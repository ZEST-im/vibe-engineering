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
    def test_token_goes_to_runs_token_not_secret(self):
        """secret 은 스냅샷용 공유 값이다. 개인 토큰으로 덮으면 스냅샷이 401 로 죽는다."""
        cfg = enroll.merge_sync_config({}, token="tok-1", endpoint="https://e/sync")

        self.assertEqual("tok-1", cfg["runs_token"])

    def test_does_not_touch_secret_when_only_token_given(self):
        cfg = enroll.merge_sync_config({}, token="tok-1", endpoint="https://e/sync")

        self.assertNotIn("secret", cfg)

    def test_preserves_existing_shared_secret(self):
        existing = {"secret": "shared-value"}

        cfg = enroll.merge_sync_config(existing, token="tok-1", endpoint="https://e/sync")

        self.assertEqual("shared-value", cfg["secret"])

    def test_shared_secret_can_be_set_for_a_fresh_machine(self):
        cfg = enroll.merge_sync_config({}, token="tok-1", endpoint="https://e/sync",
                                       shared_secret="shared-value")

        self.assertEqual("shared-value", cfg["secret"])

    def test_shared_secret_does_not_overwrite_runs_token(self):
        cfg = enroll.merge_sync_config({}, token="tok-1", endpoint="https://e/sync",
                                       shared_secret="shared-value")

        self.assertEqual("tok-1", cfg["runs_token"])

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

    @unittest.skipIf(os.name == "nt",
                     "Windows 에는 POSIX 권한 비트가 없다 — enroll.py 가 "
                     "그 사실을 사용자에게 경고한다")
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


