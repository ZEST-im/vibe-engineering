"""태스크에서 결정을 거꾸로 찾는다 — **필드를 늘리지 않고 계산한다.**

## 왜 역방향 필드를 만들지 않는가

저장된 링크는 결정 → 태스크 한 방향뿐이다(`task_id`, 채워진 비율 58%). 태스크에서
거꾸로 물으려면 결정 전체를 훑어야 하니 "역방향 필드를 추가"가 자연스러운 답처럼 보인다.

**두 방향을 사람이 맞춰 쓰면 반드시 갈라진다.** 이 레포는 같은 종류의 드리프트를 이미
두 번 겪었다(설치 목록이 세 곳, status 리터럴이 네 곳). 갈라진 링크는 없는 링크보다
나쁘다 — 있다고 믿게 만든다. 그리고 계산 비용이 이미 싸다(결정은 프로젝트당 최대 68건).

## 말로 적힌 링크를 함께 센다

실측(2026-09-08, 22개 프로젝트): 저장된 `task_id` **133건** + 태스크 본문이 결정을
가리킨 것 **17건** = **150건**. **필드를 하나도 늘리지 않고 12.8% 늘었다.**

## 이 파일이 지키는 것 넷

1. **어떻게 이어졌는지(`via`) 함께 돌려준다** — 틀렸을 때 어디를 고칠지 알아야 한다.
   검색의 `locator`·순위의 `why_ranked` 와 같은 규율이다.
2. **`#` 없는 숫자를 링크로 읽지 않는다.** 실제로 틀렸다 — "결정→태스크 **58%**" 의
   백분율을 태스크 58 로 읽었다. 좁히자 그 경로의 오탐 13건이 전부 사라졌다.
3. **아카이브까지 본다.** 2,141건 중 대부분이 아카이브에 있고, "이 태스크에 관해 뭘
   결정했지"는 대개 지난 일에 대한 질문이다.
4. **서버 없이 된다.** "서버가 꺼져 있어도 정상"이 규정이다.
"""
import importlib.util
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("vh_server_links",
                                               os.path.join(SCRIPTS, "server.py"))
server = importlib.util.module_from_spec(_spec)
sys.modules["vh_server_links"] = server
_spec.loader.exec_module(server)


def task(tid, text="", title="제목"):
    return {"id": tid, "title": title, "details": text, "status": "todo"}


def decision(did, title="결정", why="", task_id=None, revisit=""):
    return {"id": did, "title": title, "why": why, "revisit": revisit,
            "task_id": task_id, "phase": "PHASE_X"}


def links(t, decisions, ids=()):
    return server.task_link_report(t, decisions, ids)["decisions"]


class FindsStoredLinksTest(unittest.TestCase):
    def test_a_stored_task_id_is_found_from_the_task_side(self):
        found = links(task(42), [decision(1, task_id=42)])
        self.assertEqual([1], [d["id"] for d in found])
        self.assertEqual(["task_id"], found[0]["via"])

    def test_an_unrelated_decision_is_not_returned(self):
        self.assertEqual([], links(task(42), [decision(1, task_id=7)]))

    def test_a_string_task_id_matches_an_int_task(self):
        """손으로 고친 파일에는 타입이 섞인다. 읽는 쪽이 견딘다."""
        self.assertEqual([1], [d["id"] for d in links(task(42), [decision(1, task_id="42")])])

    def test_a_prefixed_task_id_matches(self):
        """`hg94` 처럼 접두어가 붙은 id 도 이어져야 한다."""
        found = links(task("hg94"), [decision(1, task_id="hg94")])
        self.assertEqual([1], [d["id"] for d in found])


class FindsProseLinksTest(unittest.TestCase):
    """**필드를 늘리지 않고 얻는 17건이 여기서 나온다.**"""

    def test_a_task_mentioning_a_decision_is_linked(self):
        found = links(task(1, "decisions #11 에 따른 서브시스템 제거"),
                      [decision(11, title="제거 결정")])
        self.assertEqual([11], [d["id"] for d in found])
        self.assertEqual(["task_text"], found[0]["via"])

    def test_korean_form_counts_too(self):
        found = links(task(1, "결정 #7의 전제"), [decision(7)])
        self.assertEqual([7], [d["id"] for d in found])

    def test_both_paths_on_one_decision_are_one_entry(self):
        """같은 결정을 두 번 실으면 목록이 부풀어 목적이 사라진다."""
        found = links(task(42, "결정 #1 에 따른 것"), [decision(1, task_id=42)])
        self.assertEqual(1, len(found))
        self.assertEqual({"task_id", "task_text"}, set(found[0]["via"]))

    def test_a_reference_to_a_missing_decision_is_reported_not_dropped(self):
        """오타이거나 지워진 것이다. **조용히 버리면 링크가 있다고 믿는다.**"""
        found = links(task(1, "결정 #99 에 따라"), [decision(1)])
        self.assertEqual(1, len(found))
        self.assertTrue(found[0]["missing"])
        self.assertIsNone(found[0]["title"])


