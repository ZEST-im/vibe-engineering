"""프로젝트 키가 만들어지는 곳을 고정한다.

키는 중앙이 프로젝트를 식별하는 값인데, 지금까지 **로컬 디렉토리명**에서 나왔다.
디렉토리명은 사람과 머신마다 다르다. 같은 리포가 한쪽에서는 `pante`, 다른 쪽에서는
`pante_bde` 로 등록돼 있었다.

중앙의 중복 제거는 프로젝트 **안에서만** 돌고 인별 합계는 프로젝트를 가로질러 더한다.
그래서 두 키에 같은 행이 있으면 그대로 이중 계상된다 — 2026-08-29 에 4쌍을 통합해
46.9억 토큰 / $8,476 을 걷어냈다.

**중앙만 고치면 다음 push 때 stale 키가 되살아난다.** 키를 만드는 쪽이 여기다.

두 가지를 특히 지킨다.

- **자동으로 바꾸지 않는다.** 키를 바꾸면 중앙 이력이 그 지점에서 끊기고 되돌릴 수
  없다. 어긋난 것은 알리기만 한다.
- **같은 키로 다른 경로를 덮지 않는다.** 워크트리는 remote 가 같아 같은 키가 나오므로
  조용히 덮으면 본체가 수집에서 사라진다.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("enroll_key", os.path.join(SCRIPTS, "enroll.py"))
enroll = importlib.util.module_from_spec(_spec)
sys.modules["enroll_key"] = enroll
_spec.loader.exec_module(enroll)


def git_repo(name, remote=None):
    """이름과 remote 가 다른 리포를 만든다 — 그 차이가 이 기능의 전부다."""
    base = tempfile.mkdtemp()
    repo = os.path.join(base, name)
    os.makedirs(os.path.join(repo, "vibe-harness"))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    if remote:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=repo, check=True)
    return repo


class DeriveFromRemoteTest(unittest.TestCase):
    def test_https_url(self):
        repo = git_repo("local-name", "https://github.com/ZEST-im/vibe-engineering.git")
        self.assertEqual("vibe-engineering", enroll.derive_project_key(repo))

    def test_ssh_url(self):
        repo = git_repo("local-name", "git@github.com:ZEST-im/vibe-engineering.git")
        self.assertEqual("vibe-engineering", enroll.derive_project_key(repo))

    def test_url_without_dot_git(self):
        repo = git_repo("local-name", "https://github.com/ZEST-im/pante")
        self.assertEqual("pante", enroll.derive_project_key(repo))

    def test_trailing_slash(self):
        repo = git_repo("local-name", "https://github.com/ZEST-im/pante/")
        self.assertEqual("pante", enroll.derive_project_key(repo))

    def test_remote_wins_over_directory_name(self):
        """이것이 이 기능의 전부다. 디렉토리명이 이기면 아무것도 달라지지 않는다."""
        repo = git_repo("pante_bde", "https://github.com/ZEST-im/pante.git")
        self.assertEqual("pante", enroll.derive_project_key(repo))

    def test_worktrees_of_one_repo_get_one_key(self):
        """워크트리는 같은 프로젝트다. 각각 다른 키를 받으면 그게 이중 계상의 씨앗이다."""
        repo = git_repo("main-checkout", "https://github.com/ZEST-im/app.git")
        wt = os.path.join(os.path.dirname(repo), "app-feature-x")
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"],
                       cwd=repo, check=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))
        subprocess.run(["git", "worktree", "add", "-q", wt, "-b", "feature-x"],
                       cwd=repo, check=True)
        self.assertEqual(enroll.derive_project_key(repo), enroll.derive_project_key(wt))


class FallbackTest(unittest.TestCase):
    def test_no_remote_falls_back_to_directory(self):
        repo = git_repo("local-only")
        self.assertEqual("local-only", enroll.derive_project_key(repo))

    def test_not_a_git_repo_falls_back_to_directory(self):
        d = os.path.join(tempfile.mkdtemp(), "plain-dir")
        os.makedirs(d)
        self.assertEqual("plain-dir", enroll.derive_project_key(d))

    def test_missing_path_does_not_crash(self):
        self.assertIsNotNone(enroll.derive_project_key("/nonexistent/xyz"))


class ParseArgTest(unittest.TestCase):
    def test_explicit_key_is_honoured(self):
        repo = git_repo("dir", "https://github.com/ZEST-im/remote-name.git")
        key, path = enroll.parse_project_arg(f"chosen={repo}")
        self.assertEqual("chosen", key)
        self.assertEqual(repo, path)

    def test_bare_path_derives_the_key(self):
        """키를 손으로 정하게 두면 머신마다 갈라진다. 생략을 허용한다."""
        repo = git_repo("dir", "https://github.com/ZEST-im/remote-name.git")
        key, path = enroll.parse_project_arg(repo)
        self.assertEqual("remote-name", key)
        self.assertEqual(repo, path)

    def test_empty_is_rejected(self):
        with self.assertRaises(ValueError):
            enroll.parse_project_arg("")


class DriftAuditTest(unittest.TestCase):
    def test_reports_mismatch(self):
        repo = git_repo("pante_bde", "https://github.com/ZEST-im/pante.git")
        reg = {"pante_bde": {"kanban_dir": os.path.join(repo, "vibe-harness")}}
        drift = enroll.audit_project_keys(reg)
        self.assertEqual(1, len(drift))
        self.assertEqual("pante", drift[0]["derived"])

    def test_quiet_when_aligned(self):
        repo = git_repo("app", "https://github.com/ZEST-im/app.git")
        reg = {"app": {"kanban_dir": os.path.join(repo, "vibe-harness")}}
        self.assertEqual([], enroll.audit_project_keys(reg))

    def test_case_difference_is_a_mismatch(self):
        """중앙은 문자열로 구별한다. 대소문자만 달라도 다른 프로젝트가 된다."""
        repo = git_repo("X", "https://github.com/ZEST-im/agent-tips-rnd.git")
        reg = {"AGENT-TIPS-RND": {"kanban_dir": os.path.join(repo, "vibe-harness")}}
        self.assertEqual(1, len(enroll.audit_project_keys(reg)))

    def test_audit_does_not_modify_the_registry(self):
        """알리기만 한다. 키를 바꾸면 중앙 이력이 끊기고 되돌릴 수 없다."""
        repo = git_repo("pante_bde", "https://github.com/ZEST-im/pante.git")
        reg = {"pante_bde": {"kanban_dir": os.path.join(repo, "vibe-harness")}}
        before = json.dumps(reg, sort_keys=True)
        enroll.audit_project_keys(reg)
        self.assertEqual(before, json.dumps(reg, sort_keys=True))

    def test_empty_registry(self):
        self.assertEqual([], enroll.audit_project_keys({}))


class CollisionGuardTest(unittest.TestCase):
    def setUp(self):
        self.registry = os.path.join(tempfile.mkdtemp(), "projects.json")

    def test_same_key_different_path_is_refused(self):
        """워크트리를 등록하면 실제로 이 상황이 된다. 덮으면 본체가 수집에서 사라진다."""
        a = git_repo("a", "https://github.com/ZEST-im/app.git")
        b = git_repo("b", "https://github.com/ZEST-im/app.git")
        enroll.add_project(self.registry, "app", a)
        with self.assertRaises(SystemExit):
            enroll.add_project(self.registry, "app", b)

    def test_reregistering_the_same_path_is_fine(self):
        a = git_repo("a", "https://github.com/ZEST-im/app.git")
        enroll.add_project(self.registry, "app", a)
        enroll.add_project(self.registry, "app", a)          # 멱등

    def test_refusal_keeps_the_original_entry(self):
        a = git_repo("a", "https://github.com/ZEST-im/app.git")
        b = git_repo("b", "https://github.com/ZEST-im/app.git")
        enroll.add_project(self.registry, "app", a)
        try:
            enroll.add_project(self.registry, "app", b)
        except SystemExit:
            pass
        with open(self.registry, encoding="utf-8") as fh:
            self.assertIn("/a/", json.load(fh)["app"]["kanban_dir"] + "/")


if __name__ == "__main__":
    unittest.main()
