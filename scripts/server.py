#!/usr/bin/env python3
"""
Vibe Harness Server v5 — JSON-based Multi-project Kanban Board
Git-friendly: stores tasks as JSON files instead of SQLite.
One server (localhost:4242) serves multiple projects with tab-based switching.
"""

import json
import os
import sys
import signal
import fcntl
import re
import glob as glob_module
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import subprocess

SKILL_DIR = os.path.expanduser("~/.claude/skills/vibe-harness")
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
        "tokens_used": fields.get("tokens_used", 0),
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
               "tokens_used", "position", "phase", "review", "created_by", "assigned_to")

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

# ── Schema Parsing ─────────────────────────────────

def _find_schema_files(kanban_dir):
    """Find schema definition files in the project directory."""
    project_dir = os.path.dirname(os.path.abspath(kanban_dir))
    files = []
    base_patterns = [
        "db/schema.rb", "db/*_schema.rb", "db/structure.sql", "prisma/schema.prisma",
        "schema.prisma", "db/migrations/*.sql", "db/migrate/*.rb",
        "migrations/*.sql", "schema.sql", "sql/*.sql",
    ]
    # Search at project root and one level deeper (e.g., rails_app/db/schema.rb)
    for depth_prefix in ["", "*/", "*/*/"]:
        for pattern in base_patterns:
            for f in sorted(glob_module.glob(os.path.join(project_dir, depth_prefix + pattern))):
                if os.path.isfile(f) and f not in files:
                    files.append(f)
    return files, project_dir

def _split_ddl(body):
    """Split DDL body by commas, respecting parentheses."""
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == '(':
            depth += 1; cur.append(ch)
        elif ch == ')':
            depth -= 1; cur.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(cur)); cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append(''.join(cur))
    return parts

def _parse_column(s):
    """Parse a single SQL column definition."""
    s = s.strip()
    if not s:
        return None
    upper = s.upper().lstrip()
    if any(upper.startswith(kw) for kw in ('CONSTRAINT', 'PRIMARY', 'FOREIGN', 'UNIQUE', 'CHECK', 'EXCLUDE', 'LIKE ')):
        return None
    name_m = re.match(r'"?(\w+)"?\s+', s)
    if not name_m:
        return None
    name = name_m.group(1)
    rest = s[name_m.end():]
    # Extract type: everything until a constraint keyword
    ckw = r'\b(?:NOT\s+NULL|NULL|DEFAULT|PRIMARY\s+KEY|UNIQUE|REFERENCES|CHECK|CONSTRAINT|GENERATED|COLLATE)\b'
    type_end = re.search(ckw, rest, re.IGNORECASE)
    if type_end:
        col_type = rest[:type_end.start()].strip()
        cpart = rest[type_end.start():]
    else:
        col_type = rest.strip()
        cpart = ''
    col_type = col_type.rstrip(',').strip()
    col = {'name': name, 'type': col_type.upper() if col_type else '', 'pk': False,
           'fk': None, 'nullable': True, 'unique': False, 'default': None}
    cu = cpart.upper()
    if 'PRIMARY KEY' in cu:
        col['pk'] = True; col['nullable'] = False
    if 'NOT NULL' in cu:
        col['nullable'] = False
    if re.search(r'\bUNIQUE\b', cu):
        col['unique'] = True
    def_m = re.search(r"DEFAULT\s+('(?:[^'\\]|\\.)*'|\S+(?:\([^)]*\))?)", cpart, re.IGNORECASE)
    if def_m:
        col['default'] = def_m.group(1)
    ref_m = re.search(r'REFERENCES\s+"?(\w+)"?\s*\("?([^)"]+)"?\)', cpart, re.IGNORECASE)
    if ref_m:
        col['fk'] = f"{ref_m.group(1)}({ref_m.group(2).strip()})"
        col['_inline_ref'] = (ref_m.group(1), ref_m.group(2).strip())
    if col['type'] in ('SERIAL', 'BIGSERIAL', 'SMALLSERIAL'):
        col['nullable'] = False
    return col

