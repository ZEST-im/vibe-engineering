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

    def test_a_weak_only_candidate_is_not_promoted_to_a_tag(self):
        """PMF14 는 LOG 에 약한 후보(bccd5da)만 있다 — strong 필터를 지우면 태깅된다."""
        by = {p["phase"]: p for p in gh.tag_plan(PHASES, LOG)}
        self.assertIsNone(by["PHASE_PMF14"]["sha"])

    def test_weak_only_reason_differs_from_no_candidate_and_names_the_count(self):
        """실측에서 보류 9건 중 5건은 '약한 후보만 있음' 이었다 — 뭉뚱그리면 그
        신호가 사라진다."""
        by = {p["phase"]: p for p in gh.tag_plan(PHASES, LOG)}
        reason = by["PHASE_PMF14"]["skipped_reason"]
        self.assertIsNotNone(reason)
        self.assertNotEqual("완료를 선언한 커밋이 없다 — 추측하지 않는다", reason)
        self.assertIn("1", reason)  # LOG 에서 PMF14 를 언급하는 약한 후보는 정확히 1건


# ── 여기부터 CLI 층 — 실제 git 레포가 있어야 뜻이 있는 것만 임시 레포로 검사한다.
# `gh` 는 절대 실제로 부르지 않는다: gate 를 통과하지 못하게 하거나(주입한
# `gh_check`), 호출을 가로채는 fake `gh_runner` 를 준다. `git push` 는 로컬
# bare 레포를 `origin` 으로 써서 **네트워크 없이 진짜 push 를** 검사한다.

def _git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, env=env, check=True)


def _repo(*subjects):
    """빈 커밋들로만 이뤄진 임시 레포. 오래된 것부터 순서대로 커밋한다. origin 없음."""
    d = tempfile.mkdtemp()
    _git(d, "init", "-q", "-b", "main")
    for subj in subjects:
        _git(d, "commit", "--allow-empty", "-q", "-m", subj)
    return d


def _repo_with_origin(*subjects):
    """origin(로컬 bare 레포) 이 있는 작업 레포 — 네트워크 없이 진짜 `git push` 를 검사한다."""
    bare = tempfile.mkdtemp()
    _git(bare, "init", "-q", "--bare", "-b", "main")
    work = _repo(*subjects)
    _git(work, "remote", "add", "origin", bare)
    _git(work, "push", "-q", "origin", "main")
    return work, bare


def _repo_with_broken_origin(*subjects):
    """`origin` 은 설정돼 있지만(주소는 읽힌다) 실제로 push 하면 반드시 실패하는 레포."""
    d = _repo(*subjects)
    _git(d, "remote", "add", "origin", "/no/such/path/on/disk")
    return d


def _sha(repo, subject_substr):
    for line in _git(repo, "log", "--format=%h %s").stdout.splitlines():
        if subject_substr in line:
            return line.split(" ", 1)[0]
    raise AssertionError(f"커밋을 못 찾음: {subject_substr}")


def _poison(msg):
    """이 경로로는 절대 오면 안 된다는 뜻의 fake runner — 오면 테스트를 실패시킨다."""
    def _fn(argv):
        raise AssertionError(f"{msg}: {argv}")
    return _fn


def _plan_entry(tag, sha, notes="노트"):
    return {"phase": "PHASE_PMF50", "tag": tag, "sha": sha,
            "notes": notes, "skipped_reason": None}


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


class ResolveFullShaTest(unittest.TestCase):
    """C3 — `%h`(짧은 sha)를 공개 태그에 그대로 박아 넣지 않는다."""

    def test_it_expands_a_short_sha_to_the_full_40_char_form(self):
        repo = _repo("feat: PMF50 완료 — 픽스처")
        short = _sha(repo, "PMF50 완료")
        full = gh._resolve_full_sha(repo, short)
        self.assertEqual(40, len(full))
        self.assertTrue(full.startswith(short))

    def test_it_returns_none_for_a_sha_that_does_not_exist(self):
        repo = _repo("chore: 초기화")
        self.assertIsNone(gh._resolve_full_sha(repo, "deadbeef"))


