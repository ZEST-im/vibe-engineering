---
name: vibekanban
description: VibeKanban — Dev progress kanban board for Claude Code. Multi-project support, task tracking with code change stats + web UI.
user-invocable: true
---

# VibeKanban — Dev Progress Kanban Board

Track development progress as a kanban board while coding with Claude Code.
One server (localhost:4242) serves multiple projects with tab-based switching.

## Core Principles

1. **Multi-project**: Single server, multiple projects via tabs
2. **Auto-tracking**: `in_progress` → `started_at`, `done` → `completed_at` auto-set
3. **Code change stats**: `lines_added`, `lines_removed` measured via `git diff`
4. **Work reports**: `details` field stores per-task reports (changed files, decisions)
5. **Progress sync**: Import existing records from PROGRESS.md / devlog files

## Setup (First Time)

After installing the plugin, run the setup script to copy server files:

```bash
# Copy server files to ~/.claude/kanban/
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py
```

Or manually:
```bash
mkdir -p ~/.claude/kanban
cp ${CLAUDE_PLUGIN_ROOT}/scripts/server.py ~/.claude/kanban/server.py
cp ${CLAUDE_PLUGIN_ROOT}/scripts/kanban.html ~/.claude/kanban/kanban.html
```

## File Locations

```
~/.claude/kanban/server.py           ← Web server (global, shared across projects)
~/.claude/kanban/kanban.html         ← Web UI (loaded by server)
~/.claude/kanban/projects.json       ← Project registry
{project}/vibekanban/kanban.db       ← Per-project SQLite DB
```

## Commands

| Command | Description |
|---|---|
| `/vibekanban` | Show current status summary |
| `/vibekanban serve` | Start server + register current project (`localhost:4242/kanban`) |
| `/vibekanban stop` | Stop server |
| `/vibekanban add <title>` | Add new task (default: todo) |
| `/vibekanban start <id or title>` | Move to in_progress |
| `/vibekanban done <id or title>` | Move to done |
| `/vibekanban move <id> <status>` | Change status |
| `/vibekanban update <id>` | Update task details |
| `/vibekanban list [status]` | List tasks |
| `/vibekanban sync` | Sync tasks from PROGRESS.md / devlog |
| `/vibekanban report` | Today's completed work summary |

## Server

### Start (auto-register current project)
```bash
# Check if server is already running
lsof -ti:4242

# Register project (if server is already running)
python3 ~/.claude/kanban/server.py register <project_key> <display_name> <db_path>

# Start server with auto-registration
python3 ~/.claude/kanban/server.py "$(pwd)/vibekanban/kanban.db" 4242 "ProjectName" &

# Start server only (for already-registered projects)
python3 ~/.claude/kanban/server.py serve 4242 &
```

### Stop
```bash
lsof -ti:4242 | xargs kill 2>/dev/null
```

## API

### Project List
```bash
curl http://localhost:4242/api/projects
```

### Register Project
```bash
curl -X POST http://localhost:4242/api/projects \
  -H 'Content-Type: application/json' \
  -d '{"key":"my_project","name":"My Project","db_path":"/path/to/vibekanban/kanban.db"}'
```

### Task API
```bash
# List
curl http://localhost:4242/api/{project_key}/tasks

# Create
curl -X POST http://localhost:4242/api/{project_key}/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"Task","status":"todo","priority":"high"}'

# Update
curl -X PUT http://localhost:4242/api/{project_key}/tasks/{id} \
  -H 'Content-Type: application/json' \
  -d '{"status":"done","lines_added":150}'

# Bulk create
curl -X POST http://localhost:4242/api/{project_key}/tasks/bulk \
  -H 'Content-Type: application/json' \
  -d '{"tasks":[{"title":"Task 1","status":"done"},{"title":"Task 2","status":"todo"}]}'
```

## Auto-Recording Rules (Claude MUST follow)

VibeKanban replaces PROGRESS.md. All dev progress goes into the kanban.

### On serve
1. Check if server is running (`lsof -ti:4242`)
2. If not → start server + register current project
3. If yes → register project only (`POST /api/projects`)
4. Print URL for browser

### When user requests work
1. If task not in kanban → add as `todo`
2. On start → change to `in_progress` (`started_at` auto-set)
3. If another task was `in_progress` → move it back to `todo`

### On task completion
1. Measure code changes via `git diff --numstat` → record `lines_added`, `lines_removed`
2. Write work report in `details`:
   - Changed files and what changed
   - Key technical decisions and reasoning
   - Follow-up tasks or notes
3. Move task to `done` (`completed_at` auto-set)

### On qq (daily wrap-up)
1. Print kanban summary (today's done, in-progress, tomorrow's tasks)
2. Update in-progress task details with interim report
3. Do NOT update PROGRESS.md (kanban replaces it)

### Key Rules
- PROGRESS.md is "external-sharing snapshot" only. Daily records go to kanban only.
- Every task MUST have a `category` (backend, frontend, infra, data, docs, qa, etc.)
- Write `details` for completed tasks thoroughly — viewable in web UI

## Web UI Features

- **Project tabs**: Switch between projects in header (URL hash persisted)
- **Kanban view**: 4 active columns (Backlog, To Do, In Progress, Review) — drag & drop, cards show description + edit/delete buttons
- **List view**: Spreadsheet-style table, all tasks (including Done) with inline editing
- **Done zone**: 3 tabs — by Date / Category / Phase grouping
- **Done card rules**: No edit/delete on Done cards in kanban — only via detail panel
- **Detail panel**: Right slide-in, shows report, schedule, code change stats
- **Dark/Light mode**: Toggle button + localStorage persistence
- **Save indicator**: Toast notification on inline edits
- **Target date**: D-day countdown, overdue=red, soon=orange
- **Code changes**: +/- bar graph
- **Completion date**: "260314" YYMMDD format
- **Drop to Done**: Drag card to Done zone to auto-complete
- **Keyboard**: `n`=new task, `Esc`=close
- **Auto-refresh**: 5 seconds
- **Phase field**: Group completed tasks by Phase (e.g., Phase 1, Phase 2)

## Notes

- Single server serves all projects (port 4242)
- `~/.claude/kanban/projects.json` stores project list
- Each project's `vibekanban/` directory can be included in git
- Server is localhost only (127.0.0.1)