def _parse_sql_schema(content):
    """Parse SQL DDL into structured schema."""
    tables, relationships = {}, []
    content = re.sub(r'--[^\n]*', '', content)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    # CREATE TABLE
    for m in re.finditer(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:"?(\w+)"?\.)?\"?(\w+)\"?\s*\((.*?)\)\s*;',
        content, re.DOTALL | re.IGNORECASE
    ):
        schema_name, table_name, body = m.group(1) or '', m.group(2), m.group(3)
        columns, constraints = [], []
        for part in _split_ddl(body):
            part = part.strip()
            if not part:
                continue
            up = part.upper().lstrip()
            if any(up.startswith(kw) for kw in ('CONSTRAINT', 'PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE(', 'UNIQUE (', 'CHECK', 'EXCLUDE')):
                constraints.append(part)
            else:
                col = _parse_column(part)
                if col:
                    columns.append(col)
        indexes = []
        for tc in constraints:
            pk_m = re.search(r'PRIMARY\s+KEY\s*\(([^)]+)\)', tc, re.IGNORECASE)
            if pk_m:
                for cn in [c.strip().strip('"') for c in pk_m.group(1).split(',')]:
                    for col in columns:
                        if col['name'] == cn:
                            col['pk'] = True; col['nullable'] = False
            fk_m = re.search(r'FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+"?(?:\w+\.)?"?(\w+)"?\s*\(([^)]+)\)', tc, re.IGNORECASE)
            if fk_m:
                fk_cols = [c.strip().strip('"') for c in fk_m.group(1).split(',')]
                ref_table = fk_m.group(2)
                ref_cols = [c.strip().strip('"') for c in fk_m.group(3).split(',')]
                for i, fc in enumerate(fk_cols):
                    rc = ref_cols[i] if i < len(ref_cols) else ref_cols[0]
                    for col in columns:
                        if col['name'] == fc:
                            col['fk'] = f"{ref_table}({rc})"
                    relationships.append({'from_table': table_name, 'from_column': fc, 'to_table': ref_table, 'to_column': rc})
            uq_m = re.search(r'UNIQUE\s*\(([^)]+)\)', tc, re.IGNORECASE)
            if uq_m:
                uq_cols = [c.strip().strip('"') for c in uq_m.group(1).split(',')]
                if len(uq_cols) == 1:
                    for col in columns:
                        if col['name'] == uq_cols[0]:
                            col['unique'] = True
                else:
                    nm = re.search(r'CONSTRAINT\s+"?(\w+)"?', tc, re.IGNORECASE)
                    indexes.append({'name': nm.group(1) if nm else f"uq_{'_'.join(uq_cols)}", 'columns': uq_cols, 'unique': True})
        # Collect inline REFERENCES as relationships
        for col in columns:
            iref = col.pop('_inline_ref', None)
            if iref:
                relationships.append({'from_table': table_name, 'from_column': col['name'], 'to_table': iref[0], 'to_column': iref[1]})
        tables[table_name] = {'name': table_name, 'schema': schema_name, 'columns': columns, 'indexes': indexes}
    # CREATE INDEX
    for m in re.finditer(
        r'CREATE\s+(UNIQUE\s+)?INDEX\s+(?:(?:IF\s+NOT\s+EXISTS|CONCURRENTLY)\s+)?\"?(\w+)\"?\s+ON\s+\"?(?:\w+\.)?(\w+)\"?\s*(?:USING\s+\w+\s*)?\(([^)]+)\)',
        content, re.IGNORECASE
    ):
        is_uq, idx_name, tname = bool(m.group(1)), m.group(2), m.group(3)
        idx_cols = [c.strip().strip('"').split()[0] for c in m.group(4).split(',')]
        if tname in tables:
            tables[tname]['indexes'].append({'name': idx_name, 'columns': idx_cols, 'unique': is_uq})
    # ALTER TABLE ADD CONSTRAINT FK
    for m in re.finditer(
        r'ALTER\s+TABLE\s+(?:ONLY\s+)?\"?(?:\w+\.)?(\w+)\"?\s+ADD\s+CONSTRAINT\s+\"?(\w+)\"?\s+FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+\"?(?:\w+\.)?(\w+)\"?\s*\(([^)]+)\)',
        content, re.IGNORECASE
    ):
        tname, _, fk_str, ref_table, ref_str = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        for i, fc in enumerate([c.strip().strip('"') for c in fk_str.split(',')]):
            rcs = [c.strip().strip('"') for c in ref_str.split(',')]
            rc = rcs[i] if i < len(rcs) else rcs[0]
            if tname in tables:
                for col in tables[tname]['columns']:
                    if col['name'] == fc:
                        col['fk'] = f"{ref_table}({rc})"
            relationships.append({'from_table': tname, 'from_column': fc, 'to_table': ref_table, 'to_column': rc})
    # ALTER TABLE ADD CONSTRAINT UNIQUE
    for m in re.finditer(
        r'ALTER\s+TABLE\s+(?:ONLY\s+)?\"?(?:\w+\.)?(\w+)\"?\s+ADD\s+CONSTRAINT\s+\"?(\w+)\"?\s+UNIQUE\s*\(([^)]+)\)',
        content, re.IGNORECASE
    ):
        tname, cname = m.group(1), m.group(2)
        uq_cols = [c.strip().strip('"') for c in m.group(3).split(',')]
        if tname in tables:
            if len(uq_cols) == 1:
                for col in tables[tname]['columns']:
                    if col['name'] == uq_cols[0]:
                        col['unique'] = True
            else:
                tables[tname]['indexes'].append({'name': cname, 'columns': uq_cols, 'unique': True})
    return list(tables.values()), relationships

