# AGENTS.md — Vibe Harness Rules for Codex and other agents

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
python3 ~/.claude/skills/vibe-harness/server.py register vibe-harness "Vibe Harness" "$(pwd)/vibe-harness"
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
    "details": "## Changes\n- file: what changed\n\n## Decisions\n- why X over Y"
  }'
```

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
2. `git add` + `git commit` (Korean commit message summarizing changes)
3. `git push origin main`

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
