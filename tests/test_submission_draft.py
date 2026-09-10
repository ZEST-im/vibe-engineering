"""제출 문안이 존재하지 않는 제품을 설명하지 않는가.

`private/MARKETPLACE_SUBMISSION.md` 는 이렇게 적혀 있었다:

> You're working on 3 projects this week. **Each has its own SQLite DB**, …

SQLite → JSON 전환은 2026-03 이다. **이 프로젝트가 바이너리를 git 에 두지 않기로 한
바로 그 결정**이고, `.coverage` 사고(PMF10 #76)의 근거로 다시 인용한 결정이다.
제출 문안은 그 전 제품을 설명하고 있었다.

같은 문서에 `Python 3.6+` 과 `No data leaves your machine` 도 있었다. 셋 다
**예전에는 맞았던 문장**이다 — 거짓말을 쓴 것이 아니라 문안이 낡았다. 그래서 검사가
없으면 또 이렇게 된다.

## 이 파일의 한계를 먼저 적는다

`private/` 은 **git 이 추적하지 않고 CI 에 존재하지 않는다.** 그래서 이 검사는
로컬에서만 돈다. `test_public_hygiene.py` 가 `private/DENY.txt` 를 다루는 방식과 같다 —
있을 때만 검사한다.

**그 사실을 skip 메시지로 말한다.** 조용히 건너뛰면 "못 본 것"과 "깨끗한 것"이
구별되지 않는다 — 위생 게이트가 바이너리를 조용히 건너뛰던 것과 같은 형태다.

그리고 같은 거짓 주장 중 **공개 파일에도 있던 것**(`Python 3.6+` 은 README 에도
있었다)은 여기가 아니라 `tests/test_installer_footprint.py` 가 CI 에서 잡는다.
로컬 전용 검사에만 맡기지 않는다.
"""
import importlib.util
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
DRAFT = os.path.join(ROOT, "private", "MARKETPLACE_SUBMISSION.md")

# 폐기된 어휘. 이 단어가 **현재 제품 설명으로** 쓰이면 없는 제품을 설명하는 것이다.
# 대조 기록에서 "예전에 이렇게 적혀 있었다"고 인용하는 것은 정상이라, 인용 표시가
# 있는 줄은 제외한다 — 규칙을 넓게 잡으면 고칠 수 없는 위반이 남고 목록이 무시된다.
RETIRED = ("SQLite", "kanban.db", "db_path")


def draft_text():
    with open(DRAFT, encoding="utf-8") as fh:
        return fh.read()


@unittest.skipUnless(
    os.path.exists(DRAFT),
    "private/MARKETPLACE_SUBMISSION.md 가 없다 — CI 에는 private/ 가 존재하지 않으므로 "
    "이 검사는 로컬 전용이다. **건너뛴 것과 통과한 것은 다르다.**")
class SubmissionDraftIsCurrentTest(unittest.TestCase):
    """제출 문안의 기계적으로 확인 가능한 주장만 본다. 문체는 대상이 아니다."""

    def setUp(self):
        self.text = draft_text()

    def prose_lines(self):
        """인용·표 행을 뺀 본문. 대조 기록이 옛 문장을 인용하는 것은 위반이 아니다."""
        out = []
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("|", ">")):
                continue
            out.append(line)
        return out

    def test_the_draft_was_actually_read(self):
        """빈 파일이면 아래 검사가 전부 조용히 통과한다."""
        self.assertGreater(len(self.text), 1000, "제출 문안이 비었거나 잘렸다")
        self.assertIn("Description", self.text, "제출 문안의 형식이 바뀌었다")

    def test_retired_storage_vocabulary_is_not_used_as_current(self):
        problems = []
        for line in self.prose_lines():
            for word in RETIRED:
                if word in line:
                    problems.append("%s: %s" % (word, line.strip()[:70]))
        self.assertEqual(
            [], problems,
            "제출 문안이 폐기된 저장 방식을 현재형으로 설명한다: " + "; ".join(problems)
            + " — 2026-03 에 JSON 으로 바꿨다")

    def test_privacy_claim_is_not_absolute(self):
        """옵션 기능이 전송한다. **공개 리스팅의 프라이버시 주장은 정확해야 한다.**"""
        for absolute in ("No data leaves your machine",
                         "no data leaves your machine",
                         "Nothing ever leaves"):
            for line in self.prose_lines():
                self.assertNotIn(
                    absolute, line,
                    "프라이버시 주장이 절대적이다 — 토큰 수집을 켜면 전송된다. "
                    "PRIVACY.md 는 정확한데 제출 문안만 어긋나면 리스팅이 거짓이 된다")

    def test_privacy_section_points_at_the_policy(self):
        self.assertIn("PRIVACY.md", self.text,
                      "프라이버시 정책을 가리키지 않는다 — 리스팅 심사가 찾는 자리다")

    def test_stated_python_matches_ci(self):
        """버전을 여기 적지 않는다. 워크플로에서 읽는다."""
        spec = importlib.util.spec_from_file_location(
            "check_submission", os.path.join(SCRIPTS, "check.py"))
        check = importlib.util.module_from_spec(spec)
        sys.modules["check_submission"] = check
        self.addCleanup(sys.modules.pop, "check_submission", None)
        spec.loader.exec_module(check)
        versions, _runners = check.ci_environment()
        self.assertTrue(versions, "CI 매트릭스를 읽지 못했다")
        lowest = min(versions, key=lambda v: [int(x) for x in v.split(".")])
        self.assertIn(
            "Python " + lowest, self.text,
            "제출 문안이 검증되는 가장 낮은 파이썬(%s)을 말하지 않는다" % lowest)

    def test_shipped_features_are_listed(self):
        """직전 두 Phase 의 주력 기능이 리스팅에서 빠져 있었다.

        `plugin.json` 의 description 에는 있는데 제출 문안에는 없었다 — 두 곳에
        적으면 갈라진다는 이 레포의 상습적 실패다. **`plugin.json` 을 정본으로 삼아
        대조한다.**
        """
        import json
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        described = manifest["description"].lower()
        lowered = self.text.lower()
        # description 이 파는 것으로 내세운 것들. 이름을 여기 적지 않고 뽑아낸다.
        claimed = [term for term in ("kanban", "phase management", "scope guard",
                                     "decision log", "token") if term in described]
        self.assertGreaterEqual(len(claimed), 4, "plugin.json description 형식이 바뀌었다")
        missing = [term for term in claimed if term.split()[0] not in lowered]
        self.assertEqual(
            [], missing,
            "plugin.json 이 내세우는데 제출 문안이 말하지 않는 기능: " + ", ".join(missing))


if __name__ == "__main__":
    unittest.main()
