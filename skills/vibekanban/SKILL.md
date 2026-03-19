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

After installing the plugin, run the setup script to copy server files and install auto-start:

```bash
# Copy server files + install launchd auto-start
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py
```

This will:
1. Copy `server.py` and `kanban.html` to `~/.claude/kanban/`
2. Install a macOS LaunchAgent (`com.vibekanban.server`) that auto-starts the server on login

To uninstall auto-start:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py uninstall
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
| `/vibekanban phase` | Show current phase status + task summary per phase |
| `/vibekanban phase init` | Create PHASES.md + docs/CURRENT_PHASE.md templates |
| `/vibekanban phase done` | Complete current phase (update PHASES.md, verify all tasks done) |
| `/vibekanban phase next <name>` | Transition to next phase (runs checklist first) |

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
3. **Code review**: Run security + quality review on all changes since last commit
   - Review items stored in task's `review` field as JSON array
   - Format: `[{"text": "리뷰 내용", "resolved": false}, ...]`
   - Web UI shows each item with 해결/미해결 radio buttons
4. Do NOT update PROGRESS.md (kanban replaces it)

### Code Review on Task Completion
When moving a task to `done` or during `qq`, perform a code review:
1. Run `git diff` to see all changes for the task
2. Check for:
   - Security issues (OWASP top 10, secrets, injection)
   - Code quality (unused imports, dead code, error handling)
   - Architecture concerns (coupling, abstraction, naming)
3. Store review findings in `review` field as JSON:
   ```json
   [
     {"text": "SQL injection risk in search_handler: use parameterized query", "resolved": false},
     {"text": "Missing error handling for API timeout in fetch_data()", "resolved": false},
     {"text": "Good: proper input validation on user registration", "resolved": true}
   ]
   ```
4. Update task via API:
   ```bash
   curl -X PUT http://localhost:4242/api/{project}/tasks/{id} \
     -H 'Content-Type: application/json' \
     -d '{"review": "[{\"text\":\"...\",\"resolved\":false}]"}'
   ```
5. Review badge appears on kanban cards (green ✓ = all resolved, orange = N unresolved)
6. Detail panel shows full review with interactive 해결/미해결 toggles

### Key Rules
- PROGRESS.md is "external-sharing snapshot" only. Daily records go to kanban only.
- Every task MUST have a `category` (backend, frontend, infra, data, docs, qa, etc.)
- Write `details` for completed tasks thoroughly — viewable in web UI

## Phase Management

VibeKanban includes a built-in phase management system for structured project progression.

### Phase Naming Convention

```
PHASE_{PURPOSE}{NN}
```

| Prefix | Focus | Transition Condition |
|--------|-------|---------------------|
| `SEED` | Initial structure, boilerplate, DB schema | Basic structure + data loading done |
| `MVP`  | Core features only — prove it works | Demoable to users |
| `PMF`  | User feedback-driven iteration | Real user feedback collection started |
| `SCALE`| Performance, architecture cleanup, AI features | Traffic/data bottleneck detected |
| `GTM`  | Launch, marketing integration | Product stabilized |

Example: `PHASE_MVP01`, `PHASE_PMF02`

### Required Files (per project)

**`PHASES.md`** — Master plan (all phases + completion history)
```
## PHASE_MVP01 ✅ DONE (2026-03-01)
> One-line summary

- Completed item 1
- Completed item 2
- N tests

## PHASE_MVP02 🚧 IN PROGRESS
> One-line summary

- [x] Completed item
- [ ] Pending item

## PHASE_PMF01 ⏳ PENDING
> One-line summary
```

**`docs/CURRENT_PHASE.md`** — Current session scope (keep short)
```
## Now: PHASE_MVP02
## Scope: [features/files]
## Done when: [checklist]
## Do NOT touch: [out-of-scope list]
```

### Phase Rules (Claude MUST follow)

1. **Read `PHASES.md` and `docs/CURRENT_PHASE.md` at session start.**
2. **Never advance to the next Phase without explicit user instruction.**
3. **Update `PHASES.md` on Phase completion** (date, achievements, test count).
4. **Strictly respect `docs/CURRENT_PHASE.md`'s `Do NOT touch` list.**
5. **Phase completion criteria**: All items in `Done when` checklist must be checked. Partial = 🚧.

### Phase Transition Checklist

| Item | Verify |
|------|--------|
| Tests | All tests for current Phase features pass |
| Docs | `PHASES.md` updated with completion details + test count |
| Tech debt | Any debt carried forward is noted in PENDING Phase |
| VibeKanban | All tasks for the Phase are `done` |

### Coding Style per Phase

| Phase | Test Coverage | Refactoring | Logging |
|-------|--------------|-------------|---------|
| SEED  | None OK      | No          | No      |
| MVP   | Critical paths only | No   | Minimal |
| PMF   | Feature-level | Light      | Feature flags + metrics |
| SCALE | Full         | Yes         | Full    |

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
