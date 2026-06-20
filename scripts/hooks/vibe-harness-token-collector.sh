#!/bin/bash
# vibe-harness-token-collector.sh — SessionEnd hook (PHASE_PMF03)
# Reads Claude Code's hook JSON on stdin, parses the session transcript, and
# records one agent run (real token usage) into the project's runs.json via the
# shared recorder. Always exits 0 — never blocks session end on error.

INPUT=$(cat)
RECORDER="$HOME/.claude/hooks/vibe-harness-record-run.py"
[ -f "$RECORDER" ] || exit 0

# Extract fields from the hook payload (python, no jq dependency).
read -r TRANSCRIPT SESSION CWD < <(python3 - "$INPUT" <<'PY'
import json, sys
try:
    o = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}
except Exception:
    o = {}
print(o.get("transcript_path", ""), o.get("session_id", ""), o.get("cwd", "") or ".")
PY
)

[ -n "$TRANSCRIPT" ] || exit 0

python3 "$RECORDER" \
  --agent claude \
  --from-transcript "$TRANSCRIPT" \
  --session-id "$SESSION" \
  --cwd "$CWD" \
  --quiet 2>/dev/null

exit 0
