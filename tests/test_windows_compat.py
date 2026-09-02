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
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

spec = importlib.util.spec_from_file_location("enroll", os.path.join(SCRIPTS, "enroll.py"))
enroll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enroll)

_rspec = importlib.util.spec_from_file_location(
    "reconcile_runs", os.path.join(SCRIPTS, "reconcile_runs.py"))
reconcile = importlib.util.module_from_spec(_rspec)
_rspec.loader.exec_module(reconcile)

RECORDER = os.path.join(SCRIPTS, "hooks", "vibe-harness-record-run.py")
COLLECTOR = os.path.join(SCRIPTS, "hooks", "vibe-harness-token-collector.sh")


def run(argv, env_extra=None, cwd=ROOT):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run([sys.executable] + argv, capture_output=True,
                          text=True, encoding="utf-8",
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
        r = subprocess.run([sys.executable, "-c", body], capture_output=True,
                           text=True, encoding="utf-8",
                           env=env, cwd=ROOT, timeout=120)

        self.assertEqual(0, r.returncode, r.stderr[-500:])
        self.assertIn("—", r.stdout)


class ImplicitEncodingTest(unittest.TestCase):
    """암묵적 로케일 인코딩을 쓰면 Windows 에서 조용히 데이터가 깎인다."""

    FLAGS = ["-X", "warn_default_encoding", "-W", "error::EncodingWarning"]

    def _probe(self, body):
        env = dict(os.environ)
        return subprocess.run([sys.executable] + self.FLAGS + ["-c", body],
                              capture_output=True, text=True,
                              encoding="utf-8", env=env, cwd=ROOT,
                              timeout=120)

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


class SourceWarningTest(unittest.TestCase):
    """컴파일 경고는 shim 보다 먼저 stderr 로 나간다 — 인코딩 처리로 막을 수 없다.

    Python 3.12 부터 invalid escape sequence 가 SyntaxWarning 으로 승격됐다. 경고 본문에는
    문제가 된 소스 줄이 그대로 실리고, 그 줄이 한글이면 cp949 콘솔에서 깨진 바이트가 된다.
    실제로 CI 3.12/3.13 에서만 터졌고 3.11 은 조용히 넘어갔다.
    """

    def _warnings(self, relpath):
        import py_compile
        import tempfile
        import warnings

        cfile = os.path.join(tempfile.mkdtemp(), "out.pyc")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            py_compile.compile(os.path.join(ROOT, relpath), cfile=cfile, doraise=True)
        return [str(w.message) for w in caught]

    def test_enroll_compiles_without_warnings(self):
        self.assertEqual([], self._warnings("scripts/enroll.py"))

    def test_reconcile_compiles_without_warnings(self):
        self.assertEqual([], self._warnings("scripts/reconcile_runs.py"))

    def test_server_compiles_without_warnings(self):
        self.assertEqual([], self._warnings("scripts/server.py"))


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


class TranscriptPathTest(unittest.TestCase):
    r"""Windows 경로에서 transcript 디렉터리를 아예 못 찾던 것.

    Claude Code 는 cwd 의 구분자를 '-' 로 바꿔 ~/.claude/projects/ 아래에 쓴다.
    규칙이 POSIX 만 보고 있어서(`[/._]`) Windows 경로는 **한 글자도** 바뀌지 않았고,
    C:\dev\proj 가 그대로 디렉터리 이름이 되어 없는 경로를 가리켰다. 크래시가 아니라
    "transcript 0개"였으므로 예약 작업은 계속 돌면서 수집만 조용히 멈춰 있었다.

    순수 문자열 함수를 보므로 macOS/Linux CI 에서도 그대로 잡힌다.
    """

    def test_windows_drive_and_backslashes_become_dashes(self):
        got = reconcile._project_slug(r"c:\dev-hoarchi\vibe-engineering")

        self.assertEqual("c--dev-hoarchi-vibe-engineering", got)

    def test_drive_letter_case_does_not_change_the_slug(self):
        """Claude Code 가 넘기는 드라이브 문자의 대소문자에 결과가 흔들리면 안 된다."""
        self.assertEqual(reconcile._project_slug(r"c:\a\b"),
                         reconcile._project_slug(r"C:\a\b"))

    def test_no_separator_survives_in_a_windows_slug(self):
        """구분자가 하나라도 남으면 디렉터리 이름이 될 수 없다."""
        slug = reconcile._project_slug(r"D:\work\a_b\c.d")

        self.assertNotIn(":", slug)
        self.assertNotIn(chr(92), slug)
        self.assertNotIn("/", slug)

    def test_posix_paths_are_unchanged(self):
        """macOS/Linux 동작을 바꾸지 않는다 — 이게 깨지면 기존 사용자 전원이 멈춘다."""
        self.assertEqual("-Users-hong-projects-my-app",
                         reconcile._project_slug("/Users/hong/projects/my_app"))

    def test_dots_and_underscores_still_collapse(self):
        self.assertEqual("-home-hong-proj-v2",
                         reconcile._project_slug("/home/hong/proj.v2"))


class MissingStdlibModuleTest(unittest.TestCase):
    """Windows 에 없는 표준 모듈. import 를 막아 macOS/Linux 에서도 재현한다.

    1. record-run.py 의 append_direct 가 함수 안에서 `import fcntl` 을 했다. 이 경로는
       localhost 서버가 떠 있지 않을 때 쓰이는 **유일한** 기록 경로인데, SessionEnd 훅이
       stderr 를 버리고 exit 0 하므로 ModuleNotFoundError 가 아무 흔적도 남기지 않았다.
       server.py 와 vibe_runtime.py 에는 이미 shim 이 있었고 여기만 빠져 있었다.
    2. server.py 는 모듈 최상단에서 ZoneInfo("Asia/Seoul") 을 만들었다. Windows 는 시스템
       tz DB 가 없어 tzdata 패키지가 없으면 여기서 죽고, 서버가 아예 뜨지 않는다.
    """

    BLOCK = (
        "import sys\n"
        "_BLOCKED = {%s}\n"
        "class _Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in _BLOCKED:\n"
        "            raise ImportError('blocked for test: ' + name)\n"
        "        return None\n"
        "for _n in list(sys.modules):\n"
        "    if _n.split('.')[0] in _BLOCKED:\n"
        "        del sys.modules[_n]\n"
        "sys.meta_path.insert(0, _Block())\n"
    )

    LOAD_RECORDER = (
        "import importlib.util\n"
        "_s = importlib.util.spec_from_file_location('rr', %r)\n"
        "rr = importlib.util.module_from_spec(_s); _s.loader.exec_module(rr)\n"
    )

    def _probe(self, body):
        return subprocess.run([sys.executable, "-c", body], capture_output=True,
                              text=True, encoding="utf-8",
                              env=dict(os.environ), cwd=ROOT, timeout=120)

    def test_recorder_records_a_run_without_fcntl(self):
        body = (self.BLOCK % "'fcntl'") + (self.LOAD_RECORDER % RECORDER) + (
            "import json, os, tempfile\n"
            "d = tempfile.mkdtemp()\n"
            "rr.append_direct(d, {'agent': 'claude', 'tokens': 123, 'task_id': None})\n"
            "with open(os.path.join(d, 'runs.json'), encoding='utf-8') as fh:\n"
            "    runs = json.load(fh)['runs']\n"
            "assert len(runs) == 1, runs\n"
            "assert runs[0]['tokens'] == 123, runs\n"
        )

        r = self._probe(body)

        self.assertEqual(0, r.returncode, r.stderr[-900:])

    def test_recorder_timestamps_without_the_tz_database(self):
        body = (self.BLOCK % "'zoneinfo'") + (self.LOAD_RECORDER % RECORDER) + (
            "ts = rr._now()\n"
            "assert ts.endswith('+09:00'), ts\n"
        )

        r = self._probe(body)

        self.assertEqual(0, r.returncode, r.stderr[-900:])

    def test_server_imports_without_the_tz_database(self):
        body = (self.BLOCK % "'zoneinfo'") + ((
            "import datetime, importlib.util, sys\n"
            "sys.path.insert(0, %r)\n"
            "_s = importlib.util.spec_from_file_location('srv', %r)\n"
            "srv = importlib.util.module_from_spec(_s); _s.loader.exec_module(srv)\n"
            "off = datetime.datetime.now(srv.KST).utcoffset()\n"
            "assert off == datetime.timedelta(hours=9), off\n"
        ) % (SCRIPTS, os.path.join(SCRIPTS, "server.py")))

        r = self._probe(body)

        self.assertEqual(0, r.returncode, r.stderr[-900:])


@unittest.skipUnless(shutil.which("bash"), "bash 없음")
class TokenCollectorHookTest(unittest.TestCase):
    r"""SessionEnd 훅은 Claude Code 가 준 transcript 경로를 훼손 없이 넘겨야 한다.

    1. 세 값을 한 줄에서 공백으로 쪼개 읽었다. Windows 사용자 이름에 공백이 흔해서
       (C:\Users\John Smith\...) 경로가 첫 공백에서 잘렸다.
    2. Windows 의 Python 은 텍스트 모드 stdout 에 CRLF 를 쓴다. read -r 은 LF 만 떼므로
       값 끝에 CR 이 남고, 그 경로로는 파일이 열리지 않는다.

    둘 다 훅이 stderr 를 버리고 exit 0 하므로 아무 말 없이 0건이 됐다. 그래서 여기서는
    "죽지 않는지"가 아니라 "정확히 그 경로가 넘어갔는지"를 본다.
    """

    PAYLOAD = {
        "transcript_path": r"C:\Users\John Smith\.claude\projects\c--x\s.jsonl",
        "session_id": "abc-123",
        "cwd": r"C:\dev\my proj",
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        hooks = os.path.join(self.tmp.name, ".claude", "hooks")
        os.makedirs(hooks)
        # 진짜 recorder 대신 argv 를 그대로 찍는 스텁 — 실제 runs.json 을 건드리지 않는다.
        with open(os.path.join(hooks, "vibe-harness-record-run.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("import sys\n"
                     "for a in sys.argv[1:]:\n"
                     "    print(a)\n")
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        env = dict(os.environ)
        env["HOME"] = self.home
        done = subprocess.run(["bash", COLLECTOR], input=json.dumps(self.PAYLOAD),
                              capture_output=True, text=True, encoding="utf-8", env=env,
                              cwd=ROOT, timeout=120)
        self.assertEqual(0, done.returncode, done.stderr[-500:])
        return done.stdout.splitlines()

    def _value_after(self, flag):
        out = self._run()
        self.assertIn(flag, out, out)
        return out[out.index(flag) + 1]

    def test_transcript_path_with_a_space_is_not_split(self):
        self.assertEqual(self.PAYLOAD["transcript_path"],
                         self._value_after("--from-transcript"))

    def test_cwd_with_a_space_is_not_split(self):
        self.assertEqual(self.PAYLOAD["cwd"], self._value_after("--cwd"))

    def test_no_carriage_return_leaks_into_any_argument(self):
        for arg in self._run():
            self.assertNotIn(chr(13), arg, repr(arg))
