#!/usr/bin/env python3
"""
VibeKanban Server v5 — JSON-based Multi-project Kanban Board
Git-friendly: stores tasks as JSON files instead of SQLite.
One server (localhost:4242) serves multiple projects with tab-based switching.
"""

import json
import os
import sys
import signal
import fcntl
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import subprocess

SKILL_DIR = os.path.expanduser("~/.claude/skills/vibekanban")
CONFIG_PATH = os.path.join(SKILL_DIR, "projects.json")

def _git_user():
    """Get git user.name, cached after first call."""
    if not hasattr(_git_user, "_cache"):
        try:
            _git_user._cache = subprocess.check_output(
                ["git", "config", "user.name"], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            _git_user._cache = ""
    return _git_user._cache

# ── Projects Registry ──────────────────────────────

def load_projects():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}

def save_projects(projects):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)

def register_project(key, name, kanban_dir):
    projects = load_projects()
    projects[key] = {"name": name, "kanban_dir": os.path.abspath(kanban_dir)}
    save_projects(projects)
    init_kanban(kanban_dir)
    return projects

# ── JSON Storage ───────────────────────────────────

def _now():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def _kanban_path(kanban_dir):
    return os.path.join(kanban_dir, "kanban.json")

def _archive_dir(kanban_dir):
    return os.path.join(kanban_dir, "archive")

def init_kanban(kanban_dir):
    os.makedirs(kanban_dir, exist_ok=True)
    kp = _kanban_path(kanban_dir)
    if not os.path.exists(kp):
        _write_kanban(kanban_dir, {"version": 1, "next_id": 1, "tasks": []})

def _read_kanban(kanban_dir):
    kp = _kanban_path(kanban_dir)
    if not os.path.exists(kp):
        return {"version": 1, "next_id": 1, "tasks": []}
    with open(kp) as f:
        data = json.load(f)
    if "next_id" not in data:
        max_id = max((t.get("id", 0) for t in data.get("tasks", [])), default=0)
        data["next_id"] = max_id + 1
    return data

def _write_kanban(kanban_dir, data):
    kp = _kanban_path(kanban_dir)
    os.makedirs(kanban_dir, exist_ok=True)
    tmp = kp + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, kp)

def _list_archives(kanban_dir):
    """Load all archived tasks."""
    adir = _archive_dir(kanban_dir)
    if not os.path.isdir(adir):
        return []
    tasks = []
    for fname in sorted(os.listdir(adir)):
        if fname.endswith(".json"):
            with open(os.path.join(adir, fname)) as f:
                data = json.load(f)
                tasks.extend(data.get("tasks", []))
    return tasks

def _archive_tasks(kanban_dir, tasks_to_archive):
    """Move done tasks to monthly archive files."""
    if not tasks_to_archive:
        return
    adir = _archive_dir(kanban_dir)
    os.makedirs(adir, exist_ok=True)
    # Group by month
    by_month = {}
    for t in tasks_to_archive:
        completed = t.get("completed_at") or t.get("updated_at") or _now()
        month = completed[:7]  # YYYY-MM
        by_month.setdefault(month, []).append(t)
    for month, month_tasks in by_month.items():
        fpath = os.path.join(adir, f"{month}.json")
        existing = {"tasks": []}
        if os.path.exists(fpath):
            with open(fpath) as f:
                existing = json.load(f)
        existing_ids = {t["id"] for t in existing["tasks"]}
        for t in month_tasks:
            if t["id"] not in existing_ids:
                existing["tasks"].append(t)
        with open(fpath, "w") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

def _new_task(data, fields):
    """Create a new task, return (updated_data, new_task)."""
    now = _now()
    tid = data.get("next_id", 1)
    task = {
        "id": tid,
        "title": fields.get("title", ""),
        "description": fields.get("description", ""),
        "details": fields.get("details", ""),
        "status": fields.get("status", "backlog"),
        "priority": fields.get("priority", "medium"),
        "category": fields.get("category", ""),
        "target_date": fields.get("target_date", ""),
        "started_at": fields.get("started_at", ""),
        "completed_at": fields.get("completed_at", ""),
        "lines_added": fields.get("lines_added", 0),
        "lines_removed": fields.get("lines_removed", 0),
        "created_at": now,
        "updated_at": now,
        "position": fields.get("position", 0),
        "phase": fields.get("phase", ""),
        "review": fields.get("review", ""),
        "created_by": fields.get("created_by", "") or _git_user(),
        "assigned_to": fields.get("assigned_to", ""),
    }
    data["tasks"].append(task)
    data["next_id"] = tid + 1
    return data, task

