"""기록된 cost_usd 를 현행 단가로 재계산한다.

2026-08 이전 행들은 낡은 단가(opus $15/$75)로 계산돼 3배 부풀려져 있다. 단가표만
고쳐도 앞으로의 행만 맞고 과거는 틀린 채로 남는다.

재계산은 파괴적이므로 규칙을 좁게 잡는다.
  - 토큰 분해가 없는 행은 건드리지 않는다 (재계산 근거가 없다)
  - 단가를 모르는 agent(codex 등)는 건드리지 않는다
  - 토큰 값 자체는 절대 바꾸지 않는다 — 비용만 다시 센다
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import reconcile_runs  # noqa: E402


def row(**over):
    base = {"session_id": "s1", "date": "2026-08-19", "agent": "claude",
            "model": "claude-opus-5", "tokens": 1_100_000,
            "input_tokens": 100_000, "output_tokens": 0,
            "cache_read_tokens": 1_000_000, "cache_write_tokens": 0,
            "cost_usd": 3.0}
    base.update(over)
    return base


class RecostTest(unittest.TestCase):
    def test_recomputes_with_current_rates(self):
        """입력 100k×$5/1M + 캐시읽기 1M×$0.5/1M = $0.5 + $0.5 = $1.0 (기존 $3.0 은 3배값)."""
        rows, changed = reconcile_runs.recost_rows([row()])

        self.assertEqual(1, changed)
        self.assertAlmostEqual(1.0, rows[0]["cost_usd"], places=6)

    def test_adds_breakdown(self):
        rows, _ = reconcile_runs.recost_rows([row()])

        self.assertAlmostEqual(0.5, rows[0]["cost_breakdown"]["in"], places=6)
        self.assertAlmostEqual(0.5, rows[0]["cost_breakdown"]["cr"], places=6)

    def test_token_counts_are_never_modified(self):
        before = row()
        rows, _ = reconcile_runs.recost_rows([dict(before)])

        for k in ("tokens", "input_tokens", "output_tokens",
                  "cache_read_tokens", "cache_write_tokens"):
            self.assertEqual(before[k], rows[0][k], k)

    def test_row_without_breakdown_is_left_alone(self):
        """분해가 없으면 재계산할 근거가 없다. 총 tokens 만으로 추정하지 않는다."""
        r = {"agent": "claude", "model": "claude-opus-5", "tokens": 500, "cost_usd": 9.9}

        rows, changed = reconcile_runs.recost_rows([r])

        self.assertEqual(0, changed)
        self.assertEqual(9.9, rows[0]["cost_usd"])

    def test_codex_rows_untouched_while_pricing_unknown(self):
        r = row(agent="codex", model="gpt-5.6-codex", cost_usd=0)

        rows, changed = reconcile_runs.recost_rows([r])

        self.assertEqual(0, changed)
        self.assertEqual(0, rows[0]["cost_usd"])
        self.assertNotIn("cost_breakdown", rows[0])

    def test_is_idempotent(self):
        """두 번 돌려도 두 번째는 변경 0 — 재실행이 안전해야 반복 적용할 수 있다.

        (첫 실행에서는 비용이 이미 맞더라도 cost_breakdown 이 새로 붙으므로 변경으로 센다.)
        """
        rows, first = reconcile_runs.recost_rows([row()])
        rows, second = reconcile_runs.recost_rows(rows)

        self.assertEqual(1, first)
        self.assertEqual(0, second)

    def test_unknown_claude_model_uses_default_and_still_recosts(self):
        rows, changed = reconcile_runs.recost_rows([row(model="claude-weird")])

        self.assertEqual(1, changed)
        self.assertGreater(rows[0]["cost_usd"], 0)


if __name__ == "__main__":
    unittest.main()
