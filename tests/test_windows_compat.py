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
import ast
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock


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

_vspec = importlib.util.spec_from_file_location(
    "vh_runtime_t", os.path.join(SCRIPTS, "vibe_runtime.py"))
vibe_runtime = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(vibe_runtime)

_sspec = importlib.util.spec_from_file_location(
    "vh_setup", os.path.join(SCRIPTS, "setup.py"))
setup = importlib.util.module_from_spec(_sspec)
_sspec.loader.exec_module(setup)

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
    """Windows 사용자에게 Windows 에 없는 것을 시키면 안 된다.

    예전에는 enroll.py 한 파일만 봤다. 그래서 install_reconcile.py 가 그대로
    cron 을 가리키고 있었고, 게다가 macOS 가드가 `--check` 뒤에 있어서 Windows 에서
    `--check` 를 돌리면 macOS 전용 plist 경로를 들이밀며 "설치되어 있지 않다"고
    **틀린 진단**을 내놨다 — 실제로는 작업 스케줄러에 등록돼 있는 상태였다.

    파일을 나열하면 다음에 또 샌다. 디렉토리를 훑는다.
    """

    def scripts(self):
        return [n for n in sorted(os.listdir(SCRIPTS)) if n.endswith(".py")]

    def test_no_script_tells_windows_users_to_use_cron(self):
        guilty = []
        for name in self.scripts():
            with io.open(os.path.join(SCRIPTS, name), encoding="utf-8") as fh:
                src = fh.read().lower()
            for i, line in enumerate(src.splitlines(), 1):
                # cron 을 언급해도 괜찮은 경우가 있다: `os.name == "nt"` 분기 밖의
                # POSIX 안내문. 구분이 어려우니 "nt 분기를 가진 파일"만 봐준다.
                if "cron" in line and 'os.name == "nt"' not in src:
                    guilty.append("%s:%d" % (name, i))

        self.assertEqual([], guilty, "Windows 에 없는 cron 을 안내한다")

    def test_the_sweep_actually_sees_files(self):
        self.assertGreater(len(self.scripts()), 5)

    @unittest.skipIf(os.name == "nt", "여기서는 아래 Windows 테스트가 본다")
    def test_install_reconcile_still_guides_posix_users_to_cron(self):
        """Windows 를 고치면서 Linux 안내까지 지우면 안 된다."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ir_guide", os.path.join(SCRIPTS, "install_reconcile.py"))
        ir = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ir)

        self.assertIn("cron", ir._other_platform_hint())

    @unittest.skipUnless(os.name == "nt", "Windows 안내 전용")
    def test_install_reconcile_guides_windows_to_the_task_scheduler(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ir_guide", os.path.join(SCRIPTS, "install_reconcile.py"))
        ir = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ir)
        hint = ir._other_platform_hint()

        self.assertNotIn("cron", hint)
        self.assertIn("schtasks", hint)

    @unittest.skipUnless(os.name == "nt", "macOS 가드가 걸리는 것은 Windows 뿐")
    def test_check_refuses_before_reporting_a_macos_path(self):
        """`--check` 가 macOS 전용 경로로 틀린 진단을 내놓으면 안 된다."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ir_check", os.path.join(SCRIPTS, "install_reconcile.py"))
        ir = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ir)

        with self.assertRaises(SystemExit) as caught:
            ir.main(["--check"])

        self.assertIn("schtasks", str(caught.exception))


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


