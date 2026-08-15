# Vibe Engineering

**Session harness for Claude Code.**  
Scope boundaries, task accountability, phase gates, and code review — built for AI-speed development.

Vibe coding is fast. But it drifts. Vibe Engineering gives Claude a frame: what to work on, what not to touch, when to stop, and what happened.

**How it got here.** It started as **vibe-kanban** — just a board to track what the agent was doing. Tracking alone
turned out to be too little: the agent needed boundaries, gates, and a record, so the board grew into a session
harness and the project became **vibe-harness**. What that harness actually does is engineer the conditions the
agent works under, which is a broader job than holding a session together — hence **vibe-engineering**. Planning
and design skills come first; loop engineering and graph engineering are next.

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

Vibe Engineering is a harness, not just a board. It gives Claude the structure to stay in bounds.

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
- **Kickoff planning** — `/vibe-planning` walks a new project through five gated stages, one question at a time, and leaves five short documents in `docs/planning/`. Built for developers who have to do the planning too.
- **Design before build** — `/vibe-design` turns the landing page and key screens into self-contained HTML you open in a browser and approve *before* implementation starts.
- **Zero dependencies** — pure Python + vanilla JS. No npm, no pip, no build step.

---

## Install

> **Note on naming.** The project was renamed from *Vibe Harness* to *Vibe Engineering*.
> The skill directory (`~/.claude/skills/vibe-harness/`), the `/vibe-harness` command, and the
> per-project `vibe-harness/` data directory keep their old names for backward compatibility —
> existing installs and registered projects keep working untouched. Old GitHub URLs redirect.

### 1. Clone

```bash
git clone https://github.com/hoarchi/vibe-engineering.git
cd vibe-engineering
```

### 2. Setup

```bash
python3 scripts/setup.py
```

This does four things:

1. Copies `server.py`, `vibe_runtime.py`, `worker.py`, `kanban.html`, `SKILL.md` → `~/.claude/skills/vibe-harness/`
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

Downloads the latest server, Worker runtime, UI, skill, and setup files from GitHub, then restarts the server. No repo pull needed.

**First time upgrading from an older install?**

Older installs didn't copy `setup.py` to `~/.claude/skills/vibe-harness/`, so the command above will say "No such file." Bootstrap it once:

```bash
mkdir -p ~/.claude/skills/vibe-harness
curl -sL https://raw.githubusercontent.com/hoarchi/vibe-engineering/main/scripts/setup.py \
  -o ~/.claude/skills/vibe-harness/setup.py
python3 ~/.claude/skills/vibe-harness/setup.py upgrade
```

After this one-time bootstrap, every future update is just the single `setup.py upgrade` command at the top.

---

## Uninstall

```bash
python3 scripts/setup.py uninstall
```

---

## Using It as a Harness

The board is useful out of the box. But the real leverage comes from using the full harness pattern.

### Starting a brand-new project

Run `/vibe-planning`. It asks one question at a time through five gates — north star,
requirements, user stories, screens, technical decisions — and leaves the five artifacts in
`docs/planning/`. Stage 4 hands off to `/vibe-design`, so you look at the landing page and key
screens in a browser before a line of it gets built. At the end it proposes the implementation
tasks for the board, and the normal phase/kanban loop below takes over.

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
  vibe_runtime.py    ← atomic lease, policy, credentials, test gate primitives
  worker.py          ← local polling Worker + isolated Git worktree execution
  kanban.html        ← Single-file vanilla JS UI
  projects.json      ← Project registry (which boards exist)
  server.log         ← Server stdout

{project}/vibe-harness/
  kanban.json              ← Active tasks
  worker.json              ← Tracked Worker/test/approval policy
  runtime.json             ← Ignored current leases and executions
  runs.json                ← Append-only terminal run usage/history
  archive/
    2026-03.json           ← Monthly archives (git-tracked)
    2026-04.json

~/Library/LaunchAgents/com.vibe-harness.server.plist   ← Auto-start
~/.claude/hooks/vibe-harness-review.sh                 ← Review hook
~/.claude/skills/vibe-harness/runtime-locks/            ← Atomic per-project locks
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
| `/vibe-planning` | Kickoff planning — five gated stages into `docs/planning/` |
| `/vibe-design` | Landing + key screens as HTML, checked in a browser |
| `python3 ~/.claude/skills/vibe-harness/server.py sync` | Push configured remote snapshots now |

---

## Managed Worker Runtime

Vibe Engineering can optionally claim `todo` tasks and run a configured agent in an
isolated Git worktree. This layer is opt-in: installing it does not start an
agent or execute a command.

1. Add `vibe-harness/worker.json` using [the Worker protocol](docs/WORKER_PROTOCOL.md).
2. Configure a real, shell-free adapter argv and test-gate commands.
3. Start one Worker:

```bash
python3 ~/.claude/skills/vibe-harness/worker.py impactbook_ai \
  --project-root "$PWD" --agent codex
```

Run one specific task once:

```bash
python3 ~/.claude/skills/vibe-harness/worker.py impactbook_ai \
  --project-root "$PWD" --agent codex --task-id 243 --once
```

The Worker creates a unique `run_id`, claims one atomic lease, sends heartbeats,
and submits the resulting worktree to the server. The server—not the model—runs
the configured test gate. A managed task cannot become `done` unless that gate
passes. Failed runs return to `todo` until `max_attempts` is exhausted, then move
to `review`. Categories requiring human approval also stop in `review`.

Runtime API:

| Endpoint | Purpose |
|---|---|
| `GET /api/{project}/runtime` | Sanitized active leases, runs, and policy |
| `POST /api/{project}/worker/claim` | Atomic todo claim |
| `POST /api/{project}/worker/heartbeat` | Extend lease |
| `POST /api/{project}/worker/complete` | Execute test gate and finish |
| `POST /api/{project}/worker/fail` | Record failure and retry/review |
| `POST /api/{project}/runtime/action` | Approve, reject, retry, or cancel |

Lease tokens are stored only as hashes and never included in snapshots. Remote
approval uses five-second authenticated polling over the existing sync endpoint;
the localhost API remains private and no WebSocket/SSE is used.

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

### Private remote dashboards

Vibe Engineering can push read-only snapshots to a private company dashboard after
tasks, decisions, runs, or archives change. Local APIs remain bound to
`127.0.0.1`; only the configured snapshot leaves the machine.

Create `~/.claude/skills/vibe-harness/sync.json` with mode `0600`:

```json
{
  "enabled": true,
  "endpoint": "https://zest.im/api/internal/vibe-harness/sync",
  "secret": "use-a-dedicated-random-upload-secret",
  "dashboards": {
    "ax-project": ["impactbook_ai"]
  }
}
```

Each dashboard receives one bundle containing the listed registered projects.
Writes are debounced for 400 ms. Failed deliveries remain in
`sync-pending.json` and retry after the next write or server restart.

```bash
chmod 600 ~/.claude/skills/vibe-harness/sync.json
python3 ~/.claude/skills/vibe-harness/server.py sync
```

For a secret-safe interactive setup instead of editing JSON directly:

```bash
python3 ~/.claude/skills/vibe-harness/server.py configure-sync \
  https://zest.im/api/internal/vibe-harness/sync ax-project impactbook_ai
```

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
