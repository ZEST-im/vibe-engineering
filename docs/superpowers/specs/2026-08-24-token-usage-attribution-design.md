# 토큰 사용량 사람별 귀속 — 설계

작성 2026-08-24 · Phase PHASE_PMF07 · 칸반 #57

## 문제

여러 머신을 교차 사용하는 사람이 있고(한 사람이 2대), 여러 사람이 같은 프로젝트를
작업한다. "이 사람이 일주일에 토큰을 얼마나 쓰나"를 물었을 때 답할 데이터가 없다.

### 지금 상태 (측정)

머신 간 합산은 **이미 동작한다.** `reconcile_runs.py` 가 `session_id` 로 중앙에서
union 하도록 설계돼 있고, `reconcile.log` 가 그것을 증명한다:

| 프로젝트 | 이 머신이 보낸 | 중앙 총계 |
|---|---:|---:|
| 제품 C | (비공개) | (비공개) |
| 제품 B | (비공개) | (비공개) |
| 제품 A | (비공개) | (비공개) |

중앙에 이 머신 것보다 많이 쌓여 있다 = 다른 출처의 데이터가 이미 들어와 있다.

빠진 것은 합산이 아니라 **귀속(attribution)** 이다. run 레코드에 owner 필드가 없다.
`_canon_user()` 는 task 의 `created_by` / `assigned_to` 에만 적용되고 run 에는 붙지
않는다. 그래서 팀 총합은 나오지만 사람별 분해가 불가능하다.

부수적으로 발견된 두 가지:

1. **3시간마다 전량 재전송.** `ingested: 108, 신규 0건` 이 하루 8회 반복된다. 새 정보
   0건인데 108 레코드를 매번 POST 한다. 직원 수 × 프로젝트 수로 선형 증가한다.
2. **일별 정확도가 없다.** run 의 `ts` 가 파일 mtime 이라, 여러 날에 걸친 세션은
   마지막 날에 전액이 몰린다.

## 결정 사항

| 항목 | 결정 | 근거 |
|---|---|---|
| 신원 출처 | **zestim 발급 개인 토큰** | 서버가 토큰으로 owner 판정 → 위조 불가, 퇴사 시 개별 폐기 가능 |
| 프로비저닝 | **신규 `scripts/enroll.py`** | `setup.py` 는 훅 중복 등록 이력으로 scope-lock |
| 금액 기준 | **API 정가 환산 유지** | 사람·일자마다 같은 자로 재야 레이스 순위가 왜곡되지 않음 |
| 금액 레이블 | **부연 없이 금액만 표시** | 사용자 결정 (2026-08-24) |
| 머신 축 | **대시보드에 노출하지 않음** | 요구가 "교차 사용 합산" 이므로 `machine` 은 운영·디버그용 |
| 개인별 공개 범위 | **전 직원에게 공개** | 레이스 토글이 전 직원 비교이므로 |

## 아키텍처

```
[직원 머신 N대]
  transcript(.jsonl)
    → reconcile: (세션 × 일자)로 분해, machine 라벨 부착
    → 로컬 runs.json (세션 단위, append-only — 현행 유지)
    → 변경된 행만 POST /runs  [Authorization: Bearer <개인 토큰>]
                                    │
[zestim 중앙]                       ▼
  토큰 → owner 판정 (클라이언트 신고 owner 무시)
    → upsert key = (owner, session_id, date)
                                    │
[AX project 개인 대시보드]           ▼
  최상단 레이스 패널: 기본 = 나, 클릭 토글 = 전 직원
```

경계 세 개:

- **머신은 사실만 보고한다** — 토큰 수, 일자, 프로젝트, 머신 라벨. 자기가 누구인지
  주장하지 않는다.
- **중앙이 신원의 authority다** — owner 는 토큰에서만 나온다.
- **대시보드는 읽기 전용이다** — 집계 쿼리만. 수집 로직을 대시보드에 넣지 않는다.

## 데이터 모델 — 생산자 하나, 투영 두 개

로컬 `runs.json` 에 일자별 분해를 그대로 적용하면 기존 dateless 레코드(세션 전체 T)와
신규 일자별 레코드(a + b = T)가 **이중 계상**된다. 그리고
`test_write_leaves_file_byte_identical_when_nothing_new` 불변식이 깨진다.

그래서 정밀도가 필요한 쪽에만 정밀도를 준다:

