# Task schema — direct JSON editing

> Reference for the `vibe-harness` skill. Load when you need it — not at session start.

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
- **Concurrent edits**: atomicity alone is not enough. Two agents that each read, modify, and
  write will have the later one silently overwrite the earlier, and both may take the same
  `next_id` — that is how ids 409 and 410 ended up on two tasks each. Git makes it worse, not
  better: two tasks at different offsets merge cleanly and one disappears from the board with
  no error. Hold a lock across the whole read-modify-write, or use the helper that does:

  ```bash
  python3 scripts/kanban_edit.py add "제목" --category infra   # 서버 없이도 안전
  python3 scripts/kanban_edit.py set 42 --status done
  ```

  It reuses the server's id allocation (prefix handling and `next_id` self-correction), reads
  the archive so an archived id is never reissued, and takes a `kanban.lock` for the duration.
  On platforms without `fcntl` the lock degrades to a no-op — pass `--require-lock` to fail
  instead of proceeding unprotected.
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
