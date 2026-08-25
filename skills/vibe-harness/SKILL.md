---
name: vibe-harness
description: Vibe-Engineering — Dev progress kanban board for Claude Code. Multi-project support, task tracking with code change stats + web UI.
user-invocable: true
---

# Vibe-Engineering — Dev Progress Kanban Board

Track development progress as a kanban board while coding with Claude Code.

## References — load only when you need them

This file holds the rules you work by. Everything you *look up* lives beside it, so a
session does not pay for reference material it never opens.

| File | Open it when |
|---|---|
| `references/task-schema.md` | Writing or editing a task by hand — field list, required fields on `done`, status values |
| `references/api.md` | Calling the local HTTP API, or explaining the Board UI |
| `references/setup.md` | Installing on a new machine or registering a project |
| `references/worker-runtime.md` | Running the managed worker (lease, heartbeat, test gate) |
| `references/remote-sync.md` | Wiring a project's snapshot to a central dashboard |

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

## File Locations

```
~/.claude/skills/vibe-harness/server.py           ← Web server (optional, shared across projects)
~/.claude/skills/vibe-harness/kanban.html         ← Web UI (loaded by server)
~/.claude/skills/vibe-harness/projects.json       ← Project registry (used by server)
~/.claude/skills/vibe-harness/users.json          ← Display-name alias map (optional, machine-local)
~/.claude/skills/vibe-harness/sync.json           ← Remote sync config + tokens (0600, machine-local, never commit)
~/.claude/skills/vibe-harness/push-state.json     ← Incremental push state (machine-local)
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

## Token usage collection

Opt-in. Reads Claude Code transcripts (`~/.claude/projects/`) and rebuilds usage per session per
calendar day (KST). Nothing is transmitted unless `sync.json` has an endpoint and a credential.

```bash
python3 scripts/enroll.py --token <t> --machine <name> --runs-schema 2   # register this machine
python3 scripts/enroll.py --add-project <key>=<repo path>                # register a project
python3 scripts/enroll.py --repair                                       # re-point after repo move
python3 scripts/reconcile_runs.py --all --dry-run                        # preview
python3 scripts/reconcile_runs.py --all --push                           # send changed rows only
python3 scripts/reconcile_runs.py --all --push --force-full-push         # resend everything (recovery)
```

Rules Claude must follow here:

- **`--add-project` is not optional.** Collection only walks projects in `projects.json`. A machine
  with an empty registry used to exit 0 having done nothing; it now fails loudly, but the fix is
  still to register the projects.
- **Project keys are shared, paths are not.** Use the same key every machine uses; the repo path
  differs per machine. A made-up key produces rows the dashboard never reads.
- **`secret` and `runs_token` are different credentials.** `secret` signs dashboard snapshots
  (per project, shared); `runs_token` signs usage rows (per person). Writing a personal token into
  `secret` breaks snapshot sync with a 401.
- **Never commit `sync.json`** or paste a token into chat, a commit message, or an issue.
- Re-running `enroll.py` is safe. The LaunchAgent label and the Windows task name are fixed.

## Shorthand Commands (user types these directly)

Three two-letter shorthands cover the daily rhythm — sync at session start (`ss`), wrap up at day end (`qq`), ship when ready (`cc`). When the user types one of these as a bare message, run the corresponding procedure.

### `ss` — sync & status

Check this repo's remote and pull everything, branches included:

1. `git fetch --all --prune --tags` — refresh remote branches/tags, prune deleted ones.
2. Fast-forward pull the current branch. Fast-forward other local tracking branches too (`git fetch origin <branch>:<branch>`). Never auto-merge a diverged branch — report it instead.
3. Report: current branch + ahead/behind vs remote, remote branch list (flag unmerged ones), uncommitted files (`git status`), and a summary of newly pulled commits if any.
4. If the pull changed harness code (`scripts/`), check whether the installed copies (`~/.claude/skills/vibe-harness/`) and any running server need updating, and tell the user.
5. **Daily review pass** — run the `vibe-review` skill in daily mode over the work since the previous session, and report it as part of `ss`. If nothing has landed since the last pass, say so in one line and move on; that is what keeps repeated `ss` calls cheap. This is the session-start ritual that makes yesterday's gap between claim and reality visible before new work starts.

### `qq` — daily wrap-up (no commit)

1. Print kanban summary (today's done, in-progress, tomorrow's tasks) — derived from kanban.json.
2. Update any in-progress task's `details` with an interim report; write `details` on done tasks that lack them.
3. Update phase docs only when warranted: `PHASES.md` on phase completion, `CURRENT_PHASE.md` on scope / Known Issues change.
4. **Code review** on uncommitted + unpushed changes (see Code Review section).
5. **Archive if `kanban.json` has grown** — more than ~30 done tasks or above ~50KB. See
   "Keeping context cheap". Archiving is a routine; skipping it is how a project ends up
   paying six figures of tokens to answer "what am I working on".
6. Update `docs/PROGRESS.md` — concise phase-level completion items only. It is an external-sharing snapshot, not a daily log; the day-to-day record stays in `kanban.json`.
7. No commit, no push — `qq` is documentation only.

### `cc` — commit + push (+ deploy check)

1. Everything `qq` does (skip whatever is already clean).
2. `git add` + `git commit` — code and its related docs (kanban.json included) go in ONE commit, never split.
3. `git push origin main`.
4. If the project has CI/CD wired to push, check build/deploy status after pushing and report it. Avoid docs-only pushes on CI/CD-triggering repos.

## Keeping context cheap

A harness that costs thousands of tokens to consult is a harness people stop consulting.
Four rules, learned by measuring rather than guessing:

**1. Measure before optimizing.** Find where the tokens actually go before changing
anything. Measured across 15 projects, `kanban.json` alone accounted for ~946,000 tokens
of session-start cost — one project spent 154,000 tokens just to answer "what am I
working on". That number decided what to fix; intuition would have pointed elsewhere.

**2. Split growing records into hot and archived.** Task history grows without limit but
only the recent edge affects the next decision. Done tasks belong in
`archive/YYYY-MM.json` — still visible on the board and counted in `stats`, but no longer
loaded into every session.

**3. Read a summary; fetch the full record only when the reasoning matters.** A task's
`details` runs to thousands of characters. Titles and change counts answer almost every
session-start question; open the full report when a specific past decision is actually in
question.

**4. Rules live in `SKILL.md`; lookups live in `references/`.** If it is something you
consult while doing a particular job — a field list, an API shape, install steps — it does
not belong in the file loaded on every invocation.

### Archiving is a routine, not a migration

**This is the rule most often missed.** Of the projects measured, several had an
`archive/` directory *and* over 200 done tasks still sitting in `kanban.json` — archived
once, then left to refill.

Archive whenever done tasks accumulate — during `qq` is the natural moment. A practical
trigger: **more than ~30 done tasks in `kanban.json`, or the file above ~50KB.** Run
`/vibe-harness archive` and the month's work moves out in one step.

After archiving, confirm `next_id` still exceeds every archived id. Reusing an id that
only exists in an archive is silent corruption — the board looks fine and two tasks share
a number.

## Session Start (Claude should follow)

At the start of a session, establish current mission context. **Load a summary, not the archive.** A project's task history grows without limit; reading it whole costs thousands of tokens every session and almost none of it changes what you do next.

**Preferred — one call, if the server is already running:**

```
GET http://localhost:4242/api/{project_key}/context
```

Returns phase, scope, checklist, `Do NOT touch`, `in_progress`, recent completions, and stats. Recent completions carry titles and change counts, **not** their full reports — fetch an individual task only when you actually need its reasoning. **Do not start the server just for this**; if it is not up, use the fallback.

**Fallback — read files directly:**

1. **`CURRENT_PHASE.md`** (checked in `private/`, then root, then `docs/`) — phase name, scope, `Done when`, and the `Do NOT touch` block. This is the primary scope signal.
2. **`vibe-harness/kanban.json`** — the active `in_progress` task, if any. Done tasks live in `vibe-harness/archive/YYYY-MM.json`; **do not read the archives at session start.** Open one only when a specific past decision is in question.
3. **`vibe-harness/decisions.json`** — recent durable decisions that may constrain the work.
4. **`docs/planning/01_philosophy.md`** (if present) — the project's north star, written by the `vibe-planning` skill. Its principles and the "who we are not for" section are decision constraints; when a task conflicts with them, say so rather than quietly picking a side.

**Keep `kanban.json` small.** Run `/vibe-harness archive` when done tasks accumulate. The board still shows them — archives are read by the dashboard and by `stats` — but they stop being loaded into every session.

From these, derive:
- Current Phase name and scope
- Existing `in_progress` task (resume) vs. new work
- The `Do NOT touch` list (the scope-guard hook also enforces this — see Phase Management below)
- Open checklist items

If no `CURRENT_PHASE.md` exists anywhere (`private/` / root / `docs/`) but the project already has kanban tasks, the session-start hook nudges you. Run `/vibe-harness phase init` to scaffold it, or ask the user how they want to scope the session before creating new tasks. Don't silently start work without a scope.

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
- PROGRESS.md is an "external-sharing snapshot" — updated at `qq` / `cc` with concise phase-level completion items, never a daily log. The day-to-day record lives in kanban.json.
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

#### Display-name aliases (`users.json`)

`git config user.name` is often not the handle you want on the board — the same person
shows up as `a.kim` on one machine, `akim-work` on another, and under their display name
when a task is typed by hand. Normalizing that by editing the JSON after the fact does not
hold: the next task created re-introduces the raw git name, so the same sweep runs again.

Canonicalize at the point of entry instead. Create an optional machine-local map:

```json
// ~/.claude/skills/vibe-harness/users.json      (chmod 600 — it holds real names)
{
  "aliases": {
    "a.kim": "akim",
    "akim-work": "akim",
    "Ayeong Kim": "akim"
  }
}
```

- Applied wherever an owner field is written: `_git_user()`, task creation, task update.
- Lookup is case-insensitive and whitespace-trimmed. Unknown names pass through untouched,
  so real teammates who need no alias are unaffected.
- The file lives **outside** any repo — real names never land in a public project.
- Missing or malformed file = no aliases. Nothing changes for anyone who skips this.
- Override the path with `VIBE_HARNESS_USERS_CONFIG` (used by the tests).

Set the canonical handle here rather than changing `git config user.name`: that name is
usually global, so changing it rewrites the author on every future commit in every repo.

### Claude Auto-Recording Rules (Multi-User)

1. On task creation → set `created_by` to `git config user.name`
2. On start → set `assigned_to` to current user
3. **On direct-to-done recording** (task created retroactively as `done`) → set BOTH `created_by` and `assigned_to`; the start trigger never fires for these
4. Human fields hold human names only — never write agent names (`claude`, `codex`) into `created_by`/`assigned_to`; agents are attributed via `runs.json` `agent`
5. On `in_progress` enforcement → only move **your own** prior in_progress tasks back to `todo`, never someone else's
6. Periodically archive done tasks (`/vibe-harness archive`) to keep kanban.json small

---

## Notes

- Single optional server serves all projects (port 4242, localhost only)
- `~/.claude/skills/vibe-harness/projects.json` stores the project list used by the server
- Each project's `vibe-harness/` directory should be git-tracked (kanban.json + decisions.json + archive/)
- JSON writes — both server and direct edits — should use atomic file replacement (write to `.tmp`, then rename) for safety

