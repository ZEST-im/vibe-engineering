"""enroll.py — 직원 머신 등록. 재실행해도 안전해야 한다(idempotent).

setup.py 는 훅을 중복 등록한 이력이 있어 잠겨 있다. 그 실패를 반복하지 않는 것이 이
모듈의 존재 이유다: 같은 명령을 두 번 실행해도 에이전트가 두 개가 되지 않고, 기존
설정(dashboards 등)을 잃지 않는다.
"""
import importlib.util
import json
import os
import plistlib
import stat
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


class MergeSyncConfigTest(unittest.TestCase):
    def test_sets_secret_from_token(self):
        cfg = enroll.merge_sync_config({}, token="tok-1", endpoint="https://e/sync")

        self.assertEqual("tok-1", cfg["secret"])

    def test_sets_endpoint(self):
        cfg = enroll.merge_sync_config({}, token="tok-1", endpoint="https://e/sync")

        self.assertEqual("https://e/sync", cfg["endpoint"])

    def test_enables_sync(self):
        cfg = enroll.merge_sync_config({}, token="tok-1", endpoint="https://e/sync")

        self.assertTrue(cfg["enabled"])

    def test_preserves_existing_dashboards(self):
        existing = {"dashboards": {"ax-project": ["codebook", "zesty_os"]}}

        cfg = enroll.merge_sync_config(existing, token="tok-1", endpoint="https://e/sync")

        self.assertEqual({"ax-project": ["codebook", "zesty_os"]}, cfg["dashboards"])

    def test_preserves_unknown_future_keys(self):
        existing = {"some_future_flag": 42}

        cfg = enroll.merge_sync_config(existing, token="tok-1", endpoint="https://e/sync")

        self.assertEqual(42, cfg["some_future_flag"])

    def test_keeps_existing_machine_label_when_none_given(self):
        existing = {"machine": "mba-01"}

        cfg = enroll.merge_sync_config(existing, token="tok-1", endpoint="https://e/sync")

        self.assertEqual("mba-01", cfg["machine"])

    def test_overrides_machine_label_when_given(self):
        existing = {"machine": "mba-01"}

        cfg = enroll.merge_sync_config(existing, token="tok-1",
                                       endpoint="https://e/sync", machine="studio-02")

        self.assertEqual("studio-02", cfg["machine"])

    def test_does_not_set_runs_schema_by_default(self):
        """중앙이 준비되기 전에 켜면 전사 수집이 멈춘다 — 명시적 옵트인만 허용."""
        cfg = enroll.merge_sync_config({}, token="tok-1", endpoint="https://e/sync")

        self.assertNotIn("runs_schema", cfg)

    def test_sets_runs_schema_when_explicitly_requested(self):
        cfg = enroll.merge_sync_config({}, token="tok-1", endpoint="https://e/sync",
                                       runs_schema=2)

        self.assertEqual(2, cfg["runs_schema"])

    def test_rejects_blank_token(self):
        with self.assertRaises(ValueError):
            enroll.merge_sync_config({}, token="   ", endpoint="https://e/sync")

    def test_rejects_blank_endpoint(self):
        with self.assertRaises(ValueError):
            enroll.merge_sync_config({}, token="tok-1", endpoint="")

    def test_does_not_mutate_the_input(self):
        existing = {"machine": "mba-01"}

        enroll.merge_sync_config(existing, token="tok-1", endpoint="https://e/sync")

        self.assertEqual({"machine": "mba-01"}, existing)


class LaunchdPlistTest(unittest.TestCase):
    def plist(self, **kw):
        kw.setdefault("script", "/repo/scripts/reconcile_runs.py")
        kw.setdefault("log", "/logs/reconcile.log")
        return enroll.build_launchd_plist(**kw)

    def test_is_parseable_plist(self):
        parsed = plistlib.loads(self.plist().encode("utf-8"))

        self.assertEqual(enroll.AGENT_LABEL, parsed["Label"])

    def test_runs_the_given_script(self):
        parsed = plistlib.loads(self.plist().encode("utf-8"))

        self.assertIn("/repo/scripts/reconcile_runs.py", parsed["ProgramArguments"])

    def test_passes_all_and_push(self):
        parsed = plistlib.loads(self.plist().encode("utf-8"))

        self.assertIn("--all", parsed["ProgramArguments"])
        self.assertIn("--push", parsed["ProgramArguments"])

    def test_uses_requested_interval(self):
        parsed = plistlib.loads(self.plist(interval=3600).encode("utf-8"))

        self.assertEqual(3600, parsed["StartInterval"])

    def test_writes_log_to_given_path(self):
        parsed = plistlib.loads(self.plist().encode("utf-8"))

        self.assertEqual("/logs/reconcile.log", parsed["StandardOutPath"])

    def test_label_is_stable_so_reruns_replace_instead_of_duplicating(self):
        self.assertEqual(enroll.AGENT_LABEL,
                         plistlib.loads(self.plist().encode("utf-8"))["Label"])


