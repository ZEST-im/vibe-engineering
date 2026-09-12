import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import time
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


class GhAvailabilityDefaultTimeoutTest(unittest.TestCase):
    """`runner` 를 안 넘긴 실제 운영 경로 — `gh auth status` 도 무한 대기하면 안 된다.

    `_run` 을 스파이로 가로채, `gh_available()` 이 기본 경로에서 실제로 `timeout` 을
    실어 부르는지만 본다. `gh auth status` 는 조회일 뿐이라 실행돼도 안전하다.
    """

    def test_the_default_path_passes_a_timeout_to_run(self):
        calls = []
        real_run = gh._run

        def spy(argv, **kwargs):
            calls.append(kwargs)
            return real_run(argv, **kwargs)

        gh._run = spy
        try:
            gh.gh_available()
        finally:
            gh._run = real_run

        self.assertEqual(1, len(calls), "기본 경로가 _run 을 정확히 한 번 불러야 한다")
        self.assertEqual(gh._GH_AUTH_TIMEOUT, calls[0].get("timeout"),
                         "gh auth status 기본 호출에 timeout 이 없다 — 무한 대기 경로가 남아 있다")


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


TASKS = [
    {"id": "hgB99", "title": "A", "status": "done", "share": True, "issue": 12},
    {"id": "hgB100", "title": "B", "status": "done", "share": True},
    {"id": "hgB101", "title": "C", "status": "done"},
    {"id": "hgB102", "title": "D", "status": "todo", "share": False},
    # `share` 없이 `issue` 만 있는 경우 — updatable() 이 `issue` 존재만 보고
    # `share` 를 안 봐도 통과할 수 있는 픽스처였다면 그 결함을 못 잡는다.
    {"id": "hgB103", "title": "E", "status": "done", "issue": 7},
]


class PromotionSelectionTest(unittest.TestCase):
    """전량 미러가 아니다 — 사람이 고른 것만 올라간다."""

    def test_only_flagged_tasks_are_promotable(self):
        self.assertEqual(["hgB100"], [t["id"] for t in gh.promotable(TASKS)])

    def test_a_task_with_an_issue_is_updated_not_recreated(self):
        """번호가 있는데 또 만들면 같은 태스크가 이슈 둘이 된다."""
        self.assertEqual(["hgB99"], [t["id"] for t in gh.updatable(TASKS)])

    def test_absent_field_means_not_shared(self):
        """`depends_on` 과 같은 형태 — 없으면 없는 것이다."""
        self.assertNotIn("hgB101", [t["id"] for t in gh.promotable(TASKS)])


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
    def _fn(argv, **_kw):
        raise AssertionError(f"{msg}: {argv}")
    return _fn


