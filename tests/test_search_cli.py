"""검색이 **서버 없이** 도는 것을 고정한다.

## 왜 이게 구조적으로 중요한가

1단계 검색은 `GET /api/{key}/search` 로만 됐다. 그런데 CLAUDE.md 는 **"서버가 꺼져
있어도 정상"** 이라고 규정하고 system of record 는 JSON 파일이다.
**정상이라고 규정한 상태에서 안 되는 기능**을 두는 것은 앞뒤가 안 맞는다.

그래서 `scripts/search.py` 가 정본이고 **서버가 그것을 부른다.** 반대가 아니다 —
구현이 둘이면 갈라지고, 갈라지면 한쪽만 코퍼스가 좁아져도 아무도 모른다.

이 파일이 지키는 것 셋:

1. **서버를 띄우지 않고도 찾는다.** 이 파일의 어떤 테스트도 소켓을 열지 않는다.
2. **서버와 같은 답을 낸다.** 두 경로가 다른 답을 내면 구현이 갈라진 것이다.
3. **코퍼스 범위가 고정된다.** 드리프트의 위험은 읽는 방식이 아니라 *보는 범위*에 있다.
"""
import importlib.util
import io
import json
import os
import sys
import contextlib
import subprocess
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("vh_search_cli",
                                               os.path.join(SCRIPTS, "search.py"))
se = importlib.util.module_from_spec(_spec)
sys.modules["vh_search_cli"] = se
_spec.loader.exec_module(se)