def _parse_schema_rb(content):
    """Parse Rails schema.rb."""
    tables, relationships = {}, []
    current = None
    for line in content.split('\n'):
        line = line.strip()
        m = re.match(r'create_table\s+"(\w+)"(.*)', line)
        if m:
            current = m.group(1)
            opts = m.group(2)
            cols = []
            if 'id: false' not in opts:
                pk_type = 'BIGINT'
                pk_m = re.search(r'primary_key:\s*:(\w+)', opts)
                if pk_m and pk_m.group(1).lower() == 'uuid':
                    pk_type = 'UUID'
                cols.append({'name': 'id', 'type': pk_type, 'pk': True, 'fk': None, 'nullable': False, 'unique': False, 'default': None})
            tables[current] = {'name': current, 'schema': '', 'columns': cols, 'indexes': []}
            continue
        if line == 'end':
            current = None
            continue
        if not current or current not in tables:
            continue
        col_m = re.match(r't\.(\w+)\s+"(\w+)"(.*)', line)
        if col_m:
            rb_type, col_name, opts = col_m.group(1), col_m.group(2), col_m.group(3)
            tmap = {'string': 'VARCHAR', 'text': 'TEXT', 'integer': 'INTEGER', 'bigint': 'BIGINT',
                    'float': 'FLOAT', 'decimal': 'DECIMAL', 'boolean': 'BOOLEAN', 'datetime': 'TIMESTAMP',
                    'date': 'DATE', 'time': 'TIME', 'binary': 'BYTEA', 'jsonb': 'JSONB', 'json': 'JSON',
                    'uuid': 'UUID', 'inet': 'INET', 'references': 'BIGINT', 'belongs_to': 'BIGINT',
                    'citext': 'CITEXT', 'hstore': 'HSTORE', 'interval': 'INTERVAL'}
            ct = tmap.get(rb_type, rb_type.upper())
            is_ref = rb_type in ('references', 'belongs_to')
            actual_name = f"{col_name}_id" if is_ref else col_name
            fk_val = None
            if is_ref:
                # Try to find foreign_key option
                fk_tbl_m = re.search(r'foreign_key:\s*\{?\s*to_table:\s*[:"]+(\w+)', opts)
                fk_tbl = fk_tbl_m.group(1) if fk_tbl_m else col_name + 's'
                fk_val = f"{fk_tbl}(id)"
                relationships.append({'from_table': current, 'from_column': actual_name, 'to_table': fk_tbl, 'to_column': 'id'})
            col = {'name': actual_name, 'type': ct, 'pk': False, 'fk': fk_val,
                   'nullable': 'null: false' not in opts, 'unique': False, 'default': None}
            def_m = re.search(r'default:\s*("([^"]*)"|(\S+))', opts)
            if def_m:
                col['default'] = def_m.group(2) if def_m.group(2) is not None else def_m.group(3)
            tables[current]['columns'].append(col)
            continue
        idx_m = re.match(r't\.index\s+\[([^\]]+)\](.*)', line)
        if idx_m:
            idx_cols = [c.strip().strip('"') for c in idx_m.group(1).split(',')]
            rest = idx_m.group(2)
            nm_m = re.search(r'name:\s*"(\w+)"', rest)
            idx_name = nm_m.group(1) if nm_m else f"idx_{current}_{'_'.join(idx_cols)}"
            is_uq = 'unique: true' in rest
            tables[current]['indexes'].append({'name': idx_name, 'columns': idx_cols, 'unique': is_uq})
            if is_uq and len(idx_cols) == 1:
                for col in tables[current]['columns']:
                    if col['name'] == idx_cols[0]:
                        col['unique'] = True
    # add_foreign_key "from_table", "to_table"[, column: "col"]
    for m in re.finditer(
        r'add_foreign_key\s+"(\w+)",\s+"(\w+)"(.*)', content
    ):
        from_tbl, to_tbl, opts = m.group(1), m.group(2), m.group(3)
        col_m = re.search(r'column:\s*"(\w+)"', opts)
        from_col = col_m.group(1) if col_m else to_tbl.rstrip('s') + '_id'
        relationships.append({'from_table': from_tbl, 'from_column': from_col,
                              'to_table': to_tbl, 'to_column': 'id'})
        if from_tbl in tables:
            for col in tables[from_tbl]['columns']:
                if col['name'] == from_col:
                    col['fk'] = f"{to_tbl}(id)"
    return list(tables.values()), relationships

