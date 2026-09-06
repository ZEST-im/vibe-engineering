"""한 워킹트리를 여러 세션이 공유하는 것을 감지한다.

주간 리뷰가 **3주 연속** 지적하고 critical 로 올린 P1 이다. 병렬 세션이 한 트리를
공유하는데, 세션 A 가 `git add -A` 로 담을 때 그 트리에는 세션 B 가 만들던 파일이
함께 있다. **그렇게 사내 수치가 공개 레포로 올라갔다.**

이 레포는 겪은 사고를 검사로 바꾸는 데 강한데 유독 이 항목만 '인식'에 멈춰 있었다.
잠글 수 없다는 것이 아무것도 안 해도 된다는 뜻은 아니다.

이 파일이 지키는 것 넷:

1. **깨끗한 트리에는 말을 걸지 않는다.** 매번 뜨는 경고는 곧 안 읽히고, 안 읽히는
   경고는 있다고 믿게 만들어 없는 것보다 나쁘다.
2. **주장을 증거보다 세게 하지 않는다.** "다른 세션이 작업 중"은 등록부 없이는 증명할
   수 없다. 최근 변경과 오래된 변경을 나누고, 소유권 주장은 세션 시작일 때만 한다.
3. **막지 않는다.** 종료 코드는 언제나 0 이다 — 오탐 한 번에 작업이 멈추면 꺼진다.
4. **자기가 감지하려는 것을 자기가 만들지 않는다.** `git status` 가 인덱스를 갱신하며
   `.git/index.lock` 을 잡으면 이 검사가 자기 잠금을 자기가 본다.
"""
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
HOOKS = os.path.join(ROOT, "scripts", "hooks")
GUARD = os.path.join(HOOKS, "vibe-harness-worktree-guard.py")

_spec = importlib.util.spec_from_file_location("worktree_guard", GUARD)
wg = importlib.util.module_from_spec(_spec)
sys.modules["worktree_guard"] = wg
_spec.loader.exec_module(wg)


def git(repo, *args, check=True):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", repo, *args], capture_output=True,
                          text=True, env=env, check=check)


def make_repo():
    """커밋 하나가 있는 깨끗한 저장소.

    브랜치 이름을 호스트 설정에 맡기지 않는다 — `init.defaultBranch` 하나에 끌려
    다른 것을 검사하게 되는 것을 이 레포는 이미 겪었다.
    """
    d = tempfile.mkdtemp()
    git(d, "init", "-q", "-b", "main")
    with open(os.path.join(d, "kept.txt"), "w", encoding="utf-8") as fh:
        fh.write("base\n")
    git(d, "add", "kept.txt")
    git(d, "commit", "-q", "-m", "base")
    return d


def write(repo, name, body="x", age_minutes=0):
    path = os.path.join(repo, name)
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(name) else None
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    if age_minutes:
        old = time.time() - age_minutes * 60
        os.utime(path, (old, old))
    return path


