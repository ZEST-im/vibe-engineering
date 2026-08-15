---
name: vibe-harness
description: Vibe-Engineering — Dev progress kanban board for Claude Code. Multi-project support, task tracking with code change stats + web UI.
user-invocable: true
---

# Vibe-Engineering — Dev Progress Kanban Board

Track development progress as a kanban board while coding with Claude Code.

## Source of Truth

**The source of truth is the JSON files under each project's `vibe-harness/` directory:**

- `vibe-harness/kanban.json` — tasks (todo, in_progress, review, done)
- `vibe-harness/decisions.json` — durable technical decisions
- `vibe-harness/archive/YYYY-MM.json` — monthly archives of done tasks

The local server at `localhost:4242` is **a Board UI and a convenience wrapper around these files** — not the system of record. Anything Claude or a teammate can do via the API can also be done by editing the JSON directly, and edits land in the same files either way.

This matters because:
- The JSON files are git-tracked and travel with the code.
- The server may not be running. That is not an error condition.
- Direct edits are the most reliable way for an agent to record progress.

## Core Principles

1. **JSON-first**: kanban.json and decisions.json are authoritative; the server is optional.
2. **Multi-project**: A single optional server can host multiple projects via tabs.
3. **Auto-tracking timestamps**: `started_at` on `in_progress`, `completed_at` on `done`.
4. **Code change stats**: `lines_added`, `lines_removed` measured via `git diff`.
5. **Work reports**: `details` field stores per-task reports (changed files, decisions).
6. **Git-friendly**: JSON storage — diffs, merges, and code review all work naturally.
7. **Archive**: Done tasks archived to monthly files, always visible in dashboard.

## Setup (First Time)

After installing the plugin, run the setup script to copy server files (only needed if you want the Board UI / auto-start):

```bash
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

You can skip setup entirely if you only want to edit the JSON files directly — the kanban data still lives in `{project}/vibe-harness/kanban.json` regardless.

## File Locations

```
~/.claude/skills/vibe-harness/server.py           ← Web server (optional, shared across projects)
~/.claude/skills/vibe-harness/kanban.html         ← Web UI (loaded by server)
~/.claude/skills/vibe-harness/projects.json       ← Project registry (used by server)
{project}/vibe-harness/kanban.json                ← Per-project task data (git-tracked, authoritative)
{project}/vibe-harness/decisions.json             ← Per-project decision log (git-tracked, authoritative)
{project}/vibe-harness/archive/YYYY-MM.json       ← Monthly archives (git-tracked)
```

## Commands

| Command | Description |
|---|---|
| `/vibe-harness` | Show current status summary |
| `/vibe-harness serve` | Start the optional Board UI server (`localhost:4242/kanban`) |
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

These commands are convenience wrappers. They ultimately read and write the same JSON files an agent would edit directly.

## Shorthand Commands (user types these directly)

Three two-letter shorthands cover the daily rhythm — sync at session start (`ss`), wrap up at day end (`qq`), ship when ready (`cc`). When the user types one of these as a bare message, run the corresponding procedure.

### `ss` — sync & status

Check this repo's remote and pull everything, branches included:

1. `git fetch --all --prune --tags` — refresh remote branches/tags, prune deleted ones.
2. Fast-forward pull the current branch. Fast-forward other local tracking branches too (`git fetch origin <branch>:<branch>`). Never auto-merge a diverged branch — report it instead.
3. Report: current branch + ahead/behind vs remote, remote branch list (flag unmerged ones), uncommitted files (`git status`), and a summary of newly pulled commits if any.
4. If the pull changed harness code (`scripts/`), check whether the installed copies (`~/.claude/skills/vibe-harness/`) and any running server need updating, and tell the user.

### `qq` — daily wrap-up (no commit)

1. Print kanban summary (today's done, in-progress, tomorrow's tasks) — derived from kanban.json.
2. Update any in-progress task's `details` with an interim report; write `details` on done tasks that lack them.
3. Update phase docs only when warranted: `PHASES.md` on phase completion, `CURRENT_PHASE.md` on scope / Known Issues change.
4. **Code review** on uncommitted + unpushed changes (see Code Review section).
5. No commit, no push — `qq` is documentation only. Do NOT touch PROGRESS.md — kanban replaces it.

### `cc` — commit + push (+ deploy check)

1. Everything `qq` does (skip whatever is already clean).
2. `git add` + `git commit` — code and its related docs (kanban.json included) go in ONE commit, never split.
3. `git push origin main`.
4. If the project has CI/CD wired to push, check build/deploy status after pushing and report it. Avoid docs-only pushes on CI/CD-triggering repos.

## Session Start (Claude should follow)

At the start of a session, establish current mission context by reading the project files in this order. **Do not call the API and do not start the server just to do this.**

1. **`CURRENT_PHASE.md`** (if present — checked in `private/`, then root, then `docs/`) — current phase name, scope, `Done when` checklist, and the `Do NOT touch` block. This is the primary scope signal.
2. **`vibe-harness/kanban.json`** — check for any task with `status: "in_progress"`. If one exists, that is the active task; continue it instead of starting new work.
3. **`vibe-harness/decisions.json`** — recent durable decisions that may constrain the work.
4. **`docs/planning/01_philosophy.md`** (if present) — the project's north star, written by the `vibe-planning` skill. Its principles and the "who we are not for" section are decision constraints; when a task conflicts with them, say so rather than quietly picking a side.
5. **Optional**: if the Board UI server happens to be running already, you can hit `GET http://localhost:4242/api/{project_key}/context` for the same information in one call. Skip this step if the server is not up — do **not** spin it up just to fetch context.

