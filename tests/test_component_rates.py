"""단가표와 비용 분해.

2026-08 실측에서 두 가지가 드러났다.

1. 단가표가 낡았다. opus 가 $15/$75 로 잡혀 있는데 Opus 5 는 $5/$25 다 — 3배 과대계상.
   sonnet 도 Sonnet 5($2/$10)가 아니라 4.6($3/$15) 값이고, fable-5($10/$50)는 표에 없어
   _default($3/$15)로 떨어져 3.3배 과소계상된다.
2. cost_usd 가 한 덩어리라 "무엇이 비용을 끌었는지" 사후 분해가 불가능하다. 실제로 캐시
   읽기가 비용의 대부분인데 화면에는 총 토큰과 총 비용만 있어 해석이 어긋났다.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import reconcile_runs  # noqa: E402


class ComponentRatesTest(unittest.TestCase):
    def test_opus_uses_current_pricing_not_legacy(self):
        """Opus 5/4.8/4.7 은 $5/$25 다. 낡은 $15/$75 를 쓰면 비용이 3배로 부풀려진다."""
        r = reconcile_runs._rates("claude-opus-5")

        self.assertAlmostEqual(0.000005, r["in"])
        self.assertAlmostEqual(0.000025, r["out"])

    def test_cache_rates_derive_from_input_rate(self):
        """캐시 읽기 0.1x, 캐시 쓰기 1.25x — 입력 단가에서 파생된다."""
        r = reconcile_runs._rates("claude-opus-5")

        self.assertAlmostEqual(r["in"] * 0.1, r["cr"])
        self.assertAlmostEqual(r["in"] * 1.25, r["cw"])

    def test_fable_has_its_own_rate_not_default(self):
        """fable-5 는 $10/$50 로 opus 보다 비싸다. _default 로 떨어지면 과소계상된다."""
        r = reconcile_runs._rates("claude-fable-5")

        self.assertAlmostEqual(0.000010, r["in"])
        self.assertAlmostEqual(0.000050, r["out"])

    def test_sonnet_5_and_4_6_are_priced_separately(self):
        """Sonnet 5 는 $2/$10, Sonnet 4.6 은 $3/$15 — 'sonnet' 한 덩어리로 묶으면 틀린다."""
        five = reconcile_runs._rates("claude-sonnet-5")
        four_six = reconcile_runs._rates("claude-sonnet-4-6")

        self.assertAlmostEqual(0.000002, five["in"])
        self.assertAlmostEqual(0.000003, four_six["in"])

    def test_haiku_unchanged(self):
        r = reconcile_runs._rates("claude-haiku-4-5")

        self.assertAlmostEqual(0.000001, r["in"])
        self.assertAlmostEqual(0.000005, r["out"])

    def test_unknown_model_falls_back(self):
        self.assertEqual(reconcile_runs.COMPONENT_RATES["_default"],
                         reconcile_runs._rates("some-unknown-model"))


class CostBreakdownTest(unittest.TestCase):
    def test_breakdown_splits_cost_by_token_type(self):
        """총액만으로는 캐시가 비용을 끌었는지 알 수 없다 — 타입별로 나눠 기록한다."""
        b = reconcile_runs.cost_breakdown("claude-opus-5",
                                          input_tokens=1_000_000, output_tokens=1_000_000,
                                          cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)

        self.assertAlmostEqual(5.0, b["in"])
        self.assertAlmostEqual(25.0, b["out"])
        self.assertAlmostEqual(0.5, b["cr"])
        self.assertAlmostEqual(6.25, b["cw"])

    def test_breakdown_sums_to_total(self):
        b = reconcile_runs.cost_breakdown("claude-opus-5", 1000, 2000, 3000, 4000)

        self.assertAlmostEqual(b["total"], b["in"] + b["out"] + b["cr"] + b["cw"], places=9)

    def test_daily_rows_carry_the_breakdown(self):
        """runs.json 행이 분해를 들고 있어야 대시보드가 사후 추정 없이 쓸 수 있다."""
        rows = reconcile_runs.build_daily_runs(self._transcripts())

        self.assertEqual(1, len(rows))
        cb = rows[0]["cost_breakdown"]
        self.assertEqual({"in", "out", "cr", "cw"}, set(cb))
        self.assertAlmostEqual(rows[0]["cost_usd"], sum(cb.values()), places=6)

    def _transcripts(self):
        import json
        import tempfile
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "s1.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "timestamp": "2026-08-19T10:00:00+09:00",
                "message": {"model": "claude-opus-5", "usage": {
                    "input_tokens": 100, "output_tokens": 200,
                    "cache_read_input_tokens": 300, "cache_creation_input_tokens": 400}},
            }) + "\n")
        self.addCleanup(lambda: None)
        return d


if __name__ == "__main__":
    unittest.main()
