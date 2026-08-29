"""수집 파이프라인이 죽은 것을 알아채는 장치를 고정한다.

세 번 겪었다. 폴더 rename 후 launchd 잡이 옛 경로를 보고 28회 연속 실패해 4일간
수집이 멈췄고, 점검 목록을 문서에 넣었더니 같은 고장이 재발했고, 죽은 워크트리
경로에 남은 등록이 유령 디렉토리를 되살리는 순환이 일주일 돌았다.

세 번 다 보드는 정상으로 보였고, 세 번 다 사람이 우연히 발견했다.

## 설계에서 가장 중요한 한 가지

**실제로 일어난 고장은 아무 기록도 남기지 않는다.** 스크립트 경로가 어긋나
프로세스가 아예 뜨지 않았으니 오류를 적을 주체가 없었다. 그래서 판단 기준은
"기록된 실패"가 아니라 **"성공의 부재"** 여야 한다 — 상태 파일이 오래됐거나
아예 없는 것 자체가 신호다. 아래 두 테스트가 그 성질을 고정한다:

- `test_missing_file_is_unknown_not_ok`
- `test_failure_does_not_erase_last_success`
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
HOOK = os.path.join(SCRIPTS, "hooks", "vibe-harness-session-start.sh")


def _load(name, path):
    sys.path.insert(0, SCRIPTS)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rr = _load("rr_pipeline", os.path.join(SCRIPTS, "reconcile_runs.py"))
srv = _load("srv_pipeline", os.path.join(SCRIPTS, "server.py"))


def hours_ago(n):
    return (datetime.now(timezone.utc) - timedelta(hours=n)).isoformat(timespec="seconds")


class RecordStatusTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "pipeline-status.json")

    def test_success_records_last_success(self):
        doc = rr.record_pipeline_status(True, done=7, path=self.path)
        self.assertIsNotNone(doc["last_success"])
        self.assertEqual(7, doc["projects_done"])
        self.assertIsNone(doc["last_error"])
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(doc, json.load(fh))

    def test_failure_does_not_erase_last_success(self):
        """실패가 성공 기록을 덮으면 '마지막으로 데이터가 들어온 게 언제냐'에 답할 수 없다."""
        first = rr.record_pipeline_status(True, done=3, path=self.path)
        after = rr.record_pipeline_status(False, error="boom", path=self.path)
        self.assertEqual(first["last_success"], after["last_success"])
        self.assertEqual("boom", after["last_error"])

    def test_failure_is_recorded_when_reconcile_raises(self):
        """--all 이 SystemExit 로 죽어도 상태는 남고 예외는 그대로 올라간다."""
        rr.record_pipeline_status(True, done=1, path=self.path)
        saved, rr.PIPELINE_STATUS_PATH = rr.PIPELINE_STATUS_PATH, self.path
        try:
            def boom(_a):
                raise SystemExit("프로젝트 전부 실패")
            orig, rr._reconcile_all = rr._reconcile_all, boom
            try:
                with self.assertRaises(SystemExit):
                    rr._run_all(object())
            finally:
                rr._reconcile_all = orig
        finally:
            rr.PIPELINE_STATUS_PATH = saved
        with open(self.path, encoding="utf-8") as fh:
            self.assertIn("전부 실패", json.load(fh)["last_error"])

    def test_write_is_atomic(self):
        rr.record_pipeline_status(True, path=self.path)
        self.assertFalse(os.path.exists(self.path + ".tmp"), "tmp 파일이 남았다")

    def test_missing_file_reads_as_empty(self):
        self.assertEqual({}, rr.read_pipeline_status(os.path.join(self.dir, "nope.json")))

    def test_corrupt_file_reads_as_empty_not_crash(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        self.assertEqual({}, rr.read_pipeline_status(self.path))


class HealthJudgementTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "pipeline-status.json")
        self.saved = srv.PIPELINE_STATUS_PATH
        srv.PIPELINE_STATUS_PATH = self.path

    def tearDown(self):
        srv.PIPELINE_STATUS_PATH = self.saved

    def write(self, **doc):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    def test_fresh_success_is_ok(self):
        self.write(last_success=hours_ago(1), projects_done=5)
        self.assertEqual("ok", srv._pipeline_health()["state"])

    def test_old_success_is_stale(self):
        self.write(last_success=hours_ago(srv.PIPELINE_STALE_HOURS + 6))
        health = srv._pipeline_health()
        self.assertEqual("stale", health["state"])
        self.assertIn("시간 전", health["reason"])

    def test_boundary_just_inside_is_ok(self):
        self.write(last_success=hours_ago(srv.PIPELINE_STALE_HOURS - 1))
        self.assertEqual("ok", srv._pipeline_health()["state"])

    def test_missing_file_is_unknown_not_ok(self):
        """실제 고장은 프로세스가 안 떠서 파일조차 안 생긴다. 이것을 정상으로 보면 안 된다."""
        if os.path.exists(self.path):
            os.remove(self.path)
        self.assertNotEqual("ok", srv._pipeline_health()["state"])

    def test_success_field_absent_is_stale(self):
        self.write(last_attempt=hours_ago(1), last_error="죽음")
        self.assertEqual("stale", srv._pipeline_health()["state"])

    def test_corrupt_file_is_not_ok(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("not json")
        self.assertNotEqual("ok", srv._pipeline_health()["state"])

    def test_recent_success_with_later_failure_is_degraded(self):
        """성공 뒤 시도가 실패했는데 ok 라고 하면 이 장치의 존재 이유가 사라진다."""
        self.write(last_success=hours_ago(2), last_attempt=hours_ago(1),
                   last_error="프로젝트 전부 실패")
        health = srv._pipeline_health()
        self.assertEqual("degraded", health["state"])
        self.assertIn("이후 시도가 실패", health["reason"])

    def test_clean_success_is_plain_ok(self):
        self.write(last_success=hours_ago(1), last_error=None)
        self.assertEqual("ok", srv._pipeline_health()["state"])

    def test_naive_timestamp_does_not_crash(self):
        self.write(last_success=datetime.now().isoformat(timespec="seconds"))
        self.assertIn(srv._pipeline_health()["state"], ("ok", "stale"))


class HookAgreesWithServerTest(unittest.TestCase):
    """임계값이 훅과 서버 두 곳에 있다. 갈라지면 한쪽만 경고한다."""

    def test_threshold_matches(self):
        with open(HOOK, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("STALE_HOURS = %d" % srv.PIPELINE_STALE_HOURS, body,
                      "훅의 임계값이 server.PIPELINE_STALE_HOURS 와 다르다")

    def test_hook_is_silent_when_fresh(self):
        out = self._run_hook(hours_ago(1))
        self.assertNotIn("수집이", out)

    def test_hook_warns_when_stale(self):
        out = self._run_hook(hours_ago(100), last_error="No such file or directory")
        self.assertIn("수집이", out)
        self.assertIn("No such file", out)

    def _run_hook(self, last_success, last_error=None):
        home = tempfile.mkdtemp()
        d = os.path.join(home, ".claude", "skills", "vibe-harness")
        os.makedirs(d)
        with open(os.path.join(d, "pipeline-status.json"), "w", encoding="utf-8") as fh:
            json.dump({"last_success": last_success, "last_error": last_error}, fh)
        env = dict(os.environ, HOME=home)
        return subprocess.run(["bash", HOOK], capture_output=True, text=True,
                              env=env, cwd=home).stdout


if __name__ == "__main__":
    unittest.main()
