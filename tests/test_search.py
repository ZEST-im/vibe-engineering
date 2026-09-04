"""검색 엔지니어링 1단계 — 필요한 만큼만 값을 치른다.

아카이브를 도입해 세션 시작이 21,446 → 867 tok 이 됐다. 그런데 싸진 이유가 **안 읽어서**다.
그 결과 아카이브가 닿을 수 없는 곳에 있다 — "왜 그렇게 했더라"를 물으면 답이 없거나
파일을 통째로 읽어야 한다.

절감의 다음 단계는 더 줄이는 게 아니라 **안 읽으면서도 쓸 수 있게** 만드는 것이다.
그래서 파일이 아니라 **스니펫**을 돌려준다. qmd 검토에서 가져온 유일한 원칙이다.

이 파일이 지키는 성질 셋:

1. **응답이 코퍼스에 비례하지 않는다.** 비례하면 검색이 아니라 그냥 읽기다.
2. **한 레코드는 한 번만 나온다.** 필드 수만큼 반복하면 결과가 부풀어 목적이 사라진다.
3. **어디서 왔는지 함께 온다.** source·id 가 없으면 찾아도 열 수 없다.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("srv_search", os.path.join(SCRIPTS, "server.py"))
srv = importlib.util.module_from_spec(_spec)
sys.modules["srv_search"] = srv
_spec.loader.exec_module(srv)


def board(tasks=(), archived=(), decisions=()):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "kanban.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "next_id": 99, "tasks": list(tasks)}, fh, ensure_ascii=False)
    if archived:
        os.makedirs(os.path.join(d, "archive"))
        with open(os.path.join(d, "archive", "2026-01.json"), "w", encoding="utf-8") as fh:
            json.dump({"tasks": list(archived)}, fh, ensure_ascii=False)
    if decisions:
        with open(os.path.join(d, "decisions.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "decisions": list(decisions)}, fh, ensure_ascii=False)
    return d


def task(tid, title="제목", details="", status="done", when="2026-01-01T00:00:00+09:00"):
    return {"id": tid, "title": title, "details": details, "status": status,
            "completed_at": when}


class FindsAcrossSourcesTest(unittest.TestCase):
    def test_finds_in_active_tasks(self):
        d = board(tasks=[task(1, details="바늘이 여기 있다")])
        self.assertEqual(1, srv._search(d, "바늘")["total"])

    def test_finds_in_archive(self):
        """아카이브가 검색되지 않으면 이 기능은 존재 이유가 없다."""
        d = board(archived=[task(2, details="아카이브 속 바늘")])
        hits = srv._search(d, "바늘")["hits"]
        self.assertEqual(1, len(hits))
        self.assertEqual("archive", hits[0]["source"])

    def test_finds_in_decisions(self):
        d = board(decisions=[{"id": 1, "title": "왜 그렇게 했나", "why": "바늘 때문이다"}])
        hits = srv._search(d, "바늘")["hits"]
        self.assertEqual("decision", hits[0]["source"])

    def test_source_and_id_come_back(self):
        """찾아도 어디 있는지 모르면 열 수 없다."""
        d = board(archived=[task(7, details="바늘")])
        hit = srv._search(d, "바늘")["hits"][0]
        self.assertEqual(7, hit["id"])
        self.assertIn("source", hit)
        self.assertIn("fields", hit)

    def test_case_insensitive(self):
        d = board(tasks=[task(1, details="Needle in here")])
        self.assertEqual(1, srv._search(d, "NEEDLE")["total"])


class SnippetNotWholeRecordTest(unittest.TestCase):
    """파일도 필드 전체도 아니다. 그게 이 기능의 전부다."""

    def test_response_does_not_grow_with_the_record(self):
        small = board(tasks=[task(1, details="앞" * 50 + "바늘" + "뒤" * 50)])
        huge = board(tasks=[task(1, details="앞" * 20000 + "바늘" + "뒤" * 20000)])
        a = len(json.dumps(srv._search(small, "바늘"), ensure_ascii=False))
        b = len(json.dumps(srv._search(huge, "바늘"), ensure_ascii=False))
        self.assertLess(b, a * 2,
                        "레코드가 400배 커졌는데 응답이 따라 커졌다 — 검색이 아니라 읽기다")

    def test_snippet_is_bounded(self):
        d = board(tasks=[task(1, details="가" * 5000 + "바늘" + "나" * 5000)])
        snip = srv._search(d, "바늘")["hits"][0]["snippet"]
        self.assertLess(len(snip), srv.SEARCH_SNIPPET_CHARS + 40)

    def test_snippet_contains_the_match(self):
        d = board(tasks=[task(1, details="가" * 500 + "바늘" + "나" * 500)])
        self.assertIn("바늘", srv._search(d, "바늘")["hits"][0]["snippet"])

    def test_snippet_marks_truncation(self):
        d = board(tasks=[task(1, details="가" * 500 + "바늘" + "나" * 500)])
        self.assertIn("…", srv._search(d, "바늘")["hits"][0]["snippet"])

    def test_short_field_is_not_marked_truncated(self):
        d = board(tasks=[task(1, details="바늘")])
        self.assertEqual("바늘", srv._search(d, "바늘")["hits"][0]["snippet"])


class OneRecordOneHitTest(unittest.TestCase):
    def test_match_in_two_fields_yields_one_hit(self):
        """필드 수만큼 반복하면 결과가 부풀어 검색의 목적이 사라진다."""
        d = board(tasks=[task(1, title="바늘", details="바늘 또 바늘")])
        res = srv._search(d, "바늘")
        self.assertEqual(1, res["total"])
        self.assertEqual(["title", "details"], res["hits"][0]["fields"],
                         "어느 필드에서 걸렸는지는 남아야 한다")


class BudgetAndOrderTest(unittest.TestCase):
    def test_limit_caps_the_response(self):
        d = board(tasks=[task(i, details="바늘") for i in range(30)])
        self.assertEqual(3, len(srv._search(d, "바늘", limit=3)["hits"]))

    def test_total_reports_the_truth_even_when_capped(self):
        """실린 것만 세면 '전부 봤다'고 착각한다."""
        d = board(tasks=[task(i, details="바늘") for i in range(30)])
        res = srv._search(d, "바늘", limit=3)
        self.assertEqual(30, res["total"])
        self.assertIn("note", res, "잘렸다는 사실이 응답에 없으면 조용한 절삭이다")

    def test_limit_is_hard_capped(self):
        d = board(tasks=[task(i, details="바늘") for i in range(200)])
        self.assertLessEqual(len(srv._search(d, "바늘", limit=99999)["hits"]),
                             srv.SEARCH_MAX_LIMIT)

    def test_non_numeric_limit_falls_back(self):
        """쿼리스트링은 사용자 입력이다. 500 이 아니라 기본값으로 떨어져야 한다."""
        d = board(tasks=[task(1, details="바늘")])
        self.assertEqual(1, srv._search(d, "바늘", limit="abc")["total"])

    def test_newest_first(self):
        d = board(tasks=[task(1, details="바늘", when="2026-01-01T00:00:00+09:00"),
                         task(2, details="바늘", when="2026-08-01T00:00:00+09:00")])
        self.assertEqual(2, srv._search(d, "바늘")["hits"][0]["id"])

    def test_undated_record_does_not_crash_sorting(self):
        rec = task(1, details="바늘")
        del rec["completed_at"]
        self.assertEqual(1, srv._search(board(tasks=[rec]), "바늘")["total"])


class RefusesToActLikeADumpTest(unittest.TestCase):
    def test_empty_query_returns_nothing(self):
        """검색어 없이 부르면 전량을 돌려주게 된다 — 그건 이 기능이 막으려던 것이다."""
        d = board(tasks=[task(i, details="아무거나") for i in range(20)])
        res = srv._search(d, "")
        self.assertEqual([], res["hits"])
        self.assertIn("note", res)

    def test_whitespace_query_is_also_refused(self):
        d = board(tasks=[task(1, details="아무거나")])
        self.assertEqual([], srv._search(d, "   ")["hits"])

    def test_no_match_is_a_tiny_response(self):
        d = board(tasks=[task(i, details="가" * 5000) for i in range(50)])
        res = srv._search(d, "없는말xyz")
        self.assertEqual(0, res["total"])
        self.assertLess(len(json.dumps(res, ensure_ascii=False)), 200)


class RobustnessTest(unittest.TestCase):
    def test_missing_decisions_file_is_fine(self):
        self.assertEqual(0, srv._search(board(), "바늘")["total"])

    def test_corrupt_decisions_does_not_break_search(self):
        d = board(tasks=[task(1, details="바늘")])
        with open(os.path.join(d, "decisions.json"), "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        self.assertEqual(1, srv._search(d, "바늘")["total"])

    def test_record_with_missing_fields(self):
        d = board(tasks=[{"id": 1, "status": "todo"}])
        self.assertEqual(0, srv._search(d, "바늘")["total"])

    def test_route_is_wired(self):
        with open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8") as fh:
            self.assertIn('rest == ["search"]', fh.read())

    def test_context_does_not_embed_search(self):
        """검색은 물었을 때만 값을 치른다. /context 에 끼면 세션 시작이 다시 비싸진다."""
        with open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8") as fh:
            body = fh.read()
        ctx = body[body.index("def _get_context("):body.index("def _get_phase_check(")]
        self.assertNotIn("_search(", ctx)


if __name__ == "__main__":
    unittest.main()
