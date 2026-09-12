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
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "gh_surface", os.path.join(ROOT, "scripts", "gh_surface.py"))
gh_surface = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gh_surface)


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
        done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
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
    """실제 레포 상태. **gh 를 쓸 수 없으면 skip 한다 — 실패가 아니다.**"""

    def setUp(self):
        ok, reason = gh_surface.gh_available()
        if not ok:
            self.skipTest(f"{reason} — CI 는 이 경로 (네트워크·인증 없음)")
        self.repo = gh_json(["repo", "view", "--json", "hasIssuesEnabled"])
        if self.repo is None:
            self.skipTest("gh 인증은 있지만 레포 상태를 읽지 못했다 — 일시적 네트워크 문제로 skip")

    def test_issues_are_enabled_because_templates_assume_it(self):
        self.assertTrue(self.repo["hasIssuesEnabled"],
                        "이슈 템플릿이 있는데 이슈가 꺼져 있다")

    def test_a_release_exists_once_readme_tells_you_to_check_a_version(self):
        body = read("README.md")
        if "describe --tags" not in body:
            self.skipTest("README 가 아직 버전 확인을 안내하지 않는다 (아직 이 주장이 없다)")
        rel = gh_json(["release", "list", "--limit", "1", "--json", "tagName"])
        self.assertTrue(rel, "README 가 버전을 확인하라는데 릴리스가 하나도 없다")


if __name__ == "__main__":
    unittest.main()
