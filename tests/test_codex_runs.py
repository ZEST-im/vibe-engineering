"""Codex 세션 토큰 수집.

지금까지 harness 는 ~/.claude/projects/ 만 읽고 agent 를 "claude" 로 하드코딩했다.
그래서 Codex 사용량이 장부에서 통째로 빠져 있었다 — 2026-08 실측으로 총량 +11.5%,
출력 기준 6.1% 가 누락돼 있었다.

⚠️ 토큰 의미가 Claude 와 다르다. 여기서 틀리면 조용히 이중계상된다.
  Claude: input_tokens(캐시 제외) + cache_read_input_tokens(별도)
  Codex : input_tokens(캐시 포함 총량), cached_input_tokens 는 그 부분집합
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import reconcile_runs  # noqa: E402


def _event(inp, cached, out, cw=0):
    return {"payload": {"type": "token_count", "info": {"total_token_usage": {
        "input_tokens": inp, "cached_input_tokens": cached,
        "cache_write_input_tokens": cw, "output_tokens": out,
        "total_tokens": inp + out}}}}


def _meta(cwd, ts="2026-08-19T01:00:00.000Z", model="gpt-5.6-codex"):
    return {"type": "session_meta",
            "payload": {"cwd": cwd, "timestamp": ts, "model": model,
                        "session_id": "01a0-test"}}


class CodexRunsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def write(self, name, lines):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        return path

    def test_cached_input_is_split_out_not_double_counted(self):
        """Codex 의 input_tokens 는 캐시를 포함한 총량이다. 그대로 쓰면 이중계상된다."""
        self.write("rollout-2026-08-19T10-00-00-abc.jsonl",
                   [_meta("/x/proj"), _event(inp=19379, cached=11008, out=360)])

        rows = reconcile_runs.build_codex_daily_runs(self.dir)

        self.assertEqual(1, len(rows))
        r = rows[0]
        self.assertEqual(19379 - 11008, r["input_tokens"])   # 캐시 제외 실입력
        self.assertEqual(11008, r["cache_read_tokens"])
        self.assertEqual(360, r["output_tokens"])
        self.assertEqual(19379 + 360, r["tokens"])           # 총량은 보존

    def test_agent_is_codex_not_claude(self):
        self.write("rollout-2026-08-19T10-00-00-abc.jsonl",
                   [_meta("/x/proj"), _event(1000, 0, 100)])

        rows = reconcile_runs.build_codex_daily_runs(self.dir)

        self.assertEqual("codex", rows[0]["agent"])
        self.assertEqual("codex", rows[0]["source"].split("-")[0])

    def test_last_cumulative_event_wins(self):
        """total_token_usage 는 누적값이라 마지막 것만 취해야 한다. 합치면 폭증한다."""
        self.write("rollout-2026-08-19T10-00-00-abc.jsonl",
                   [_meta("/x/proj"), _event(100, 0, 10), _event(500, 0, 50)])

        rows = reconcile_runs.build_codex_daily_runs(self.dir)

        self.assertEqual(500, rows[0]["input_tokens"])
        self.assertEqual(50, rows[0]["output_tokens"])

    def test_cost_is_not_fabricated_when_pricing_unknown(self):
        """OpenAI 단가를 모르면 비용을 지어내지 않는다 — 0 으로 두고 토큰만 기록한다."""
        self.write("rollout-2026-08-19T10-00-00-abc.jsonl",
                   [_meta("/x/proj"), _event(1000, 0, 100)])

        rows = reconcile_runs.build_codex_daily_runs(self.dir)

        self.assertEqual(0, rows[0]["cost_usd"])
        self.assertNotIn("cost_breakdown", rows[0])

    def test_rows_are_scoped_to_the_requested_cwd(self):
        """runs.json 은 프로젝트별이다. 다른 프로젝트의 세션이 섞이면 안 된다."""
        self.write("a.jsonl", [_meta("/x/mine"), _event(1000, 0, 100)])
        self.write("b.jsonl", [_meta("/x/other"), _event(9999, 0, 999)])

        rows = reconcile_runs.build_codex_daily_runs(self.dir, cwd="/x/mine")

        self.assertEqual(1, len(rows))
        self.assertEqual(1000, rows[0]["input_tokens"])

    def test_session_without_token_events_is_skipped(self):
        self.write("a.jsonl", [_meta("/x/proj")])

        self.assertEqual([], reconcile_runs.build_codex_daily_runs(self.dir))

    def test_date_comes_from_session_timestamp_in_kst(self):
        """2026-08-19T01:00Z = KST 10:00 → 업무일자는 08-19."""
        self.write("a.jsonl", [_meta("/x/proj", ts="2026-08-19T01:00:00.000Z"),
                               _event(10, 0, 1)])

        rows = reconcile_runs.build_codex_daily_runs(self.dir)

        self.assertEqual("2026-08-19", rows[0]["date"])

    def test_utc_late_evening_maps_to_next_kst_day(self):
        """2026-08-19T16:00Z = KST 익일 01:00 → 08-20."""
        self.write("a.jsonl", [_meta("/x/proj", ts="2026-08-19T16:00:00.000Z"),
                               _event(10, 0, 1)])

        rows = reconcile_runs.build_codex_daily_runs(self.dir)

        self.assertEqual("2026-08-20", rows[0]["date"])


if __name__ == "__main__":
    unittest.main()