class RefusesToGuessTest(unittest.TestCase):
    def test_a_percentage_is_not_a_task_reference(self):
        """**실제로 틀렸던 것이다.**

        결정 #4 의 본문에 "결정→태스크 58% 로 연결은 이미 대부분 있다"가 있었고,
        `#` 를 선택으로 둔 정규식이 그 **백분율 58** 을 태스크 58 로 읽었다.
        `#` 를 요구하도록 좁히자 이 경로의 오탐 13건이 전부 사라졌다(남은 것은 0건).

        번호 앞의 `#` 는 사람이 "이걸 가리킨다"고 표시한 것이다. 표시 없는 숫자는
        백분율·개수·연도일 수 있고, 검증 없이 이으면 보드가 없는 링크를 말한다.
        """
        dec = decision(4, why="실측이 반박했다 — 태스크→Phase 95%, 결정→태스크 58% 로 "
                             "연결은 이미 대부분 있다")
        self.assertEqual([], server.links_for_task(58, [dec], {"58"}))

    def test_a_hash_marked_reference_in_a_decision_does_count(self):
        dec = decision(4, why="태스크 #58 에서 드러났다")
        found = server.links_for_task(58, [dec], {"58"})
        self.assertEqual(["decision_text"], found[0]["via"])

    def test_a_decision_pointing_at_a_nonexistent_task_is_ignored(self):
        """검증 없이 이으면 보드가 없는 링크를 말한다."""
        dec = decision(4, why="태스크 #999 에서 드러났다")
        self.assertEqual([], server.links_for_task(999, [dec], {"1", "2"}))


class ReachesTheArchiveTest(unittest.TestCase):
    """2,141건 중 대부분이 아카이브에 있다. hot 만 보면 링크 조회가 반쪽이다."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "vh_ke_links", os.path.join(SCRIPTS, "kanban_edit.py"))
        cls.ke = importlib.util.module_from_spec(spec)
        sys.modules["vh_ke_links"] = cls.ke
        spec.loader.exec_module(cls.ke)

    def board(self, hot=(), archived=(), decisions=()):
        import json
        import tempfile
        d = os.path.join(tempfile.mkdtemp(), "vibe-harness")
        os.makedirs(d)
        with open(os.path.join(d, "kanban.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "next_id": 500, "tasks": list(hot)}, fh,
                      ensure_ascii=False)
        if archived:
            os.makedirs(os.path.join(d, "archive"))
            with open(os.path.join(d, "archive", "2026-01.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"tasks": list(archived)}, fh, ensure_ascii=False)
        with open(os.path.join(d, "decisions.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "decisions": list(decisions)}, fh,
                      ensure_ascii=False)
        return d

    def test_an_archived_task_can_be_asked_about(self):
        d = self.board(hot=[task(1)], archived=[task(62, "결정 #2 를 따랐다")],
                       decisions=[decision(2)])
        out = self.ke.show_task(d, 62)
        self.assertEqual([2], [x["id"] for x in out["links"]])

    def test_it_works_without_a_server(self):
        """이 테스트는 소켓을 열지 않는다. 그게 요점이다."""
        d = self.board(hot=[task(1, "결정 #5 에 따라")], decisions=[decision(5)])
        self.assertEqual([5], [x["id"] for x in self.ke.show_task(d, 1)["links"]])

    def test_a_missing_task_is_an_error_not_an_empty_answer(self):
        d = self.board(hot=[task(1)], decisions=[])
        with self.assertRaises(SystemExit):
            self.ke.show_task(d, 404)


class ServedOverHttpTest(unittest.TestCase):
    """없는 태스크에 빈 목록을 돌려주면 '관련 결정이 없다'로 읽힌다."""

    def test_the_route_filters_and_reports_via(self):
        import json
        import tempfile
        import threading
        import urllib.error
        import urllib.request
        d = os.path.join(tempfile.mkdtemp(), "vibe-harness")
        os.makedirs(d)
        with open(os.path.join(d, "kanban.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "next_id": 9,
                       "tasks": [task(3, "결정 #1 에 따라")]}, fh, ensure_ascii=False)
        with open(os.path.join(d, "decisions.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "decisions": [decision(1)]}, fh, ensure_ascii=False)

        saved = server.load_projects
        server.load_projects = lambda: {"demo": {"name": "D", "kanban_dir": d}}
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d/api/demo/decisions" % httpd.server_port
        try:
            with urllib.request.urlopen(base + "?task=3", timeout=10) as r:
                doc = json.loads(r.read())
            self.assertEqual(["task_text"], doc["decisions"][0]["via"])

            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(base + "?task=404", timeout=10)
            self.assertEqual(404, caught.exception.code)
            caught.exception.close()

            with urllib.request.urlopen(base, timeout=10) as r:
                self.assertEqual(1, len(json.loads(r.read())),
                                 "필터 없이 부르면 결정 전체여야 한다")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
            server.load_projects = saved


class NoReverseFieldWasAddedTest(unittest.TestCase):
    """**이 Phase 의 원칙이다.** 필드를 늘리면 그게 두 번째 `depends_on` 이 된다."""

    def test_the_schema_gained_no_reverse_field(self):
        with open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8") as fh:
            body = fh.read()
        for invented in ("decision_ids", "related_decisions", "linked_decisions"):
            self.assertNotIn('"%s"' % invented, body,
                             "역방향 필드를 만들었다 — 두 방향은 반드시 갈라진다")

    def test_new_tasks_do_not_get_a_links_field(self):
        """계산 결과를 저장하면 그 순간부터 원본과 갈라진다."""
        data, created = server._new_task({"version": 1, "next_id": 1, "tasks": []},
                                         {"title": "새 태스크"})
        self.assertNotIn("links", created)


if __name__ == "__main__":
    unittest.main()
