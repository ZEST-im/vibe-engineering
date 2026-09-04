# Local HTTP API and Web UI

> Reference for the `vibe-harness` skill. Load when you need it — not at session start.

## Web UI Features

The Board UI is served by the optional local server. When it's running:

- **Project tabs**: Switch between projects in header (URL hash persisted)
- **Kanban view**: 4 active columns (Backlog, To Do, In Progress, Review) — drag & drop
- **List view**: Spreadsheet-style table, all tasks (including Done) with inline editing
- **Done zone**: 3 tabs — by Date / Category / Phase grouping (includes archived tasks)
- **Detail panel**: Right slide-in, shows report, schedule, code change stats
- **Dark/Light mode**: Toggle button + localStorage persistence
- **Target date**: D-day countdown, overdue=red, soon=orange
- **Code changes**: +/- bar graph
- **Drop to Done**: Drag card to Done zone to auto-complete
- **Keyboard**: `n`=new task, `Esc`=close
- **Auto-refresh**: 5 seconds
- **Mission / Log / Stats tabs**: visual surface of the same data in kanban.json + decisions.json

## Optional Local API

The server at `localhost:4242` provides an HTTP API that reads and writes the same JSON files described above. Use it when:

- The server happens to be running already and an API call is shorter than a JSON edit.
- You want the Board UI to reflect a change immediately without a page refresh.
- A teammate is using the UI concurrently and you want their view to update via the auto-refresh poll.

Do **not** start the server just to use the API. If the server is down, edit the JSON directly.

### Start (only when you actually want the Board UI)

```bash
# Check if server is already running
lsof -ti:4242

# Start server only (for already-registered projects)
python3 ~/.claude/skills/vibe-harness/server.py serve 4242 &

# Start server with auto-registration (legacy db_path also works)
python3 ~/.claude/skills/vibe-harness/server.py "$(pwd)/vibe-harness" 4242 "ProjectName" &

# Register a project against an already-running server
python3 ~/.claude/skills/vibe-harness/server.py register <project_key> <display_name> <kanban_dir>
```

### Stop
```bash
lsof -ti:4242 | xargs kill 2>/dev/null
```

### Project List
```bash
curl http://localhost:4242/api/projects
```

### Register Project
```bash
curl -X POST http://localhost:4242/api/projects \
  -H 'Content-Type: application/json' \
  -d '{"key":"my_project","name":"My Project","kanban_dir":"/path/to/vibe-harness"}'
```

### Task API
```bash
# List (returns active + archived tasks)
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

# Search archived history, decisions and live tasks — returns snippets, not files
curl -G http://localhost:4242/api/{project_key}/search \
  --data-urlencode 'q=왜 이렇게 결정했나' --data-urlencode 'limit=5'
#   → {"query":…, "total":N, "hits":[{source, id, title, phase, date, fields, snippet}]}
#
# Archiving made session start cheap by *not reading* history. That left the history
# unreachable: answering "why did we decide this?" meant loading whole files again.
# Search returns the matching span only, so the cost is paid per question rather than
# per session. /context stays as small as it was — search is never embedded in it.
#
# An empty q is refused rather than dumping everything, `total` reports the real count
# even when `limit` truncates, and one record yields one hit no matter how many of its
# fields matched.

# Archive done tasks to monthly files
curl -X POST http://localhost:4242/api/{project_key}/archive
```

### Decision Log API
```bash
# List decisions
curl http://localhost:4242/api/{project_key}/decisions

# Record a decision
curl -X POST http://localhost:4242/api/{project_key}/decisions \
  -H 'Content-Type: application/json' \
  -d '{"title":"SQLite WAL 유지","why":"동시 사용자 3명 이하면 충분","revisit":"동시 접속 10명 초과 시","phase":"PHASE_PMF01"}'
```

### Context / Velocity / Phase-Check API
```bash
# Same data as reading docs/CURRENT_PHASE.md + kanban.json, packaged for the UI
curl http://localhost:4242/api/{project_key}/context

# Phase burndown, daily trend, category token breakdown, cost estimate
curl http://localhost:4242/api/{project_key}/velocity

# Automated phase completion pre-check
curl http://localhost:4242/api/{project_key}/phase-check

# Agent run usage log (append-only, agent-agnostic)
curl http://localhost:4242/api/{project_key}/runs              # list (optionally ?task_id=N)
curl -X POST http://localhost:4242/api/{project_key}/runs \
  -H 'Content-Type: application/json' \
  -d '{"task_id":6,"agent":"codex","model":"gpt-5-codex","tokens":297469,"time_seconds":737,"commit":"017b446"}'
  # appends to runs.json AND syncs the task's tokens_used to the sum of its runs
```

### Export / Import API
```bash
# Export all tasks (active + archived) to JSON
curl http://localhost:4242/api/{project}/export > vibe-harness/kanban-export.json

# Import with merge (keeps newer version by updated_at)
curl -X POST http://localhost:4242/api/{project}/import \
  -H 'Content-Type: application/json' \
  -d @vibe-harness/kanban-export.json

# Import with replace (overwrite all tasks)
curl -X POST http://localhost:4242/api/{project}/import \
  -H 'Content-Type: application/json' \
  -d '{"mode":"replace","tasks":[...]}'
```

### Merge Strategy

| Mode | Behavior |
|------|----------|
| `merge` (default) | New tasks inserted. Existing tasks (same id): keep whichever has newer `updated_at` |
| `replace` | Delete all existing tasks, insert imported tasks |