def _plan_entry(tag, sha, notes="노트", summary=None):
    """계획 항목 하나. **게이트와 두 공개 표면(태그 메시지, `gh release create
    --notes`)이 실제로 보는 건 `summary` 뿐이다** — `notes`(전체 본문)는 더 이상
    검사도 공개도 되지 않는다. `summary` 를 안 주면 `notes` 와 같은 값을 써서
    대부분의(게이트와 무관한) 테스트가 그대로 동작하게 한다 — 게이트 동작 자체를
    검증하는 테스트는 반드시 `summary=` 를 명시해야 그 값을 검사·게시하는지
    증명하는 뜻이 있다."""
    if summary is None:
        summary = notes
    return {"phase": "PHASE_PMF50", "tag": tag, "sha": sha,
            "notes": notes, "summary": summary, "skipped_reason": None}


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

        def fake_gh(argv, **_kw):
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

        def fake_gh(argv, **_kw):
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

        def spy(argv, **kwargs):
            calls.append(argv)
            return real_run(argv, **kwargs)

        gh._run = spy
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                gh._run_tag(plan, repo, apply=True,
                           gh_check=lambda: (True, "ok"),
                           gh_runner=lambda argv, **_kw: (
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

        def gh_release_exists(argv, **_kw):
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

        def fake_gh(argv, **_kw):
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


class RunTagShaMismatchTest(unittest.TestCase):
    """2라운드 리뷰 — 복구 분기가 **이름만** 보고 push 해버리는 새 Important 결함.

    `_tag_exists_locally` 는 이름만 본다. 로컬에 같은 이름의 태그가 '다른 커밋'을
    가리키면 복구 분기가 그걸 그대로 push 해 버려서, dry-run 이 보여준 sha 와
    실제로 공개되는 커밋이 어긋난다 — 그런데도 성공(exit 0)으로 보고된다."""

    def test_a_locally_existing_tag_at_the_wrong_commit_is_not_pushed(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처", "chore: 다른 커밋")
        planned_sha = _sha(repo, "PMF50 완료")
        wrong_sha = _sha(repo, "다른 커밋")
        # 이름은 같지만 계획과 다른 커밋을 가리키는 태그가 로컬에 이미 있다.
        _git(repo, "tag", "-a", "phase/PMF50", wrong_sha, "-m", "실수로 다른 커밋에")

        plan = [_plan_entry("phase/PMF50", planned_sha)]

        def gh_view_missing_only(argv, **_kw):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            raise AssertionError(f"sha 가 어긋나는데 gh 를 불렀다: {argv}")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=gh_view_missing_only)
        out = buf.getvalue()

        self.assertEqual(1, code)
        self.assertIn("다른 커밋", out)
        full_planned = gh._resolve_full_sha(repo, planned_sha)
        full_wrong = gh._resolve_full_sha(repo, wrong_sha)
        self.assertIn(full_planned, out, "계획한(올바른) sha 를 메시지에 밝히지 않았다")
        self.assertIn(full_wrong, out, "기존 태그가 실제로 가리키는 sha 를 밝히지 않았다")
        # 가장 중요한 확인 — push 되지 않았다. origin(bare) 에 이 태그가 전혀 없어야 한다.
        self.assertEqual("", _git(bare, "tag", "-l").stdout.strip(),
                         "어긋난 태그를 그대로 push 해 버렸다")
        # 로컬 태그도 우리가 건드리지 않았다 — 여전히(잘못된) wrong_sha 를 가리킨다.
        self.assertEqual(full_wrong, gh._resolve_full_sha(repo, "phase/PMF50"))


class RunTagPushRejectionTest(unittest.TestCase):
    """Minor(스코프 포함) — non-fast-forward 거부를 '재실행하면 복구' 로 잘못 안내하면
    안 된다. 재실행은 같은 거부를 반복할 뿐이다."""

    def test_a_push_rejected_by_a_conflicting_remote_tag_says_rerun_wont_fix_it(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처", "chore: 딴 데서 온 태그")
        planned_sha = _sha(repo, "PMF50 완료")
        decoy_sha = _sha(repo, "딴 데서 온 태그")

        # 원격에 이미 '다른 커밋'을 가리키는 같은 이름의 태그가 있는 상태를 만든다 —
        # 이 작업 레포는 그 사실을 (로컬 태그가 없으니) 전혀 모른다.
        _git(repo, "tag", "-a", "phase/PMF50", decoy_sha, "-m", "딴 데서 만들어진 것")
        _git(repo, "push", "-q", "origin", "phase/PMF50")
        _git(repo, "tag", "-d", "phase/PMF50")  # 로컬에서는 지운다 — 원격에만 남는다
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip())  # 픽스처 전제 확인

        plan = [_plan_entry("phase/PMF50", planned_sha)]

        def gh_view_missing_only(argv, **_kw):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            raise AssertionError(f"push 가 거부됐는데 gh 를 더 불렀다: {argv}")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=gh_view_missing_only)
        out = buf.getvalue()

        self.assertEqual(1, code)
        self.assertIn("재실행으로는 못 고친다", out)
        self.assertIn("git push --delete", out)
        self.assertNotIn("다시 실행하면 복구한다", out,
                         "재실행으로 못 고치는데 재실행하라고 안내했다")
        # 원격은 그대로다 — 여전히 decoy 를 가리킨다. 우리가 덮어쓰지 않았다.
        self.assertEqual(gh._resolve_full_sha(repo, decoy_sha),
                         gh._resolve_full_sha(bare, "phase/PMF50"))


class PushSafetyTest(unittest.TestCase):
    """Minor(스코프 포함) — 무인 실행 중 자격증명 프롬프트가 뜨면 화면에 아무것도 안
    보이는 채로 영원히 멈춘다. `_run` 의 `env`/`timeout` 자체와, `_run_tag` 의 push 호출이
    실제로 그걸 쓰는지 둘 다 확인한다."""

    def test_run_passes_env_through_to_the_child_process(self):
        code, out, _err = gh._run(
            [sys.executable, "-c",
             "import os, sys; sys.stdout.write(os.environ.get('GIT_TERMINAL_PROMPT', 'unset'))"],
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        self.assertEqual(0, code)
        self.assertEqual("0", out)

    def test_run_with_a_timeout_does_not_hang_and_reports_it(self):
        start = time.monotonic()
        code, _out, err = gh._run(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
        elapsed = time.monotonic() - start
        self.assertEqual(124, code)
        self.assertLess(elapsed, 4, "timeout 이 실제로는 걸리지 않고 5초를 기다렸다")
        self.assertIn("초", err)

    def test_the_push_call_disables_the_terminal_prompt_and_has_a_timeout(self):
        """`_run_tag` 가 실제로 push 호출에 이 가드를 붙이는지 — 스파이로 가로챈다."""
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha)]

        calls = []
        real_run = gh._run

        def spy(argv, **kwargs):
            calls.append((argv, kwargs))
            return real_run(argv, **kwargs)

        gh._run = spy
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                gh._run_tag(plan, repo, apply=True,
                           gh_check=lambda: (True, "ok"),
                           gh_runner=lambda argv, **_kw: (
                               (1, "", "not found") if argv[:3] == ["gh", "release", "view"]
                               else (0, "", "")))
        finally:
            gh._run = real_run

        push_calls = [(a, k) for a, k in calls if len(a) > 3 and a[3] == "push"]
        self.assertEqual(1, len(push_calls), "push 호출을 못 찾음")
        argv, kwargs = push_calls[0]
        self.assertEqual("0", (kwargs.get("env") or {}).get("GIT_TERMINAL_PROMPT"),
                         "GIT_TERMINAL_PROMPT=0 없이 push 했다")
        self.assertEqual(gh._PUSH_TIMEOUT, kwargs.get("timeout"), "push 에 timeout 이 없다")


class RunTagFailureBranchTest(unittest.TestCase):
    """C2 — '태그는 됐는데 그 다음이 실패' 가 가장 위험한 상태다. 이전엔 커버리지가 없었다."""

    def test_a_git_tag_creation_failure_is_reported_and_never_reaches_gh(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        # "?" 는 git 태그 이름에 못 쓰는 문자 — `git tag -a` 가 반드시 실패한다.
        plan = [_plan_entry("phase/PMF?50", sha)]

        def gh_view_missing_only(argv, **_kw):
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

        def gh_view_missing_only(argv, **_kw):
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

        def gh_view_missing_then_create_fails(argv, **_kw):
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


class GhCallTimeoutTest(unittest.TestCase):
    """`gh release view`/`gh release create` 도 `push` 처럼 시간제한이 있어야 한다 —
    없으면 태그는 이미 공개된 채로 화면에 아무것도 안 보이는 채로 영원히 멈춘다.
    실제 `gh` 는 절대 안 부른다 — fake gh_runner 로 넘어온 kwargs 만 본다."""

    def test_release_view_and_release_create_both_carry_a_timeout(self):
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha)]

        calls = []

        def fake_gh(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            return 0, "", ""

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gh._run_tag(plan, repo, apply=True,
                       gh_check=lambda: (True, "ok"), gh_runner=fake_gh)

        view_calls = [(a, k) for a, k in calls if a[:3] == ["gh", "release", "view"]]
        create_calls = [(a, k) for a, k in calls if a[:3] == ["gh", "release", "create"]]
        self.assertEqual(1, len(view_calls), "gh release view 를 정확히 한 번 불러야 한다")
        self.assertEqual(1, len(create_calls), "gh release create 를 정확히 한 번 불러야 한다")
        self.assertEqual(gh._GH_RELEASE_VIEW_TIMEOUT, view_calls[0][1].get("timeout"),
                         "gh release view 에 timeout 이 없다")
        self.assertEqual(gh._GH_RELEASE_CREATE_TIMEOUT, create_calls[0][1].get("timeout"),
                         "gh release create 에 timeout 이 없다")


class DenyGateUnitTest(unittest.TestCase):
    """`_load_deny_terms`/`_deny_hit_count` — 순수 함수 층. 진짜 private/DENY.txt 는
    절대 읽지 않는다 — 임시 디렉터리에 우리만의 가짜 금칙어를 심는다."""

    def test_absent_file_returns_none_and_says_so(self):
        terms, why = gh._load_deny_terms(tempfile.mkdtemp())
        self.assertIsNone(terms)
        self.assertIn("없음", why)

    def test_present_file_returns_terms_and_names_the_count(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "private"))
        with open(os.path.join(d, "private", "DENY.txt"), "w", encoding="utf-8") as fh:
            fh.write("ZQX-FIXTURE-ONE\n# 주석은 건너뛴다\nZQX-FIXTURE-TWO\n")
        terms, why = gh._load_deny_terms(d)
        self.assertEqual(["ZQX-FIXTURE-ONE", "ZQX-FIXTURE-TWO"], terms)
        self.assertIn("2", why)

    def test_hit_count_counts_without_ever_returning_the_string(self):
        self.assertEqual(1, gh._deny_hit_count(
            "노트 안에 ZQX-FIXTURE-ONE 이 섞였다", ["ZQX-FIXTURE-ONE", "ZQX-FIXTURE-TWO"]))
        self.assertEqual(2, gh._deny_hit_count(
            "ZQX-FIXTURE-ONE 그리고 ZQX-FIXTURE-TWO 둘 다",
            ["ZQX-FIXTURE-ONE", "ZQX-FIXTURE-TWO"]))
        self.assertEqual(0, gh._deny_hit_count("완전히 깨끗하다", ["ZQX-FIXTURE-ONE"]))

    def test_no_terms_means_no_hits(self):
        """`None`(파일 없음)이든 `[]`(파일은 있지만 항목 없음)이든 적중은 0건이다."""
        self.assertEqual(0, gh._deny_hit_count("아무 내용", None))
        self.assertEqual(0, gh._deny_hit_count("아무 내용", []))


