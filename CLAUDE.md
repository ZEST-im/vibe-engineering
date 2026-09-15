# vibe-harness 프로젝트 규칙

## 세션 시작 시 필독

```
private/PHASES.md 와 private/CURRENT_PHASE.md 를 읽고 시작한다.
```

## 내부 문서 경로

내부 운영/계획 문서는 모두 `private/` 에 있다 (gitignore — 공개 안 됨).

| 파일 | 설명 |
|---|---|
| `private/PHASES.md` | 전체 개발 Phase 목록 + 완료 내역 |
| `private/CURRENT_PHASE.md` | 현재 세션 스코프 |
| `private/HARNESS_PLAN.md` | Harness Engineering 강화 계획 |
| `private/MARKETPLACE_SUBMISSION.md` | 마켓플레이스 제출 초안 |
| `private/geeknews-post.md` | GeekNews 포스팅 초안 |

## 공개 파일 구조

```
vibe-harness/          ← public repo
  README.md            ← 제품 문서
  LICENSE
  PRIVACY.md
  scripts/             ← 배포 코드 (server.py, kanban.html, setup.py)
  skills/              ← Claude Code 스킬 정의
  docs/                ← 스크린샷 등 공개 리소스
  private/             ← .gitignored (내부 전용)
```

## 머지 · PR 규칙

**머지는 기능 하나가 완전히 끝났을 때 한 번만 한다.** 고칠 때마다 PR 을 열고 머지하면
`main` 이 반쯤 끝난 상태로 여러 번 움직이고, 되돌릴 때 어디까지가 한 덩어리인지 알 수 없다.

| | |
|---|---|
| 커밋 | **여러 개.** 원인 하나당 하나. 무엇을 왜 고쳤는지 + 어떤 변이로 확인했는지 적는다 |
| PR | **하나.** 기능/작업 묶음 하나에 PR 하나. 관련된 것은 브랜치 하나에 모은다 |
| 머지 | **맨 마지막에 한 번.** 아래를 전부 통과한 뒤에만 |

머지 전 조건 — 하나라도 빠지면 머지하지 않는다:

1. `python3 scripts/check.py` 6개 게이트 전부 초록
2. PR 의 CI 초록. **그 커밋의** 실행을 봐야 한다 — `gh run list` 맨 위가 이전 커밋일 수 있다
3. 자체 검토(`/review`)를 돌리고 **거기서 나온 것까지 고친** 상태
4. 사람의 승인. `main` 직접 push 는 금지다 (`docs/OUTCOME_BASED_ENGINEERING_ASSIGNMENTS.md`)

PR 이 여럿 열려 있으면 머지 전에 **실제로 병합해 본다.** 파일 목록이 안 겹쳐도 같은
파일의 같은 구역을 건드리면 충돌한다 — 목록만 보고 "안 겹친다" 고 말하지 않는다.

---

## 스코프 규칙

`private/CURRENT_PHASE.md`의 **Do NOT touch** 목록을 반드시 확인하고 준수한다.
