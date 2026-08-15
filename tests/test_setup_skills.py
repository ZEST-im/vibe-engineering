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
        for name in ("vibe-harness", "vibe-planning", "vibe-design"):
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
