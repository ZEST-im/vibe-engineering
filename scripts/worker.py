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


def run_once(args):
    claim_payload = {"worker_id": args.worker_id, "agent": args.agent}
    if args.task_id is not None:
        claim_payload["task_id"] = args.task_id
    status, claim = request_json("POST", f"{args.server}/api/{args.project}/worker/claim", claim_payload)
    if status == 409:
        return False
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
    return True


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
    parser.add_argument("--command", nargs=argparse.REMAINDER, help="Explicit argv override after --command")
    args = parser.parse_args()
    args.server = args.server.rstrip("/")
    args.project_root = os.path.abspath(args.project_root)
    while True:
        worked = run_once(args)
        if args.once:
            return 0 if worked else 3
        if not worked:
            time.sleep(max(0.2, args.poll_seconds))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"worker error: {exc}", file=sys.stderr)
        raise SystemExit(1)
