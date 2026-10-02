# 애플리케이션 아키텍처 — vibe-engineering

> `/vibe-aa` 로 작성 (2026-09-29). 입력: `docs/architecture/00_solution.md` (있음),
> `02_data.md` (없음 — `vibe-sa` 가 `vibe-da` 를 건너뛰기로 했다),
> `docs/planning/02_requirements.md` (없음), 코드(있음).
>
> **산출물은 다이어그램이 아니라 `tests/test_module_boundaries.py` 다.** 문서만 있는
> 경계는 일주일 안에 넘어간다.

## 1. As-is — 정적 import 가 거짓말을 한다

의존 그래프를 `import` 문에서만 뽑으면 이렇게 보인다.

```
server → reconcile_runs, vibe_runtime
reconcile_runs → vibe_runtime
enroll, install_reconcile → vibe_runtime
나머지 7개 → 없음          순환: 없음
```

**사실이 아니다.** 이 레포는 `importlib.spec_from_file_location` 으로 동적 로드를 쓰고
`subprocess` 로 자기 스크립트를 부른다. 그 간선은 AST 의 `import` 문에 없다.

| 실제 간선 | 방식 | 정적 분석에 보이나 |
|---|---|---|
| `kanban_edit` → `server` | `importlib` | **아니오** |
| `enroll` → `setup` | `importlib` | **아니오** |
| `server` → `reconcile_runs` | 둘 다 | 예 |
| `check` → worktree-guard | `importlib` | 아니오 |

세 종류(정적·동적·프로세스)를 모두 세어도 **순환은 없다.** 구조 자체는 건강하다.

### 진짜 문제는 한 파일이다

| 파일 | 줄 | 함수 |
|---|---|---|
| `server.py` | **3,308** | **131** |
| `gh_surface.py` | 1,245 | — |
| `reconcile_runs.py` | 1,041 | — |

`server.py` 안에 최소 아홉 개의 관심사가 섞여 있다 — 보드 CRUD · 결정 로그 · 아카이브 ·
컨텍스트/뷰 · 중앙 동기화 · 비용/토큰 · 실행 런타임 · HTTP 핸들러 · 프로젝트 등록.

**그러나 지금 쪼개지 않는다.** 쪼갤 이유를 댈 수 없다 — 사용자 1인, 배포는 파일 복사,
팀 병렬 작업 없음. `/vibe-aa` 의 기본("이유를 댈 수 있을 때만 쪼갠다")을 그대로 적용한다.
쪼개는 대신 **경계가 더 나빠지지 않도록 검사를 건다.**

## 2. 배포 단위

**하나.** 모듈형 단일체. 설치는 파일 복사이고 런타임 의존성이 없다(표준 라이브러리만).

쪼갤 근거로 인정되는 것 — 다른 배포 주기, 독립 출시가 필요한 별도 팀, 격리 요구 — 중
해당하는 것이 없다. `"확장할지도 모른다"` 는 이유가 아니다.

## 3. 모듈

| 모듈 | 소유 | 노출 | 의존해도 되는 것 |
|---|---|---|---|
| `vibe_runtime` | 실행 잠금·정책 | 런타임 원시연산 | **없음 (잎)** |
| `setup` | 설치 목록의 정본(`SKILLS`) | 설치·제거 | **없음 (빈 머신에서 돈다)** |
| `reconcile_runs` | transcript 해석, 토큰·모델·비용 | 수집 API, 요율표 | `vibe_runtime` |
| `server` | 보드·결정·스냅샷·HTTP | 보드 함수, 동기화 | `reconcile_runs`, `vibe_runtime` |
| `kanban_edit` | 서버 없는 보드 편집 | CLI | `server` (의도된 재사용) |
| `enroll` | 머신 등록·설치본 갱신 | CLI | `vibe_runtime`, `setup` |
| `search` · `worker` · `review_sync` · `gh_surface` · `check` · `install_reconcile` | 각자 | CLI | 잎이거나 `vibe_runtime` |

## 4. 의존 방향

```
              kanban_edit ──⇢ server ──→ reconcile_runs ──→ vibe_runtime
                                  └──────────────────────────↗
  enroll ──⇢ setup                enroll ──────────────────→ vibe_runtime
  (→ 정적  ⇢ 동적)                install_reconcile ───────→ vibe_runtime
```

