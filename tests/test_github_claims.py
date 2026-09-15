"""문서가 말하는 GitHub 사실이 실제로 참인가.

`private/` 를 읽는 검사와 같은 구조다 — **네트워크가 없으면 skip 하고 그 사실을 말한다.**
조용히 통과하면 "못 본 것"과 "깨끗한 것"이 같아 보인다.

가용성 판단은 `scripts/gh_surface.gh_available` 하나로 통일한다 — 여기서 별도의
"gh 를 쓸 수 있는가" 판정을 다시 만들면 두 판정이 서로 다른 이유로 어긋날 수 있다.
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "gh_surface", os.path.join(ROOT, "scripts", "gh_surface.py"))
gh_surface = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gh_surface)

# `gh_surface.gh_available` 의 기본 경로(`runner=None`)는 이제 `_GH_AUTH_TIMEOUT`(15초)을
# 물고 `_run` 을 부른다 — 더 이상 무제한 대기가 아니다. 이 파일은 그와 별개로 **주입한
# 러너**에도 항상 시간제한을 강제해서, 운영 경로의 값이 바뀌더라도 이 테스트 파일
# 자체의 시간 상한은 여기서 명시적으로 통제한다.
_GH_AVAILABLE_TIMEOUT = 20


def _make_bounded_runner(timeout):
    """`gh_available` 에 넘길 러너를 만든다 — 호출마다 `timeout` 을 강제한다."""
    def runner(argv):
        return gh_surface._run(argv, timeout=timeout)
    return runner


_bounded_availability_runner = _make_bounded_runner(_GH_AVAILABLE_TIMEOUT)


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def gh_json(args, timeout=20):
    """`gh` 호출 결과를 파싱한다. 호출 자체가 실패하면 None.

    가용성(설치/인증) 판정은 `gh_surface.gh_available` 이 이미 했다 — 여기서
    None 은 "그 판정 이후에도 이 특정 쿼리가 실패했다"는 뜻이라, 이 값을 보고
    또 skip 하지 않는다: 인증된 gh 가 있는데 쿼리가 실패하면 그건 assert 로
    드러나야 할 진짜 실패다.
    """
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return None


class DocumentedFilesExistTest(unittest.TestCase):
    """네트워크 없이 확인되는 것부터. **CI 에서도 돈다.**"""

    def test_issue_template_config_points_at_a_real_security_path(self):
        cfg = read(os.path.join(".github", "ISSUE_TEMPLATE", "config.yml"))
        self.assertIn("security/advisories/new", cfg)

    def test_security_policy_exists_if_templates_route_to_it(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "SECURITY.md")),
                        "이슈 템플릿이 보안 신고를 안내하는데 SECURITY.md 가 없다")

    def test_contributing_names_the_real_entrypoint(self):
        body = read("CONTRIBUTING.md")
        self.assertIn("scripts/check.py", body)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "scripts", "check.py")),
                        "CONTRIBUTING.md 가 가리키는 scripts/check.py 가 없다")


class LiveRepoStateTest(unittest.TestCase):
    """실제 레포 상태. **gh 를 쓸 수 없으면 skip 한다 — 실패가 아니다.**

    `setUp` 은 딱 하나만 판정한다 — gh 를 쓸 수 있는가. 그 뒤로는 각 테스트가
    자기 쿼리를 스스로 던지고, 그 쿼리가 실패하면 (필드명 오타, gh 출력 형식
    변경 등 네트워크와 무관한 이유라도) skip 이 아니라 assert 로 드러낸다 —
    두 테스트가 서로 다른 쿼리를 쓰는데 한쪽 쿼리 실패로 다른 쪽까지 뭉뚱그려
    skip 하지 않도록, 쿼리를 setUp 에 공유해두지 않는다.
    """

    def setUp(self):
        ok, reason = gh_surface.gh_available(runner=_bounded_availability_runner)
        if not ok:
            self.skipTest(f"{reason} — CI 는 이 경로 (네트워크·인증 없음)")

    def test_issues_are_enabled_because_templates_assume_it(self):
        repo = gh_json(["repo", "view", "--json", "hasIssuesEnabled"])
        self.assertIsNotNone(
            repo,
            "gh 인증은 있는데 repo view 쿼리가 실패했다 — --json 필드명이나 gh 출력 형식을 확인해라"
            " (네트워크 문제가 아니라 진짜 실패다)")
        self.assertTrue(repo["hasIssuesEnabled"],
                        "이슈 템플릿이 있는데 이슈가 꺼져 있다")

    def test_a_release_exists_once_readme_tells_you_to_check_a_version(self):
        body = read("README.md")
        if "describe --tags" not in body:
            self.skipTest("README 가 아직 버전 확인을 안내하지 않는다 (아직 이 주장이 없다)")
        rel = gh_json(["release", "list", "--limit", "1", "--json", "tagName"])
        self.assertTrue(rel, "README 가 버전을 확인하라는데 릴리스가 하나도 없다")


class AvailabilityGateTimeoutTest(unittest.TestCase):
    """`gh_available` 에 넘기는 러너가 실제로 시간제한을 무는지 확인한다.

    `gh_surface.gh_available` 의 기본 경로(`runner=None`)는 이제 `_GH_AUTH_TIMEOUT`
    (15초)을 물고 `_run` 을 부른다 — 더 이상 무제한 대기가 아니다. 이 파일은 항상
    `_bounded_availability_runner` 를 넘기므로, **주입한 러너**에도 실제로 시간
    제한이 붙는지와, 정말 멈춘 호출을 끊어내는지를 직접 확인한다(운영 경로의 기본값과
    별개로, 이 테스트 파일 자체의 시간 상한을 스스로 통제하기 위함이다).
    """

    def test_gh_available_calls_the_runner_with_a_timeout(self):
        calls = []
        real_run = gh_surface._run

        def spy(argv, **kwargs):
            calls.append((argv, kwargs))
            return real_run(argv, **kwargs)

        gh_surface._run = spy
        try:
            gh_surface.gh_available(runner=_bounded_availability_runner)
        finally:
            gh_surface._run = real_run

        self.assertEqual(1, len(calls), "gh_available 이 러너를 정확히 한 번 불러야 한다")
        argv, kwargs = calls[0]
        self.assertEqual(["gh", "auth", "status"], argv)
        self.assertEqual(
            _GH_AVAILABLE_TIMEOUT, kwargs.get("timeout"),
            "이 파일의 러너가 timeout 없이 _run 을 불렀다 — gh_available 기본 경로와 같아졌다")

    def test_a_hanging_command_through_the_bound_runner_is_terminated_not_blocked(self):
        short_runner = _make_bounded_runner(1)
        start = time.monotonic()
        code, _out, err = short_runner(
            [sys.executable, "-c", "import time; time.sleep(5)"])
        elapsed = time.monotonic() - start
        self.assertEqual(124, code)
        self.assertLess(elapsed, 4, "timeout 이 실제로는 안 걸리고 5초를 기다렸다")
        self.assertIn("초", err)


if __name__ == "__main__":
    unittest.main()
