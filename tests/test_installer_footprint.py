"""설치가 이 머신에 무엇을 하는지, README 가 정확히 말하는가.

README 의 Setup 절은 이렇게 적혀 있었다:

> 3. Registers **a code review hook** in `~/.claude/settings.json`

실제로 `setup.py` 는 훅 **5개**를 등록하고 헬퍼 **2개**를 `~/.claude/hooks/` 에 복사한다.
그중 하나(`vibe-harness-scope-guard`)는 `PreToolUse` 에서 **편집을 막을 수 있다.**
그리고 복사되는 런타임 파일 10개 중 3개(`kanban_edit.py`·`search.py`·`review_sync.py`)는
README 에 한 번도 등장하지 않았다 — `search.py` 는 직전 Phase 의 주력 기능이다.

**남의 설정 파일에 무엇을 쓰는지 축소해서 말하는 것은 오타가 아니라 신뢰 문제다.**
설치하는 사람이 동의한 것보다 많이 쓴다.

## 왜 개수를 세지 않고 이름을 대조하는가

README 에 "다섯 개"라고 적고 그 숫자를 검사하면, 훅이 여섯 개가 될 때 숫자만 고치고
목록은 그대로 둘 수 있다. 그래서 **`setup.py` 의 정본 목록에서 이름을 뽑아** 하나씩
문서에 있는지 본다 — 훅이 늘면 README 가 그것을 말할 때까지 이 검사가 실패한다.

정본은 `setup.py` 다. 여기에 파일명·훅 이름을 다시 적지 않는다. 적으면 갈라진다.
"""
import importlib.util
import os
import re
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")


