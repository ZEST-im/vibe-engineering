#!/usr/bin/env python3
"""check.py — 푸시 전에 CI 가 하는 것을 전부 한 번에 돌린다.

## 왜 필요한가

CI 는 세 갈래다 — 테스트(3버전), 린트, 커버리지. 로컬에서는 그중 하나만 돌리기 쉽고,
실제로 그랬다: ruff 가 로컬에 없어서 "전체 테스트 OK" 가 CI 의 절반만 본 것이었고,
**네 커밋이 빨간 채로 들어갔다.** 거기에 푸시 후 `gh run list` 맨 위(이전 커밋)를 초록으로
읽는 실수가 겹쳤다.

따로 기억해야 하는 검사는 결국 하나씩 빠진다. 그래서 진입점을 하나로 만든다.

## 버전을 여기에 적지 않는다

`ruff==…`, `coverage==…`, `--fail-under=…` 는 **워크플로에서 읽어온다.** 여기에 다시 적으면
두 곳이 갈라지고, 갈라진 순간 "로컬은 통과하는데 CI 는 실패"가 된다 — 이 레포는 같은
종류의 드리프트(설치 파일 목록이 세 곳에 흩어짐)를 이미 한 번 겪었다.

워크플로를 못 읽으면 **추측하지 않고 멈춘다.** 잘못된 버전으로 통과시키는 것보다
안 도는 게 낫다.

    python3 scripts/check.py            # 전부
    python3 scripts/check.py --fast     # 린트·커버리지 없이 테스트만
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import venv


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "tests.yml")
VENV = os.path.join(ROOT, ".check-venv")

PIN = re.compile(r"pip install\s+([a-z0-9_-]+)==([0-9][0-9a-zA-Z.]*)")
FLOOR = re.compile(r"--fail-under=(\d+)")


def ci_pins():
    """워크플로가 고정한 도구 버전과 커버리지 하한.

    여기서 읽는 이유는 하나다 — 두 곳에 적으면 갈라지기 때문이다.
    """
    if not os.path.exists(WORKFLOW):
        raise SystemExit(
            f"워크플로를 찾지 못했다: {WORKFLOW}\n"
            "  버전을 추측해서 돌리면 '로컬은 통과, CI 는 실패'가 된다. 멈춘다.")
    with open(WORKFLOW, encoding="utf-8") as fh:
        body = fh.read()
    tools = dict(PIN.findall(body))
    floor = FLOOR.search(body)
    missing = [t for t in ("ruff", "coverage") if t not in tools]
    if missing:
        raise SystemExit(
            "워크플로에서 고정 버전을 못 읽었다: " + ", ".join(missing) + "\n"
            "  `pip install <도구>==<버전>` 형식이 바뀌었는지 확인한다.")
    return tools, int(floor.group(1)) if floor else None


def clone_state():
    """이 클론이 원격과 어떤 관계인지. **분기의 종류까지** 가른다.

    갈라졌을 때 대응이 두 가지고 서로 반대다.

    - **재작성** (force-push): `reset --hard` 다. 여기서 `pull` 하면 머지 커밋이 생기면서
      원격이 지운 것이 되돌아온다. 실제로 그럴 뻔했다 — 공개 레포에서 스크럽한 제3자
      실명이 되살아날 상황이었다.
    - **진짜 분기**: 양쪽에 서로 없는 작업이 있다. 머지하거나 리베이스한다.

    구별법은 간단하다. 로컬에만 있는 커밋의 **메시지가 전부 원격에도 있으면** 같은 작업이
    다른 SHA 로 올라간 것이다 — 재작성이다.

    네트워크는 건드리지 않는다. fetch 는 `ss` 의 일이고, 여기서 또 하면 느리고 오프라인에서
    막힌다. 이미 가져온 ref 로만 판단한다.
    """
    def git(*args):
        done = subprocess.run(["git", "-C", ROOT, *args],
                              capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else None

    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not upstream:
        return "no-upstream", "추적 브랜치가 없다 — 분기 판단 생략"

    counts = git("rev-list", "--left-right", "--count", "HEAD...@{u}")
    if not counts:
        return "unknown", "ahead/behind 를 읽지 못했다"
    ahead, behind = (int(n) for n in counts.split())
    if not ahead and not behind:
        return "aligned", f"{upstream} 와 일치"
    if not ahead:
        return "behind", f"{behind}커밋 뒤처짐 — pull 하면 된다"
    if not behind:
        return "ahead", f"{ahead}커밋 앞섬 — 푸시하면 된다"

    ours = set((git("log", "--format=%s", "HEAD", "^@{u}") or "").splitlines())
    theirs = set((git("log", "--format=%s", "@{u}", "^HEAD") or "").splitlines())
    if ours and ours <= theirs:
        return "rewritten", (
            f"ahead {ahead} / behind {behind} — **히스토리 재작성으로 보인다.** "
            f"로컬 {len(ours)}개가 전부 원격에 같은 메시지로 있다.\n"
            "     `pull` 하지 말 것 — 머지 커밋이 생기면서 원격이 지운 것이 되돌아온다.\n"
            "     내용을 확인한 뒤 `git reset --hard @{u}` 다.")
    return "diverged", (
        f"ahead {ahead} / behind {behind} — 양쪽에 서로 없는 작업이 있다. "
        "머지하거나 리베이스한다")


def venv_python(path=VENV):
    sub = "Scripts" if os.name == "nt" else "bin"
    return os.path.join(path, sub, "python")


def ensure_venv(tools):
    """도구용 venv. 버전이 맞으면 그대로 쓰고, 다르면 다시 만든다."""
    stamp = os.path.join(VENV, ".pins")
    want = "\n".join(f"{k}=={v}" for k, v in sorted(tools.items()))
    if os.path.exists(stamp):
        with open(stamp, encoding="utf-8") as fh:
            if fh.read() == want and os.path.exists(venv_python()):
                return venv_python()
        shutil.rmtree(VENV, ignore_errors=True)
    print(f"  도구 준비 중 ({want.replace(chr(10), ', ')}) …")
    venv.EnvBuilder(with_pip=True, clear=True).create(VENV)
    subprocess.run([venv_python(), "-m", "pip", "install", "-q",
                    *[f"{k}=={v}" for k, v in sorted(tools.items())]], check=True)
    with open(stamp, "w", encoding="utf-8") as fh:
        fh.write(want)
    return venv_python()


def run(label, argv, cwd=ROOT):
    print(f"\n── {label}")
    done = subprocess.run(argv, cwd=cwd)
    ok = done.returncode == 0
    print(f"   {'PASS' if ok else 'FAIL'}  ({' '.join(os.path.basename(a) for a in argv[:2])})")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI 가 하는 검사를 로컬에서 한 번에")
    ap.add_argument("--fast", action="store_true",
                    help="테스트만. 린트·커버리지는 건너뛴다 (푸시 전에는 쓰지 말 것)")
    a = ap.parse_args(argv)

    # 코드가 멀쩡해도 클론이 갈라져 있으면 푸시가 사고가 된다. 먼저 본다.
    state, detail = clone_state()
    bad_state = state in ("rewritten", "diverged")
    print(f"\n── 클론 상태\n   {'FAIL' if bad_state else 'PASS'}  {state}: {detail}")

    results = [("clone", not bad_state)]
    results.append(("compileall",
                    run("컴파일", [sys.executable, "-m", "compileall", "-q",
                                 "scripts", "tests"])))
    results.append(("tests",
                    run("테스트", [sys.executable, "-m", "unittest", "discover",
                                "-s", "tests"])))

    if a.fast:
        print("\n  --fast: 린트·커버리지를 건너뛰었다. **이 상태로 푸시하지 말 것** — "
              "CI 의 절반만 본 것이다.")
    else:
        tools, floor = ci_pins()
        py = ensure_venv(tools)
        results.append(("ruff", run("린트", [py, "-m", "ruff", "check", "scripts", "tests"])))
        cov_ok = run("커버리지", [py, "-m", "coverage", "run", "--source=scripts",
                                "-m", "unittest", "discover", "-s", "tests"])
        if cov_ok:
            args = [py, "-m", "coverage", "report", "--sort=cover"]
            if floor is not None:
                args.append(f"--fail-under={floor}")
            cov_ok = run(f"커버리지 하한 {floor}%" if floor else "커버리지", args)
        results.append(("coverage", cov_ok))

    failed = [name for name, ok in results if not ok]
    print("\n" + "─" * 46)
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'}  {name}")
    if failed:
        print(f"\n실패: {', '.join(failed)} — 푸시하지 말 것")
        return 1
    print("\n전부 통과. 푸시 후에는 **그 커밋의** 실행을 확인한다:")
    print("  gh run list --limit 5 --json headSha,conclusion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