def _parse_prisma(content):
    """Parse Prisma schema."""
    tables, relationships = {}, []
    current = None
    for line in content.split('\n'):
        line = line.strip()
        m = re.match(r'model\s+(\w+)\s*\{', line)
        if m:
            current = m.group(1)
            tables[current] = {'name': current, 'schema': '', 'columns': [], 'indexes': []}
            continue
        if line == '}':
            current = None
            continue
        if not current or current not in tables:
            continue
        col_m = re.match(r'(\w+)\s+(\w+)(\[\])?\??(.*)$', line)
        if col_m:
            name, ptype, is_arr, attrs = col_m.group(1), col_m.group(2), bool(col_m.group(3)), col_m.group(4) or ''
            if is_arr:
                continue
            tmap = {'Int': 'INTEGER', 'BigInt': 'BIGINT', 'Float': 'FLOAT', 'Decimal': 'DECIMAL',
                    'String': 'TEXT', 'Boolean': 'BOOLEAN', 'DateTime': 'TIMESTAMP', 'Json': 'JSONB', 'Bytes': 'BYTEA'}
            if ptype not in tmap:
                # Relation field
                if '@relation' in attrs:
                    rel_m = re.search(r'@relation\(.*?fields:\s*\[(\w+)\].*?references:\s*\[(\w+)\]', attrs)
                    if rel_m:
                        relationships.append({'from_table': current, 'from_column': rel_m.group(1), 'to_table': ptype, 'to_column': rel_m.group(2)})
                continue
            ct = tmap[ptype]
            is_id = '@id' in attrs
            is_uq = '@unique' in attrs
            nullable = '?' in line.split(name, 1)[1].split('@')[0]
            def_val = None
            def_m = re.search(r'@default\(([^)]+)\)', attrs)
            if def_m:
                def_val = def_m.group(1)
            tables[current]['columns'].append({'name': name, 'type': ct, 'pk': is_id,
                'fk': None, 'nullable': nullable, 'unique': is_uq or is_id, 'default': def_val})
            continue
        idx_m = re.match(r'@@(index|unique)\(\[([^\]]+)\](?:.*name:\s*"(\w+)")?\)', line)
        if idx_m:
            it, cols_str, iname = idx_m.group(1), idx_m.group(2), idx_m.group(3)
            cols = [c.strip().strip('"') for c in cols_str.split(',')]
            tables[current]['indexes'].append({
                'name': iname or f"{'uq' if it == 'unique' else 'idx'}_{current}_{'_'.join(cols)}",
                'columns': cols, 'unique': it == 'unique'})
    # Set FK info on columns
    for r in relationships:
        if r['from_table'] in tables:
            for col in tables[r['from_table']]['columns']:
                if col['name'] == r['from_column']:
                    col['fk'] = f"{r['to_table']}({r['to_column']})"
    return list(tables.values()), relationships

def _get_schema(kanban_dir):
    """Find and parse all schema files for a project."""
    files, project_dir = _find_schema_files(kanban_dir)
    if not files:
        return {"tables": [], "relationships": [], "files": []}
    all_tables, all_rels, file_info = {}, [], []
    # If schema.rb or structure.sql exists, skip migration files
    has_schema = any(os.path.basename(f).endswith("_schema.rb") or os.path.basename(f) in ("schema.rb", "structure.sql") for f in files)
    if has_schema:
        files = [f for f in files if "/migrate/" not in f and "/migrations/" not in f]
    for fpath in files:
        with open(fpath, encoding="utf-8", errors="replace") as f:
            content = f.read()
        fname = os.path.basename(fpath)
        if fname.endswith(".rb"):
            tbls, rels = _parse_schema_rb(content)
        elif fname.endswith(".prisma"):
            tbls, rels = _parse_prisma(content)
        else:
            tbls, rels = _parse_sql_schema(content)
        rel_path = os.path.relpath(fpath, project_dir)
        for t in tbls:
            if t["name"] in all_tables:
                ex = all_tables[t["name"]]
                if t["columns"]:
                    ex["columns"] = t["columns"]
                ex["indexes"].extend(t.get("indexes", []))
            else:
                t["source_file"] = rel_path
                all_tables[t["name"]] = t
        all_rels.extend(rels)
        file_info.append({"path": rel_path, "type": fname.rsplit(".", 1)[-1]})
    # Deduplicate relationships
    seen, unique_rels = set(), []
    for r in all_rels:
        key = (r["from_table"], r["from_column"], r["to_table"], r["to_column"])
        if key not in seen:
            seen.add(key); unique_rels.append(r)
    return {"tables": sorted(all_tables.values(), key=lambda t: t["name"]),
            "relationships": unique_rels, "files": file_info}

