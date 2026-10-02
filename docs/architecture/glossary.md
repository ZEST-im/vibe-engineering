# 용어집 — vibe-engineering

> `/vibe-da` 산출물 (2026-09-29). **한 개념에 이름 하나.** 이 표에 없는 이름은 쓰지 않는다.
>
> 이 문서가 존재하는 이유는 사람이 아니라 **에이전트** 때문이다. 글로서리를 읽은 에이전트는
> 맞는 이름을 쓰고, 안 읽은 에이전트는 **세션마다 그럴듯한 새 이름을 하나씩 만든다.**
> 실제로 그렇게 됐다 — `02_data.md` §1④ 에 갈라진 이름 6개가 있다.
>
> 필드의 규범적 정의는 `skills/vibe-harness/references/task-schema.md` 가 정본이다.
> 여기는 **이름을 고정하는 표**이고, 그 문서와 어긋나면 그 문서가 이긴다.

## 엔티티

| 용어 | 코드 이름 | 정의 | 주인 |
|---|---|---|---|
| 프로젝트 | `project` | 보드 하나를 가진 레포. key 로 식별한다 | `server` |
| 태스크 | `task` | 사람이 하기로 한 일 한 덩어리. 보드의 카드 | `server` |
| 결정 | `decision` | 되돌리기 비싼 선택 + 다시 볼 조건 | `server` |
| 실행 | `run` | 에이전트가 한 번 돈 것. 토큰·모델·시간 | `reconcile_runs` |
| 페이즈 | `phase` | 일의 묶음. **엔티티가 아니라 task 의 문자열** | 사용자 |
| 스냅샷 | `snapshot` | 중앙(`os.zest.im`)으로 밀어 올린 사본 | `server` |

## 태스크 필드

`TASK_FIELDS` (22개) 가 코드상의 정본 목록이다. `id`·`created_at`·`updated_at` 은
서버가 발급하므로 그 목록 밖이다.

| 용어 | 코드 이름 | 정의 | 허용값 |
|---|---|---|---|
| 아이디 | `id` | `{접두어}{번호}`. **보드 안에서만 유일** | `hgA132` 형태 |
| 제목 | `title` | 한 줄 | 문자열, 필수 |
| 설명 | `description` | 무엇을 왜 — 착수 전에 쓴다 | 문자열 |
| 작업 보고 | `details` | 무엇을 했나 — 완료 시 필수 | 문자열 |
| 상태 | `status` | 아래 코드 집합 | **5종 고정** |
| 분류 | `category` | 아래 코드 집합 | 권장 12종 |
| 우선순위 | `priority` | | `high` · `medium` · `low` · `critical` |
| 소속 페이즈 | `phase` | `PHASE_{목적}{NN}` | 아래 코드 집합 |
| 담당자 | `assigned_to` | **사람.** `git config user.name` | 아래 사람 표 |
| 생성자 | `created_by` | **사람.** 에이전트 이름 금지 | 아래 사람 표 |
| 검수 메모 | `review` | 자유 텍스트. ⚠️ `status` 의 값 `review` 와 **이름이 겹친다** | 문자열 |
| 토큰 | `tokens_used` | 이 태스크 run 들의 합 | 정수 |
| 모델 | `models` | 완료 구간에 쓰인 모델. 자동 기록 | 문자열 배열 |
| 코드 증감 | `lines_added` / `lines_removed` | `git diff --numstat` | 정수 |
| 시각 | `created_at` · `updated_at` · `started_at` · `completed_at` | ISO-8601 **KST aware** | |
| 순서 | `position` | 열 안의 정렬. 정수/문자열 혼재 — 수치 강제변환 | |
| 목표일 | `target_date` | | `YYYY-MM-DD` |
| 선행 | `depends_on` | 먼저 끝나야 하는 task id 배열 | ⚠️ **실사용 0건** |
| 공개 | `share` / `share_note` | GitHub 이슈로 승격 여부 / 본문 | bool / 문자열 |
| 이슈 번호 | `issue` | 승격된 이슈 번호 | 정수 |

## 쓰지 않는 이름 — 이미 데이터에 있는 것

발견되면 정본 이름으로 고친다. 순서는 **expand → 둘 다 읽기 → 백필 → contract**.

| 쓰지 않는다 | 대신 | 지금 어디에 |
|---|---|---|
| `createdAt` · `updatedAt` · `startedAt` | `created_at` · `updated_at` · `started_at` | 프로젝트 A · 프로젝트 B |
| `detail` · `note` · `notes` · `result` | `details` | 프로젝트 C · 프로젝트 B |
| `goal` | `description` | 프로젝트 D |
| `agent_usage` | `runs.json` 의 run | 프로젝트 B |
| `date_label` | `target_date` | 프로젝트 A |
| `tags` | `category` · `phase` | 프로젝트 A |