class RunTagApplyGateTest(unittest.TestCase):
    """게이트 두 개(gh 가용성, origin 고정) — 순서가 무너지면 실제 레포에 태그가 남는다."""

    def test_apply_is_gated_by_gh_availability_and_creates_nothing(self):
        """게이트가 루프 뒤로 밀리면(I2) 이 태그가 실제로 만들어진다."""
        repo = _repo("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (False, "gh 인증 없음 — 테스트"),
                               gh_runner=_poison("gh 게이트 실패했는데 gh 를 불렀다"))
        self.assertEqual(1, code)
        self.assertIn("gh 인증 없음 — 테스트", buf.getvalue())
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip(),
                         "게이트가 늦게 걸리면 이 태그가 만들어진다")

    def test_apply_stops_without_an_origin_remote_and_creates_nothing(self):
        """I4 — `origin` 이 없으면 `-R` 을 고정할 근거가 없어 아예 멈춘다."""
        repo = _repo("feat: PMF50 완료 — 픽스처")  # origin 없음
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"),
                               gh_runner=_poison("origin 이 없는데 gh 를 불렀다"))
        self.assertEqual(1, code)
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip())

    def test_every_gh_call_is_pinned_with_dash_r(self):
        """I4 — `-R` 없이 부르면 `gh` 가 프로세스 cwd 로 레포를 잘못 고른다."""
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        expected_slug = _git(repo, "remote", "get-url", "origin").stdout.strip()
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha)]
        calls = []

        def fake_gh(argv):
            calls.append(argv)
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            return 0, "", ""

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gh._run_tag(plan, repo, apply=True,
                       gh_check=lambda: (True, "ok"), gh_runner=fake_gh)

        self.assertTrue(calls, "gh 를 한 번도 안 불렀다")
        for argv in calls:
            self.assertIn("-R", argv)
            self.assertEqual(expected_slug, argv[argv.index("-R") + 1])


class RunTagApplySuccessTest(unittest.TestCase):
    """정상 흐름 — annotated 태그 → push → `gh release create --verify-tag`."""

    def test_apply_creates_annotated_tag_pushes_it_and_calls_gh_release(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        calls = []

        def fake_gh(argv):
            calls.append(argv)
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"  # 아직 릴리스 없음 → 만들어야 한다
            return 0, "", ""

        plan = [_plan_entry("phase/PMF50", sha, notes="공개 릴리스 노트")]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=fake_gh)
        out = buf.getvalue()

        self.assertEqual(0, code)
        self.assertIn("생성 1", out)

        # 로컬에 annotated 태그가 실제로 생겼다.
        self.assertEqual("phase/PMF50", _git(repo, "tag", "-l", "phase/PMF50").stdout.strip())
        self.assertEqual("tag", _git(repo, "cat-file", "-t", "phase/PMF50").stdout.strip(),
                         "라이트웨이트 태그다 — annotated 여야 한다")

        # I5 — 태그가 실제로 origin(bare) 에 push 됐다.
        self.assertEqual("phase/PMF50", _git(bare, "tag", "-l", "phase/PMF50").stdout.strip(),
                         "태그가 push 되지 않았다")

        # I1 — notes/title 이 서로 바뀌어도 assertIn 만으로는 못 잡는다. 인접값을 본다.
        create_calls = [c for c in calls if c[:3] == ["gh", "release", "create"]]
        self.assertEqual(1, len(create_calls))
        argv = create_calls[0]
        self.assertIn("--verify-tag", argv)
        self.assertEqual("phase/PMF50", argv[argv.index("--title") + 1])
        self.assertEqual("공개 릴리스 노트", argv[argv.index("--notes") + 1])
        self.assertNotIn("--target", argv)  # I5 — target 이 아니라 이미 push 된 태그를 쓴다

    def test_run_tag_passes_a_full_40_char_sha_to_git_tag_a_not_the_short_form(self):
        """C3 — `_run` 을 가로채 실제로 어떤 sha 문자열이 `git tag -a` 로 갔는지 본다."""
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        short = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", short)]

        calls = []
        real_run = gh._run

        def spy(argv):
            calls.append(argv)
            return real_run(argv)

        gh._run = spy
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                gh._run_tag(plan, repo, apply=True,
                           gh_check=lambda: (True, "ok"),
                           gh_runner=lambda argv: (
                               (1, "", "not found") if argv[:3] == ["gh", "release", "view"]
                               else (0, "", "")))
        finally:
            gh._run = real_run

        tag_calls = [c for c in calls if len(c) > 3 and c[3] == "tag" and "-a" in c]
        self.assertEqual(1, len(tag_calls), "annotated 태그 생성 호출을 못 찾음")
        sha_arg = tag_calls[0][tag_calls[0].index("-a") + 2]  # ["tag","-a",<name>,<sha>,...]
        self.assertEqual(40, len(sha_arg), f"짧은 sha 를 그대로 넘겼다: {sha_arg}")
        self.assertTrue(sha_arg.startswith(short))