| | 로컬 `runs.json` | 중앙 저장소 |
|---|---|---|
| granularity | 세션 단위 (현행 유지) | (세션 × 일자) |
| 키 | `session_id` | `(owner, session_id, date)` |
| 마이그레이션 | 불필요 | 신규 컬럼, legacy 는 `date=NULL` |
| 불변식 테스트 | 그대로 통과 | — |

합계는 동일하다(일자별 합 = 세션 합). 정밀도만 다르다.

### 일자 버킷팅

메시지별 `timestamp` 를 **KST 달력 날짜**로 버킷한다. 이 머신의 전체 transcript
25,049 개 usage 메시지 중 timestamp 누락은 0 이었다. `tz` 가 없는 경우는 KST 로 본다.

## 중앙 API 계약 (zestim 구현 대상)

### 요청

```
POST /api/internal/vibe-harness/runs
Authorization: Bearer <개인 토큰>
Content-Type: application/json

{
  "project": "codebook",
  "schema": 2,
  "machine": "mba-01",
  "runs": [
    {
      "session_id": "8d3d8ee8-73d7-4ee2-8033-ceafb47c8791",
      "date": "2026-08-19",
      "agent": "claude",
      "model": "claude-opus-5",
      "tokens": 21856005,
      "input_tokens": 240,
      "output_tokens": 154283,
      "cache_read_tokens": 20707263,
      "cache_write_tokens": 994219,
      "cost_usd": 39.2173,
      "machine": "mba-01",
      "source": "transcript-daily"
    }
  ]
}
```

### 서버 규칙

1. **owner 는 토큰에서 판정한다.** 페이로드에 `owner` 가 있어도 무시한다. 토큰이
   유효하지 않으면 401.
2. **upsert key = `(owner, project, session_id, date)`.** 같은 키가 오면 수치 필드를
   더 큰 값으로 올린다(`reconcile_runs.MERGE_MAX_FIELDS` 와 같은 규칙). 세션 도중
   보낸 값이 과소집계일 수 있어서다.
3. **`schema` 가 없으면 기존(세션 단위) 형식이다.** 현재 라이브 트래픽이 이것이므로
   반드시 계속 받아야 한다.
4. `machine` 은 저장하되 대시보드 집계 축으로 쓰지 않는다.

### 응답

```json
{"ok": true, "project": "codebook", "ingested": 3, "total_runs": 124}
```

### 마이그레이션

- 기존 레코드: `owner = NULL`, `date = NULL` 로 남긴다. 삭제하지 않는다.
- 전환 순서가 중요하다: **중앙이 schema 2 를 받을 수 있게 된 뒤에** 각 머신의
  `sync.json` 에 `runs_schema: 2` 를 켠다. 클라이언트가 먼저 바뀌면 전사 수집이
  조용히 멈춘다. 그래서 클라이언트 기본값은 schema 1 이고, 옵트인만 허용한다.
- 백필: 보존 기간(기본 30일) 안쪽 transcript 는 `--force-full-push` 로 회수 가능하다.
  그 밖은 영구 손실이다.

## 증분 push

로컬 `push-state.json` 에 프로젝트별로 `{"session_id|date": "tokens:cost"}` 지문을
둔다. 변경된 행만 보낸다.

- 지난 날짜 행은 확정되면 다시 안 바뀌므로, 정상 상태에서는 **오늘 행만** 전송된다.
- **전송 성공 이후에만** 상태를 갱신한다. 실패한 전송을 보냈다고 적으면 그 행은 영구
  유실된다 (`test_state_is_not_saved_when_push_fails`).
- 복구용 `--force-full-push` 로 상태를 무시하고 전량 재전송할 수 있다.

## 출퇴근 도장 연계 (day-close)

개인 대시보드에 이미 출근/퇴근 도장이 있다. 이것을 수집 트리거로 쓰자는 아이디어에는
방향 제약이 있다: **서버가 직원 머신으로 요청할 수 없다** (NAT·방화벽 뒤).

세 갈래로 나눈다:

1. **증분 push** — 낭비의 본질은 주기가 아니라 전량 재전송이다. 출퇴근과 무관하게
   지금 낭비가 사라진다. **구현 완료.**
2. **퇴근 도장 = day-close 신호** — 일자별 레코드는 그 날이 끝나야 확정된다. 퇴근
   도장이 그 사람의 그 날 확정 신호가 되면, 대시보드가 미확정 일자를 재계산하지 않아도
   된다. 레이스는 확정된 날만 그린다. **zestim 측 후속.**
