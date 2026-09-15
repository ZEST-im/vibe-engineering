import contextlib
import importlib.util
import io
import json
import os
import shutil
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


# 이 파일의 테스트는 `--all` 을 돌린다. 그 경로가 사용자의 실제
# pipeline-status.json 을 써서 운영 신호를 "degraded" 로 오염시켰다.
# 모듈 단위로 임시 경로에 묶는다.
_STATUS_TMP = tempfile.mkdtemp()
reconcile_runs.PIPELINE_STATUS_PATH = os.path.join(_STATUS_TMP, "pipeline-status.json")


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
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"message": {"model": "claude-fable-5", "usage": usage}}) + "\n")
        return path

    def read_runs(self):
        with open(os.path.join(self.kanban, "runs.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_write_leaves_file_byte_identical_when_nothing_new(self):
        """server.py와 같은 포맷으로 써야 매 실행마다 전체 파일이 재포맷되지 않는다."""
        path = os.path.join(self.kanban, "runs.json")
        doc = {"version": 1, "runs": [hook_run(session_id="7d886a6b", tokens=10 ** 9,
                                               input_tokens=10 ** 9, output_tokens=10 ** 9,
                                               cache_read_tokens=10 ** 9, cache_write_tokens=10 ** 9,
                                               cost_usd=10 ** 9)]}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
        with open(path, encoding="utf-8") as fh:
            before = fh.read()
        self.write_transcript("7d886a6b", {
            "input_tokens": 1, "output_tokens": 1,
            "cache_read_input_tokens": 1, "cache_creation_input_tokens": 1,
        })

        reconcile_runs.reconcile("proj", self.kanban, self.transcripts)

        with open(path, encoding="utf-8") as fh:
            self.assertEqual(before, fh.read())

    def test_write_keeps_run_missing_from_transcripts(self):
        with open(os.path.join(self.kanban, "runs.json"), "w", encoding="utf-8") as fh:
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
        with open(os.path.join(self.transcripts, "7d886a6b.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"message": {"model": "claude-fable-5", "usage": {
                "input_tokens": 1, "output_tokens": 1,
                "cache_read_input_tokens": 1, "cache_creation_input_tokens": 1}}}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_does_not_overwrite_runs_file_it_could_not_parse(self):
        path = os.path.join(self.kanban, "runs.json")
        corrupt = '{"version": 1, "runs": [{"tokens": 999'   # 잘린 JSON
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(corrupt)

        with self.assertRaises(SystemExit):
            reconcile_runs.reconcile("proj", self.kanban, self.transcripts)

        with open(path, encoding="utf-8") as fh:
            self.assertEqual(corrupt, fh.read())

    def test_writes_normally_when_runs_file_is_absent(self):
        reconcile_runs.reconcile("proj", self.kanban, self.transcripts)

        with open(os.path.join(self.kanban, "runs.json"), encoding="utf-8") as fh:
            self.assertEqual(1, len(json.load(fh)["runs"]))


class ReconcileAllTest(unittest.TestCase):
    """--all 은 손상된 프로젝트 하나 때문에 나머지 프로젝트를 건너뛰면 안 된다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.transcripts = os.path.join(self.tmp.name, "transcripts")
        os.makedirs(self.transcripts)
        with open(os.path.join(self.transcripts, "7d886a6b.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"message": {"model": "claude-fable-5", "usage": {
                "input_tokens": 1, "output_tokens": 1,
                "cache_read_input_tokens": 1, "cache_creation_input_tokens": 1}}}) + "\n")

        self.broken = os.path.join(self.tmp.name, "broken", "vibe-harness")
        self.healthy = os.path.join(self.tmp.name, "healthy", "vibe-harness")
        os.makedirs(self.broken)
        os.makedirs(self.healthy)
        with open(os.path.join(self.broken, "runs.json"), "w", encoding="utf-8") as fh:
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

        with open(os.path.join(self.healthy, "runs.json"), encoding="utf-8") as fh:
            self.assertEqual(1, len(json.load(fh)["runs"]))


class MissingBoardDirIsSkippedNotCrashedTest(unittest.TestCase):
    """보드 디렉토리가 없을 때 — 만들지도, 전체를 멈추지도 않는다.

    서버 시작 루프가 등록된 경로를 뒤에서 만들어 주고 있었다. 그 루프는 사람이
    지운 프로젝트까지 되살려서 없앴는데(#9), 없앤 뒤 `reconcile` 이
    `open(runs.json, "w")` 에서 `FileNotFoundError` 로 죽는 자리가 열렸다.

    그리고 그 예외는 `_run_all` 의 프로젝트 단위 가드(`except SystemExit`)를
    **통과한다** — 프로젝트 하나 때문에 나머지 전부의 수집이 멈춘다. 이 저장소가
    반복해 싸워 온 "조용한 수집 정지" 와 같은 모양이다.

    여기서 `makedirs` 로 만들면 안 된다: transcript 는 리포가 아니라
    `~/.claude/projects/` 에 살아서, 지운 프로젝트도 transcript 는 남는다.
    만들면 수집이 보드를 되살린다 — #9 에서 서버가 하던 바로 그 짓이다.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "myrepo")
        self.kanban = os.path.join(self.repo, "vibe-harness")   # 만들지 않는다
        self.transcripts = os.path.join(self.tmp.name, "transcripts")
        os.makedirs(self.repo)
        os.makedirs(self.transcripts)
        with open(os.path.join(self.transcripts, "s1.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({"sessionId": "s1", "cwd": self.repo,
                                 "message": {"model": "claude-fable-5",
                                             "usage": {"input_tokens": 5,
                                                       "output_tokens": 5}}}) + "\n")

    def test_it_raises_system_exit_not_a_bare_oserror(self):
        """**등급이 중요하다.** `_run_all` 은 `SystemExit` 만 프로젝트 단위로 잡는다.

        다른 예외면 거기를 통과해 나머지 프로젝트의 수집까지 멈춘다.
        """
        with self.assertRaises(SystemExit) as caught:
            reconcile_runs.reconcile("fresh", self.kanban, self.transcripts)

        self.assertIn(self.kanban, str(caught.exception))

    def test_it_does_not_resurrect_the_board(self):
        with self.assertRaises(SystemExit):
            reconcile_runs.reconcile("fresh", self.kanban, self.transcripts)

        self.assertFalse(os.path.isdir(self.kanban),
                         "수집이 지운 보드를 되살렸다")

    def test_an_existing_board_still_collects(self):
        """막되 끄지 않는다."""
        os.makedirs(self.kanban)

        reconcile_runs.reconcile("fresh", self.kanban, self.transcripts)

        self.assertTrue(os.path.exists(os.path.join(self.kanban, "runs.json")))


class OneOddLineDoesNotEatTheRestTest(unittest.TestCase):
    """깨진 줄 하나가 그 뒤 전부를 버리던 것 — 조용한 under-counting.

    줄 단위 `try` 가 `json.loads` **만** 감싸고 있었다. 파싱은 되는데 dict 가 아닌
    줄(`[1,2,3]`, `"hello"`)은 바로 다음 `m.get(...)` 에서 AttributeError 를 내고,
    그 예외가 바깥 `except Exception: pass` 로 빠져 **파일 순회가 통째로 중단**됐다.
    `isinstance(msg, dict)` 검사는 `m.get` 다음이라 막지 못한다.

    실측: 정상 3줄(600 토큰) 가운데에 `[1,2,3]` 을 넣으면 **200** 이 나왔다 —
    첫 줄만 세고 멈춘 것이다. 에러도 로그도 없다.
    """

    GOOD = json.dumps({"message": {"model": "claude-fable-5",
                                   "usage": {"input_tokens": 100,
                                             "output_tokens": 100}}})

    def _file(self, lines):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        path = os.path.join(d, "s.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return path

    def _summarize(self, lines):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            total = reconcile_runs._summarize(self._file(lines))[0]
        return total, err.getvalue()

    def test_a_line_that_is_not_an_object_only_costs_that_line(self):
        total, _err = self._summarize([self.GOOD, "[1,2,3]", self.GOOD])

        self.assertEqual(400, total, "깨진 줄 뒤의 줄까지 버렸다")

    def test_a_non_numeric_usage_only_costs_that_record(self):
        odd = json.dumps({"message": {"usage": {"input_tokens": "많음"}}})
        total, _err = self._summarize([self.GOOD, odd, self.GOOD])

        self.assertEqual(400, total)

    def test_it_says_how_much_it_could_not_count(self):
        """덜 센 것을 조용히 덜 센 채로 두지 않는다."""
        _total, err = self._summarize([self.GOOD, "[1,2,3]", self.GOOD])

        self.assertIn("WARN", err)

    def test_a_transcript_being_written_stays_quiet(self):
        """**소음을 만들면 안 된다.**

        지금 쓰이고 있는 transcript 는 마지막 줄이 잘려 있다 — 정상이다.
        여기서 경고하면 활성 세션마다 매 수집에 한 줄씩 나오고, 그 소음이 위의
        진짜 경고를 덮는다.
        """
        total, err = self._summarize([self.GOOD, self.GOOD, '{"messa'])

        self.assertEqual(400, total)
        self.assertEqual("", err, "쓰이는 중인 파일에 경고를 냈다")


class DryRunShowsBothThePreviewAndTheProblemTest(unittest.TestCase):
    """미리보기는 둘 다 말해야 한다 — 무엇이 기록될지와, 실제로는 못 한다는 것.

    보드 디렉토리 가드를 함수 맨 앞에 두자 dry-run 이 토큰 미리보기를 잃고 바로
    실패했다. 반대로 조용히 넘어가면 "기록될 예정" 만 보여주고 실제 실행이 죽는다 —
    미리보기가 성공처럼 보이는 것이 이 저장소가 반복해 싸워 온 실패다.

    dry-run 은 아무것도 바꾸지 않으므로 실패로 세지 않는다. 종료코드를 흔들지 않고
    화면으로 말한다.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "myrepo")
        self.kanban = os.path.join(self.repo, "vibe-harness")   # 만들지 않는다
        self.transcripts = os.path.join(self.tmp.name, "t")
        os.makedirs(self.repo)
        os.makedirs(self.transcripts)
        with open(os.path.join(self.transcripts, "s1.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({"sessionId": "s1", "cwd": self.repo,
                                 "message": {"model": "claude-fable-5",
                                             "usage": {"input_tokens": 500,
                                                       "output_tokens": 500}}}) + "\n")

    def _dry_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            reconcile_runs.reconcile("dead", self.kanban, self.transcripts,
                                     dry_run=True)
        return out.getvalue()

    def test_dry_run_does_not_fail(self):
        """아무것도 바꾸지 않는 실행을 실패로 세면 종료코드가 흔들린다."""
        self._dry_run()   # SystemExit 이면 이 검사가 터진다

    def test_dry_run_still_shows_the_token_preview(self):
        self.assertIn("1,000", self._dry_run(), "미리보기를 잃었다")

    def test_dry_run_says_the_real_run_would_stop(self):
        self.assertIn("WARN", self._dry_run(),
                      "실제 실행이 죽을 것을 미리보기가 숨겼다")

    def test_the_real_run_still_refuses(self):
        """막되 끄지 않는다 — 쓰는 쪽은 여전히 멈춰야 한다."""
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                reconcile_runs.reconcile("dead", self.kanban, self.transcripts)

        self.assertFalse(os.path.isdir(self.kanban), "수집이 보드를 되살렸다")


if __name__ == "__main__":
    unittest.main()
