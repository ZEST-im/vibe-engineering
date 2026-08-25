# vibe-engineering on Windows

vibe-engineering은 원래 macOS/Unix 설계다. server.py는 크로스플랫폼으로 맞췄지만,
**셸 훅과 LaunchAgent 자동화는 Windows에서 동작하지 않는다.** 이 문서는 Windows에서
무엇이 되고 무엇을 수동으로 해야 하는지 정리한다.

## TL;DR

- **server.py는 Windows에서 그대로 실행된다** (fcntl no-op shim + UTF-8 stdout, commit `b0eb1e4`).
- **토큰 사용량 수집도 Windows에서 동작한다.** `enroll.py` 가 작업 스케줄러에 등록한다
  (2026-08-24 이후). 그 전 버전은 자동 등록이 없었고 안내 문구가 Windows에 없는 cron을
  가리켰다 — `git pull` 로 최신을 받는다.
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

## 토큰 사용량 수집 (Windows)

macOS와 같은 명령을 쓴다. 자동 등록만 방식이 다르다.

```bat
:: 1) 이 컴퓨터 등록
python scripts\enroll.py --token <토큰> --machine <이름> --runs-schema 2

:: 2) 수집할 프로젝트 등록 — 이걸 빼면 아무것도 수집되지 않는다
python scripts\enroll.py --add-project codebook=C:\workspace\codebook

:: 3) 확인 후 전송
python scripts\reconcile_runs.py --all --dry-run
python scripts\reconcile_runs.py --all --push
```

`enroll.py` 는 작업 스케줄러에 `VibeHarnessReconcile` 작업을 만든다. `schtasks /Create /F` 라
같은 이름을 덮어쓰므로 재실행해도 작업이 두 개가 되지 않는다 (macOS의 고정 LaunchAgent
Label과 같은 규율). 확인·삭제는 이렇게 한다.

```bat
schtasks /Query /TN VibeHarnessReconcile
schtasks /Delete /TN VibeHarnessReconcile /F
```

권한 문제로 등록에 실패하면 `enroll.py` 가 실행할 명령을 그대로 출력한다. 관리자 권한
프롬프트에서 그 명령을 직접 실행하면 된다.

### `PYTHONUTF8=1` 은 이제 필요 없다

예전에는 이걸 붙이지 않으면 cp949 콘솔에서 `UnicodeEncodeError` 로 죽었다. 원인은 스크립트
출력에 쓰인 `—`(em dash, U+2014)가 cp949에 없어서였다. 지금은 `enroll.py` 와
`reconcile_runs.py` 가 시작할 때 stdout/stderr를 UTF-8로 재설정한다 (`server.py` 와 동일).

같은 계열의 더 조용한 버그도 함께 고쳤다. transcript를 열 때 인코딩을 지정하지 않아
Windows 기본 인코딩으로 UTF-8 바이트를 읽었고, `errors="ignore"` 가 깨진 바이트를 버려서
**JSON 파싱이 실패한 줄이 통째로 누락**됐다. 크래시가 아니라 조용한 과소집계라 더 나빴다.
`tests/test_windows_compat.py` 가 두 경우를 macOS/Linux에서도 재현되는 형태로 고정한다.

### 토큰 파일 권한

`~/.claude/skills/vibe-harness/sync.json` 에는 개인 토큰이 들어간다. 스크립트는 `0600` 으로
기록하지만 **Windows는 POSIX 권한을 적용하지 않아 실제로는 보호되지 않는다** (`-rw-r--r--`
로 보인다). 계정 밖에서 접근 가능한 위치에 프로필을 두지 않는 것으로 대신한다.

### `runs.json` 을 실수로 커밋하지 않기

프로젝트에 따라 `vibe-harness/runs.json` 이 git에 추적되지 않는 상태일 수 있다. 사용량이
계속 갱신되는 파일이라 커밋 노이즈가 되기 쉽다. 커밋하지 않을 프로젝트라면 그 리포의
`.gitignore` 에 넣어두는 편이 안전하다. 시크릿은 들어 있지 않다 — 세션 id·날짜·모델명·
토큰 수·비용·머신 라벨뿐이다.

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
