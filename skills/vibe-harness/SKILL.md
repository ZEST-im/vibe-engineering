---
name: vibe-harness
description: Vibe-Harness — Dev progress kanban board for Claude Code. Multi-project support, task tracking with code change stats + web UI.
user-invocable: true
---

# Vibe-Harness — Dev Progress Kanban Board

Track development progress as a kanban board while coding with Claude Code.
One server (localhost:4242) serves multiple projects with tab-based switching.

## Core Principles

1. **Multi-project**: Single server, multiple projects via tabs
2. **Auto-tracking**: `in_progress` → `started_at`, `done` → `completed_at` auto-set
3. **Code change stats**: `lines_added`, `lines_removed` measured via `git diff`
4. **Work reports**: `details` field stores per-task reports (changed files, decisions)
5. **Git-friendly**: JSON storage — diffs, merges, and code review all work naturally
6. **Archive**: Done tasks archived to monthly files, always visible in dashboard

## Setup (First Time)

After installing the plugin, run the setup script to copy server files and install auto-start:

```bash
# Copy server files + install launchd auto-start
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py
```

This will:
1. Copy `server.py`, `kanban.html`, `SKILL.md` to `~/.claude/skills/vibe-harness/`
2. Install a macOS LaunchAgent (`com.vibe-harness.server`) that auto-starts the server on login
3. Register a code review hook in `~/.claude/settings.json`

To uninstall auto-start:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py uninstall
```

Or manually:
```bash
mkdir -p ~/.claude/skills/vibe-harness
cp ${CLAUDE_PLUGIN_ROOT}/scripts/server.py ~/.claude/skills/vibe-harness/server.py
cp ${CLAUDE_PLUGIN_ROOT}/scripts/kanban.html ~/.claude/skills/vibe-harness/kanban.html
```

## File Locations

```
~/.claude/skills/vibe-harness/server.py           ← Web server (global, shared across projects)
~/.claude/skills/vibe-harness/kanban.html         ← Web UI (loaded by server)
~/.claude/skills/vibe-harness/projects.json       ← Project registry
{project}/vibe-harness/kanban.json                ← Per-project task data (git-tracked)
{project}/vibe-harness/archive/YYYY-MM.json       ← Monthly archives (git-tracked)
```

## Commands

| Command | Description |
|---|---|
| `/vibe-harness` | Show current status summary |
| `/vibe-harness serve` | Start server + register current project (`localhost:4242/kanban`) |
| `/vibe-harness stop` | Stop server |
| `/vibe-harness add <title>` | Add new task (default: todo) |
| `/vibe-harness start <id or title>` | Move to in_progress |
| `/vibe-harness done <id or title>` | Move to done |
| `/vibe-harness move <id> <status>` | Change status |
| `/vibe-harness update <id>` | Update task details |
| `/vibe-harness list [status]` | List tasks |
| `/vibe-harness sync` | Sync tasks from PROGRESS.md / devlog |
| `/vibe-harness report` | Today's completed work summary |
| `/vibe-harness export` | Export all tasks to JSON file (`vibe-harness/kanban-export.json`) |
| `/vibe-harness import` | Import tasks from JSON file (merge mode: keeps newer version) |
| `/vibe-harness import replace` | Import tasks from JSON file (replace mode: overwrite all) |
| `/vibe-harness archive` | Archive done tasks to monthly files |
| `/vibe-harness phase` | Show current phase status + task summary per phase |
| `/vibe-harness phase init` | Create PHASES.md + docs/CURRENT_PHASE.md templates |
| `/vibe-harness phase done` | Complete current phase — runs automated pre-check, updates PHASES.md |
| `/vibe-harness phase next <name>` | Transition to next phase (runs checklist first) |
| `/vibe-harness phase check` | Run automated phase completion check (non-destructive) |
| `/vibe-harness decide "<title>"` | Record a technical decision in the Decision Log |

## Server

### Start (auto-register current project)
```bash
# Check if server is already running
lsof -ti:4242

# Register project (if server is already running)
python3 ~/.claude/skills/vibe-harness/server.py register <project_key> <display_name> <kanban_dir>

# Start server with auto-registration (legacy db_path also works)
python3 ~/.claude/skills/vibe-harness/server.py "$(pwd)/vibe-harness" 4242 "ProjectName" &

# Start server only (for already-registered projects)
python3 ~/.claude/skills/vibe-harness/server.py serve 4242 &
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

### Velocity & Stats API
```bash
curl http://localhost:4242/api/{project_key}/velocity
# Returns: phase burndown, daily trend, category token breakdown, cost estimate
```

## Session Start (Claude MUST follow)

세션 시작 시 반드시 현재 미션 컨텍스트를 확인한다:

```bash
curl http://localhost:4242/api/{project_key}/context
```

응답에서 다음을 파악하고 작업을 시작한다:
- `phase` — 현재 Phase 이름
- `scope` — 이번 Phase의 작업 범위
- `in_progress` — 이미 진행 중인 태스크 (있으면 이어서 진행)
- `do_not_touch` — 절대 건드리면 안 되는 영역 (**이 목록을 반드시 준수**)
- `checklist.items` — 남은 완료 체크리스트

컨텍스트가 없거나 서버가 응답 안 하면 → 서버 시작 후 재시도.

**웹 UI**: 사용자가 브라우저에서 `localhost:4242/kanban`을 열고 **🎯 Mission** 탭을 클릭하면 같은 정보를 시각적으로 확인할 수 있다.

---

## Auto-Recording Rules (Claude MUST follow)

Vibe-Harness replaces PROGRESS.md. All dev progress goes into the kanban.

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
2. Estimate token usage for this task → record `tokens_used`:
   - Use conversation turn count and diff size as the signal:
     - Count tool calls made during the task (Read, Edit, Bash calls each ≈ 2K–5K)
     - Count lines changed in git diff (each line ≈ 10–20 tokens)
     - Rough formula: `(tool_calls × 3000) + (lines_changed × 15) + (conversation_turns × 800)`
   - Quick bands: tiny (≤5 tool calls, <30 diff lines) ≈ 20K; small ≈ 50K; medium ≈ 150K; large (>30 tool calls) ≈ 400K
   - Record as integer (e.g. `50000`). Accuracy within 2× is acceptable.
3. Write work report in `details`:
   - Changed files and what changed
   - Key technical decisions and reasoning
   - Follow-up tasks or notes
4. Move task to `done` (`completed_at` auto-set)

### When recording a decision (`/vibe-harness decide`)
1. Capture: title (what was decided), why (reasoning), revisit condition, linked task ID
2. POST to `/api/{project_key}/decisions`
3. Example: `"왜 이렇게 했지?" → Log 탭에서 검색`

### On qq (daily wrap-up)
1. Print kanban summary (today's done, in-progress, tomorrow's tasks)
2. Update in-progress task details with interim report
3. **Code review**: Run review on all uncommitted + unpushed changes (see "Code Review" section)
4. Do NOT update PROGRESS.md (kanban replaces it)

### ⚠️ Code Review (MANDATORY — Claude MUST follow)

**Claude MUST perform a code review immediately after executing `git push` or `gh pr create`.**
This is NOT optional. Do NOT skip to the next task. Do NOT ask the user if they want a review.
Just do it — every single time.

#### Trigger conditions (ANY of these = review MUST happen)
1. **You just ran `git push`** → review NOW, before doing anything else
2. **You just ran `gh pr create`** → review NOW, before doing anything else
3. **User says `qq`** (daily wrap-up) → review all uncommitted + unpushed changes
4. **User says `/vibe-harness review`** → review on demand

#### Step-by-step procedure (follow exactly)

**Step 1: Get the diff**
```bash
# After git push:
git diff @{push}..HEAD 2>/dev/null || git diff origin/$(git branch --show-current)..HEAD

# After gh pr create:
git diff main..HEAD

# After qq:
git diff HEAD
```

**Step 2: Review the diff — focus on CRITICAL and HIGH only**

Keep it lightweight. Do NOT nitpick MEDIUM/LOW issues on every push.

- 🔴 **CRITICAL**: Security issues (secrets, injection, auth bypass, XSS)
- 🟡 **HIGH**: Bug risks (null refs, race conditions, missing error handling, data loss)

Skip MEDIUM (code quality, naming, dead code) — these can wait for dedicated refactoring sessions.

**Step 3: Create review tasks for CRITICAL/HIGH findings**

For each CRITICAL or HIGH finding, create a **separate kanban task** with `status: "review"` and `category: "review"`:
```bash
curl -X POST http://localhost:4242/api/{project}/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "🔴 SQL injection in search_handler",
    "description": "Use parameterized query instead of string interpolation in search_handler.py:42",
    "status": "review",
    "category": "review",
    "priority": "high",
    "created_by": "claude-review"
  }'
```

Title format: `{emoji} {brief description}`
- 🔴 for CRITICAL
- 🟡 for HIGH

**Step 4: Print summary to user**
```
📋 Code Review
━━━━━━━━━━━━━━
🔴 CRITICAL: (count)
🟡 HIGH: (count)
━━━━━━━━━━━━━━
Created (N) review tasks in kanban.
```

If no CRITICAL/HIGH found:
```
📋 Code Review — ✅ No critical/high issues found.
```

**Step 5: If CRITICAL found → warn prominently**
```
⚠️ CRITICAL SECURITY ISSUE — fix before merging
→ (description)
```

