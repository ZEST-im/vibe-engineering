#!/bin/bash
# vibe-harness-session-start.sh — SessionStart hook
# Loads CURRENT_PHASE.md from the current project and injects it into Claude's context.

CWD=$(pwd)

# python3 를 그냥 부르면 Windows 에서 깨진다. python.exe 만 깔린 머신에는 python3 가
# 아예 없고, PATH 에는 MS Store 앱 실행 별칭 스텁이 앉아 있어 "파일은 존재하는데
# exit 49" 로 실패한다. 그래서 존재 여부가 아니라 실제로 도는지를 본다.
# 못 찾으면 파이썬이 필요한 경고만 건너뛴다 — 세션 시작 자체를 막지는 않는다.
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
PY_BIN=$(vibe_python) || PY_BIN=""

# 수집 잡 상태를 보는 방법은 OS 마다 다르다. Windows 에 launchctl 은 없고,
# 없는 명령을 알려주는 안내는 없느니만 못하다.
job_status_hint() {
  case "$(uname -s 2>/dev/null)" in
    Darwin)
      echo "launchctl list | grep vibe-harness   (2열이 마지막 exit status)" ;;
    MINGW*|MSYS*|CYGWIN*|Windows*)
      echo "schtasks /Query /TN VibeHarnessReconcile /V /FO LIST" ;;
    *)
      echo "crontab -l | grep reconcile_runs" ;;
  esac
}

# 수집 파이프라인이 살아 있는지. 보드가 정상으로 보여도 수집은 죽어 있을 수 있고,
# 실제로 세 번 그랬다 — 세 번 다 사람이 우연히 발견했다. 여기서 먼저 말한다.
#
# 서버에 묻지 않고 상태 파일을 직접 읽는다. 서버가 죽은 것도 알아야 할 상황이라
# 서버를 경유하면 같은 고장에 같이 눈이 먼다.
warn_if_pipeline_stale() {
  local status_file="$HOME/.claude/skills/vibe-harness/pipeline-status.json"
  [[ -f "$status_file" ]] || return 0
  [[ -n "$PY_BIN" ]] || return 0
  local msg
# Windows 의 Python 은 stdout 을 로케일 코드페이지(cp949)로 인코딩한다. 이 훅의
# echo 는 UTF-8 이라 한 스트림에 두 인코딩이 섞이고, 읽는 쪽에서 통째로 깨진다.
# -X utf8 로 못박아 둔다.
  msg=$("$PY_BIN" -X utf8 - "$status_file" <<'PYEOF' 2>/dev/null
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
  # Windows 의 Python 은 stdout 에 CRLF 를 쓴다. 명령 치환은 개행만 떼므로 CR 이
  # 값 끝에 남아 뒤의 문자열 자르기와 출력이 어긋난다.
  msg=${msg%$'\r'}
  [[ -z "$msg" ]] && return 0
  local hours="${msg%%|*}" err="${msg#*|}"
  echo ""
  echo "  ⚠ 토큰 수집이 ${hours} 동안 성공하지 못했습니다 (3시간마다 돌아야 함)"
  [[ -n "$err" ]] && echo "    마지막 오류: $err"
  echo "    확인: $PY_BIN scripts/reconcile_runs.py --all --push"
  echo "    잡 상태: $(job_status_hint)"
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

# 아카이브가 밀렸는지. 문서(qq 5단계)로 규정해 뒀는데 2주 뒤 22개 중 4개가 다시
# 30건을 넘겼다. 규율이 아니라 검사가 필요하다는 뜻이라 여기서 말한다.
warn_if_archive_overdue() {
  local kb; kb=$(find_kanban "$CWD") || return 0
  [[ -n "$kb" ]] || return 0
  [[ -n "$PY_BIN" ]] || return 0
  local msg
  msg=$("$PY_BIN" -X utf8 - "$kb" <<'PYEOF' 2>/dev/null
import json, os, sys
DONE, BYTES = 30, 50 * 1024
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        tasks = json.load(fh).get("tasks", [])
except Exception:
    raise SystemExit(0)
done = sum(1 for t in tasks if t.get("status") == "done")
size = os.path.getsize(sys.argv[1])
if done >= DONE or size >= BYTES:
    print("%d|%d" % (done, size // 1024))
PYEOF
)
  msg=${msg%$'\r'}
  [[ -z "$msg" ]] && return 0
  echo ""
  echo "  ⚠ 완료 태스크 ${msg%%|*}건(${msg#*|}KB)이 kanban.json 에 쌓였습니다 — 세션마다 읽힙니다"
  echo "    정리: /vibe-harness archive   (보드에서는 계속 보입니다)"
  echo ""
}

PHASE_FILE=$(find_phase_file "$CWD")
if [[ -z "$PHASE_FILE" ]]; then
  # No CURRENT_PHASE.md. Nudge only if this is an active vibe-harness project
  # (kanban has tasks) — otherwise stay silent (not every dir uses phases).
  KANBAN=$(find_kanban "$CWD")
  if [[ -n "$KANBAN" ]]; then
    NTASKS=$("${PY_BIN:-python3}" -X utf8 -c "import json,sys;print(len(json.load(open('$KANBAN')).get('tasks',[])))" 2>/dev/null || echo 0)
    NTASKS=${NTASKS%$'\r'}
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
  warn_if_archive_overdue
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
warn_if_archive_overdue
exit 0
