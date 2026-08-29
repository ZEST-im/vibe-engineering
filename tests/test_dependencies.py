"""태스크 의존 관계를 고정한다.

칸반이 평면 목록이라 "이걸 하려면 저게 먼저"가 표현되지 않았다. 실측하니 484건 중
22건이 그 관계를 제목·설명에 **말로** 적고 있었다 — 사람은 읽지만 보드는 모른다.

선택 필드 `depends_on: [id, ...]` 을 둔다. 다만 이 작업의 핵심은 표현이 아니라
**구별**이다. 지금은 막힌 태스크와 지금 당장 할 수 있는 태스크가 보드에서 똑같아
보인다 — 에이전트가 막힌 것을 집어 들어도 아무도 말려주지 않는다.

두 가지를 특히 조심한다.

- **아카이브를 완료로 세지 않으면** 오래된 프로젝트에서 멀쩡한 태스크가 전부 막힌
  것으로 보인다. 아카이브는 done 을 옮겨둔 것이다.
- **순환은 조용하다.** A→B→A 면 어떤 순서로도 끝나지 않는데 보드는 아무 말도 하지
  않는다. 없는 id 를 가리키는 것도 마찬가지다.
"""
import importlib.util
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("srv_deps", os.path.join(SCRIPTS, "server.py"))
srv = importlib.util.module_from_spec(_spec)
sys.modules["srv_deps"] = srv
_spec.loader.exec_module(srv)


def t(tid, status="todo", deps=None):
    task = {"id": tid, "title": f"작업 {tid}", "status": status}
    if deps is not None:
        task["depends_on"] = deps
    return task


class BlockedDetectionTest(unittest.TestCase):
    def test_unmet_dependency_marks_task_blocked(self):
        rep = srv._dependency_report([t(1, "todo"), t(2, "todo", deps=[1])])
        self.assertEqual({"2": ["1"]}, rep["blocked"])

    def test_done_dependency_unblocks(self):
        rep = srv._dependency_report([t(1, "done"), t(2, "todo", deps=[1])])
        self.assertEqual({}, rep["blocked"])

    def test_archived_dependency_counts_as_done(self):
        """아카이브를 안 세면 오래된 프로젝트가 전부 막힌 것으로 보인다."""
        rep = srv._dependency_report([t(2, "todo", deps=[1])], archived=[t(1, "done")])
        self.assertEqual({}, rep["blocked"], "아카이브된 선행 태스크는 완료다")

    def test_archive_membership_wins_over_status_field(self):
        """아카이브에 있으면 status 가 뭐라 적혀 있든 끝난 것이다.

        아카이브는 done 을 옮겨둔 곳이므로 소속 자체가 완료의 근거다. 손으로 고친
        아카이브에 다른 status 가 남아 있어도 그것 때문에 후속 태스크가 막히면 안 된다.
        (이 경우를 짚지 않으면 status=="done" 검사만으로 통과해 버려서, 아카이브를
        완료로 세는 코드를 지워도 테스트가 잡지 못한다 — 실제로 그랬다.)
        """
        stale = {"id": 1, "title": "옛 태스크", "status": "in_progress"}
        rep = srv._dependency_report([t(2, "todo", deps=[1])], archived=[stale])
        self.assertEqual({}, rep["blocked"])

    def test_partially_met_still_blocked_and_names_only_the_gap(self):
        rep = srv._dependency_report(
            [t(1, "done"), t(2, "todo"), t(3, "todo", deps=[1, 2])])
        self.assertEqual({"3": ["2"]}, rep["blocked"],
                         "이미 끝난 선행까지 나열하면 무엇을 기다리는지 흐려진다")

    def test_done_task_is_not_reported_blocked(self):
        rep = srv._dependency_report([t(1, "todo"), t(2, "done", deps=[1])])
        self.assertEqual({}, rep["blocked"])

    def test_scalar_dependency_is_accepted(self):
        """손으로 적을 때 리스트를 빼먹는다. 받아주되 같은 의미로 해석한다."""
        rep = srv._dependency_report([t(1, "todo"), t(2, "todo", deps=1)])
        self.assertEqual({"2": ["1"]}, rep["blocked"])

    def test_string_and_int_ids_match(self):
        """접두어 도입 이후 id 는 문자열일 수 있다. 1 과 "1" 이 갈라지면 안 된다."""
        rep = srv._dependency_report([t("1", "done"), t(2, "todo", deps=[1])])
        self.assertEqual({}, rep["blocked"])


