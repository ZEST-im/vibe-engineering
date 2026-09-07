"""푸시 전 검사 진입점이 CI 와 갈라지지 않게 한다.

CI 는 세 갈래다 — 테스트(3버전), 린트, 커버리지. 로컬에서는 하나만 돌리기 쉽고 실제로
그랬다: ruff 가 없어서 "전체 테스트 OK" 가 절반만 본 것이었고 **네 커밋이 빨간 채로
들어갔다.** 따로 기억해야 하는 검사는 결국 하나씩 빠진다.

`scripts/check.py` 가 진입점인데, 여기에 새 위험이 하나 생긴다 — **로컬 검사기가 자기
버전을 들면 CI 와 갈라진다.** 그러면 "로컬은 통과하는데 CI 는 실패"가 되고, 그건 검사가
없는 것보다 나쁘다. 없으면 최소한 안 봤다는 걸 안다.

그래서 이 파일이 지키는 것은 하나다: **버전은 워크플로 한 곳에만 있다.**
이 레포는 같은 종류의 드리프트(설치 파일 목록이 세 곳에 흩어짐)를 이미 겪었다.
"""
import ast
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "tests.yml")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("check_mod", os.path.join(SCRIPTS, "check.py"))
check = importlib.util.module_from_spec(_spec)
sys.modules["check_mod"] = check
_spec.loader.exec_module(check)


def workflow_text():
    with open(WORKFLOW, encoding="utf-8") as fh:
        return fh.read()


class VersionsComeFromTheWorkflowTest(unittest.TestCase):
    def test_reads_the_pins_ci_actually_uses(self):
        tools, floor = check.ci_pins()
        body = workflow_text()
        for name, version in tools.items():
            self.assertIn(f"{name}=={version}", body)
        self.assertIsNotNone(floor, "커버리지 하한을 못 읽었다")

    def test_check_does_not_hardcode_versions(self):
        """여기에 버전을 적는 순간 두 곳이 갈라진다."""
        with open(os.path.join(SCRIPTS, "check.py"), encoding="utf-8") as fh:
            body = fh.read()
        pinned = re.findall(r"\b(?:ruff|coverage)==\d", body)
        self.assertEqual([], pinned,
                         "check.py 가 도구 버전을 직접 들고 있다 — 워크플로에서 읽어야 한다")

    def test_refuses_rather_than_guessing_when_workflow_is_gone(self):
        """추측해서 통과시키는 것보다 안 도는 게 낫다."""
        saved = check.WORKFLOW
        check.WORKFLOW = os.path.join(tempfile.mkdtemp(), "nope.yml")
        try:
            with self.assertRaises(SystemExit):
                check.ci_pins()
        finally:
            check.WORKFLOW = saved

    def test_refuses_when_a_pin_format_changed(self):
        """형식이 바뀌면 조용히 도구 없이 도는 게 아니라 멈춰야 한다."""
        tmp = os.path.join(tempfile.mkdtemp(), "tests.yml")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("run: pip install ruff==0.16.3\nrun: coverage report --fail-under=50\n")
        saved = check.WORKFLOW
        check.WORKFLOW = tmp
        try:
            with self.assertRaises(SystemExit):
                check.ci_pins()          # coverage 핀이 없다
        finally:
            check.WORKFLOW = saved


