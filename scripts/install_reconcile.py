#!/usr/bin/env python3
"""install_reconcile.py — 이 머신에 토큰 사용량 주기 전송(launchd)을 설치.

3시간마다 reconcile_runs.py --all --push 를 돌려, 이 머신에서 작업한 모든 프로젝트의
Claude 세션 토큰 사용량을 중앙 저장소로 보낸다(session_id로 union → 팀 전체 합산).

## 이 파일이 낸 사고

폴더를 rename 하자 plist 에 박힌 절대경로가 없는 파일을 가리키게 됐고, 잡이 **28회
연속 실패하며 토큰 수집이 4일간 죽어 있었다.** 보드는 정상으로 보였다. 사람이 우연히
발견했다.

그런데도 이 파일은 커버리지 **0%** 였다 — 사고를 낸 스크립트가 한 줄도 안 돌아간 채로
넉 달을 있었다. 그래서 여기 두 가지를 넣는다.

- **`--check`**: 설치된 plist 가 지금도 유효한지 묻는다. 파일이 있는지, 가리키는 대상이
  실재하는지, **이 체크아웃과 같은 경로인지**, 잡의 마지막 exit status 가 무엇인지.
  경로 어긋남은 조용하기 때문에 물어볼 방법 자체가 필요하다.
- **plist 를 문자열 템플릿으로 쓰지 않는다.** 경로에 `&` 나 `<` 가 하나만 있어도 XML 이
  깨지고, launchd 는 그것을 로드하지 못한 채 조용히 아무것도 안 한다. `plistlib` 이
  이스케이프를 책임진다.

전제: sync.json(endpoint+secret)이 설정돼 있어야 함
      (없으면: server.py configure-sync ... 또는 기존 sync 설정 재사용).

사용: python3 scripts/install_reconcile.py            # 설치+로드(즉시 1회 실행)
      python3 scripts/install_reconcile.py --check    # 설치된 것이 지금도 유효한가
      python3 scripts/install_reconcile.py --uninstall
"""
import argparse
import os
import plistlib
import subprocess
import sys

HOME = os.path.expanduser("~")
LABEL = "com.vibe-harness.reconcile"
PLIST = os.path.join(HOME, "Library/LaunchAgents", LABEL + ".plist")
RECONCILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "reconcile_runs.py"))
LOG = os.path.join(HOME, ".claude/skills/vibe-harness/reconcile.log")
SYNC = os.path.join(HOME, ".claude/skills/vibe-harness/sync.json")
INTERVAL = 10800  # 3h
PYTHON = "/usr/bin/python3"