class SetupAutoStartTest(unittest.TestCase):
    r"""setup.py 의 3단계가 Windows 에서 4단계(훅 설치)를 통째로 날려먹던 것.

    launchd 는 macOS 전용인데 launchctl 을 조건 없이 불렀다. Windows 에서
    subprocess 는 "0 아닌 종료코드"가 아니라 FileNotFoundError 를 던지므로 main()
    이 훅 설치에 도달하지 못했다. 훅이 없으면 SessionEnd 수집이 아예 돌지 않는다 —
    이 레포가 반복해서 당한 "조용한 실패"의 원형이다. 그래서 3단계는 무슨 일이
    있어도 4단계를 막지 못해야 한다.
    """

    def test_server_task_overwrites_one_fixed_name(self):
        """재실행이 작업을 두 개로 늘리면 안 된다 — enroll.py 와 같은 규율."""
        argv = setup.build_server_schtasks_argv(
            python=r"C:\Program Files\Python312\pythonw.exe")

        self.assertEqual("schtasks", argv[0])
        self.assertIn("/Create", argv)
        self.assertIn("/F", argv)
        self.assertEqual(setup.WINDOWS_SERVER_TASK, argv[argv.index("/TN") + 1])

    def test_server_task_runs_at_logon(self):
        argv = setup.build_server_schtasks_argv()

        self.assertEqual("ONLOGON", argv[argv.index("/SC") + 1])

    def test_server_task_quotes_paths_that_contain_spaces(self):
        argv = setup.build_server_schtasks_argv(
            python=r"C:\Program Files\Python312\pythonw.exe")
        tr = argv[argv.index("/TR") + 1]

        self.assertIn('"C:\\Program Files\\Python312\\pythonw.exe"', tr)
        self.assertIn("server.py", tr)

    def test_non_darwin_skips_instead_of_raising(self):
        """예외가 새면 훅이 사라진다. macOS 아닌 곳에서는 조용히 건너뛴다."""
        saved_platform, saved_name = setup.sys.platform, setup.os.name
        setup.sys.platform, setup.os.name = "linux", "posix"
        try:
            self.assertFalse(setup.install_launchd())
        finally:
            setup.sys.platform, setup.os.name = saved_platform, saved_name

    def test_non_darwin_does_not_create_a_mac_only_directory(self):
        """~/Library/LaunchAgents 를 Windows 에 만들어 두는 것은 쓰레기다."""
        saved_platform, saved_name = setup.sys.platform, setup.os.name
        saved_agents = setup.LAUNCH_AGENTS
        tmp = tempfile.mkdtemp()
        setup.LAUNCH_AGENTS = os.path.join(tmp, "Library", "LaunchAgents")
        setup.sys.platform, setup.os.name = "linux", "posix"
        try:
            setup.install_launchd()

            self.assertFalse(os.path.exists(setup.LAUNCH_AGENTS))
        finally:
            setup.sys.platform, setup.os.name = saved_platform, saved_name
            setup.LAUNCH_AGENTS = saved_agents

    def test_windows_delegates_to_the_scheduled_task(self):
        """Windows 에서는 건너뛰는 대신 로그온 작업으로 같은 목적을 이룬다."""
        saved_platform, saved_name = setup.sys.platform, setup.os.name
        saved_install = setup.install_windows_server_task
        calls = []
        setup.install_windows_server_task = lambda: calls.append(1) or True
        setup.sys.platform, setup.os.name = "win32", "nt"
        try:
            self.assertTrue(setup.install_launchd())
            self.assertEqual(1, len(calls))
        finally:
            setup.sys.platform, setup.os.name = saved_platform, saved_name
            setup.install_windows_server_task = saved_install

    def test_schtasks_refusal_falls_back_to_the_run_key(self):
        """ONLOGON 은 관리자 권한을 요구한다.

        일반 계정에서는 schtasks 가 "액세스가 거부되었습니다" 로 실패한다. 거기서
        포기하면 서버가 로그온 때 뜨지 않고, 사용자에게는 관리자 셸이 필요한 명령을
        직접 치라고 안내하게 된다. 권한 없이 되는 경로(HKCU Run)로 떨어져야 한다.
        """
        from unittest import mock

        refused = types.SimpleNamespace(
            returncode=1, stderr="ERROR: Access is denied.", stdout="")
        with mock.patch.object(setup.subprocess, "run", return_value=refused), \
                mock.patch.object(setup, "install_windows_run_key",
                                  return_value=True) as fallback:
            self.assertTrue(setup.install_windows_server_task())

        fallback.assert_called_once_with()

    def test_missing_schtasks_falls_back_to_the_run_key(self):
        """schtasks 가 아예 없는 환경도 있다. 예외가 새면 setup 이 멈춘다."""
        from unittest import mock

        with mock.patch.object(setup.subprocess, "run",
                               side_effect=OSError("no schtasks")), \
                mock.patch.object(setup, "install_windows_run_key",
                                  return_value=True) as fallback:
            self.assertTrue(setup.install_windows_server_task())

        fallback.assert_called_once_with()

    def test_successful_task_drops_the_run_key(self):
        """두 경로가 동시에 살아 있으면 로그온마다 서버가 두 번 뜬다."""
        from unittest import mock

        ok = types.SimpleNamespace(returncode=0, stderr="", stdout="")
        with mock.patch.object(setup.subprocess, "run", return_value=ok), \
                mock.patch.object(setup, "remove_windows_run_key",
                                  return_value=False) as cleanup:
            self.assertTrue(setup.install_windows_server_task())

        cleanup.assert_called_once_with()