class ReleaseNotesDenyGateTest(unittest.TestCase):
    """릴리스 노트는 검사되지 않은 공개 표면이었다 — `private/PHASES.md` 에서 파생되는데
    그 파일은 gitignore 대상이라 `tests/test_public_hygiene.py` 의 추적 파일 검사가
    닿지 못한다. `--apply` 가 뭔가 만들기 **직전**에 `private/DENY.txt` 로 막는다.

    **실제 `private/DENY.txt` 는 절대 쓰지 않는다** — 우리만의 가짜 금칙어로 주입해서
    증명한다.
    """

    FIXTURE_TERM = "ZQX-FIXTURE-INTERNAL-CODE"

    def _repo_with_deny(self, *terms):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        os.makedirs(os.path.join(repo, "private"))
        with open(os.path.join(repo, "private", "DENY.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(terms) + "\n")
        return repo, bare

    def test_a_hit_blocks_the_phase_creates_nothing_and_never_prints_the_string(self):
        repo, bare = self._repo_with_deny(self.FIXTURE_TERM)
        sha = _sha(repo, "PMF50 완료")
        # 게이트는 공개되는 `summary` 만 본다 — `notes`(전체 본문, 공개 안 됨)에는
        # 일부러 안 넣는다.
        summary = f"이 요약엔 {self.FIXTURE_TERM} 이 섞여 있다"
        plan = [_plan_entry("phase/PMF50", sha, notes="내부 전체 기록 — 공개 안 됨",
                            summary=summary)]

        # gh 를 한 번이라도 부르면 실패시킨다 — 차단된 Phase 는 gh 호출까지 가면 안 된다.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"),
                               gh_runner=_poison("금칙 문자열이 있는데 gh 를 불렀다"))
        out = buf.getvalue()

        self.assertEqual(1, code, "금칙 문자열 적중인데 성공으로 끝났다")
        self.assertIn("phase/PMF50", out)
        self.assertIn("1건", out)
        self.assertNotIn(self.FIXTURE_TERM, out, "금칙 문자열 자체가 출력에 그대로 찍혔다")
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip(),
                         "차단됐는데 로컬에 태그가 생겼다")
        self.assertEqual("", _git(bare, "tag", "-l").stdout.strip(),
                         "차단됐는데 원격에 태그가 생겼다")

    def test_clean_notes_proceed_past_the_gate(self):
        repo, bare = self._repo_with_deny(self.FIXTURE_TERM)
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha, notes="완전히 깨끗한 공개 노트")]

        def fake_gh(argv, **kwargs):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            return 0, "", ""

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=fake_gh)
        out = buf.getvalue()

        self.assertEqual(0, code, "깨끗한 노트인데 차단됐다")
        self.assertIn("생성 1", out)
        self.assertEqual("phase/PMF50", _git(bare, "tag", "-l", "phase/PMF50").stdout.strip())

    def test_missing_deny_file_is_reported_not_silent(self):
        """`private/DENY.txt` 가 없는 환경(CI, 다른 머신)이 정상 경로다 — 조용히
        넘어가지 않고 그 사실을 출력에 남긴다."""
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")  # private/ 자체가 없다
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha, notes="깨끗한 노트")]

        def fake_gh(argv, **kwargs):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            return 0, "", ""

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=fake_gh)
        out = buf.getvalue()

        self.assertEqual(0, code)
        self.assertIn("private/DENY.txt 없음", out)