def plist_dict(reconcile, log, label=LABEL, interval=INTERVAL):
    """launchd 가 읽을 잡 정의.

    `RunAtLoad` 로 설치 즉시 한 번 돌린다 — 3시간을 기다렸다가 실패를 알게 되면
    그 3시간은 조용한 공백이다.
    """
    return {
        "Label": label,
        "ProgramArguments": [PYTHON, reconcile, "--all", "--push"],
        "StartInterval": interval,
        "RunAtLoad": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def write_plist(path, body):
    """**바이너리로 쓴다.** plistlib 이 XML 이스케이프를 책임진다.

    이전에는 문자열 템플릿에 경로를 그대로 끼워 넣었다. 경로에 `&` 가 하나만 있어도
    XML 이 깨지고, launchd 는 깨진 plist 를 로드하지 못한 채 아무 말도 하지 않는다 —
    이 프로젝트가 반복해서 당해 온 '성공처럼 보이는 침묵'과 같은 형태다.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        plistlib.dump(body, fh)
    os.replace(tmp, path)


def read_plist(path):
    """설치된 잡 정의. 없거나 깨졌으면 None — 깨진 것도 없는 것과 같은 결과를 낸다."""
    try:
        with open(path, "rb") as fh:
            return plistlib.load(fh)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def installed_target(path):
    """설치된 plist 가 실제로 가리키는 스크립트 경로."""
    doc = read_plist(path)
    if not doc:
        return None
    args = doc.get("ProgramArguments") or []
    # [python, <script>, --all, --push] — 플래그가 아닌 두 번째 인자가 대상이다
    for arg in args[1:]:
        if not str(arg).startswith("-"):
            return str(arg)
    return None


def job_status(label=LABEL, runner=None):
    """`launchctl list` 가 말하는 (pid, 마지막 exit status). 못 읽으면 None.

    **2열이 마지막 exit status 다.** 28회 연속 실패가 여기 계속 적혀 있었는데
    아무도 보지 않았다.
    """
    runner = runner or subprocess.run
    try:
        done = runner(["launchctl", "list"], capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(done, "returncode", 1) != 0:
        return None
    for line in (done.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == label:
            return parts[0], parts[1]
    return None


def problems(plist=None, reconcile=None, runner=None):
    """설치된 것이 **지금도** 유효한가. 문제 목록을 돌려준다 (빈 목록이면 정상).

    경로 어긋남은 조용하다 — 잡은 등록돼 있고, 보드는 멀쩡하고, 실패는 로그에만 쌓인다.
    그래서 "물어볼 수 있는 것"을 만드는 것이 이 함수의 전부다.
    """
    plist = PLIST if plist is None else plist
    reconcile = RECONCILE if reconcile is None else reconcile
    found = []

    if not os.path.exists(plist):
        return ["잡이 설치되어 있지 않다: %s" % plist]

    if read_plist(plist) is None:
        return ["plist 를 읽을 수 없다(깨졌거나 형식이 다르다): %s\n"
                "  launchd 는 이것을 로드하지 못한 채 아무 말도 하지 않는다." % plist]

    target = installed_target(plist)
    if not target:
        found.append("plist 에 실행할 스크립트가 없다")
    else:
        if not os.path.exists(target):
            found.append("plist 가 없는 파일을 가리킨다: %s\n"
                         "  **이것이 4일간 수집을 멈춘 형태다** — 잡은 등록돼 있고 "
                         "실패만 조용히 쌓인다." % target)
        elif os.path.realpath(target) != os.path.realpath(reconcile):
            found.append("plist 가 다른 체크아웃을 가리킨다\n"
                         "  설치됨: %s\n  여기:   %s" % (target, reconcile))

    status = job_status(runner=runner)
    if status is None:
        found.append("`launchctl list` 에 %s 가 없다 — 등록은 됐지만 로드되지 않았다"
                     % LABEL)
    elif status[1] not in ("0", "-"):
        found.append("잡의 마지막 exit status 가 %s 다 (0 이어야 한다)" % status[1])
    return found


def install(plist=None, reconcile=None, log=None, runner=None):
    """설치하고 로드한다. **여러 번 돌려도 같은 결과여야 한다.**

    먼저 unload 하는 것이 멱등성의 핵심이다 — 로드된 채로 덮어쓰면 옛 정의가 계속
    살아 있고, 고쳤다고 생각한 것이 안 고쳐진다.
    """
    plist = PLIST if plist is None else plist
    reconcile = RECONCILE if reconcile is None else reconcile
    log = LOG if log is None else log
    runner = runner or subprocess.run

    if os.path.exists(plist):
        runner(["launchctl", "unload", plist], capture_output=True)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    write_plist(plist, plist_dict(reconcile, log))
    return runner(["launchctl", "load", plist], capture_output=True, text=True)


def uninstall(plist=None, runner=None):
    plist = PLIST if plist is None else plist
    runner = runner or subprocess.run
    if os.path.exists(plist):
        runner(["launchctl", "unload", plist], capture_output=True)
        os.remove(plist)
    return plist


def main(argv=None):
    ap = argparse.ArgumentParser(description="토큰 수집 주기 실행 잡 설치")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="설치된 잡이 지금도 유효한지 본다 (경로 어긋남·exit status)")
    a = ap.parse_args(argv)

    if a.check:
        found = problems()
        if not found:
            print("정상: %s" % PLIST)
            print("  대상: %s" % installed_target(PLIST))
            return 0
        print("문제 %d건:" % len(found))
        for p in found:
            print("  ✗ " + p)
        print("\n다시 설치: python3 %s" % os.path.abspath(__file__))
        return 1

    if sys.platform != "darwin":
        raise SystemExit("launchd는 macOS 전용 — 다른 OS는 cron으로 "
                         f"'*/180 * * * * {PYTHON} {RECONCILE} --all --push' 등록")

    if a.uninstall:
        print("제거됨:", uninstall())
        return 0

    if not os.path.exists(SYNC):
        print("⚠️ sync.json 없음 — 먼저 sync 설정 필요:")
        print("   VIBE_HARNESS_SYNC_SECRET=<시크릿> python3 <repo>/scripts/server.py \\")
        print("     configure-sync https://os.zest.im/api/internal/vibe-harness/sync ax-project <내프로젝트>")

    r = install()
    if getattr(r, "returncode", 1) == 0:
        print(f"설치+로드 완료: {PLIST}")
        print("  → 3시간마다 + 로드 시 1회: reconcile_runs.py --all --push")
        print(f"  로그: {LOG}")
        print(f"  확인: python3 {os.path.abspath(__file__)} --check")
        return 0
    print("launchctl load 실패:", (r.stderr or "").strip())
    return 1


if __name__ == "__main__":
    sys.exit(main())
