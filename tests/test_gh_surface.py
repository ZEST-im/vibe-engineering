import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
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


class TagPlanTest(unittest.TestCase):
    def test_it_names_the_tag_after_the_phase(self):
        plan = gh.tag_plan(PHASES, LOG)
        by = {p["phase"]: p for p in plan}
        self.assertEqual("phase/PMF13", by["PHASE_PMF13"]["tag"])

    def test_a_phase_without_a_boundary_is_listed_with_a_reason(self):
        """**못 그은 것을 빠뜨리면 몇 개를 못 그었는지 셀 수 없다.**"""
        plan = gh.tag_plan(PHASES, [])
        self.assertTrue(plan, "후보가 없다고 계획이 비면 안 된다")
        self.assertTrue(all(p["sha"] is None for p in plan))
        self.assertTrue(all(p["skipped_reason"] for p in plan))

    def test_every_planned_tag_carries_notes(self):
        for p in gh.tag_plan(PHASES, LOG):
            if p["sha"]:
                self.assertTrue(p["notes"], f"{p['phase']} 에 노트가 없다")


# ── 여기부터 CLI 층 — 실제 git 레포가 있어야 뜻이 있는 것만 임시 레포로 검사한다.
# `gh` 는 절대 실제로 부르지 않는다: gate 를 통과하지 못하게 하거나(주입한
# `gh_check`), 호출을 가로채는 fake `gh_runner` 를 준다.

def _git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, env=env, check=True)


def _repo(*subjects):
    """빈 커밋들로만 이뤄진 임시 레포. 오래된 것부터 순서대로 커밋한다."""
    d = tempfile.mkdtemp()
    _git(d, "init", "-q", "-b", "main")
    for subj in subjects:
        _git(d, "commit", "--allow-empty", "-q", "-m", subj)
    return d


def _sha(repo, subject_substr):
    for line in _git(repo, "log", "--format=%h %s").stdout.splitlines():
        if subject_substr in line:
            return line.split(" ", 1)[0]
    raise AssertionError(f"커밋을 못 찾음: {subject_substr}")


PHASES_FIXTURE = """# 픽스처

## PHASE_PMF50 ✅ DONE (2026-01-01)
> 태그 대상

내용 50

## PHASE_PMF51 ✅ DONE (2026-01-02)
> 경계 없음

내용 51
"""


class TagCliMissingPhasesTest(unittest.TestCase):
    def test_missing_phases_file_stops_instead_of_an_empty_plan(self):
        """조용히 빈 계획으로 넘어가면 '못 찾음'과 '깨끗함'이 같아 보인다."""
        with self.assertRaises(SystemExit) as cm:
            gh.main(["tag", "--phases", "/no/such/PHASES.md"])
        self.assertIn("찾지 못했다", str(cm.exception.code))


class TagCliDryRunTest(unittest.TestCase):
    """`main` 이 실제로 파일을 읽고 `git log` 를 불러 계획을 세우는지."""

    def test_dry_run_lists_a_strong_boundary_and_a_skip_and_creates_nothing(self):
        repo = _repo("chore: 초기화", "feat: PMF50 완료 — 픽스처")
        phases_path = os.path.join(repo, "PHASES.md")
        with open(phases_path, "w", encoding="utf-8") as fh:
            fh.write(PHASES_FIXTURE)
        sha = _sha(repo, "PMF50 완료")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh.main(["tag", "--phases", phases_path], root=repo)
        out = buf.getvalue()

        self.assertEqual(0, code)
        self.assertIn(f"phase/PMF50  {sha}", out)
        self.assertIn("PHASE_PMF51: 보류", out)
        self.assertIn("2개 Phase 중 1개 태그 가능, 1개 보류", out)
        self.assertIn("[dry-run]", out)
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip(),
                         "dry-run 인데 태그가 생겼다")

    def test_default_phases_path_is_private_phases_md_under_root(self):
        """`--phases` 를 생략하면 `root` 기준 `private/PHASES.md` 를 읽는다."""
        repo = _repo("chore: 초기화")
        os.makedirs(os.path.join(repo, "private"))
        with open(os.path.join(repo, "private", "PHASES.md"), "w", encoding="utf-8") as fh:
            fh.write(PHASES_FIXTURE)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh.main(["tag"], root=repo)
        out = buf.getvalue()

        self.assertEqual(0, code)
        # 이 레포엔 PMF50/51 을 언급하는 커밋이 전혀 없으니 둘 다 보류다.
        self.assertIn("2개 Phase 중 0개 태그 가능, 2개 보류", out)


