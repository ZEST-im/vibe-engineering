#!/usr/bin/env python3
"""vibe-harness-worktree-guard.py — 한 워킹트리를 여러 세션이 공유하는 것을 감지한다.

## 무엇이 실제로 났던 사고인가

병렬 세션이 한 워킹트리를 공유한다. 세션 A 가 `git add -A` 로 담을 때, 그 트리에는
세션 B 가 만들던 파일이 함께 있다. **그렇게 사내 수치가 공개 레포로 올라갔다.**
Codex 앱까지 같은 트리를 보면서 하루 세 번 부딪혔는데, 3주 동안 규칙도 감지도 없었다.

## 왜 감지만 하는가

**잠글 수 없다는 것이 아무것도 안 해도 된다는 뜻은 아니다.** 반대로, 막는 것은 답이
아니다 — 오탐 한 번에 작업이 멈추면 그 검사는 곧 꺼지고, 꺼진 검사는 없는 것보다
나쁘다(있다고 믿게 만든다). 그래서 말하고 비켜선다. 종료 코드는 언제나 0 이다.

## 세 신호와 각 신호가 실제로 증명하는 것

주장을 증거보다 세게 하지 않는 것이 이 파일의 규율이다. "다른 세션이 작업 중이다"는
대개 **증명할 수 없다** — 세션 등록부 없이는 누구의 변경인지 알 방법이 없다.
증명할 수 있는 것만 말한다.

| 신호 | 확실히 말할 수 있는 것 |
|---|---|
| `.git/index.lock` 존재 | **지금** 다른 git 프로세스가 이 저장소에서 돌고 있다 |
| 최근 N분 내 바뀐 미커밋 파일 | 방금 무언가가 이 트리에 썼다. 이 세션은 아니다 |
| 미커밋 변경 | 무언가 이 트리에 쓰다 말았다 |

셋째가 밋밋해 보여도 그것이 정확히 사고의 재료다. **세션 시작 시점이라면** 그 변경은
정의상 이 세션의 것이 아니다 — 이전의 나든 지금 도는 다른 세션이든. `git add -A` 는
둘을 구별하지 않는다.

그 "세션 시작 시점이라면"이 `--session-start` 다. 훅이 부를 때만 붙는다. 손으로 돌릴
때는 방금 내가 만든 변경일 수 있으므로 소유권을 주장하지 않는다 — **말할 수 있는 것만
말한다**는 것이 신호를 셋으로 나눈 이유와 같다.

## 자기가 감지하려는 것을 자기가 만들지 않는다

`git status` 는 인덱스를 갱신하면서 `.git/index.lock` 을 잡을 수 있다. 그러면 이
검사가 자기 잠금을 자기가 보게 된다. `--no-optional-locks` 로 막는다.

    python3 vibe-harness-worktree-guard.py [경로] [--session-start]
"""
import os
import subprocess
import sys
import time


# 이 시간 안에 바뀌었으면 "방금"이라고 부른다.
# 짧으면 놓치고, 길면 어제 하던 내 작업까지 "방금"이 된다. 세션 하나가 생각하는
# 사이의 공백보다는 길고, 자리를 비웠다 돌아오는 간격보다는 짧게 잡는다.
ACTIVE_MINUTES = 10

# 몇 개까지 이름을 대는가. 전부 늘어놓으면 경고가 스크롤이 되고, 스크롤은 안 읽힌다.
LIST_LIMIT = 5


def _git(repo, *args):
    """읽기 전용 git. 인덱스를 갱신하지 않는다 — 갱신하면 스스로 잠금을 만든다."""
    try:
        done = subprocess.run(
            ["git", "--no-optional-locks", "-C", repo, *args],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def toplevel(start):
    out = _git(start, "rev-parse", "--show-toplevel")
    return out.strip() if out else None


def dirty_paths(repo):
    """미커밋 경로. 추적/미추적을 가리지 않는다 — `add -A` 도 가리지 않기 때문이다.

    `-z` 로 읽는다. 공백이나 개행이 든 경로를 줄 단위로 자르면 조용히 빠진다.
    """
    out = _git(repo, "status", "--porcelain", "-z")
    if not out:
        return []
    paths = []
    for entry in out.split("\0"):
        if len(entry) > 3:
            # "XY path" — 이름이 바뀐 경우 원본 경로가 뒤따르지만 그건 별도 항목으로 온다
            paths.append(entry[3:])
    return paths


def survey(start, now=None, active_minutes=ACTIVE_MINUTES):
    """이 워킹트리가 공유되고 있다는 증거를 모은다. 판단은 하지 않는다."""
    repo = toplevel(start)
    if not repo:
        return None
    now = time.time() if now is None else now
    cutoff = now - active_minutes * 60

    paths = dirty_paths(repo)
    recent = []
    for p in paths:
        full = os.path.join(repo, p)
        try:
            if os.stat(full).st_mtime >= cutoff:
                recent.append(p)
        except OSError:
            # 지워진 파일은 mtime 이 없다. 없는 것을 최근으로도 오래된 것으로도 세지 않는다.
            continue
    return {
        "repo": repo,
        "git_lock": os.path.exists(os.path.join(repo, ".git", "index.lock")),
        "dirty": paths,
        "recent": recent,
        "active_minutes": active_minutes,
    }


def _names(paths):
    shown = ", ".join(paths[:LIST_LIMIT])
    if len(paths) > LIST_LIMIT:
        shown += " 외 %d건" % (len(paths) - LIST_LIMIT)
    return shown


def message(found, session_start=False):
    """경고문. 할 말이 없으면 None — 깨끗한 트리에 말을 걸면 다음번에 안 읽힌다.

    `session_start` 일 때만 "이 세션이 만든 것이 아니다"라고 말한다. 그때는 참이고,
    다른 때는 아니다.
    """
    if not found or (not found["dirty"] and not found["git_lock"]):
        return None
    whose = " — 이 세션이 만든 것이 아닙니다" if session_start else ""

    lines = []
    if found["git_lock"]:
        lines.append("  🔴 다른 git 프로세스가 지금 이 저장소에서 돌고 있습니다 "
                     "(.git/index.lock)")
    if found["recent"]:
        lines.append("  🟡 %d분 안에 바뀐 미커밋 파일 %d건%s"
                     % (found["active_minutes"], len(found["recent"]), whose))
        lines.append("     " + _names(found["recent"]))
    elif found["dirty"]:
        lines.append("  ⚠ 미커밋 변경 %d건%s" % (len(found["dirty"]), whose))
        lines.append("     " + _names(found["dirty"]))

    if found["dirty"]:
        # 사고는 "누구 것인지 몰라서"가 아니라 "전부 담아서" 났다.
        lines.append("     담을 때 `git add -A` 대신 경로를 지정하세요 — "
                     "남의 작업이 같이 올라갑니다")
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    session_start = "--session-start" in argv
    rest = [a for a in argv if not a.startswith("--")]
    start = rest[0] if rest else os.getcwd()
    try:
        text = message(survey(start), session_start)
    except Exception:
        # 세션 시작을 막지 않는다. 이 검사가 죽는 것은 이 검사만의 문제다.
        return 0
    if text:
        print("")
        print(text)
        print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
