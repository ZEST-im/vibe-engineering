#!/usr/bin/env python3
"""
vibe-harness-record-run.py — shared agent-run usage recorder (PHASE_PMF03)

Records one agent run into the project's runs.json (append-only). Agent-agnostic:
called by the Claude Code SessionEnd hook, or directly by a Codex/Gemini adapter.

Two input modes:
  1. --from-transcript <path>   parse a Claude Code transcript .jsonl, sum usage
  2. direct flags               --tokens / --input / --output / --cache-read / --cache-write

Resolution (shared):
  project  cwd → git root → projects.json kanban_dir match (longest match)
  task_id  the current in_progress task (this git user), else None
  commit   git rev-parse --short HEAD in cwd
  dedupe   skip if a run with the same (session_id, agent) already exists

Delivery: POST localhost:4242/api/{key}/runs if the server is up; otherwise append
to {kanban_dir}/runs.json directly (atomic) and sync the task's tokens_used. The
server is just a convenience wrapper — the JSON file is the source of record.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

try:
    import fcntl
except ImportError:
    # Windows has no fcntl. flock becomes a no-op - the atomic .tmp then
    # os.replace below is the real write guard, and this is a single-user
    # local file. A bare "import fcntl" here used to raise inside
    # append_direct(), which is the path taken whenever the localhost server
    # is down. The SessionEnd hook swallows stderr, so that crash recorded
    # nothing at all and said nothing: silent under-counting on every
    # Windows machine without a running server.
    class _FcntlShim:
        LOCK_EX = LOCK_UN = 0

        def flock(self, *args, **kwargs):
            pass

    fcntl = _FcntlShim()

CONFIG_PATH = os.path.expanduser("~/.claude/skills/vibe-harness/projects.json")
SERVER = "http://localhost:4242"


def _now():
    # KST-aware ISO (…+09:00). datetime.now(KST) is correct on any host, so runs
    # recorded from a UTC cloud runner don't land in the wrong day's bucket.
    #
    # Fixed offset, not ZoneInfo("Asia/Seoul"): Windows ships no system tz database,
    # so ZoneInfo raises ZoneInfoNotFoundError unless the tzdata package happens to
    # be installed. The SessionEnd hook swallows stderr and exits 0, which turned
    # that crash into silent under-counting. KST has no DST, so nothing is lost.
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def _git(args, cwd):
    try:
        return subprocess.check_output(["git"] + args, cwd=cwd,
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""


def _safe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def parse_transcript(path):
    """Sum token usage across assistant messages; return (totals, model)."""
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    model = ""
    if not path or not os.path.exists(path):
        return totals, model
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            m = o.get("message") if isinstance(o, dict) else None
            if not isinstance(m, dict):
                continue
            u = m.get("usage")
            if not isinstance(u, dict):
                continue
            totals["input"] += _safe_int(u.get("input_tokens"))
            totals["output"] += _safe_int(u.get("output_tokens"))
            totals["cache_read"] += _safe_int(u.get("cache_read_input_tokens"))
            totals["cache_write"] += _safe_int(u.get("cache_creation_input_tokens"))
            if m.get("model"):
                model = m["model"]
    return totals, model


def load_projects():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def resolve_project(cwd):
    """Return (key, kanban_dir) for the project containing cwd, or (None, None)."""
    cwd = os.path.abspath(cwd or os.getcwd())
    git_root = _git(["rev-parse", "--show-toplevel"], cwd) or cwd
    best = (None, None, -1)
    for key, info in load_projects().items():
        kdir = info.get("kanban_dir", "")
        base = os.path.dirname(os.path.abspath(kdir))  # project root
        if not base:
            continue
        for cand in (git_root, cwd):
            if cand == base or cand.startswith(base + os.sep):
                if len(base) > best[2]:
                    best = (key, kdir, len(base))
    return best[0], best[1]


def resolve_task_id(kanban_dir, git_user):
    """Current in_progress task for this user (else None)."""
    kp = os.path.join(kanban_dir, "kanban.json")
    if not os.path.exists(kp):
        return None
    try:
        data = json.load(open(kp, encoding="utf-8"))
    except Exception:
        return None
    in_prog = [t for t in data.get("tasks", []) if t.get("status") == "in_progress"]
    if git_user:
        owned = [t for t in in_prog
                 if git_user in (t.get("assigned_to"), t.get("created_by"))]
        if owned:
            owned.sort(key=lambda t: t.get("started_at") or "", reverse=True)
            return owned[0].get("id")
    if len(in_prog) == 1:
        return in_prog[0].get("id")
    return None


def already_recorded(kanban_dir, session_id, agent):
    if not session_id:
        return False
    rp = os.path.join(kanban_dir, "runs.json")
    if not os.path.exists(rp):
        return False
    try:
        runs = json.load(open(rp, encoding="utf-8")).get("runs", [])
    except Exception:
        return False
    return any(r.get("session_id") == session_id and r.get("agent") == agent for r in runs)


def append_direct(kanban_dir, run):
    """Append run to runs.json (atomic) and sync the task's tokens_used."""
    rp = os.path.join(kanban_dir, "runs.json")
    data = {"version": 1, "runs": []}
    if os.path.exists(rp):
        try:
            data = json.load(open(rp, encoding="utf-8"))
        except Exception:
            pass
    data.setdefault("runs", []).append(run)
    tmp = rp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush(); os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, rp)
    # sync task tokens_used = sum of its runs
    tid = run.get("task_id")
    if tid is not None:
        kp = os.path.join(kanban_dir, "kanban.json")
        if os.path.exists(kp):
            try:
                kd = json.load(open(kp, encoding="utf-8"))
            except Exception:
                return
            total = sum(_safe_int(r.get("tokens")) for r in data["runs"] if r.get("task_id") == tid)
            task = next((t for t in kd["tasks"] if t.get("id") == tid), None)
            if task is not None:
                task["tokens_used"] = total
                task["updated_at"] = _now()
                tmp = kp + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    json.dump(kd, f, indent=2, ensure_ascii=False)
                    f.flush(); os.fsync(f.fileno())
                    fcntl.flock(f, fcntl.LOCK_UN)
                os.replace(tmp, kp)


