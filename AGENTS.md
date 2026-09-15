# AGENTS.md — Vibe Engineering Rules for Codex and other agents

Claude Code enforces these rules via hooks and skill instructions.
This file provides the same rules for Codex CLI and other agents that read AGENTS.md.

---

## Session Start — REQUIRED

Before writing any code, fetch the current mission context:

```bash
curl http://localhost:4242/api/vibe-harness/context
```

From the response, extract and respect:
- `phase` — current phase name (e.g. `PHASE_MVP01`)
- `scope` — what this phase covers
- `in_progress` — already-running tasks (resume these first)
- `do_not_touch` — **files and areas you MUST NOT edit this session**
- `checklist.items` — remaining completion criteria

If the server is not running:
```bash
python3 ~/.claude/skills/vibe-harness/server.py serve 4242 &
```

If this project is not yet registered:
```bash
python3 ~/.claude/skills/vibe-harness/server.py register vibe-harness "Vibe Engineering" "$(pwd)/vibe-harness"
```

When the user types `ss` (sync & status):
1. `git fetch --all --prune --tags`
2. Fast-forward pull the current branch; fast-forward other local tracking branches (`git fetch origin <branch>:<branch>`). Never auto-merge a diverged branch — report it.
3. Report: ahead/behind vs remote, remote branch list, uncommitted files, newly pulled commits.

---

## Scope Rules

1. **Do NOT touch** anything listed in `do_not_touch` from the context API.
2. Do not move to the next phase without explicit user instruction.
3. If a task would require touching out-of-scope files, stop and ask first.

---

## Kanban — Task Lifecycle

### Before starting work
Check if a task for this work already exists:
```bash
curl http://localhost:4242/api/vibe-harness/tasks
```

If it doesn't exist, create it:
```bash
curl -X POST http://localhost:4242/api/vibe-harness/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"<task title>","status":"todo","category":"backend","phase":"PHASE_MVP01"}'
```

### When starting a task
Move it to `in_progress` (only ONE task in_progress at a time):
```bash
curl -X PUT http://localhost:4242/api/vibe-harness/tasks/<id> \
  -H 'Content-Type: application/json' \
  -d '{"status":"in_progress"}'
```

If another task is already `in_progress`, move it back to `todo` first.

### When completing a task
Measure code changes, write a work report, move to `done`:
```bash
# Measure changes
git diff --numstat HEAD

# Update task
curl -X PUT http://localhost:4242/api/vibe-harness/tasks/<id> \
  -H 'Content-Type: application/json' \
  -d '{
    "status": "done",
    "lines_added": <N>,
    "lines_removed": <N>,
    "created_by": "<git config user.name>",
    "assigned_to": "<git config user.name>",
    "details": "## Changes\n- file: what changed\n\n## Decisions\n- why X over Y"
  }'
```

`created_by`/`assigned_to` are ALWAYS required — also when a task is recorded
directly as `done` in one step. Use the **human** user name (`git config user.name`),
never an agent name (`codex`, `claude`) — agent attribution goes in `runs.json`.

---

## Phase Rules

| Prefix | Focus | Transition condition |
|--------|-------|---------------------|
| `SEED` | Boilerplate, schema | Basic structure + data loading done |
| `MVP`  | Core features only | Showable to user |
| `PMF`  | Iteration on feedback | Real user feedback started |
| `SCALE`| Performance, architecture | Traffic/data bottleneck hit |
| `GTM`  | Launch, marketing | Product stable |

- **Never auto-transition** to the next phase. Wait for explicit user instruction.
- Phase completion requires all `checklist.items` checked.

---

## Session End

When the user types `qq` (wrap-up without push):
1. Write `details` on any completed tasks that lack them
2. Update `private/PHASES.md` if a phase was completed
3. Summarize today's work briefly

When the user types `cc` (commit + push):
1. All of the above
2. `git add` + `git commit` (Korean commit message summarizing changes) — one commit per
   cause, not one big commit
3. `git push` to a **work branch**, never to `main`

---

## Merge / PR Rules

**Merge once, when a whole feature is done — not after every fix.** Opening and merging a
PR per fix moves `main` through half-finished states, and makes it impossible to tell where
one unit of work begins and ends when you need to revert.

| | |
|---|---|
| Commits | **Many.** One per cause. Say what changed, why, and which mutation proved the check works |
| PR | **One.** One PR per feature / batch of work. Keep related work on one branch |
| Merge | **Once, at the very end** — and only after everything below passes |

Before merging — if any of these is missing, do not merge:

1. `python3 scripts/check.py` — all six gates green
2. PR CI green. Check the run **for that commit** — the top of `gh run list` may be the
   previous one
3. A self review was run and **its findings were fixed too**
4. A human approved. Direct pushes to `main` are forbidden
   (`docs/OUTCOME_BASED_ENGINEERING_ASSIGNMENTS.md`)

If several PRs are open, **actually merge them locally first.** Two PRs can touch the same
region of the same file even when their file lists look disjoint — never claim "no overlap"
from the file list alone.

---

## Key API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/vibe-harness/context` | Current phase, scope, do_not_touch |
| GET | `/api/vibe-harness/tasks` | All tasks |
| POST | `/api/vibe-harness/tasks` | Create task |
| PUT | `/api/vibe-harness/tasks/<id>` | Update task |
| GET | `/api/vibe-harness/velocity` | Phase burndown + stats |

Board UI: [http://localhost:4242/kanban](http://localhost:4242/kanban)

---

## What Codex cannot do (Claude-only)

These are enforced automatically for Claude Code but are **best-effort** for Codex:

- `scope-guard` hook — blocks edits to `do_not_touch` files at the tool level
- `stop-gate` hook — warns when stopping with `in_progress` tasks
- `review` hook — auto-triggers code review on `git push`
- `session-start` hook — auto-loads phase context on session open

Follow these rules manually since the enforcement layer is absent.