3. **트리거** — 에이전트가 zestim 의 가벼운 상태 엔드포인트를 폴링해 퇴근 감지 시
   마지막 수집 1회. 또는 퇴근 도장을 머신 CLI 에서 찍게 한다(즉시 트리거, 단 근태 UX
   변경). **후속, 1·2 이후.**

## 대시보드 레이스 패널 (zestim 구현 대상)

AX project 개인 대시보드 최상단.

- 데이터: `사람 × 일자 × cost_usd` 를 주간으로 롤업.
- 기본 상태: 본인 레인만.
- 클릭 토글: 전 직원 레인 비교.
- 금액은 숫자만 표시한다. 기준 설명 문구를 붙이지 않는다.
- 확정되지 않은 날(퇴근 도장 전)은 레이스에서 제외하거나 흐리게 처리한다.

필요한 집계 엔드포인트:

```
GET /api/internal/vibe-harness/usage?scope=me|all&from=YYYY-MM-DD&to=YYYY-MM-DD
→ [{"owner": "hogun", "date": "2026-08-19", "cost_usd": 39.21, "tokens": 21856005}, ...]
```

`scope=all` 은 전 직원 공개이므로, 사내 인증을 통과한 요청에만 응답한다.

## 프로비저닝

`scripts/enroll.py` — 재실행 안전(idempotent).

```
python3 scripts/enroll.py --token <zestim 발급 토큰>
python3 scripts/enroll.py --token <토큰> --machine studio-02
python3 scripts/enroll.py --repair       # 에이전트 경로만 교정
python3 scripts/enroll.py --dry-run --token t
```

하는 일:

1. `projects.json` 이 없으면 빈 것으로 생성. 있으면 **절대 덮지 않는다.**
2. `sync.json` 에 토큰·endpoint 기록 (`0600`). `dashboards` 등 기존 키는 보존한다.
3. launchd 에이전트 설치/교정. `Label` 이 고정이라 재실행해도 중복되지 않는다.
   인터프리터는 `/usr/bin/python3` (Homebrew python 업그레이드에 깨지지 않게 —
   `reconcile_runs.py` 는 stdlib only).
4. macOS 외 플랫폼은 자동 등록 대신 실행할 명령을 출력한다.

`setup.py` 는 건드리지 않는다 (scope-lock).

### 입·퇴사 절차 연계

- **온보딩**: `employee-onboarding` 스킬 체크리스트에 "vibe-harness 토큰 발급 +
  `enroll.py` 실행" 항목 추가. 빠지면 그 사람은 대시보드에서 조용히 누락된다.
- **오프보딩**: `employee-offboarding` 스킬에 "vibe-harness 개인 토큰 폐기" 추가.
  `is_active` 만 내리고 토큰을 살려두면 그 머신은 계속 전송한다.

## 알려진 위험

| 위험 | 내용 | 대응 |
|---|---|---|
| 보존 기간 | `cleanupPeriodDays` 미설정 → 기본 30일. 머신이 그 이상 꺼져 있으면 그 구간 영구 손실 | 각 머신에서 값을 올린다. enroll.py 범위 밖(전역 settings) |
| 전환 순서 | 클라이언트가 중앙보다 먼저 schema 2 로 가면 수집 중단 | 기본값 schema 1, 명시적 옵트인만 |
| 개인정보 | 개인별 금액이 전 직원에게 공개된다 | 조직 정책 결정. `PRIVACY.md` 는 현재 scope-lock 이라 이 Phase 에서 수정하지 않음 — 반영 필요 |
| 정가 환산 | 실제 구독 지출과 다른 숫자다 | 사용자 인지 확인됨. 경영 지표로 쓰려면 별도 배분 로직 필요 |
| 머신 라벨 | hostname 에 실명이 들어갈 수 있다 | 사내 중앙으로만 전송되고 공개 레포에는 들어가지 않음. `--machine` 으로 override 가능 |

## 스코프 밖 / 후속

- zestim(Rails) 측 토큰 발급·관리 화면, `/runs` schema 2 수용, 집계 엔드포인트,
  레이스 패널 렌더링 — 별도 레포·별도 CI
- day-close 트리거 (위 2·3항)
- 태스크 `started_at` / `completed_at` 이 비는 문제 (#49 와 동일 증상, 이번 #57 생성
  시에도 `started_at` 이 비었다) — 별도 태스크로 분리 필요

## 테스트

