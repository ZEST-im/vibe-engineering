"""`--update-skill` 이 스킬을 하나만 갱신하고 있었다.

## 무엇이 났나

2026-09-29, 새 스킬 4종(`vibe-sa`·`vibe-aa`·`vibe-da`·`vibe-ta`)을 머지하고
`enroll.py --update-skill` 을 돌렸다. **"16개 파일 반영" 이라고 했는데 새 스킬은 하나도
안 깔렸다.** 확인해 보니 `vibe-debug` 도 없었다 — 이틀 전에 머지된 것이다.

원인은 단순하다. `--update-skill` 의 복사 목록은 `vibe-harness` 자신의 파일만 담는다.
다른 스킬 디렉토리는 **애초에 대상이 아니었다.** 갱신이 실패한 것이 아니라 갱신할
생각이 없었던 것이고, 그 사실을 아무도 말해주지 않았다.

그것들을 설치하는 것은 `setup.py` 뿐인데, 그 파일은 훅과 자동시작까지 건드린다 —
실제로 그날 `setup.py` 를 잘못 실행해 **훅이 5개 이벤트에 중복 등록**됐다.

## 왜 `setup.py` 의 함수를 부르는가

`copy_skill_files()` 가 이미 두 가지를 정확히 한다.

- **Claude 와 Codex 양쪽**에 깐다. 한쪽만 하면 Codex 에서는 옛 스킬이 돈다
- Codex 사본에서 `user-invocable:` 을 걷어낸다 — **그게 남아 있으면 Codex 가 그
  스킬을 거부한다.** 복사는 성공했다고 출력되고 스킬만 없다

여기서 다시 구현하면 저 두 가지가 조용히 빠진다. 이 레포는 설치 파일 목록이 세 곳으로
갈렸던 사고를 이미 겪었다.

## 목록도 손으로 적지 않는다

무엇을 설치할지는 `setup.SKILLS` 하나가 정한다. 여기 두 번째 목록을 두면, 스킬을
추가했을 때 설치는 되는데 갱신은 안 되는 상태가 조용히 생긴다.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

os.environ["VIBE_HARNESS_SYNC_CONFIG"] = os.path.join(
    tempfile.gettempdir(), "vibe-harness-update-all-no-sync.json")


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


enroll = load("vh_enroll_update_all", "enroll.py")
setup = load("vh_setup_update_all", "setup.py")


class EverySkillIsCoveredTest(unittest.TestCase):
    """설치되는 스킬과 갱신되는 스킬이 같아야 한다."""

    def test_the_skill_list_comes_from_setup(self):
        """두 번째 목록을 두지 않는다 — 스킬을 추가하면 자동으로 따라와야 한다."""
        self.assertEqual(sorted(setup.SKILLS), sorted(enroll.skill_dirs_to_install()))

    def test_the_new_architecture_skills_are_included(self):
        covered = set(enroll.skill_dirs_to_install())

        for name in ("vibe-sa", "vibe-aa", "vibe-da", "vibe-ta", "vibe-debug"):
            self.assertIn(name, covered, f"{name} 이 갱신 대상에서 빠졌다")

    def test_every_covered_skill_exists_in_the_repo(self):
        for name in enroll.skill_dirs_to_install():
            self.assertTrue(
                os.path.isfile(os.path.join(ROOT, "skills", name, "SKILL.md")),
                f"{name} 이 목록에 있는데 레포에 없다")


class ItInstallsToBothRootsTest(unittest.TestCase):
    """Codex 쪽을 빼먹으면 거기서는 옛 스킬이 돈다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.claude = os.path.join(self.tmp.name, "claude")
        self.codex = os.path.join(self.tmp.name, "codex")
        self._saved = (setup.SKILLS_ROOT, setup.CODEX_SKILLS_ROOT)
        setup.SKILLS_ROOT, setup.CODEX_SKILLS_ROOT = self.claude, self.codex

    def tearDown(self):
        setup.SKILLS_ROOT, setup.CODEX_SKILLS_ROOT = self._saved
        self.tmp.cleanup()

    def test_skills_land_in_both(self):
        enroll.install_skill_dirs(ROOT, setup_mod=setup)

        for root in (self.claude, self.codex):
            for name in ("vibe-sa", "vibe-debug"):
                self.assertTrue(os.path.isfile(os.path.join(root, name, "SKILL.md")),
                                f"{root} 에 {name} 이 없다")

    def test_the_codex_copy_drops_user_invocable(self):
        """남아 있으면 Codex 가 그 스킬을 거부한다 — 설치는 성공으로 보인다."""
        enroll.install_skill_dirs(ROOT, setup_mod=setup)

        claude_md = open(os.path.join(self.claude, "vibe-sa", "SKILL.md"), encoding="utf-8").read()
        codex_md = open(os.path.join(self.codex, "vibe-sa", "SKILL.md"), encoding="utf-8").read()

        self.assertIn("user-invocable:", claude_md)
        self.assertNotIn("user-invocable:", codex_md)

    def test_support_files_come_along(self):
        """references/ 가 빠지면 SKILL.md 의 조회 표가 죽은 포인터가 된다."""
        enroll.install_skill_dirs(ROOT, setup_mod=setup)

        self.assertTrue(
            os.path.isfile(os.path.join(self.claude, "vibe-harness",
                                        "references", "task-schema.md")),
            "vibe-harness 의 references 가 따라오지 않았다")


