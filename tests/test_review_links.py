"""리뷰가 가리키는 태스크가 실재하는지 검사한다.

## 왜 필요한가

`history.json` 의 `priorities` 에는 category·severity·consecutive_weeks 는 있었지만
**태스크나 결정을 가리키는 필드가 없었다.** 그래서 W36 의 P1(워킹트리 공유, 3주 연속
critical)이 어느 태스크로 닫혔는지 링크로 따라갈 수 없었다 — PMF11 에서 그것을 닫을 때
**기억으로 이었고, 기억은 세션이 끝나면 사라진다.**

`schema_version: 2` 에서 `tasks`·`decisions` 를 둘 수 있게 했다.

## 이 검사가 지키는 것

**리뷰가 없는 태스크를 가리키면 그게 끊긴 링크다.** 끊긴 링크는 없는 것보다 나쁘다 —
답이 있는 것처럼 보인다. 같은 규율을 태스크→결정(`missing: true`)에도 적용했다.

## CI 에서는 건너뛴다

리뷰는 이제 `private/` 에 쌓인다(공개 레포에 사람 점수를 두지 않기로 한 결정).
`private/` 는 gitignore 라 CI 가 볼 수 없다 — `test_plan_docs` 와 같은 구조다.
없는 것을 실패로 만들면 CI 가 항상 빨개져서 아무도 안 본다.
"""
import json
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(ROOT, "private", "reviews", "history.json")
KANBAN_DIR = os.path.join(ROOT, "vibe-harness")


def board_ids():
    ids = set()
    kp = os.path.join(KANBAN_DIR, "kanban.json")
    if os.path.exists(kp):
        with open(kp, encoding="utf-8") as fh:
            ids |= {str(t.get("id")) for t in json.load(fh).get("tasks") or []}
    adir = os.path.join(KANBAN_DIR, "archive")
    if os.path.isdir(adir):
        for name in sorted(os.listdir(adir)):
            if name.endswith(".json"):
                with open(os.path.join(adir, name), encoding="utf-8") as fh:
                    ids |= {str(t.get("id")) for t in json.load(fh).get("tasks") or []}
    return ids


def decision_ids():
    p = os.path.join(KANBAN_DIR, "decisions.json")
    if not os.path.exists(p):
        return set()
    with open(p, encoding="utf-8") as fh:
        return {str(d.get("id")) for d in json.load(fh).get("decisions") or []}


def entries():
    """(회차, 항목) — priorities 와 resolved 를 함께."""
    with open(HISTORY, encoding="utf-8") as fh:
        doc = json.load(fh)
    out = []
    for review in doc.get("reviews") or []:
        label = review.get("period", {}).get("label")
        for key in ("priorities", "resolved"):
            for item in review.get(key) or []:
                out.append((label, key, item))
    return doc, out


class ReviewLinksResolveTest(unittest.TestCase):
    def setUp(self):
        if not os.path.exists(HISTORY):
            self.skipTest("private/reviews/history.json 없음 (CI)")

    def test_every_referenced_task_exists(self):
        """**끊긴 링크는 없는 링크보다 나쁘다** — 답이 있는 것처럼 보인다."""
        ids = board_ids()
        _doc, items = entries()
        broken = []
        for label, key, item in items:
            for tid in item.get("tasks") or []:
                if str(tid) not in ids:
                    broken.append("%s/%s %r → 태스크 %s" % (label, key,
                                                          item.get("category"), tid))
        self.assertEqual([], broken, "리뷰가 없는 태스크를 가리킨다: " + "; ".join(broken))

    def test_every_referenced_decision_exists(self):
        ids = decision_ids()
        _doc, items = entries()
        broken = [(label, item.get("category"), d)
                  for label, _key, item in items
                  for d in item.get("decisions") or [] if str(d) not in ids]
        self.assertEqual([], broken, "리뷰가 없는 결정을 가리킨다: %s" % (broken,))

    def test_the_schema_says_it_uses_links(self):
        """필드를 쓰면서 버전을 안 올리면 읽는 쪽이 없는 줄 안다."""
        doc, items = entries()
        uses = any(item.get("tasks") or item.get("decisions") for _l, _k, item in items)
        if uses:
            self.assertGreaterEqual(doc.get("schema_version", 1), 2)

    def test_the_series_is_not_split(self):
        """리뷰는 시리즈다. 회차가 두 디렉토리로 갈리면 추이를 이을 수 없다.

        공개 레포의 4회분은 **샘플로 동결**하고, 시리즈는 여기서 이어간다.
        그래서 이 파일에 과거 회차가 전부 들어 있어야 한다.
        """
        doc, _items = entries()
        labels = [r["period"]["label"] for r in doc["reviews"]]
        for past in ("2026-W33", "2026-W35", "2026-W35r", "2026-W36"):
            self.assertIn(past, labels, "과거 회차가 빠졌다 — 추이가 끊긴다")

    def test_a_repeated_priority_carries_its_week_count(self):
        """반복은 세지 않으면 반복인 줄 모른다."""
        _doc, items = entries()
        for label, key, item in items:
            if key == "priorities" and item.get("status") == "repeated":
                self.assertGreaterEqual(item.get("consecutive_weeks", 0), 2,
                                        "%s: repeated 인데 주 수가 없다" % label)


class TheRuleIsInTheSkillTest(unittest.TestCase):
    """규칙이 스킬에 없으면 다음 리뷰가 다시 아무것도 가리키지 않는다."""

    def skill(self):
        with open(os.path.join(ROOT, "skills", "vibe-review", "SKILL.md"),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_it_documents_the_fields(self):
        body = self.skill()
        self.assertIn("Point the priorities at something", body)
        self.assertIn('"tasks"', body)

    def test_it_says_to_verify_the_id_first(self):
        """없는 id 를 적으면 끊긴 링크가 된다 — 그 경고가 있어야 한다."""
        self.assertIn("Only ids you verified exist", self.skill())

    def test_it_prefers_empty_over_guessed(self):
        self.assertIn("Leave it out rather than guess", self.skill())


if __name__ == "__main__":
    unittest.main()