class ClearsStaleBytecodeTest(unittest.TestCase):
    """**낡은 `.pyc` 가 위반 주입 검증을 오염시킨다.**

    `cp backup.py live.py` 로 되돌리면 내용은 옛것인데 **mtime 도 옛것**이라 `.pyc` 가
    여전히 유효해 보인다. 그러면 주입된 버전이 계속 로드되고 **복구했는데 테스트가
    실패한다** — 2026-09-08 에 그렇게 걸려서 원인을 코드에서 찾았다.

    위반 주입은 이 레포가 새 검사를 채택하는 기준이다. 그 절차를 오염시키는 것은
    검사 자체의 결함이라 진입점이 매번 지운다.
    """

    def test_the_entrypoint_clears_caches(self):
        with open(os.path.join(SCRIPTS, "check.py"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("_bytecode_caches", body,
                      "낡은 바이트코드를 안 지우면 주입 검증이 조용히 거짓말한다")

    def test_it_finds_the_caches_that_matter(self):
        found = check._bytecode_caches()
        for path in found:
            self.assertIn("__pycache__", path)
            self.assertNotIn(".check-venv", path,
                             "venv 안의 캐시를 지우면 도구를 매번 다시 컴파일한다")

    def test_it_does_not_reach_outside_the_repo(self):
        for path in check._bytecode_caches():
            self.assertTrue(os.path.abspath(path).startswith(os.path.abspath(check.ROOT)),
                            "레포 밖을 지우려 한다: %s" % path)


class CoversEveryCiJobTest(unittest.TestCase):
    """CI 에 잡이 하나 늘었는데 로컬 진입점이 모르면 다시 절반만 보게 된다."""

    def test_entrypoint_runs_what_ci_runs(self):
        with open(os.path.join(SCRIPTS, "check.py"), encoding="utf-8") as fh:
            body = fh.read()
        for needed in ("compileall", "unittest", "ruff", "coverage"):
            self.assertIn(needed, body, f"check.py 가 {needed} 를 돌리지 않는다")

    def test_ci_job_count_matches_what_the_entrypoint_knows(self):
        """잡이 늘면 이 테스트가 먼저 깨져서 진입점을 같이 고치게 한다.

        들여쓰기만 보면 `on:` 아래의 트리거(push·pull_request)까지 잡힌다 —
        실제로 처음엔 그랬다. `jobs:` 블록 안으로 한정한다.
        """
        body = workflow_text()
        jobs_at = body.index("\njobs:")
        jobs = re.findall(r"^  ([a-z][a-z0-9_-]*):$", body[jobs_at:], re.M)
        self.assertEqual(
            {"test", "lint", "coverage"}, set(jobs),
            "CI 잡 구성이 바뀌었다. scripts/check.py 도 함께 고쳤는지 확인하고 "
            "이 테스트의 기대값을 갱신할 것")

    def test_fast_mode_warns_instead_of_pretending(self):
        """--fast 가 조용히 통과하면 그게 '절반만 본 초록'이다."""
        with open(os.path.join(SCRIPTS, "check.py"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("푸시하지 말 것", body,
                      "--fast 가 무엇을 건너뛰었는지 말하지 않는다")


class SaysWhatItCouldNotCheckTest(unittest.TestCase):
    """없앨 수 없는 차이는 **매번 말하게 한다.**

    로컬 검사는 파이썬 셋을 돌릴 수도, 러너의 git 설정을 가져올 수도 없다. 2주 연속
    지적된 항목이고, 바로 얼마 전 다른 머신의 정렬을 확인하는 데 초록 다섯 개가 아무
    도움이 안 됐는데 이 검사는 한마디도 하지 않았다.

    **유보는 통과했을 때도 나와야 한다.** 실패할 때만 보여주면 정작 초록일 때 못 보고,
    사고는 초록일 때 난다.
    """

    def test_reads_the_matrix_and_runner_from_the_workflow(self):
        versions, runners = check.ci_environment()
        body = workflow_text()
        self.assertGreaterEqual(len(versions), 2, "매트릭스를 못 읽었다")
        for v in versions:
            self.assertIn(f'"{v}"', body)
        self.assertTrue(runners, "runs-on 을 못 읽었다")

    def test_does_not_hardcode_the_ci_environment(self):
        """핀 버전과 같은 이유다 — 갈라진 유보 문구는 유보가 아니라 거짓말이 된다."""
        with open(os.path.join(SCRIPTS, "check.py"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertEqual([], re.findall(r'"3\.1[0-9]"', body),
                         "check.py 가 파이썬 버전을 직접 들고 있다")
        self.assertNotIn('"ubuntu-latest"', body,
                         "check.py 가 러너 이름을 직접 들고 있다")

    def test_names_the_versions_it_did_not_run(self):
        notes = "\n".join(check.unverified_here())
        versions, _ = check.ci_environment()
        local = "%d.%d" % sys.version_info[:2]
        for v in versions:
            if v != local:
                self.assertIn(v, notes, f"CI 가 도는 {v} 를 유보로 말하지 않는다")

    def test_says_the_tree_may_differ_from_what_ci_will_see(self):
        """CI 는 커밋된 트리만 본다. 지금 통과한 것과 푸시될 것이 같지 않다."""
        notes = check.unverified_here()
        dirty = subprocess.run(
            ["git", "-C", ROOT, "status", "--porcelain"],
            capture_output=True, text=True).stdout.strip()
        if dirty:
            self.assertTrue(any("커밋되지 않은" in n for n in notes),
                            "미커밋 변경이 있는데 유보에 없다")

    def test_a_non_aligned_clone_is_carried_into_the_notes(self):
        """`✅ clone` 은 '갈라지지 않았다'까지만 말한다. behind 도 초록으로 지나간다."""
        notes = check.unverified_here(("behind", "3커밋 뒤처짐"))
        self.assertTrue(any("behind" in n for n in notes),
                        "정렬되지 않은 클론 상태를 유보로 말하지 않는다")
        self.assertEqual([], [n for n in check.unverified_here(("aligned", ""))
                              if "aligned" in n],
                         "정렬된 상태까지 유보로 말하면 유보가 소음이 된다")

    def test_the_notes_are_printed_on_success_too(self):
        with open(os.path.join(SCRIPTS, "check.py"), encoding="utf-8") as fh:
            body = fh.read()
        tree = ast.parse(body)
        main = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "unverified_here"]
        self.assertEqual(1, len(calls),
                         "main 이 unverified_here 를 부르지 않는다")
        # 실패 분기(return 1) 앞에 있어야 통과·실패 양쪽에서 나온다.
        returns = [n.lineno for n in ast.walk(main)
                   if isinstance(n, ast.Return)
                   and isinstance(n.value, ast.Constant) and n.value.value == 1]
        self.assertTrue(returns and calls[0].lineno < min(returns),
                        "유보가 실패 분기 뒤에 있다 — 초록일 때 안 보인다")


class ShippedWithTheToolTest(unittest.TestCase):
    def test_check_is_documented(self):
        ref = os.path.join(ROOT, "skills", "vibe-harness", "references", "setup.md")
        with open(ref, encoding="utf-8") as fh:
            self.assertIn("scripts/check.py", fh.read(),
                          "진입점을 만들어놓고 문서가 옛 방법을 안내하면 아무도 안 쓴다")

    def test_venv_is_not_tracked(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as fh:
            self.assertIn(".check-venv", fh.read())


if __name__ == "__main__":
    unittest.main()


class CloneStateTest(unittest.TestCase):
    """재작성과 진짜 분기는 **대응이 반대**라 구별해야 한다.

    재작성에 `pull` 하면 머지 커밋이 생기면서 원격이 지운 것이 되돌아온다. 실제로 그럴
    뻔했다 — 공개 레포에서 스크럽한 제3자 실명이 되살아날 상황이었다. 진짜 분기에
    `reset --hard` 하면 반대로 내 작업이 사라진다.
    """

    def setUp(self):
        self.saved = check.ROOT
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        check.ROOT = self.saved

    def git(self, repo, *args, **kw):
        import subprocess as sp
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        return sp.run(["git", "-C", repo, *args], capture_output=True, text=True,
                      env=env, check=kw.get("check", True))

    def make_pair(self):
        """origin 과 그것을 추적하는 클론.

        **브랜치 이름을 호스트 설정에 맡기지 않는다.** `init.defaultBranch` 가 로컬은
        `main`, CI 는 `master` 였고, 그래서 뒤의 `checkout main` 이 CI 에서는 원격
        추적 브랜치를 새로 만들어버렸다 — 분기 상황 자체가 만들어지지 않아 두 테스트가
        로컬에서만 통과했다. 환경에 기대는 테스트는 환경이 다른 곳에서 조용히 다른 것을
        검사한다.
        """
        origin = os.path.join(self.base, "origin.git")
        work = os.path.join(self.base, "work")
        self.git(self.base, "init", "-q", "--bare", "-b", "main", "origin.git")
        self.git(self.base, "clone", "-q", origin, "work")
        self.git(work, "symbolic-ref", "HEAD", "refs/heads/main")
        self.git(work, "commit", "-q", "--allow-empty", "-m", "base")
        self.git(work, "push", "-q", "-u", "origin", "main")
        self.assertEqual("main", self.git(work, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
                         "작업 브랜치가 main 이 아니다 — 호스트의 defaultBranch 에 끌려갔다")
        return origin, work

    def state_of(self, work):
        check.ROOT = work
        return check.clone_state()

    def test_aligned(self):
        _o, work = self.make_pair()
        self.assertEqual("aligned", self.state_of(work)[0])

    def test_ahead(self):
        _o, work = self.make_pair()
        self.git(work, "commit", "-q", "--allow-empty", "-m", "mine")
        self.assertEqual("ahead", self.state_of(work)[0])

    def commit(self, work, message, content):
        """내용이 다른 커밋. 빈 커밋으로는 재작성을 흉내낼 수 없다 —

        같은 초에 만든 동일 트리·동일 메시지·동일 부모의 빈 커밋은 **SHA 까지 같아진다.**
        커밋은 내용 주소이기 때문이다. 처음에 그렇게 만들었더니 원격이 로컬의 후손이 돼서
        'behind' 로 나왔고, 재작성 판정을 검증하지 못했다.
        """
        with open(os.path.join(work, "f.txt"), "w", encoding="utf-8") as fh:
            fh.write(content)
        self.git(work, "add", "f.txt")
        self.git(work, "commit", "-q", "-m", message)

    def test_rewrite_is_recognised_as_rewrite(self):
        """같은 작업이 다른 SHA 로 올라간 것 — 여기서 pull 하면 안 된다."""
        _o, work = self.make_pair()
        self.commit(work, "일한 것", "original")
        # 원격이 같은 메시지를 **다른 내용**으로 갖게 만든다 (스크럽 후 force-push 흉내)
        self.git(work, "checkout", "-q", "-b", "rewritten", "HEAD~1")
        self.commit(work, "일한 것", "scrubbed")
        self.commit(work, "스크럽 기록", "note")
        self.git(work, "push", "-q", "-f", "origin", "rewritten:main")
        self.git(work, "checkout", "-q", "-f", "main")
        self.git(work, "fetch", "-q", "origin")
        state, detail = self.state_of(work)
        self.assertEqual("rewritten", state)
        self.assertIn("reset --hard", detail)

    def test_real_divergence_is_not_called_a_rewrite(self):
        """양쪽에 서로 없는 작업이 있으면 reset 은 내 것을 지운다."""
        _o, work = self.make_pair()
        self.git(work, "checkout", "-q", "-b", "other")
        self.commit(work, "원격 쪽 작업", "theirs")
        self.git(work, "push", "-q", "-f", "origin", "other:main")
        self.git(work, "checkout", "-q", "-f", "main")
        self.commit(work, "내 쪽 작업", "mine")
        self.git(work, "fetch", "-q", "origin")
        self.assertEqual("diverged", self.state_of(work)[0])

    def test_no_upstream_is_skipped_not_failed(self):
        """추적 브랜치가 없는 것은 고장이 아니다."""
        work = os.path.join(self.base, "solo")
        os.makedirs(work)
        self.git(work, "init", "-q", "-b", "main")
        self.git(work, "commit", "-q", "--allow-empty", "-m", "x")
        self.assertEqual("no-upstream", self.state_of(work)[0])

    def test_bad_states_fail_the_check(self):
        """판정만 하고 통과시키면 갈라진 채로 푸시한다."""
        with open(os.path.join(SCRIPTS, "check.py"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn('("rewritten", "diverged")', body,
                      "재작성·분기 상태가 check 를 실패시키지 않는다")