class AgentPythonTest(unittest.TestCase):
    """에이전트는 Homebrew python 업그레이드에 깨지면 안 된다.

    reconcile_runs.py 는 런타임 의존성이 0(stdlib only)이라 시스템 python 으로 충분하다.
    """

    def test_prefers_system_python_when_present(self):
        self.assertEqual("/usr/bin/python3",
                         enroll.default_agent_python(exists=lambda p: True))

    def test_falls_back_to_running_interpreter_when_absent(self):
        self.assertEqual(sys.executable,
                         enroll.default_agent_python(exists=lambda p: False))

    def test_plist_honors_explicit_interpreter(self):
        text = enroll.build_launchd_plist(script="/a.py", log="/l.log",
                                          python="/custom/python3")

        parsed = plistlib.loads(text.encode("utf-8"))
        self.assertEqual("/custom/python3", parsed["ProgramArguments"][0])

    def test_plist_defaults_to_resolved_agent_python(self):
        text = enroll.build_launchd_plist(script="/a.py", log="/l.log")

        parsed = plistlib.loads(text.encode("utf-8"))
        self.assertEqual(enroll.default_agent_python(), parsed["ProgramArguments"][0])


class AgentNeedsUpdateTest(unittest.TestCase):
    """이 리포에서 실제로 터진 버그: 리포 폴더명이 바뀌자 plist 경로가 죽었다."""

    def test_false_when_identical(self):
        text = enroll.build_launchd_plist(script="/a/reconcile_runs.py", log="/l.log")

        self.assertFalse(enroll.agent_needs_update(text, text))

    def test_true_when_script_path_moved(self):
        old = enroll.build_launchd_plist(script="/old/reconcile_runs.py", log="/l.log")
        new = enroll.build_launchd_plist(script="/new/reconcile_runs.py", log="/l.log")

        self.assertTrue(enroll.agent_needs_update(old, new))

    def test_true_when_no_agent_installed_yet(self):
        new = enroll.build_launchd_plist(script="/new/reconcile_runs.py", log="/l.log")

        self.assertTrue(enroll.agent_needs_update(None, new))

    def test_ignores_insignificant_whitespace(self):
        new = enroll.build_launchd_plist(script="/a/reconcile_runs.py", log="/l.log")

        self.assertFalse(enroll.agent_needs_update(new + "\n", new))


class WriteSyncConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "sync.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_is_owner_only_readable(self):
        """시크릿이 들어간다 — 다른 사용자가 읽을 수 있으면 안 된다."""
        enroll.write_sync_config(self.path, {"secret": "tok-1"})

        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(0o600, mode)

    def test_second_write_is_byte_identical(self):
        enroll.write_sync_config(self.path, {"secret": "tok-1", "enabled": True})
        with open(self.path) as fh:
            first = fh.read()

        enroll.write_sync_config(self.path, {"secret": "tok-1", "enabled": True})

        with open(self.path) as fh:
            self.assertEqual(first, fh.read())

    def test_round_trips_the_config(self):
        cfg = {"secret": "tok-1", "dashboards": {"ax-project": ["a"]}}

        enroll.write_sync_config(self.path, cfg)

        with open(self.path) as fh:
            self.assertEqual(cfg, json.load(fh))


class BootstrapProjectsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "projects.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_empty_registry_when_absent(self):
        enroll.bootstrap_projects(self.path)

        with open(self.path) as fh:
            self.assertEqual({}, json.load(fh))

    def test_does_not_clobber_existing_registry(self):
        with open(self.path, "w") as fh:
            json.dump({"codebook": {"name": "CodeBook", "kanban_dir": "/x"}}, fh)

        enroll.bootstrap_projects(self.path)

        with open(self.path) as fh:
            self.assertIn("codebook", json.load(fh))

    def test_leaves_corrupt_registry_untouched(self):
        with open(self.path, "w") as fh:
            fh.write("{broken")

        with self.assertRaises(SystemExit):
            enroll.bootstrap_projects(self.path)

        with open(self.path) as fh:
            self.assertEqual("{broken", fh.read())


class ResolveScriptPathTest(unittest.TestCase):
    def test_points_at_the_reconcile_script_next_to_enroll(self):
        expected = os.path.join(SCRIPTS, "reconcile_runs.py")

        self.assertEqual(expected, enroll.resolve_script_path())

    def test_resolved_script_exists(self):
        self.assertTrue(os.path.isfile(enroll.resolve_script_path()))


if __name__ == "__main__":
    unittest.main()
