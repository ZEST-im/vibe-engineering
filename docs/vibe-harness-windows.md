# vibe-engineering on Windows

vibe-engineering은 원래 macOS/Unix 설계다. server.py는 크로스플랫폼으로 맞췄지만,
**셸 훅과 LaunchAgent 자동화는 Windows에서 동작하지 않는다.** 이 문서는 Windows에서
무엇이 되고 무엇을 수동으로 해야 하는지 정리한다.

## TL;DR

- **server.py는 Windows에서 그대로 실행된다** (fcntl no-op shim + UTF-8 stdout, commit `b0eb1e4`).
- **`.sh` 훅 5종 + LaunchAgent 자동시작은 비활성**이다. 이들이 자동화하던 규율은 수동 이행한다.
- 데이터(source of record)는 어차피 평범한 JSON 파일이라 플랫폼 무관하게 직접 편집 가능하다.

## 되는 것

- `vibe-harness/kanban.json`, `decisions.json`, `runs.json` 직접 편집 (기본 경로).
- 서버 + 웹 UI: `python scripts\server.py serve 4242` → http://localhost:4242/kanban
- 모든 REST API (`/tasks`, `/decisions`, `/runs`, `/velocity`, `/context`, `/phase-check` …).
- 종류별 단가 비용모델, 관대한 phase 파서 등 로직 전부.

## 안 되는 것 (그리고 수동 대체)

| 훅 (macOS) | 이벤트 | 자동화하던 일 | Windows 수동 대체 |
|---|---|---|---|
| session-start | SessionStart | `CURRENT_PHASE.md` 로드·주입 | 세션 시작 시 `private/` → 루트 → `docs/` 순으로 `CURRENT_PHASE.md` 직접 읽기 |
| scope-guard | PreToolUse | Do NOT touch 편집 차단 | `CURRENT_PHASE.md`의 `Do NOT touch` / `SCOPE_LOCK` 블록 수동 준수 |
| review | PostToolUse | git push 후 코드리뷰 | push 후 직접 코드리뷰 |
| stop-gate | Stop | `in_progress` 잔여 경고 | kanban 수동 확인 |
| token-collector | SessionEnd | 실측 토큰 → `runs.json` 자동기록 | 세션 종료 시 recorder 수동 호출 (아래) |

**보류 이유**: Windows에 `python3`/`jq`/`launchctl`이 기대한 형태로 없고, PreToolUse 훅이
오작동하면 편집이 통째 차단될 위험이 있어서다. 훅을 억지로 켜기보다 규율을 수동 이행한다.

## 서버 실행 (Windows)

```bat
:: 시작 (포트 생략 시 4242)
python scripts\server.py serve 4242

:: 프로젝트 등록
python scripts\server.py register <key> <name> <C:\abs\path\to\project\vibe-harness>

:: 재시작: 실행 중 python 프로세스 종료(Ctrl+C 또는 작업관리자) 후 serve 재실행
```

- launchd(LaunchAgent) 대신 로그인 자동시작이 필요하면 **작업 스케줄러**나 시작프로그램
  바로가기로 위 `serve` 명령을 걸면 된다 (선택).

## 수동 토큰 기록 (SessionEnd 훅 대체)

recorder는 크로스플랫폼 Python이라 Windows에서도 직접 호출된다:

```bat
:: Codex 등 usage를 아는 경우
python %USERPROFILE%\.claude\hooks\vibe-harness-record-run.py ^
  --agent codex --model gpt-5-codex --tokens 297469 --cwd .

:: Claude Code 세션 트랜스크립트에서 실측 합산
python %USERPROFILE%\.claude\hooks\vibe-harness-record-run.py ^
  --agent claude --from-transcript <세션.jsonl 경로> --session-id <id> --cwd .
```

recorder가 프로젝트/`in_progress` 태스크/커밋을 자동 resolve하고, 서버가 떠 있으면
POST, 아니면 `runs.json`에 직접 append한다.

## 인코딩 (cp949)

server.py가 stdout/stderr를 UTF-8로 강제한다. 그래도 콘솔에서 한글/em대시가 깨지면:

```bat
chcp 65001
set PYTHONUTF8=1
```

## upgrade 주의 (해결됨)

크로스플랫폼 패치는 이제 **상류 server.py에 반영**되어 있다(`b0eb1e4`). 따라서
`setup.py upgrade`가 이 패치를 덮지 않는다. (과거엔 로컬 패치가 덮여 재적용이 필요했음.)

## 참고

- 비-Claude 에이전트(Codex 등)용 하네스 룰은 저장소 루트 `AGENTS.md` 참조.
- Phase 관리 규약·명령은 `skills/vibe-harness/SKILL.md`의 Phase Management 절 참조.