class MachineLocalStateSurvivesTest(unittest.TestCase):
    """설치본의 `vibe-harness` 에는 머신 로컬 상태가 함께 산다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.claude = os.path.join(self.tmp.name, "claude")
        self.codex = os.path.join(self.tmp.name, "codex")
        self._saved = (setup.SKILLS_ROOT, setup.CODEX_SKILLS_ROOT)
        setup.SKILLS_ROOT, setup.CODEX_SKILLS_ROOT = self.claude, self.codex
        self.harness = os.path.join(self.claude, "vibe-harness")
        os.makedirs(self.harness)
        for name in ("sync.json", "projects.json", "users.json", "push-state.json"):
            with open(os.path.join(self.harness, name), "w", encoding="utf-8") as fh:
                json.dump({"지켜져야": name}, fh, ensure_ascii=False)

    def tearDown(self):
        setup.SKILLS_ROOT, setup.CODEX_SKILLS_ROOT = self._saved
        self.tmp.cleanup()

    def test_local_json_is_not_wiped(self):
        enroll.install_skill_dirs(ROOT, setup_mod=setup)

        for name in ("sync.json", "projects.json", "users.json", "push-state.json"):
            path = os.path.join(self.harness, name)
            self.assertTrue(os.path.isfile(path), f"{name} 이 사라졌다")
            self.assertEqual(name, json.load(open(path, encoding="utf-8"))["지켜져야"])


class ItSaysWhatIsMissingTest(unittest.TestCase):
    """"N개 반영" 만 말하고 빠진 것을 말하지 않던 것이 이 사고의 근본이다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "install")

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_missing_after_a_full_install(self):
        os.makedirs(self.root)
        for name in setup.SKILLS:
            os.makedirs(os.path.join(self.root, name), exist_ok=True)
            open(os.path.join(self.root, name, "SKILL.md"), "w", encoding="utf-8").close()

        self.assertEqual([], enroll.missing_installed_skills(self.root, setup_mod=setup))

    def test_an_absent_skill_is_named(self):
        os.makedirs(self.root)
        for name in setup.SKILLS:
            if name == "vibe-sa":
                continue
            os.makedirs(os.path.join(self.root, name), exist_ok=True)
            open(os.path.join(self.root, name, "SKILL.md"), "w", encoding="utf-8").close()

        self.assertEqual(["vibe-sa"], enroll.missing_installed_skills(self.root, setup_mod=setup))

    def test_an_empty_install_names_them_all(self):
        self.assertEqual(sorted(setup.SKILLS),
                         sorted(enroll.missing_installed_skills(self.root, setup_mod=setup)))


if __name__ == "__main__":
    unittest.main()
