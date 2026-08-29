#!/bin/bash
# vibe-harness-session-start.sh — SessionStart hook
# Loads CURRENT_PHASE.md from the current project and injects it into Claude's context.

CWD=$(pwd)

# 수집 파이프라인이 살아 있는지. 보드가 정상으로 보여도 수집은 죽어 있을 수 있고,
# 실제로 세 번 그랬다 — 세 번 다 사람이 우연히 발견했다. 여기서 먼저 말한다.
#
# 서버에 묻지 않고 상태 파일을 직접 읽는다. 서버가 죽은 것도 알아야 할 상황이라
# 서버를 경유하면 같은 고장에 같이 눈이 먼다.
warn_if_pipeline_stale() {
  local status_file="$HOME/.claude/skills/vibe-harness/pipeline-status.json"
  [[ -f "$status_file" ]] || return 0
  local msg
  msg=$(python3 - "$status_file" <<'PYEOF' 2>/dev/null
import datetime, json, sys
STALE_HOURS = 24
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        doc = json.load(fh)
    seen = datetime.datetime.fromisoformat(str(doc.get("last_success")))
except Exception:
    raise SystemExit(0)
if seen.tzinfo is None:
    seen = seen.replace(tzinfo=datetime.timezone.utc)
hours = (datetime.datetime.now(seen.tzinfo) - seen).total_seconds() / 3600
if hours > STALE_HOURS:
    err = doc.get("last_error")
    print("%.0f시간|%s" % (hours, (err or "")[:80]))
PYEOF
)
  [[ -z "$msg" ]] && return 0
  local hours="${msg%%|*}" err="${msg#*|}"
  echo ""
  echo "  ⚠ 토큰 수집이 ${hours} 동안 성공하지 못했습니다 (3시간마다 돌아야 함)"
  [[ -n "$err" ]] && echo "    마지막 오류: $err"
  echo "    확인: python3 scripts/reconcile_runs.py --all --push"
  echo "    잡 상태: launchctl list | grep vibe-harness   (2열이 마지막 exit status)"
  echo ""
}

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

# Find a vibe-harness/kanban.json by walking up — signals an active vibe-harness project.
find_kanban() {
  local dir="$1"
  local depth=0
  while [[ "$dir" != "/" && $depth -lt 6 ]]; do
    if [[ -f "$dir/vibe-harness/kanban.json" ]]; then
      echo "$dir/vibe-harness/kanban.json"; return 0
    fi
    dir=$(dirname "$dir")
    ((depth++))
  done
  return 1
}

PHASE_FILE=$(find_phase_file "$CWD")
if [[ -z "$PHASE_FILE" ]]; then
  # No CURRENT_PHASE.md. Nudge only if this is an active vibe-harness project
  # (kanban has tasks) — otherwise stay silent (not every dir uses phases).
  KANBAN=$(find_kanban "$CWD")
  if [[ -n "$KANBAN" ]]; then
    NTASKS=$(python3 -c "import json,sys;print(len(json.load(open('$KANBAN')).get('tasks',[])))" 2>/dev/null || echo 0)
    if [[ "$NTASKS" -gt 0 ]] 2>/dev/null; then
      PROOT=$(dirname "$(dirname "$KANBAN")")
      echo ""
      echo "┌─────────────────────────────────────────────────┐"
      echo "  [Vibe Engineering] ⚠ Phase 미설정 — 태스크 ${NTASKS}개 있는데 CURRENT_PHASE.md 없음"
      echo "└─────────────────────────────────────────────────┘"
      echo ""
      echo "  이 프로젝트는 kanban 태스크는 있지만 Phase 스코프 파일이 없습니다."
      echo "  scope/Do-NOT-touch 가드가 동작하지 않습니다."
      echo ""
      echo "  → Phase 관리를 시작하려면: /vibe-harness phase init"
      echo "    (CURRENT_PHASE.md + PHASES.md 템플릿 생성. private/ · docs/ · root 어디든 인식)"
      echo "  → 또는 이번 세션 스코프를 사용자에게 먼저 확인하세요."
      echo ""
    fi
  fi
  warn_if_pipeline_stale
  exit 0
fi

PROJECT=$(basename "$(dirname "$PHASE_FILE")")
# CURRENT_PHASE.md may live in private/ or docs/ — project name is one level up
[[ "$PROJECT" == "docs" || "$PROJECT" == "private" ]] && PROJECT=$(basename "$(dirname "$(dirname "$PHASE_FILE")")")

echo ""
echo "┌─────────────────────────────────────────────────┐"
echo "  [Vibe Engineering] 세션 시작 — 현재 Phase 로드됨"
echo "└─────────────────────────────────────────────────┘"
echo ""
cat "$PHASE_FILE"
echo ""
echo "  📌 Phase 파일: $PHASE_FILE"
echo "  Do NOT touch 목록을 반드시 준수하세요."
echo ""
warn_if_pipeline_stale
exit 0
