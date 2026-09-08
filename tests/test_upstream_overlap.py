"""커밋하려는 순간, 원격이 움직였고 내가 들고 있는 파일이 그 파일인지 말한다.

## 감지가 있는데 왜 또 필요한가

`vibe-harness-worktree-guard.py` 는 **세션 시작 시점**에 "이 트리에 누가 쓰다 말았다"를
말한다. 그것은 맞는 신호지만 시점이 다르다. 실제로 물리는 곳은 **커밋하려는 순간**이고,
그때 필요한 정보는 트리가 더러운지가 아니라 이것이다:

    원격이 앞섰다 + 내가 들고 있는 더티 파일이 하필 그 앞선 커밋이 건드린 파일이다

2026-09-08 하루에 두 번 그랬다. 두 번 다 `server.py`·`kanban.json`·`runs.json` 이 겹쳐서
stash → pull → 재적용을 손으로 했다. 두 번째는 그 사고를 고치는 커밋을 만드는 중이었다.

## 겹치지 않으면 왜 FAIL 이 아닌가

원격이 앞선 것 자체는 흔하고, 겹치지 않으면 그냥 pull 하면 된다. 그때까지 멈추면
오탐이 잦아지고, 잦은 오탐은 검사를 끄게 만든다 — 꺼진 검사는 없는 것보다 나쁘다.
**행동이 필요한 것만 말한다.**

## fetch 실패가 왜 FAIL 이 아닌가

오프라인이면 원격 상태를 알 수 없다. **모른다는 것은 겹친다는 것이 아니다.** 가드의
기존 규율(주장을 증거보다 세게 하지 않는다)이 여기서도 그대로다 — 모르면 모른다고
말하고 비켜선다.

## 왜 진짜 저장소로 검사하는가

`git` 출력을 흉내내면 흉내낸 것을 검사하게 된다. 로컬 bare 저장소를 원격으로 두면
**네트워크 없이 진짜 fetch** 를 돌릴 수 있다. 그래서 mock 이 없다.
"""
import importlib.util
import os
import subprocess
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, "scripts", "hooks", "vibe-harness-worktree-guard.py")