def load_setup():
    sys.path.insert(0, SCRIPTS)
    spec = importlib.util.spec_from_file_location("setup_footprint",
                                                  os.path.join(SCRIPTS, "setup.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["setup_footprint"] = mod
    spec.loader.exec_module(mod)
    return mod


def readme():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        return fh.read()


def section(title, text=None):
    """`## title` 부터 다음 같은 깊이 제목까지. 절 안에서만 확인해야 하는 주장이 있다.

    Uninstall 절이 그 예다 — "vibe-harness 디렉토리는 남는다"가 파일 어딘가에 적혀
    있는 것으로는 부족하다. 제거를 실행하려는 사람이 읽는 자리에 있어야 한다.
    """
    text = readme() if text is None else text
    m = re.search(r"^(#{2,3})\s*" + re.escape(title) + r"\s*$", text, re.M)
    if not m:
        return ""
    depth = len(m.group(1))
    rest = text[m.end():]
    nxt = re.search(r"^#{1,%d}\s" % depth, rest, re.M)
    return rest[:nxt.start()] if nxt else rest


class HooksAreDisclosedTest(unittest.TestCase):
    """등록되는 훅을 하나도 빠뜨리지 않고 말하는가."""

    def setUp(self):
        self.setup = load_setup()
        self.text = readme()

    def test_every_hook_id_is_documented(self):
        missing = sorted(i for i in self.setup.HOOK_IDS if i not in self.text)
        self.assertEqual(
            [], missing,
            "설치되는데 README 가 말하지 않는 훅: " + ", ".join(missing)
            + " — 사용자의 settings.json 에 동의한 것보다 많이 쓴다")

    def test_every_hook_event_is_documented(self):
        events = sorted({event for _src, event, _entry in self.setup.HOOKS})
        missing = [e for e in events if e not in self.text]
        self.assertEqual(
            [], missing,
            "README 가 말하지 않는 훅 이벤트: " + ", ".join(missing)
            + " — 어느 시점에 끼어드는지가 사용자에게 가장 중요하다")

    def test_every_hook_helper_is_documented(self):
        missing = [h for h in self.setup.HOOK_HELPERS if h not in self.text]
        self.assertEqual(
            [], missing,
            "~/.claude/hooks/ 에 복사되는데 README 가 말하지 않는 헬퍼: " + ", ".join(missing))

    def test_blocking_hook_is_marked_as_blocking(self):
        """막을 수 있는 훅과 알리기만 하는 훅은 사용자에게 완전히 다른 이야기다.

        `vibe-harness-scope-guard` 는 `PreToolUse` 에서 exit 1 로 편집을 거부한다.
        나머지 넷은 알리기만 한다. 그 차이를 README 가 말하지 않으면, 설치한 사람은
        자기 편집이 왜 거부되는지 알 방법이 없다.
        """
        setup_section = section("2. Setup")
        self.assertIn("vibe-harness-scope-guard", setup_section,
                      "Setup 절이 스코프 가드를 말하지 않는다")
        row = [ln for ln in setup_section.splitlines() if "vibe-harness-scope-guard" in ln]
        self.assertTrue(row, "스코프 가드 설명 줄을 찾지 못했다")
        self.assertRegex(
            row[0], r"[Bb]lock",
            "스코프 가드가 **편집을 막을 수 있다**는 것을 README 가 말하지 않는다 — "
            "막는 훅과 알리는 훅은 사용자에게 다른 이야기다")

    def test_hook_count_claim_matches_reality(self):
        """개수를 적었다면 그 개수도 맞아야 한다. 'a code review hook' 이 이 검사의 계기다."""
        spelled = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
                   6: "six", 7: "seven", 8: "eight"}
        actual = len(self.setup.HOOKS)
        claim = re.search(r"[Rr]egisters\s+(\w+)\s+hooks?\b", self.text)
        self.assertIsNotNone(claim, "README 가 훅을 몇 개 등록하는지 말하지 않는다")
        self.assertEqual(
            spelled.get(actual, str(actual)), claim.group(1).lower(),
            "README 는 훅을 %s 개 등록한다고 하는데 실제로는 %d 개다"
            % (claim.group(1), actual))


class InstalledFilesAreDisclosedTest(unittest.TestCase):
    """무엇이 어디에 복사되는지 말하는가."""

    def setUp(self):
        self.setup = load_setup()
        self.text = readme()

    def test_every_runtime_file_is_documented(self):
        missing = [f for f in self.setup.SKILL_RUNTIME_FILES if f not in self.text]
        self.assertEqual(
            [], missing,
            "설치되는데 README 가 말하지 않는 런타임 파일: " + ", ".join(missing))

    def test_every_installed_skill_is_documented(self):
        missing = [s for s in self.setup.SKILLS if s not in self.text]
        self.assertEqual([], missing,
                         "설치되는데 README 가 말하지 않는 스킬: " + ", ".join(missing))

    def test_written_locations_are_documented(self):
        """어디에 쓰는지 — 이것이 "내 머신에 무엇을 하는가"의 답이다."""
        for target in ("~/.claude/settings.json", "~/.claude/hooks/", "~/.claude/skills/"):
            self.assertIn(target, self.text,
                          "README 가 %s 에 쓴다는 것을 말하지 않는다" % target)

    def test_autostart_label_is_documented(self):
        """라벨을 알아야 사용자가 `launchctl list` 로 직접 확인하고 멈출 수 있다."""
        label = self.setup.PLIST_NAME[:-len(".plist")]
        self.assertIn(label, self.text,
                      "자동시작 에이전트 라벨(%s)이 README 에 없다" % label)


class UninstallIsHonestTest(unittest.TestCase):
    """제거가 무엇을 남기는지 말하는가.

    "uninstall 하면 다 지워진다"는 **거짓이다** — `~/.claude/skills/vibe-harness/` 는
    `projects.json` 과 서버 로그가 살아 있어서 의도적으로 남긴다. 그 사실을 제거를
    실행하려는 사람이 읽는 자리에 적어야 한다.
    """

    def setUp(self):
        self.setup = load_setup()
        self.section = section("Uninstall")

    def test_uninstall_section_exists(self):
        self.assertTrue(self.section.strip(), "Uninstall 절을 찾지 못했다")

    def test_removable_skills_are_named(self):
        missing = [s for s in self.setup.REMOVABLE_SKILLS if s not in self.section]
        self.assertEqual([], missing,
                         "제거되는데 Uninstall 절이 말하지 않는 스킬: " + ", ".join(missing))

    def test_retained_directory_is_named(self):
        self.assertIn(
            "~/.claude/skills/vibe-harness/", self.section,
            "제거해도 남는 디렉토리를 Uninstall 절이 말하지 않는다 — "
            "다 지워진다고 믿게 만든다")

    def test_retention_reason_is_given(self):
        """남기는 이유가 없으면 버그로 읽히고, 버그로 읽히면 누군가 '고친다'."""
        self.assertRegex(
            self.section, r"projects\.json",
            "남기는 이유(projects.json 이 거기 있다)를 말하지 않는다")

    def test_project_data_is_declared_untouched(self):
        """프로젝트별 데이터는 사용자의 기록이고 사용자의 레포에 있다. 건드리지 않는다."""
        self.assertRegex(
            self.section, r"[Pp]er-project|never touched|프로젝트별",
            "프로젝트별 vibe-harness/ 데이터가 그대로 남는다는 것을 말하지 않는다")


class StatedRequirementsMatchCITest(unittest.TestCase):
    """README 가 요구한다고 적은 파이썬 버전이 **실제로 검증되는 버전인가.**

    README 는 `Python 3.6+` 이라고 적어 두고 있었다. 그런데 코드는 3.6 에서 아예 돌지
    않는다 — `shutil.copytree(dirs_exist_ok=…)` 는 3.8, `subprocess.run(capture_output=…)`
    와 `text=True` 는 3.7 부터다. 그리고 CI 가 도는 것은 **3.11·3.12·3.13** 뿐이다.

    즉 세 숫자가 전부 달랐다: 문서가 약속한 것(3.6), 코드가 요구하는 것(3.8),
    검증되는 것(3.11). 사용자가 신뢰하는 것은 첫 번째이고, 그것만 아무 근거가 없었다.

    **버전을 여기 적지 않는다.** 워크플로에서 읽는다 — `check.py` 가 자기 버전을 들면
    "로컬은 통과, CI 는 실패"가 되는 것과 같은 이유다. 매트릭스가 3.12 로 올라가면
    이 검사가 README 를 고칠 때까지 실패한다.
    """

    def setUp(self):
        sys.path.insert(0, SCRIPTS)
        spec = importlib.util.spec_from_file_location(
            "check_requirements", os.path.join(SCRIPTS, "check.py"))
        self.check = importlib.util.module_from_spec(spec)
        sys.modules["check_requirements"] = self.check
        spec.loader.exec_module(self.check)
        self.addCleanup(sys.modules.pop, "check_requirements", None)
        self.versions, _runners = self.check.ci_environment()

    def test_ci_matrix_was_actually_read(self):
        """못 읽으면 아래 검사가 조용히 무의미해진다."""
        self.assertTrue(self.versions, "워크플로에서 파이썬 매트릭스를 읽지 못했다")

    def test_readme_states_the_lowest_tested_version(self):
        lowest = min(self.versions, key=lambda v: [int(x) for x in v.split(".")])
        requirements = section("Requirements")
        self.assertTrue(requirements.strip(), "Requirements 절을 찾지 못했다")
        self.assertIn(
            "Python " + lowest, requirements,
            "README 는 CI 가 도는 가장 낮은 버전(%s)을 요구사항으로 적어야 한다 — "
            "그보다 낮은 숫자를 적으면 검증하지 않은 것을 약속하는 것이다" % lowest)

    def test_every_tested_version_is_named(self):
        """`3.11+` 만 적으면 어디까지 검증됐는지 알 수 없다. 상단도 말해야 한다."""
        requirements = section("Requirements")
        missing = [v for v in self.versions if v not in requirements]
        self.assertEqual(
            [], missing,
            "CI 가 도는데 README 가 말하지 않는 버전: " + ", ".join(missing))

    def test_untested_range_is_not_promised(self):
        """3.8~3.10 은 돌 것 같지만 아무것도 확인하지 않는다. 약속하지 않는다는 말이 있어야 한다."""
        requirements = section("Requirements")
        self.assertRegex(
            requirements, r"[Uu]ntested|not claimed|not verified|nothing verifies",
            "검증되지 않은 버전 범위를 어떻게 취급하는지 README 가 말하지 않는다")


if __name__ == "__main__":
    unittest.main()