비순환이다. `vibe_runtime` 이 바닥이고 아무것도 부르지 않는다.

## 5. 계약

| 계약 | 사이 | 방식 | 주인 | 변경 규칙 |
|---|---|---|---|---|
| 보드 파일 | 모든 도구 ↔ `{project}/vibe-harness/*.json` | JSON 파일 | `server` | `task-schema.md` 가 정본. 필드 추가는 자유, 제거·개명은 금지 |
| `runs.json` | 수집 ↔ 중앙 | JSON, **append-only** | `reconcile_runs` | 기존 필드 제거·개명 금지 |
| 설치 목록 | `setup` → `enroll` | `SKILLS` 상수 | `setup` | **한 곳에서만 정한다.** 두 번째 목록을 두면 갈라진다 |
| 스냅샷 전송 | `server` → `os.zest.im` | HTTP, key 단위 upsert | zestim(별개 레포) | source 단위로 쪼개 보낸다 |
| 상태 전이 | `kanban_edit` → `server._update_task` | 함수 호출 | `server` | 전이 규칙은 한 구현만 |

**`kanban_edit ⇢ server` 를 금지하지 않는 이유:** id 발급과 상태 전이를 두 번 구현하면
갈라진다. 실제로 갈라져서 CLI 로 닫은 태스크의 `completed_at` 이 비는 사고가 났고,
경로를 합쳐서 닫았다. 금지하면 사람이 검사를 끄거나 구현을 복제한다.

## 6. 구조에 영향을 주는 표준

- **읽기 실패는 전이를 막지 않는다.** 기록은 부산물이다 — 못 읽으면 빈 값으로 비켜선다
- **모르는 필드는 버리지 않는다.** `server` 는 화이트리스트지만 `kanban_edit` 은 통과시킨다.
  `gh_surface` 가 이슈 번호를 그렇게 적는다
- **텍스트 파일은 `encoding` 을 명시한다.** 빠뜨리면 Windows 에서 cp949 로 열린다
- **시각은 KST aware.** 나이브 값을 UTC 로 읽으면 9시간 어긋난다

## 7. 강제

`tests/test_module_boundaries.py` — 기존 테스트 스위트 안에서 돈다(CI 포함).

넷을 막는다. **전부 문서에 이미 규정으로 있고 지금 지켜지는 것**이다. 새 규칙을 발명하지
않았다.

1. 순환 없음 (동적 간선 포함)
2. `vibe_runtime` 은 잎 — 여기 의존이 생기면 "모든 것이 의존하는 utils" 가 된다
3. `setup` 은 로컬 의존 없음 — 빈 머신에서 도는 설치 스크립트다
4. 수집·검색은 `server` 에 의존하지 않음 — *"서버가 꺼져 있어도 정상"* 이 규정이다

### 위반 주입으로 확인했다

| 주입 | 잡힌 검사 |
|---|---|
| `vibe_runtime` 에 `import search` | 잎 규칙 |
| `setup` 에 `import enroll` | 설치 독립 + 방향 + **순환** |
| `reconcile_runs` 에 `server` **동적 로드** | 수집 독립 + 순환 |

세 번째가 핵심이다 — **동적으로 주입했는데 잡혔다.** 정적 분석이었으면 통과했을 것이다.

세 번 다 복구 후 11개 통과를 확인했다.

## 8. 이주 단계 (하지 않기로 한 것 포함)

| 단계 | 할까 | 이유 |
|---|---|---|
| `server.py` 를 관심사별로 분리 | **아니오, 지금은** | 쪼갤 근거가 없다. 경계 검사로 악화만 막는다 |
| 스코프 시스템에 모듈 매핑 | **보류** | `Do NOT touch` 는 파일 단위인데 이 레포는 모듈=파일이라 이미 등가다 |
| `gh_surface` (1,245줄) 검토 | 아니오 | 잎이고 아무도 의존하지 않는다. 커도 격리돼 있다 |

**`server.py` 분리를 기록으로 남긴다** — 언제 다시 볼지가 있어야 결정이다.
revisit 조건: *두 사람 이상이 `server.py` 를 동시에 고치기 시작할 때, 또는 한 관심사만
바꾸는데 다른 관심사의 테스트가 깨질 때.*
