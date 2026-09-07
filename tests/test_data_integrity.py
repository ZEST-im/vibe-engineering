"""kanban·runs·decisions JSON 의 불변식을 고정한다.

CLAUDE.md 가 규정한 규율(id 재사용 금지, 완료 시 details·lines 필수,
runs.json append-only)은 문서에만 있고 어디서도 강제되지 않았다. 여기서 강제한다.
"""
import importlib.util
import json
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "vibe-harness")
SCRIPTS = os.path.join(ROOT, "scripts")


def board_statuses():
    """보드가 아는 status. **server.py 에서 가져온다 — 여기 다시 적지 않는다.**

    적었다가 어긋났다. 이 검사는 넷만 알고 있었는데 서버의 새 태스크 기본값은
    `backlog` 라, 서버로 만든 태스크가 곧바로 불변식 위반이 됐다. 검사가 정상 데이터를
    위반으로 부르면 고쳐지는 건 데이터 쪽이다 — 그게 더 나쁘다.
    """
    sys.path.insert(0, SCRIPTS)
    spec = importlib.util.spec_from_file_location("vh_server_status",
                                                  os.path.join(SCRIPTS, "server.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("vh_server_status", mod)
    spec.loader.exec_module(mod)
    return tuple(mod.BOARD_STATUSES)


BOARD_STATUSES = board_statuses()

RUN_TOKEN_FIELDS = ("tokens", "input_tokens", "output_tokens",
                    "cache_read_tokens", "cache_write_tokens")


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return json.load(fh)


def archived_tasks():
    """archive/YYYY-MM.json 에 옮겨진 태스크.

    아카이브는 kanban.json 을 가볍게 유지하려고 done 을 월별로 빼낸 것이다.
    id 불변식은 **아카이브까지 합쳐야** 참이다 — kanban 만 보면 아카이브된 id 를
    재사용해도 잡히지 않는다.
    """
    adir = os.path.join(DATA, "archive")
    if not os.path.isdir(adir):
        return []
    out = []
    for name in sorted(os.listdir(adir)):
        if name.endswith(".json"):
            with open(os.path.join(adir, name), encoding="utf-8") as fh:
                out.extend(json.load(fh).get("tasks", []))
    return out


def load_server():
    """server.py 를 한 번만 읽는다.

    `setdefault` 만 쓰면 부를 때마다 새 모듈 객체를 만들어 exec 하므로, 같은 함수를
    두 번 가져와도 서로 다른 객체가 된다 — "정본이 하나"를 검사할 수가 없다.
    """
    cached = sys.modules.get("vh_server_ids")
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(
        "vh_server_ids", os.path.join(SCRIPTS, "server.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vh_server_ids"] = mod
    spec.loader.exec_module(mod)
    return mod


# **여기 다시 구현하지 않는다.** 예전엔 같은 규칙이라 적어두고 실제로는 달랐다 —
# 이쪽은 `(\d+)$` 로 접두어를 벗겼고 server 는 `int(id)` 라 접두어 id 를 통째로
# 건너뛰었다. 그래서 `_mint_id` 의 중복 방지 보정이 접두어 보드에서 죽어 있었고,
# `next_id: 5` 인 보드에 `hg40`·`hg41` 이 있으면 `hg5` 가 발급됐다.
id_number = load_server().id_number


class IdNumberingSurvivesPrefixesTest(unittest.TestCase):
    """접두어가 붙어도 번호 수열은 하나다.

    ## 조용히 꺼져 있던 안전망

    `_mint_id` 에는 "next_id 가 실제 최대값보다 뒤처져 있으면 발급 직전에 맞춘다"는
    보정이 있다. 그런데 `_numeric_ids` 가 `int(id)` 라 **접두어 id 를 통째로
    건너뛰었다.** 접두어를 쓰는 보드에서는 그 보정이 아무것도 보지 못했다.

    재현: `next_id: 5` 인 보드에 `hg40`·`hg41` 이 있으면 다음 발급이 **`hg5`** 였다.
    중복을 막으려고 둔 장치가 중복 생성기가 된 것이다.
    """

    def test_a_prefixed_board_still_corrects_a_stale_next_id(self):
        srv = load_server()
        board = {"next_id": 5, "tasks": [{"id": "hg40"}, {"id": "hg41"}]}
        self.assertEqual("hg42", srv._mint_id(board, "hg")[0],
                         "접두어 보드에서 중복 방지 보정이 죽어 있다")

    def test_a_mixed_case_prefix_is_read(self):
        """머신을 가르는 접두어(`hgB`)에는 대문자가 들어간다."""
        srv = load_server()
        self.assertEqual(99, srv.id_number("hgB99"))
        board = {"next_id": 1, "tasks": [{"id": "hgB99"}]}
        self.assertEqual("hgB100", srv._mint_id(board, "hgB")[0])

    def test_bare_numbers_still_work(self):
        srv = load_server()
        self.assertEqual(93, srv.id_number(93))
        self.assertEqual(93, srv.id_number("93"))

    def test_an_unreadable_id_is_skipped_not_crashing(self):
        srv = load_server()
        self.assertIsNone(srv.id_number("no-digits"))
        self.assertEqual([7], srv._numeric_ids([{"id": "x"}, {"id": "hg7"}]))

    def test_the_two_implementations_are_one(self):
        """예전엔 '같은 규칙'이라 적어두고 실제로는 달랐다. 이제 같은 함수다."""
        self.assertIs(id_number, load_server().id_number)


class KanbanIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.kanban = load("kanban.json")
        self.tasks = self.kanban["tasks"]
        self.archived = archived_tasks()
        self.all_tasks = self.tasks + self.archived

    def test_task_ids_are_unique_across_archive(self):
        ids = [t["id"] for t in self.all_tasks]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(set(), dupes, "중복 id(아카이브 포함): " + str(sorted(dupes)))

    def test_next_id_is_above_every_used_number(self):
        """접두어가 붙어도 번호는 하나의 수열에서 나온다.

        id_prefix 를 켜면 id 가 "hg67" 같은 문자열이 된다. 그래도 next_id 가 세는 것은
        같은 번호이므로, 접두어를 떼고 비교해야 한다. 정수와 문자열을 그대로 비교하면
        TypeError 로 죽는다 — 실제로 그렇게 깨졌다.
        """
        used = [n for n in (id_number(t["id"]) for t in self.all_tasks) if n is not None]
        if not used:
            self.skipTest("번호를 읽을 수 있는 태스크가 없음")
        self.assertGreater(self.kanban["next_id"], max(used),
                           "next_id 가 이미 쓴 번호보다 작거나 같음 — 재사용 위험")

    def test_status_is_a_known_value(self):
        for t in self.all_tasks:
            self.assertIn(t["status"], BOARD_STATUSES,
                          "task %s: 알 수 없는 status %r" % (t["id"], t["status"]))

    def test_the_allowed_set_is_the_five_the_board_documents(self):
        """정본에서 가져오더라도 정본 자체가 줄어들면 조용히 느슨해진다.

        CLAUDE.md 는 5단계를 규정한다. `backlog`/`review` 가 빠지면 보드가 실제 진행을
        표현하지 못하는데, 이 검사는 오히려 더 잘 통과한다 — 그래서 수를 못 박는다.
        """
        self.assertEqual({"backlog", "todo", "in_progress", "review", "done"},
                         set(BOARD_STATUSES),
                         "보드 status 집합이 CLAUDE.md 의 5단계와 다르다")

    def test_done_tasks_carry_a_report(self):
        """CLAUDE.md: 완료 시 details 와 변경량이 필수."""
        for t in self.all_tasks:
            if t["status"] != "done":
                continue
            self.assertTrue((t.get("details") or "").strip(),
                            "task %s: done 인데 details 없음" % t["id"])
            self.assertIsNotNone(t.get("lines_added"),
                                 "task %s: done 인데 lines_added 없음" % t["id"])
            self.assertIsNotNone(t.get("lines_removed"),
                                 "task %s: done 인데 lines_removed 없음" % t["id"])

    def test_at_most_one_task_in_progress_per_person(self):
        """CLAUDE.md: 한 번에 in_progress 는 유저당 1개."""
        counts = {}
        for t in self.all_tasks:
            if t["status"] == "in_progress":
                who = t.get("assigned_to") or t.get("created_by") or "?"
                counts[who] = counts.get(who, 0) + 1
        over = {k: v for k, v in counts.items() if v > 1}
        self.assertEqual({}, over, "in_progress 가 1개를 넘는 담당자: " + str(over))

    def test_every_task_has_a_category(self):
        for t in self.all_tasks:
            self.assertTrue((t.get("category") or "").strip(),
                            "task %s: category 없음" % t["id"])


class RunsIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.runs = load("runs.json")

    def test_keeps_version_field(self):
        """CURRENT_PHASE Do NOT touch: 기존 필드 제거 금지."""
        self.assertIn("version", self.runs)

    def test_session_ids_are_unique(self):
        sids = [r.get("session_id") for r in self.runs["runs"] if r.get("session_id")]
        dupes = {s for s in sids if sids.count(s) > 1}
        self.assertEqual(set(), dupes, "중복 session_id: " + str(sorted(dupes)))

    def test_token_counts_are_non_negative(self):
        for r in self.runs["runs"]:
            for field in RUN_TOKEN_FIELDS:
                value = r.get(field)
                if value is not None:
                    self.assertGreaterEqual(value, 0,
                                            "%s 의 %s 가 음수" % (r.get("session_id"), field))

    def test_total_tokens_are_not_below_their_components(self):
        for r in self.runs["runs"]:
            parts = [r.get(f) or 0 for f in RUN_TOKEN_FIELDS[1:]]
            if r.get("tokens") is not None and any(parts):
                self.assertGreaterEqual(r["tokens"], sum(parts) * 0.99,
                                        "%s: tokens 가 구성요소 합보다 작음" % r.get("session_id"))


class DecisionsIntegrityTest(unittest.TestCase):
    def test_decisions_file_parses_when_present(self):
        path = os.path.join(DATA, "decisions.json")
        if not os.path.exists(path):
            self.skipTest("decisions.json 없음")
        data = load("decisions.json")
        self.assertIsInstance(data, dict)


if __name__ == "__main__":
    unittest.main()
