# Vibe Harness: 하네스 강화 + 에이전트 격상 계획

## 배경

현재 vibe-harness는 **대시보드로는 85% 완성**이지만 **하네스(제약 강제)로는 30% 미완성**.
모든 규칙이 SKILL.md 텍스트 안에 있어서 Claude가 따를 수도, 안 따를 수도 있는 상태.

| 영역 | 현재 | 문제 |
|------|------|------|
| 스코프 강제 | SKILL.md 텍스트만 | Do NOT touch 파일 수정해도 감지 안 됨 |
| 리뷰 게이트 | hook이 echo만 출력 | 실제 리뷰 자동 실행 없음 |
| 세션 시작 | 수동으로 CURRENT_PHASE.md 읽기 | 안 읽고 시작해도 막을 수 없음 |
| Phase 전환 | 텍스트 체크리스트 | 자동 검증 없음 |
| 토큰 추적 | Claude가 주관적으로 추정 | 통계적으로 무의미 |

---

## Part 1: 하네스 강화 🚧 IN PROGRESS

### 강화 1: PreToolUse 스코프 가드

**목표**: CURRENT_PHASE.md의 `Do NOT touch` 목록에 있는 파일 편집 시도 시 자동 차단

- `~/.claude/hooks/vibe-harness-scope-guard.sh` 신규
- `settings.json`에 `PreToolUse` 훅 등록 (Edit, Write 매처)
- 훅이 `tool_input.file_path` 파싱 → CURRENT_PHASE.md의 SCOPE_LOCK 블록과 대조
- 위반 시 exit 1로 Claude에게 경고 + 차단

**CURRENT_PHASE.md 기계가 읽을 수 있는 포맷**:
```markdown
## Do NOT touch
<!-- SCOPE_LOCK_BEGIN -->
- billing/
- admin/
- app/models/user.rb
<!-- SCOPE_LOCK_END -->
```

### 강화 2: 리뷰 게이트 실질화

**목표**: git push 후 단순 echo가 아니라 실제 diff + 구조화된 리뷰 지시 출력

- `vibe-harness-review.sh` 개선: diff 요약 + kanban API curl 명령어 포함한 강제 프롬프트 출력
- Claude가 반드시 리뷰를 수행하게 강한 컨텍스트 제공

### 강화 3: SessionStart/Stop 훅

**목표**: 세션 시작 시 CURRENT_PHASE.md 자동 로드, 종료 시 in_progress 있으면 경고

- `scripts/session-start.sh` 신규: CURRENT_PHASE.md 내용 출력 → Claude 컨텍스트 주입
- `scripts/stop-gate.sh` 신규: in_progress 태스크 있으면 경고 메시지
- `settings.json` SessionStart / Stop 훅 등록
- `setup.py` 훅 자동 설치 추가

### 강화 4: `phase-done` 자동 체크리스트

**목표**: Phase 전환 전 모든 조건 자동 검증

검증 항목:
1. kanban in_progress = 0
2. kanban review 미해결 = 0
3. CURRENT_PHASE.md `Done when` 항목 전부 `[x]`
4. PHASES.md 최근 업데이트 여부

- `server.py`에 `/api/{project}/phase-check` 엔드포인트 추가
- `SKILL.md`에 `phase-done` 명령어 추가

### 강화 5: 토큰 추적 기준 개선

**목표**: 주관적 추정 대신 일관된 기준 제공

- SKILL.md 추정 기준을 "세션 내 메시지 왕복 수 기반" 방식으로 개선
- 태스크 복잡도 × 예상 왕복 수 = 토큰 추정 테이블

---

## Part 2: 스킬 → 에이전트 격상 ⏳ PENDING

### 3단계 격상 경로

| Level | 내용 | 난이도 | 시기 |
|---|---|---|---|
| Level 1 | review hook → `claude` CLI subprocess | 낮음 | Part 1 이후 |
| Level 2 | `agents/code-reviewer.md` 정의 → subagent 등록 | 중간 | Level 1 이후 |
| Level 3 | plugin.json 기반 공식 플러그인 전환 | 높음 | 장기 |

**Level 2 구조**:
```
~/.claude/skills/vibe-harness/
├── SKILL.md
├── agents/
│   ├── code-reviewer.md     ← vibe-harness:code-reviewer
│   └── session-manager.md   ← vibe-harness:session-manager
```

**Level 3 구조** (플러그인):
```
~/.claude/plugins/marketplaces/vibe-harness/
└── plugins/vibe-harness/
    ├── .claude-plugin/plugin.json
    ├── agents/
    ├── commands/
    ├── hooks/hooks.json      ← SessionStart, Stop 게이트
    └── scripts/
```

---

## 미결 질문

1. **Level 3 타이밍**: Level 2로 충분한지, 처음부터 플러그인으로 가야 하는지
2. **Stop 게이트**: 강제 중단 vs 경고만 — UX 트레이드오프
3. **Scope guard 민감도**: 완전 차단(exit 1) vs 경고(exit 0 + 메시지)