From these, derive:
- Current Phase name and scope
- Existing `in_progress` task (resume) vs. new work
- The `Do NOT touch` list (the scope-guard hook also enforces this — see Phase Management below)
- Open checklist items

If no `CURRENT_PHASE.md` exists anywhere (`private/` / root / `docs/`) but the project already has kanban tasks, the session-start hook nudges you. Run `/vibe-harness phase init` to scaffold it, or ask the user how they want to scope the session before creating new tasks. Don't silently start work without a scope.

---

## Recording Work — Direct JSON Editing (default path)

The default path for an agent is to read and edit `vibe-harness/kanban.json` and `vibe-harness/decisions.json` directly. The commands and API are conveniences over the same edits.

### kanban.json shape

```json
{
  "version": 1,
  "next_id": 7,
  "tasks": [
    {
      "id": 6,
      "title": "Add scope-guard hook",
      "description": "Block edits outside CURRENT_PHASE Do NOT touch list",
      "details": "",
      "status": "in_progress",
      "priority": "medium",
      "category": "infra",
      "phase": "PHASE_MVP02",
      "target_date": null,
      "started_at": "2026-05-21T10:14:00",
      "completed_at": null,
      "lines_added": 0,
      "lines_removed": 0,
      "tokens_used": 0,
      "position": 0,
      "created_by": "hoarchi",
      "assigned_to": "hoarchi",
      "created_at": "2026-05-21T10:12:00",
      "updated_at": "2026-05-21T10:14:00"
    }
  ]
}
```

### Rules when editing kanban.json directly

- **`next_id` consistency**: When creating a new task, use the current `next_id` as the new task's `id`, then increment `next_id` by 1. Never reuse an id; never let two tasks share an id.
- **`status` enum**: One of `backlog | todo | in_progress | review | done`. Nothing else.
- **One `in_progress` at a time** (per user): Before moving a task to `in_progress`, scan tasks and move any other `in_progress` task **owned by the same user** back to `todo`. Do not touch other users' tasks.
- **Timestamps** (ISO-8601, seconds precision is fine):
  - `created_at`: set on creation, never modified.
  - `updated_at`: bump on every field change.
  - `started_at`: set when status first transitions to `in_progress`. Leave alone on subsequent transitions back into `in_progress` unless you're explicitly restarting.
  - `completed_at`: set when status transitions to `done`. Clear it if a done task is reopened.
- **Required fields on creation**: `id`, `title`, `status`, `category`, `created_at`, `updated_at`, `created_by`. Everything else can default to empty/0/null.
- **Owner fields are ALWAYS required — including direct-to-done records**: `created_by` and `assigned_to` hold the **human** user (`git config user.name`), never an agent name (`claude`, `codex`, …) — agent attribution lives in `runs.json` `agent`. When a task is recorded retroactively as `done` in one step (wrap-up style), the start-transition trigger never fires, so set `assigned_to` explicitly at that moment. An unassigned done task is a recording bug.
- **On completion (`status: "done"`)**: also record:
  - `lines_added`, `lines_removed` — from `git diff --numstat` for files changed in this task.
  - `details` — work report: changed files, key decisions, follow-ups.
  - `tokens_used` — sum of this task's runs in `runs.json` if logged, else a rough integer estimate (see Token Estimation below).
  - **Append a run to `runs.json`** — `{agent, model, tokens, time_seconds, commit, ts}` for the agent that did the work (see runs.json section). Agent-agnostic: record it whether the work was done by Codex, Claude, Gemini, or any other agent.
  - Any verification notes (tests run, manual checks) belong in `details`.
