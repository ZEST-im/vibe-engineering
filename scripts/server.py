#!/usr/bin/env python3
"""
VibeKanban Server v3 — Multi-project Kanban Board
하나의 서버(localhost:4242)에서 여러 프로젝트 칸반을 탭으로 전환
"""

import sqlite3
import json
import os
import sys
import signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

CONFIG_PATH = os.path.expanduser("~/.claude/kanban/projects.json")

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

def register_project(key, name, db_path):
    projects = load_projects()
    projects[key] = {"name": name, "db_path": os.path.abspath(db_path)}
    save_projects(projects)
    init_db(db_path)
    return projects

# ── DB ──────────────────────────────────────────────

def init_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            details TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'backlog',
            priority TEXT DEFAULT 'medium',
            category TEXT DEFAULT '',
            target_date TEXT DEFAULT '',
            started_at TEXT DEFAULT '',
            completed_at TEXT DEFAULT '',
            lines_added INTEGER DEFAULT 0,
            lines_removed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            position INTEGER DEFAULT 0
        )
    """)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    migrations = {
        "details": "TEXT DEFAULT ''",
        "target_date": "TEXT DEFAULT ''",
        "started_at": "TEXT DEFAULT ''",
        "completed_at": "TEXT DEFAULT ''",
        "lines_added": "INTEGER DEFAULT 0",
        "lines_removed": "INTEGER DEFAULT 0",
        "phase": "TEXT DEFAULT ''",
        "review": "TEXT DEFAULT ''",
    }
    for col, typedef in migrations.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typedef}")
    if "date_label" in existing:
        conn.execute("UPDATE tasks SET target_date = date_label WHERE target_date = '' AND date_label != ''")
    conn.commit()
    conn.close()

def get_conn(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c

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
        """parts = path segments after /api/. Returns (project_key, db_path, remaining_parts)"""
        if len(parts) < 1:
            return None, None, parts
        projects = load_projects()
        key = parts[0]
        if key in projects:
            return key, projects[key]["db_path"], parts[1:]
        return None, None, parts

    def do_OPTIONS(self):
        self.send_response(200)
        for h, v in [("Access-Control-Allow-Origin","*"),
                      ("Access-Control-Allow-Methods","GET,POST,PUT,DELETE,OPTIONS"),
                      ("Access-Control-Allow-Headers","Content-Type")]:
            self.send_header(h, v)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        p = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

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
                exists = os.path.exists(info["db_path"])
                result.append({"key": key, "name": info["name"], "db_path": info["db_path"], "exists": exists})
            return self._json(result)

        # ── API: /api/{project}/tasks ──
        if p.startswith("/api/"):
            parts = p[5:].split("/")  # strip "/api/"
            pkey, db_path, rest = self._resolve_project(parts)
            if not pkey or not db_path:
                return self._json({"error": "unknown project"}, 404)

            if rest == ["tasks"] or rest == []:
                if not os.path.exists(db_path):
                    return self._json([])
                c = get_conn(db_path)
                rows = c.execute("SELECT * FROM tasks ORDER BY position, id").fetchall()
                c.close()
                return self._json([dict(r) for r in rows])

            if rest == ["stats"]:
                if not os.path.exists(db_path):
                    return self._json({"total": 0})
                c = get_conn(db_path)
                stats = {}
                for s in ["backlog","todo","in_progress","review","done"]:
                    stats[s] = c.execute("SELECT COUNT(*) FROM tasks WHERE status=?", (s,)).fetchone()[0]
                stats["total"] = sum(stats.values())
                c.close()
                return self._json(stats)

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path.rstrip("/")

        # ── Register project ──
        if p == "/api/projects":
            d = self._body()
            key = d.get("key", "")
            name = d.get("name", key)
            db_path = d.get("db_path", "")
            if not key or not db_path:
                return self._json({"error": "key and db_path required"}, 400)
            projects = register_project(key, name, db_path)
            return self._json({"registered": key, "total": len(projects)}, 201)

        # ── API: /api/{project}/tasks ──
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, db_path, rest = self._resolve_project(parts)
            if not pkey:
                return self._json({"error": "unknown project"}, 404)

            if rest == ["tasks"]:
                d = self._body()
                c = get_conn(db_path)
                cols = "title,description,details,status,priority,category,target_date,started_at,completed_at,lines_added,lines_removed,position,phase,review"
                cur = c.execute(
                    f"INSERT INTO tasks ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d.get("title",""), d.get("description",""), d.get("details",""),
                     d.get("status","backlog"), d.get("priority","medium"), d.get("category",""),
                     d.get("target_date",""), d.get("started_at",""), d.get("completed_at",""),
                     d.get("lines_added",0), d.get("lines_removed",0), d.get("position",0),
                     d.get("phase",""), d.get("review","")))
                c.commit()
                t = dict(c.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone())
                c.close()
                return self._json(t, 201)

            if rest == ["tasks", "bulk"]:
                d = self._body()
                c = get_conn(db_path)
                ids = []
                for item in d.get("tasks", []):
                    cols = "title,description,details,status,priority,category,target_date,started_at,completed_at,lines_added,lines_removed,position,phase,review"
                    cur = c.execute(
                        f"INSERT INTO tasks ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (item.get("title",""), item.get("description",""), item.get("details",""),
                         item.get("status","backlog"), item.get("priority","medium"), item.get("category",""),
                         item.get("target_date",""), item.get("started_at",""), item.get("completed_at",""),
                         item.get("lines_added",0), item.get("lines_removed",0), item.get("position",0),
                         item.get("phase",""), item.get("review","")))
                    ids.append(cur.lastrowid)
                c.commit()
                c.close()
                return self._json({"created": len(ids), "ids": ids}, 201)

        self.send_response(404)
        self.end_headers()

    def do_PUT(self):
        p = urlparse(self.path).path.rstrip("/")
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, db_path, rest = self._resolve_project(parts)
            if not pkey:
                return self._json({"error": "unknown project"}, 404)

            # /api/{project}/tasks/{id}
            if len(rest) == 2 and rest[0] == "tasks":
                tid = rest[1]
                d = self._body()
                c = get_conn(db_path)
                allowed = ("title","description","details","status","priority","category",
                           "target_date","started_at","completed_at","lines_added","lines_removed","position","phase","review")
                sets, vals = [], []
                for k in allowed:
                    if k in d:
                        sets.append(f"{k}=?")
                        vals.append(d[k])
                if "status" in d:
                    if d["status"] == "in_progress" and "started_at" not in d:
                        sets.append("started_at=CASE WHEN started_at='' THEN datetime('now','localtime') ELSE started_at END")
                    if d["status"] == "done" and "completed_at" not in d:
                        sets.append("completed_at=datetime('now','localtime')")
                if sets:
                    sets.append("updated_at=datetime('now','localtime')")
                    vals.append(tid)
                    c.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", vals)
                    c.commit()
                t = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
                c.close()
                return self._json(dict(t)) if t else self._json({"error":"not found"}, 404)

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        p = urlparse(self.path).path.rstrip("/")
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, db_path, rest = self._resolve_project(parts)
            if not pkey:
                return self._json({"error": "unknown project"}, 404)

            if len(rest) == 2 and rest[0] == "tasks":
                tid = rest[1]
                c = get_conn(db_path)
                c.execute("DELETE FROM tasks WHERE id=?", (tid,))
                c.commit()
                c.close()
                return self._json({"deleted": tid})

        self.send_response(404)
        self.end_headers()


# (HTML is served from kanban.html in the same directory)

# ── Main ────────────────────────────────────────────

def main():
    port = 4242

    # Usage: server.py register <key> <name> <db_path>
    # Usage: server.py serve [port]
    # Usage: server.py (legacy: server.py <db_path> <port> <name>)

    if len(sys.argv) > 1 and sys.argv[1] == "register":
        key = sys.argv[2]
        name = sys.argv[3] if len(sys.argv) > 3 else key
        db_path = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.getcwd(), "vibekanban", "kanban.db")
        projects = register_project(key, name, db_path)
        print(f"Registered: {key} → {db_path}")
        print(f"Total projects: {len(projects)}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 4242
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        # Legacy mode: server.py <db_path> <port> <name>
        db_path = sys.argv[1]
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 4242
        name = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(os.path.dirname(os.path.dirname(db_path)))
        key = name.replace(".", "_").replace(" ", "_").replace("-", "_").lower()
        register_project(key, name, db_path)
        print(f"Auto-registered: {key} ({name})")

    # Init all registered project DBs
    projects = load_projects()
    for key, info in projects.items():
        if os.path.exists(os.path.dirname(info["db_path"])):
            init_db(info["db_path"])

    server = HTTPServer(("127.0.0.1", port), Handler)

    def shutdown(sig, frame):
        server.shutdown()
        sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"VibeKanban v3 — http://localhost:{port}/kanban")
    print(f"  Projects: {', '.join(projects.keys()) if projects else '(none)'}")
    print(f"  Ctrl+C to stop")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
