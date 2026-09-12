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
                             capture_output=True, text=True, encoding="utf-8")
        return out.returncode == 0

    def test_ci_measures_coverage_with_a_floor(self):
        """커버리지는 CI 에만 있어서, 지워져도 로컬에서는 아무 일도 안 일어난다.

        3주 연속 지적이었던 항목이라 다시 조용히 사라지지 않게 여기서 묶는다.
        측정만 하고 문턱이 없으면 그건 문서지 검사가 아니므로 `--fail-under` 까지 본다.
        """
        path = os.path.join(ROOT, ".github", "workflows", "tests.yml")
        if not os.path.exists(path):
            self.skipTest("워크플로 없음")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("coverage run --source=scripts", body,
                      "CI 가 커버리지를 재지 않는다")
        self.assertIn("--fail-under=", body,
                      "커버리지를 재기만 하고 문턱이 없다 — 내려가도 아무도 모른다")
        self.assertIn("coverage==", body,
                      "버전을 고정하지 않으면 도구가 바뀔 때 숫자가 흔들린다")

    # 래칫의 실측값. **"정리"랍시고 지우거나 워크플로 값만 보고 계산하지 말 것** —
    # 문턱을 올릴 때는 이 상수도 같이 올려야 한다. 그 이중 기록이 결함이 아니라
    # 래칫 그 자체다: 한쪽만 고치면(워크플로만 내리고 여기를 그대로 두면) 이 테스트가
    # 잡고, 양쪽을 같이 고치면 리뷰에 그 변경이 보인다. 지금 값 55 는
    # `.github/workflows/tests.yml` 의 `--fail-under=55` 와 나란히 움직인다.
    KNOWN_COVERAGE_FLOOR = 55

    def test_coverage_floor_never_decreases(self):
        """CONTRIBUTING.md 가 "커버리지 문턱은 오직 올라가기만 한다"고 적은 것의 실행판.

        전에는 이 규칙이 워크플로 주석과 CONTRIBUTING.md 산문에만 있었다 — 둘 다 사람이
        읽어야 막히는 문서였고, `--fail-under=` 를 40 으로 낮춰도 어떤 자동 검사도
        걸리지 않았다(`test_ci_measures_coverage_with_a_floor` 는 문턱이 "있는지"만
        보지 "내려갔는지"는 보지 않는다). 여기서는 그 값을 이 파일에 박아둔 하한과
        비교해 내려갔으면 실패시킨다.
        """
        path = os.path.join(ROOT, ".github", "workflows", "tests.yml")
        if not os.path.exists(path):
            self.skipTest("워크플로 없음")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        match = re.search(r"--fail-under=(\d+)", body)
        self.assertIsNotNone(match, "커버리지 문턱을 찾지 못했다")
        floor = int(match.group(1))
        self.assertGreaterEqual(
            floor, self.KNOWN_COVERAGE_FLOOR,
            "커버리지 문턱이 %d 에서 %d 로 내려갔다 — 이 레포는 래칫만 허용한다"
            "(한 번 올리면 다시 안 내린다, 그래야 하한 조정이 의미가 있다). "
            "실측이 정말 %d 아래로 떨어졌다면 문턱이 아니라 커버리지를 고치고, "
            "하한을 다시 올릴 때는 이 파일의 KNOWN_COVERAGE_FLOOR 도 같이 올려라."
            % (self.KNOWN_COVERAGE_FLOOR, floor, self.KNOWN_COVERAGE_FLOOR))

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