class HookCommandPathTest(unittest.TestCase):
    """훅 명령에 역슬래시가 들어가면 Windows 에서 훅이 전부 죽는다.

    Claude Code 는 Windows 에서도 훅 명령을 bash 에 넘긴다. bash 에서 역슬래시는
    이스케이프라 역슬래시 경로가 `C:Userskimyh...` 로 뭉개지고, 실제로
    "bash: C:Userskimyh/.claude/hooksvibe-harness-review.sh: No such file or
    directory" 가 툴 호출마다 찍혔다. 조용한 실패가 아니라 훅 5개 전원 정지다.
    """

    def test_no_backslash_in_any_registered_hook_command(self):
        bad = [e["hooks"][0]["command"] for _, _, e in setup.HOOKS
               if "\\" in e["hooks"][0]["command"]]

        self.assertEqual([], bad, "훅 명령에 역슬래시 — bash 가 먹는다")

    def test_hook_cmd_converts_a_windows_path(self):
        """이 머신이 POSIX 여도 규칙이 고정되어야 한다 — 그래서 문자열로 직접 본다."""
        self.assertNotIn("\\", setup.hook_cmd("x.sh").replace(setup.HOOKS_DIR, ""))
        self.assertTrue(setup.hook_cmd("x.sh").endswith("/x.sh"))


if __name__ == "__main__":
    unittest.main()


NETSTAT_SAMPLE = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    127.0.0.1:4242         0.0.0.0:0              LISTENING       8092
  TCP    127.0.0.1:4242         127.0.0.1:50152        ESTABLISHED     8092
  TCP    127.0.0.1:4242         127.0.0.1:53975        TIME_WAIT       0
  TCP    127.0.0.1:50152        127.0.0.1:4242         ESTABLISHED     8532
  TCP    127.0.0.1:42420        0.0.0.0:0              LISTENING       9999
