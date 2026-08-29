"""Claude + Codex 를 한 번의 수집으로 합친다.

지금까지 Codex 는 수집기만 있고 reconcile 흐름에 연결돼 있지 않아, 별도로 호출하지
않으면 runs.json 에 쌓이지 않았다. 에이전트가 늘 때마다 사람이 따로 돌려야 하는 구조는
결국 빠뜨린다 — 한 번의 수집이 양쪽을 다 담아야 한다.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import reconcile_runs  # noqa: E402


class CollectRunsTest(unittest.TestCase):
    def setUp(self):
        self.claude = tempfile.mkdtemp()
        self.codex = tempfile.mkdtemp()

    def _claude_session(self, name="c1"):
        path = os.path.join(self.claude, name + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "timestamp": "2026-08-19T10:00:00+09:00",
                "message": {"model": "claude-opus-5", "usage": {
                    "input_tokens": 100, "output_tokens": 200,
                    "cache_read_input_tokens": 300, "cache_creation_input_tokens": 0}},
            }) + "\n")

    def _codex_session(self, cwd, name="x1"):
        path = os.path.join(self.codex, name + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "session_meta", "payload": {
                "cwd": cwd, "timestamp": "2026-08-19T01:00:00.000Z",
                "session_id": "cx-" + name}}) + "\n")
            fh.write(json.dumps({"type": "turn_context",
                                 "payload": {"model": "gpt-5.6-sol"}}) + "\n")
            fh.write(json.dumps({"payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 1000, "cached_input_tokens": 400,
                                      "output_tokens": 50, "cache_write_input_tokens": 0}}}}) + "\n")

    def test_collects_both_agents_in_one_pass(self):
        self._claude_session()
        self._codex_session("/x/proj")

        runs = reconcile_runs.collect_runs(self.claude, cwd="/x/proj",
                                           codex_sessions=self.codex)

        self.assertEqual({"claude", "codex"}, {r["agent"] for r in runs})

    def test_codex_rows_carry_ts_so_they_merge_like_claude_rows(self):
        """merge_runs 는 session_id 로 묶고 dry-run 은 ts[:10] 을 읽는다. ts 가 없으면 깨진다."""
        self._codex_session("/x/proj")

        runs = reconcile_runs.collect_runs(self.claude, cwd="/x/proj",
                                           codex_sessions=self.codex)

        codex = [r for r in runs if r["agent"] == "codex"][0]
        self.assertTrue(codex.get("ts"), "codex 행에 ts 가 없다")
        self.assertEqual("2026-08-19", codex["ts"][:10])
        self.assertTrue(codex.get("session_id"))

    def test_other_projects_codex_sessions_are_excluded(self):
        self._codex_session("/x/mine", name="mine")
        self._codex_session("/x/other", name="other")

        runs = reconcile_runs.collect_runs(self.claude, cwd="/x/mine",
                                           codex_sessions=self.codex)

        self.assertEqual(1, len([r for r in runs if r["agent"] == "codex"]))

    def test_without_cwd_no_codex_rows_are_guessed(self):
        """프로젝트를 특정하지 못하면 남의 세션을 끌어오지 않는다."""
        self._codex_session("/x/proj")

        runs = reconcile_runs.collect_runs(self.claude, cwd=None,
                                           codex_sessions=self.codex)

        self.assertEqual([], [r for r in runs if r["agent"] == "codex"])

    def test_claude_rows_record_cost_breakdown_too(self):
        """build_runs 도 분해를 남긴다 — 비용 계산이 세 곳에 흩어져 있었다."""
        self._claude_session()

        runs = reconcile_runs.collect_runs(self.claude, cwd=None,
                                           codex_sessions=self.codex)

        claude = [r for r in runs if r["agent"] == "claude"][0]
        self.assertEqual({"in", "out", "cr", "cw"}, set(claude["cost_breakdown"]))


if __name__ == "__main__":
    unittest.main()
