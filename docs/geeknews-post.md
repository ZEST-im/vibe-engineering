# GeekNews 제출용

## 제목

Show GN: Vibe Coding 시대의 개발 관리 — AI가 알아서 기록하는 칸반보드

## URL

https://github.com/hoarchi/vibe-harness

## 본문
Jira 없이, Notion 없이, git만으로 팀 칸반이 돌아갑니다.
Vibe coding으로 개발하다 보면 "내가 뭘 했더라?"가 가장 큰 문제입니다. 
Vibe-Harness은 Claude Code와 연동되어, AI가 코딩하는 동안 진행 상황을 자동으로 칸반보드에 기록합니다.

**여러 프로젝트를 탭 하나로 관리하고, 팀원과 git pull/push만으로 칸반을 공유할 수 있습니다.** JSON 파일 저장이라 merge conflict도 일반 코드처럼 해결됩니다. 

**`git push`하면 AI가 코드 리뷰를 자동 실행합니다.** 보안(OWASP), 버그 리스크를 검토해서 CRITICAL/HIGH 이슈가 있으면 칸반보드의 Review 컬럼에 태스크를 자동 생성합니다. 리뷰 결과가 칸반에 남으니 누가 봐도 현재 상태를 알 수 있습니다.

작업 시작하면 `started_at` 자동 기록, 완료되면 `git diff`로 코드 변경량 측정, 변경 파일과 기술 결정 사항까지 작업 보고서로 남깁니다. 개발자는 코딩에만 집중하면 됩니다.

**왜 만들었나:**
- AI가 코드를 짜는 시대에, 진행 관리도 AI가 해야 한다고 생각해서
- PROGRESS.md를 수동으로 관리하는 게 번거로워서
- 기존 Jira/Notion은 Claude Code와 연동이 안 되니까

**주요 특징:**
- 멀티 프로젝트: 하나의 서버에서 여러 프로젝트를 탭으로 전환
- 멀티 유저: JSON 저장 → git pull/push로 팀 칸반 공유 (바이너리 충돌 없음)
- 자동 코드 리뷰: `git push` 시 CRITICAL/HIGH 이슈 자동 검토 → 리뷰 태스크 자동 생성
- Claude Code Skill로 동작: 태스크 생성/진행/완료를 AI가 알아서 기록
- Kanban + List 뷰: 드래그앤드롭, 인라인 편집, Dark/Light 모드
- 의존성 제로: Python 표준 라이브러리 + vanilla JS (npm, pip, 빌드 없음)
- localhost only: 외부 서버 없음, 완전한 프라이버시

설치: `git clone` + `python3 scripts/setup.py` (한 줄)

MIT 라이선스.