- **Atomic writes**: Write to `kanban.json.tmp` first, then rename over `kanban.json`. The server does this; agents editing directly should do the same to avoid leaving the file half-written.
- **Don't reorder the file just to reorder it.** Append new tasks; sort only via `position` if needed.

### decisions.json shape and rules

```json
{
  "version": 1,
  "next_id": 3,
  "decisions": [
    {
      "id": 2,
      "title": "...",
      "why": "...",
      "revisit": "...",
      "task_id": 6,
      "phase": "PHASE_MVP02",
      "tags": [],
      "created_at": "2026-05-21T10:30:00",
      "updated_at": "2026-05-21T10:30:00"
    }
  ]
}
```

Record a decision in `decisions.json` (not in a task's `details`) when the choice is **durable** — it will outlive the task and affect future work. Rule of thumb: would a future agent reading the codebase six months from now need to know *why* this was done? If yes, it's a decision.

- Same `next_id` / `id` discipline as kanban.json.
- `task_id` links back to the kanban task that spawned the decision (nullable).
- `revisit` should describe a concrete condition that would make this decision worth re-opening.

### runs.json shape and rules (agent run usage log)

Append-only log of **who ran what, at what cost**. Agent-agnostic — any tool (Codex, Claude Code, Gemini, Cursor, …) records into the same file. `kanban.json` stays a status board; per-run usage lives here so a single task can accumulate multiple runs from different agents without overwriting.

```json
{
  "version": 1,
  "runs": [
    {
      "task_id": 6,
      "agent": "claude",
      "model": "claude-opus-4-8",
      "tokens": 4628627,
      "input_tokens": 46438,
      "output_tokens": 79449,
      "cache_read_tokens": 4111339,
      "cache_write_tokens": 391401,
      "time_seconds": null,
      "commit": "59675cc",
      "session_id": "d87cee14-...",
      "ts": "2026-06-20T14:02:00"
    }
  ]
}
```

- **Append-only.** Add a run object; never edit or delete existing entries. No `next_id` — entries are not addressed by id.
- **Required per run**: `agent` (free string: `codex` / `claude` / `gemini` / …), `tokens` (integer), `ts` (ISO-8601).
- **Optional**: `task_id` (links to a kanban task, nullable for ad-hoc runs), `model` (specific model id), token breakdown (`input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_write_tokens`, else `null`), `time_seconds`, `commit` (git short SHA), `session_id` (for idempotent auto-collection).
- **`agent` is the recording dimension** — cost rates differ per agent/model, so always set it. Don't assume Claude.
- **Token breakdown drives accurate cost.** Claude runs are cache-dominated (cache reads cost ~10% of input), so a flat sum overstates cost ~7×. When the breakdown is present, cost is computed per-component (`COMPONENT_RATES` in server.py); otherwise it falls back to a blended flat rate on `tokens` (fine for Codex/Gemini single-number usage).
- **Atomic writes**: same `.tmp` + rename discipline as kanban.json.
- **Relationship to `tokens_used`**: when a task has runs logged here, set the task's `kanban.json` `tokens_used` to the **sum of that task's runs**. If no run is logged, `tokens_used` falls back to a rough estimate.

#### Auto-collection (PHASE_PMF03) — preferred over manual estimates

Real usage is captured automatically; you rarely set `tokens_used` by hand anymore.

- **Claude Code**: the `SessionEnd` hook (`vibe-harness-token-collector.sh`) parses the session transcript, sums real usage, and records one run via the shared recorder. Idempotent by `session_id`.
- **Codex / Gemini / any agent**: call the shared recorder directly with the agent's reported usage:
  ```bash
  python3 ~/.claude/hooks/vibe-harness-record-run.py \
    --agent codex --model gpt-5-codex --tokens 297469 \
    --time-seconds 737 --cwd "$PWD"
  ```
- The recorder resolves the project (cwd → git root → `projects.json`), the current `in_progress` task, and the git commit automatically; posts to the server if up, else appends to `runs.json` directly.

**Server path (optional convenience):** if `localhost:4242` is running:
- `GET  /api/{project}/runs` — list runs (`?task_id=N` to filter).
- `POST /api/{project}/runs` — append a run (`agent` required; breakdown/`session_id`/`commit`/etc. optional). Appends to `runs.json` **and** auto-syncs the linked task's `tokens_used`.
- The 📊 Stats tab shows per-agent and per-model token + cost breakdown.

Editing `runs.json` directly stays the canonical path — the server and recorder are just wrappers.

### When the user requests work

1. If a matching task isn't in kanban → create one as `todo` (or `in_progress` if starting immediately).
2. On start → set `status: "in_progress"`, set `started_at`, bump `updated_at`. Move any prior `in_progress` task owned by the current user back to `todo`.
3. On completion → record stats + details, set `status: "done"`, set `completed_at`, bump `updated_at`.

### Token estimation (for `tokens_used` on completion)

Prefer **actual** usage: if you logged a run in `runs.json`, set `tokens_used` to the sum of that task's runs. Estimate only as a fallback when no real number is available — accuracy within 2× is acceptable.

- Tool calls (Read/Edit/Bash) ≈ 2K–5K each
- Diff lines ≈ 10–20 tokens each
- Conversation turns ≈ 800 tokens each
- Quick bands: tiny (≤5 tool calls, <30 diff lines) ≈ 20K; small ≈ 50K; medium ≈ 150K; large (>30 tool calls) ≈ 400K

### On `qq` (daily wrap-up)

See **Shorthand Commands** above — `ss` / `qq` / `cc` procedures are defined there.

---

## ⚠️ Code Review (MANDATORY — Claude MUST follow)

**Claude MUST perform a code review immediately after executing `git push` or `gh pr create`.**
Not optional. Don't skip to the next task. Don't ask the user if they want a review. Just do it.

#### Trigger conditions (ANY of these = review MUST happen)
1. **You just ran `git push`** → review NOW
2. **You just ran `gh pr create`** → review NOW
3. **User says `qq`** → review all uncommitted + unpushed changes
4. **User says `/vibe-harness review`** → review on demand

#### Step 1: Get the diff

```bash
# After git push:
git diff @{push}..HEAD 2>/dev/null || git diff origin/$(git branch --show-current)..HEAD

# After gh pr create:
git diff main..HEAD

# After qq:
git diff HEAD
```

#### Step 2: Review the diff — focus on CRITICAL and HIGH only

- 🔴 **CRITICAL**: Security issues (secrets, injection, auth bypass, XSS)
- 🟡 **HIGH**: Bug risks (null refs, race conditions, missing error handling, data loss)

Skip MEDIUM — save those for dedicated refactoring sessions.

#### Step 3: Create review tasks in kanban.json

For each CRITICAL or HIGH finding, append a task to `kanban.json` with:
- `status: "review"`
- `category: "review"`
- `priority: "high"`
- `created_by: "claude-review"`
- Title format: `🔴 SQL injection in search_handler` or `🟡 Race condition in worker pool`

Follow the same `next_id` / timestamp rules as any other task. (If the Board UI server is up you may POST instead — same effect, same file.)

#### Step 4: Print summary

```
📋 Code Review
━━━━━━━━━━━━━━
🔴 CRITICAL: (count)
🟡 HIGH: (count)
━━━━━━━━━━━━━━
Created (N) review tasks in kanban.
```

If clean:
```
📋 Code Review — ✅ No critical/high issues found.
```

#### Step 5: If CRITICAL → warn prominently

```
⚠️ CRITICAL SECURITY ISSUE — fix before merging
→ (description)
```

Resolve review tasks by moving them to `done` once fixed.

### Key Rules
- PROGRESS.md is "external-sharing snapshot" only. Daily records live in kanban.json only.
- Every task MUST have a `category` (backend, frontend, infra, data, docs, qa, review, etc.)
- Write `details` thoroughly on completion — viewable in web UI and in git history.
- Record `tokens_used` (estimated integer) on completion.

## Phase Management

Vibe-Engineering includes a built-in phase management system for structured project progression.

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

The `SCOPE_LOCK_BEGIN` / `SCOPE_LOCK_END` block is machine-readable: the `PreToolUse` scope guard hook reads it automatically and **blocks** any Edit or Write to matching files or directories. Patterns are prefix-matched against the relative path from the project root.

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
| Vibe-Engineering | All tasks for the Phase are `done` (check kanban.json) |

The `/vibe-harness phase check` and `/vibe-harness phase done` commands automate this — they read kanban.json and the phase markdown files. If the server is up, the same check is exposed at `GET /api/{project}/phase-check` as a convenience.

### Coding Style per Phase

| Phase | Test Coverage | Refactoring | Logging |
|-------|--------------|-------------|---------|
| SEED  | None OK      | No          | No      |
| MVP   | Critical paths only | No   | Minimal |
| PMF   | Feature-level | Light      | Feature flags + metrics |
| SCALE | Full         | Yes         | Full    |

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

## Multi-User Rules

Vibe-Engineering uses JSON files for storage — fully git-friendly.

### Storage — Git-Tracked

- `vibe-harness/kanban.json` — active tasks (todo, in_progress, review + recent done)
- `vibe-harness/decisions.json` — durable decisions
- `vibe-harness/archive/YYYY-MM.json` — monthly archives of completed tasks
- All files are text-based JSON — git diff, merge, and conflict resolution work naturally
- Commit these files along with your code

### Sharing Workflow

```
1. Work normally — kanban.json is updated as you work (direct edits or via API)
2. git add vibe-harness/ → commit with your code changes
3. On pull — if merge conflict in kanban.json, resolve like any JSON (per-task)
4. Archive periodically: /vibe-harness archive → moves done tasks to archive/YYYY-MM.json
```

### User Identification

- Tasks have `created_by` and `assigned_to` fields
- Set `created_by` from `git config user.name` on task creation
- `in_progress` limit (1 task) applies **per user**, not globally
- When starting a task, set `assigned_to` to current user

### Claude Auto-Recording Rules (Multi-User)

1. On task creation → set `created_by` to `git config user.name`
2. On start → set `assigned_to` to current user
3. **On direct-to-done recording** (task created retroactively as `done`) → set BOTH `created_by` and `assigned_to`; the start trigger never fires for these
4. Human fields hold human names only — never write agent names (`claude`, `codex`) into `created_by`/`assigned_to`; agents are attributed via `runs.json` `agent`
5. On `in_progress` enforcement → only move **your own** prior in_progress tasks back to `todo`, never someone else's
6. Periodically archive done tasks (`/vibe-harness archive`) to keep kanban.json small

---

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

## Notes

- Single optional server serves all projects (port 4242, localhost only)
- `~/.claude/skills/vibe-harness/projects.json` stores the project list used by the server
- Each project's `vibe-harness/` directory should be git-tracked (kanban.json + decisions.json + archive/)
- JSON writes — both server and direct edits — should use atomic file replacement (write to `.tmp`, then rename) for safety

## Optional Remote Snapshot Sync

Remote dashboards use an outbound, read-only snapshot publisher. Never expose
the localhost server or reuse an end-user login token as the upload secret.

Configuration: `~/.claude/skills/vibe-harness/sync.json` (chmod `600`):

```json
{
  "enabled": true,
  "endpoint": "https://example.com/api/internal/vibe-harness/sync",
  "secret": "dedicated-upload-secret",
  "dashboards": {"ax-project": ["impactbook_ai"]}
}
```

- A write to tasks, decisions, or runs schedules a debounced bundle upload.
- Archives are included with active tasks.
- Failed uploads are persisted to `sync-pending.json` and retried.
- Run `python3 ~/.claude/skills/vibe-harness/server.py sync` for a manual flush.
- Run `server.py configure-sync <endpoint> <dashboard> <project_key>...` to
  create the mode-0600 config without placing the secret in shell history.
- Dashboard access control belongs to the receiving application; the publisher
  only authenticates with its dedicated bearer secret.

## Managed Worker Runtime (Optional)

The Worker runtime is opt-in. Never start a Worker merely because `worker.py`
exists. Start it only when the user explicitly requests managed execution.

Source-of-truth rules:

- `kanban.json`, `CURRENT_PHASE.md`, and `decisions.json` remain authoritative.
- `runtime.json` is ephemeral and ignored by Git; cross-process locks live under
  `~/.claude/skills/vibe-harness/runtime-locks/` outside project repositories.
- `runs.json` remains append-only; one terminal record per `run_id`.
- A managed task may become `done` only after the server-run test gate passes.
- Never trust an agent-provided claim that tests passed.
- Never expose lease tokens in logs, snapshots, task details, or chat output.

Start a Worker:

```bash
python3 ~/.claude/skills/vibe-harness/worker.py <project_key> \
  --project-root "$(pwd)" --agent codex
```

Project policy lives at `vibe-harness/worker.json`. Adapter and test commands
must be argv arrays; the runtime never executes them through a shell. Each run
uses an isolated Git worktree. See `docs/WORKER_PROTOCOL.md` in the repository
for the API, state machine, retry, lease, and approval contracts.
