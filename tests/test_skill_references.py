"""설치본에 `references/` 가 없으면 SKILL.md 의 조회 표는 죽은 포인터다.

SKILL.md 는 규칙만 담고 조회는 `references/` 로 넘긴다 — "세션이 열지도 않을 참조
자료의 값을 내지 않게" 하려는 설계다. 그래서 SKILL.md 안에 조회 표가 있고 5개 파일을
가리킨다.

그런데 에이전트가 읽는 것은 레포가 아니라 **설치본**(`~/.claude/skills/vibe-harness/`)
이고, 그 설치본에는 `references/` 디렉토리가 아예 없었다. 포인터 5개가 전부 죽어 있었다.

## 왜 갈렸나

설치 경로가 둘인데 규칙이 다르다.

    setup.py              copytree  → 디렉토리 통째로, references 포함
    enroll --update-skill 화이트리스트 → 개별 파일만, references 없음

화이트리스트는 이유가 있다 — 설치본에는 `sync.json`·`projects.json` 같은 머신 로컬
상태가 함께 살아서, 통째로 덮으면 그게 날아간다. 다만 `references/` 는 순수 레포
문서라 로컬 대응물이 없다. 보호할 것이 없는데 같이 빠졌다.

## 이미 있던 테스트가 왜 못 잡았나

`test_skills.py::test_referenced_support_files_exist` 가 SKILL.md 의 포인터를 뽑아
검사하는데, **레포에** 있는지만 본다. 레포에는 다 있으니 통과한다. 설치 계획은 아무도
대조하지 않았다.

`--update-skill` 은 "10개 파일 반영" 을 성공으로 보고한다. 무엇을 빠뜨렸는지는 말하지
않는다 — 검사는 돌았는데 그 검사가 애초에 보지 않는 자리다.

## 여기서 고정하는 것

포인터 목록을 손으로 두 번 적지 않는다. **SKILL.md 가 정본이고** 설치 계획이 그것을
따라야 한다 — 그래야 새 참조 문서를 추가할 때 화이트리스트를 잊어도 CI 가 잡는다.
"""
import importlib.util
import os
import re
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SKILL_MD = os.path.join(ROOT, "skills", "vibe-harness", "SKILL.md")

# SKILL.md 가 `references/x.md` 꼴로 가리키는 것들. test_skills.py 와 같은 모양이다.
POINTER_RE = re.compile(r"`(references/[A-Za-z0-9_./-]+)`")


