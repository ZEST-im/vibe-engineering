# Managed worker runtime

> Reference for the `vibe-harness` skill. Load when you need it — not at session start.

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
