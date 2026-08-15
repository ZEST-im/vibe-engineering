#!/bin/bash
# vibe-harness-stop-gate.sh — Stop hook
# Warns if there are in_progress or review tasks before session ends.

CWD=$(pwd)
PROJECT=$(basename "$CWD")

STATS=$(curl -s "http://localhost:4242/api/${PROJECT}/stats" 2>/dev/null)
if [[ -z "$STATS" ]]; then
  exit 0
fi

IN_PROGRESS=$(echo "$STATS" | jq -r '.in_progress // 0' 2>/dev/null)
REVIEW=$(echo "$STATS" | jq -r '.review // 0' 2>/dev/null)

if [[ "$IN_PROGRESS" -eq 0 && "$REVIEW" -eq 0 ]]; then
  exit 0
fi

echo ""
echo "┌─────────────────────────────────────────────────┐"
echo "  [Vibe Engineering] 세션 종료 전 확인"
echo "└─────────────────────────────────────────────────┘"
if [[ "$IN_PROGRESS" -gt 0 ]]; then
  echo "  ⚠️  in_progress 태스크 ${IN_PROGRESS}개 — work report 작성 후 done/todo 이동 권장"
fi
if [[ "$REVIEW" -gt 0 ]]; then
  echo "  ⚠️  review 태스크 ${REVIEW}개 미해결 — 처리 후 종료 권장"
fi
echo ""
exit 0