class RunTagApplyTest(unittest.TestCase):
    """--apply 경로 — gate·idempotent·성공 흐름. `gh` 는 실제로 부르지 않는다."""

    def test_apply_is_gated_by_gh_availability_and_creates_nothing(self):
        plan = [{"phase": "PHASE_PMF50", "tag": "phase/PMF50", "sha": "abc1234",
                 "notes": "노트", "skipped_reason": None}]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, "/does/not/matter", apply=True,
                               gh_check=lambda: (False, "gh 인증 없음 — 테스트"))
        self.assertEqual(1, code)
        self.assertIn("gh 인증 없음 — 테스트", buf.getvalue())

    def test_apply_skips_a_tag_that_already_exists_without_calling_gh(self):
        repo = _repo("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        _git(repo, "tag", "-a", "phase/PMF50", sha, "-m", "이미 있음")

        def poison(argv):
            raise AssertionError(f"이미 있는 태그인데 gh 를 불렀다: {argv}")

        plan = [{"phase": "PHASE_PMF50", "tag": "phase/PMF50", "sha": sha,
                 "notes": "노트", "skipped_reason": None}]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=poison)
        self.assertEqual(0, code)
        self.assertIn("이미 있다", buf.getvalue())

    def test_apply_creates_an_annotated_tag_and_calls_gh_release_with_notes(self):
        repo = _repo("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        calls = []

        def fake_gh(argv):
            calls.append(argv)
            return 0, "", ""

        plan = [{"phase": "PHASE_PMF50", "tag": "phase/PMF50", "sha": sha,
                 "notes": "공개 릴리스 노트", "skipped_reason": None}]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=fake_gh)

        self.assertEqual(0, code)
        self.assertEqual("phase/PMF50", _git(repo, "tag", "-l", "phase/PMF50").stdout.strip())
        self.assertEqual("tag", _git(repo, "cat-file", "-t", "phase/PMF50").stdout.strip(),
                         "라이트웨이트 태그다 — annotated 여야 한다")
        self.assertEqual(1, len(calls))
        self.assertIn("release", calls[0])
        self.assertIn(sha, calls[0])
        self.assertIn("공개 릴리스 노트", calls[0])


class LogLinesTest(unittest.TestCase):
    """CLI 층 도우미 — 못 읽으면 크래시 대신 빈 목록. 경계를 지어내지 않는 원칙은 여기서도 같다."""

    def test_a_nonzero_exit_is_empty_even_if_stdout_has_bytes(self):
        """이 가드가 없으면 실패한 호출이 남긴 부스러기를 후보로 오인한다."""
        def runner(argv):
            return 1, "가짜abc 2026-01-01 실패한 호출의 부스러기", "fatal: ..."
        self.assertEqual([], gh._log_lines("/whatever", runner=runner))

    def test_a_missing_git_binary_is_empty_not_an_exception(self):
        def runner(argv):
            raise FileNotFoundError("git")
        self.assertEqual([], gh._log_lines("/whatever", runner=runner))

    def test_a_real_non_git_directory_also_yields_empty(self):
        """주입 없이 실제 git 이 돌 때도 같은 결과인지 통합적으로 확인한다."""
        self.assertEqual([], gh._log_lines(tempfile.mkdtemp()))
