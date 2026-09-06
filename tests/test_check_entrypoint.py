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
import importlib.util
import os
import re
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
