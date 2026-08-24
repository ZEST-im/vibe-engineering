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
