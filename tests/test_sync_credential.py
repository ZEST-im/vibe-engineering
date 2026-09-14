"""스냅샷 동기화가 쓸 자격증명 선택.

왜 이 테스트가 있나 — 참가 플로우가 머신에 심어주는 것은 개인 토큰 하나뿐이고 공유
secret 은 어디서도 내려가지 않는다. secret 을 손으로 못 받은 머신은 _load_sync_config
가 None 을 돌려주는 바람에 **모든 프로젝트의** 스냅샷이 조용히 멈췄다. 에러도 로그도
없어서, 옛날 머신이 밀어둔 행이 대시보드에 남아 있으면 본인은 잘 되는 줄 안다
(실측: 한 사람의 두 머신 중 하나만 밀고 있었고, 화면에는 티가 나지 않았다).

순서가 reconcile_runs.push_credential 과 반대다. 그쪽은 사람별 귀속이 필요해 개인
토큰이 먼저지만, 스냅샷은 source key 단위 머지라 귀속이 없다. 이미 secret 으로 돌고
있는 머신의 동작을 바꾸지 않는 쪽이 안전하므로 secret 을 먼저 본다.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

spec = importlib.util.spec_from_file_location("vibe_server_cred", os.path.join(SCRIPTS, "server.py"))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class SnapshotCredentialTest(unittest.TestCase):
    def test_공유_secret_이_있으면_그대로_쓴다(self):
        cfg = {"secret": "shared", "runs_token": "personal"}

        self.assertEqual("shared", server.snapshot_credential(cfg))

    def test_secret_이_없으면_개인_토큰으로_떨어진다(self):
        self.assertEqual("personal", server.snapshot_credential({"runs_token": "personal"}))

    def test_공백만_있는_값은_없는_것으로_본다(self):
        cfg = {"secret": "   ", "runs_token": "personal"}

        self.assertEqual("personal", server.snapshot_credential(cfg))

    def test_둘_다_없으면_빈_문자열(self):
        self.assertEqual("", server.snapshot_credential({}))
        self.assertEqual("", server.snapshot_credential(None))


class LoadSyncConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sync.json")
        patcher = mock.patch.object(server, "SYNC_CONFIG_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, cfg):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)

    def test_개인_토큰만_있어도_동기화가_살아있다(self):
        self._write({
            "enabled": True,
            "endpoint": "https://os.zest.im/api/internal/vibe-harness/sync",
            "runs_token": "personal",
            "dashboards": {"ax-project": ["demo-project"]},
        })

        cfg = server._load_sync_config()

        self.assertIsNotNone(cfg)
        self.assertEqual("personal", server.snapshot_credential(cfg))

    def test_공유_secret_만_있는_기존_머신도_그대로_산다(self):
        self._write({
            "enabled": True,
            "endpoint": "https://os.zest.im/api/internal/vibe-harness/sync",
            "secret": "shared",
            "dashboards": {"ax-project": ["zesty-os"]},
        })

        self.assertIsNotNone(server._load_sync_config())

    def test_자격증명이_아예_없으면_끈다(self):
        self._write({
            "enabled": True,
            "endpoint": "https://os.zest.im/api/internal/vibe-harness/sync",
            "dashboards": {"ax-project": ["zesty-os"]},
        })

        self.assertIsNone(server._load_sync_config())


class PostSnapshotAuthTest(unittest.TestCase):
    """실제로 헤더에 실리는 값까지 본다 — 고르기만 하고 안 쓰면 의미가 없다."""

    def _sent_header(self, cfg):
        captured = {}

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=None):
            captured["auth"] = req.get_header("Authorization")
            return _Resp()

        with mock.patch.object(server.urllib_request, "urlopen", fake_urlopen):
            server._post_snapshot(cfg, {"dashboard": "ax-project", "sources": []})
        return captured["auth"]

    def test_개인_토큰_머신은_그_토큰으로_보낸다(self):
        cfg = {"endpoint": "https://example.test/sync", "runs_token": "personal"}

        self.assertEqual("Bearer personal", self._sent_header(cfg))

    def test_공유_secret_머신은_그대로_secret_으로_보낸다(self):
        cfg = {"endpoint": "https://example.test/sync", "secret": "shared", "runs_token": "personal"}

        self.assertEqual("Bearer shared", self._sent_header(cfg))


if __name__ == "__main__":
    unittest.main()