def board(tasks=(), archived=(), decisions=()):
    d = os.path.join(tempfile.mkdtemp(), "vibe-harness")
    os.makedirs(d)
    with open(os.path.join(d, "kanban.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "next_id": 99, "tasks": list(tasks)}, fh,
                  ensure_ascii=False)
    if archived:
        os.makedirs(os.path.join(d, "archive"))
        with open(os.path.join(d, "archive", "2026-01.json"), "w", encoding="utf-8") as fh:
            json.dump({"tasks": list(archived)}, fh, ensure_ascii=False)
    if decisions:
        with open(os.path.join(d, "decisions.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "decisions": list(decisions)}, fh, ensure_ascii=False)
    return d


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, env=env, check=True)


def task(tid, title="제목", details="", when="2026-01-01T00:00:00+09:00"):
    return {"id": tid, "title": title, "details": details, "status": "done",
            "completed_at": when}


class WorksWithoutTheServerTest(unittest.TestCase):
    """이 클래스의 어떤 테스트도 소켓을 열지 않는다. 그게 요점이다."""

    def test_finds_without_any_server(self):
        d = board(tasks=[task(1, details="바늘이 여기 있다")])
        self.assertEqual(1, se.search(d, "바늘")["total"])

    def test_the_cli_prints_what_it_found(self):
        d = board(tasks=[task(1, "이중 계상 정리")])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = se.main(["--dir", d, "이중", "계상"])
        self.assertEqual(0, code)
        self.assertIn("이중 계상 정리", buf.getvalue())

    def test_the_cli_can_emit_json(self):
        d = board(tasks=[task(1, "이중 계상 정리")])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            se.main(["--dir", d, "--json", "계상"])
        self.assertEqual(1, json.loads(buf.getvalue())["total"])

    def test_multi_word_query_is_one_phrase(self):
        """`search.py 이중 계상` 이 두 질의가 되면 안 된다."""
        d = board(tasks=[task(1, "이중 계상 정리")])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            se.main(["--dir", d, "--json", "이중", "계상"])
        self.assertEqual("이중 계상", json.loads(buf.getvalue())["query"])

    def test_a_wrong_path_is_an_error_not_zero_hits(self):
        """**"찾았는데 없다"와 "찾을 데가 없다"는 다르다.**

        경로가 틀렸는데 `0건` 을 돌려주면 "그런 기록은 없구나"로 읽힌다. 이 Phase 가
        죽이려는 형태가 정확히 그것이다 — 조용히 틀린 답.
        """
        with self.assertRaises(SystemExit):
            se.main(["--dir", tempfile.mkdtemp(), "아무거나"])

    def test_the_library_says_so_too(self):
        """CLI 만 막으면 서버 경유로는 그대로 조용한 0건이 된다."""
        out = se.search(tempfile.mkdtemp(), "아무거나")
        self.assertEqual(0, out["total"])
        self.assertIn("안 찾았다", out.get("note", ""))

    def test_a_real_board_carries_no_such_warning(self):
        out = se.search(board(tasks=[task(1, details="바늘")]), "바늘")
        self.assertNotIn("안 찾았다", out.get("note", ""))

    def test_it_reports_how_much_it_scanned(self):
        """0건일 때 '코퍼스가 몇 건이었나'가 없으면 검색기를 의심할 근거가 없다."""
        d = board(tasks=[task(1), task(2)], archived=[task(3)])
        self.assertEqual(3, se.search(d, "없는말xyz")["records_scanned"])


class FindsTheBoardFromAnywhereTest(unittest.TestCase):
    """프로젝트 어디서 불러도 같은 보드를 찾아야 쓰인다."""

    def test_walks_up_to_the_board(self):
        d = board(tasks=[task(1)])
        deep = os.path.join(os.path.dirname(d), "a", "b", "c")
        os.makedirs(deep)
        self.assertEqual(d, se.find_kanban_dir(deep))

    def test_returns_none_outside_a_project(self):
        self.assertIsNone(se.find_kanban_dir(tempfile.mkdtemp()))


class AgreesWithTheServerTest(unittest.TestCase):
    """두 경로가 다른 답을 내면 구현이 갈라진 것이다."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "vh_server_cli_cmp", os.path.join(SCRIPTS, "server.py"))
        cls.server = importlib.util.module_from_spec(spec)
        sys.modules["vh_server_cli_cmp"] = cls.server
        spec.loader.exec_module(cls.server)

    def test_same_answer(self):
        d = board(tasks=[task(1, "이중 계상 정리")],
                  archived=[task(2, details="아카이브 속 이중 계상")],
                  decisions=[{"id": 3, "title": "왜", "why": "이중 계상 때문"}])
        self.assertEqual(se.search(d, "이중 계상"), self.server._search(d, "이중 계상"))

    def test_the_server_does_not_carry_its_own_copy(self):
        """서버가 자기 구현을 들면 두 경로가 갈라진다."""
        self.assertIs(self.server._search, self.server._SEARCH.search)
        with open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertNotIn("def _search(", body,
                         "server.py 가 검색을 다시 구현하고 있다")


class CorpusIsPinnedTest(unittest.TestCase):
    """드리프트의 위험은 읽는 방식이 아니라 **보는 범위**에 있다."""

    def test_it_covers_the_three_json_sources(self):
        d = board(tasks=[task(1, details="바늘")],
                  archived=[task(2, details="바늘")],
                  decisions=[{"id": 3, "title": "t", "why": "바늘"}])
        found = {r[0] for r in se.records(d, include_docs=False, include_commits=False)}
        self.assertEqual({"task", "archive", "decision"}, found)

    def test_the_declared_sources_match_what_it_reads(self):
        """`SOURCES` 가 문서가 아니라 사실이어야 한다.

        다섯 출처 전부가 실제로 나오는지 본다 — 목록에만 있고 안 읽히면 그 목록은
        거짓말이고, 반대로 읽는데 목록에 없으면 아무도 그것을 기대하지 않는다.
        """
        d = board(tasks=[task(1, details="바늘")],
                  archived=[task(2, details="바늘")],
                  decisions=[{"id": 3, "title": "t", "why": "바늘"}])
        root = os.path.dirname(d)
        with open(os.path.join(root, "note.md"), "w", encoding="utf-8") as fh:
            fh.write("# 메모\n바늘\n")
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "바늘을 심는다")
        self.assertEqual(set(se.SOURCES),
                         {h["source"] for h in se.search(d, "바늘")["hits"]})

    def test_a_broken_file_does_not_kill_the_whole_search(self):
        """깨진 파일 하나 때문에 나머지를 못 찾으면 그게 더 나쁘다."""
        d = board(tasks=[task(1, details="바늘")])
        with open(os.path.join(d, "decisions.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual(1, se.search(d, "바늘")["total"])


class ReachesDocsAndCommitsTest(unittest.TestCase):
    """**밖에 있는 코퍼스가 안의 4~6배였다.**

    실측(2026-09-06): codebook_vibe 는 JSON 547 KB 대 마크다운 2,918 KB + 커밋 619 KB.
    `북극성` 은 문서에 있는데 검색은 0건을 냈다 — 1단계가 JSON 만 봤기 때문이다.
    """

    def project(self, docs=None, commits=()):
        d = board(tasks=[task(1, "보드에만 있는 것")])
        root = os.path.dirname(d)
        for rel, body in (docs or {}).items():
            full = os.path.join(root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(body)
        if commits:
            git(root, "init", "-q", "-b", "main")
            for message in commits:
                git(root, "add", "-A")
                git(root, "commit", "-q", "--allow-empty", "-m", message)
        return d, root

    def test_finds_in_markdown(self):
        d, _root = self.project(docs={"docs/PROGRESS.md": "# 진행\n북극성은 여기 있다\n"})
        hits = se.search(d, "북극성")["hits"]
        self.assertEqual(1, len(hits))
        self.assertEqual("doc", hits[0]["source"])

    def test_a_doc_hit_can_be_opened(self):
        """파일만 알려주고 줄을 안 주면 큰 문서에서 다시 찾아야 한다."""
        body = "\n".join(["머리말"] * 20 + ["여기에 북극성"])
        d, _root = self.project(docs={"docs/PROGRESS.md": body})
        self.assertEqual("docs/PROGRESS.md:21", se.search(d, "북극성")["hits"][0]["locator"])

    def test_a_doc_gets_its_own_heading_as_a_title(self):
        d, _root = self.project(docs={"docs/PROGRESS.md": "# 진행 상황\n북극성\n"})
        self.assertIn("진행 상황", se.search(d, "북극성")["hits"][0]["title"])

    def test_finds_in_commit_messages(self):
        """이 프로젝트는 설계 근거를 커밋 본문에 쌓아왔다. 문서만 넣으면 절반이다."""
        d, _root = self.project(commits=["fix: 이중 계상을 걷어낸다"])
        hits = se.search(d, "이중 계상")["hits"]
        self.assertEqual("commit", hits[0]["source"])

    def test_a_commit_hit_says_how_to_open_it(self):
        d, _root = self.project(commits=["fix: 이중 계상을 걷어낸다"])
        self.assertTrue(se.search(d, "이중 계상")["hits"][0]["locator"].startswith("git show "))

    def test_source_code_is_not_in_the_corpus(self):
        """비용이 아니라 **희석** 때문이다 — grep 이 더 잘하고, 넣으면 문서가 묻힌다.

        **`source` 라벨을 보면 안 된다.** 처음에 그렇게 썼는데, `.py` 를 `DOC_SUFFIXES`
        에 넣는 위반을 주입하니 코드가 `doc` 으로 들어오면서 라벨 검사가 그대로 통과했다.
        무엇이 들어왔는지는 **경로**가 말한다.
        """
        d, root = self.project(docs={"docs/a.md": "문서 속 바늘"})
        for name in ("code.py", "app.ts", "style.css"):
            with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                fh.write("// 코드 속 바늘\n")
        ids = {h["id"] for h in se.search(d, "바늘")["hits"]}
        self.assertEqual({"docs/a.md"}, ids, "소스코드가 코퍼스에 들어왔다")

    def test_the_doc_suffix_list_is_markdown_only(self):
        """확장자를 하나 늘리는 것으로 이 결정이 뒤집힌다. 목록 자체를 못 박는다."""
        self.assertEqual({".md", ".mdx"}, set(se.DOC_SUFFIXES),
                         "문서 확장자 목록이 바뀌었다 — 소스코드를 넣지 않기로 한 결정을 "
                         "다시 확인할 것")

    def test_generated_and_ignored_files_are_skipped(self):
        """무엇이 진짜 내용인지는 프로젝트가 `.gitignore` 로 이미 답해뒀다.

        실제로 필요했다 — e2e 픽스처(`test_temp/`)가 코퍼스에 섞여 들어왔다.
        """
        d, root = self.project(docs={"docs/real.md": "진짜 바늘",
                                     "test_temp/fixture.md": "가짜 바늘"})
        with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write("test_temp/\n")
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init")
        ids = {h["id"] for h in se.search(d, "바늘")["hits"] if h["source"] == "doc"}
        self.assertEqual({"docs/real.md"}, ids, "gitignore 된 픽스처가 검색됐다")

    def test_private_is_included_on_purpose(self):
        """추적되지 않지만 **일부러** 넣는다.

        이 도구의 규약상 Phase 계획과 결정 근거가 `private/` 에 산다(CLAUDE.md).
        그게 정확히 이 검색이 찾아야 할 것이다. 검색은 로컬에서만 돌고 아무 데도
        보내지 않으므로 공개 위험이 없다.
        """
        d, root = self.project(docs={"private/PHASES.md": "북극성 결정"})
        with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write("private/\n")
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "commit", "-q", "--allow-empty", "-m", "init")
        ids = {h["id"] for h in se.search(d, "북극성")["hits"]}
        self.assertIn("private/PHASES.md", ids)

    def test_a_giant_generated_doc_does_not_dominate(self):
        d, _root = self.project(docs={"docs/huge.md": "바늘" + "가" * (600 * 1024)})
        self.assertEqual(0, se.search(d, "바늘")["total"],
                         "512KB 넘는 문서가 코퍼스에 들어왔다")

    def test_a_repo_without_git_still_searches_docs(self):
        """git 이 없다고 문서 검색이 통째로 죽으면 안 된다."""
        d, _root = self.project(docs={"docs/a.md": "바늘"})
        self.assertEqual(1, se.search(d, "바늘")["total"])


class DoesNotWanderTest(unittest.TestCase):
    """경계를 모르는 채로 걸어 들어가면 엉뚱한 디렉토리를 통째로 코퍼스에 넣는다.

    실제로 났다 — 픽스처가 공유 임시 디렉토리에 보드를 만들자 **다른 테스트의 파일이
    코퍼스에 섞였고**, 스위트가 1.3초에서 20초가 됐다. 프로덕션에서 같은 일이 나는
    경로도 있다: `kanban_dir` 을 `~/vibe-harness` 로 등록하면 부모가 홈 전체다.

    git 저장소면 `git ls-files` 가 경계를 알려주므로 이 문제가 없다. 없을 때만 상한이 든다.
    """

    def test_the_walk_is_capped_without_git(self):
        root = tempfile.mkdtemp()
        d = os.path.join(root, "vibe-harness")
        os.makedirs(d)
        with open(os.path.join(d, "kanban.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "next_id": 1, "tasks": []}, fh)
        for i in range(12):
            with open(os.path.join(root, "d%02d.md" % i), "w", encoding="utf-8") as fh:
                fh.write("바늘\n")
        rels, capped = se._walked_docs(root, cap=5)
        self.assertTrue(capped, "상한에 안 걸렸다 — 무한정 걸어 들어간다")
        self.assertEqual(5, len(rels))

    def test_an_uncapped_walk_reports_no_cap(self):
        root = tempfile.mkdtemp()
        with open(os.path.join(root, "a.md"), "w", encoding="utf-8") as fh:
            fh.write("바늘")
        rels, capped = se._walked_docs(root, cap=100)
        self.assertFalse(capped)
        self.assertEqual(["a.md"], rels)

    def test_a_git_repo_needs_no_cap(self):
        """추적 목록이 경계를 알려주므로 상한이 개입할 일이 없다."""
        d = board(tasks=[task(1)])
        root = os.path.dirname(d)
        with open(os.path.join(root, "a.md"), "w", encoding="utf-8") as fh:
            fh.write("바늘")
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init")
        self.assertIsNotNone(se._tracked_docs(root))

    def test_callers_can_scope_to_json_only(self):
        """서버·CLI 말고도 부르는 곳이 생기면 범위를 좁힐 수 있어야 한다."""
        d = board(tasks=[task(1, details="바늘")])
        with open(os.path.join(os.path.dirname(d), "a.md"), "w", encoding="utf-8") as fh:
            fh.write("문서 속 바늘")
        wide = se.search(d, "바늘")
        narrow = se.search(d, "바늘", include_docs=False, include_commits=False)
        self.assertEqual(2, wide["total"])
        self.assertEqual(1, narrow["total"])


class RanksExplainablyTest(unittest.TestCase):
    """코퍼스를 넓히자 순위가 필수가 됐다.

    codebook_vibe 에서 `마이그레이션` 은 **138건**이 걸리는데 10건만 실린다
    (확장 전에는 51건이었다). 최신순뿐이면 찾던 것이 11번째일 때 못 찾고,
    `total` 이 정직하게 138이라 말해도 해결되지 않는다 — 볼 수 있는 건 10건이다.

    실측(2026-09-06), 제목에 질의가 든 히트가 몇 번째로 올라오는가:

        codebook_vibe  커버리지      26번째 → 1번째
        codebook_vibe  마이그레이션    8번째 → 1번째
        vibe-engineering API        15번째 → 1번째

    limit 10 에서 "26번째"는 **아예 안 보였다**는 뜻이다.
    """

    def one(self, **fields):
        base = {"id": fields.pop("id", 1), "status": "done",
                "completed_at": "2026-01-01T00:00:00+09:00"}
        base.update(fields)
        return base

    def test_a_title_match_outranks_a_body_match(self):
        d = board(tasks=[self.one(id=1, title="무관", details="바늘 " * 3),
                         self.one(id=2, title="바늘 이야기", details="무관")])
        hits = se.search(d, "바늘", limit=5)["hits"]
        self.assertEqual(2, hits[0]["id"], "제목 매치가 본문 매치보다 아래에 있다")

    def test_more_matches_rank_higher(self):
        d = board(tasks=[self.one(id=1, details="바늘"),
                         self.one(id=2, details="바늘 바늘 바늘 바늘 바늘")])
        self.assertEqual(2, se.search(d, "바늘", limit=5)["hits"][0]["id"])

    def test_a_short_focused_record_beats_a_long_incidental_one(self):
        """짧은 결정 하나가 거대한 리뷰 문서에 묻히지 않아야 한다."""
        d = board(tasks=[self.one(id=1, details="바늘 " + "무관한 말 " * 4000),
                         self.one(id=2, details="바늘")])
        self.assertEqual(2, se.search(d, "바늘", limit=5)["hits"][0]["id"])

    def test_recency_is_the_tiebreaker_not_the_ranking(self):
        """최근성을 버리지 않는다 — 작업 로그에서 최신은 실제로 좋은 신호다.

        다만 **동점일 때만** 쓴다. 점수가 다르면 점수가 이긴다.
        """
        old_strong = self.one(id=1, title="바늘", details="바늘 바늘",
                              completed_at="2020-01-01T00:00:00+09:00")
        new_weak = self.one(id=2, title="무관", details="바늘",
                            completed_at="2026-09-01T00:00:00+09:00")
        hits = se.search(board(tasks=[old_strong, new_weak]), "바늘", limit=5)["hits"]
        self.assertEqual(1, hits[0]["id"], "최신이 점수를 이겼다")

        tie_old = self.one(id=3, details="바늘", completed_at="2020-01-01T00:00:00+09:00")
        tie_new = self.one(id=4, details="바늘", completed_at="2026-09-01T00:00:00+09:00")
        hits = se.search(board(tasks=[tie_old, tie_new]), "바늘", limit=5)["hits"]
        self.assertEqual(4, hits[0]["id"], "동점인데 최신이 위로 안 왔다")

    def test_every_hit_says_why_it_ranked(self):
        """**근거 없는 순위는 고칠 수 없다.**

        이 레포는 출처를 함께 주는 것을 규율로 삼아왔다(source·id·locator).
        순위도 같아야 한다 — 틀렸을 때 왜 틀렸는지 알아야 고친다.
        """
        d = board(tasks=[self.one(id=1, title="바늘", details="바늘 바늘")])
        hit = se.search(d, "바늘", limit=5)["hits"][0]
        self.assertGreater(hit["score"], 0)
        why = hit["why_ranked"]
        self.assertEqual({"title", "details"}, set(why["fields"]))
        self.assertEqual(2, why["fields"]["details"]["hits"])
        self.assertGreater(why["fields"]["title"]["weight"],
                           why["fields"]["details"]["weight"],
                           "제목이 본문보다 무겁지 않다")
        self.assertIn("length_factor", why)

    def test_scoring_needs_no_index(self):
        """BM25·임베딩을 기각한 근거는 '색인이 푸는 문제가 없다'였다.

        점수 계산이 코퍼스 전체 통계(IDF 등)를 필요로 하면 그 결정이 무너진다 —
        레코드 하나만 주고도 점수가 나와야 한다.
        """
        points, why = se.score_record({"title": "바늘"}, "바늘")
        self.assertGreater(points, 0)
        self.assertEqual({"title"}, set(why["fields"]))

    def test_a_non_matching_record_scores_zero(self):
        self.assertEqual((0.0, {}), se.score_record({"title": "무관"}, "바늘"))


if __name__ == "__main__":
    unittest.main()
