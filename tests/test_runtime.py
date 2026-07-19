import concurrent.futures
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib import error as urllib_error
from urllib import request as urllib_request


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

spec = importlib.util.spec_from_file_location("vibe_server", os.path.join(SCRIPTS, "server.py"))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = self.tmp.name
        self.kanban = os.path.join(self.project, "vibe-harness")
        os.makedirs(self.kanban)
        self._write_json("kanban.json", {"version": 1, "next_id": 2, "tasks": [self.task()]})
        self._write_json("runs.json", {"version": 1, "runs": []})
        self.write_policy(pass_gate=True, approval="required", max_attempts=2)
        self.original_sync = server._schedule_remote_sync
        server._schedule_remote_sync = lambda *args, **kwargs: None

    def tearDown(self):
        server._schedule_remote_sync = self.original_sync
        self.tmp.cleanup()

    def task(self, **updates):
        item = {
            "id": 1,
            "title": "managed task",
            "description": "",
            "details": "",
            "status": "todo",
            "priority": "high",
            "category": "backend",
            "target_date": "",
            "started_at": "",
            "completed_at": "",
            "lines_added": 0,
            "lines_removed": 0,
            "tokens_used": 0,
            "created_at": "2026-07-18T00:00:00",
            "updated_at": "2026-07-18T00:00:00",
            "position": 0,
            "phase": "PHASE_PMF05",
            "review": "",
            "created_by": "human",
            "assigned_to": "human",
        }
        item.update(updates)
        return item

    def _write_json(self, name, value):
        with open(os.path.join(self.kanban, name), "w", encoding="utf-8") as handle:
            json.dump(value, handle)

    def _read_json(self, name):
        with open(os.path.join(self.kanban, name), encoding="utf-8") as handle:
            return json.load(handle)

    def write_policy(self, pass_gate, approval="required", max_attempts=2):
        code = "raise SystemExit(0)" if pass_gate else "raise SystemExit(7)"
        self._write_json("worker.json", {
            "version": 1,
            "lease_ttl_seconds": 10,
            "heartbeat_seconds": 5,
            "max_attempts": max_attempts,
            "approval": {"default": approval, "auto_complete_categories": [], "always_require_categories": []},
            "test_gate": {"commands": [{"argv": [sys.executable, "-c", code], "timeout_seconds": 5}]},
            "adapters": {},
        })

    def claim(self, worker="worker-a"):
        return server._runtime_claim(self.kanban, {"worker_id": worker, "agent": "test"})

    @staticmethod
    def credentials(claim):
        return {key: claim[key] for key in ("run_id", "lease_id", "lease_token")}

    def test_atomic_claim_allows_exactly_one_worker(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda worker: self.claim(worker), ["worker-a", "worker-b"]))
        self.assertEqual([status for _, _, status in results].count(201), 1)
        self.assertEqual([status for _, _, status in results].count(409), 1)
        runtime = self._read_json("runtime.json")
        self.assertEqual(sum(lease["status"] == "active" for lease in runtime["leases"].values()), 1)

    def test_heartbeat_extends_lease_and_rejects_wrong_token(self):
        claim, _, _ = self.claim()
        before = claim["lease"]["expires_at"]
        result, error, status = server._runtime_heartbeat(self.kanban, self.credentials(claim))
        self.assertEqual((error, status), (None, 200))
        self.assertGreaterEqual(result["expires_at"], before)
        bad = self.credentials(claim)
        bad["lease_token"] = "wrong"
        _, error, status = server._runtime_heartbeat(self.kanban, bad)
        self.assertEqual((error, status), ("invalid lease token", 403))

    def test_expired_lease_returns_task_to_todo_and_appends_run(self):
        claim, _, _ = self.claim()
        runtime = self._read_json("runtime.json")
        runtime["leases"][claim["lease_id"]]["expires_at"] = "2000-01-01T00:00:00+00:00"
        self._write_json("runtime.json", runtime)
        server._runtime_view(self.kanban)
        self.assertEqual(self._read_json("kanban.json")["tasks"][0]["status"], "todo")
        runs = self._read_json("runs.json")["runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "expired")
        self.assertEqual(runs[0]["run_id"], claim["run_id"])

    def test_failed_gate_never_marks_done_and_exhaustion_reviews(self):
        self.write_policy(pass_gate=False, max_attempts=2)
        first, _, _ = self.claim()
        result, error, status = server._runtime_finish(self.kanban, self.credentials(first), "complete")
        self.assertEqual((error, status), (None, 200))
        self.assertEqual(result["task"]["status"], "todo")
        self.assertFalse(server._managed_done_allowed(self.kanban, result["task"]))
        second, _, _ = self.claim()
        result, error, status = server._runtime_finish(self.kanban, self.credentials(second), "complete")
        self.assertEqual((error, status), (None, 200))
        self.assertEqual(result["task"]["status"], "review")
        self.assertEqual(len(self._read_json("runs.json")["runs"]), 2)

    def test_passed_gate_waits_for_approval_then_done(self):
        claim, _, _ = self.claim()
        result, error, status = server._runtime_finish(self.kanban, self.credentials(claim), "complete")
        self.assertEqual((error, status), (None, 200))
        self.assertEqual(result["task"]["status"], "review")
        self.assertEqual(result["execution"]["status"], "awaiting_approval")
        result, error, status = server._runtime_action(self.kanban, {"run_id": claim["run_id"], "action": "approve"})
        self.assertEqual((error, status), (None, 200))
        self.assertEqual(result["task"]["status"], "done")
        self.assertTrue(server._managed_done_allowed(self.kanban, result["task"]))

    def test_auto_policy_completes_only_after_passed_gate(self):
        self.write_policy(pass_gate=True, approval="auto")
        claim, _, _ = self.claim()
        result, error, status = server._runtime_finish(self.kanban, self.credentials(claim), "complete")
        self.assertEqual((error, status), (None, 200))
        self.assertEqual(result["task"]["status"], "done")
        self.assertEqual(result["execution"]["status"], "passed")

    def test_terminal_submission_is_idempotent(self):
        claim, _, _ = self.claim()
        payload = self.credentials(claim)
        first, error, status = server._runtime_finish(self.kanban, payload, "complete")
        self.assertEqual((error, status), (None, 200))
        second, error, status = server._runtime_finish(self.kanban, payload, "complete")
        self.assertEqual((error, status), (None, 200))
        self.assertEqual(first["execution"]["run_id"], second["execution"]["run_id"])
        self.assertEqual(len(self._read_json("runs.json")["runs"]), 1)

    def test_runtime_view_never_exposes_lease_token_hash(self):
        self.claim()
        view = server._runtime_view(self.kanban)
        self.assertEqual(len(view["leases"]), 1)
        self.assertNotIn("token_hash", next(iter(view["leases"].values())))

    def test_remote_approval_command_applies_and_acknowledges(self):
        claim, _, _ = self.claim()
        server._runtime_finish(self.kanban, self.credentials(claim), "complete")
        command = {"id": "cmd_test", "source_key": "demo", "run_id": claim["run_id"], "action": "approve"}
        calls = []
        original_config = server._load_sync_config
        original_projects = server.load_projects
        original_remote = server._remote_request
        server._load_sync_config = lambda: {"endpoint": "http://example.test", "secret": "x", "dashboards": {"ax-project": ["demo"]}}
        server.load_projects = lambda: {"demo": {"kanban_dir": self.kanban}}
        def remote(_cfg, method, query=None, payload=None):
            calls.append((method, query, payload))
            return {"commands": [command]} if method == "GET" else {"ok": True}
        server._remote_request = remote
        try:
            self.assertEqual(server._poll_remote_commands_once(), 1)
        finally:
            server._load_sync_config = original_config
            server.load_projects = original_projects
            server._remote_request = original_remote
        self.assertEqual(self._read_json("kanban.json")["tasks"][0]["status"], "done")
        self.assertEqual(calls[-1][0], "DELETE")
        self.assertEqual(calls[-1][2]["command_ids"], ["cmd_test"])

    def test_foreign_host_does_not_acknowledge_unknown_run(self):
        command = {"id": "cmd_foreign", "source_key": "demo", "run_id": "run_on_other_host", "action": "approve"}
        calls = []
        original_config = server._load_sync_config
        original_projects = server.load_projects
        original_remote = server._remote_request
        server._load_sync_config = lambda: {"endpoint": "http://example.test", "secret": "x", "dashboards": {"ax-project": ["demo"]}}
        server.load_projects = lambda: {"demo": {"kanban_dir": self.kanban}}
        def remote(_cfg, method, query=None, payload=None):
            calls.append(method)
            return {"commands": [command]}
        server._remote_request = remote
        try:
            self.assertEqual(server._poll_remote_commands_once(), 0)
        finally:
            server._load_sync_config = original_config
            server.load_projects = original_projects
            server._remote_request = original_remote
        self.assertEqual(calls, ["GET"])

    def test_http_worker_routes_and_done_guard(self):
        original_projects = server.load_projects
        server.load_projects = lambda: {"demo": {"name": "Demo", "kanban_dir": self.kanban}}
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_port}/api/demo"
        def call(method, path, payload=None):
            raw = json.dumps(payload).encode() if payload is not None else None
            req = urllib_request.Request(base + path, data=raw, method=method, headers={"Content-Type": "application/json"})
            try:
                with urllib_request.urlopen(req, timeout=3) as response:
                    return response.status, json.loads(response.read())
            except urllib_error.HTTPError as exc:
                try:
                    return exc.code, json.loads(exc.read())
                finally:
                    exc.close()
        try:
            status, claim = call("POST", "/worker/claim", {"worker_id": "http-worker", "agent": "test"})
            self.assertEqual(status, 201)
            status, view = call("GET", "/runtime")
            self.assertEqual(status, 200)
            self.assertNotIn("token_hash", view["leases"][claim["lease_id"]])
            status, body = call("PUT", "/tasks/1", {"status": "done"})
            self.assertEqual(status, 409)
            self.assertIn("test gate", body["error"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            server.load_projects = original_projects

    def test_local_worker_cli_uses_isolated_git_worktree_end_to_end(self):
        self.write_policy(pass_gate=True, approval="auto")
        subprocess.run(["git", "init", "-q", self.project], check=True)
        subprocess.run(["git", "-C", self.project, "config", "user.name", "Runtime Test"], check=True)
        subprocess.run(["git", "-C", self.project, "config", "user.email", "runtime@example.test"], check=True)
        subprocess.run(["git", "-C", self.project, "add", "."], check=True)
        subprocess.run(["git", "-C", self.project, "commit", "-qm", "fixture"], check=True)
        original_projects = server.load_projects
        server.load_projects = lambda: {"demo": {"name": "Demo", "kanban_dir": self.kanban}}
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        worktrees = tempfile.TemporaryDirectory()
        env = os.environ.copy()
        env["VIBE_HARNESS_WORKTREE_ROOT"] = worktrees.name
        try:
            completed = subprocess.run([
                sys.executable, os.path.join(SCRIPTS, "worker.py"), "demo",
                "--server", f"http://127.0.0.1:{httpd.server_port}",
                "--project-root", self.project,
                "--agent", "test", "--once", "--command",
                sys.executable, "-c", "raise SystemExit(0)",
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            task = self._read_json("kanban.json")["tasks"][0]
            self.assertEqual(task["status"], "done")
            runtime = self._read_json("runtime.json")
            execution = next(iter(runtime["executions"].values()))
            self.assertTrue(execution["tests"]["passed"])
            self.assertNotEqual(os.path.realpath(execution["worktree_path"]), os.path.realpath(self.project))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            server.load_projects = original_projects
            worktrees.cleanup()


if __name__ == "__main__":
    unittest.main()
