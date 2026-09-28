"""한 번도 쓰이지 않은 보드가 남이 올려둔 보드를 덮는 것을 막는다.

## 실제로 난 사고

2026-09-14 15:00. 한 머신이 재시작하면서 **자기 것이 아닌 키 두 개를 0건으로 밀어**,
다른 머신이 올려둔 17건·15건짜리 보드를 덮었다.

경로는 이렇다. 서버는 시작할 때 등록된 모든 프로젝트에 `init_kanban` 을 돌려 빈 보드를
만든다. 레포만 클론돼 있고 한 번도 안 쓴 키도 그때 디렉토리가 생긴다. 스냅샷은
`os.path.isdir()` 만 보고 싣는다 — 그래서 **0건짜리 source 가 번들에 실려 나가고**,
수신 쪽 머지는 key 단위 upsert 라 마지막에 민 쪽이 이긴다.

기존 가드는 디렉토리 **부재**만 막는다. 빈 보드는 디렉토리가 있으므로 통과한다.

## 데이터가 사라지는 것은 아니다. 그래서 더 나쁘다

원 보드는 각 머신에 그대로 있고 다시 밀면 복구된다. 그러나 그 사이 화면은 **빈 보드를
사실로 보여준다.** 아무도 오류를 보지 못하고, 그 프로젝트는 일을 안 한 것이 된다.

## 왜 "태스크도 결정도 없음" 인가

`context`·`schema` 는 보드가 아니라 **레포 파일**에서 나온다. 클론만 해두면 값이 생기고,
빈 보드에서도 구조는 채워진 dict 다(`phase: ""`, `scope: ""`). 그래서 그것들로는 "이
보드가 쓰였는가" 를 가를 수 없다. 사람이 이 보드에 무언가를 남겼다는 증거는 태스크와
결정 둘뿐이다.

아카이브는 태스크에 합쳐진 뒤 판정하므로, 활성 태스크가 0 이어도 아카이브가 있으면
쓰인 보드다.
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

# 머신 설정이 새어 들어오면 id 발급과 동기화 설정이 실제 값을 집어온다.
os.environ["VIBE_HARNESS_SYNC_CONFIG"] = os.path.join(
    tempfile.gettempdir(), "vibe-harness-empty-source-no-sync.json")

_spec = importlib.util.spec_from_file_location(
    "vh_server_empty_source", os.path.join(SCRIPTS, "server.py"))
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


class SnapshotSourceTestCase(unittest.TestCase):
    """프로젝트 등록을 테스트 안에서만 갈아끼운다 — 머신의 실제 등록을 읽지 않는다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = os.path.join(self.tmp.name, "projects.json")
        self._saved_config = server.CONFIG_PATH
        server.CONFIG_PATH = self.registry
        self.projects = {}

    def tearDown(self):
        server.CONFIG_PATH = self._saved_config
        self.tmp.cleanup()

    def board(self, key, tasks=(), decisions=(), archives=()):
        """프로젝트 하나를 만들어 등록한다. 빈 보드는 tasks 를 비워 부른다."""
        project_dir = os.path.join(self.tmp.name, key)
        kanban_dir = os.path.join(project_dir, "vibe-harness")
        os.makedirs(kanban_dir, exist_ok=True)
        with open(os.path.join(kanban_dir, "kanban.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "next_id": 1, "tasks": list(tasks)}, fh, ensure_ascii=False)
        with open(os.path.join(kanban_dir, "decisions.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "next_id": 1, "decisions": list(decisions)},
                      fh, ensure_ascii=False)
        if archives:
            adir = os.path.join(kanban_dir, "archive")
            os.makedirs(adir, exist_ok=True)
            with open(os.path.join(adir, "2026-01.json"), "w", encoding="utf-8") as fh:
                json.dump({"tasks": list(archives)}, fh, ensure_ascii=False)
        self.projects[key] = {"name": key, "kanban_dir": kanban_dir}
        with open(self.registry, "w", encoding="utf-8") as fh:
            json.dump(self.projects, fh, ensure_ascii=False)
        return kanban_dir

    def register_missing(self, key):
        """등록은 있는데 디렉토리는 없는 키 — 기존 가드가 막던 경우."""
        self.projects[key] = {"name": key,
                              "kanban_dir": os.path.join(self.tmp.name, key, "gone")}
        with open(self.registry, "w", encoding="utf-8") as fh:
            json.dump(self.projects, fh, ensure_ascii=False)

    def keys_in_bundle(self, *project_keys):
        snap = server._build_dashboard_snapshot("ax-project", list(project_keys))
        return [s["key"] for s in snap["sources"]]


TASK = {"id": 1, "title": "실제 작업", "status": "todo", "position": 1}
DECISION = {"id": 1, "title": "무언가 정했다", "status": "accepted"}


class EmptyBoardIsNotPublishedTest(SnapshotSourceTestCase):
    def test_a_board_never_used_is_left_out(self):
        """여기가 사고 지점 — 이 source 가 남의 17건짜리 보드를 덮었다."""
        self.board("never-used")

        self.assertEqual([], self.keys_in_bundle("never-used"))

    def test_a_board_with_tasks_is_published(self):
        self.board("real-work", tasks=[TASK])

        self.assertEqual(["real-work"], self.keys_in_bundle("real-work"))

    def test_decisions_alone_count_as_used(self):
        """결정도 사람이 남긴 기록이다. 태스크가 0 이라고 버리면 그것을 잃는다."""
        self.board("decisions-only", decisions=[DECISION])

        self.assertEqual(["decisions-only"], self.keys_in_bundle("decisions-only"))

    def test_archived_tasks_count_as_used(self):
        """활성 태스크를 전부 아카이브한 보드는 빈 보드가 아니다."""
        self.board("all-archived", archives=[TASK])

        self.assertEqual(["all-archived"], self.keys_in_bundle("all-archived"))


class OtherSourcesAreUntouchedTest(SnapshotSourceTestCase):
    def test_an_empty_board_does_not_remove_the_others(self):
        self.board("alpha", tasks=[TASK])
        self.board("blank")
        self.board("beta", tasks=[TASK])

        self.assertEqual(["alpha", "beta"], self.keys_in_bundle("alpha", "blank", "beta"))

    def test_requested_order_survives(self):
        self.board("beta", tasks=[TASK])
        self.board("alpha", tasks=[TASK])

        self.assertEqual(["beta", "alpha"], self.keys_in_bundle("beta", "alpha"))

    def test_a_published_source_still_carries_its_contents(self):
        """걸러내느라 실리는 쪽의 내용을 건드리면 안 된다."""
        self.board("alpha", tasks=[TASK], decisions=[DECISION])
        self.board("blank")

        snap = server._build_dashboard_snapshot("ax-project", ["alpha", "blank"])
        alpha = snap["sources"][0]

        self.assertEqual(1, len(alpha["tasks"]))
        self.assertEqual(1, len(alpha["decisions"]))


class ExistingGuardStillHoldsTest(SnapshotSourceTestCase):
    def test_a_missing_directory_is_still_left_out(self):
        """디렉토리 부재를 막던 기존 가드를 잃지 않는다."""
        self.register_missing("gone")

        self.assertEqual([], self.keys_in_bundle("gone"))

    def test_an_unregistered_key_is_still_left_out(self):
        self.board("alpha", tasks=[TASK])

        self.assertEqual(["alpha"], self.keys_in_bundle("alpha", "never-registered"))


class BundleStaysWellFormedTest(SnapshotSourceTestCase):
    def test_all_empty_yields_no_sources_but_a_valid_bundle(self):
        """전부 비어도 번들은 망가지지 않는다 — 빈 목록을 정상으로 보낸다."""
        self.board("blank-one")
        self.board("blank-two")

        snap = server._build_dashboard_snapshot("ax-project", ["blank-one", "blank-two"])

        self.assertEqual([], snap["sources"])
        self.assertTrue(snap.get("revision"), "revision 이 없으면 수신 쪽이 비교할 수 없다")
        self.assertEqual("ax-project", snap["dashboard"])

    def test_revision_changes_when_a_board_starts_being_used(self):
        """빈 보드가 채워지면 번들이 달라졌다고 말해야 한다."""
        self.board("later", tasks=[])
        before = server._build_dashboard_snapshot("ax-project", ["later"])["revision"]
        self.board("later", tasks=[TASK])
        after = server._build_dashboard_snapshot("ax-project", ["later"])["revision"]

        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