## 코드 집합

### `status` — 5종. **코드가 막는다** (유일하게 지켜지는 집합)

| 값 | 뜻 |
|---|---|
| `backlog` | 하기로 했지만 이번이 아니다 |
| `todo` | 이번에 한다 |
| `in_progress` | 지금 한다. **사람당 하나만** |
| `review` | 끝났고 확인을 기다린다 |
| `done` | 끝났다. `completed_at`·`details`·`lines_*` 가 있어야 한다 |

### `category` — 권장 12종 (현재 데이터는 **40종**)

`backend` · `frontend` · `infra` · `data` · `docs` · `qa` · `feature` · `fullstack` ·
`product` · `review` · `content` · `ops`

새 값을 만들기 전에 위 12개 중 맞는 것이 없는지 본다. 없으면 만들되 **이 표에 추가한다.**

### `phase` 접두어 — 전역 규약 5종 (현재 데이터는 **39종**)

| 접두어 | 초점 |
|---|---|
| `SEED` | 초기 구조·스키마 |
| `MVP` | 핵심 기능. 동작 증명 |
| `PMF` | 피드백 기반 반복 |
| `SCALE` | 성능·아키텍처·AI |
| `GTM` | 출시·마케팅 — **실사용 0건** |

프로젝트가 자기 접두어를 만드는 것은 막지 않는다(`PIV`·`TEC`·`SOU` 등이 이미 있다).
다만 **같은 뜻을 두 접두어로 쓰지 않는다.**

### `priority`

`critical` > `high` > `medium` > `low`. `critical` 은 전역 규약에 없던 값이 데이터에서
자라난 것이다 — 여기서 정식으로 인정한다.

## 사람과 에이전트 — 다른 자리에 적는다

**`assigned_to`·`created_by` 는 사람이다.** 에이전트 귀속은 `runs.json` 의 `agent` 다.
지금 데이터의 **455건(17.0%)** 이 이 규칙을 어긴다.

| 사람 | 정본 이름 | 같은 사람의 다른 표기 |
|---|---|---|
| 레포 작성자 | `hogun` | `zest.hogun` · `hoarchi` — **한 사람이 세 이름으로 기록돼 있다** |
| 동료 3인 | 각자 하나씩 | (실명이라 공개 문서에 적지 않는다) |

| 에이전트 | `runs.json` 의 `agent` |
|---|---|
| Claude Code | `claude` |
| Codex | `codex` |
| Gemini | `gemini` |

⚠️ `프로젝트 E` · `프로젝트 E-web` 처럼 **프로젝트 이름이 소유자 필드에 들어간 것**이
55건 있다. 사람도 에이전트도 아니다.

## id 접두어 — 사람 + 머신

| 접두어 | 머신 |
|---|---|
| `hgA` | mac-studio |
| `hgB` | macbook |

**사람만으로는 부족하다** — 같은 사람이 두 머신에서 같은 보드에 쓰면 `next_id` 가 두 번
발급된다. 과거 id 는 바꾸지 않는다. 커밋 메시지와 결정 로그가 그 id 를 참조한다.

## 시간과 수 표기

| | 규칙 | 안 지키면 |
|---|---|---|
| 시각 | ISO-8601, **KST aware**. 나이브 값 금지 | UTC 로 읽혀 9시간 어긋난다 |
| 토큰 | 정수. 구성요소별(`input`/`output`/`cache_read`/`cache_write`)이 있으면 그것으로 비용 계산 | 평탄 합산은 비용을 약 7배 부풀린다 |
| 코드 증감 | 정수. `git diff --numstat` | |
| 텍스트 파일 | 열 때 `encoding` 명시 | Windows 에서 cp949 로 열린다 |

## 헷갈리는 이름

| 이름 | 무엇이 아닌가 |
|---|---|
| `review` | **둘이다** — `status` 의 값(상태)이자 필드(검수 메모, 자유 텍스트 144종) |
| `archive/` | **이력이 아니다.** 같은 현재 상태가 다른 파일로 옮겨진 것 |
| `runs.json` | 유일한 진짜 이벤트 로그. **append-only** — 필드 제거·개명 금지 |
| `schema.sql` | **가짜다.** 스크린샷용 데모 SQL. 이 시스템은 JSON 파일을 쓴다 |
| `version: 1` | `kanban.json` 에 있지만 **읽는 코드가 없다.** 장식이다 |