class DryRunShowsHygieneRefusalsTest(unittest.TestCase):
    """Important 1 — dry-run 이 보여주는 'N개 태그 가능' 은 --apply 승인 근거다.
    걸릴 phase 를 숨기면 그 숫자가 거짓말이 된다. 게이트는 apply 여부와 무관하게
    돈다 — 실제 private/DENY.txt 는 절대 쓰지 않는다."""

    FIXTURE_TERM = "ZQX-FIXTURE-INTERNAL-CODE"

    def test_dry_run_marks_a_dirty_phase_and_corrects_the_taggable_count(self):
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        os.makedirs(os.path.join(repo, "private"))
        with open(os.path.join(repo, "private", "DENY.txt"), "w", encoding="utf-8") as fh:
            fh.write(self.FIXTURE_TERM + "\n")
        sha = _sha(repo, "PMF50 완료")
        # 게이트는 공개되는 `summary` 만 본다.
        plan = [_plan_entry("phase/PMF50", sha, notes="내부 전체 기록 — 공개 안 됨",
                            summary=f"{self.FIXTURE_TERM} 섞임")]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=False)
        out = buf.getvalue()

        self.assertEqual(0, code, "dry-run 은 항상 0 이어야 한다 — 아무것도 안 만든다")
        self.assertIn("[dry-run]", out)
        self.assertIn("phase/PMF50", out)
        self.assertIn("1건", out)
        self.assertIn("1개 Phase 중 0개 태그 가능, 1개 보류", out,
                      "금칙 검사 적중을 '태그 가능' 수에서 빼지 않았다 — dry-run 이 과장 보고한다")
        self.assertNotIn(self.FIXTURE_TERM, out, "금칙 문자열 자체가 dry-run 출력에 찍혔다")
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip(), "dry-run 인데 태그가 생겼다")

    def test_a_clean_phase_still_counts_normally_next_to_a_dirty_one(self):
        """적중 여부와 무관하게 각 phase 는 여전히 목록에 나온다 — 사라지면 안 된다."""
        repo, _bare = _repo_with_origin(
            "feat: PMF49 완료 — 픽스처", "feat: PMF50 완료 — 픽스처")
        os.makedirs(os.path.join(repo, "private"))
        with open(os.path.join(repo, "private", "DENY.txt"), "w", encoding="utf-8") as fh:
            fh.write(self.FIXTURE_TERM + "\n")
        sha49 = _sha(repo, "PMF49 완료")
        sha50 = _sha(repo, "PMF50 완료")
        plan = [
            {"phase": "PHASE_PMF49", "tag": "phase/PMF49", "sha": sha49,
             "notes": "내부 전체 기록 — 공개 안 됨", "summary": "깨끗한 요약",
             "skipped_reason": None},
            {"phase": "PHASE_PMF50", "tag": "phase/PMF50", "sha": sha50,
             "notes": "내부 전체 기록 — 공개 안 됨", "summary": f"{self.FIXTURE_TERM} 포함",
             "skipped_reason": None},
        ]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=False)
        out = buf.getvalue()

        self.assertEqual(0, code)
        self.assertIn("phase/PMF49  ", out)
        self.assertIn("phase/PMF50  ", out)
        self.assertIn("2개 Phase 중 1개 태그 가능, 1개 보류", out)


