"""Execution-control primitives for Vibe Engineering.

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
import time
import uuid
from datetime import datetime, timedelta, timezone

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt          # Windows 표준 모듈. POSIX 에는 없다
except ImportError:
    msvcrt = None


def read_json_fast(path):
    """JSON 을 읽되 **핸들을 최대한 빨리 닫는다.**

    `json.load(fh)` 는 파싱이 끝날 때까지 파일을 연 채로 둔다. POSIX 에서는
    상관없지만 Windows 에서는 그 시간 동안 다른 쪽의 os.replace 가 거부된다.
    파싱은 바이트를 다 읽은 뒤에 해도 되므로, 여는 구간을 read 까지로 줄인다.
    태스크 60개짜리 보드에서 파싱이 읽기보다 훨씬 오래 걸린다 — 창이 그만큼 준다.

    POSIX 에서는 결과도 성능도 사실상 같다.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    return json.loads(raw.decode("utf-8"))


def tmp_name(path):
    """원자 교체용 임시 파일 이름. 쓰는 주체마다 다른 이름을 쓴다.

    모두가 `<path>.tmp` 하나를 쓰면 동시 쓰기가 서로의 임시 파일을 덮는다.
    POSIX 는 그래도 대개 넘어가지만 Windows 는 상대의 핸들 때문에 교체 자체가
    거부된다 — 실측에서 쓰기 3개가 겹치자 600번 중 598번이 실패했다.
    """
    return "%s.tmp.%d.%d" % (path, os.getpid(), threading.get_ident())


def atomic_replace(tmp, path, attempts=400, delay=0.002):
    """tmp 를 path 로 원자 교체한다. 실패하면 짧게 기다렸다 다시 시도한다.

    POSIX 의 rename 은 대상을 누가 열고 있어도 성공한다. Windows 는 열린 핸들이
    하나라도 있으면 PermissionError 로 거부한다. 서버가 ThreadingHTTPServer 라
    읽기와 쓰기가 겹치는 것은 예외가 아니라 평시다 — 브라우저 탭 하나를 2초마다
    폴링시킨 것만으로 보드 저장 200번 중 3번이 실패했고, 탭이 늘면 16% 까지 갔다.

    POSIX 에서는 첫 시도에 성공하므로 루프가 한 바퀴 돌고 끝난다. 즉 여기서
    달라지는 것은 Windows 뿐이다.
    """
    for remaining in range(attempts - 1, -1, -1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if not remaining:
                raise
            time.sleep(delay)


def restrict_to_owner(path):
    """시크릿이 든 파일을 소유자만 읽을 수 있게 한다.

    POSIX 는 chmod 600 이 전부다. Windows 의 chmod 는 읽기 전용 비트만 건드리고
    권한에는 아무 영향이 없다 — 같은 머신의 다른 계정이 토큰을 그대로 읽는다.
    NTFS 는 ACL 이므로 icacls 로 상속을 끊고 현재 사용자만 남긴다. icacls 는
    Windows 기본 탑재라 런타임 의존성은 그대로 0 이다.

    chmod 실패는 그대로 올린다. 호출부마다 정책이 다르고(enroll 은 중단, server 는
    무시) 여기서 삼키면 그 구분이 사라진다. icacls 는 best-effort 다 — 실패하면
    상속 ACL 로 남을 뿐이라 고치기 전과 같다.

    **좁혔는지를 돌려준다.** 예전에는 아무것도 돌려주지 않아서, 호출부가 결과를
    알 방법이 없는데도 "남겼다" 고 출력했다. 시크릿이 든 파일이라 잠기지 않았는데
    잠갔다고 말하면 사용자가 확인할 이유를 잃는다. 삼키는 것은 그대로 두되(여기서
    올리면 enroll 이 멈춘다) 무슨 일이 있었는지는 말한다.

    POSIX 는 True — chmod 가 실패하면 예외로 올라가므로 여기 도달했으면 성공이다.
    """
    os.chmod(path, 0o600)
    if os.name != "nt":
        return True
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if not user:
        return False
    try:
        done = subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", user + ":F"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


# Windows 에는 fcntl 이 없다. 그동안 잠금을 그냥 포기했고, 그 결과 병렬 편집에서
# 갱신이 유실됐다 (테스트에서 12개 중 1개만 살아남았다). msvcrt 는 Windows 표준
# 모듈이라 이걸 쓰면 런타임 의존성은 여전히 0이다.
def _lock_exclusive(fh, timeout=30.0):
    if fcntl is not None:
        fcntl.flock(fh, fcntl.LOCK_EX)
        return
    if msvcrt is None:
        return
    # msvcrt 에는 쓸 만한 "기다리는 잠금"이 없다. LK_LOCK 은 1초 간격으로 10번만
    # 재시도하고 포기하므로 짧은 편집이 여러 개 겹치면 그냥 실패한다. 직접 돈다.
    deadline = time.monotonic() + timeout
    while True:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def _lock_release(fh):
    if fcntl is not None:
        fcntl.flock(fh, fcntl.LOCK_UN)
        return
    if msvcrt is None:
        return
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        # 이미 풀렸거나 핸들이 닫히는 중이다. 여기서 예외를 올리면 원래 작업의
        # 예외를 덮어써 원인을 잃는다.
        pass


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
    tmp = tmp_name(path)
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    atomic_replace(tmp, path)


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
            _lock_exclusive(handle)
            try:
                yield
            finally:
                _lock_release(handle)


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
                text=True, encoding="utf-8", errors="replace",
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
