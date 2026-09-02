#!/bin/bash
# vibe-harness-token-collector.sh — SessionEnd hook (PHASE_PMF03)
# Reads Claude Code's hook JSON on stdin, parses the session transcript, and
# records one agent run (real token usage) into the project's runs.json via the
# shared recorder. Always exits 0 — never blocks session end on error.

INPUT=$(cat)
RECORDER="$HOME/.claude/hooks/vibe-harness-record-run.py"
[ -f "$RECORDER" ] || exit 0

# python3 를 그냥 부르면 Windows 에서 깨진다. python.exe 만 깔린 머신에는 python3 가
# 아예 없고, PATH 에는 MS Store 앱 실행 별칭 스텁이 앉아 있어 "파일은 존재하는데
# exit 49" 로 실패한다. 그래서 존재 여부가 아니라 실제로 도는지를 본다.
# 이 훅은 stderr 를 버리고 exit 0 하므로, 여기서 틀리면 조용한 과소집계가 된다.
vibe_python() {
  local c
  for c in python3 python py; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "" >/dev/null 2>&1; then
      printf '%s\n' "$c"
      return 0
    fi
  done
  return 1
}
PY_BIN=$(vibe_python) || exit 0

# Extract fields from the hook payload (python, no jq dependency).
# 한 줄에 하나씩 읽는다 — Windows 사용자 이름에는 공백이 흔해서
# (C:\Users\John Smith\.claude\...) 공백으로 쪼개면 경로가 잘린다.
# 경로에 개행은 들어가지 않으므로 줄 단위는 안전하다.
{ read -r TRANSCRIPT; read -r SESSION; read -r CWD; } < <("$PY_BIN" -X utf8 - "$INPUT" <<'PYEOF'
import json, sys
try:
    o = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}
except Exception:
    o = {}
print(o.get("transcript_path", ""))
print(o.get("session_id", ""))
print(o.get("cwd", "") or ".")
PYEOF
)

# Windows 의 Python 은 텍스트 모드 stdout 에서 줄바꿈을 CRLF 로 쓴다. read -r 은 LF 만
# 떼므로 CR 이 값 끝에 남고, 그 경로로는 파일이 열리지 않는데 이 훅은 stderr 를 버려서
# 아무 말 없이 0건이 된다. 원본도 --cwd 가 같은 상태였다.
TRANSCRIPT=${TRANSCRIPT%$'\r'}
SESSION=${SESSION%$'\r'}
CWD=${CWD%$'\r'}

[ -n "$TRANSCRIPT" ] || exit 0

"$PY_BIN" "$RECORDER" \
  --agent claude \
  --from-transcript "$TRANSCRIPT" \
  --session-id "$SESSION" \
  --cwd "$CWD" \
  --quiet 2>/dev/null

exit 0
