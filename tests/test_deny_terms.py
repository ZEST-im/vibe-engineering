"""금칙어를 손이 아니라 사실에서 파생시킨다 — 그 로직 검증.

## 왜 이 파일이 생겼나

2026-10-02 에 아키텍처 문서를 쓰면서 사내 프로젝트명 5종과 동료 실명 3인을 공개
레포에 적었다. **위생 게이트는 초록이었다.**

두 층 다 제 일을 했는데 샜다:

- **구조 규칙**은 모양만 본다. 10자리 숫자·내부 경로는 잡지만, 프로젝트명은
  평범한 식별자라 잡을 모양이 없다. 여기에 규칙을 넓게 잡으면 모든 문서가 걸리고
  그러면 게이트가 꺼진다
- **정확 문자열**(`private/DENY.txt`)은 목록에 있는 것만 잡는다. 17항목이 있었지만
  **등록된 프로젝트 21개가 거기 없었다**

즉 구멍은 "규칙이 없다"가 아니라 **"목록을 사람이 채운다"** 였다. 손 목록은 갈라진다 —
설치 파일 목록이 세 군데로 갈려 머신 하나가 수집기 없이 남았던 사고가 이미 있다.

## 여기서 검사하지 않는 것

**실제 레지스트리를 읽지 않는다.** 테스트가 실제 `~/.claude/` 를 건드리지 않는 것이
이 레포의 규칙이다. 그래서 읽는 쪽은 `check.py` 의 `deny-coverage` 단계가 맡고,
여기서는 픽스처로 **로직만** 검증한다.

그 분리의 대가는 분명하다 — 이 파일이 초록이어도 실제 유출은 `check.py` 를 돌려야
안다. 그 유보는 `check.py` 가 「여기서 확인하지 못한 것」에 적는다.
"""
import os
import shutil
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import deny_terms as dt  # noqa: E402


class RegistryBecomesTermsTest(unittest.TestCase):
    """등록된 프로젝트 key 가 금칙어가 된다."""

    def test_keys_become_terms(self):
        terms = dt.terms_from_registry({"acme_pipeline": {}, "beta_portal": {}})

        self.assertEqual(["acme_pipeline", "beta_portal"], terms)

    def test_this_repo_is_not_denied_in_a_real_run(self):
        """자기 이름을 금칙어로 만들면 README 부터 걸린다.

        하드코딩이 아니라 **신원 파일에서 파생**해 뺀다 — `self_identity` 가 그 일을
        하고, 여기서는 그 둘이 실제로 이어져 있는지만 본다.
        """
        public = dt.self_identity(ROOT)

        terms = dt.terms_from_registry({"vibe-engineering": {}, "acme_pipeline": {}},
                                       public)

        self.assertEqual(["acme_pipeline"], terms)

    def test_short_keys_are_refused(self):
        """`qa`·`web` 같은 key 가 들어가면 모든 문서가 걸리고 게이트가 꺼진다."""
        terms = dt.terms_from_registry({"qa": {}, "web": {}, "acme_pipeline": {}})

        self.assertEqual(["acme_pipeline"], terms)

    def test_a_broken_registry_yields_nothing(self):
        """읽을 수 없으면 빈 목록 — 터지지 않는다. 기록은 부산물이다."""
        self.assertEqual([], dt.terms_from_registry(None))
        self.assertEqual([], dt.terms_from_registry("not a dict"))


class BoardsBecomeTermsTest(unittest.TestCase):
    """보드에 적힌 사람 이름이 금칙어가 된다."""

    def test_owner_fields_become_terms(self):
        board = {"tasks": [
            {"created_by": "hong-gildong", "assigned_to": "kim-younghee"},
            {"created_by": "hong-gildong"},
        ]}

        self.assertEqual(["hong-gildong", "kim-younghee"], dt.terms_from_boards([board]))

    def test_agent_names_are_not_people(self):
        """`claude`·`codex` 는 공개 문서에 정상적으로 나오는 말이다."""
        board = {"tasks": [{"created_by": "claude", "assigned_to": "codex"}]}

        self.assertEqual([], dt.terms_from_boards([board]))

    def test_malformed_boards_are_skipped(self):
        self.assertEqual([], dt.terms_from_boards([None, "x", {}, {"tasks": None}]))

    def test_a_value_with_spaces_is_not_a_name(self):
        """설명문이 소유자 필드에 들어간 경우. 금칙어로 쓰면 오탐이 쏟아진다."""
        board = {"tasks": [{"created_by": "migrated from old board"}]}

        self.assertEqual([], dt.terms_from_boards([board]))


