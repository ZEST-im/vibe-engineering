"""주기 실행 잡을 설치하는 스크립트를 고정한다.

## 왜 이 파일부터인가

`install_reconcile.py` 는 커버리지 **0%** 였다. 하필 **이 파일이 낸 사고**가 이 레포에서
가장 오래간 침묵이다 — 폴더 rename 뒤 plist 가 없는 파일을 가리켰고, 잡이 28회 연속
실패하며 **토큰 수집이 4일간 죽어 있었다.** 보드는 정상으로 보였고 사람이 우연히 발견했다.

커버리지 총계를 올리려고 여기 온 것이 아니다. **사고를 낸 파일부터** 본다.

## 무엇을 고정하는가

1. **경로 어긋남을 물어볼 수 있다.** 조용한 고장이라 감지가 아니라 *질문할 방법*이
   없었던 것이 문제였다.
2. **plist 는 문자열 조립이 아니다.** 경로에 `&` 하나면 XML 이 깨지고, launchd 는
   깨진 것을 로드하지 못한 채 아무 말도 하지 않는다.
3. **재설치는 멱등이다.** 두 번 돌려도 같은 정의가 남고, 덮어쓰기 전에 unload 한다 —
   로드된 채로 덮으면 옛 정의가 살아 있어 "고쳤는데 안 고쳐진" 상태가 된다.

launchctl 은 실제로 부르지 않는다. 부르면 이 테스트가 **이 머신의 실제 수집 잡을
건드린다** — 감시 신호를 테스트가 더럽히면 그 신호는 곧 무시된다(PMF09 에서 같은
것을 한 번 겪었다).
"""
import importlib.util
import os
import plistlib
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

_spec = importlib.util.spec_from_file_location(
    "install_reconcile", os.path.join(SCRIPTS, "install_reconcile.py"))
ir = importlib.util.module_from_spec(_spec)
sys.modules["install_reconcile"] = ir
_spec.loader.exec_module(ir)


class FakeRun:
    """launchctl 대역. **실제로 부르지 않는다** — 이 머신의 수집 잡을 건드리게 된다."""

    def __init__(self, listing="", returncode=0):
        self.calls = []
        self.listing = listing
        self.returncode = returncode

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))

        class R:
            pass
        r = R()
        r.returncode = self.returncode
        r.stdout = self.listing if argv[:2] == ["launchctl", "list"] else ""
        r.stderr = ""
        return r

    def loaded(self, exit_status="0", pid="-"):
        self.listing = "%s\t%s\t%s\n" % (pid, exit_status, ir.LABEL)
        return self


def sandbox():
    d = tempfile.mkdtemp()
    return (os.path.join(d, "LaunchAgents", ir.LABEL + ".plist"),
            os.path.join(d, "reconcile_runs.py"),
            os.path.join(d, "logs", "reconcile.log"))


def make_target(path):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# stand-in\n")
    return path


class PlistIsBuiltNotConcatenatedTest(unittest.TestCase):
    def test_a_path_with_xml_metacharacters_survives(self):
        """문자열 템플릿이었다면 여기서 XML 이 깨진다.

        깨진 plist 를 launchd 는 로드하지 못하고, 아무 말도 하지 않는다 —
        '성공처럼 보이는 침묵'의 또 한 형태다.
        """
        plist, _t, log = sandbox()
        nasty = "/tmp/a & b/<x>/reconcile_runs.py"
        ir.write_plist(plist, ir.plist_dict(nasty, log))
        self.assertEqual(nasty, ir.installed_target(plist))

    def test_the_job_definition_carries_what_launchd_needs(self):
        body = ir.plist_dict("/x/reconcile_runs.py", "/x/log")
        self.assertEqual(ir.LABEL, body["Label"])
        self.assertEqual(10800, body["StartInterval"])
        self.assertTrue(body["RunAtLoad"],
                        "설치 즉시 한 번 돌지 않으면 첫 3시간이 조용한 공백이 된다")
        self.assertEqual(["--all", "--push"], body["ProgramArguments"][2:])

    def test_the_label_is_the_one_everything_else_references(self):
        """훅 안내문·문서·CURRENT_PHASE 의 Do NOT touch 가 이 이름을 가리킨다."""
        self.assertEqual("com.vibe-harness.reconcile", ir.LABEL)

    def test_a_corrupt_plist_reads_as_missing_not_as_a_crash(self):
        plist, _t, _l = sandbox()
        os.makedirs(os.path.dirname(plist))
        with open(plist, "w", encoding="utf-8") as fh:
            fh.write("not a plist")
        self.assertIsNone(ir.read_plist(plist))