"""


class ServerPidLookupTest(unittest.TestCase):
    """업그레이드 후 서버를 못 멈추면 디스크와 도는 코드가 갈라진다.

    예전에는 `lsof` 를 무조건 불렀고, Windows 에 없어서 나는 FileNotFoundError 를
    바깥의 `except Exception: pass` 가 삼켰다. 그래서 업그레이드가 끝났다고
    출력하면서도 **구버전 서버가 계속 돌았다.** 크래시가 아니라 조용한 무동작이라
    재시작했다고 믿게 된다 — 실제로 sync 설정을 못 읽는 구버전이 오래 살아남았다.
    """

    def netstat(self, stdout):
        done = types.SimpleNamespace(stdout=stdout, stderr="", returncode=0)
        return unittest.mock.patch.object(setup.subprocess, "run",
                                          return_value=done)

    def test_windows_reads_the_listening_pid_from_netstat(self):
        with unittest.mock.patch.object(setup.os, "name", "nt"), \
                self.netstat(NETSTAT_SAMPLE):
            self.assertEqual(["8092"], setup.server_pids(4242))

    def test_established_and_time_wait_rows_are_ignored(self):
        """ESTABLISHED 행의 pid 를 죽이면 서버가 아니라 **브라우저**를 죽인다."""
        with unittest.mock.patch.object(setup.os, "name", "nt"), \
                self.netstat(NETSTAT_SAMPLE):
            self.assertNotIn("8532", setup.server_pids(4242))
            self.assertNotIn("0", setup.server_pids(4242))

    def test_a_port_that_merely_starts_the_same_is_not_matched(self):
        """`:42420` 은 `:4242` 가 아니다. 부분 문자열로 보면 남의 서버를 죽인다."""
        with unittest.mock.patch.object(setup.os, "name", "nt"), \
                self.netstat(NETSTAT_SAMPLE):
            self.assertNotIn("9999", setup.server_pids(4242))

    def test_missing_tool_is_reported_as_no_server_not_a_crash(self):
        with unittest.mock.patch.object(setup.subprocess, "run",
                                        side_effect=OSError("no such tool")):
            self.assertEqual([], setup.server_pids(4242))


class ForceRmtreeTest(unittest.TestCase):
    """읽기 전용 파일이 섞이면 Windows 의 shutil.rmtree 가 WinError 5 로 멈춘다."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.target = os.path.join(self.tmp.name, "skill", "references")
        os.makedirs(self.target)
        self.ro = os.path.join(self.target, "ro.md")
        with io.open(self.ro, "w", encoding="utf-8") as fh:
            fh.write("x")

    def tearDown(self):
        import stat as _stat
        for root, _d, files in os.walk(self.tmp.name):
            for n in files:
                try:
                    os.chmod(os.path.join(root, n), _stat.S_IWRITE)
                except OSError:
                    pass
        self.tmp.cleanup()

    def test_removes_a_tree_that_holds_a_read_only_file(self):
        import stat as _stat
        os.chmod(self.ro, _stat.S_IREAD)
        top = os.path.dirname(self.target)

        setup.force_rmtree(top)

        self.assertFalse(os.path.exists(top))

    def test_ordinary_tree_is_removed_too(self):
        top = os.path.dirname(self.target)

        setup.force_rmtree(top)

        self.assertFalse(os.path.exists(top))