def _get_context(kanban_dir):
    """Current session context: phase, scope, in-progress tasks, do-not-touch."""
    project_dir = os.path.dirname(os.path.abspath(kanban_dir))
    phase_file = None
    for candidate in [
        os.path.join(project_dir, "private", "CURRENT_PHASE.md"),
        os.path.join(project_dir, "docs", "CURRENT_PHASE.md"),
        os.path.join(project_dir, "CURRENT_PHASE.md"),
    ]:
        if os.path.exists(candidate):
            phase_file = candidate
            break

    phase_name, scope, checklist_items, do_not_touch = "", "", [], []

    if phase_file:
        with open(phase_file, encoding="utf-8") as f:
            content = f.read()
        section = None
        for line in content.splitlines():
            m = re.match(r"^##\s*Now:\s*(.+)", line)
            if m: phase_name = m.group(1).strip(); continue
            m = re.match(r"^##\s*Scope:\s*(.+)", line)
            if m: scope = m.group(1).strip(); continue
            if re.match(r"^##\s*Done when", line, re.IGNORECASE): section = "checklist"; continue
            if re.match(r"^##\s*Do NOT touch", line, re.IGNORECASE): section = "do_not_touch"; continue
            if re.match(r"^##", line): section = None; continue
            if line.strip().startswith("<!--"): continue
            if section == "checklist":
                chk = re.match(r"^- \[([xX ])\]\s*(.+)", line)
                if chk:
                    checklist_items.append({"text": chk.group(2).strip(), "done": chk.group(1).lower() == "x"})
            elif section == "do_not_touch":
                bullet = re.match(r"^-\s+(.+)", line)
                if bullet:
                    do_not_touch.append(bullet.group(1).strip())
                elif line.strip() and not line.strip().startswith("#"):
                    do_not_touch.extend(p.strip() for p in line.split(",") if p.strip())

    data = _read_kanban(kanban_dir)
    all_tasks = data.get("tasks", [])
    archived = _list_archives(kanban_dir)

    in_progress = [t for t in all_tasks if t.get("status") == "in_progress"]
    all_done = sorted(
        [t for t in (all_tasks + archived) if t.get("status") == "done"],
        key=lambda t: t.get("completed_at") or t.get("updated_at") or "",
        reverse=True
    )

    stats = {s: 0 for s in ["backlog", "todo", "in_progress", "review", "done"]}
    for t in all_tasks + archived:
        s = t.get("status", "")
        if s in stats:
            stats[s] += 1

    done_checks = sum(1 for c in checklist_items if c["done"])
    return {
        "phase": phase_name,
        "scope": scope,
        "checklist": {
            "total": len(checklist_items),
            "done": done_checks,
            "items": checklist_items,
        },
        "do_not_touch": do_not_touch,
        "in_progress": in_progress,
        "recent_done": all_done[:3],
        "stats": stats,
    }


def _get_phase_check(kanban_dir):
    """Check phase transition readiness: kanban state + CURRENT_PHASE.md checklist."""
    project_dir = os.path.dirname(os.path.abspath(kanban_dir))
    issues = []
    warnings = []

    # 1. Kanban state
    data = _read_kanban(kanban_dir)
    tasks = data.get("tasks", [])
    in_progress = [t for t in tasks if t.get("status") == "in_progress"]
    review = [t for t in tasks if t.get("status") == "review"]
    if in_progress:
        issues.append(f"in_progress 태스크 {len(in_progress)}개: " +
                      ", ".join(f"#{t['id']} {t['title'][:30]}" for t in in_progress))
    if review:
        issues.append(f"review 미해결 태스크 {len(review)}개: " +
                      ", ".join(f"#{t['id']} {t['title'][:30]}" for t in review))

    # 2. CURRENT_PHASE.md checklist
    phase_file = None
    for candidate in [
        os.path.join(project_dir, "CURRENT_PHASE.md"),
        os.path.join(project_dir, "docs", "CURRENT_PHASE.md"),
    ]:
        if os.path.exists(candidate):
            phase_file = candidate
            break

    unchecked, total_checks, phase_name = [], 0, ""
    if phase_file:
        with open(phase_file, encoding="utf-8") as f:
            content = f.read()
        for line in content.splitlines():
            m = re.match(r"^##\s*Now:\s*(.+)", line)
            if m:
                phase_name = m.group(1).strip()
            chk = re.match(r"^- \[([ xX])\]\s*(.+)", line)
            if chk:
                total_checks += 1
                if chk.group(1) == " ":
                    unchecked.append(chk.group(2).strip())
        if unchecked:
            issues.append(f"Done when 미완료 {len(unchecked)}/{total_checks}: " +
                          ", ".join(unchecked[:3]) + ("..." if len(unchecked) > 3 else ""))
    else:
        warnings.append("CURRENT_PHASE.md 없음 — 수동으로 확인하세요")

    # 3. PHASES.md freshness
    phases_file = os.path.join(project_dir, "PHASES.md")
    if not os.path.exists(phases_file):
        warnings.append("PHASES.md 없음 — Phase 완료 기록을 남겨야 합니다")

    ready = len(issues) == 0
    return {
        "ready": ready,
        "phase": phase_name,
        "issues": issues,
        "warnings": warnings,
        "kanban": {
            "in_progress": len(in_progress),
            "review": len(review),
            "done": sum(1 for t in tasks if t.get("status") == "done"),
        },
        "checklist": {
            "total": total_checks,
            "unchecked": len(unchecked),
        },
    }

