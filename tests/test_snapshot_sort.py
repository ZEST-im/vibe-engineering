"""스냅샷 정렬은 실데이터의 타입 혼합을 견뎌야 한다.

`_snapshot_source` 가 태스크를 `(position, id)` 로 정렬하는데, position 을 그대로 비교해서
int 와 str 이 섞이면 TypeError 로 죽는다. id 는 이미 str() 로 감싸 안전한데 position 만
빠져 있었다.

실제로 막혔다: codebook_vibe 보드에 position 이 int 159 개 + str 7 개로 섞여 있어
`server.py sync` 가 통째로 실패했고, 그 바람에 대시보드 source 목록을 고칠 수가 없었다.
스냅샷 하나가 죽으면 그 머신의 동기화 전체가 멈춘다 — 한 보드의 데이터 흠이 전 프로젝트를
가린다.

칸반 데이터는 사람이 손으로도 고치고 여러 세션이 동시에 쓴다. 타입이 섞이는 것을 막을 수
없으니 읽는 쪽이 견뎌야 한다.
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

# 머신 설정이 새어 들어오면 id 발급이 문자열이 된다. 이 파일은 정렬만 본다.
os.environ["VIBE_HARNESS_SYNC_CONFIG"] = os.path.join(
    tempfile.gettempdir(), "vibe-harness-tests-no-sync.json")

_spec = importlib.util.spec_from_file_location("vh_server_snap",
                                               os.path.join(SCRIPTS, "server.py"))
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


def board(tmp, tasks):
    kdir = os.path.join(tmp, "vibe-harness")
    os.makedirs(kdir, exist_ok=True)
    with open(os.path.join(kdir, "kanban.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "next_id": 999, "tasks": tasks}, fh, ensure_ascii=False)
    return kdir


class SnapshotSortTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, tasks):
        kdir = board(self.tmp.name, tasks)
        return server._snapshot_source("proj", {"kanban_dir": kdir, "name": "proj"})

    def ids(self, tasks):
        return [t["id"] for t in self.source(tasks)["tasks"]]

    def test_mixed_position_types_do_not_crash(self):
        """실제로 이렇게 죽었다 — int 와 str position 이 한 보드에 섞여 있었다."""
        tasks = [{"id": 1, "position": 2}, {"id": 2, "position": "1"}]

        self.assertEqual(2, len(self.ids(tasks)))

    def test_mixed_position_types_sort_by_number(self):
        """'1' 은 문자열이어도 1 번째다. 문자열이라고 뒤로 밀면 순서가 뒤집힌다."""
        tasks = [{"id": "a", "position": 2}, {"id": "b", "position": "1"}]

        self.assertEqual(["b", "a"], self.ids(tasks))

    def test_missing_position_is_first(self):
        tasks = [{"id": 1, "position": 5}, {"id": 2}]

        self.assertEqual([2, 1], self.ids(tasks))

    def test_null_position_does_not_crash(self):
        tasks = [{"id": 1, "position": None}, {"id": 2, "position": 3}]

        self.assertEqual(2, len(self.ids(tasks)))

    def test_unparsable_position_does_not_crash(self):
        tasks = [{"id": 1, "position": "abc"}, {"id": 2, "position": 1}]

        self.assertEqual(2, len(self.ids(tasks)))

    def test_mixed_id_types_still_sort(self):
        """접두어 id 가 들어오면 id 도 str 과 int 가 섞인다."""
        tasks = [{"id": "hg67", "position": 1}, {"id": 5, "position": 1}]

        self.assertEqual(2, len(self.ids(tasks)))

    def test_float_position_is_accepted(self):
        tasks = [{"id": 1, "position": 1.5}, {"id": 2, "position": 1}]

        self.assertEqual([2, 1], self.ids(tasks))


if __name__ == "__main__":
    unittest.main()