class ReadyListTest(unittest.TestCase):
    def test_ready_excludes_blocked(self):
        rep = srv._dependency_report([t(1, "todo"), t(2, "todo", deps=[1])])
        self.assertEqual(["1"], rep["ready"])

    def test_ready_excludes_in_progress_and_done(self):
        rep = srv._dependency_report([t(1, "in_progress"), t(2, "done"), t(3, "todo")])
        self.assertEqual(["3"], rep["ready"])

    def test_backlog_counts_as_ready_when_unblocked(self):
        rep = srv._dependency_report([t(1, "backlog")])
        self.assertEqual(["1"], rep["ready"])


class BadGraphTest(unittest.TestCase):
    def test_unknown_reference_is_reported_not_crashed(self):
        rep = srv._dependency_report([t(1, "todo", deps=[999])])
        self.assertEqual({"1": ["999"]}, rep["unknown_refs"])

    def test_unknown_reference_does_not_block(self):
        """없는 것을 영원히 기다리게 두면 조용히 멈춘다. 막지 말고 말한다."""
        rep = srv._dependency_report([t(1, "todo", deps=[999])])
        self.assertEqual({}, rep["blocked"])
        self.assertIn("1", rep["ready"])

    def test_two_node_cycle_is_found(self):
        rep = srv._dependency_report([t(1, "todo", deps=[2]), t(2, "todo", deps=[1])])
        self.assertTrue(rep["cycles"], "A→B→A 를 못 찾으면 보드가 조용히 멈춘다")

    def test_three_node_cycle_is_found(self):
        rep = srv._dependency_report(
            [t(1, "todo", deps=[2]), t(2, "todo", deps=[3]), t(3, "todo", deps=[1])])
        self.assertTrue(rep["cycles"])

    def test_self_dependency_is_a_cycle(self):
        rep = srv._dependency_report([t(1, "todo", deps=[1])])
        self.assertTrue(rep["cycles"])

    def test_diamond_is_not_a_cycle(self):
        """A→B,C→D 는 순환이 아니다. 오탐하면 경고가 무시된다."""
        rep = srv._dependency_report(
            [t(1, "todo"), t(2, "todo", deps=[1]), t(3, "todo", deps=[1]),
             t(4, "todo", deps=[2, 3])])
        self.assertEqual([], rep["cycles"])

    def test_long_chain_is_not_a_cycle(self):
        chain = [t(1, "todo")] + [t(i, "todo", deps=[i - 1]) for i in range(2, 30)]
        self.assertEqual([], srv._dependency_report(chain)["cycles"])


class BackwardCompatibilityTest(unittest.TestCase):
    def test_boards_without_depends_on_are_untouched(self):
        """기존 21개 프로젝트 484건에는 이 필드가 없다. 아무것도 달라지면 안 된다."""
        rep = srv._dependency_report([t(1, "todo"), t(2, "in_progress"), t(3, "done")])
        self.assertEqual({}, rep["blocked"])
        self.assertEqual({}, rep["unknown_refs"])
        self.assertEqual([], rep["cycles"])
        self.assertEqual(["1"], rep["ready"])

    def test_empty_board(self):
        rep = srv._dependency_report([])
        self.assertEqual({"blocked": {}, "unknown_refs": {}, "cycles": [], "ready": []}, rep)

    def test_task_without_id_does_not_crash(self):
        srv._dependency_report([{"title": "id 없음", "status": "todo"}])

    def test_context_exposes_dependencies(self):
        with open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8") as fh:
            self.assertIn('"dependencies": _dependency_report(', fh.read())


if __name__ == "__main__":
    unittest.main()
