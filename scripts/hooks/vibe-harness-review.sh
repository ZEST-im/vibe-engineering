#!/bin/bash
# vibe-harness-review.sh — PostToolUse hook
# On git push / gh pr create: output structured review gate with diff summary.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

if ! echo "$COMMAND" | grep -qE '^\s*(git\s+push|gh\s+pr\s+create)'; then
  exit 0
fi

PROJECT=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null || echo "unknown")
DIFF_STAT=$(git diff HEAD~1 HEAD --numstat 2>/dev/null | awk '{a+=$1; r+=$2; f++} END {print f" files, +"a" -"r}')
CHANGED_FILES=$(git diff HEAD~1 HEAD --name-only 2>/dev/null | head -10 | sed 's/^/     /')

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [Vibe Harness] CODE REVIEW GATE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  변경 요약: ${DIFF_STAT:-변경 없음}"
if [[ -n "$CHANGED_FILES" ]]; then
  echo "  변경 파일:"
  echo "$CHANGED_FILES"
fi
echo ""
echo "  ▶ 지금 바로 수행하세요:"
echo "  1. git diff HEAD~1 HEAD 로 변경사항 전체 확인"
echo "  2. CRITICAL / HIGH 이슈 탐색:"
echo "     · 보안: SQL injection, XSS, 인증 우회, 하드코딩 시크릿"
echo "     · 데이터: 마이그레이션 안전성, 롤백 가능 여부"
echo "     · 아키텍처: Phase 스코프 위반, Do NOT touch 파일 수정"
echo "  3. 이슈 발견 시 kanban에 review 태스크 생성:"
echo "     curl -s -X POST http://localhost:4242/api/${PROJECT}/tasks \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"title\":\"[REVIEW] <요약>\",\"status\":\"review\",\"category\":\"qa\",\"priority\":\"high\"}'"
echo "  4. 결과 요약: CRITICAL N건 / HIGH N건 / 태스크 N개 생성"
echo ""
echo "  MEDIUM 이하는 태스크 생성 없이 요약에만. 이슈 없으면: ✅ Review clean"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
exit 0