TASK_FIELDS = ("title", "description", "details", "status", "priority", "category",
               "target_date", "started_at", "completed_at", "lines_added", "lines_removed",
               "position", "phase", "review", "created_by", "assigned_to")

def _update_task(task, fields):
    """Update task fields in place."""
    now = _now()
    for k in TASK_FIELDS:
        if k in fields:
            task[k] = fields[k]
    # Auto-set timestamps and user
    if "status" in fields:
        if fields["status"] == "in_progress":
            if not task.get("started_at"):
                task["started_at"] = now
            if not task.get("assigned_to"):
                task["assigned_to"] = _git_user()
        if fields["status"] == "done" and "completed_at" not in fields:
            task["completed_at"] = now
    task["updated_at"] = now
    return task

# ── Handler ─────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def _resolve_project(self, parts):
        if len(parts) < 1:
            return None, None, parts
        projects = load_projects()
        key = parts[0]
        if key in projects:
            return key, projects[key]["kanban_dir"], parts[1:]
        return None, None, parts

    def do_OPTIONS(self):
        self.send_response(200)
        for h, v in [("Access-Control-Allow-Origin", "*"),
                      ("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS"),
                      ("Access-Control-Allow-Headers", "Content-Type")]:
            self.send_header(h, v)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        p = parsed.path.rstrip("/")

        # ── UI ──
        if p in ("", "/kanban"):
            html_path = os.path.join(os.path.dirname(__file__), "kanban.html")
            with open(html_path, encoding="utf-8") as f:
                return self._html(f.read())

        # ── API: projects list ──
        if p == "/api/projects":
            projects = load_projects()
            result = []
            for key, info in projects.items():
                exists = os.path.exists(_kanban_path(info["kanban_dir"]))
                result.append({"key": key, "name": info["name"], "kanban_dir": info["kanban_dir"], "exists": exists})
            return self._json(result)

        # ── API: /api/{project}/... ──
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, kanban_dir, rest = self._resolve_project(parts)
            if not pkey or not kanban_dir:
                return self._json({"error": "unknown project"}, 404)

            if rest == ["tasks"] or rest == []:
                # Return active + archived tasks
                data = _read_kanban(kanban_dir)
                all_tasks = data["tasks"] + _list_archives(kanban_dir)
                all_tasks.sort(key=lambda t: (t.get("position", 0), t.get("id", 0)))
                return self._json(all_tasks)

            if rest == ["export"]:
                data = _read_kanban(kanban_dir)
                all_tasks = data["tasks"] + _list_archives(kanban_dir)
                return self._json({
                    "version": 1,
                    "project": pkey,
                    "exported_at": _now(),
                    "tasks": all_tasks
                })

            if rest == ["stats"]:
                data = _read_kanban(kanban_dir)
                all_tasks = data["tasks"] + _list_archives(kanban_dir)
                stats = {}
                for s in ["backlog", "todo", "in_progress", "review", "done"]:
                    stats[s] = sum(1 for t in all_tasks if t.get("status") == s)
                stats["total"] = len(all_tasks)
                return self._json(stats)

            if rest == ["archive"]:
                data = _read_kanban(kanban_dir)
                done_tasks = [t for t in data["tasks"] if t.get("status") == "done"]
                if not done_tasks:
                    return self._json({"archived": 0, "message": "no done tasks to archive"})
                _archive_tasks(kanban_dir, done_tasks)
                data["tasks"] = [t for t in data["tasks"] if t.get("status") != "done"]
                _write_kanban(kanban_dir, data)
                return self._json({"archived": len(done_tasks)})

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path.rstrip("/")

        # ── Register project ──
        if p == "/api/projects":
            d = self._body()
            key = d.get("key", "")
            name = d.get("name", key)
            kanban_dir = d.get("kanban_dir", d.get("db_path", ""))
            # Backward compat: if db_path given, convert to kanban_dir
            if kanban_dir.endswith(".db") or kanban_dir.endswith("/kanban.db"):
                kanban_dir = os.path.dirname(kanban_dir)
            if not key or not kanban_dir:
                return self._json({"error": "key and kanban_dir required"}, 400)
            projects = register_project(key, name, kanban_dir)
            return self._json({"registered": key, "total": len(projects)}, 201)

        # ── API: /api/{project}/... ──
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, kanban_dir, rest = self._resolve_project(parts)
            if not pkey:
                return self._json({"error": "unknown project"}, 404)

            if rest == ["tasks"]:
                d = self._body()
                data = _read_kanban(kanban_dir)
                data, task = _new_task(data, d)
                _write_kanban(kanban_dir, data)
                return self._json(task, 201)

            if rest == ["import"]:
                d = self._body()
                imp_tasks = d.get("tasks", [])
                mode = d.get("mode", "merge")
                data = _read_kanban(kanban_dir)

                if mode == "replace":
                    data["tasks"] = []
                    data["next_id"] = 1

                imported, skipped, updated = 0, 0, 0
                existing_by_id = {t["id"]: t for t in data["tasks"]}

                for t in imp_tasks:
                    orig_id = t.get("id")
                    if mode == "merge" and orig_id and orig_id in existing_by_id:
                        existing = existing_by_id[orig_id]
                        if t.get("updated_at", "") > (existing.get("updated_at") or ""):
                            _update_task(existing, t)
                            updated += 1
                        else:
                            skipped += 1
                        continue
                    data, _ = _new_task(data, t)
                    imported += 1

                _write_kanban(kanban_dir, data)
                return self._json({"imported": imported, "updated": updated, "skipped": skipped, "mode": mode})

            if rest == ["tasks", "bulk"]:
                d = self._body()
                data = _read_kanban(kanban_dir)
                ids = []
                for item in d.get("tasks", []):
                    data, task = _new_task(data, item)
                    ids.append(task["id"])
                _write_kanban(kanban_dir, data)
                return self._json({"created": len(ids), "ids": ids}, 201)

            if rest == ["archive"]:
                # POST to archive = archive done tasks
                data = _read_kanban(kanban_dir)
                done_tasks = [t for t in data["tasks"] if t.get("status") == "done"]
                if not done_tasks:
                    return self._json({"archived": 0, "message": "no done tasks to archive"})
                _archive_tasks(kanban_dir, done_tasks)
                data["tasks"] = [t for t in data["tasks"] if t.get("status") != "done"]
                _write_kanban(kanban_dir, data)
                return self._json({"archived": len(done_tasks)})

        self.send_response(404)
        self.end_headers()

    def do_PUT(self):
        p = urlparse(self.path).path.rstrip("/")
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, kanban_dir, rest = self._resolve_project(parts)
            if not pkey:
                return self._json({"error": "unknown project"}, 404)

            # /api/{project}/tasks/{id}
            if len(rest) == 2 and rest[0] == "tasks":
                tid = int(rest[1])
                d = self._body()
                data = _read_kanban(kanban_dir)
                task = next((t for t in data["tasks"] if t["id"] == tid), None)
                if not task:
                    return self._json({"error": "not found"}, 404)
                _update_task(task, d)
                _write_kanban(kanban_dir, data)
                return self._json(task)

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        p = urlparse(self.path).path.rstrip("/")
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, kanban_dir, rest = self._resolve_project(parts)
            if not pkey:
                return self._json({"error": "unknown project"}, 404)

            if len(rest) == 2 and rest[0] == "tasks":
                tid = int(rest[1])
                data = _read_kanban(kanban_dir)
                data["tasks"] = [t for t in data["tasks"] if t["id"] != tid]
                _write_kanban(kanban_dir, data)
                return self._json({"deleted": tid})

        self.send_response(404)
        self.end_headers()


