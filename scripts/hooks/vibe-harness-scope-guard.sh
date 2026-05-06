#!/bin/bash
# vibe-harness-scope-guard.sh — PreToolUse hook
# Blocks Edit/Write on files that match CURRENT_PHASE.md Do NOT touch list.
# Exit 1 = block, Exit 0 = allow.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)

# Only check file-editing tools
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
  exit 0
fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Find CURRENT_PHASE.md by walking up from the file's directory
find_phase_file() {
  local dir
  dir=$(dirname "$1")
  local depth=0
  while [[ "$dir" != "/" && $depth -lt 7 ]]; do
    if [[ -f "$dir/CURRENT_PHASE.md" ]]; then
      echo "$dir/CURRENT_PHASE.md"
      return 0
    fi
    if [[ -f "$dir/docs/CURRENT_PHASE.md" ]]; then
      echo "$dir/docs/CURRENT_PHASE.md"
      return 0
    fi
    dir=$(dirname "$dir")
    ((depth++))
  done
  return 1
}

PHASE_FILE=$(find_phase_file "$FILE_PATH")
if [[ -z "$PHASE_FILE" ]]; then
  exit 0  # No CURRENT_PHASE.md found — allow
fi

# Extract machine-readable SCOPE_LOCK block
SCOPE_LOCK=$(sed -n '/<!-- SCOPE_LOCK_BEGIN -->/,/<!-- SCOPE_LOCK_END -->/p' "$PHASE_FILE" \
  | grep -v '<!--' | grep -v '^[[:space:]]*$')

if [[ -z "$SCOPE_LOCK" ]]; then
  exit 0  # No SCOPE_LOCK block — allow (backward compat)
fi

# Determine project root (parent of docs/ if needed)
PROJECT_ROOT=$(dirname "$PHASE_FILE")
[[ "$PROJECT_ROOT" == */docs ]] && PROJECT_ROOT=$(dirname "$PROJECT_ROOT")

# Relative path of the file being edited
REL_PATH="${FILE_PATH#$PROJECT_ROOT/}"

# Check each pattern
while IFS= read -r line; do
  PATTERN=$(echo "$line" | sed 's/^[[:space:]]*-[[:space:]]*//' | xargs)
  [[ -z "$PATTERN" ]] && continue

  # Match: rel_path starts with pattern OR contains /pattern
  if [[ "$REL_PATH" == "$PATTERN"* || "$REL_PATH" == *"/$PATTERN"* ]]; then
    PHASE=$(grep '^## Now:' "$PHASE_FILE" 2>/dev/null | head -1 | sed 's/^## Now:[[:space:]]*//')
    echo ""
    echo "🚫 SCOPE VIOLATION — Do NOT touch: $PATTERN"
    echo "   File:    $REL_PATH"
    echo "   Phase:   ${PHASE:-unknown}"
    echo "   Rule:    $PHASE_FILE"
    echo ""
    echo "이 파일은 현재 Phase 스코프 밖입니다."
    echo "작업이 필요하다면 사용자에게 먼저 확인하세요."
    exit 1
  fi
done <<< "$SCOPE_LOCK"

exit 0
