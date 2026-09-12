import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "gh_surface", os.path.join(ROOT, "scripts", "gh_surface.py"))
gh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gh)

PHASES = """# 개발 Phase

## PHASE_PMF14 ✅ DONE (2026-09-08)
> 공개 표면 — 밖에서 들어오는 사람의 경로

대조 127건 중 18건이 틀렸다.

## Done when:
- [x] README 가 주장 검증 범위에 (#hgB99)
- [x] 설치가 무엇을 쓰는지 정확히 (#hgB100)

## PHASE_PMF13 ✅ DONE (2026-09-08)
> 링크 엔지니어링

앞 Phase 의 후속이다.
"""


class PhaseSectionsTest(unittest.TestCase):
    """파일이 아니라 텍스트를 받는다 — private/ 는 CI 에 없다."""

    def test_it_finds_every_done_phase(self):
        got = gh.phase_sections(PHASES)
        self.assertEqual({"PHASE_PMF14", "PHASE_PMF13"}, set(got))

    def test_it_keeps_the_one_line_summary(self):
        got = gh.phase_sections(PHASES)
        self.assertEqual("공개 표면 — 밖에서 들어오는 사람의 경로",
                         got["PHASE_PMF14"]["title"])

    def test_it_keeps_the_completion_date(self):
        self.assertEqual("2026-09-08",
                         gh.phase_sections(PHASES)["PHASE_PMF14"]["date"])

    def test_a_section_stops_at_the_next_phase(self):
        """경계를 못 그으면 앞 Phase 의 내용이 뒤에 섞인다."""
        body = gh.phase_sections(PHASES)["PHASE_PMF14"]["body"]
        self.assertIn("대조 127건", body)
        self.assertNotIn("링크 엔지니어링", body)


class ReleaseNotesTest(unittest.TestCase):
    def test_notes_carry_the_summary_and_the_body(self):
        notes = gh.release_notes(PHASES, "PHASE_PMF14")
        self.assertIn("공개 표면", notes)
        self.assertIn("대조 127건", notes)

    def test_unknown_phase_returns_none_not_empty_string(self):
        """빈 문자열을 돌려주면 '노트가 없는 릴리스'가 조용히 만들어진다."""
        self.assertIsNone(gh.release_notes(PHASES, "PHASE_PMF99"))


class GhAvailabilityTest(unittest.TestCase):
    """조용히 건너뛰면 '못 본 것'과 '깨끗한 것'이 같아 보인다."""

    def test_missing_binary_is_not_an_error(self):
        def runner(argv):
            raise FileNotFoundError("gh")
        ok, why = gh.gh_available(runner)
        self.assertFalse(ok)
        self.assertIn("gh", why)

    def test_unauthenticated_says_so(self):
        def runner(argv):
            return 1, "", "You are not logged into any GitHub hosts"
        ok, why = gh.gh_available(runner)
        self.assertFalse(ok)
        self.assertIn("인증", why)

    def test_missing_project_scope_is_named(self):
        """project 스코프는 2026-09-12 에 추가됐다. 다른 머신엔 없을 수 있다."""
        def runner(argv):
            return 0, "Token scopes: 'repo', 'workflow'", ""
        ok, why = gh.gh_available(runner, need_scope="project")
        self.assertFalse(ok)
        self.assertIn("project", why)

    def test_available_reports_why_too(self):
        """가능할 때도 이유를 채운다 — 빈 문자열이면 호출부가 조용해진다."""
        def runner(argv):
            return 0, "Token scopes: 'repo', 'project', 'workflow'", ""
        ok, why = gh.gh_available(runner, need_scope="project")
        self.assertTrue(ok)
        self.assertTrue(why.strip())

    def test_permission_denied_says_so(self):
        """실행 권한이 없으면 다른 OSError 로 잡힌다."""
        def runner(argv):
            raise PermissionError("permission denied")
        ok, why = gh.gh_available(runner)
        self.assertFalse(ok)
        self.assertIn("실행할 수 없다", why)


LOG = [
    # 디코이가 진짜 완료 커밋보다 **앞**에 온다 — 안정 정렬이 순서만으로
    # 답을 맞히지 못하게 한다. 오직 strong/weak 분류만으로 맞아야 한다.
    "bccd5da 2026-09-08 docs(progress): PMF14 개시 + PMF13 마무리 뒤 후속 5건 기록",
    "e315ab6 2026-09-08 feat: PMF13 완료 — 계획이 실측에 세 번 반박당한 Phase",
    "68c818d 2026-08-29 docs: PMF08 종료 정리 — 근본 원인 태스크를 PMF09 로 넘긴다",
    "5c62957 2026-09-06 chore(kanban): PMF11 이전 완료 태스크 아카이브",
    "fc23f71 2026-09-06 feat: PMF11 완료 — 눈먼 곳 6/6",
]


class BoundaryCandidatesTest(unittest.TestCase):
    """기계적으로 뽑으면 틀린다 — 예비 조사에서 셋이 어긋났다."""

    def test_the_completion_commit_outranks_a_later_chore(self):
        got = gh.boundary_candidates(LOG, "PMF11")
        self.assertEqual("fc23f71", got[0]["sha"])
        self.assertEqual("strong", got[0]["confidence"])

    def test_a_handoff_mention_is_not_a_completion(self):
        """`PMF08 종료 … PMF09 로 넘긴다` 는 PMF09 의 경계가 아니다."""
        got = gh.boundary_candidates(LOG, "PMF09")
        self.assertTrue(all(c["confidence"] != "strong" for c in got),
                        "인계 언급을 완료로 읽었다")

    def test_the_next_phase_opening_is_not_this_phase_closing(self):
        """`PMF14 개시 + PMF13 마무리 뒤` 는 PMF13 의 경계가 아니다."""
        got = gh.boundary_candidates(LOG, "PMF13")
        self.assertEqual("e315ab6", got[0]["sha"])

    def test_a_phase_with_no_commit_returns_empty_not_a_guess(self):
        """지어낸 경계는 없는 것보다 나쁘다."""
        self.assertEqual([], gh.boundary_candidates(LOG, "PMF04"))