class SilentWhenNothingToSayTest(unittest.TestCase):
    """매번 뜨는 경고는 경고가 아니라 배경 소음이다."""

    def test_clean_tree_says_nothing(self):
        repo = make_repo()
        self.assertIsNone(wg.message(wg.survey(repo), session_start=True),
                          "깨끗한 트리에 말을 걸면 다음번에 안 읽힌다")

    def test_not_a_repo_says_nothing(self):
        self.assertIsNone(wg.survey(tempfile.mkdtemp()))

    def test_ignored_files_do_not_count(self):
        """gitignore 된 것은 `add -A` 로도 안 담긴다 — 사고의 재료가 아니다."""
        repo = make_repo()
        with open(os.path.join(repo, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write("noise.log\n")
        git(repo, "add", ".gitignore")
        git(repo, "commit", "-q", "-m", "ignore")
        write(repo, "noise.log")
        self.assertEqual([], wg.survey(repo)["dirty"])


class TellsRecentFromStaleTest(unittest.TestCase):
    """이것이 오탐과 진짜 신호를 가르는 유일한 축이다."""

    def test_a_file_touched_just_now_is_recent(self):
        repo = make_repo()
        write(repo, "kept.txt", "changed")
        found = wg.survey(repo)
        self.assertEqual(["kept.txt"], found["recent"])
        self.assertIn("🟡", wg.message(found, session_start=True))

    def test_yesterdays_leftovers_are_not_called_active(self):
        """어제 두고 간 내 작업까지 '방금'이라고 하면 그 신호는 의미가 없다."""
        repo = make_repo()
        write(repo, "kept.txt", "changed", age_minutes=24 * 60)
        found = wg.survey(repo)
        self.assertEqual([], found["recent"])
        text = wg.message(found, session_start=True)
        self.assertIn("⚠", text)
        self.assertNotIn("🟡", text)

    def test_untracked_files_count(self):
        """`add -A` 는 추적 여부를 가리지 않는다. 감지도 가리면 안 된다."""
        repo = make_repo()
        write(repo, "secret-notes.md")
        self.assertIn("secret-notes.md", wg.survey(repo)["dirty"])

    def test_a_deleted_file_does_not_crash_the_survey(self):
        """지워진 파일은 mtime 이 없다. 없는 것을 세지도, 죽지도 않는다."""
        repo = make_repo()
        os.remove(os.path.join(repo, "kept.txt"))
        found = wg.survey(repo)
        self.assertEqual(["kept.txt"], found["dirty"])
        self.assertEqual([], found["recent"])

    def test_paths_with_spaces_survive(self):
        """줄 단위로 자르면 이런 경로가 조용히 빠진다. `-z` 로 읽는 이유다."""
        repo = make_repo()
        write(repo, "a file with spaces.txt")
        self.assertIn("a file with spaces.txt", wg.survey(repo)["dirty"])


class ClaimsOnlyWhatItCanProveTest(unittest.TestCase):
    def test_index_lock_is_reported_as_certain(self):
        """이건 추정이 아니다 — 다른 git 프로세스가 지금 돌고 있다는 뜻이다."""
        repo = make_repo()
        open(os.path.join(repo, ".git", "index.lock"), "w").close()
        self.assertIn("🔴", wg.message(wg.survey(repo), session_start=True))

    def test_index_lock_alone_still_warns(self):
        """트리가 깨끗해도 잠금이 있으면 말해야 한다 — 지금 누가 쓰고 있다."""
        repo = make_repo()
        open(os.path.join(repo, ".git", "index.lock"), "w").close()
        self.assertIsNotNone(wg.message(wg.survey(repo), session_start=True))

    def test_ownership_is_claimed_only_at_session_start(self):
        """손으로 돌릴 때는 방금 내가 만든 변경일 수 있다. 그때는 남의 것이라 하지 않는다."""
        repo = make_repo()
        write(repo, "kept.txt", "changed")
        found = wg.survey(repo)
        self.assertIn("이 세션이 만든 것이 아닙니다", wg.message(found, session_start=True))
        self.assertNotIn("이 세션이 만든 것이 아닙니다", wg.message(found, session_start=False))

    def test_it_names_the_actual_hazard(self):
        """누구 것인지 몰라서 난 사고가 아니다. 전부 담아서 난 사고다."""
        repo = make_repo()
        write(repo, "kept.txt", "changed")
        self.assertIn("git add -A", wg.message(wg.survey(repo), session_start=True))

    def test_long_lists_are_trimmed(self):
        """스크롤이 되면 안 읽힌다."""
        repo = make_repo()
        for i in range(12):
            write(repo, "f%02d.txt" % i)
        text = wg.message(wg.survey(repo), session_start=True)
        self.assertIn("외 7건", text)


class NeverBlocksTest(unittest.TestCase):
    """오탐 한 번에 작업이 멈추면 그 검사는 곧 꺼진다."""

    def run_quiet(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = wg.main(argv)
        return code, buf.getvalue()

    def test_exit_zero_on_a_dirty_tree(self):
        repo = make_repo()
        write(repo, "kept.txt", "changed")
        code, out = self.run_quiet([repo, "--session-start"])
        self.assertEqual(0, code)
        self.assertIn("🟡", out, "경고를 내야 할 상황에 조용했다")

    def test_exit_zero_outside_a_repo(self):
        code, out = self.run_quiet([tempfile.mkdtemp()])
        self.assertEqual(0, code)
        self.assertEqual("", out)

    def test_exit_zero_when_the_survey_explodes(self):
        saved = wg.survey
        wg.survey = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.assertEqual(0, self.run_quiet(["."])[0])
        finally:
            wg.survey = saved


class DoesNotCauseWhatItDetectsTest(unittest.TestCase):
    def test_git_is_called_without_optional_locks(self):
        """`git status` 가 인덱스를 갱신하면 스스로 `.git/index.lock` 을 잡는다.

        그러면 이 검사가 자기 잠금을 자기가 보고, 매 세션 🔴 를 띄운다 — 오탐 중에서도
        가장 나쁜 종류다(원인이 검사 자신이라 아무리 조심해도 안 사라진다).
        """
        repo = make_repo()          # 픽스처의 git 호출까지 세면 안 된다
        seen = []
        real = subprocess.run

        def spy(argv, *a, **k):
            seen.append(list(argv))
            return real(argv, *a, **k)

        wg.subprocess.run = spy
        try:
            wg.survey(repo)
        finally:
            wg.subprocess.run = real
        self.assertTrue(seen, "git 을 한 번도 부르지 않았다")
        for argv in seen:
            self.assertIn("--no-optional-locks", argv,
                          "인덱스를 갱신할 수 있는 git 호출이 있다: %s" % " ".join(argv))


class ShippedAndWiredTest(unittest.TestCase):
    """만들어놓고 배선하지 않으면 아무 세션에서도 돌지 않는다."""

    def test_the_session_hook_calls_it(self):
        with open(os.path.join(HOOKS, "vibe-harness-session-start.sh"),
                  encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("vibe-harness-worktree-guard.py", body)
        self.assertIn("--session-start", body,
                      "훅이 세션 시작임을 알리지 않으면 소유권 문구가 안 나온다")
        # Phase 파일이 있을 때와 없을 때, 두 경로 모두에서 불려야 한다.
        self.assertEqual(3, body.count("warn_if_worktree_shared"),
                         "정의 1 + 호출 2 여야 한다 — 한쪽 경로만 넣으면 절반이 못 본다")

    def test_the_rule_is_written_where_the_agent_reads_it(self):
        """감지는 사람이 아니라 에이전트에게 말한다. 규칙이 스킬에 없으면 다음 세션이
        경고를 읽고도 `git add -A` 를 친다 — 무엇을 하라는 건지 안 적혀 있으니까."""
        with open(os.path.join(ROOT, "skills", "vibe-harness", "SKILL.md"),
                  encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("git add -A", body,
                      "무엇이 위험한 동작인지 스킬이 말하지 않는다")
        self.assertIn("index.lock", body,
                      "🔴 를 봤을 때 무엇을 하라는지 스킬이 말하지 않는다")

    def test_the_installer_ships_it(self):
        with open(os.path.join(ROOT, "scripts", "setup.py"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn('"vibe-harness-worktree-guard.py"', body,
                      "설치 목록에 없으면 훅은 있는데 헬퍼가 없어 조용히 아무것도 안 한다")


if __name__ == "__main__":
    unittest.main()
