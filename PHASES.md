## PHASE_MVP01 🚧 IN PROGRESS
> 멀티유저 안전성 확보 — DB 공유 규칙, 사용자 식별, JSON export/import

- [x] .gitignore: kanban.db 바이너리 파일 제외
- [x] 스키마: created_by, assigned_to 필드 추가 + 마이그레이션
- [x] SQLite: WAL 모드 + busy_timeout 설정 (동시 세션 안전)
- [x] API: /export (GET), /import (POST) — JSON 기반 공유
- [x] SKILL.md: export/import 커맨드 + 멀티유저 규칙 문서화
- [x] PHASES.md + CURRENT_PHASE.md 생성
- [ ] kanban.html: created_by/assigned_to UI 표시
