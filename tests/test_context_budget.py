"""세션 시작 컨텍스트의 in_progress 비대칭을 고정한다.

`recent_done` 은 `_task_digest` 를 거쳐 제목만 싣는데 `in_progress` 는 details 전량이었다.
한 프로젝트가 in_progress 6건으로 /context 36KB 중 20,899B 를 차지한 적이 있다.

**그런데 단순 절삭은 반대 방향이다.** in_progress details 는 "지금 뭘 하고 있나"라
세션 시작에 실제로 필요한 정보다. 그것을 깎으면 절감이 아니라 손실이다.

그래서 예산제로 간다. 두 가지를 동시에 지켜야 한다.

1. **가장 최근 착수한 것은 예산을 넘기더라도 온전히 싣는다.** 하나뿐인 활성 태스크의
   details 가 길다는 이유로 잘리면 이 엔드포인트의 쓸모가 사라진다.
2. **뺀 것은 뺐다고 말한다.** 조용히 사라지는 것이 이 레포가 반복해 온 실패 방식이다.

규율(담당자당 1건)이 깨진 것도 payload 에 싣는다. 페이로드가 커지는 근본 원인이
규율 위반이므로, 크기를 줄이는 것보다 원인을 말하는 쪽이 낫다.
"""
import importlib.util
import json
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("srv_budget", os.path.join(SCRIPTS, "server.py"))
srv = importlib.util.module_from_spec(_spec)
sys.modules["srv_budget"] = srv
_spec.loader.exec_module(srv)


def task(tid, details_len=0, started="2026-08-01T00:00:00+09:00", who="hogun"):
    return {
        "id": tid,
        "title": f"작업 {tid}",
        "status": "in_progress",
        "category": "infra",
        "phase": "PHASE_X",
        "details": "가" * details_len,
        "started_at": started,
        "assigned_to": who,
        "lines_added": 0,
        "lines_removed": 0,
    }


def size(payload):
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class BudgetTest(unittest.TestCase):
    def test_single_task_keeps_full_details_even_over_budget(self):
        """활성 태스크가 하나뿐이면 길어도 온전해야 한다 — 자르면 엔드포인트가 쓸모없다."""
        big = srv.IN_PROGRESS_DETAIL_BUDGET * 3
        out, note = srv._in_progress_payload([task(1, big)])
        self.assertEqual(big, len(out[0]["details"]))
        self.assertIsNone(note)

    def test_extra_tasks_fall_back_to_digest(self):
        tasks = [task(i, 3000, started=f"2026-08-0{i}T00:00:00+09:00") for i in (1, 2, 3)]
        out, note = srv._in_progress_payload(tasks)
        full = [t for t in out if "details" in t]
        digested = [t for t in out if "details" not in t]
        self.assertEqual(1, len(full), "예산을 넘겨서까지 원문을 싣고 있다")
        self.assertEqual(2, len(digested))
        self.assertIsNotNone(note)

    def test_most_recently_started_is_the_one_kept(self):
        old = task(1, 3000, started="2026-08-01T00:00:00+09:00")
        new = task(2, 3000, started="2026-08-28T00:00:00+09:00")
        out, _ = srv._in_progress_payload([old, new])
        self.assertIn("details", out[0])
        self.assertEqual(2, out[0]["id"], "가장 최근 착수한 것이 온전해야 한다")

    def test_omission_is_announced_not_silent(self):
        tasks = [task(i, 5000, started=f"2026-08-0{i}T00:00:00+09:00") for i in (1, 2)]
        out, note = srv._in_progress_payload(tasks)
        self.assertIn("details 를 뺐다", note)
        omitted = [t for t in out if "details_omitted_chars" in t]
        self.assertEqual(1, len(omitted))
        self.assertEqual(5000, omitted[0]["details_omitted_chars"],
                         "얼마나 뺐는지 숫자로 남아야 조회할지 판단할 수 있다")

    def test_digest_keeps_what_identifies_the_task(self):
        tasks = [task(i, 5000, started=f"2026-08-0{i}T00:00:00+09:00") for i in (1, 2)]
        out, _ = srv._in_progress_payload(tasks)
        digested = [t for t in out if "details_omitted_chars" in t][0]
        for key in ("id", "title", "category", "phase"):
            self.assertIn(key, digested, f"digest 에 {key} 가 없으면 무엇이 빠졌는지 모른다")

    def test_extra_tasks_cost_digest_not_details(self):
        """지키려는 성질은 총량이 아니라 **한계비용**이다.

        태스크가 하나 늘 때 details 만큼 늘면 규율이 깨질수록 선형으로 커진다.
        digest 만큼만 늘어야 한다. (예산은 '자' 단위, 크기는 바이트라 총량으로
        단언하면 한글 3바이트 때문에 단위가 어긋난다 — 실제로 한 번 어긋났다.)
        """
        one = [task(1, 4000, started="2026-08-01T00:00:00+09:00")]
        many = [task(i, 4000, started=f"2026-08-{i:02d}T00:00:00+09:00") for i in range(1, 11)]
        base = size(srv._in_progress_payload(one)[0])
        grown = size(srv._in_progress_payload(many)[0])
        per_extra = (grown - base) / 9
        self.assertLess(per_extra, 400,
                        "태스크 하나당 %.0fB 씩 는다 — digest 가 아니라 details 가 실리고 있다"
                        % per_extra)

    def test_no_tasks_is_empty_and_quiet(self):
        out, note = srv._in_progress_payload([])
        self.assertEqual([], out)
        self.assertIsNone(note)

    def test_missing_started_at_does_not_crash(self):
        t = task(1, 100)
        del t["started_at"]
        out, _ = srv._in_progress_payload([t])
        self.assertEqual(1, len(out))


class DisciplineIsSurfacedTest(unittest.TestCase):
    """페이로드가 커지는 원인은 규율 위반이다. 크기를 줄이기보다 원인을 말한다."""

    def build(self, tasks):
        owners = {}
        for t in tasks:
            who = t.get("assigned_to") or t.get("created_by") or "?"
            owners[who] = owners.get(who, 0) + 1
        return sorted(k for k, v in owners.items() if v > 1)

    def test_one_per_person_is_clean(self):
        self.assertEqual([], self.build([task(1, who="hogun"), task(2, who="jina")]))

    def test_two_for_one_person_is_flagged(self):
        self.assertEqual(["hogun"],
                         self.build([task(1, who="hogun"), task(2, who="hogun")]))

    def test_context_exposes_the_fields(self):
        """계산만 맞고 노출이 빠지면 아무도 못 본다."""
        with open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8") as fh:
            body = fh.read()
        for field in ('"in_progress_note"', '"in_progress_over_limit"'):
            self.assertIn(field, body, f"/context 응답에 {field} 가 없다")


if __name__ == "__main__":
    unittest.main()