class ItCatchesAnInjectedLeakTest(unittest.TestCase):
    """**이 검사가 처음부터 통과하면 아무것도 증명하지 못한다.**

    그래서 실제로 샜던 모양 그대로 주입해 본다 — 공개 문서 한 줄에 사내 프로젝트명이
    들어간 상태다. 2026-10-02 에 게이트가 놓친 것이 정확히 이 모양이었다.
    """

    def setUp(self):
        self.terms = dt.terms_from_registry({"acme_pipeline": {}, "beta_portal": {}})

    def test_a_clean_file_passes(self):
        """전제 확인 — 깨끗할 때 조용해야 아래 실패가 의미를 갖는다."""
        clean = {"docs/architecture/02_data.md": [
            "| 정본 이름 | 갈라진 이름 | 쓰는 곳 |",
            "| `created_at` | `createdAt` | 프로젝트 A |",
        ]}

        self.assertEqual([], dt.offenders(self.terms, clean))

    def test_the_injected_leak_is_caught(self):
        leaked = {"docs/architecture/02_data.md": [
            "| 정본 이름 | 갈라진 이름 | 쓰는 곳 |",
            "| `created_at` | `createdAt` | acme_pipeline |",
        ]}

        hits = dt.offenders(self.terms, leaked)

        self.assertEqual(1, len(hits), "주입한 유출을 못 잡으면 이 게이트는 장식이다")
        path, line_no, term, _ = hits[0]
        self.assertEqual(("docs/architecture/02_data.md", 2, "acme_pipeline"),
                         (path, line_no, term))

    def test_public_ok_still_suppresses(self):
        """구조 규칙 층과 같은 예외 표시를 쓴다 — 두 층이 다르게 굴면 사람이 틀린다."""
        marked = {"README.md": ["acme_pipeline 는 공개 예시다  public-ok"]}

        self.assertEqual([], dt.offenders(marked and self.terms, marked))

    def test_one_line_reports_once(self):
        """한 줄에 두 금칙어가 있어도 보고는 한 번 — 같은 수정으로 닫힌다."""
        both = {"docs/x.md": ["acme_pipeline 과 beta_portal 을 비교하면"]}

        self.assertEqual(1, len(dt.offenders(self.terms, both)))


class SelfIdentityIsNotALeakTest(unittest.TestCase):
    """레포가 스스로 공개한 이름은 금칙어가 될 수 없다.

    처음엔 이 제외가 없었고 **425건**이 떴다 — 대부분 작성자 본인과 조직 이름,
    즉 LICENSE 와 plugin.json 에 이미 적혀 있는 것이었다. 그 숫자를 본 사람은
    규칙을 고치는 대신 게이트를 끈다.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        with open(os.path.join(self.root, "LICENSE"), "w", encoding="utf-8") as fh:
            fh.write("MIT - Gildong Hong (github.com/gildong)\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_name_in_license_is_public(self):
        public = dt.self_identity(self.root)

        self.assertIn("gildong", public)

    def test_a_public_name_is_not_a_term(self):
        public = dt.self_identity(self.root)

        terms = dt.terms_from_registry({"gildong": {}, "acme_pipeline": {}}, public)

        self.assertEqual(["acme_pipeline"], terms)

    def test_the_remote_url_counts_too(self):
        """조직 이름은 원격 URL 에 있다 — 그것도 공개된 것이다."""
        public = dt.self_identity(self.root, "https://github.com/AcmeOrg/thing.git")

        self.assertIn("acmeorg", public)

    def test_a_missing_identity_file_is_not_fatal(self):
        """신원 파일이 없으면 제외가 비는 것이지 터지는 것이 아니다."""
        self.assertEqual(set(), dt.self_identity("/nonexistent"))


class NothingIsSilentlySkippedTest(unittest.TestCase):
    """레지스트리를 못 읽은 것과 깨끗한 것은 다르다."""

    def test_a_missing_registry_yields_no_terms(self):
        terms = dt.derived_terms("/nonexistent/projects.json")

        self.assertEqual([], terms)

    def test_no_terms_means_the_layer_did_not_run(self):
        """금칙어가 0개면 offenders 는 영원히 빈 목록이다 — 통과가 아니라 미실행이다.

        부르는 쪽(`check.py`)이 이 둘을 구분해 보고해야 한다는 것을 여기 못박는다.
        """
        anything = {"docs/x.md": ["acme_pipeline"]}

        self.assertEqual([], dt.offenders([], anything))


if __name__ == "__main__":
    unittest.main()