# ── Decision Log ────────────────────────────────────

def _decisions_path(kanban_dir):
    return os.path.join(kanban_dir, "decisions.json")

def _read_decisions(kanban_dir):
    p = _decisions_path(kanban_dir)
    if not os.path.exists(p):
        return {"version": 1, "next_id": 1, "decisions": []}
    with open(p) as f:
        return json.load(f)

def _write_decisions(kanban_dir, data):
    p = _decisions_path(kanban_dir)
    os.makedirs(kanban_dir, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, p)

def _new_decision(data, d):
    dec = {
        "id": data["next_id"],
        "title": d.get("title", "").strip(),
        "why": d.get("why", "").strip(),
        "revisit": d.get("revisit", "").strip(),
        "task_id": d.get("task_id"),
        "phase": d.get("phase", "").strip(),
        "tags": d.get("tags", []),
        "created_at": _now(),
        "updated_at": _now(),
    }
    data["next_id"] += 1
    data["decisions"].append(dec)
    return data, dec

def _update_decision(dec, d):
    for f in ("title", "why", "revisit", "task_id", "phase", "tags"):
        if f in d:
            dec[f] = d[f]
    dec["updated_at"] = _now()


# ── Runs Log (agent run usage, append-only) ──────────

def _runs_path(kanban_dir):
    return os.path.join(kanban_dir, "runs.json")

def _read_runs(kanban_dir):
    p = _runs_path(kanban_dir)
    if not os.path.exists(p):
        return {"version": 1, "runs": []}
    with open(p) as f:
        return json.load(f)

def _write_runs(kanban_dir, data):
    p = _runs_path(kanban_dir)
    os.makedirs(kanban_dir, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, p)

def _safe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0

def _new_run(data, r):
    """Append an agent run. Agent-agnostic: `agent` is a free string.

    Optional cache_read_tokens/cache_write_tokens enable accurate component-based
    cost (Claude transcripts are cache-heavy). session_id supports idempotent
    auto-collection (skip if already recorded). All extra fields are additive —
    runs.json stays append-only and backward compatible.
    """
    run = {
        "task_id": r.get("task_id"),
        "agent": (r.get("agent") or "").strip(),
        "model": (r.get("model") or "").strip(),
        "tokens": _safe_int(r.get("tokens")),
        "input_tokens": r.get("input_tokens"),
        "output_tokens": r.get("output_tokens"),
        "cache_read_tokens": r.get("cache_read_tokens"),
        "cache_write_tokens": r.get("cache_write_tokens"),
        "time_seconds": r.get("time_seconds"),
        "commit": (r.get("commit") or "").strip(),
        "session_id": (r.get("session_id") or "").strip(),
        "ts": (r.get("ts") or "").strip() or _now(),
    }
    data.setdefault("runs", []).append(run)
    return data, run

def _sync_task_tokens(kanban_dir, task_id, runs):
    """Derive a task's tokens_used from the sum of its runs (board stays correct)."""
    if task_id is None:
        return
    total = sum(_safe_int(r.get("tokens")) for r in runs if r.get("task_id") == task_id)
    data = _read_kanban(kanban_dir)
    task = next((t for t in data["tasks"] if t.get("id") == task_id), None)
    if task is not None:
        task["tokens_used"] = total
        task["updated_at"] = _now()
        _write_kanban(kanban_dir, data)


# ── Velocity & Cost Tracking ─────────────────────────

CLAUDE_COST_PER_TOKEN = 0.000009  # ~$9/MTok blended (Sonnet 4.6 avg) — fallback default

# Blended $/token (input+output rough avg) per agent → model substring.
# Used when runs.json carries per-run agent/model attribution; falls back to _default.
COST_PER_TOKEN = {
    "claude": {
        "_default": 0.000009,
        "opus": 0.00003,    # ~$15/$75 in/out blended
        "sonnet": 0.000009,
        "haiku": 0.0000024,
    },
    "codex": {"_default": 0.000006},
    "gpt": {"_default": 0.000006},
    "gemini": {"_default": 0.000004},
    "cursor": {"_default": 0.000006},
    "_default": CLAUDE_COST_PER_TOKEN,
}