def load_guard():
    spec = importlib.util.spec_from_file_location("vh_guard_overlap", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(repo, *args, check=True):
    """테스트용 git. 사용자 설정에 의존하지 않도록 신원을 인자로 준다."""
    done = subprocess.run(
        ["git", "-c", "user.email=t@example.test", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "-C", repo, *args],
        capture_output=True, text=True)
    if check and done.returncode != 0:
        raise AssertionError("git %s 실패: %s" % (" ".join(args), done.stderr))
    return done.stdout


def write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class OverlapTestCase(unittest.TestCase):
    """작업 저장소 하나 + 로컬 bare 원격 하나 + 원격에 직접 미는 두 번째 클론."""

    def setUp(self):
        self.guard = load_guard()
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name

        self.bare = os.path.join(base, "remote.git")
        subprocess.run(["git", "init", "--bare", "-b", "main", self.bare],
                       capture_output=True, check=True)

        self.repo = os.path.join(base, "work")
        subprocess.run(["git", "clone", self.bare, self.repo],
                       capture_output=True, check=True)
        write(self.repo, "shared.txt", "base\n")
        write(self.repo, "mine.txt", "base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "base")
        git(self.repo, "push", "-u", "origin", "main")

        # 다른 세션 역할. 여기서 커밋해 원격을 앞세운다.
        self.other = os.path.join(base, "other")
        subprocess.run(["git", "clone", self.bare, self.other],
                       capture_output=True, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def remote_moves(self, rel, text="from the other session\n"):
        write(self.other, rel, text)
        git(self.other, "add", "-A")
        git(self.other, "commit", "-m", "other session touches " + rel)
        git(self.other, "push", "origin", "main")

    def dirty(self, rel, text="my uncommitted work\n"):
        write(self.repo, rel, text)


class BehindDetectionTest(OverlapTestCase):
    def test_clean_and_current_reports_nothing_behind(self):
        found = self.guard.upstream_overlap(self.repo, fetch=True)

        self.assertEqual(0, found["behind"])
        self.assertEqual([], found["overlap"])

    def test_fetch_sees_a_commit_pushed_after_the_clone(self):
        """fetch 하지 않으면 못 보고, 하면 본다 — 정확성의 대가가 네트워크다."""
        self.remote_moves("shared.txt")

        stale = self.guard.upstream_overlap(self.repo, fetch=False)
        fresh = self.guard.upstream_overlap(self.repo, fetch=True)

        self.assertEqual(0, stale["behind"], "fetch 없이 원격 변화를 봤다면 테스트가 거짓이다")
        self.assertEqual(1, fresh["behind"])


class OverlapTest(OverlapTestCase):
    def test_the_file_i_am_holding_is_the_file_that_moved(self):
        """오늘 두 번 물린 그 상황."""
        self.remote_moves("shared.txt")
        self.dirty("shared.txt")

        found = self.guard.upstream_overlap(self.repo, fetch=True)

        self.assertEqual(["shared.txt"], found["overlap"])

    def test_remote_moved_but_not_my_files(self):
        """앞선 것만으로는 멈출 이유가 없다 — pull 하면 된다."""
        self.remote_moves("shared.txt")
        self.dirty("mine.txt")

        found = self.guard.upstream_overlap(self.repo, fetch=True)

        self.assertEqual(1, found["behind"])
        self.assertEqual([], found["overlap"])

    def test_untracked_files_count_as_mine(self):
        """`git add -A` 는 추적 여부를 가리지 않는다. 겹침 판정도 가려선 안 된다."""
        self.remote_moves("docs/new.md")
        self.dirty("docs/new.md")

        found = self.guard.upstream_overlap(self.repo, fetch=True)

        self.assertEqual(["docs/new.md"], found["overlap"])

    def test_a_path_with_a_space_is_not_lost(self):
        """경로를 줄 단위로 자르면 조용히 빠진다 — dirty_paths 가 -z 를 쓰는 이유."""
        self.remote_moves("a file.txt")
        self.dirty("a file.txt")

        found = self.guard.upstream_overlap(self.repo, fetch=True)

        self.assertEqual(["a file.txt"], found["overlap"])

    def test_overlap_is_sorted_and_deduplicated(self):
        self.remote_moves("shared.txt")
        self.remote_moves("mine.txt")
        self.dirty("shared.txt")
        self.dirty("mine.txt")

        found = self.guard.upstream_overlap(self.repo, fetch=True)

        self.assertEqual(["mine.txt", "shared.txt"], found["overlap"])


class UnknownStateTest(OverlapTestCase):
    def test_fetch_failure_is_reported_not_raised(self):
        """오프라인은 사고가 아니다. 모른다고 말하고 비켜선다."""
        git(self.repo, "remote", "set-url", "origin",
            os.path.join(self.tmp.name, "does-not-exist.git"))
        self.dirty("shared.txt")

        found = self.guard.upstream_overlap(self.repo, fetch=True)

        self.assertTrue(found["fetch_failed"])
        self.assertEqual([], found["overlap"], "모름을 겹침으로 바꾸면 안 된다")

    def test_no_upstream_is_not_an_error(self):
        """upstream 이 없으면 비교 대상이 없다. 그것도 말할 수 있는 것이 없는 경우다."""
        git(self.repo, "checkout", "-b", "local-only")

        found = self.guard.upstream_overlap(self.repo, fetch=False)

        self.assertIsNone(found["upstream"])
        self.assertEqual([], found["overlap"])

    def test_outside_a_repo_returns_none(self):
        outside = os.path.join(self.tmp.name, "not-a-repo")
        os.makedirs(outside, exist_ok=True)

        self.assertIsNone(self.guard.upstream_overlap(outside, fetch=False))


class MessageTest(OverlapTestCase):
    """말하는 것도 규약이다 — 할 말이 없으면 조용하다."""

    def test_silent_when_there_is_nothing_to_act_on(self):
        found = self.guard.upstream_overlap(self.repo, fetch=True)

        self.assertIsNone(self.guard.overlap_message(found))

    def test_overlap_is_named(self):
        self.remote_moves("shared.txt")
        self.dirty("shared.txt")
        found = self.guard.upstream_overlap(self.repo, fetch=True)

        text = self.guard.overlap_message(found)

        self.assertIn("shared.txt", text)

    def test_behind_without_overlap_says_so_without_alarm(self):
        self.remote_moves("shared.txt")
        self.dirty("mine.txt")
        found = self.guard.upstream_overlap(self.repo, fetch=True)

        text = self.guard.overlap_message(found)

        self.assertIsNotNone(text)
        self.assertNotIn("shared.txt", text,
                         "겹치지도 않은 파일 이름을 대면 경고가 소음이 된다")

    def test_fetch_failure_says_it_does_not_know(self):
        git(self.repo, "remote", "set-url", "origin",
            os.path.join(self.tmp.name, "does-not-exist.git"))
        found = self.guard.upstream_overlap(self.repo, fetch=True)

        text = self.guard.overlap_message(found)

        self.assertIsNotNone(text)


if __name__ == "__main__":
    unittest.main()


class FetchPolicyTest(OverlapTestCase):
    """`check.py` 는 언제 네트워크를 타는가.

    그 파일에는 반대 방향의 규칙이 이미 적혀 있다 — "네트워크는 건드리지 않는다.
    fetch 는 ss 의 일이고, 여기서 또 하면 느리고 오프라인에서 막힌다."

    둘 다 지킬 수 있다. **깨끗한 트리에서는 겹침이 애초에 불가능하다** — 들고 있는
    파일이 없으니 무엇과도 겹칠 수 없다. 그러니 fetch 는 답을 바꿀 수 있을 때만 한다.
    """

    def setUp(self):
        super().setUp()
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_fetch_policy", os.path.join(ROOT, "scripts", "check.py"))
        self.check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.check)

    def test_clean_tree_does_not_reach_the_network(self):
        self.remote_moves("shared.txt")   # 원격은 앞섰지만 내 트리는 깨끗하다

        found = self.check.upstream_conflict(self.repo)

        self.assertFalse(found["fetched"],
                         "겹칠 수 없는 상태에서 네트워크를 탔다")
        self.assertEqual([], found["overlap"])

    def test_dirty_tree_fetches_and_finds_the_overlap(self):
        self.remote_moves("shared.txt")
        self.dirty("shared.txt")

        found = self.check.upstream_conflict(self.repo)

        self.assertTrue(found["fetched"], "겹칠 수 있는 상태인데 확인하지 않았다")
        self.assertEqual(["shared.txt"], found["overlap"])

    def test_overlap_is_the_only_thing_that_fails_the_gate(self):
        self.remote_moves("shared.txt")
        self.dirty("mine.txt")

        found = self.check.upstream_conflict(self.repo)

        self.assertEqual(1, found["behind"])
        self.assertFalse(self.check.conflict_fails_gate(found),
                         "겹치지 않는 앞섬으로 멈추면 오탐이 잦아진다")

    def test_overlap_fails_the_gate(self):
        self.remote_moves("shared.txt")
        self.dirty("shared.txt")

        found = self.check.upstream_conflict(self.repo)

        self.assertTrue(self.check.conflict_fails_gate(found))

    def test_not_knowing_does_not_fail_the_gate(self):
        git(self.repo, "remote", "set-url", "origin",
            os.path.join(self.tmp.name, "does-not-exist.git"))
        self.dirty("shared.txt")

        found = self.check.upstream_conflict(self.repo)

        self.assertTrue(found["fetch_failed"])
        self.assertFalse(self.check.conflict_fails_gate(found),
                         "모름을 실패로 바꾸면 오프라인에서 커밋을 못 한다")
