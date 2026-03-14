# VibeKanban

Dev progress kanban board for [Claude Code](https://claude.ai/claude-code).
Track tasks, code changes, and work reports — all from your terminal.

### Kanban View (Dark)
![Kanban Dark](docs/screenshot-kanban-dark.png)

### Kanban View (Light)
![Kanban Light](docs/screenshot-kanban-light.png)

### List View
![List View](docs/screenshot-list.png)

### Detail Panel
![Detail Panel](docs/screenshot-detail.png)

## Features

- **Multi-project** — One server, multiple projects via tabs
- **Auto-tracking** — `started_at` / `completed_at` set automatically on status change
- **Code change stats** — `lines_added`, `lines_removed` from `git diff`
- **Work reports** — Per-task details (changed files, decisions, follow-ups)
- **Kanban + List views** — Drag & drop kanban or spreadsheet-style inline editing
- **Done grouping** — By date, category, or phase
- **Dark / Light mode** — Toggle with localStorage persistence
- **Progress sync** — Import from existing PROGRESS.md / devlog files
- **Zero dependencies** — Pure Python + vanilla JS. No npm, no build step.

## Install

### As a Claude Code Plugin (recommended)

```bash
claude plugin install @hoarchi/vibekanban
```

Then run the setup to copy server files:

```bash
/vibekanban setup
```

Or manually:

```bash
mkdir -p ~/.claude/kanban
cp ~/.claude/plugins/cache/vibekanban/scripts/server.py ~/.claude/kanban/
cp ~/.claude/plugins/cache/vibekanban/scripts/kanban.html ~/.claude/kanban/
```

### Manual Install

```bash
git clone https://github.com/hoarchi/vibekanban.git
mkdir -p ~/.claude/kanban
cp vibekanban/scripts/server.py ~/.claude/kanban/
cp vibekanban/scripts/kanban.html ~/.claude/kanban/
mkdir -p ~/.claude/skills
cp -r vibekanban/skills/vibekanban ~/.claude/skills/
```

## Quick Start

### 1. Start the server

```bash
python3 ~/.claude/kanban/server.py serve 4242 &
```

### 2. Register your project

```bash
python3 ~/.claude/kanban/server.py register my_project "My Project" "$(pwd)/vibekanban/kanban.db"
```

### 3. Open the board

Visit [http://localhost:4242/kanban](http://localhost:4242/kanban)

### 4. Use with Claude Code

Just tell Claude what to do. The skill automatically:
- Creates tasks when you request work
- Moves tasks to `in_progress` when starting
- Records code changes and work reports on completion
- Tracks everything in the kanban board

Or use explicit commands:

```
/vibekanban serve      → Start server + register project
/vibekanban add title  → Add a task
/vibekanban done 3     → Mark task #3 as done
/vibekanban report     → Today's summary
```

## How It Works

```
Claude Code ──(curl)──→ localhost:4242 ──(sqlite)──→ vibekanban/kanban.db
                              │
                         kanban.html
                              │
                        Your Browser
```

- **Server**: `~/.claude/kanban/server.py` — Python HTTP server, serves API + UI
- **UI**: `~/.claude/kanban/kanban.html` — Single-file vanilla JS frontend
- **DB**: `{project}/vibekanban/kanban.db` — SQLite per project
- **Registry**: `~/.claude/kanban/projects.json` — Maps project keys to DB paths

## Web UI

### Kanban View
4 active columns (Backlog, To Do, In Progress, Review) with drag & drop.
Cards show title, description, priority, category, D-day countdown, and code change bars.
Edit/delete buttons on hover (active cards only — Done cards open detail panel).

### List View
Spreadsheet-style table with ALL tasks including Done.
Inline editing — click any cell to edit, changes save automatically.

### Done Zone
Completed tasks grouped by:
- **Date** — Completion date (YYMMDD format)
- **Category** — backend, frontend, infra, etc.
- **Phase** — Phase 1, Phase 2, etc.

### Detail Panel
Click any card to open the right slide-in panel with:
- Full description and work report
- Schedule (target, started, completed, elapsed time)
- Code change stats (+/- bar graph)

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects` | List all projects |
| POST | `/api/projects` | Register a project |
| GET | `/api/{key}/tasks` | List tasks |
| POST | `/api/{key}/tasks` | Create task |
| PUT | `/api/{key}/tasks/{id}` | Update task |
| DELETE | `/api/{key}/tasks/{id}` | Delete task |
| POST | `/api/{key}/tasks/bulk` | Bulk create tasks |
| GET | `/api/{key}/stats` | Task count by status |

### Task Fields

| Field | Type | Description |
|-------|------|-------------|
| title | string | Task title (required) |
| description | string | Brief description |
| details | string | Work report (files changed, decisions, notes) |
| status | string | `backlog` / `todo` / `in_progress` / `review` / `done` |
| priority | string | `low` / `medium` / `high` |
| category | string | `backend` / `frontend` / `infra` / `data` / `docs` / `qa` |
| phase | string | Phase grouping (e.g., "Phase 1") |
| target_date | string | Target date (YYYY-MM-DD) |
| started_at | string | Auto-set when → in_progress |
| completed_at | string | Auto-set when → done |
| lines_added | int | Lines of code added |
| lines_removed | int | Lines of code removed |
| position | int | Sort order within column |

## Requirements

- Python 3.6+
- Claude Code CLI
- A modern browser

No npm. No pip install. No build step. Just Python and a browser.

## License

MIT — [Hogun Jung](https://github.com/hoarchi) / [Zest Inc.](https://zest.im)
