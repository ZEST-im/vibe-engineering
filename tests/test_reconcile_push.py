"""중앙 전송 — 증분 push 와 스키마 전환.

중앙(zestim)은 아직 일자별 스키마를 모른다. 그래서 기본 동작은 지금과 100% 동일해야
하고, sync.json 의 runs_schema=2 로 옵트인했을 때만 일자별 증분으로 바뀐다. 중앙이
준비되기 전에 클라이언트가 먼저 바뀌면 전사 수집이 조용히 멈춘다.
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


class Sender:
    """전송된 payload 를 기록하는 가짜 전송자. 네트워크를 타지 않는다."""

    def __init__(self, fail=False):
        self.payloads = []
        self.fail = fail

    def __call__(self, url, payload):
        self.payloads.append(payload)
        if self.fail:
            raise RuntimeError("central down")
        return {"ok": True}

    @property
    def calls(self):
        return len(self.payloads)


class PushBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kanban = os.path.join(self.tmp.name, "vibe-harness")
        self.transcripts = os.path.join(self.tmp.name, "transcripts")
        os.makedirs(self.kanban)
        os.makedirs(self.transcripts)
        self.state_path = os.path.join(self.tmp.name, "push-state.json")
        self._prev_state = reconcile_runs.PUSH_STATE_PATH
        reconcile_runs.PUSH_STATE_PATH = self.state_path
        self._prev_cfg = reconcile_runs._sync_cfg
        self.cfg = {"endpoint": "https://example.test/sync", "secret": "s",
                    "runs_schema": 2, "machine": "mba-01"}
        reconcile_runs._sync_cfg = lambda: self.cfg

    def tearDown(self):
        reconcile_runs.PUSH_STATE_PATH = self._prev_state
        reconcile_runs._sync_cfg = self._prev_cfg
        self.tmp.cleanup()

    def write_transcript(self, session_id, entries):
        path = os.path.join(self.transcripts, session_id + ".jsonl")
        with open(path, "a") as fh:
            for ts, tok in entries:
                fh.write(json.dumps({
                    "timestamp": ts,
                    "message": {"model": "claude-opus-5",
                                "usage": {"input_tokens": tok, "output_tokens": 0,
                                          "cache_read_input_tokens": 0,
                                          "cache_creation_input_tokens": 0}},
                }) + "\n")
        return path

    def run_reconcile(self, sender, force_full=False):
        reconcile_runs.reconcile("proj", self.kanban, self.transcripts,
                                 push=True, sender=sender, force_full=force_full)


class EmptyRegistryTest(unittest.TestCase):
    """새 머신은 projects.json 이 비어 있다. 조용히 0건 처리하면 "성공했는데 데이터가
    없는" 상태가 되고, 그게 이 제품이 반복해서 실패해 온 방식이다."""

    def setUp(self):
        self.orig_projects = reconcile_runs._projects
        self.orig_argv = sys.argv

    def tearDown(self):
        reconcile_runs._projects = self.orig_projects
        sys.argv = self.orig_argv

    def test_all_with_empty_registry_fails_loudly(self):
        reconcile_runs._projects = lambda: {}
        sys.argv = ["reconcile_runs.py", "--all", "--dry-run"]

        with self.assertRaises(SystemExit) as ctx:
            reconcile_runs.main()

        self.assertIn("projects.json", str(ctx.exception))

    def test_all_with_registry_that_matches_nothing_fails_loudly(self):
        """등록은 됐지만 transcript 가 하나도 안 잡히는 경우도 조용해선 안 된다."""
        reconcile_runs._projects = lambda: {"proj": {"kanban_dir": "/nonexistent/vibe-harness"}}
        sys.argv = ["reconcile_runs.py", "--all", "--dry-run"]

        with self.assertRaises(SystemExit) as ctx:
            reconcile_runs.main()

        self.assertIn("0개", str(ctx.exception))


class PushCredentialTest(unittest.TestCase):
    """스냅샷 secret 과 run 전송 토큰은 다른 자격증명이다.

    /sync(스냅샷)는 프로젝트 단위 공유 secret 만 인정하고, /runs(사람별 귀속)는 개인
    토큰을 요구한다. 한 필드에 뭉개면 개인 토큰으로 덮어쓰는 순간 스냅샷이 401 로 죽는다.
    실제로 그렇게 깨뜨린 뒤에 이 테스트를 넣었다.
    """

    def test_uses_runs_token_when_present(self):
        cred = reconcile_runs.push_credential({"secret": "shared", "runs_token": "personal"})

        self.assertEqual("personal", cred)

    def test_falls_back_to_shared_secret(self):
        self.assertEqual("shared", reconcile_runs.push_credential({"secret": "shared"}))

    def test_blank_runs_token_falls_back(self):
        cred = reconcile_runs.push_credential({"secret": "shared", "runs_token": "  "})

        self.assertEqual("shared", cred)

    def test_no_credential_at_all_is_empty(self):
        self.assertEqual("", reconcile_runs.push_credential({}))

    def test_push_without_any_credential_aborts(self):
        with self.assertRaises(SystemExit):
            reconcile_runs._push_central({"endpoint": "https://e/sync"}, {"project": "p", "runs": []})