def _cost_per_token(agent, model):
    """Resolve blended cost rate from agent + model (substring match)."""
    amap = COST_PER_TOKEN.get((agent or "").lower())
    if not amap:
        return COST_PER_TOKEN["_default"]
    ml = (model or "").lower()
    for key, rate in amap.items():
        if key != "_default" and key in ml:
            return rate
    return amap.get("_default", COST_PER_TOKEN["_default"])

# Per-component $/token (PMF03, cost model A). Used when a run carries a token
# breakdown (input/output/cache_read/cache_write) — accurate because Claude runs
# are cache-dominated and cache reads cost ~10% of input.
COMPONENT_RATES = {
    "claude": {
        "opus":     {"in": 0.000015, "out": 0.000075, "cw": 0.00001875, "cr": 0.0000015},
        "sonnet":   {"in": 0.000003, "out": 0.000015, "cw": 0.00000375, "cr": 0.0000003},
        "haiku":    {"in": 0.000001, "out": 0.000005, "cw": 0.00000125, "cr": 0.0000001},
        "_default": {"in": 0.000003, "out": 0.000015, "cw": 0.00000375, "cr": 0.0000003},
    },
}

def _component_rates(agent, model):
    amap = COMPONENT_RATES.get((agent or "").lower())
    if not amap:
        return None
    ml = (model or "").lower()
    for key, rates in amap.items():
        if key != "_default" and key in ml:
            return rates
    return amap.get("_default")

def _run_cost(run):
    """Cost of one run. Uses component rates when a breakdown is present,
    else falls back to the blended flat rate on `tokens` (e.g. Codex/Gemini)."""
    agent, model = run.get("agent"), run.get("model")
    rates = _component_rates(agent, model)
    has_breakdown = any(run.get(k) is not None for k in
                        ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))
    if rates and has_breakdown:
        return (_safe_int(run.get("input_tokens")) * rates["in"]
                + _safe_int(run.get("output_tokens")) * rates["out"]
                + _safe_int(run.get("cache_read_tokens")) * rates["cr"]
                + _safe_int(run.get("cache_write_tokens")) * rates["cw"])
    return _safe_int(run.get("tokens")) * _cost_per_token(agent, model)