class RmtreeIsRoutedTest(unittest.TestCase):
    """setup.py 가 shutil.rmtree 를 직접 부르면 읽기 전용 파일에서 다시 멈춘다."""

    def test_setup_routes_every_rmtree_through_the_helper(self):
        with io.open(os.path.join(SCRIPTS, "setup.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        bad = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "rmtree"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "shutil"
                    and node.lineno > self._helper_line(tree)):
                bad.append("setup.py:%d" % node.lineno)

        self.assertEqual([], bad, "shutil.rmtree 직접 호출")

    def _helper_line(self, tree):
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "force_rmtree":
                return node.end_lineno
        self.fail("force_rmtree 가 없다")


class NoImplicitEncodingInSourceTest(unittest.TestCase):
    """텍스트 모드 open() 에 encoding 이 빠지면 Windows 에서 로케일(cp949)로 열린다.

    위의 ImplicitEncodingTest 는 함수를 하나씩 실행해 본다. 그래서 **실행되지 않은
    경로는 보지 못한다** — 실제로 runs.json 을 쓰는 줄이 그렇게 빠져나갔고, 한글
    제목을 cp949 로 쓰다 중간에 UnicodeEncodeError 로 끊겨 파일이 깨졌다. 읽기는
    utf-8 로 고정돼 있어서 그 다음 수집이 통째로 멈췄다.

    실행이 아니라 소스를 본다. 새로 추가되는 줄도 같이 잡힌다.
    """

    BINARY = ("rb", "wb", "ab", "r+b", "w+b", "a+b", "rb+", "wb+", "ab+")

    def _offenders(self, relpath):
        tree = ast.parse(io.open(os.path.join(ROOT, relpath), encoding="utf-8").read())
        bad = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "open"):
                continue
            if any(k.arg == "encoding" for k in node.keywords):
                continue
            mode = node.args[1].value if len(node.args) > 1 and isinstance(
                node.args[1], ast.Constant) else ""
            if isinstance(mode, str) and "b" in mode:
                continue
            bad.append("%s:%d" % (relpath, node.lineno))
        return bad

    # subprocess 쪽과 같은 이유로 `tests` 도 본다 — 규칙이 `scripts` 만 보는 동안
    # 테스트가 36곳에서 로케일로 열고 있었다. 한글 픽스처를 쓰는 순간 같은 자리에서
    # 터진다. 스캔은 소스를 보므로 아직 안 터진 것도 지금 잡힌다.
    DIRS = ("scripts", os.path.join("scripts", "hooks"), "tests")

    def test_no_script_opens_text_without_an_encoding(self):
        bad = []
        for d in self.DIRS:
            for name in sorted(os.listdir(os.path.join(ROOT, d))):
                if name.endswith(".py"):
                    bad += self._offenders(os.path.join(d, name))

        self.assertEqual([], bad, "encoding 없는 텍스트 open — Windows 에서 cp949 로 열린다")


class NoImplicitSubprocessEncodingTest(unittest.TestCase):
    """subprocess 를 텍스트 모드로 열 때 encoding 이 빠지면 로케일로 디코드된다.

    cp949 머신에서 한글 커밋 메시지를 읽다 UnicodeDecodeError 가 나고, 그 예외는
    subprocess 의 reader 스레드에서 터진다. 호출한 쪽은 예외 대신 `stdout=None`
    을 받아 `AttributeError` 로 죽는다 — 원인에서 두 단계 떨어진 곳이다.
    실제로 check.py 의 분기 판정과 search.py 의 커밋 검색이 그렇게 멈췄다.

    open() 과 같은 이유로 실행이 아니라 소스를 본다. macOS 에서는 로케일이 이미
    UTF-8 이라 명시해도 동작이 같다 — 고정하는 쪽은 Windows 다.
    """

    TEXT_KW = ("text", "universal_newlines")

    def _offenders(self, relpath):
        tree = ast.parse(io.open(os.path.join(ROOT, relpath), encoding="utf-8").read())
        bad = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kw = {k.arg for k in node.keywords if k.arg}
            if kw & set(self.TEXT_KW) and "encoding" not in kw:
                bad.append("%s:%d" % (relpath, node.lineno))
        return bad

    # `tests` 도 같이 본다. 스캔이 `scripts` 만 보는 동안 테스트 헬퍼 8곳이
    # encoding 없이 남아 있었고, 그중 `test_gh_surface._git` 이 한글 커밋 제목을
    # 읽다 이 머신에서 35건을 터뜨렸다 — 고치는 규칙은 같은데 보는 범위만 좁았다.
    DIRS = ("scripts", os.path.join("scripts", "hooks"), "tests")

    def test_no_script_decodes_subprocess_output_with_the_locale(self):
        bad = []
        for d in self.DIRS:
            for name in sorted(os.listdir(os.path.join(ROOT, d))):
                if name.endswith(".py"):
                    bad += self._offenders(os.path.join(d, name))

        self.assertEqual([], bad, "encoding 없는 텍스트 subprocess — 로케일로 디코드된다")


