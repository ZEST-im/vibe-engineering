import importlib.util
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

spec = importlib.util.spec_from_file_location("vibe_setup", os.path.join(SCRIPTS, "setup.py"))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class CopySkillFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skills_root = os.path.join(self.tmp.name, "skills-dest")
        self.repo_skills = os.path.join(self.tmp.name, "repo", "skills")
        self.scripts_dir = os.path.join(self.tmp.name, "repo", "scripts")
        os.makedirs(self.scripts_dir)
        # 픽스처는 선언된 스킬 목록에서 파생한다 — 스킬이 늘어도 테스트가 따라온다
        for name in setup.SKILLS:
            d = os.path.join(self.repo_skills, name)
            os.makedirs(d)
            with open(os.path.join(d, "SKILL.md"), "w") as fh:
                fh.write("# " + name + "\n")

        self.orig_root = setup.SKILLS_ROOT
        self.orig_src = setup.SRC
        setup.SKILLS_ROOT = self.skills_root
        setup.SRC = self.scripts_dir

    def tearDown(self):
        setup.SKILLS_ROOT = self.orig_root
        setup.SRC = self.orig_src
        self.tmp.cleanup()

    def test_installs_every_declared_skill(self):
        setup.copy_skill_files()

        for name in setup.SKILLS:
            path = os.path.join(self.skills_root, name, "SKILL.md")
            self.assertTrue(os.path.exists(path), name + " not installed")

    def test_every_declared_skill_exists_in_repo(self):
        """SKILLS 에 있는데 skills/ 에 없으면 설치가 조용히 건너뛴다."""
        for name in setup.SKILLS:
            path = os.path.join(ROOT, "skills", name, "SKILL.md")
            self.assertTrue(os.path.exists(path), "skills/" + name + "/SKILL.md 없음")

    def test_copies_supporting_files_not_just_skill_md(self):
        """스킬이 references/ 같은 부속 파일을 가질 수 있어야 한다."""
        ref_dir = os.path.join(self.repo_skills, "vibe-design", "references")
        os.makedirs(ref_dir)
        with open(os.path.join(ref_dir, "design-systems.md"), "w") as fh:
            fh.write("# catalog\n")

        setup.copy_skill_files()

        self.assertTrue(os.path.exists(
            os.path.join(self.skills_root, "vibe-design", "references", "design-systems.md")))

    def test_removes_support_files_deleted_from_repo(self):
        """레포에서 지운 부속 파일이 설치본에 남으면 안 된다.

        스킬이 참조하지 않는 낡은 문서가 설치본에만 남아 있으면, 사용자는
        레포에 없는 지침을 따르게 된다.
        """
        ref_dir = os.path.join(self.repo_skills, "vibe-design", "references")
        os.makedirs(ref_dir)
        with open(os.path.join(ref_dir, "old.md"), "w") as fh:
            fh.write("stale")
        setup.copy_skill_files()
        installed_old = os.path.join(self.skills_root, "vibe-design", "references", "old.md")
        self.assertTrue(os.path.exists(installed_old))

        os.remove(os.path.join(ref_dir, "old.md"))
        setup.copy_skill_files()

        self.assertFalse(os.path.exists(installed_old), "지운 파일이 설치본에 남음")

    def test_does_not_copy_pycache_or_backups(self):
        d = os.path.join(self.repo_skills, "vibe-design", "__pycache__")
        os.makedirs(d)
        with open(os.path.join(d, "junk.pyc"), "w") as fh:
            fh.write("x")
        with open(os.path.join(self.repo_skills, "vibe-design", "SKILL.md.bak"), "w") as fh:
            fh.write("old")

        setup.copy_skill_files()

        dest = os.path.join(self.skills_root, "vibe-design")
        self.assertFalse(os.path.exists(os.path.join(dest, "__pycache__")))
        self.assertFalse(os.path.exists(os.path.join(dest, "SKILL.md.bak")))

    def test_review_skill_is_installed(self):
        setup.copy_skill_files()

        self.assertIn("vibe-review", setup.SKILLS)
        self.assertTrue(os.path.exists(os.path.join(self.skills_root, "vibe-review", "SKILL.md")))

    def test_skips_skill_missing_from_repo(self):
        os.remove(os.path.join(self.repo_skills, "vibe-design", "SKILL.md"))

        setup.copy_skill_files()

        self.assertFalse(os.path.exists(os.path.join(self.skills_root, "vibe-design", "SKILL.md")))
        self.assertTrue(os.path.exists(os.path.join(self.skills_root, "vibe-planning", "SKILL.md")))

    def test_uninstall_keeps_vibe_harness_dir(self):
        setup.copy_skill_files()
        with open(os.path.join(self.skills_root, "vibe-harness", "projects.json"), "w") as fh:
            fh.write("{}")

        setup.remove_added_skills()

        self.assertTrue(os.path.exists(os.path.join(self.skills_root, "vibe-harness", "projects.json")))
        self.assertFalse(os.path.exists(os.path.join(self.skills_root, "vibe-planning")))
        self.assertFalse(os.path.exists(os.path.join(self.skills_root, "vibe-design")))


if __name__ == "__main__":
    unittest.main()


class UpgradeFileListTest(unittest.TestCase):
    """`setup.py upgrade` 와 `enroll.py --update-skill` 이 같은 파일을 덮어야 한다.

    두 목록이 갈라져 reconcile_runs.py 가 upgrade 경로에서 빠져 있었다. README 가
    안내하는 한 줄 업데이트만 돌린 머신은 단가표 수정이 반영되지 않은 채 남는다.
    """

    def test_upgrade_covers_every_file_enroll_installs(self):
        import re
        root = os.path.join(os.path.dirname(__file__), "..")
        enroll_src = open(os.path.join(root, "scripts", "enroll.py"), encoding="utf-8").read()
        setup_src = open(os.path.join(root, "scripts", "setup.py"), encoding="utf-8").read()

        block = re.search(r"SKILL_CODE_FILES = \((.*?)\)\n", enroll_src, re.S).group(1)
        installed = set(re.findall(r'"([\w.]+\.(?:py|html|md))"\s*\)', block))

        missing = {n for n in installed if n != "SKILL.md" and f'"{n}"' not in setup_src}
        self.assertEqual(set(), missing, f"setup.py upgrade 가 빠뜨린 파일: {missing}")
