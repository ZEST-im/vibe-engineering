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

spec = importlib.util.spec_from_file_location("reconcile_runs", os.path.join(SCRIPTS, "reconcile_runs.py"))
reconcile_runs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconcile_runs)


def hook_run(**updates):
    """record-run 훅이 쓴 기존 run 한 건."""
    run = {
        "task_id": None,
        "agent": "claude",
        "model": "claude-opus-4-8",
        "tokens": 91056417,
        "input_tokens": 66630,
        "output_tokens": 553209,
        "cache_read_tokens": 86381909,
        "cache_write_tokens": 4054669,
        "time_seconds": None,
        "commit": "030afa5",
        "session_id": "71a08bd7",
        "ts": "2026-07-07T16:30:21",
    }
    run.update(updates)
    return run


def transcript_run(**updates):
    """build_runs()가 transcript에서 재구성한 run 한 건."""
    run = {
        "task_id": None,
        "agent": "claude",
        "model": "claude-fable-5",
        "tokens": 777489,
        "input_tokens": 13932,
        "output_tokens": 10187,
        "cache_read_tokens": 701354,
        "cache_write_tokens": 52016,
        "cost_usd": 0.51,
        "session_id": "7d886a6b",
        "commit": "",
        "ts": "2026-07-23T09:51:13+09:00",
        "source": "transcript-reconcile",
    }
    run.update(updates)
    return run


class MergeRunsTest(unittest.TestCase):
    def test_keeps_existing_run_that_has_no_transcript(self):
        existing = {"version": 1, "runs": [hook_run()]}

        merged = reconcile_runs.merge_runs(existing, [transcript_run()])

        sids = [r["session_id"] for r in merged["runs"]]
        self.assertIn("71a08bd7", sids)

    def test_keeps_top_level_version(self):
        existing = {"version": 1, "runs": []}

        merged = reconcile_runs.merge_runs(existing, [transcript_run()])

        self.assertEqual(1, merged["version"])

    def test_appends_run_for_new_session(self):
        existing = {"version": 1, "runs": [hook_run()]}

        merged = reconcile_runs.merge_runs(existing, [transcript_run()])

        self.assertEqual(2, len(merged["runs"]))
        self.assertEqual("7d886a6b", merged["runs"][-1]["session_id"])

    def test_keeps_fields_reconcile_does_not_produce(self):
        existing = {"version": 1, "runs": [hook_run(session_id="7d886a6b")]}

        merged = reconcile_runs.merge_runs(existing, [transcript_run(session_id="7d886a6b")])

        self.assertIn("time_seconds", merged["runs"][0])

    def test_does_not_blank_existing_commit(self):
        existing = {"version": 1, "runs": [hook_run(session_id="7d886a6b")]}

        merged = reconcile_runs.merge_runs(existing, [transcript_run(session_id="7d886a6b", commit="")])

        self.assertEqual("030afa5", merged["runs"][0]["commit"])

    def test_raises_token_count_when_transcript_is_more_complete(self):
        existing = {"version": 1, "runs": [hook_run(session_id="7d886a6b", tokens=1000)]}

        merged = reconcile_runs.merge_runs(existing, [transcript_run(session_id="7d886a6b", tokens=16255693)])

        self.assertEqual(16255693, merged["runs"][0]["tokens"])

    def test_does_not_lower_token_count_recorded_by_hook(self):
        existing = {"version": 1, "runs": [hook_run(session_id="7d886a6b", tokens=16255693)]}

        merged = reconcile_runs.merge_runs(existing, [transcript_run(session_id="7d886a6b", tokens=1000)])

        self.assertEqual(16255693, merged["runs"][0]["tokens"])

    def test_keeps_existing_run_without_session_id(self):
        existing = {"version": 1, "runs": [hook_run(session_id=None, task_id=7)]}

        merged = reconcile_runs.merge_runs(existing, [transcript_run()])

        self.assertEqual(7, merged["runs"][0]["task_id"])

    def test_adds_version_when_existing_file_has_none(self):
        merged = reconcile_runs.merge_runs({"runs": []}, [transcript_run()])

        self.assertEqual(1, merged["version"])


class ReconcileWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kanban = os.path.join(self.tmp.name, "vibe-harness")
        self.transcripts = os.path.join(self.tmp.name, "transcripts")
        os.makedirs(self.kanban)
        os.makedirs(self.transcripts)

    def tearDown(self):
        self.tmp.cleanup()

    def write_transcript(self, session_id, usage):
        path = os.path.join(self.transcripts, session_id + ".jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"message": {"model": "claude-fable-5", "usage": usage}}) + "\n")
        return path

    def read_runs(self):
        with open(os.path.join(self.kanban, "runs.json")) as fh:
            return json.load(fh)

    def test_write_leaves_file_byte_identical_when_nothing_new(self):
        """server.py와 같은 포맷으로 써야 매 실행마다 전체 파일이 재포맷되지 않는다."""
        path = os.path.join(self.kanban, "runs.json")
        doc = {"version": 1, "runs": [hook_run(session_id="7d886a6b", tokens=10 ** 9,
                                               input_tokens=10 ** 9, output_tokens=10 ** 9,
                                               cache_read_tokens=10 ** 9, cache_write_tokens=10 ** 9,
                                               cost_usd=10 ** 9)]}
        with open(path, "w") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
        with open(path) as fh:
            before = fh.read()
        self.write_transcript("7d886a6b", {
            "input_tokens": 1, "output_tokens": 1,
            "cache_read_input_tokens": 1, "cache_creation_input_tokens": 1,
        })

        reconcile_runs.reconcile("proj", self.kanban, self.transcripts)

        with open(path) as fh:
            self.assertEqual(before, fh.read())

    def test_write_keeps_run_missing_from_transcripts(self):
        with open(os.path.join(self.kanban, "runs.json"), "w") as fh:
            json.dump({"version": 1, "runs": [hook_run()]}, fh)
        self.write_transcript("7d886a6b", {
            "input_tokens": 100, "output_tokens": 200,
            "cache_read_input_tokens": 300, "cache_creation_input_tokens": 400,
        })

        reconcile_runs.reconcile("proj", self.kanban, self.transcripts)

        written = self.read_runs()
        self.assertEqual(1, written["version"])
        self.assertEqual(["71a08bd7", "7d886a6b"], [r["session_id"] for r in written["runs"]])


class CorruptRunsFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kanban = os.path.join(self.tmp.name, "vibe-harness")
        self.transcripts = os.path.join(self.tmp.name, "transcripts")
        os.makedirs(self.kanban)
        os.makedirs(self.transcripts)
        with open(os.path.join(self.transcripts, "7d886a6b.jsonl"), "w") as fh:
            fh.write(json.dumps({"message": {"model": "claude-fable-5", "usage": {
                "input_tokens": 1, "output_tokens": 1,
                "cache_read_input_tokens": 1, "cache_creation_input_tokens": 1}}}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_does_not_overwrite_runs_file_it_could_not_parse(self):
        path = os.path.join(self.kanban, "runs.json")
        corrupt = '{"version": 1, "runs": [{"tokens": 999'   # 잘린 JSON
        with open(path, "w") as fh:
            fh.write(corrupt)

        with self.assertRaises(SystemExit):
            reconcile_runs.reconcile("proj", self.kanban, self.transcripts)

        with open(path) as fh:
            self.assertEqual(corrupt, fh.read())

    def test_writes_normally_when_runs_file_is_absent(self):
        reconcile_runs.reconcile("proj", self.kanban, self.transcripts)

        with open(os.path.join(self.kanban, "runs.json")) as fh:
            self.assertEqual(1, len(json.load(fh)["runs"]))


class ReconcileAllTest(unittest.TestCase):
    """--all 은 손상된 프로젝트 하나 때문에 나머지 프로젝트를 건너뛰면 안 된다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.transcripts = os.path.join(self.tmp.name, "transcripts")
        os.makedirs(self.transcripts)
        with open(os.path.join(self.transcripts, "7d886a6b.jsonl"), "w") as fh:
            fh.write(json.dumps({"message": {"model": "claude-fable-5", "usage": {
                "input_tokens": 1, "output_tokens": 1,
                "cache_read_input_tokens": 1, "cache_creation_input_tokens": 1}}}) + "\n")

        self.broken = os.path.join(self.tmp.name, "broken", "vibe-harness")
        self.healthy = os.path.join(self.tmp.name, "healthy", "vibe-harness")
        os.makedirs(self.broken)
        os.makedirs(self.healthy)
        with open(os.path.join(self.broken, "runs.json"), "w") as fh:
            fh.write('{"runs": [')

        self.orig_projects = reconcile_runs._projects
        self.orig_transcript_dir = reconcile_runs._transcript_dir
        reconcile_runs._projects = lambda: {
            "broken": {"kanban_dir": self.broken},
            "healthy": {"kanban_dir": self.healthy},
        }
        reconcile_runs._transcript_dir = lambda cwd: self.transcripts
        self.orig_argv = sys.argv

    def tearDown(self):
        reconcile_runs._projects = self.orig_projects
        reconcile_runs._transcript_dir = self.orig_transcript_dir
        sys.argv = self.orig_argv
        self.tmp.cleanup()

    def test_healthy_project_still_written_when_another_is_corrupt(self):
        sys.argv = ["reconcile_runs.py", "--all"]

        with self.assertRaises(SystemExit):
            reconcile_runs.main()

        with open(os.path.join(self.healthy, "runs.json")) as fh:
            self.assertEqual(1, len(json.load(fh)["runs"]))


if __name__ == "__main__":
    unittest.main()