def load_enroll():
    """enroll 을 모듈로 읽는다. import 부작용 없이 함수만 본다."""
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    spec = importlib.util.spec_from_file_location(
        "vh_enroll_refs", os.path.join(SCRIPTS, "enroll.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def declared_pointers():
    with open(SKILL_MD, encoding="utf-8") as fh:
        return sorted(set(POINTER_RE.findall(fh.read())))


class DeclaredPointersTest(unittest.TestCase):
    def test_skill_md_actually_declares_references(self):
        """이 테스트 파일의 전제 — SKILL.md 에 조회 표가 있다."""
        self.assertTrue(declared_pointers(),
                        "SKILL.md 에 references 포인터가 없다 — 나머지 검사가 무의미하다")


class InstallPlanCoversPointersTest(unittest.TestCase):
    """SKILL.md 가 가리키는 것은 설치 계획에 전부 있어야 한다."""

    def setUp(self):
        self.enroll = load_enroll()

    def planned_names(self, dest):
        return {os.path.relpath(target, dest).replace(os.sep, "/")
                for _src, target in self.enroll.skill_install_plan(ROOT, dest)}

    def test_every_pointer_is_installed(self):
        """여기가 실제로 터진 지점 — 5개가 계획에 없었다."""
        with tempfile.TemporaryDirectory() as dest:
            planned = self.planned_names(dest)

        missing = [p for p in declared_pointers() if p not in planned]
        self.assertEqual([], missing,
                         "SKILL.md 가 가리키는데 설치되지 않는다: %s" % missing)

    def test_pointers_keep_their_subdirectory(self):
        """`references/api.md` 는 설치본에서도 references/ 아래여야 한다.

        파일명만 평평하게 복사하면 SKILL.md 의 경로와 어긋나 여전히 못 찾는다.
        """
        with tempfile.TemporaryDirectory() as dest:
            planned = self.planned_names(dest)

        for p in declared_pointers():
            self.assertIn(p, planned, "%s 가 경로 그대로 계획에 없다" % p)

    def test_sources_exist(self):
        """계획이 가리키는 원본이 실재해야 한다 — 없는 것을 계획하면 조용히 건너뛴다."""
        with tempfile.TemporaryDirectory() as dest:
            for src, _target in self.enroll.skill_install_plan(ROOT, dest):
                self.assertTrue(os.path.exists(src), "원본 없음: %s" % src)


class InstallCreatesReferencesTest(unittest.TestCase):
    """계획에 있는 것과 실제로 복사되는 것은 다른 문제다."""

    def setUp(self):
        self.enroll = load_enroll()
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "vibe-harness")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reference_files_land_in_the_install(self):
        self.enroll.install_skill_files(ROOT, self.dest)

        for p in declared_pointers():
            self.assertTrue(os.path.exists(os.path.join(self.dest, p)),
                            "설치본에 %s 가 없다" % p)

    def test_reference_content_matches_the_repo(self):
        """빈 파일을 만들어 두고 통과시키는 것을 막는다."""
        self.enroll.install_skill_files(ROOT, self.dest)

        rel = "references/task-schema.md"
        with open(os.path.join(ROOT, "skills", "vibe-harness", rel), encoding="utf-8") as fh:
            want = fh.read()
        with open(os.path.join(self.dest, rel), encoding="utf-8") as fh:
            self.assertEqual(want, fh.read())

    def test_machine_local_state_survives(self):
        """references 를 넣느라 통째 복사로 되돌리면 로컬 상태가 날아간다."""
        os.makedirs(self.dest, exist_ok=True)
        local = os.path.join(self.dest, "sync.json")
        with open(local, "w", encoding="utf-8") as fh:
            fh.write('{"runs_token": "지켜져야 한다"}')

        self.enroll.install_skill_files(ROOT, self.dest)

        with open(local, encoding="utf-8") as fh:
            self.assertIn("지켜져야 한다", fh.read())

    def test_rerun_is_idempotent(self):
        first = self.enroll.install_skill_files(ROOT, self.dest)
        second = self.enroll.install_skill_files(ROOT, self.dest)

        self.assertEqual(sorted(first), sorted(second))


class MissingReferenceIsReportedTest(unittest.TestCase):
    """레포가 맞아도 설치본이 어긋날 수 있다 — 그때 조용하면 안 된다.

    화이트리스트를 고쳐도 이미 설치된 머신은 그대로다. 누가 파일을 지울 수도 있다.
    "10개 반영" 만 말하고 끝나면 그 상태를 알 방법이 없다 — 내가 실제로 그렇게 몰랐다.
    """

    def setUp(self):
        self.enroll = load_enroll()
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "vibe-harness")

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_missing_after_a_full_install(self):
        self.enroll.install_skill_files(ROOT, self.dest)

        self.assertEqual([], self.enroll.missing_installed_references(ROOT, self.dest))

    def test_a_deleted_reference_is_named(self):
        self.enroll.install_skill_files(ROOT, self.dest)
        os.unlink(os.path.join(self.dest, "references", "api.md"))

        self.assertEqual(["references/api.md"],
                         self.enroll.missing_installed_references(ROOT, self.dest))

    def test_an_empty_install_names_all_of_them(self):
        self.assertEqual(declared_pointers(),
                         self.enroll.missing_installed_references(ROOT, self.dest))


if __name__ == "__main__":
    unittest.main()