# ── Main ────────────────────────────────────────────

def main():
    port = 4242

    if len(sys.argv) > 1 and sys.argv[1] == "register":
        key = sys.argv[2]
        name = sys.argv[3] if len(sys.argv) > 3 else key
        kanban_dir = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.getcwd(), "vibekanban")
        projects = register_project(key, name, kanban_dir)
        print(f"Registered: {key} → {kanban_dir}")
        print(f"Total projects: {len(projects)}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 4242
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        # Legacy mode: server.py <path> <port> <name>
        path_arg = sys.argv[1]
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 4242
        name = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(os.path.dirname(os.path.dirname(path_arg)))
        key = name.replace(".", "_").replace(" ", "_").replace("-", "_").lower()
        # Convert old db_path to kanban_dir
        kanban_dir = os.path.dirname(path_arg) if path_arg.endswith(".db") else path_arg
        register_project(key, name, kanban_dir)
        print(f"Auto-registered: {key} ({name})")

    # Init all registered projects
    projects = load_projects()
    for key, info in projects.items():
        kdir = info.get("kanban_dir", "")
        # Backward compat: convert old db_path
        if not kdir and "db_path" in info:
            kdir = os.path.dirname(info["db_path"])
        if kdir and os.path.exists(os.path.dirname(kdir)):
            init_kanban(kdir)

    server = HTTPServer(("127.0.0.1", port), Handler)

    def shutdown(sig, frame):
        server.shutdown()
        sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"VibeKanban v5 — http://localhost:{port}/kanban")
    print(f"  Projects: {', '.join(projects.keys()) if projects else '(none)'}")
    print(f"  Storage: JSON (git-friendly)")
    print(f"  Ctrl+C to stop")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