class EveryEntrypointSurvivesCp949Test(unittest.TestCase):
    """엔트리포인트 전부가 cp949 콘솔에서 한글을 출력할 수 있어야 한다.

    위 ConsoleEncodingTest 는 enroll 과 reconcile 두 개만 본다. 그래서 나머지
    7개(check, setup, search, worker, kanban_edit, review_sync,
    install_reconcile)가 전부 빠져 있었고, 실제로 `check.py --fast` 는 이 머신에서
    em-dash 한 글자에 UnicodeEncodeError 로 죽었다.

    **파일을 나열하지 않고 디렉토리를 훑는다.** 나열하면 다음에 추가되는
    엔트리포인트가 또 빠진다. 이 테스트가 이미 그렇게 새어나간 자리다.
    """

    # 라이브러리 모듈. 직접 실행되지 않으므로 콘솔을 건드릴 이유가 없다.
    LIBRARIES = {"vibe_runtime.py"}

    def entrypoints(self):
        return [n for n in sorted(os.listdir(SCRIPTS))
                if n.endswith(".py") and n not in self.LIBRARIES]

    def test_every_entrypoint_prints_korean_under_a_cp949_console(self):
        body = (
            "import importlib.util, os, sys\n"
            # 직접 실행하면 파이썬이 스크립트 디렉토리를 path 에 넣어준다. 여기서는
            # spec 으로 읽으므로 그 일을 대신해야 형제 모듈 import 가 재현된다.
            "sys.path.insert(0, os.path.dirname(sys.argv[1]))\n"
            "spec = importlib.util.spec_from_file_location('m', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "print('한글 — 대시')\n"
        )
        env = dict(os.environ, PYTHONIOENCODING="cp949:strict")
        dead = []
        for name in self.entrypoints():
            r = subprocess.run([sys.executable, "-c", body, os.path.join(SCRIPTS, name)],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, cwd=ROOT, timeout=120)
            if r.returncode != 0:
                dead.append("%s: %s" % (name, r.stderr.strip().splitlines()[-1:]))

        self.assertEqual([], dead, "cp949 콘솔에서 죽는 엔트리포인트")

    def test_the_list_is_not_empty(self):
        """훑기가 조용히 0개를 훑으면 위 테스트는 아무것도 검사하지 않는다."""
        self.assertGreater(len(self.entrypoints()), 5)


