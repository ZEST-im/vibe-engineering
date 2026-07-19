"""Execution-control primitives for Vibe Harness.

This module deliberately knows nothing about Kanban task semantics. server.py owns
task transitions while this module provides policy loading, atomic runtime files,
lease credentials, timestamps, and test-command execution.
"""

import contextlib
import hashlib
import json
import os
import secrets
import shlex
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone

try:
    import fcntl
except ImportError:
    fcntl = None


DEFAULT_POLICY = {
    "version": 1,
    "lease_ttl_seconds": 120,
    "heartbeat_seconds": 30,
    "max_attempts": 2,
    "approval": {
        "default": "required",
        "auto_complete_categories": ["docs", "test"],
        "always_require_categories": ["database", "security", "deploy"],
    },
    "test_gate": {"commands": []},
    "adapters": {},
}

_locks_guard = threading.Lock()
_locks = {}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def expires_at(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(seconds)))).isoformat(timespec="seconds")


def runtime_path(kanban_dir):
    return os.path.join(kanban_dir, "runtime.json")


def policy_path(kanban_dir):
    return os.path.join(kanban_dir, "worker.json")


def empty_runtime():
    return {"version": 1, "leases": {}, "executions": {}}


def read_runtime(kanban_dir):
    try:
        with open(runtime_path(kanban_dir), encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return empty_runtime()
        data.setdefault("version", 1)
        data.setdefault("leases", {})
        data.setdefault("executions", {})
        return data
    except (OSError, ValueError, TypeError):
        return empty_runtime()


def write_runtime(kanban_dir, data):
    path = runtime_path(kanban_dir)
    os.makedirs(kanban_dir, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _merge(base, override):
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_policy(kanban_dir):
    try:
        with open(policy_path(kanban_dir), encoding="utf-8") as handle:
            raw = json.load(handle)
        policy = _merge(DEFAULT_POLICY, raw if isinstance(raw, dict) else {})
    except (OSError, ValueError, TypeError):
        policy = _merge(DEFAULT_POLICY, {})
    policy["lease_ttl_seconds"] = max(10, min(3600, int(policy.get("lease_ttl_seconds", 120))))
    policy["heartbeat_seconds"] = max(5, min(policy["lease_ttl_seconds"] // 2, int(policy.get("heartbeat_seconds", 30))))
    policy["max_attempts"] = max(1, min(10, int(policy.get("max_attempts", 2))))
    return policy


@contextlib.contextmanager
def runtime_lock(kanban_dir):
    key = os.path.abspath(kanban_dir)
    with _locks_guard:
        lock = _locks.setdefault(key, threading.RLock())
    with lock:
        os.makedirs(kanban_dir, exist_ok=True)
        lock_root = os.path.expanduser(os.environ.get(
            "VIBE_HARNESS_RUNTIME_LOCK_DIR",
            "~/.claude/skills/vibe-harness/runtime-locks",
        ))
        os.makedirs(lock_root, exist_ok=True)
        lock_name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".lock"
        lock_path = os.path.join(lock_root, lock_name)
        with open(lock_path, "a+", encoding="utf-8") as handle:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def new_identity():
    token = secrets.token_urlsafe(32)
    return {
        "run_id": "run_" + uuid.uuid4().hex,
        "lease_id": "lease_" + uuid.uuid4().hex,
        "lease_token": token,
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
    }


def valid_token(lease, token):
    if not lease or not token:
        return False
    actual = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
    return secrets.compare_digest(str(lease.get("token_hash", "")), actual)


def sanitized_runtime(data, policy=None):
    leases = {}
    for key, value in data.get("leases", {}).items():
        leases[key] = {field: item for field, item in value.items() if field != "token_hash"}
    executions = {}
    for key, value in data.get("executions", {}).items():
        executions[key] = {field: item for field, item in value.items() if field != "worktree_path"}
    return {
        "version": data.get("version", 1),
        "leases": leases,
        "executions": executions,
        "policy": policy,
    }


def approval_required(policy, category):
    approval = policy.get("approval", {})
    category = str(category or "").lower()
    if category in [str(item).lower() for item in approval.get("always_require_categories", [])]:
        return True
    if category in [str(item).lower() for item in approval.get("auto_complete_categories", [])]:
        return False
    return approval.get("default", "required") != "auto"


def _command_spec(item, default_timeout):
    if isinstance(item, str):
        return shlex.split(item), default_timeout
    if isinstance(item, dict):
        argv = item.get("argv", [])
        timeout = int(item.get("timeout_seconds", default_timeout))
        return [str(part) for part in argv], timeout
    return [], default_timeout


def run_test_gate(kanban_dir, policy, workdir=None):
    commands = policy.get("test_gate", {}).get("commands", [])
    if not commands:
        return {"status": "not_configured", "passed": False, "commands": []}
    project_dir = os.path.abspath(workdir or os.path.dirname(os.path.abspath(kanban_dir)))
    results = []
    for item in commands:
        argv, timeout = _command_spec(item, 600)
        if not argv:
            results.append({"argv": [], "exit_code": None, "status": "invalid", "output": "empty argv"})
            return {"status": "failed", "passed": False, "commands": results}
        try:
            completed = subprocess.run(
                argv,
                cwd=project_dir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=max(1, timeout),
                env=os.environ.copy(),
            )
            output = (completed.stdout or "")[-12000:]
            result = {"argv": argv, "exit_code": completed.returncode, "status": "passed" if completed.returncode == 0 else "failed", "output": output}
        except subprocess.TimeoutExpired as exc:
            output = ((exc.stdout or "") if isinstance(exc.stdout, str) else "")[-12000:]
            result = {"argv": argv, "exit_code": None, "status": "timeout", "output": output}
        except OSError as exc:
            result = {"argv": argv, "exit_code": None, "status": "error", "output": str(exc)}
        results.append(result)
        if result["status"] != "passed":
            return {"status": "failed", "passed": False, "commands": results}
    return {"status": "passed", "passed": True, "commands": results}
