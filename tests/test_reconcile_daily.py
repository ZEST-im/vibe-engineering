"""일자별 분해(build_daily_runs) — 중앙 저장소로 보낼 (세션 × 일자) 행.

로컬 runs.json 은 세션 단위를 유지한다(불변식 테스트가 그걸 지킨다). 중앙만 일자별
정밀도를 받는다. 레이스 애니메이션이 일별로 정확히 달리려면 세션이 여러 날에 걸칠 때
마지막 날에 전액이 몰리면 안 된다 — 그게 이 모듈이 존재하는 이유다.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

spec = importlib.util.spec_from_file_location(
    "reconcile_runs", os.path.join(SCRIPTS, "reconcile_runs.py"))
reconcile_runs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconcile_runs)


def usage(i=1, o=2, cr=3, cw=4):
    return {
        "input_tokens": i,
        "output_tokens": o,
        "cache_read_input_tokens": cr,
        "cache_creation_input_tokens": cw,
    }


class BuildDailyRunsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.transcripts = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, session_id, messages):
        path = os.path.join(self.transcripts, session_id + ".jsonl")
        with open(path, "w") as fh:
            for m in messages:
                fh.write(json.dumps(m) + "\n")
        return path

    def msg(self, ts, model="claude-opus-5", **kw):
        return {"timestamp": ts, "message": {"model": model, "usage": usage(**kw)}}

    def test_session_spanning_two_days_becomes_two_rows(self):
        self.write("s1", [
            self.msg("2026-08-19T10:00:00+09:00"),
            self.msg("2026-08-20T10:00:00+09:00"),
        ])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual(["2026-08-19", "2026-08-20"], sorted(r["date"] for r in rows))

    def test_row_tokens_count_only_that_days_messages(self):
        self.write("s1", [
            self.msg("2026-08-19T10:00:00+09:00", i=10, o=0, cr=0, cw=0),
            self.msg("2026-08-20T10:00:00+09:00", i=99, o=0, cr=0, cw=0),
        ])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        day19 = next(r for r in rows if r["date"] == "2026-08-19")
        self.assertEqual(10, day19["tokens"])

    def test_daily_rows_sum_to_session_total(self):
        self.write("s1", [
            self.msg("2026-08-19T23:59:59+09:00"),
            self.msg("2026-08-20T00:00:01+09:00"),
        ])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual(20, sum(r["tokens"] for r in rows))  # (1+2+3+4) * 2

    def test_utc_timestamp_is_bucketed_by_kst_calendar_date(self):
        """UTC 2026-08-18T20:00Z 는 KST 로 2026-08-19 새벽이다."""
        self.write("s1", [self.msg("2026-08-18T20:00:00Z")])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual("2026-08-19", rows[0]["date"])

    def test_row_carries_session_id(self):
        self.write("abc-123", [self.msg("2026-08-19T10:00:00+09:00")])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual("abc-123", rows[0]["session_id"])

    def test_row_carries_machine_label(self):
        self.write("s1", [self.msg("2026-08-19T10:00:00+09:00")])

        rows = reconcile_runs.build_daily_runs(self.transcripts, machine="mba-01")

        self.assertEqual("mba-01", rows[0]["machine"])

    def test_does_not_carry_owner_because_central_assigns_it(self):
        """클라이언트가 owner 를 주장하면 위조 경로가 된다 — 서버가 토큰으로 판정한다."""
        self.write("s1", [self.msg("2026-08-19T10:00:00+09:00")])

        rows = reconcile_runs.build_daily_runs(self.transcripts, machine="mba-01")

        self.assertNotIn("owner", rows[0])

    def test_one_row_per_session_and_date(self):
        self.write("s1", [
            self.msg("2026-08-19T09:00:00+09:00"),
            self.msg("2026-08-19T18:00:00+09:00"),
        ])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual(1, len(rows))

    def test_cost_uses_component_rates_of_that_rows_model(self):
        self.write("s1", [self.msg("2026-08-19T10:00:00+09:00",
                                   model="claude-opus-5", i=1000, o=0, cr=0, cw=0)])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        # Opus 5 입력 단가 $5/1M. 2026-08 이전에는 $15/1M(구 Opus 3) 로 고정돼 있었다.
        self.assertAlmostEqual(1000 * 0.000005, rows[0]["cost_usd"], places=6)

    def test_message_without_timestamp_is_skipped(self):
        self.write("s1", [{"message": {"model": "claude-opus-5", "usage": usage()}}])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual([], rows)

    def test_message_without_usage_creates_no_row(self):
        self.write("s1", [{"timestamp": "2026-08-19T10:00:00+09:00", "message": {}}])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual([], rows)

    def test_zero_token_day_creates_no_row(self):
        self.write("s1", [self.msg("2026-08-19T10:00:00+09:00", i=0, o=0, cr=0, cw=0)])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual([], rows)

    def test_subagent_transcripts_in_subdirectories_are_included(self):
        sub = os.path.join(self.transcripts, "sess", "subagents")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-x.jsonl"), "w") as fh:
            fh.write(json.dumps(self.msg("2026-08-19T10:00:00+09:00")) + "\n")

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual(1, len(rows))

    def test_rows_are_sorted_by_date(self):
        self.write("s1", [
            self.msg("2026-08-21T10:00:00+09:00"),
            self.msg("2026-08-19T10:00:00+09:00"),
        ])

        rows = reconcile_runs.build_daily_runs(self.transcripts)

        self.assertEqual(["2026-08-19", "2026-08-21"], [r["date"] for r in rows])


class ChangedRowsTest(unittest.TestCase):
    """증분 push — 3시간마다 전량 재전송하던 낭비를 없앤다.

    로그 증거: zesty_os 가 `ingested: 108, 신규 0건` 을 하루 8회 반복했다.
    """

    def row(self, session_id="s1", date="2026-08-19", tokens=10):
        return {"session_id": session_id, "date": date, "tokens": tokens,
                "cost_usd": 0.1, "model": "claude-opus-5"}

    def test_all_rows_are_new_when_state_is_empty(self):
        rows = [self.row()]

        self.assertEqual(rows, reconcile_runs.changed_rows({}, rows))

    def test_unchanged_row_is_not_resent(self):
        rows = [self.row()]
        state = reconcile_runs.push_state_for(rows)

        self.assertEqual([], reconcile_runs.changed_rows(state, rows))

    def test_row_whose_tokens_grew_is_resent(self):
        state = reconcile_runs.push_state_for([self.row(tokens=10)])
        grown = [self.row(tokens=20)]

        self.assertEqual(grown, reconcile_runs.changed_rows(state, grown))

    def test_new_date_for_known_session_is_resent(self):
        state = reconcile_runs.push_state_for([self.row(date="2026-08-19")])
        rows = [self.row(date="2026-08-19"), self.row(date="2026-08-20")]

        self.assertEqual([self.row(date="2026-08-20")], reconcile_runs.changed_rows(state, rows))

    def test_same_date_different_session_is_its_own_row(self):
        state = reconcile_runs.push_state_for([self.row(session_id="s1")])
        rows = [self.row(session_id="s1"), self.row(session_id="s2")]

        self.assertEqual([self.row(session_id="s2")], reconcile_runs.changed_rows(state, rows))

    def test_state_survives_json_round_trip(self):
        rows = [self.row()]
        state = json.loads(json.dumps(reconcile_runs.push_state_for(rows)))

        self.assertEqual([], reconcile_runs.changed_rows(state, rows))


class MachineIdTest(unittest.TestCase):
    def test_sync_config_override_wins_over_hostname(self):
        self.assertEqual("mba-01", reconcile_runs.machine_id({"machine": "mba-01"}))

    def test_falls_back_to_hostname_when_not_configured(self):
        import socket

        self.assertEqual(socket.gethostname(), reconcile_runs.machine_id({}))

    def test_blank_override_falls_back_to_hostname(self):
        import socket

        self.assertEqual(socket.gethostname(), reconcile_runs.machine_id({"machine": "  "}))


if __name__ == "__main__":
    unittest.main()