def _get_velocity(kanban_dir):
    """Phase burndown + token cost stats. Tokens/cost derive from runs.json when present."""
    from collections import defaultdict
    data = _read_kanban(kanban_dir)
    archived = _list_archives(kanban_dir)
    all_tasks = data.get("tasks", []) + archived

    runs = _read_runs(kanban_dir).get("runs", [])
    runs_by_task = defaultdict(list)
    for r in runs:
        runs_by_task[r.get("task_id")].append(r)

    def task_tokens(t):
        rs = runs_by_task.get(t.get("id"))
        if rs:
            return sum(_safe_int(r.get("tokens")) for r in rs)
        return t.get("tokens_used") or 0

    def task_cost(t):
        rs = runs_by_task.get(t.get("id"))
        if rs:
            return sum(_run_cost(r) for r in rs)
        return (t.get("tokens_used") or 0) * CLAUDE_COST_PER_TOKEN

    # ── Phase stats ──
    phase_map = {}
    for t in all_tasks:
        ph = t.get("phase") or "No Phase"
        if ph not in phase_map:
            phase_map[ph] = {"phase": ph, "total": 0, "done": 0, "tokens": 0, "cost": 0.0, "dates": []}
        phase_map[ph]["total"] += 1
        if t.get("status") == "done":
            phase_map[ph]["done"] += 1
            cd = t.get("completed_at") or t.get("updated_at") or ""
            if cd:
                phase_map[ph]["dates"].append(cd[:10])
        phase_map[ph]["tokens"] += task_tokens(t)
        phase_map[ph]["cost"] += task_cost(t)

    phases = []
    for ph, s in sorted(phase_map.items()):
        pct = round(s["done"] / s["total"] * 100) if s["total"] else 0
        phases.append({
            "phase": ph,
            "total": s["total"],
            "done": s["done"],
            "remaining": s["total"] - s["done"],
            "pct": pct,
            "tokens": s["tokens"],
            "cost_usd": round(s["cost"], 4),
        })

    # ── Daily done trend (last 30 days) ──
    daily = defaultdict(int)
    for t in all_tasks:
        if t.get("status") == "done":
            cd = (t.get("completed_at") or t.get("updated_at") or "")[:10]
            if cd:
                daily[cd] += 1
    daily_trend = [{"date": k, "count": v} for k, v in sorted(daily.items())[-30:]]

    # ── Category token breakdown ──
    cat_tokens = defaultdict(int)
    cat_cost = defaultdict(float)
    for t in all_tasks:
        cat = t.get("category") or "기타"
        cat_tokens[cat] += task_tokens(t)
        cat_cost[cat] += task_cost(t)
    category_breakdown = [
        {"category": k, "tokens": v, "cost_usd": round(cat_cost[k], 4)}
        for k, v in sorted(cat_tokens.items(), key=lambda x: -x[1])
    ]

    # ── Agent / model breakdown (from runs.json) ──
    agent_tok = defaultdict(int); agent_cost = defaultdict(float); agent_runs = defaultdict(int)
    model_tok = defaultdict(int); model_cost = defaultdict(float); model_runs = defaultdict(int)
    for r in runs:
        ag = r.get("agent") or "unknown"
        md = r.get("model") or "—"
        tok = _safe_int(r.get("tokens"))
        c = _run_cost(r)
        agent_tok[ag] += tok; agent_cost[ag] += c; agent_runs[ag] += 1
        mk = (ag, md)
        model_tok[mk] += tok; model_cost[mk] += c; model_runs[mk] += 1
    agent_breakdown = [
        {"agent": k, "tokens": v, "cost_usd": round(agent_cost[k], 4), "runs": agent_runs[k]}
        for k, v in sorted(agent_tok.items(), key=lambda x: -x[1])
    ]
    model_breakdown = [
        {"agent": k[0], "model": k[1], "tokens": v, "cost_usd": round(model_cost[k], 4), "runs": model_runs[k]}
        for k, v in sorted(model_tok.items(), key=lambda x: -x[1])
    ]

    total_tokens = sum(task_tokens(t) for t in all_tasks)
    total_cost = sum(task_cost(t) for t in all_tasks)
    return {
        "phases": phases,
        "daily_trend": daily_trend,
        "category_breakdown": category_breakdown,
        "agent_breakdown": agent_breakdown,
        "model_breakdown": model_breakdown,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "total_runs": len(runs),
        "total_tasks": len(all_tasks),
        "total_done": sum(1 for t in all_tasks if t.get("status") == "done"),
    }


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
                all_tasks.sort(key=lambda t: (t.get("position", 0), str(t.get("id", 0))))
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

            if rest == ["schema"]:
                return self._json(_get_schema(kanban_dir))

            if rest == ["phase-check"]:
                return self._json(_get_phase_check(kanban_dir))

            if rest == ["context"]:
                return self._json(_get_context(kanban_dir))

            if rest == ["decisions"]:
                data = _read_decisions(kanban_dir)
                return self._json(data["decisions"])

            if rest == ["velocity"]:
                return self._json(_get_velocity(kanban_dir))

            if rest == ["runs"]:
                qs = parse_qs(parsed.query)
                runs = _read_runs(kanban_dir)["runs"]
                tid = qs.get("task_id", [None])[0]
                if tid is not None:
                    runs = [r for r in runs if str(r.get("task_id")) == str(tid)]
                return self._json(runs)

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

            if rest == ["decisions"]:
                d = self._body()
                data = _read_decisions(kanban_dir)
                data, dec = _new_decision(data, d)
                _write_decisions(kanban_dir, data)
                return self._json(dec, 201)

            if rest == ["runs"]:
                d = self._body()
                if not (d.get("agent") or "").strip():
                    return self._json({"error": "agent required"}, 400)
                data = _read_runs(kanban_dir)
                data, run = _new_run(data, d)
                _write_runs(kanban_dir, data)
                # Derive the linked task's tokens_used from its runs (board stays correct).
                _sync_task_tokens(kanban_dir, run.get("task_id"), data["runs"])
                return self._json(run, 201)

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

            if len(rest) == 2 and rest[0] == "decisions":
                did = int(rest[1])
                d = self._body()
                data = _read_decisions(kanban_dir)
                dec = next((x for x in data["decisions"] if x["id"] == did), None)
                if not dec:
                    return self._json({"error": "not found"}, 404)
                _update_decision(dec, d)
                _write_decisions(kanban_dir, data)
                return self._json(dec)

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

            if len(rest) == 2 and rest[0] == "decisions":
                did = int(rest[1])
                data = _read_decisions(kanban_dir)
                data["decisions"] = [x for x in data["decisions"] if x["id"] != did]
                _write_decisions(kanban_dir, data)
                return self._json({"deleted": did})

        self.send_response(404)
        self.end_headers()


# ── Main ────────────────────────────────────────────

def main():
    port = 4242

    if len(sys.argv) > 1 and sys.argv[1] == "register":
        key = sys.argv[2]
        name = sys.argv[3] if len(sys.argv) > 3 else key
        kanban_dir = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.getcwd(), "vibe-harness")
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

    print(f"Vibe Harness v5 — http://localhost:{port}/kanban")
    print(f"  Projects: {', '.join(projects.keys()) if projects else '(none)'}")
    print(f"  Storage: JSON (git-friendly)")
    print(f"  Ctrl+C to stop")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
