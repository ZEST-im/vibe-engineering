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
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import venv


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "tests.yml")
VENV = os.path.join(ROOT, ".check-venv")

PIN = re.compile(r"pip install\s+([a-z0-9_-]+)==([0-9][0-9a-zA-Z.]*)")
FLOOR = re.compile(r"--fail-under=(\d+)")
RUNS_ON = re.compile(r"runs-on:\s*(\S+)")
MATRIX = re.compile(r"python-version:\s*\[([^\]]+)\]")
VERSION = re.compile(r"[\"']([0-9]+\.[0-9]+)[\"']")


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


def ci_environment():
    """CI 가 실제로 도는 환경. **여기에 적지 않고 워크플로에서 읽는다.**

    핀 버전과 같은 이유다 — 두 곳에 적으면 갈라지고, 갈라진 유보 문구는 유보가 아니라
    거짓말이 된다. 매트릭스가 늘었는데 이 목록이 그대로면 "확인 못 한 것"이 실제보다
    적게 나온다.
    """
    with open(WORKFLOW, encoding="utf-8") as fh:
        body = fh.read()
    versions = sorted({v for block in MATRIX.findall(body)
                       for v in VERSION.findall(block)})
    runners = sorted(set(RUNS_ON.findall(body)))
    return versions, runners


def unverified_here(clone=None):
    """이 실행이 **확인하지 못한 것**. 통과했을 때도 말한다.

    없앨 수 없는 차이다 — 한 머신에서 파이썬 셋을 돌릴 수도, 러너의 git 설정을 가져올
    수도 없다. 없앨 수 없으면 **매번 말하게 한다.** 유보를 실패할 때만 보여주면
    정작 초록일 때 못 보는데, 사고는 초록일 때 난다.

    실제로 그랬다: 다른 머신의 정렬을 확인하는 데 초록 다섯 개가 아무 도움이 안 됐고,
    사람에게 물어서야 알아냈다. 그때 이 검사는 한마디도 하지 않았다.
    """
    notes = []
    try:
        versions, runners = ci_environment()
    except (OSError, ValueError):
        versions, runners = [], []

    local_py = "%d.%d" % sys.version_info[:2]
    others = [v for v in versions if v != local_py]
    if others:
        notes.append("파이썬 %s — 여기서는 %s 하나만 돌았다"
                     % ("·".join(others), local_py))
    if versions and local_py not in versions:
        notes.append("반대로 %s 는 CI 가 보지 않는다 — 여기서만 통과한 것이 있을 수 있다"
                     % local_py)

    here = platform.system().lower()
    if runners and not any(here[:3] in r.lower() for r in runners):
        notes.append("%s — 여기는 %s (경로·줄바꿈·로케일이 다르다)"
                     % ("·".join(sorted(set(runners))), platform.system()))

    dirty = subprocess.run(["git", "--no-optional-locks", "-C", ROOT,
                            "status", "--porcelain"],
                           capture_output=True, text=True)
    n = len([ln for ln in dirty.stdout.splitlines() if ln.strip()])
    if n:
        notes.append("커밋되지 않은 변경 %d건 — **CI 는 커밋된 트리만 본다.** "
                     "지금 통과한 것과 푸시될 것이 같지 않다" % n)

    if os.path.isdir(os.path.join(ROOT, "private")):
        notes.append("`private/` 는 CI 에 없다 — `private-free` 단계가 그 환경을 재현한다 (--fast 에서는 건너뛴다)")

    if clone and clone[0] != "aligned":
        notes.append("클론 상태가 `%s` 다. 통과는 '갈라지지 않았다'까지만 말한다"
                     % clone[0])
    return notes


GUARD = os.path.join(ROOT, "scripts", "hooks", "vibe-harness-worktree-guard.py")


