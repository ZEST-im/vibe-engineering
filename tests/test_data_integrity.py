"""kanban·runs·decisions JSON 의 불변식을 고정한다.

CLAUDE.md 가 규정한 규율(id 재사용 금지, 완료 시 details·lines 필수,
runs.json append-only)은 문서에만 있고 어디서도 강제되지 않았다. 여기서 강제한다.
"""
import json
import re
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "vibe-harness")

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


def id_number(task_id):
    """id 에서 번호만 뽑는다. 접두어가 붙어도(hg67) 같은 수열이다.

    server.py 의 _numeric_ids 와 같은 규칙 — 읽을 수 없으면 None 이고 비교에서 빠진다.
    """
    if isinstance(task_id, int):
        return task_id
    m = re.search(r"(\d+)$", str(task_id or ""))
    return int(m.group(1)) if m else None


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
            self.assertIn(t["status"], ("todo", "in_progress", "done", "review"),
                          "task %s: 알 수 없는 status %r" % (t["id"], t["status"]))

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