#### Web UI
- Review tasks appear in the "Review" column of the kanban board
- Resolve by moving to `done` after fixing

### Key Rules
- PROGRESS.md is "external-sharing snapshot" only. Daily records go to kanban only.
- Every task MUST have a `category` (backend, frontend, infra, data, docs, qa, etc.)
- Write `details` for completed tasks thoroughly — viewable in web UI
- Record `tokens_used` (estimated integer) when completing tasks — shown in Done cards and detail panel

## Phase Management

Vibe-Harness includes a built-in phase management system for structured project progression.

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
## Done when:
- [ ] Item 1
- [ ] Item 2
## Do NOT touch:
<!-- SCOPE_LOCK_BEGIN -->
- billing/
- auth/
- app/models/user.rb
<!-- SCOPE_LOCK_END -->
```

The `SCOPE_LOCK_BEGIN` / `SCOPE_LOCK_END` block is machine-readable: the `PreToolUse` scope guard hook reads it automatically and **blocks** any Edit or Write to matching files or directories. Patterns are prefix-matched against the relative path from the project root. No need to list every file — `billing/` covers the entire directory.

### Phase Rules (Claude MUST follow)

1. **Read `PHASES.md` and `docs/CURRENT_PHASE.md` at session start.**
2. **Never advance to the next Phase without explicit user instruction.**
3. **Update `PHASES.md` on Phase completion** (date, achievements, test count).
4. **Strictly respect `docs/CURRENT_PHASE.md`'s `Do NOT touch` list.**
5. **Phase completion criteria**: All items in `Done when` checklist must be checked. Partial = 🚧.

### `phase check` / `phase done` — Automated Pre-check

Before marking a phase done, run the automated check:

```bash
curl http://localhost:4242/api/{project}/phase-check
```

Response:
```json
{
  "ready": false,
  "phase": "PHASE_MVP01",
  "issues": ["2 in_progress tasks", "1 Done when item unchecked"],
  "warnings": ["PHASES.md not found"],
  "kanban": {"in_progress": 2, "review": 0, "done": 12},
  "checklist": {"total": 5, "unchecked": 1}
}
```

**Only proceed with phase transition when `"ready": true`.**

`/vibe-harness phase done` runs this check automatically before updating PHASES.md.

### Phase Transition Checklist

| Item | Verify |
|------|--------|
| Tests | All tests for current Phase features pass |
| Docs | `PHASES.md` updated with completion details + test count |
| Tech debt | Any debt carried forward is noted in PENDING Phase |
| Vibe-Harness | All tasks for the Phase are `done` |

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
- **Done zone**: 3 tabs — by Date / Category / Phase grouping (includes archived tasks)
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

## Multi-User Rules

Vibe-Harness uses JSON files for storage — fully git-friendly.

### Storage — Git-Tracked

- `vibe-harness/kanban.json` — active tasks (todo, in_progress, review + recent done)
- `vibe-harness/archive/YYYY-MM.json` — monthly archives of completed tasks
- All files are text-based JSON — git diff, merge, and conflict resolution work naturally
- Commit these files along with your code

### Sharing Workflow

```
1. Work normally — kanban.json is updated as you work
2. git add vibe-harness/ → commit with your code changes
3. On pull — if merge conflict in kanban.json, resolve like any JSON (per-task)
4. Archive periodically: /vibe-harness archive → moves done tasks to archive/YYYY-MM.json
```

### User Identification

- Tasks have `created_by` and `assigned_to` fields
- Claude auto-sets `created_by` from `git config user.name` on task creation
- `in_progress` limit (1 task) applies **per user**, not globally
- When starting a task, set `assigned_to` to current user

### Export/Import API

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

# Archive done tasks to monthly files
curl -X POST http://localhost:4242/api/{project}/archive
```

### Merge Strategy

| Mode | Behavior |
|------|----------|
| `merge` (default) | New tasks inserted. Existing tasks (same id): keep whichever has newer `updated_at` |
| `replace` | Delete all existing tasks, insert imported tasks |

### Claude Auto-Recording Rules (Multi-User)

1. On task creation → set `created_by` to `git config user.name`
2. On `/vibe-harness start` → set `assigned_to` to current user
3. On `in_progress` enforcement → only move **own** tasks back to `todo`, not others'
4. Periodically archive done tasks (`/vibe-harness archive`) to keep kanban.json small

## Notes

- Single server serves all projects (port 4242)
- `~/.claude/skills/vibe-harness/projects.json` stores project list
- Each project's `vibe-harness/` directory should be git-tracked (kanban.json + archive/)
- Server is localhost only (127.0.0.1)
- JSON writes use atomic file replacement (write to .tmp, then rename) for safety
