"""스킬 파일 자체를 검증한다.

이 레포의 제품은 skills/*/SKILL.md 다. 설치 배선만 테스트하면 파일에 무엇이
적혀 있든 통과하므로, 내용의 불변식을 여기서 고정한다.
"""
import os
import re
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(ROOT, "skills")

SKILL_NAME_RE = re.compile(r"`(vibe-[a-z]+)`")


def skill_dirs():
    return sorted(
        d for d in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, d))
    )


def read_skill(name):
    with open(os.path.join(SKILLS_DIR, name, "SKILL.md"), encoding="utf-8") as fh:
        return fh.read()


def frontmatter(text):
    """SKILL.md 선두의 --- 블록을 key: value 로 파싱한다."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    out = {}
    for line in text[4:end].split("\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


class SkillFrontmatterTest(unittest.TestCase):
    def test_every_skill_dir_has_skill_md(self):
        for name in skill_dirs():
            path = os.path.join(SKILLS_DIR, name, "SKILL.md")
            self.assertTrue(os.path.exists(path), name + "/SKILL.md 없음")

    def test_frontmatter_name_matches_directory(self):
        for name in skill_dirs():
            fm = frontmatter(read_skill(name))
            self.assertEqual(name, fm.get("name"),
                             name + ": frontmatter name 이 디렉토리명과 다름")

    def test_frontmatter_has_description(self):
        for name in skill_dirs():
            fm = frontmatter(read_skill(name))
            desc = fm.get("description", "")
            # description 은 모델이 스킬을 고르는 유일한 단서다
            self.assertGreaterEqual(len(desc), 40, name + ": description 이 너무 짧음")

    def test_frontmatter_declares_user_invocable(self):
        for name in skill_dirs():
            fm = frontmatter(read_skill(name))
            self.assertEqual("true", fm.get("user-invocable"),
                             name + ": user-invocable 선언 없음")


class SkillCrossReferenceTest(unittest.TestCase):
    def test_referenced_skills_exist(self):
        """`vibe-xxx` 로 언급한 스킬이 실재해야 한다."""
        existing = set(skill_dirs())
        for name in skill_dirs():
            for ref in set(SKILL_NAME_RE.findall(read_skill(name))):
                if ref.startswith("vibe-") and ref != "vibe-engineering":
                    self.assertIn(ref, existing,
                                  name + " 가 없는 스킬 " + ref + " 를 참조함")

    def test_referenced_support_files_exist(self):
        """SKILL.md 가 가리키는 부속 파일이 실재해야 한다."""
        ref_re = re.compile(r"`(references/[A-Za-z0-9_./-]+)`")
        for name in skill_dirs():
            for rel in set(ref_re.findall(read_skill(name))):
                path = os.path.join(SKILLS_DIR, name, rel)
                self.assertTrue(os.path.exists(path),
                                name + " 가 없는 파일 " + rel + " 을 참조함")

    def test_skills_are_documented_in_readme(self):
        """스킬을 추가하고 README 갱신을 잊는 것을 막는다."""
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        for name in skill_dirs():
            self.assertIn("/" + name, readme, name + " 이 README 에 없음")


class RepoShipsWhatItClaimsTest(unittest.TestCase):
    """레포에 있다고 보고한 것이 실제로 커밋에 들어갔는지 본다.

    CI 워크플로를 추가했는데 .gitignore 의 `.github/` 에 걸려 푸시되지 않은 적이 있다.
    로컬에는 있고 원격에는 없으니 로컬 테스트로는 영원히 잡히지 않는 종류다.
    """

    def _tracked(self, path):
        import subprocess
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "--error-unmatch", path],
                             capture_output=True, text=True)
        return out.returncode == 0

    def test_ci_workflow_is_tracked_by_git(self):
        workflow_dir = os.path.join(ROOT, ".github", "workflows")
        if not os.path.isdir(workflow_dir):
            self.skipTest("워크플로 디렉토리 없음")
        files = [f for f in os.listdir(workflow_dir) if f.endswith((".yml", ".yaml"))]
        self.assertTrue(files, ".github/workflows 에 워크플로가 없음")
        for name in files:
            rel = ".github/workflows/" + name
            self.assertTrue(self._tracked(rel),
                            rel + " 이 git 추적 대상이 아님 — .gitignore 확인")

    def test_installed_scripts_are_tracked(self):
        """setup.py 가 배포하는 파일이 레포에 실제로 있어야 원격 설치가 성립한다."""
        for name in ("server.py", "vibe_runtime.py", "worker.py", "kanban.html", "setup.py"):
            self.assertTrue(self._tracked("scripts/" + name),
                            "scripts/" + name + " 이 git 추적 대상이 아님")


class SkillInstallContractTest(unittest.TestCase):
    def test_setup_declares_every_skill_dir(self):
        """skills/ 에 디렉토리를 만들고 setup.py 등록을 잊으면 설치가 안 된다."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "vibe_setup_contract", os.path.join(ROOT, "scripts", "setup.py"))
        setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)

        for name in skill_dirs():
            self.assertIn(name, setup.SKILLS, name + " 이 setup.SKILLS 에 없음")


if __name__ == "__main__":
    unittest.main()