class AsksWhetherItIsStillValidTest(unittest.TestCase):
    """경로 어긋남은 조용하다. 물어볼 방법이 없었던 것이 4일 침묵의 원인이다."""

    def test_clean_install_reports_no_problems(self):
        plist, target, log = sandbox()
        make_target(target)
        ir.write_plist(plist, ir.plist_dict(target, log))
        self.assertEqual([], ir.problems(plist, target, FakeRun().loaded()))

    def test_missing_plist_is_reported(self):
        plist, target, _l = sandbox()
        found = ir.problems(plist, target, FakeRun().loaded())
        self.assertEqual(1, len(found))
        self.assertIn("설치되어 있지 않다", found[0])

    def test_a_plist_pointing_at_a_deleted_file_is_the_outage(self):
        """이것이 정확히 4일간 수집을 멈춘 형태다."""
        plist, target, log = sandbox()
        make_target(target)
        ir.write_plist(plist, ir.plist_dict(target, log))
        os.remove(target)
        found = ir.problems(plist, target, FakeRun().loaded())
        self.assertTrue(any("없는 파일을 가리킨다" in p for p in found), found)

    def test_a_plist_from_another_checkout_is_reported(self):
        """폴더를 rename 하면 여기가 갈린다. 파일은 **존재하므로** 존재 검사로는 안 잡힌다."""
        plist, target, log = sandbox()
        make_target(target)
        other = make_target(os.path.join(os.path.dirname(target), "moved.py"))
        ir.write_plist(plist, ir.plist_dict(other, log))
        found = ir.problems(plist, target, FakeRun().loaded())
        self.assertTrue(any("다른 체크아웃" in p for p in found), found)

    def test_a_nonzero_exit_status_is_reported(self):
        """2열이 마지막 exit status 다. 28회 연속 실패가 여기 계속 적혀 있었다."""
        plist, target, log = sandbox()
        make_target(target)
        ir.write_plist(plist, ir.plist_dict(target, log))
        found = ir.problems(plist, target, FakeRun().loaded(exit_status="78"))
        self.assertTrue(any("exit status 가 78" in p for p in found), found)

    def test_registered_but_not_loaded_is_reported(self):
        """plist 는 있는데 launchctl 이 모르면 아무것도 안 돈다."""
        plist, target, log = sandbox()
        make_target(target)
        ir.write_plist(plist, ir.plist_dict(target, log))
        found = ir.problems(plist, target, FakeRun(listing="0\t0\tcom.other.job\n"))
        self.assertTrue(any("로드되지 않았다" in p for p in found), found)

    def test_check_never_touches_launchctl_state(self):
        """묻기만 한다. 확인이 상태를 바꾸면 그건 확인이 아니다."""
        plist, target, log = sandbox()
        make_target(target)
        ir.write_plist(plist, ir.plist_dict(target, log))
        run = FakeRun().loaded()
        ir.problems(plist, target, run)
        for argv in run.calls:
            self.assertNotIn(argv[1], ("load", "unload", "bootstrap", "bootout"),
                             "확인이 잡을 건드렸다: %s" % " ".join(argv))


class ReinstallIsIdempotentTest(unittest.TestCase):
    def test_twice_leaves_one_identical_definition(self):
        plist, target, log = sandbox()
        make_target(target)
        ir.install(plist, target, log, FakeRun())
        with open(plist, "rb") as fh:
            first = fh.read()
        ir.install(plist, target, log, FakeRun())
        with open(plist, "rb") as fh:
            self.assertEqual(first, fh.read())

    def test_it_unloads_before_overwriting(self):
        """로드된 채로 덮어쓰면 옛 정의가 살아 있다 — 고쳤는데 안 고쳐진 상태가 된다."""
        plist, target, log = sandbox()
        make_target(target)
        ir.install(plist, target, log, FakeRun())      # 첫 설치: 지울 것이 없다
        run = FakeRun()
        ir.install(plist, target, log, run)
        verbs = [a[1] for a in run.calls]
        self.assertEqual(["unload", "load"], verbs,
                         "덮어쓰기 전에 unload 하지 않는다")

    def test_reinstall_repairs_a_moved_checkout(self):
        """rename 뒤 다시 설치하면 경로가 실제로 고쳐져야 한다."""
        plist, target, log = sandbox()
        make_target(target)
        stale = os.path.join(os.path.dirname(target), "old", "reconcile_runs.py")
        ir.write_plist(plist, ir.plist_dict(stale, log))
        ir.install(plist, target, log, FakeRun())
        self.assertEqual(target, ir.installed_target(plist))
        self.assertEqual([], ir.problems(plist, target, FakeRun().loaded()))

    def test_uninstall_removes_the_file(self):
        plist, target, log = sandbox()
        make_target(target)
        ir.install(plist, target, log, FakeRun())
        ir.uninstall(plist, FakeRun())
        self.assertFalse(os.path.exists(plist))

    def test_uninstall_on_nothing_is_not_an_error(self):
        plist, _t, _l = sandbox()
        run = FakeRun()
        ir.uninstall(plist, run)
        self.assertEqual([], run.calls, "없는 잡을 unload 하려 들었다")


class ReadsALaunchctlListingTest(unittest.TestCase):
    def test_finds_our_label_among_others(self):
        run = FakeRun(listing=(
            "123\t0\tcom.apple.something\n"
            "-\t78\tcom.vibe-harness.reconcile\n"
            "456\t0\tcom.vibe-harness.server\n"))
        self.assertEqual(("-", "78"), ir.job_status(runner=run))

    def test_absent_label_is_none_not_an_exception(self):
        self.assertIsNone(ir.job_status(runner=FakeRun(listing="1\t0\tcom.other\n")))

    def test_a_failing_launchctl_is_none(self):
        self.assertIsNone(ir.job_status(runner=FakeRun(returncode=1)))


class WrittenFileIsAValidPlistTest(unittest.TestCase):
    def test_the_system_parser_accepts_it(self):
        """우리 파서만 읽을 수 있으면 소용없다. launchd 가 읽어야 한다."""
        plist, target, log = sandbox()
        ir.write_plist(plist, ir.plist_dict(target, log))
        with open(plist, "rb") as fh:
            doc = plistlib.load(fh)
        self.assertEqual(ir.LABEL, doc["Label"])


if __name__ == "__main__":
    unittest.main()
