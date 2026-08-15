# Vibe Engineering — 진행 상황

> 외부 공유용 스냅샷. **Phase 단위 완료 사항만 간결하게** 적는다.
> 일상 기록은 `vibe-harness/kanban.json` 에 남고, 이 파일은 `qq` / `cc` 때 갱신된다.

## PHASE_PMF06 🚧 IN PROGRESS
> vibe-engineering 리브랜딩 + 착수 기획·디자인·리뷰 스킬

- **리브랜딩** — `vibe-harness` → `vibe-engineering`, 이후 `ZEST-im` org 로 이전.
  설치 경로·커맨드·데이터 디렉토리는 기존 사용자 호환을 위해 그대로 둔다. 구 URL 은 리다이렉트.
- **`/vibe-planning`** — 착수 기획 6단계 관문. 북극성부터 스캐폴딩까지.
  가상 프로젝트로 1~6단계를 완주해 스킬 결함 12건을 찾아 반영했다.
- **`/vibe-design`** — 구현 전에 화면을 self-contained HTML 로 만들고 브라우저로 확인.
  사용자군이 둘일 때 각각을 다른 표면으로 설계하도록 강제한다.
- **`/vibe-review`** — 팀원에게 적용할 잣대를 자기 레포에 적용하는 주간·일간 리뷰.
  보고를 믿지 않고 직접 실행해 증거를 모은다.
- **테스트 51개** — 제품 본체(`skills/`)와 데이터 불변식까지 확장. 신규 테스트는 위반을
  주입해 실제로 잡는지 확인한 뒤 채택했다.
- **CI** — GitHub Actions. Python 3.11/3.12/3.13 매트릭스 + ruff 린트.

## PHASE_PMF05 ✅ DONE (2026-07-18)
> Thin agent execution layer — atomic lease, worker runtime, test gate, 승인 흐름

## PHASE_PMF04 ✅ DONE (2026-07-11)
> zest.im 사내 프로젝트 대시보드 단방향 자동 동기화

## PHASE_PMF03 ✅ DONE (2026-06-20)
> 실측 토큰 자동수집 — 세션 종료 시 에이전트별 usage 를 자동 기록

## PHASE_PMF02 ✅ DONE
> 에이전트별 토큰·비용 집계와 Stats 뷰

## PHASE_PMF01 ✅ DONE
> Phase 관리·스코프 가드·결정 로그

## PHASE_MVP02 ✅ DONE
> 멀티 프로젝트, 아카이브, DB 스키마 뷰

## PHASE_MVP01 ✅ DONE
> 칸반 보드와 로컬 서버