| 파일 | 개수 | 다루는 것 |
|---|---:|---|
| `tests/test_reconcile_daily.py` | 23 | 일자별 분해, KST 경계, 합 보존, owner 미주장, 증분 지문, 머신 라벨 |
| `tests/test_reconcile_push.py` | 14 | 증분 전송, 실패 시 상태 미저장, force-full, 프로젝트 격리, schema 1 하위호환 |
| `tests/test_enroll.py` | 34 | 설정 병합·보존, plist 생성·멱등, 0600 권한, 레지스트리 미파괴, 인터프리터 선택 |

전체 139 tests 통과 (기존 68 + 신규 71). `ruff==0.16.3` clean, `compileall` OK.

---

# 정정 및 구현 결과 (2026-08-24, 중앙 측)

zestim 실제 구조를 확인하고 나서 위 설계의 세 가지를 정정한다.

## 정정 1 — DB 가 아니라 GCS JSON 이다

`중앙 `/runs` 핸들러` → `중앙 수집 모듈` → `중앙 오브젝트 스토리지 모듈`.
저장은 `vibe-harness/runs/{project}.json` 이고 동시성은 GCS precondition(generation)으로
직렬화된다. **마이그레이션이 없다.** 위에서 "신규 컬럼" 이라 쓴 것은 JSON 필드 추가로
읽으면 된다. zestim 은 Next.js 앱이다(Rails 아님).

## 정정 2 — owner 는 Discord uid 다

`중앙 수집 모듈` 의 `사람 매핑 테이블` 이 이미 Discord uid → 별칭 매핑을 갖고 있고,
개인 대시보드(`app/my/dashboard`)가 uid 기반으로 동작한다. owner 를 uid 로 저장하면
`scope=me` 필터가 기존 구조에 그대로 붙는다. 별칭은 표시할 때 해석한다.

토큰 발급은 `harnessPersonMapped(uid)` 를 통과해야 한다 — 귀속 대상 없는 토큰을 만들지
않는다. 신규 입사자는 `사람 매핑 테이블` 등록이 선행이며, 이 항목이 온보딩 체크리스트에
들어가야 한다.

## 정정 3 — 이중 계상 규칙이 빠져 있었다 (중요)

legacy 세션 행을 지우지 않기로 했으므로, 같은 세션에 일자별 행이 생기면 저장소에 둘이
공존한다. 그대로 합산하면 **같은 사용량이 두 번 더해진다**(세션 전체 T + 일자별 a+b=T
= 2T). 테스트로 실증했다: 고치기 전 `expected 600 to be 300`.

규칙: **일자별 행이 있는 세션의 legacy 행은 집계에서 제외한다** (`effectiveRuns`).
저장은 그대로 두고 읽을 때만 고른다.

같은 함수에서 일별 버킷도 고쳤다. 기존 `tokenVelocityFromRuns` 는 `run.ts` 앞 10자로만
날짜를 잡아서, `ts` 가 없는 일자별 행이 일별 추이에서 통째로 빠졌다. `date` 를 우선
본다.

## 함께 고친 잠재 결함

`ingestRuns` 가 `map.set(session_id, run)` 으로 통째로 덮어쓰고 있었다. 세션 도중
기록된 과소집계 값이 나중에 도착하면 완전한 값을 지운다. `mergeRuns` 로 바꿔 수치
필드는 큰 쪽을 남기고, 빈 문자열이 기존 `commit` 을 지우지 않게 했다.

## 구현된 것 (zestim)

| 파일 | 내용 |
|---|---|
| `중앙 토큰 레지스트리 모듈` | 개인 토큰 레지스트리. GCS `vibe-harness/tokens.json`, **sha256 해시만 저장**, 폐기는 `revoked_at` 기록(레코드 유지) |
| `중앙 병합 모듈` | `runKey` / `mergeRuns`(max-merge) / `prepareIncomingRuns`(owner 도장·필드 화이트리스트) / `effectiveRuns`(이중 계상 제거) |
| `중앙 `/runs` 핸들러` | 개인 토큰 → owner 판정. schema 2 는 개인 토큰만. 공유 secret 은 schema 1 로 계속 동작 |
| `중앙 `/tokens` 핸들러` | 발급(POST)·조회(GET)·폐기(DELETE). 관리자(공유 secret)만. **개인 토큰에는 발급 권한 없음** |
| `중앙 수집 모듈` | `HarnessRun` 에 `owner`/`date`/`machine` 추가, `ingestRuns`·`tokenVelocityFromRuns` 수정 |

테스트 88개 추가 (전체 258 passed). 라우트를 직접 실행하는 테스트로 인가 배선을
고정했다 — 이 리포의 기존 규약이고, 실제로 그 테스트가 "클라이언트가 보낸 owner 가
그대로 저장된다" 는 위조 구멍을 잡았다(`expected 'u9' to be undefined`).