def _guard_module():
    """워킹트리 가드를 모듈로 읽는다. 파일명에 하이픈이 있어 import 가 안 된다.

    없거나 깨져 있으면 None — 이 검사가 없다고 다른 검사를 막지 않는다.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("vh_guard_for_check", GUARD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def upstream_conflict(repo=None):
    """커밋 직전 충돌 신호. **깨끗한 트리에서는 네트워크를 타지 않는다.**

    이 파일에는 `clone_state()` 가 "네트워크는 건드리지 않는다" 는 규칙과 함께 있다.
    그 규칙과 정확성이 부딪히는데, 부딪히는 구간이 생각보다 좁다 — **들고 있는 파일이
    없으면 무엇과도 겹칠 수 없다.** 그러니 fetch 는 답을 바꿀 수 있을 때만 한다.

    `clone_state()` 는 여전히 받아둔 ref 로만 본다. 저기서 보는 것(재작성·분기)은
    fetch 없이도 판단할 수 있고, 여기서 보는 것(내 파일이 그 파일인가)은 아니다.
    """
    repo = repo or ROOT
    guard = _guard_module()
    if guard is None:
        return None

    holding = guard.dirty_paths(repo, untracked_all=True)
    found = guard.upstream_overlap(repo, fetch=bool(holding))
    if found is not None:
        found["fetched"] = bool(holding) and not found["fetch_failed"]
    return found


def conflict_fails_gate(found):
    """겹침만 막는다.

    앞선 것만으로 멈추면 오탐이 잦아지고, 잦은 오탐은 검사를 끄게 만든다.
    fetch 실패도 막지 않는다 — **모른다는 것은 겹친다는 것이 아니다.**
    """
    return bool(found and found["overlap"])


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


def _bytecode_caches():
    """`scripts/`·`tests/` 아래의 `__pycache__`. venv 안은 건드리지 않는다."""
    found = []
    for top in ("scripts", "tests"):
        base = os.path.join(ROOT, top)
        for dirpath, dirnames, _files in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != ".check-venv"]
            if os.path.basename(dirpath) == "__pycache__":
                found.append(dirpath)
    return found


# 복사에서 빼는 것. `private/` 는 **CI 에 없어서** 빼고, 나머지는 무겁거나 상태를
# 옮겨서 뺀다 — 특히 `__pycache__` 는 낡은 .pyc 로 주입 검증을 오염시킨다.
#
# **`.git` 은 빼지 않는다.** 처음에 뺐다가 오탐 22건을 봤다 — 이 스위트는 git 을
# 데이터 소스로 쓴다(검사 범위를 `git ls-files` 에 묻고, 추적 여부로 배포 목록을
# 검증한다). 7.2MB / 0.3초라 아낄 것도 없었다.
PRIVATE_FREE_SKIP = ("private", ".check-venv", "__pycache__",
                     ".pytest_cache", "htmlcov", "node_modules", ".coverage")


def copy_without_private(root=ROOT, dest=None):
    """워킹트리를 `private/` 없이 복사한다. 복사본 경로를 돌려준다."""
    dest = dest or tempfile.mkdtemp(prefix="vh-nopriv-")
    shutil.copytree(root, dest, symlinks=True, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*PRIVATE_FREE_SKIP))
    return dest


def private_free_tests(root=ROOT, python=None, verbose=False):
    """`private/` 없는 사본에서 스위트를 돌린다. `(ran, ok)`.

    **왜 사본인가.** 로컬에는 `private/` 가 늘 있어서 평소 실행은 CI 환경이 아니다.
    2026-09-11 에 그 차이로 CI 3버전이 전부 깨졌고, 로컬은 초록이었다. 이 파일은 그
    사실을 **유보로 출력만 하고 있었다** — 알고도 막지 않은 것이다.

    **왜 가드를 세지 않는가.** 정적으로 `skipTest` 를 찾는 방법도 있었지만 이 레포에
    이미 세 관용구가 쓰인다(`skipTest`·`@skipUnless`·부재 시 빈 값 헬퍼). 네 번째가
    나오면 조용히 뚫린다. 대리 지표 대신 성질을 본다 — `private/` 없이도 초록인가.

    `private/` 가 없으면 **돌지 않는다.** 그땐 평소 실행이 이미 그 환경이다.
    """
    if not os.path.isdir(os.path.join(root, "private")):
        return False, True
    tmp = tempfile.mkdtemp(prefix="vh-nopriv-")
    try:
        dest = copy_without_private(root, os.path.join(tmp, "tree"))
        done = subprocess.run(
            [python or sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            cwd=dest, capture_output=True, text=True)
        if done.returncode != 0 and verbose:
            print((done.stderr or done.stdout).rstrip()[-4000:])
        return True, done.returncode == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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

    # **낡은 바이트코드가 주입 검증을 오염시킨다.**
    #
    # `cp backup.py live.py` 로 파일을 되돌리면 내용은 옛것인데 **mtime 도 옛것**이라
    # `.pyc` 가 여전히 유효해 보인다. 그러면 주입된 버전이 계속 로드되고, 복구했는데
    # 테스트가 실패한다 — 원인을 코드에서 찾다 30분을 버렸다(2026-09-08).
    #
    # 위반 주입은 이 레포의 채택 기준이므로 그 절차를 오염시키는 것은 검사 자체의 결함이다.
    for cache in _bytecode_caches():
        shutil.rmtree(cache, ignore_errors=True)

    # 코드가 멀쩡하고 클론이 갈라지지 않았어도, **내가 들고 있는 파일이 하필 원격이
    # 건드린 파일이면** 지금 커밋하는 것이 손으로 풀 일을 만든다. 2026-09-08 하루에
    # 두 번 그랬다.
    conflict = upstream_conflict()
    conflict_bad = conflict_fails_gate(conflict)
    guard = _guard_module()
    conflict_text = guard.overlap_message(conflict) if guard else None
    if conflict_text:
        print(f"\n── 원격과의 충돌\n   {'FAIL' if conflict_bad else 'PASS'}")
        print(conflict_text)
    else:
        print("\n── 원격과의 충돌\n   PASS  겹치는 파일 없음")

    results = [("clone", not bad_state), ("conflict", not conflict_bad)]
    results.append(("compileall",
                    run("컴파일", [sys.executable, "-m", "compileall", "-q",
                                 "scripts", "tests"])))
    results.append(("tests",
                    run("테스트", [sys.executable, "-m", "unittest", "discover",
                                "-s", "tests"])))

    if a.fast:
        print("\n  --fast: 린트·커버리지와 `private/` 없는 재실행을 건너뛰었다. "
              "**이 상태로 푸시하지 말 것** — CI 의 절반만 본 것이다.")
    else:
        # 로컬에는 있고 CI 에는 없는 것이 초록을 갈라놓는다. 여기서만 도는 단계다 —
        # CI 는 이미 이 환경이라 저기서 또 돌 이유가 없다.
        print("\n── private/ 없는 환경")
        ran, nopriv_ok = private_free_tests(verbose=True)
        if ran:
            print(f"   {'PASS' if nopriv_ok else 'FAIL'}  (사본에서 스위트 재실행)")
            results.append(("private-free", nopriv_ok))
        else:
            print("   SKIP  private/ 가 없다 — 평소 실행이 이미 그 환경이다")

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

    # 통과했을 때도 낸다. 유보를 실패할 때만 보여주면 정작 초록일 때 못 보는데,
    # 사고는 초록일 때 난다.
    notes = unverified_here((state, detail))
    if notes:
        print("\n  여기서 확인하지 못한 것")
        for n in notes:
            print(f"    · {n}")

    if failed:
        print(f"\n실패: {', '.join(failed)} — 푸시하지 말 것")
        return 1
    print("\n전부 통과 — 위 유보를 뺀 범위에서. 푸시 후에는 **그 커밋의** 실행을 확인한다:")
    print("  gh run list --limit 5 --json headSha,conclusion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
