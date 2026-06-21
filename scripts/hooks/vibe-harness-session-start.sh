#!/bin/bash
# vibe-harness-session-start.sh — SessionStart hook
# Loads CURRENT_PHASE.md from the current project and injects it into Claude's context.

CWD=$(pwd)

find_phase_file() {
  local dir="$1"
  local depth=0
  while [[ "$dir" != "/" && $depth -lt 6 ]]; do
    if [[ -f "$dir/private/CURRENT_PHASE.md" ]]; then
      echo "$dir/private/CURRENT_PHASE.md"; return 0
    fi
    if [[ -f "$dir/CURRENT_PHASE.md" ]]; then
      echo "$dir/CURRENT_PHASE.md"; return 0
    fi
    if [[ -f "$dir/docs/CURRENT_PHASE.md" ]]; then
      echo "$dir/docs/CURRENT_PHASE.md"; return 0
    fi
    dir=$(dirname "$dir")
    ((depth++))
  done
  return 1
}

PHASE_FILE=$(find_phase_file "$CWD")
if [[ -z "$PHASE_FILE" ]]; then
  exit 0  # No phase file — silent pass
fi

PROJECT=$(basename "$(dirname "$PHASE_FILE")")
# CURRENT_PHASE.md may live in private/ or docs/ — project name is one level up
[[ "$PROJECT" == "docs" || "$PROJECT" == "private" ]] && PROJECT=$(basename "$(dirname "$(dirname "$PHASE_FILE")")")

echo ""
echo "┌─────────────────────────────────────────────────┐"
echo "  [Vibe Harness] 세션 시작 — 현재 Phase 로드됨"
echo "└─────────────────────────────────────────────────┘"
echo ""
cat "$PHASE_FILE"
echo ""
echo "  📌 Phase 파일: $PHASE_FILE"
echo "  Do NOT touch 목록을 반드시 준수하세요."
echo ""
exit 0
