# Vibe Engineering Worker Protocol

## Invariants

- `kanban.json`, `CURRENT_PHASE.md`, and `decisions.json` remain the project source of truth.
- `runtime.json` is ephemeral execution-control state and must not be committed.
- `runs.json` remains append-only. A terminal execution appends exactly one run record.
- A task can have at most one active lease.
- A managed task cannot enter `done` unless the Harness test gate passed.
- Lease tokens are returned once and stored only as SHA-256 hashes.
- Every mutating Worker request is idempotent by `run_id` and lease token.

## State machine

```text
todo --claim--> in_progress --gate pass, auto--> done
                            --gate pass, approval--> review --approve--> done
                            --failure, attempts left--> todo
                            --failure, exhausted--> review
                            --lease expired, attempts left--> todo
                            --lease expired, exhausted--> review
```

## Files

- `vibe-harness/worker.json`: tracked project execution policy.
- `vibe-harness/runtime.json`: ignored mutable leases/executions state.
- `~/.claude/skills/vibe-harness/runtime-locks/`: per-project cross-process locks.
- `vibe-harness/runs.json`: existing append-only terminal usage log.

## Worker API

- `GET /api/{project}/runtime`: sanitized leases, executions, and policy.
- `POST /api/{project}/worker/claim`: atomically claim a todo task.
- `POST /api/{project}/worker/heartbeat`: extend an active lease.
- `POST /api/{project}/worker/complete`: run the server-side test gate and finish.
- `POST /api/{project}/worker/fail`: record an execution failure.
- `POST /api/{project}/runtime/action`: local approve, reject, retry, or cancel.

Claim response includes `run_id`, `lease_id`, one-time `lease_token`, task data,
current Phase context, and the configured adapter. Heartbeat and terminal requests
must include all three identifiers.

## Policy

`worker.json` is optional. Safe defaults require human approval and provide no test
commands, which means a run cannot auto-complete until the project configures a
real gate.

```json
{
  "version": 1,
  "lease_ttl_seconds": 120,
  "heartbeat_seconds": 30,
  "max_attempts": 2,
  "approval": {
    "default": "required",
    "auto_complete_categories": ["docs", "test"],
    "always_require_categories": ["database", "security", "deploy"]
  },
  "test_gate": {
    "commands": [
      {"argv": ["python3", "-m", "unittest", "discover", "-s", "tests"], "timeout_seconds": 300}
    ]
  },
  "adapters": {
    "codex": {"argv": ["codex", "exec", "--full-auto", "{prompt}"]}
  }
}
```

Commands are argv arrays and never pass through a shell. The Harness executes them
from the registered project root and captures bounded stdout/stderr and exit codes.

## Remote approval

Remote dashboards receive only sanitized runtime state. zest.im stores approval
commands in a private queue. The local server polls that queue over the existing
bearer-authenticated sync channel, applies commands to the source-of-truth task,
and acknowledges each command id. WebSocket/SSE is intentionally not used.