class AtomicReplaceIsRoutedTest(unittest.TestCase):
    """원자 교체는 반드시 atomic_replace 를 거쳐야 한다.

    POSIX 의 rename 은 대상이 열려 있어도 성공한다. Windows 는 거부한다 —
    실측: 브라우저 탭 하나가 2초마다 폴링하는 것만으로 보드 저장 200번 중 3번,
    탭이 여럿이면 32번이 PermissionError 로 실패했다. 읽기 4스레드를 붙이면
    200번 중 198번이 실패한다. ThreadingHTTPServer 라 이 조건은 평시다.

    또 모두가 `<path>.tmp` 하나를 쓰면 동시 쓰기끼리도 서로를 막는다.

    CI 는 ubuntu 에서만 돌아 이 동작 차이를 볼 수 없다. 그래서 **동작이 아니라
    배선을 고정한다** — 어느 플랫폼에서 돌려도 같은 것을 검사한다.
    """

    HELPER = "vibe_runtime.py"   # atomic_replace 의 구현 자체가 사는 곳

    def _raw_sites(self, relpath):
        tree = ast.parse(io.open(os.path.join(ROOT, relpath), encoding="utf-8").read())
        bad = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "replace"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"):
                bad.append("%s:%d" % (relpath, node.lineno))
        return bad

    def test_no_script_calls_os_replace_directly(self):
        bad = []
        for d in ("scripts", os.path.join("scripts", "hooks")):
            for name in sorted(os.listdir(os.path.join(ROOT, d))):
                if name.endswith(".py") and name != self.HELPER:
                    bad += self._raw_sites(os.path.join(d, name))

        self.assertEqual([], bad, "os.replace 직접 호출 — Windows 에서 재시도가 없다")

    def test_temp_names_are_not_shared(self):
        """`path + '.tmp'` 는 동시 쓰기끼리 같은 파일을 잡는다."""
        bad = []
        for d in ("scripts", os.path.join("scripts", "hooks")):
            for name in sorted(os.listdir(os.path.join(ROOT, d))):
                if not name.endswith(".py"):
                    continue
                rel = os.path.join(d, name)
                for i, line in enumerate(io.open(os.path.join(ROOT, rel),
                                                 encoding="utf-8"), 1):
                    if '+ ".tmp"' in line and "lambda" not in line:
                        bad.append("%s:%d" % (rel, i))

        self.assertEqual([], bad, "공유 임시 파일명 — 동시 쓰기가 서로를 막는다")

    def test_tmp_name_differs_between_threads_that_are_alive_together(self):
        """**동시에 살아 있는** 쓰기끼리 겹치지 않으면 된다.

        threading.get_ident() 는 죽은 스레드의 id 를 재사용한다. 그래서 순차로
        돌린 스레드 8개는 같은 이름을 받을 수 있고, 실제로 CI 의 리눅스
        3.11·3.12 에서 8개가 전부 같은 값이었다(Windows·3.13 에서는 우연히
        겹쳐 돌아 통과했다). 처음 쓴 단언이 틀렸던 것이다.

        그건 결함이 아니다 — 먼저 쓰기가 os.replace 로 임시 파일을 치운 뒤에야
        다음 것이 시작하므로 순차 스레드는 애초에 충돌할 수 없다. 고정해야
        하는 성질은 '같이 살아 있는 동안 다른가'뿐이다. barrier 로 8개를 동시에
        세워 놓고 본다.
        """
        import threading
        n = 8
        seen, lock = [], threading.Lock()
        gate = threading.Barrier(n, timeout=30)

        def work():
            gate.wait()                       # 8개가 다 뜰 때까지 아무도 안 죽는다
            name = vibe_runtime.tmp_name("/x/k.json")
            with lock:
                seen.append(name)
            gate.wait()                       # 이름을 다 받을 때까지 살아 있는다

        threads = [threading.Thread(target=work) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(n, len(seen), "스레드가 제때 끝나지 않았다")
        self.assertEqual(n, len(set(seen)))

    def test_tmp_name_includes_the_pid(self):
        """다른 프로세스끼리도 갈라야 한다 — 훅·수집기·서버가 같은 보드를 쓴다."""
        self.assertIn(str(os.getpid()), vibe_runtime.tmp_name("/x/k.json"))


@unittest.skipUnless(os.name == "nt", "os.replace 가 거부되는 것은 Windows 뿐")
class ConcurrentBoardWriteTest(unittest.TestCase):
    """읽는 쪽이 있어도 보드 저장이 성공해야 한다. 고치기 전엔 2% ~ 99% 가 실패했다."""

    def test_writes_survive_a_concurrent_reader(self):
        import tempfile, threading, time
        spec = importlib.util.spec_from_file_location("srv_cc",
                                                      os.path.join(SCRIPTS, "server.py"))
        srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)

        d = tempfile.mkdtemp()
        srv.init_kanban(d)
        board = {"version": 1, "next_id": 1,
                 "tasks": [{"id": i, "title": "태스크 %d" % i, "details": "내용 " * 40}
                           for i in range(40)]}
        srv._write_kanban(d, board)
        stop = threading.Event()

        def poller():
            while not stop.is_set():
                try:
                    srv._read_kanban(d)
                except Exception:
                    pass
                time.sleep(0.01)

        t = threading.Thread(target=poller, daemon=True)
        t.start()
        failures = 0
        try:
            for _ in range(60):
                try:
                    srv._write_kanban(d, board)
                except OSError:
                    failures += 1
        finally:
            stop.set(); t.join(timeout=3)

        self.assertEqual(0, failures)

