# Vibe Harness

**Session harness for Claude Code.**  
Scope boundaries, task accountability, phase gates, and code review — built for AI-speed development.

Vibe coding is fast. But it drifts. Vibe Harness gives Claude a frame: what to work on, what not to touch, when to stop, and what happened.

---

### Kanban View (Dark)
![Kanban Dark](docs/screenshot-kanban-dark.png)

### List View
![List View](docs/screenshot-list.png)

### Detail Panel
![Detail Panel](docs/screenshot-detail.png)

---

## The Problem

When you code with Claude at full speed, three things tend to go wrong:

1. **Drift** — Claude touches files outside the original scope
2. **Amnesia** — the next session has no idea what was decided last time
3. **No gates** — code ships without review, docs stay stale, phases blur together

Vibe Harness is a harness, not just a board. It gives Claude the structure to stay in bounds.

---

## How It Works

```
CURRENT_PHASE.md     ← what Claude may/must not touch this session
PHASES.md            ← master plan, completion history
kanban board         ← one in_progress at a time, tracked per task
review hook          ← auto-triggered on git push / gh pr create
qq / cc commands     ← session-end rituals that close the loop
```

The kanban board (localhost:4242) is the visible surface. The real value is the discipline layer underneath: phase files, scope locks, review gates, and session bookends.

---

## Features

- **Phase management** — SEED → MVP → PMF → SCALE → GTM. Scope per phase defined in `CURRENT_PHASE.md`. Claude must not touch anything outside the `Do NOT touch` list.
- **One in_progress at a time** — enforced by the skill. If Claude starts a second task, the first gets bumped back to `todo`.
- **Task accountability** — `lines_added`, `lines_removed`, `tokens_used`, work report, and decisions logged per task on completion.
- **Review gate** — `git push` / `gh pr create` auto-triggers a structured code review hook. Findings land in the kanban as `review` tasks.
- **Multi-project** — one server (port 4242), multiple projects as tabs. Each project's data is JSON — git-tracked alongside code.
- **DB Schema view** — reads schema files (schema.rb, schema.sql, Prisma) and renders an ERD: tables, columns, PK/FK/UQ badges, index list, and FK relationship lines.
- **Archive** — done tasks auto-archived to monthly JSON files. Always visible. Never lost.
- **Session rituals** — `qq` (wrap-up without push) and `cc` (commit + push + deploy + docs) as first-class commands.
- **Zero dependencies** — pure Python + vanilla JS. No npm, no pip, no build step.

---

## Install

### 1. Clone

```bash
git clone https://github.com/hoarchi/vibe-harness.git
cd vibe-harness
```

### 2. Setup

```bash
python3 scripts/setup.py
```

This does four things:

1. Copies `server.py`, `kanban.html`, `SKILL.md` → `~/.claude/skills/vibe-harness/`
2. Installs a macOS LaunchAgent — server auto-starts on login at port 4242
3. Registers a code review hook in `~/.claude/settings.json`
4. Migrates old project registry if upgrading from a prior version

After setup, the cloned repo is only needed for updates.

### 3. Register your project

```bash
python3 ~/.claude/skills/vibe-harness/server.py register my_project "My Project" "$(pwd)/vibe-harness"
```

### 4. Open the board

