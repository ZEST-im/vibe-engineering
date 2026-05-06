## Now: PHASE_MVP01
## Scope: 멀티유저 안전성 — schema, export/import, UI, .gitignore
## Done when:
- [x] kanban.db가 .gitignore에 포함
- [x] created_by/assigned_to 스키마 마이그레이션
- [x] WAL + busy_timeout 설정
- [x] export/import API 엔드포인트
- [x] SKILL.md 멀티유저 규칙 문서화
- [ ] kanban.html에 created_by/assigned_to 표시
## Do NOT touch:
<!-- SCOPE_LOCK_BEGIN -->
<!-- SCOPE_LOCK_END -->
서버 아키텍처 변경 (PostgreSQL 전환 등), 인증/로그인 시스템, WebSocket/SSE 실시간 동기화, task_history 감사 로그 테이블