class WholePlanHygienePreflightTest(unittest.TestCase):
    """Important 1 — 한 phase 라도 걸리면 **아무것도 시작하지 않는다.** plan 에서
    깨끗한 phase 가 걸린 phase 보다 앞에 있어도(이름순이면 흔하다) 그것마저 만들면
    안 된다 — 부분 공개보다 전체 거부가 안전하다."""

    FIXTURE_TERM = "ZQX-FIXTURE-INTERNAL-CODE"

    def test_a_dirty_phase_blocks_creation_for_a_clean_phase_listed_before_it(self):
        repo, bare = _repo_with_origin(
            "feat: PMF49 완료 — 픽스처", "feat: PMF50 완료 — 픽스처")
        os.makedirs(os.path.join(repo, "private"))
        with open(os.path.join(repo, "private", "DENY.txt"), "w", encoding="utf-8") as fh:
            fh.write(self.FIXTURE_TERM + "\n")
        sha49 = _sha(repo, "PMF49 완료")
        sha50 = _sha(repo, "PMF50 완료")
        # PMF49 는 깨끗하고 목록의 **앞**에 있다 — 예전 방식(phase 별 루프 안에서
        # 그때그때 거부)이라면 PMF50 에 도달하기 전에 이미 태그·push 됐을 것이다.
        plan = [
            {"phase": "PHASE_PMF49", "tag": "phase/PMF49", "sha": sha49,
             "notes": "내부 전체 기록 — 공개 안 됨", "summary": "완전히 깨끗한 요약",
             "skipped_reason": None},
            {"phase": "PHASE_PMF50", "tag": "phase/PMF50", "sha": sha50,
             "notes": "내부 전체 기록 — 공개 안 됨", "summary": f"{self.FIXTURE_TERM} 포함",
             "skipped_reason": None},
        ]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"),
                               gh_runner=_poison("전체 사전 검사를 통과 못 했는데 gh 를 불렀다"))

        self.assertEqual(1, code)
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip(),
                         "깨끗한 phase(PMF49)까지 태그가 생겼다 — 부분 실행됐다")
        self.assertEqual("", _git(bare, "tag", "-l").stdout.strip())


class StructuralRulesReusedTest(unittest.TestCase):
    """Important 2 — R1–R4 는 `private/DENY.txt` 가 없어도 항상 돈다. 이 레포가 겪은
    실제 사고 두 건 모두 이 층만으로 잡혔다(구조 규칙 파일의 기록) — 그 층을 그대로
    불러 쓴다(사본 없음)."""

    def test_a_structural_violation_blocks_even_without_a_deny_file(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        # private/ 자체가 없다 — DENY.txt 는 절대 없다.
        sha = _sha(repo, "PMF50 완료")
        # R3(17~20자리 숫자)와 같은 모양의 완전히 지어낸 자리수 — 실제 uid 아님.
        # 게이트는 공개되는 `summary` 만 본다.
        summary = "테스트용 가짜 uid 12345678901234567 로 발급"  # public-ok
        plan = [_plan_entry("phase/PMF50", sha, notes="내부 전체 기록 — 공개 안 됨",
                            summary=summary)]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"),
                               gh_runner=_poison("구조 규칙 적중인데 gh 를 불렀다"))
        out = buf.getvalue()

        self.assertEqual(1, code)
        self.assertIn("phase/PMF50", out)
        self.assertNotIn("12345678901234567", out, "구조 규칙 적중 문자열이 그대로 찍혔다")  # public-ok
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip())
        self.assertEqual("", _git(bare, "tag", "-l").stdout.strip())

    def test_clean_notes_are_unaffected_by_the_structural_layer(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha, notes="완전히 평범한 공개 노트")]

        def fake_gh(argv, **kwargs):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            return 0, "", ""

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=fake_gh)

        self.assertEqual(0, code)
        self.assertEqual("phase/PMF50", _git(bare, "tag", "-l", "phase/PMF50").stdout.strip())