## 남은 것

- **집계 엔드포인트** `GET /api/internal/vibe-harness/usage?scope=me|all` — 아직 없다
- **레이스 패널** — `app/my/dashboard` 최상단. `ProjectPanel.tsx` 가 `AxDashboard` 를
  렌더하는 자리 위
- **각 머신 전환** — `enroll.py --token <발급받은 토큰>` 실행 후 `runs_schema: 2` 켜기.
  순서를 지켜야 한다(중앙 배포 → 머신 전환)
- **day-close** — 퇴근 도장을 그 날 확정 신호로 쓰는 것

---

# 3번 — 집계 엔드포인트와 레이스 패널 (구현 완료)

## 인증 경계를 바꿨다

위에서 집계 엔드포인트를 `/api/internal/vibe-harness/usage` 로 적었는데, `internal` 은
머신 대 머신(공유 secret) 경로다. 이건 **사람이 부르는** 엔드포인트라 앱 인증을 써야
한다. 실제 위치:

```
GET /api/my/dashboard/token-usage?scope=me|all&from=&to=&today=
```

`중앙 인증 모듈` 의 `myUid(req)` 가 Discord uid 를 주고, 그게 run 의 `owner` 와 같은
키다. 그래서 필터가 그냥 `r.owner === viewer` 다.

`scope=me` 는 뷰어 자신으로 **고정**한다. `owner` 파라미터로 남의 것만 조회하는 경로를
두지 않았다. 전원 비교는 `scope=all` 로 명시적으로 켠다.

## 집계 규칙

| 항목 | 규칙 |
|---|---|
| 대상 행 | `owner` 와 `date` 가 모두 있는 일자별 행만. legacy 행은 owner 가 없어 사람 레인에 못 들어간다 |
| 중복 | 프로젝트 단위로 `effectiveRuns` 를 먼저 적용 |
| 머신 | 합산된다. `owner` 가 같으면 한 레인 — 2대 교차 사용이 여기서 해결된다 |
| 범위 | 기본은 오늘이 속한 주(월~일, KST). 최대 92일 |
| 정렬 | 날짜 → 사람 |
| 레인 | 누적. 데이터 없는 날은 직전 값 유지(레이스는 뒤로 가지 않는다) |

프로젝트 목록은 `loadHarnessSnapshot('ax-project').sources` 에서 온다. 요청당 프로젝트
수만큼 GCS 읽기가 발생하므로 `Promise.all` 로 병렬화하고 범위 상한을 뒀다.

## 패널

`app/my/dashboard/components/TokenRaceSection.tsx` — 개인 대시보드 최상단(인사말 바로
아래, 핵심 업무 위). 기본 `scope=me`, 버튼으로 `all` 토글.

- 주의 첫날부터 하루씩 전진하며 레인이 늘어난다(420ms/일). 끝나면 멈추고 ↻ 로 재생.
- 하단 날짜 칩을 누르면 그 날로 점프한다.
- 뷰어 레인은 굵게·진한 색으로 구분한다.
- **금액은 숫자만 표시한다.** 기준 설명 문구를 붙이지 않는다.

계산은 전부 `중앙 집계 모듈` 에 있고 컴포넌트는 그리기만 한다 — 이 리포의 vitest
는 `lib/**` 만 수집하므로, 로직이 lib 에 있어야 테스트가 붙는다.

## 최종 상태

| 리포 | 테스트 | 비고 |
|---|---:|---|
| vibe-engineering | 139 | 커밋됨 (`dad1ded`) |
| zestim | 298 | 미커밋 |

zestim 신규 테스트 128개. `tsc --noEmit` 은 제 코드에서 에러 0(남은 2건은 `.next/types`
고아 생성물, gitignore).

## 아직 남은 것

- **각 머신 전환** — 중앙 배포 후 `enroll.py --token <발급 토큰>` 2대 실행 →
  `sync.json` 에 `runs_schema: 2`. 순서를 반드시 지킨다.
- **day-close** — 퇴근 도장을 그 날 확정 신호로. 지금은 오늘 행도 그대로 그린다.
- **`cleanupPeriodDays`** — 기본 30일. 머신이 그 이상 꺼지면 그 구간 영구 손실.
- **`PRIVACY.md`** — 개인별 금액이 전 직원에게 공개되는 설계. scope-lock 이라 미반영.
- **온보딩·오프보딩 체크리스트** — `사람 매핑 테이블` 등록 + 토큰 발급 / 토큰 폐기.
