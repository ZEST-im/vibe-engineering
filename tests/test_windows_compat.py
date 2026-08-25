"""Windows 호환 불변식.

Windows 사용자가 실제로 겪은 것을 macOS/Linux 에서도 재현되는 형태로 고정한다.

1. cp949 콘솔에서 출력이 크래시했다. 스크립트가 '—'(U+2014) 를 쓰는데 cp949 에 없다.
   `PYTHONUTF8=1` 을 손으로 붙여야 돌아가는 상태였다.
2. transcript 를 encoding 없이 열고 있었다. Windows 기본 인코딩(cp949)으로 UTF-8
   바이트를 읽으면 errors="ignore" 가 조용히 버려서 JSON 파싱이 실패한다 —
   크래시가 아니라 **조용한 과소집계**라 더 나쁘다.
3. 수집 에이전트 자동 등록이 macOS 전용이었고, 안내 문구는 Windows 에 없는 cron 을
   가리켰다.
"""
import importlib.util
import os
import subprocess
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

spec = importlib.util.spec_from_file_location("enroll", os.path.join(SCRIPTS, "enroll.py"))
enroll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enroll)


def run(argv, env_extra=None, cwd=ROOT):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run([sys.executable] + argv, capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=120)


class ConsoleEncodingTest(unittest.TestCase):
    """cp949 콘솔에서 죽지 않아야 한다. 사용자가 PYTHONUTF8 을 붙여야 했던 그 문제다."""

    ENV = {"PYTHONIOENCODING": "cp949:strict"}

    def test_enroll_survives_cp949_console(self):
        r = run(["scripts/enroll.py", "--dry-run", "--repair"], self.ENV)

        self.assertEqual(0, r.returncode, r.stderr[-500:])

    def test_reconcile_help_survives_cp949_console(self):
        r = run(["scripts/reconcile_runs.py", "--help"], self.ENV)

        self.assertEqual(0, r.returncode, r.stderr[-500:])

    def test_em_dash_prints_after_module_import(self):
        """대시를 지우는 것은 해법이 아니다. 모듈을 import 하면 출력이 가능해져야 한다."""
        body = (
            "import importlib.util\n"
            "spec = importlib.util.spec_from_file_location('en','scripts/enroll.py')\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "print('대시 — 통과')\n"
        )
        env = dict(os.environ); env.update(self.ENV)
        r = subprocess.run([sys.executable, "-c", body], capture_output=True, text=True,
                           env=env, cwd=ROOT, timeout=120)

        self.assertEqual(0, r.returncode, r.stderr[-500:])
        self.assertIn("—", r.stdout)


class ImplicitEncodingTest(unittest.TestCase):
    """암묵적 로케일 인코딩을 쓰면 Windows 에서 조용히 데이터가 깎인다."""

    FLAGS = ["-X", "warn_default_encoding", "-W", "error::EncodingWarning"]

    def _probe(self, body):
        env = dict(os.environ)
        return subprocess.run([sys.executable] + self.FLAGS + ["-c", body],
                              capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)

    def test_reading_transcripts_specifies_encoding(self):
        body = (
            "import importlib.util, json, os, tempfile\n"
            "spec = importlib.util.spec_from_file_location('rr','scripts/reconcile_runs.py')\n"
            "rr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)\n"
            "d = tempfile.mkdtemp()\n"
            "rec = {'timestamp':'2026-08-19T10:00:00+09:00','message':{'model':'claude-opus-5',"
            "'usage':{'input_tokens':1,'output_tokens':1,'cache_read_input_tokens':1,"
            "'cache_creation_input_tokens':1}}}\n"
            "open(os.path.join(d,'s1.jsonl'),'w',encoding='utf-8').write(json.dumps(rec)+'\\n')\n"
            "assert rr.build_daily_runs(d)\n"
            "assert rr.build_runs(d)\n"
        )

        r = self._probe(body)

        self.assertEqual(0, r.returncode, r.stderr[-800:])

    def test_reading_runs_file_specifies_encoding(self):
        body = (
            "import importlib.util, json, os, tempfile\n"
            "spec = importlib.util.spec_from_file_location('rr','scripts/reconcile_runs.py')\n"
            "rr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)\n"
            "d = tempfile.mkdtemp(); p = os.path.join(d,'runs.json')\n"
            "open(p,'w',encoding='utf-8').write(json.dumps({'version':1,'runs':[]}))\n"
            "rr._load_runs(p)\n"
        )

        r = self._probe(body)

        self.assertEqual(0, r.returncode, r.stderr[-800:])


class SchtasksTest(unittest.TestCase):
    """Windows 자동 등록. launchd 와 같은 규율 — 재실행해도 중복되지 않는다."""

    def argv(self, **kw):
        kw.setdefault("script", r"C:\work\vibe-engineering\scripts\reconcile_runs.py")
        kw.setdefault("python", r"C:\Program Files\Python312\python.exe")
        return enroll.build_schtasks_argv(**kw)

    def test_calls_schtasks_create(self):
        argv = self.argv()

        self.assertEqual("schtasks", argv[0])
        self.assertIn("/Create", argv)

    def test_forces_overwrite_so_rerun_does_not_duplicate(self):
        self.assertIn("/F", self.argv())

    def test_uses_stable_task_name(self):
        argv = self.argv()

        self.assertEqual(enroll.WINDOWS_TASK_NAME, argv[argv.index("/TN") + 1])

    def test_three_hours_becomes_hourly_three(self):
        argv = self.argv(interval=10800)

        self.assertEqual("HOURLY", argv[argv.index("/SC") + 1])
        self.assertEqual("3", argv[argv.index("/MO") + 1])

    def test_sub_hour_interval_uses_minutes(self):
        argv = self.argv(interval=900)

        self.assertEqual("MINUTE", argv[argv.index("/SC") + 1])
        self.assertEqual("15", argv[argv.index("/MO") + 1])

    def test_runs_the_collector_with_all_and_push(self):
        tr = self.argv()[self.argv().index("/TR") + 1]

        self.assertIn("reconcile_runs.py", tr)
        self.assertIn("--all", tr)
        self.assertIn("--push", tr)

    def test_quotes_paths_that_contain_spaces(self):
        """C:\\Program Files\\... 를 따옴표로 감싸지 않으면 작업이 실행되지 않는다."""
        tr = self.argv()[self.argv().index("/TR") + 1]

        self.assertIn('"C:\\Program Files\\Python312\\python.exe"', tr)

    def test_interval_below_a_minute_is_clamped(self):
        argv = self.argv(interval=10)

        self.assertEqual("1", argv[argv.index("/MO") + 1])


class WindowsGuidanceTest(unittest.TestCase):
    def test_does_not_tell_windows_users_to_use_cron(self):
        """Windows 에 cron 은 없다. 잘못된 안내는 없느니만 못하다."""
        source = open(os.path.join(SCRIPTS, "enroll.py"), encoding="utf-8").read()

        self.assertNotIn("cron", source.lower())


if __name__ == "__main__":
    unittest.main()