class StructuralHitCountUnitTest(unittest.TestCase):
    """`_structural_hit_count`/`_structural_rules` 자체 — 사본이 아니라 실제
    `tests/test_public_hygiene.py` 의 RULES 를 가져오는지도 함께 본다."""

    def test_reuses_the_same_rules_object_as_the_hygiene_test_file(self):
        path = os.path.join(gh.ROOT, "tests", "test_public_hygiene.py")
        spec = importlib.util.spec_from_file_location("_direct_hygiene_check", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(list(mod.RULES), list(gh._structural_rules()),
                         "규칙 사본이 원본과 어긋났다 — 두 벌을 두면 반드시 벌어진다")

    def test_a_clean_note_has_zero_structural_hits(self):
        self.assertEqual(0, gh._structural_hit_count("완전히 평범한 문장"))

    def test_an_r1_shaped_number_counts_as_a_hit(self):
        self.assertEqual(1, gh._structural_hit_count("합계 1,234,567,890 토큰"))  # public-ok

    def test_empty_notes_have_zero_hits(self):
        self.assertEqual(0, gh._structural_hit_count(""))
        self.assertEqual(0, gh._structural_hit_count(None))


class EmptyDenyFileIsNotSilentTest(unittest.TestCase):
    """Minor 4 — 파일은 있는데 항목이 0개면(잘렸거나 손상됐을 수 있다) 조용히
    '검사했더니 깨끗했다'로 통과시키면 안 된다. `tests/test_public_hygiene.py` 의
    `ExactDenyListTest` 도 이 경우를 하드 실패로 다룬다 — 여기서도 같게 다룬다."""

    def _repo_with_empty_deny(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        os.makedirs(os.path.join(repo, "private"))
        open(os.path.join(repo, "private", "DENY.txt"), "w", encoding="utf-8").close()
        return repo, bare

    def test_apply_refuses_when_the_deny_file_is_present_but_empty(self):
        repo, bare = self._repo_with_empty_deny()
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha, notes="완전히 깨끗한 노트")]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"),
                               gh_runner=_poison("DENY.txt 가 비어 있는데 gh 를 불렀다"))

        self.assertEqual(1, code, "DENY.txt 가 비어 있는데 성공으로 끝났다 — 조용히 통과시켰다")
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip())
        self.assertEqual("", _git(bare, "tag", "-l").stdout.strip())

    def test_dry_run_still_shows_the_plan_when_the_deny_file_is_empty(self):
        """Important 1 과 같은 원칙 — 신뢰 못 하는 상태라도 dry-run 은 숨기지 않는다."""
        repo, _bare = self._repo_with_empty_deny()
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha, notes="완전히 깨끗한 노트")]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=False)
        out = buf.getvalue()

        self.assertEqual(0, code)
        self.assertIn("phase/PMF50", out)
        self.assertIn("[dry-run]", out)

    def test_a_present_deny_file_with_only_comments_is_also_treated_as_empty(self):
        """주석만 있는 파일은 `terms == []` 로 이어진다 — 같은 취급을 받아야 한다."""
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        os.makedirs(os.path.join(repo, "private"))
        with open(os.path.join(repo, "private", "DENY.txt"), "w", encoding="utf-8") as fh:
            fh.write("# 이 줄만 있다\n")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha, notes="완전히 깨끗한 노트")]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"),
                               gh_runner=_poison("주석뿐인 DENY.txt 인데 gh 를 불렀다"))

        self.assertEqual(1, code)


class HygieneLayerVisibilityTest(unittest.TestCase):
    """N1 — dry-run 은 두 층(구조 규칙 + 정확 금칙어) 모두 돌았다는 것과, 각각
    몇 개로 검사했는지를 말해야 한다. 안 그러면 'RULES 가 텅 비어도 화면 모양은
    깨끗한 실행과 똑같다'가 된다."""

    def test_dry_run_prints_both_layer_counts(self):
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        os.makedirs(os.path.join(repo, "private"))
        with open(os.path.join(repo, "private", "DENY.txt"), "w", encoding="utf-8") as fh:
            fh.write("ZQX-FIXTURE-ONE\nZQX-FIXTURE-TWO\n")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha, notes="깨끗한 노트")]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=False)
        out = buf.getvalue()

        self.assertEqual(0, code)
        self.assertIn("구조 규칙", out, "구조 규칙 층이 돌았다는 말이 dry-run 에 없다")
        self.assertIn(f"{len(gh._structural_rules())}개", out,
                      "구조 규칙 몇 개로 검사했는지가 dry-run 에 없다")
        self.assertIn("금칙 문자열 2개", out, "정확 금칙어 개수가 dry-run 에 없다")