class RunTagIdempotencyTest(unittest.TestCase):
    """C2 — idempotency 는 **릴리스 존재 여부**로 판단한다. 로컬 태그만 보면 '태그는
    있는데 릴리스가 없다'(복구가 필요한 상태)를 '이미 끝남'으로 잘못 읽는다."""

    def test_apply_skips_when_the_release_already_exists_without_recreating_anything(self):
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha)]

        def gh_release_exists(argv):
            if argv[:3] == ["gh", "release", "view"]:
                return 0, "", ""
            raise AssertionError(f"릴리스가 있다는데 다른 gh 호출을 했다: {argv}")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=gh_release_exists)

        self.assertEqual(0, code)
        self.assertIn("이미 있다", buf.getvalue())
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip(),
                         "릴리스가 있는데 태그를 또 만들었다")

    def test_apply_recovers_a_tag_that_exists_locally_without_a_release(self):
        """이전 --apply 가 태그까지만 만들고 push/릴리스에서 실패한 상태를 흉내낸다."""
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        _git(repo, "tag", "-a", "phase/PMF50", sha, "-m", "이전 시도")  # 로컬에만 있음

        plan = [_plan_entry("phase/PMF50", sha)]

        def fake_gh(argv):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            return 0, "", ""

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=fake_gh)
        out = buf.getvalue()

        self.assertEqual(0, code)
        self.assertIn("복구", out)
        self.assertIn("phase/PMF50", out)
        # 태그를 다시 만들려 했다면(이미 있는 이름이라) 실패했을 것 — 성공으로 끝났다는
        # 것 자체가 재생성을 시도하지 않았다는 증거다.
        self.assertEqual("phase/PMF50", _git(bare, "tag", "-l", "phase/PMF50").stdout.strip(),
                         "복구된 태그가 origin 에 push 되지 않았다")


class RunTagFailureBranchTest(unittest.TestCase):
    """C2 — '태그는 됐는데 그 다음이 실패' 가 가장 위험한 상태다. 이전엔 커버리지가 없었다."""

    def test_a_git_tag_creation_failure_is_reported_and_never_reaches_gh(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        # "?" 는 git 태그 이름에 못 쓰는 문자 — `git tag -a` 가 반드시 실패한다.
        plan = [_plan_entry("phase/PMF?50", sha)]

        def gh_view_missing_only(argv):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            raise AssertionError(f"태그 생성이 실패했는데 gh 를 더 불렀다: {argv}")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=gh_view_missing_only)

        self.assertEqual(1, code)
        self.assertIn("태그 생성 실패", buf.getvalue())
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip())
        self.assertEqual("", _git(bare, "tag", "-l").stdout.strip())

    def test_a_push_failure_is_reported_as_an_orphan_and_never_reaches_gh_release_create(self):
        repo = _repo_with_broken_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha)]

        def gh_view_missing_only(argv):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            raise AssertionError(f"push 가 실패했는데 gh 를 더 불렀다: {argv}")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=gh_view_missing_only)
        out = buf.getvalue()

        self.assertEqual(1, code)
        self.assertIn("push 에 실패", out)
        # 로컬 태그는 남아 있다 — 다음 --apply 가 재생성 없이 push 부터 재시도할 근거.
        self.assertEqual("phase/PMF50", _git(repo, "tag", "-l").stdout.strip())

    def test_a_release_creation_failure_names_the_orphan_tag_and_the_recovery(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha)]

        def gh_view_missing_then_create_fails(argv):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            if argv[:3] == ["gh", "release", "create"]:
                return 1, "", "422 Unprocessable Entity"
            raise AssertionError(f"예상 못한 gh 호출: {argv}")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"),
                               gh_runner=gh_view_missing_then_create_fails)
        out = buf.getvalue()

        self.assertEqual(1, code)
        self.assertIn("릴리스 생성에 실패", out)
        self.assertIn("phase/PMF50", out)   # orphan 태그 이름을 명시
        self.assertIn("--apply", out)       # 복구 방법(재실행)을 명시
        # 태그·push 는 이미 끝났어야 한다 — 로컬과 origin(bare) 모두에.
        self.assertEqual("phase/PMF50", _git(repo, "tag", "-l", "phase/PMF50").stdout.strip())
        self.assertEqual("phase/PMF50", _git(bare, "tag", "-l", "phase/PMF50").stdout.strip())


class LogLinesTest(unittest.TestCase):
    """I3 — git log 를 못 읽으면 **크게 실패한다.** `private/PHASES.md` 가 없을 때와
    같은 태도 — 조용히 빈 로그로 넘어가면 '경계 없음' 과 '못 읽음' 이 같아 보인다."""

    def test_a_nonzero_exit_stops_instead_of_a_silent_empty_log(self):
        def runner(argv):
            return 1, "가짜abc 2026-01-01 실패한 호출의 부스러기", "fatal: not a git repository"
        with self.assertRaises(SystemExit):
            gh._log_lines("/whatever", runner=runner)

    def test_a_missing_git_binary_stops_instead_of_a_silent_empty_log(self):
        def runner(argv):
            raise FileNotFoundError("git")
        with self.assertRaises(SystemExit):
            gh._log_lines("/whatever", runner=runner)
