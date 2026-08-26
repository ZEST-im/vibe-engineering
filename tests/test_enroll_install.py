"""`enroll.py --update-skill` — 레포의 코드를 설치본으로 반영한다.

서버는 레포가 아니라 설치본(`~/.claude/skills/vibe-harness/server.py`)에서 돈다. 그래서
`git pull` 만으로는 서버가 바뀌지 않는다.

위험한 지점: 설치 디렉토리에는 코드와 **머신 로컬 상태가 같이 있다**. sync.json(개인 토큰),
projects.json(수집 대상), users.json(실명 별칭), push-state.json(전송 이력). 통째로 덮으면
토큰과 등록 정보가 날아간다. 그래서 복사 대상은 화이트리스트다 — 새 파일이 생기면 명시적으로
추가해야 하고, 모르는 파일은 건드리지 않는다.

setup.py 는 복사하지 않는다. 훅을 중복 등록한 이력이 있어 잠긴 파일이고, 설치본에 최신을
넣어두면 누군가 그걸 실행하게 된다.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

spec = importlib.util.spec_from_file_location("enroll", os.path.join(SCRIPTS, "enroll.py"))
enroll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enroll)


class InstallPlanTest(unittest.TestCase):
    def plan(self):
        return enroll.skill_install_plan(ROOT)

    def names(self):
        return [os.path.basename(dest) for _src, dest in self.plan()]

    def test_installs_the_server(self):
        self.assertIn("server.py", self.names())

    def test_installs_the_web_ui(self):
        self.assertIn("kanban.html", self.names())

    def test_installs_the_skill_definition(self):
        self.assertIn("SKILL.md", self.names())

    def test_installs_the_collector_so_the_agent_can_run_it(self):
        self.assertIn("reconcile_runs.py", self.names())

    def test_never_touches_machine_local_state(self):
        forbidden = {"sync.json", "projects.json", "users.json", "push-state.json"}

        self.assertEqual(set(), forbidden & set(self.names()))

    def test_does_not_install_setup_py(self):
        """훅 중복 등록 이력이 있어 잠긴 파일이다. 설치본에 최신을 두면 실행하게 된다."""
        self.assertNotIn("setup.py", self.names())

    def test_every_source_exists(self):
        missing = [src for src, _dest in self.plan() if not os.path.exists(src)]

        self.assertEqual([], missing)

    def test_plan_is_stable(self):
        self.assertEqual(self.plan(), self.plan())


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "vibe-harness")
        os.makedirs(self.dest)

    def tearDown(self):
        self.tmp.cleanup()

    def seed_local_state(self):
        for name, body in (
            ("sync.json", {"secret": "shared", "runs_token": "personal", "id_prefix": "hg"}),
            ("projects.json", {"codebook": {"kanban_dir": "/x"}}),
            ("users.json", {"aliases": {"a": "b"}}),
            ("push-state.json", {"codebook": {"s|d": "1:1"}}),
        ):
            with open(os.path.join(self.dest, name), "w", encoding="utf-8") as fh:
                json.dump(body, fh)

    def read(self, name):
        with open(os.path.join(self.dest, name), encoding="utf-8") as fh:
            return json.load(fh)

    def test_copies_the_server(self):
        enroll.install_skill_files(ROOT, self.dest)

        self.assertTrue(os.path.isfile(os.path.join(self.dest, "server.py")))

    def test_preserves_the_personal_token(self):
        self.seed_local_state()

        enroll.install_skill_files(ROOT, self.dest)

        self.assertEqual("personal", self.read("sync.json")["runs_token"])

    def test_preserves_the_id_prefix(self):
        self.seed_local_state()

        enroll.install_skill_files(ROOT, self.dest)

        self.assertEqual("hg", self.read("sync.json")["id_prefix"])

    def test_preserves_the_project_registry(self):
        self.seed_local_state()

        enroll.install_skill_files(ROOT, self.dest)

        self.assertIn("codebook", self.read("projects.json"))

    def test_preserves_push_state(self):
        self.seed_local_state()

        enroll.install_skill_files(ROOT, self.dest)

        self.assertIn("codebook", self.read("push-state.json"))

    def test_creates_the_destination_when_absent(self):
        fresh = os.path.join(self.tmp.name, "fresh")

        enroll.install_skill_files(ROOT, fresh)

        self.assertTrue(os.path.isfile(os.path.join(fresh, "server.py")))

    def test_rerun_is_idempotent(self):
        enroll.install_skill_files(ROOT, self.dest)
        first = os.path.getsize(os.path.join(self.dest, "server.py"))

        enroll.install_skill_files(ROOT, self.dest)

        self.assertEqual(first, os.path.getsize(os.path.join(self.dest, "server.py")))

    def test_reports_what_it_copied(self):
        copied = enroll.install_skill_files(ROOT, self.dest)

        self.assertIn("server.py", [os.path.basename(p) for p in copied])


class IdPrefixConfigTest(unittest.TestCase):
    """접두어는 중앙이 배정한다. 사람이 손으로 넣으면 빠뜨리고, 빠뜨리면 정수로 발급돼
    다시 충돌한다 — 이 기능이 막으려던 바로 그 상태다."""

    def test_writes_the_assigned_prefix(self):
        cfg = enroll.merge_sync_config({}, token="t", endpoint="https://e/sync", id_prefix="ar")

        self.assertEqual("ar", cfg["id_prefix"])

    def test_keeps_existing_prefix_when_none_given(self):
        cfg = enroll.merge_sync_config({"id_prefix": "hg"}, token="t", endpoint="https://e/sync")

        self.assertEqual("hg", cfg["id_prefix"])

    def test_does_not_invent_a_prefix(self):
        cfg = enroll.merge_sync_config({}, token="t", endpoint="https://e/sync")

        self.assertNotIn("id_prefix", cfg)

    def test_blank_prefix_does_not_overwrite(self):
        cfg = enroll.merge_sync_config({"id_prefix": "hg"}, token="t",
                                       endpoint="https://e/sync", id_prefix="  ")

        self.assertEqual("hg", cfg["id_prefix"])

    def test_rejects_a_prefix_that_would_break_id_parsing(self):
        """접두어가 숫자로 시작하면 정수 id 와 구분되지 않는다."""
        with self.assertRaises(ValueError):
            enroll.merge_sync_config({}, token="t", endpoint="https://e/sync", id_prefix="1a")

    def test_rejects_a_prefix_with_separators(self):
        with self.assertRaises(ValueError):
            enroll.merge_sync_config({}, token="t", endpoint="https://e/sync", id_prefix="a b")


if __name__ == "__main__":
    unittest.main()