class StructuralRulesEmptyIsNotSilentTest(unittest.TestCase):
    """N1 — `RULES` 가 비어 있으면(잘렸거나 손상됐을 수 있다) `_structural_hit_count`
    는 모든 노트에 조용히 0 을 돌려준다 — 그러면 R3 위반 노트로도 tag·push·release
    가 그대로 생긴다. `deny_corrupted` 와 똑같이 다뤄야 한다."""

    def setUp(self):
        self._saved_rules = gh._STRUCTURAL_RULES

    def tearDown(self):
        gh._STRUCTURAL_RULES = self._saved_rules

    def test_apply_refuses_when_structural_rules_are_empty(self):
        gh._STRUCTURAL_RULES = ()  # 잘리거나 손상된 RULES 를 흉내낸다
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        # DENY.txt 도 없다 — 구조 규칙이 유일한 층인 상태에서 그 층마저 비었다.
        plan = [_plan_entry("phase/PMF50", sha, notes="완전히 깨끗해 보이는 노트")]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"),
                               gh_runner=_poison("구조 규칙이 비었는데 gh 를 불렀다"))
        out = buf.getvalue()

        self.assertEqual(1, code, "구조 규칙이 0개인데 성공으로 끝났다 — 조용히 통과시켰다")
        self.assertIn("구조 규칙", out)
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip())
        self.assertEqual("", _git(bare, "tag", "-l").stdout.strip())

    def test_dry_run_still_shows_the_plan_when_structural_rules_are_empty(self):
        """Important 1 과 같은 원칙 — 신뢰 못 하는 상태라도 dry-run 은 숨기지 않는다."""
        gh._STRUCTURAL_RULES = ()
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha, notes="완전히 깨끗해 보이는 노트")]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=False)
        out = buf.getvalue()

        self.assertEqual(0, code)
        self.assertIn("phase/PMF50", out)
        self.assertIn("[dry-run]", out)
        self.assertIn("구조 규칙", out)

    def test_a_real_r3_violation_is_missed_only_while_rules_are_forced_empty(self):
        """비우기 전엔 잡히고, 비우면 놓친다는 것을 같은 요약으로 대조한다."""
        repo, _bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        summary = "테스트용 가짜 uid 98765432109876543 로 발급"  # public-ok

        # 1) 정상 상태 — 구조 규칙이 잡아 차단해야 한다. 게이트는 공개되는
        #    `summary` 만 본다.
        plan = [_plan_entry("phase/PMF50", sha, notes="내부 전체 기록 — 공개 안 됨",
                            summary=summary)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code_normal = gh._run_tag(plan, repo, apply=True,
                                      gh_check=lambda: (True, "ok"),
                                      gh_runner=_poison("정상 상태인데 구조 규칙을 놓쳤다"))
        self.assertEqual(1, code_normal, "정상 상태에서 R3 위반을 놓쳤다")

        # 2) RULES 를 비우면 같은 노트가 그대로 통과해 버린다 — 이게 N1 의 구멍이다.
        #    여기서는 그 구멍이 이제 막혔는지(하드 실패로) 를 같은 노트로 재확인한다.
        gh._STRUCTURAL_RULES = ()
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            code_empty = gh._run_tag(plan, repo, apply=True,
                                     gh_check=lambda: (True, "ok"),
                                     gh_runner=_poison("구조 규칙이 비었는데 gh 를 불렀다"))
        self.assertEqual(1, code_empty, "구조 규칙이 비었는데 통과시켰다")


class ReleaseSummaryTest(unittest.TestCase):
    """공개되는 것 — Phase 의 한 줄 요약. `release_notes()`(전체 본문, ~4KB)와
    달리 이게 실제로 태그·릴리스에 실린다."""

    def test_it_returns_the_one_line_title(self):
        self.assertEqual("공개 표면 — 밖에서 들어오는 사람의 경로",
                         gh.release_summary(PHASES, "PHASE_PMF14"))

    def test_unknown_phase_returns_none_not_empty_string(self):
        """`release_notes()` 와 같은 신호 — 빈 문자열이면 '요약 없는 릴리스'가
        조용히 만들어진다."""
        self.assertIsNone(gh.release_summary(PHASES, "PHASE_PMF99"))

    def test_it_is_much_shorter_than_the_full_notes(self):
        """실측: 태그 대상 6개 전부 21~32자, 본문은 ~4KB — 자릿수가 다르다."""
        notes = gh.release_notes(PHASES, "PHASE_PMF14")
        summary = gh.release_summary(PHASES, "PHASE_PMF14")
        self.assertLess(len(summary), len(notes))


class TagPlanCarriesASummaryTest(unittest.TestCase):
    """`tag_plan` 의 각 taggable 항목은 `notes`(내부) 와 `summary`(공개) 를
    모두 들고 있어야 한다 — 게이트·발행 둘 다 `summary` 를 봐야 하기 때문이다."""

    def test_every_planned_tag_carries_a_summary(self):
        for p in gh.tag_plan(PHASES, LOG):
            if p["sha"]:
                self.assertTrue(p["summary"], f"{p['phase']} 에 요약이 없다")

    def test_the_summary_is_the_one_line_title_not_the_full_body(self):
        # PHASE_PMF14 는 LOG 에 약한 후보만 있어 이 fixture 에서는 태깅 안 된다
        # (TagPlanTest 참고) — 강한 후보가 있는 PMF13 으로 확인한다.
        by = {p["phase"]: p for p in gh.tag_plan(PHASES, LOG)}
        self.assertEqual("링크 엔지니어링", by["PHASE_PMF13"]["summary"])
        self.assertNotIn("앞 Phase 의 후속이다", by["PHASE_PMF13"]["summary"],
                         "요약에 본문 내용이 섞였다 — 더 이상 공개되면 안 되는 텍스트다")


class GateChecksTheSummaryNotTheNotesTest(unittest.TestCase):
    """게이트는 공개되는 `summary` 만 본다 — `notes`(전체 본문, 더 이상 공개되지
    않음)를 검사하면 두 방향 다 틀린다: 아무도 안 볼 텍스트 때문에 거부하거나
    (오탐), 실제로 나가는 텍스트를 놓친다(누락). 두 방향 다 증명한다."""

    FIXTURE_TERM = "ZQX-FIXTURE-INTERNAL-CODE"

    def _repo_with_deny(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        os.makedirs(os.path.join(repo, "private"))
        with open(os.path.join(repo, "private", "DENY.txt"), "w", encoding="utf-8") as fh:
            fh.write(self.FIXTURE_TERM + "\n")
        return repo, bare

    def test_a_dirty_summary_refuses_even_with_clean_notes(self):
        repo, bare = self._repo_with_deny()
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry("phase/PMF50", sha, notes="완전히 깨끗한 내부 기록",
                            summary=f"{self.FIXTURE_TERM} 포함")]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"),
                               gh_runner=_poison("summary 가 걸렸는데 gh 를 불렀다"))

        self.assertEqual(1, code, "summary 가 걸렸는데 통과시켰다")
        self.assertEqual("", _git(repo, "tag", "-l").stdout.strip())
        self.assertEqual("", _git(bare, "tag", "-l").stdout.strip())

    def test_a_dirty_notes_does_not_refuse_when_the_summary_is_clean(self):
        """`notes` 는 더 이상 공개되지 않는다 — 거기 금칙 문자열이 있어도 막을
        이유가 없다. 막으면 아무도 안 볼 텍스트 때문에 거부하는 오탐이다."""
        repo, bare = self._repo_with_deny()
        sha = _sha(repo, "PMF50 완료")
        plan = [_plan_entry(
            "phase/PMF50", sha,
            notes=f"내부 전체 기록에만 있다 — {self.FIXTURE_TERM}",
            summary="완전히 깨끗한 공개 요약")]

        def fake_gh(argv, **kwargs):
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            return 0, "", ""

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=fake_gh)

        self.assertEqual(0, code, "notes 에만 있는 금칙 문자열 때문에 거부했다 — 오탐이다")
        self.assertEqual("phase/PMF50",
                         _git(bare, "tag", "-l", "phase/PMF50").stdout.strip())


