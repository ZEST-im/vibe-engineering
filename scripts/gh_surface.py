#!/usr/bin/env python3
"""gh_surface.py — 칸반을 정본으로 두고 GitHub 을 공개 표면으로 쓴다.

## 순수 파생과 네트워크를 가른다

`PHASES.md` → 릴리스 노트, `kanban.json` → 승격 대상은 **입력만 있으면 정해진다.**
그 층은 파일도 네트워크도 건드리지 않아 고정 입력으로 검사할 수 있다.
`gh` 를 부르는 층은 얇게 두고 가용성 게이트 뒤에 둔다 — CI 에는 인증이 없다.

## 외부 행위는 dry-run 이 기본이다

이슈·릴리스·프로젝트는 **만들면 남는다.** `--apply` 가 없으면 무엇을 할지 출력만 한다.
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DONE_PHASE = re.compile(r"^##\s+(PHASE_\w+)\s+✅\s*DONE\s*\(([0-9-]+)\)\s*$", re.M)


def phase_sections(body):
    """`PHASES.md` 본문에서 완료 Phase 절을 뽑는다. **파일이 아니라 텍스트를 받는다.**"""
    out = {}
    hits = list(DONE_PHASE.finditer(body or ""))
    for i, m in enumerate(hits):
        start = m.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        section = body[start:end]
        title = ""
        for line in section.splitlines():
            if line.startswith("> "):
                title = line[2:].strip()
                break
        out[m.group(1)] = {
            "title": title,
            "date": m.group(2),
            "body": section.strip(),
        }
    return out


def release_notes(body, phase):
    """한 Phase 의 릴리스 노트. 없으면 **`None`** — 빈 문자열이면 빈 릴리스가 생긴다."""
    sec = phase_sections(body).get(phase)
    if sec is None:
        return None
    head = f"## {sec['title']}" if sec["title"] else f"## {phase}"
    return f"{head}\n\n{sec['body']}\n"


# 그 Phase 를 **주어로** 완료를 선언한 표현. 인계·개시 언급과 구별한다.
_CLOSING = ("완료", "종료", "마무리", "완결")
# 이 말이 Phase 이름 **앞이나 뒤** 가까이 있으면 그 Phase 의 경계가 아니다 (인계·개시).
# 예: "PMF14 개시 + PMF13 마무리 뒤" — "개시" 는 PMF13 보다 앞에 있지만 이 커밋을
# "다음 Phase 를 열며 지난 Phase 마무리를 언급"으로 만든다. 뒤쪽 근접("PMF11 이전
# 완료")도 같은 이유로 걸러야 해서 앞·뒤 창을 모두 본다.
_NOT_CLOSING = ("개시", "넘긴다", "넘김", "이전", "선행")

_WINDOW = 12


def boundary_candidates(log_lines, phase):
    """`<sha> <date> <subject>` 줄에서 그 Phase 의 경계 후보를 고른다.

    **추측하지 않는다.** 후보가 없으면 빈 목록이고, 그때는 태깅하지 않는다.
    """
    out = []
    pat = re.compile(r"(?<![A-Z0-9])" + re.escape(phase) + r"(?![0-9])")
    for line in log_lines:
        parts = line.split(" ", 2)
        if len(parts) < 3:
            continue
        sha, date, subject = parts
        m = pat.search(subject)
        if not m:
            continue
        before = subject[max(0, m.start() - _WINDOW):m.start()]
        after = subject[m.end():m.end() + _WINDOW]
        strong = (any(w in after for w in _CLOSING)
                  and not any(w in before for w in _NOT_CLOSING)
                  and not any(w in after for w in _NOT_CLOSING))
        out.append({"sha": sha, "date": date, "subject": subject,
                    "confidence": "strong" if strong else "weak"})
    out.sort(key=lambda c: 0 if c["confidence"] == "strong" else 1)
    return out


def tag_plan(phases_body, log_lines):
    """무엇을 태깅할지. **못 그은 것도 이유와 함께 목록에 남긴다.**"""
    plan = []
    for phase, _sec in sorted(phase_sections(phases_body).items()):
        short = phase.replace("PHASE_", "")
        cands = [c for c in boundary_candidates(log_lines, short)
                 if c["confidence"] == "strong"]
        top = cands[0] if cands else None
        plan.append({
            "phase": phase,
            "tag": f"phase/{short}",
            "sha": top["sha"] if top else None,
            "notes": release_notes(phases_body, phase) if top else None,
            "skipped_reason": None if top else "완료를 선언한 커밋이 없다 — 추측하지 않는다",
        })
    return plan


def _run(argv):
    done = subprocess.run(argv, capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def gh_available(runner=None, need_scope=None):
    """`gh` 를 쓸 수 있는가. **없다고 실패시키지 않는다 — 이유를 돌려준다.**"""
    runner = runner or _run
    try:
        code, out, err = runner(["gh", "auth", "status"])
    except FileNotFoundError:
        return False, "gh 가 설치돼 있지 않다 — GitHub 표면 작업을 건너뛴다"
    except OSError as exc:
        return False, f"gh 를 실행할 수 없다 ({exc}) — 건너뛴다"
    if code != 0:
        return False, f"gh 인증이 없다 — `gh auth login` 이 필요하다 ({err.strip()[:80]})"
    if need_scope and f"'{need_scope}'" not in out:
        return False, (f"토큰에 `{need_scope}` 스코프가 없다 — "
                       f"`gh auth refresh -s {need_scope}` 로 추가한다")
    return True, "gh 사용 가능" + (f" ({need_scope} 스코프 확인됨)" if need_scope else "")


def _log_lines(root, runner=None):
    """`git log` 를 읽어 `tag_plan` 이 먹을 줄 목록으로 만든다.

    **CLI 층의 일이다** — `tag_plan` 은 파일도 git 도 건드리지 않는다(순수 유지).
    로그를 못 읽으면(레포가 아니거나 git 이 없으면) 빈 목록을 돌려준다 — 경계를
    지어내지 않는다는 원칙은 여기서도 같다: 후보가 없으면 그냥 없는 것이다.
    """
    runner = runner or _run
    try:
        code, out, _err = runner(
            ["git", "-C", root, "log", "--format=%h %ad %s", "--date=short"])
    except OSError:
        return []
    if code != 0:
        return []
    return [line for line in out.splitlines() if line.strip()]


def _run_tag(plan, root, apply=False, gh_check=None, gh_runner=None):
    """계획을 출력하고, `apply` 일 때만 실제로 태그·릴리스를 만든다.

    `gh_check`/`gh_runner` 는 테스트 주입용 — 기본은 각각 `gh_available`, `_run`.
    """
    gh_check = gh_check or gh_available
    gh_runner = gh_runner or _run

    taggable = [p for p in plan if p["sha"]]
    skipped = [p for p in plan if not p["sha"]]

    for p in plan:
        if p["sha"]:
            print(f"{p['tag']}  {p['sha']}  ({p['phase']})")
        else:
            print(f"{p['phase']}: 보류 — {p['skipped_reason']}")
    print(f"\n{len(plan)}개 Phase 중 {len(taggable)}개 태그 가능, {len(skipped)}개 보류")

    if not apply:
        print("[dry-run] 아무것도 만들지 않았다 — 실행하려면 --apply")
        return 0

    ok, why = gh_check()
    if not ok:
        print(f"\n{why}")
        return 1

    created = existed = failed = 0
    for p in taggable:
        code, out, _err = _run(["git", "-C", root, "tag", "-l", p["tag"]])
        if code == 0 and out.strip() == p["tag"]:
            print(f"{p['tag']}: 이미 있다 — 건너뛴다")
            existed += 1
            continue

        message = f"{p['tag']}\n\n{p['notes']}"
        code, _out, err = _run(
            ["git", "-C", root, "tag", "-a", p["tag"], p["sha"], "-m", message])
        if code != 0:
            print(f"{p['tag']}: 태그 생성 실패 ({err.strip()[:120]})")
            failed += 1
            continue

        code, _out, err = gh_runner(
            ["gh", "release", "create", p["tag"], "--target", p["sha"],
             "--title", p["tag"], "--notes", p["notes"]])
        if code != 0:
            print(f"{p['tag']}: 릴리스 생성 실패 ({err.strip()[:120]})")
            failed += 1
            continue

        print(f"{p['tag']}: 태그 + 릴리스 생성 완료")
        created += 1

    print(f"\n생성 {created}, 이미 있음 {existed}, 실패 {failed}")
    return 0 if failed == 0 else 1


def main(argv=None, root=None):
    """`gh_surface.py tag` — 기본은 dry-run.

    `root` 는 테스트가 임시 레포를 주입하기 위한 자리다. 기본은 이 파일이
    있는 레포의 루트(`ROOT`) — `private/PHASES.md` 도 그 기준으로 찾는다.
    """
    ap = argparse.ArgumentParser(description="GitHub 표면 — 칸반이 정본이다")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tag", help="Phase 를 태그·릴리스로. 기본은 dry-run")
    t.add_argument("--phases", default=None, help="PHASES.md 경로 (기본: private/PHASES.md)")
    t.add_argument("--apply", action="store_true",
                   help="실제로 만든다. 없으면 무엇을 할지 출력만 한다")
    a = ap.parse_args(argv)

    base = root or ROOT
    phases_path = a.phases or os.path.join(base, "private", "PHASES.md")
    if not os.path.exists(phases_path):
        raise SystemExit(
            f"PHASES.md 를 찾지 못했다: {phases_path}\n"
            "  private/ 는 gitignore 대상이라 이 파일이 없는 환경일 수 있다 — "
            "추측해서 빈 계획으로 진행하지 않고 멈춘다.")
    with open(phases_path, encoding="utf-8") as fh:
        phases_body = fh.read()

    plan = tag_plan(phases_body, _log_lines(base))
    return _run_tag(plan, base, apply=a.apply)


if __name__ == "__main__":
    sys.exit(main())