[http://localhost:4242/kanban](http://localhost:4242/kanban)

---

## Update

```bash
python3 ~/.claude/skills/vibe-harness/setup.py upgrade
```

Downloads latest `server.py`, `kanban.html`, `SKILL.md` from GitHub and restarts the server. No repo pull needed.

**First time upgrading from an older install?**

```bash
curl -sL https://raw.githubusercontent.com/hoarchi/vibe-harness/main/scripts/setup.py \
  -o ~/.claude/skills/vibe-harness/setup.py
```

---

## Uninstall

```bash
python3 scripts/setup.py uninstall
```

---

## Using It as a Harness

The board is useful out of the box. But the real leverage comes from using the full harness pattern.

### Session start prompt (add to your workflow)

```
PHASES.md와 CURRENT_PHASE.md를 읽고 작업을 시작해.
현재 Phase의 scope 밖은 건드리지 말고,
완료 후 PHASES.md를 업데이트해줘.
```

This single prompt means Claude starts every session knowing exactly what's in scope and what to leave alone.

### Keep CURRENT_PHASE.md tight

```markdown
## Now: PHASE_MVP02
## Scope: [auth flow, user model, sessions controller]
## Done when:
- [x] login/logout working
- [ ] password reset email
- [ ] session expiry
## Do NOT touch: billing, admin panel, mailers other than password reset
```

The `Do NOT touch` list is the harness. The shorter the scope, the faster and safer the session.

### One task in_progress

The skill enforces this. If you notice two tasks `in_progress` on the board, something went wrong — Claude started a subtask without closing the parent. Call it out explicitly.

### Token budget as a task size signal

If a task burns >100K tokens and still isn't done, it's too big. Break it in half. Tasks with high `tokens_used` + low `lines_added` are usually analysis tasks masquerading as implementation tasks.

### Review before every push, not just on merge

The hook triggers on `git push`. Don't skip it. If Claude is pushing 10 times a day, 10 reviews is correct — each one is scoped to what actually changed.

### Phase graduation checklist

Before moving to the next phase:

1. All `done-when` items checked in `CURRENT_PHASE.md`
2. `PHASES.md` updated with completion date and task count
3. `qq` run to close open work reports
4. All tasks in kanban are `done` or moved to next phase backlog
5. Screenshot the board — it's the record of the phase

### Archive as institutional memory

Monthly archive files (`vibe-harness/archive/YYYY-MM.json`) are git-tracked. They're a searchable history of every decision, every file changed, every token spent. When something breaks three months later, check the archive before blaming recent changes.

---

## File Layout

```
~/.claude/skills/vibe-harness/
  SKILL.md           ← Claude reads this to know the commands
  server.py          ← HTTP server: API + static serving
  kanban.html        ← Single-file vanilla JS UI
  projects.json      ← Project registry (which boards exist)
  server.log         ← Server stdout

{project}/vibe-harness/
  kanban.json              ← Active tasks
  archive/
    2026-03.json           ← Monthly archives (git-tracked)
    2026-04.json

~/Library/LaunchAgents/com.vibe-harness.server.plist   ← Auto-start
~/.claude/hooks/vibe-harness-review.sh                 ← Review hook
```

---

## Commands

| Command | Description |
|---|---|
| `/vibe-harness` | Current board status |
| `/vibe-harness serve` | Start server + register project |
| `/vibe-harness add <title>` | Add a task |
| `/vibe-harness start <id>` | Move to in_progress |
| `/vibe-harness done <id>` | Mark done (records lines + report) |
| `/vibe-harness archive` | Archive done tasks to monthly file |
| `/vibe-harness report` | Today's completed task summary |
| `qq` | Session wrap-up: docs + kanban + no push |
| `cc` | Full close: docs + kanban + commit + push + deploy |

---

## Web UI

### Kanban view
Backlog / To Do / In Progress / Review / Done columns. Cards show title, priority, category, D-day countdown, and code change bars. Edit on hover; click card to open detail panel.

### List view
Spreadsheet-style table with all tasks including archived. Inline editing — click any cell.

### Done zone
Completed tasks grouped by date, category, or phase. Archived tasks load alongside active done tasks.

### Detail panel
Full description, work report, code review items with resolved/unresolved toggles, schedule, code change bar graph, and token usage.

### DB Schema view
Click **DB** tab to see project database schema as an ERD. No DB connection needed — reads schema files directly.

Auto-detects:

| File | Format |
|---|---|
| `db/schema.rb` | Rails ActiveRecord |
| `db/structure.sql` | Rails SQL dump |
| `prisma/schema.prisma` | Prisma ORM |
| `schema.sql` | Any SQL DDL |
| `db/migrations/*.sql` | Raw SQL migrations |

Shows: column types, PK/FK/UQ/NN/DF badges, indexes, and Bezier FK relationship lines between tables.

---

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/projects` | List projects |
| POST | `/api/projects` | Register project |
| GET | `/api/{key}/tasks` | List tasks (active + archived) |
| POST | `/api/{key}/tasks` | Create task |
| PUT | `/api/{key}/tasks/{id}` | Update task |
| DELETE | `/api/{key}/tasks/{id}` | Delete task |
| POST | `/api/{key}/tasks/bulk` | Bulk create |
| GET | `/api/{key}/export` | Export to JSON |
| POST | `/api/{key}/import` | Import from JSON |
| POST | `/api/{key}/archive` | Archive done tasks |
| GET | `/api/{key}/stats` | Count by status |
| GET | `/api/{key}/schema` | Parse schema files → ERD data |

### Task fields

| Field | Type | Description |
|---|---|---|
| `title` | string | Required |
| `description` | string | One-liner context |
| `details` | string | Work report: files changed, decisions, notes |
| `status` | string | `backlog` / `todo` / `in_progress` / `review` / `done` |
| `priority` | string | `low` / `medium` / `high` |
| `category` | string | `backend` / `frontend` / `infra` / `data` / `docs` / `qa` |
| `phase` | string | e.g. `PHASE_MVP02` |
| `target_date` | string | YYYY-MM-DD |
| `started_at` | string | Auto-set on → in_progress |
| `completed_at` | string | Auto-set on → done |
| `lines_added` | int | From `git diff --numstat` |
| `lines_removed` | int | From `git diff --numstat` |
| `tokens_used` | int | Estimated — Claude records on completion |
| `review` | string | JSON: `[{"text":"...","resolved":false}]` |
| `created_by` | string | Auto from `git config user.name` |
| `assigned_to` | string | Set on `/vibe-harness start` |

---

## Requirements

- Python 3.6+
- Claude Code CLI
- macOS (LaunchAgent auto-start; server works on any OS)

---

## License

MIT — [Hogun Jung](https://github.com/hoarchi) / [Zest Inc.](https://zest.im)