def post_server(key, run):
    """Try the running server first; return True on success."""
    try:
        req = urllib.request.Request(
            f"{SERVER}/api/{key}/runs", data=json.dumps(run).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status in (200, 201)
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--from-transcript", default="")
    ap.add_argument("--tokens", type=int, default=0)
    ap.add_argument("--input", type=int, default=0)
    ap.add_argument("--output", type=int, default=0)
    ap.add_argument("--cache-read", type=int, default=0)
    ap.add_argument("--cache-write", type=int, default=0)
    ap.add_argument("--time-seconds", type=int, default=0)
    ap.add_argument("--session-id", default="")
    ap.add_argument("--cwd", default="")
    ap.add_argument("--task-id", type=int, default=0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cwd = args.cwd or os.getcwd()

    breakdown = {"input": args.input, "output": args.output,
                 "cache_read": args.cache_read, "cache_write": args.cache_write}
    model = args.model
    if args.from_transcript:
        breakdown, tmodel = parse_transcript(args.from_transcript)
        model = model or tmodel
    tokens = args.tokens or (breakdown["input"] + breakdown["output"]
                             + breakdown["cache_read"] + breakdown["cache_write"])

    if tokens <= 0:
        if not args.quiet:
            print("vibe-harness: no tokens to record, skipping", file=sys.stderr)
        return 0

    key, kanban_dir = resolve_project(cwd)
    if not key:
        if not args.quiet:
            print(f"vibe-harness: no registered project for {cwd}, skipping", file=sys.stderr)
        return 0

    if already_recorded(kanban_dir, args.session_id, args.agent):
        if not args.quiet:
            print(f"vibe-harness: session {args.session_id} already recorded, skipping", file=sys.stderr)
        return 0

    git_user = _git(["config", "user.name"], cwd)
    task_id = args.task_id or resolve_task_id(kanban_dir, git_user)
    commit = _git(["rev-parse", "--short", "HEAD"], cwd)

    run = {
        "task_id": task_id,
        "agent": args.agent,
        "model": model,
        "tokens": tokens,
        "input_tokens": breakdown["input"] or None,
        "output_tokens": breakdown["output"] or None,
        "cache_read_tokens": breakdown["cache_read"] or None,
        "cache_write_tokens": breakdown["cache_write"] or None,
        "time_seconds": args.time_seconds or None,
        "commit": commit,
        "session_id": args.session_id,
        "ts": _now(),
    }

    via = "server" if post_server(key, run) else None
    if not via:
        append_direct(kanban_dir, run)
        via = "file"

    if not args.quiet:
        print(f"vibe-harness: recorded {args.agent} run ({tokens:,} tokens) "
              f"→ {key} task={task_id} via {via}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
