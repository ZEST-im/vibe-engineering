#!/usr/bin/env python3
"""Local polling Worker for the Vibe Engineering execution protocol."""

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import time
from urllib import error as urllib_error
from urllib import request as urllib_request


def request_json(method, url, payload=None, timeout=30):
    raw = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib_request.Request(
        url,
        data=raw,
        method=method,
        headers={"Content-Type": "application/json", "User-Agent": "Vibe-Engineering-Worker/1"},
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = {"error": str(exc)}
        return exc.code, body


def git_output(cwd, *args):
    try:
        return subprocess.check_output(["git", "-C", cwd, *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def create_worktree(project_root, project, task_id, run_id):
    if not git_output(project_root, "rev-parse", "--show-toplevel"):
        raise RuntimeError("registered project is not a Git repository")
    branch = f"vibe/task-{task_id}-{run_id[-8:]}"
    root = os.path.expanduser(os.environ.get("VIBE_HARNESS_WORKTREE_ROOT", "~/.vibe-harness/worktrees"))
    path = os.path.join(root, project, run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    completed = subprocess.run(
        ["git", "-C", project_root, "worktree", "add", "-b", branch, path, "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError("git worktree add failed: " + (completed.stdout or "").strip())
    return path, branch


def build_prompt(claim):
    task = claim.get("task", {})
    context = claim.get("context", {})
    checklist = context.get("checklist", {}).get("items", [])
    return "\n".join([
        "You are a Vibe Engineering managed worker.",
        f"Task #{task.get('id')}: {task.get('title', '')}",
        f"Description: {task.get('description', '')}",
        f"Details: {task.get('details', '')}",
        f"Phase: {context.get('phase', '')}",
        f"Scope: {context.get('scope', '')}",
        "Do not touch: " + "; ".join(context.get("do_not_touch", [])),
        "Phase checklist: " + "; ".join(item.get("text", "") for item in checklist if not item.get("done")),
        "Implement only this task. Do not mark it done; the Harness test gate controls completion.",
    ])


def adapter_argv(claim, override, prompt, worktree):
    raw = override or (claim.get("adapter") or {}).get("argv") or []
    if not raw:
        raise RuntimeError("no adapter argv configured for this agent")
    values = {
        "prompt": prompt,
        "run_id": claim["run_id"],
        "task_id": str(claim.get("task", {}).get("id", "")),
        "worktree": worktree,
    }
    return [str(part).format(**values) for part in raw]


def heartbeat_loop(base, project, credentials, interval, stop):
    while not stop.wait(max(1, interval)):
        status, body = request_json("POST", f"{base}/api/{project}/worker/heartbeat", credentials)
        if status != 200:
            print(f"heartbeat failed ({status}): {body.get('error', body)}", file=sys.stderr)
            return


# 루프가 구별해야 하는 세 가지. 지금까지는 True/False 뿐이라 "할 일이 없다"와
# "서버가 안 받는다"가 같은 값이었다 — 놀고 있는 워커와 고장난 워커가 구별되지 않았다.
WORKED = "worked"
IDLE = "idle"
ERROR = "error"


def run_once(args):
    claim_payload = {"worker_id": args.worker_id, "agent": args.agent}
    if args.task_id is not None:
        claim_payload["task_id"] = args.task_id
    status, claim = request_json("POST", f"{args.server}/api/{args.project}/worker/claim", claim_payload)
    if status == 409:
        return IDLE
    if status != 201:
        raise RuntimeError(f"claim failed ({status}): {claim.get('error', claim)}")
    credentials = {key: claim[key] for key in ("run_id", "lease_id", "lease_token")}
    started = time.time()
    try:
        worktree, branch = create_worktree(args.project_root, args.project, claim["task"]["id"], claim["run_id"])
        prompt = build_prompt(claim)
        argv = adapter_argv(claim, args.command, prompt, worktree)
    except Exception as exc:
        payload = dict(credentials, failure_reason=str(exc), agent=args.agent)
        request_json("POST", f"{args.server}/api/{args.project}/worker/fail", payload)
        raise

    print(f"claimed task #{claim['task']['id']} → {claim['run_id']}")
    print(f"worktree: {worktree}")
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=heartbeat_loop,
        args=(args.server, args.project, credentials, int(claim.get("heartbeat_seconds", 30)), stop),
        daemon=True,
    )
    heartbeat.start()
    completed = subprocess.run(argv, cwd=worktree)
    stop.set()
    heartbeat.join(timeout=2)
    payload = dict(
        credentials,
        agent=args.agent,
        time_seconds=round(time.time() - started, 3),
        worktree_path=worktree,
        branch=branch,
        commit=git_output(worktree, "rev-parse", "HEAD"),
        changes={
            "status": git_output(worktree, "status", "--short")[-12000:],
            "numstat": git_output(worktree, "diff", "--numstat")[-12000:],
        },
    )
    endpoint = "complete" if completed.returncode == 0 else "fail"
    if completed.returncode != 0:
        payload["failure_reason"] = f"agent_exit_{completed.returncode}"
    status, result = request_json("POST", f"{args.server}/api/{args.project}/worker/{endpoint}", payload, timeout=3600)
    if status != 200:
        raise RuntimeError(f"finish failed ({status}): {result.get('error', result)}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return WORKED


def main():
    parser = argparse.ArgumentParser(description="Run a local Vibe Engineering Worker")
    parser.add_argument("project")
    parser.add_argument("--server", default="http://127.0.0.1:4242")
    parser.add_argument("--agent", default="codex")
    parser.add_argument("--worker-id", default=f"{platform.node()}-{os.getpid()}")
    parser.add_argument("--project-root", default=os.getcwd())
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-consecutive-errors", type=int, default=5,
                        help="연속 오류가 이 횟수를 넘으면 이유와 함께 중단한다")
    parser.add_argument("--max-backoff-seconds", type=float, default=300,
                        help="지수 백오프 상한")
    parser.add_argument("--max-idle-seconds", type=float, default=0,
                        help="이 시간 동안 할 일이 없으면 정상 종료한다 (0=무제한)")
    parser.add_argument("--command", nargs=argparse.REMAINDER, help="Explicit argv override after --command")
    args = parser.parse_args()
    args.server = args.server.rstrip("/")
    args.project_root = os.path.abspath(args.project_root)
    return run_loop(args)


def run_loop(args, runner=run_once, sleeper=time.sleep, now=time.monotonic):
    """폴링 루프.

    세 가지를 명시한다 — 언제 다시 돌고, 언제 멈추고, 무엇을 근거로 정하는가.

    - **일시적 오류로 죽지 않는다.** 예전에는 claim 이 500 을 한 번만 내도 예외가
      최상위까지 올라가 워커가 영영 끝났다. 이제 지수 백오프로 물러섰다가 다시 온다.
    - **영원히 조용히 돌지 않는다.** 오류가 연속으로 한도를 넘으면 **이유와 함께**
      비정상 종료한다. 계속 도는 워커와 아무것도 못 하는 워커가 같아 보이면 안 된다.
    - **놀고 있는 것과 고장난 것을 나눈다.** IDLE 은 정상이므로 오류 카운터를 되돌린다.
    """
    consecutive = 0
    idle_since = None
    last_state = None
    while True:
        try:
            outcome = runner(args)
        except Exception as exc:                      # noqa: BLE001 - 루프는 살아남아야 한다
            outcome = ERROR
            reason = str(exc)
        else:
            reason = None

        if args.once:
            if outcome == WORKED:
                return 0
            if outcome == ERROR:
                print(f"worker error: {reason}", file=sys.stderr)
                return 1
            return 3

        if outcome == WORKED:
            consecutive, idle_since = 0, None
            if last_state != WORKED:
                print("worker: 작업 처리 중")
            last_state = WORKED
            continue

        if outcome == ERROR:
            consecutive += 1
            idle_since = None
            delay = min(args.poll_seconds * (2 ** (consecutive - 1)), args.max_backoff_seconds)
            print(f"worker: 오류 {consecutive}/{args.max_consecutive_errors} "
                  f"— {delay:.0f}초 뒤 재시도: {reason}", file=sys.stderr)
            if consecutive >= args.max_consecutive_errors:
                print(f"worker: 오류가 {consecutive}회 연속 — 중단한다. 마지막 이유: {reason}",
                      file=sys.stderr)
                return 1
            last_state = ERROR
            sleeper(delay)
            continue

        # IDLE — 정상이다. 오류 카운터를 되돌린다.
        consecutive = 0
        if idle_since is None:
            idle_since = now()
            if last_state != IDLE:
                print("worker: 할 일 없음 — 대기")
        elif args.max_idle_seconds and (now() - idle_since) >= args.max_idle_seconds:
            print(f"worker: {args.max_idle_seconds:.0f}초 동안 할 일이 없어 종료한다")
            return 0
        last_state = IDLE
        sleeper(max(0.2, args.poll_seconds))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"worker error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