class AddProjectTest(unittest.TestCase):
    """수집은 projects.json 에 등록된 프로젝트만 훑는다. 손으로 JSON 을 고치게 하면
    빠뜨리고, 빠뜨리면 조용히 0건이 된다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "projects.json")
        self.repo = os.path.join(self.tmp.name, "codebook_vibe")
        os.makedirs(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        with open(self.path) as fh:
            return json.load(fh)

    def test_registers_key_with_kanban_dir_under_repo(self):
        enroll.add_project(self.path, "codebook", self.repo)

        expected = os.path.join(self.repo, "vibe-harness").replace(os.sep, "/")
        self.assertEqual(expected, self.read()["codebook"]["kanban_dir"])

    def test_kanban_dir_is_stored_posix_style(self):
        """projects.json 은 플랫폼과 무관하게 "/" 로 적는다.

        역슬래시를 그대로 넣으면 JSON 이스케이프가 필요해져 손으로 고칠 때 깨지고,
        한 파일 안에서 머신마다 표기가 갈린다. 읽는 쪽은 전부 os.path.abspath 를
        거치므로 "/" 로 적어도 Windows 에서 그대로 동작한다.
        """
        enroll.add_project(self.path, "codebook", self.repo)

        self.assertNotIn(chr(92), self.read()["codebook"]["kanban_dir"])

    def test_creates_registry_when_absent(self):
        enroll.add_project(self.path, "codebook", self.repo)

        self.assertIn("codebook", self.read())

    def test_keeps_other_projects(self):
        enroll.add_project(self.path, "codebook", self.repo)
        other = os.path.join(self.tmp.name, "zesty-os")
        os.makedirs(other)

        enroll.add_project(self.path, "zesty_os", other)

        self.assertEqual(["codebook", "zesty_os"], sorted(self.read().keys()))

    def test_rerun_is_idempotent(self):
        enroll.add_project(self.path, "codebook", self.repo)
        first = self.read()

        enroll.add_project(self.path, "codebook", self.repo)

        self.assertEqual(first, self.read())

    def test_rejects_repo_that_does_not_exist(self):
        with self.assertRaises(ValueError):
            enroll.add_project(self.path, "codebook", os.path.join(self.tmp.name, "nope"))

    def test_rejects_blank_key(self):
        with self.assertRaises(ValueError):
            enroll.add_project(self.path, "  ", self.repo)

    def test_parses_key_equals_path_pairs(self):
        self.assertEqual(("codebook", "/x/y"), enroll.parse_project_arg("codebook=/x/y"))

    def test_bare_path_now_derives_the_key(self):
        """계약이 바뀌었다 — 예전에는 '=' 없는 인자를 거부했다.

        키를 사람이 손으로 정하게 두는 것이 문제의 원인이었다. 같은 리포가 머신마다
        다른 키(`pante` vs `pante_bde`)로 등록돼 인별 합계가 이중 계상됐다. 그래서
        키 생략을 허용하고 git remote 에서 뽑는다. 자세한 계약은
        tests/test_project_key.py 에 있다.
        """
        key, path = enroll.parse_project_arg(SCRIPTS)     # 이 레포 안이라 remote 가 있다
        self.assertTrue(key)
        self.assertEqual(SCRIPTS, path)

    def test_still_rejects_an_empty_argument(self):
        with self.assertRaises(ValueError):
            enroll.parse_project_arg("   ")


class ResolveScriptPathTest(unittest.TestCase):
    def test_points_at_the_reconcile_script_next_to_enroll(self):
        expected = os.path.join(SCRIPTS, "reconcile_runs.py")

        self.assertEqual(expected, enroll.resolve_script_path())

    def test_resolved_script_exists(self):
        self.assertTrue(os.path.isfile(enroll.resolve_script_path()))


class AddProjectToDashboardTest(unittest.TestCase):
    """수집(projects.json)과 대시보드 노출(sync.json)은 서로 다른 스위치다.

    하나만 켜면 사용량이 중앙에 올라가는데 화면에는 없다 — 2026-09-04 실측으로
    박찬일의 pante_capture 13.7억 토큰이 그 상태였다. 화면 어디에도 신호가 없다.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "sync.json")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, cfg):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)

    def read(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_appends_key_to_existing_dashboard_list(self):
        self.write({"secret": "s", "dashboards": {"ax-project": ["zestim"]}})

        self.assertTrue(enroll.add_project_to_dashboard(self.path, "pante_capture"))
        self.assertEqual(["zestim", "pante_capture"],
                         self.read()["dashboards"]["ax-project"])

    def test_preserves_other_keys_in_sync_config(self):
        """dashboards 를 통째로 덮으면 그 머신의 토큰·머신명이 날아간다."""
        self.write({"secret": "s", "runs_token": "t", "machine": "mac-main",
                    "dashboards": {"ax-project": ["zestim"]}})

        enroll.add_project_to_dashboard(self.path, "pante_capture")

        cfg = self.read()
        self.assertEqual("t", cfg["runs_token"])
        self.assertEqual("mac-main", cfg["machine"])
        self.assertEqual("s", cfg["secret"])

    def test_preserves_other_dashboards(self):
        self.write({"dashboards": {"ax-project": ["zestim"], "other": ["x"]}})

        enroll.add_project_to_dashboard(self.path, "pante_capture")

        self.assertEqual(["x"], self.read()["dashboards"]["other"])

    def test_is_idempotent(self):
        self.write({"dashboards": {"ax-project": ["pante_capture"]}})

        self.assertFalse(enroll.add_project_to_dashboard(self.path, "pante_capture"))
        self.assertEqual(["pante_capture"], self.read()["dashboards"]["ax-project"])

    def test_creates_dashboards_when_absent(self):
        self.write({"secret": "s"})

        self.assertTrue(enroll.add_project_to_dashboard(self.path, "pante_capture"))
        self.assertEqual(["pante_capture"], self.read()["dashboards"]["ax-project"])

    def test_missing_sync_file_is_created(self):
        self.assertTrue(enroll.add_project_to_dashboard(self.path, "pante_capture"))
        self.assertEqual(["pante_capture"], self.read()["dashboards"]["ax-project"])

    def test_blank_key_is_ignored(self):
        self.write({"dashboards": {"ax-project": ["zestim"]}})

        self.assertFalse(enroll.add_project_to_dashboard(self.path, "   "))
        self.assertEqual(["zestim"], self.read()["dashboards"]["ax-project"])

    def test_broken_sync_json_aborts_instead_of_overwriting(self):
        """시크릿이 든 파일이다 — 파싱 실패 시 덮어쓰면 그 머신이 전송을 못 한다."""
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")

        with self.assertRaises(SystemExit):
            enroll.add_project_to_dashboard(self.path, "pante_capture")

    def test_written_file_is_owner_only(self):
        self.write({"dashboards": {"ax-project": []}})

        enroll.add_project_to_dashboard(self.path, "pante_capture")

        self.assertEqual(0o600, os.stat(self.path).st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
