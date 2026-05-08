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

## 스코프 규칙

`private/CURRENT_PHASE.md`의 **Do NOT touch** 목록을 반드시 확인하고 준수한다.