class IncrementalPushTest(PushBase):
    def test_first_push_sends_the_row(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        sender = Sender()

        self.run_reconcile(sender)

        self.assertEqual(["2026-08-19"], [r["date"] for r in sender.payloads[0]["runs"]])

    def test_second_push_sends_nothing_when_no_new_usage(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        self.run_reconcile(Sender())
        sender = Sender()

        self.run_reconcile(sender)

        self.assertEqual(0, sender.calls)

    def test_only_the_changed_day_is_resent(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        self.run_reconcile(Sender())
        self.write_transcript("s1", [("2026-08-20T10:00:00+09:00", 5)])
        sender = Sender()

        self.run_reconcile(sender)

        self.assertEqual(["2026-08-20"], [r["date"] for r in sender.payloads[0]["runs"]])

    def test_growing_day_is_resent_with_new_total(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        self.run_reconcile(Sender())
        self.write_transcript("s1", [("2026-08-19T18:00:00+09:00", 7)])
        sender = Sender()

        self.run_reconcile(sender)

        self.assertEqual(17, sender.payloads[0]["runs"][0]["tokens"])

    def test_state_is_not_saved_when_push_fails(self):
        """실패한 전송을 보냈다고 기록하면 그 행은 영구히 유실된다."""
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        try:
            self.run_reconcile(Sender(fail=True))
        except Exception:
            pass
        sender = Sender()

        self.run_reconcile(sender)

        self.assertEqual(1, len(sender.payloads[0]["runs"]))

    def test_force_full_resends_rows_already_sent(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        self.run_reconcile(Sender())
        sender = Sender()

        self.run_reconcile(sender, force_full=True)

        self.assertEqual(1, len(sender.payloads[0]["runs"]))

    def test_state_of_one_project_does_not_suppress_another(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        self.run_reconcile(Sender())
        other = os.path.join(self.tmp.name, "other")
        os.makedirs(other)
        sender = Sender()

        reconcile_runs.reconcile("other-proj", other, self.transcripts,
                                 push=True, sender=sender)

        self.assertEqual(1, len(sender.payloads[0]["runs"]))


class PayloadTest(PushBase):
    def test_schema2_payload_declares_its_schema(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        sender = Sender()

        self.run_reconcile(sender)

        self.assertEqual(2, sender.payloads[0]["schema"])

    def test_schema2_payload_carries_machine_label(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        sender = Sender()

        self.run_reconcile(sender)

        self.assertEqual("mba-01", sender.payloads[0]["machine"])

    def test_schema2_rows_do_not_claim_an_owner(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        sender = Sender()

        self.run_reconcile(sender)

        self.assertNotIn("owner", sender.payloads[0]["runs"][0])


class LegacySchemaTest(PushBase):
    """runs_schema 를 켜지 않은 머신은 지금과 완전히 같이 동작해야 한다."""

    def setUp(self):
        super().setUp()
        self.cfg = {"endpoint": "https://example.test/sync", "secret": "s"}
        reconcile_runs._sync_cfg = lambda: self.cfg

    def test_default_config_sends_session_level_runs(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10),
                                     ("2026-08-20T10:00:00+09:00", 10)])
        sender = Sender()

        self.run_reconcile(sender)

        self.assertEqual(1, len(sender.payloads[0]["runs"]))

    def test_default_config_omits_schema_field(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        sender = Sender()

        self.run_reconcile(sender)

        self.assertNotIn("schema", sender.payloads[0])

    def test_default_config_resends_every_run_as_before(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10)])
        self.run_reconcile(Sender())
        sender = Sender()

        self.run_reconcile(sender)

        self.assertEqual(1, len(sender.payloads[0]["runs"]))


class LocalFileTest(PushBase):
    """로컬 runs.json 은 세션 단위를 유지한다 — 마이그레이션 위험 0."""

    def test_local_runs_stay_session_level_without_date_field(self):
        self.write_transcript("s1", [("2026-08-19T10:00:00+09:00", 10),
                                     ("2026-08-20T10:00:00+09:00", 10)])

        self.run_reconcile(Sender())

        with open(os.path.join(self.kanban, "runs.json")) as fh:
            runs = json.load(fh)["runs"]
        self.assertEqual(1, len(runs))
        self.assertNotIn("date", runs[0])


if __name__ == "__main__":
    unittest.main()