class PublishedTextIsTheSummaryTest(unittest.TestCase):
    """부분 공개 결정의 핵심 — 태그 메시지와 `gh release create --notes` 모두
    `summary`(한 줄)만 실어야 한다. 둘 중 하나라도 `notes`(전체 본문)로 되돌아가면
    이 테스트가 실패해야 한다."""

    def test_both_publish_sinks_carry_the_summary_not_the_full_notes(self):
        repo, bare = _repo_with_origin("feat: PMF50 완료 — 픽스처")
        sha = _sha(repo, "PMF50 완료")
        # 서로 확실히 구분되는 표식 — 어느 쪽이 실렸는지 헷갈릴 여지가 없다.
        notes_marker = "AAAA-내부-전체-본문-마커-공개되면-안됨-AAAA"
        summary_marker = "BBBB-공개-요약-마커-BBBB"
        plan = [_plan_entry("phase/PMF50", sha, notes=notes_marker, summary=summary_marker)]

        calls = []

        def fake_gh(argv, **kwargs):
            calls.append(argv)
            if argv[:3] == ["gh", "release", "view"]:
                return 1, "", "not found"
            return 0, "", ""

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gh._run_tag(plan, repo, apply=True,
                               gh_check=lambda: (True, "ok"), gh_runner=fake_gh)
        self.assertEqual(0, code)

        # 싱크 1 — annotated 태그 메시지(push 되면 공개된다).
        tag_message = _git(repo, "tag", "-l", "--format=%(contents)",
                           "phase/PMF50").stdout
        self.assertIn(summary_marker, tag_message, "태그 메시지에 summary 가 없다")
        self.assertNotIn(notes_marker, tag_message,
                         "태그 메시지에 전체 notes 가 실렸다 — 공개 결정을 어겼다")

        # 싱크 2 — `gh release create --notes`.
        create_calls = [c for c in calls if c[:3] == ["gh", "release", "create"]]
        self.assertEqual(1, len(create_calls), "release create 를 정확히 한 번 불러야 한다")
        argv = create_calls[0]
        notes_arg = argv[argv.index("--notes") + 1]
        self.assertEqual(summary_marker, notes_arg,
                         "release --notes 에 summary 가 그대로 실리지 않았다")
        self.assertNotIn(notes_marker, notes_arg,
                         "release --notes 에 전체 notes 가 실렸다 — 공개 결정을 어겼다")
