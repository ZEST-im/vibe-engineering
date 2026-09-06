"""계획 문서가 현실과 어긋난 채 남아 있는 것을 막는다.

`HARNESS_PLAN.md` 의 체크박스 12개가 넉 달간 미체크로 남아 있었다. 그 12개는 **전부 이미
구현돼 있었다** — context 엔드포인트, 스코프 가드, decisions API, velocity. 문서만 보면
안 한 일 12개가 있는 것처럼 보였다. 완료된 Phase 의 계획서 두 개(PMF03·PMF06)에서도
같은 것이 37개 더 나왔다. 합쳐서 **유령 항목 49개.**

이게 이 레포가 반복해 온 실패의 문서판이다. 어제 `Do NOT touch` 가 실제와 달라 정상화를
되돌릴 뻔했고, rename 점검 목록을 문서에 넣었더니 같은 고장이 재발했다. **문서로 대응한
것은 대응이 아니다** — 그래서 정리에 그치지 않고 검사로 만든다.

## 규칙

**완료된 Phase 의 계획 문서에 열린 체크박스가 있으면 안 된다.** 일이 끝났는데 문서가
그것을 모르는 상태이기 때문이다. 열려 있어도 되는 것은 진행 중인 Phase 의 것뿐이다.

## CI 에서는 건너뛴다

`private/` 는 gitignore 라 CI 가 볼 수 없다. 이건 로컬 위생 검사고, 없으면 skip 한다 —
`test_public_hygiene.py` 의 DENY.txt 와 같은 구조다. 없는 것을 실패로 만들면 CI 가 항상
빨개져서 아무도 안 본다.
"""
import os
import re
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIVATE = os.path.join(ROOT, "private")
PHASES = os.path.join(PRIVATE, "PHASES.md")

# 지금 진행 중인 Phase 의 계획을 담는 문서. 열린 항목이 있는 게 정상이다.
LIVE_DOCS = {"PHASES.md", "CURRENT_PHASE.md"}

OPEN_BOX = "- [ ]"
PHASE_IN_DOC = re.compile(r"PHASE_(PMF|MVP|SEED|SCALE|GTM)\d+")
DONE_PHASE = re.compile(r"^##\s+(PHASE_\w+)\s+✅", re.M)
ACTIVE_PHASE = re.compile(r"^##\s+(PHASE_\w+)\s+🚧", re.M)


def private_docs():
    if not os.path.isdir(PRIVATE):
        return []
    return sorted(f for f in os.listdir(PRIVATE) if f.endswith(".md"))


def phase_status(body=None):
    """PHASES.md 가 말하는 Phase 별 상태.

    `body` 를 주면 그것을 읽는다 — 파서 자체를 고정 입력으로 검사하기 위해서다.
    실제 파일로만 검사하면 파일 상태에 따라 검사 내용이 바뀐다.
    """
    if body is None:
        if not os.path.exists(PHASES):
            return set(), set()
        with open(PHASES, encoding="utf-8") as fh:
            body = fh.read()
    return set(DONE_PHASE.findall(body)), set(ACTIVE_PHASE.findall(body))


def declares_closed(body):
    """문서가 첫머리에서 스스로 닫혔다고 말하는가."""
    return "닫혔다" in body[:1200] or "종료:" in body[:1200] or "종료일" in body[:1200]


def read(name):
    with open(os.path.join(PRIVATE, name), encoding="utf-8") as fh:
        return fh.read()


class ClosedPhasesHaveNoOpenBoxesTest(unittest.TestCase):
    """완료된 Phase 의 계획서에 열린 항목이 남아 있으면 안 된다."""

    def setUp(self):
        if not private_docs():
            self.skipTest("private/ 없음 — 로컬 전용 검사 (CI 는 항상 이 경로)")
        self.done, self.active = phase_status()

    def test_no_ghost_items_in_closed_plan_docs(self):
        """닫힌 문서에 열린 항목이 있으면 안 된다.

        판정을 **문서의 자기 선언**으로 한다. 처음에는 문서가 언급한 Phase 이름으로
        판정했는데, `HARNESS_PLAN.md` 는 "Phase 1" 처럼 자체 번호를 써서 `PHASE_PMFxx`
        가 한 번도 안 나온다 — 규칙이 통째로 비껴갔고, 위반을 주입해도 안 잡혔다.
        문서 표기에 의존하는 규칙은 표기가 다른 문서를 그냥 놓친다.
        """
        offenders = []
        for name in private_docs():
            if name in LIVE_DOCS:
                continue
            body = read(name)
            open_count = body.count(OPEN_BOX)
            if not open_count:
                continue
            if declares_closed(body):
                offenders.append(f"  {name}: 닫혔다고 적어놓고 열린 항목이 {open_count}개")
                continue
            mentioned = set("PHASE_" + m.group(0)[6:] for m in PHASE_IN_DOC.finditer(body))
            if (mentioned & self.done) and not (mentioned & self.active):
                offenders.append(
                    f"  {name}: 열린 항목 {open_count}개 — 그런데 "
                    f"{', '.join(sorted(mentioned & self.done))} 는 이미 DONE 이다")
        self.assertEqual(
            [], offenders,
            "계획 문서가 일이 끝난 것을 모르는 상태다. 다음 세션은 그걸 '안 한 일'로 "
            "읽는다:\n" + "\n".join(offenders))

    def test_live_docs_are_allowed_to_have_open_items(self):
        """진행 중인 계획까지 닫으라고 하면 이 검사가 계획 세우기를 막는다."""
        self.assertTrue(
            any(read(n).count(OPEN_BOX) >= 0 for n in LIVE_DOCS if
                os.path.exists(os.path.join(PRIVATE, n))),
            "LIVE_DOCS 가 실재하지 않는다 — 이름이 바뀌었는지 확인")

    def test_a_closed_doc_says_it_is_closed(self):
        """닫은 문서는 첫머리에서 그 사실을 말해야 한다. 안 그러면 또 열어본다."""
        missing = []
        for name in private_docs():
            if name in LIVE_DOCS:
                continue
            body = read(name)
            mentioned = set("PHASE_" + m.group(0)[6:] for m in PHASE_IN_DOC.finditer(body))
            if not (mentioned & self.done) or (mentioned & self.active):
                continue
            if not declares_closed(body):
                missing.append(name)
        self.assertEqual(
            [], missing,
            "완료된 Phase 의 계획서인데 닫혔다는 표시가 첫머리에 없다: " + ", ".join(missing))


class TheGuardItselfTest(unittest.TestCase):
    """검사가 실제로 잡는지. 항상 통과하는 검사는 검사가 아니다."""

    FIXTURE = (
        "## PHASE_PMF01 \u2705 DONE (2026-01-01)\n"
        "> 끝난 것\n\n"
        "## PHASE_PMF02 \U0001f6a7 IN PROGRESS\n"
        "> 하는 중\n"
    )

    def test_parser_tells_the_two_headers_apart(self):
        """파서를 **고정 입력**으로 검사한다.

        처음엔 실제 PHASES.md 로 "완료도 있고 진행 중도 있다"를 단언했는데,
        Phase 를 다 닫은 순간 진행 중이 0이 되어 깨졌다. **Phase 사이의 전환 대기는
        정상 상태지 고장이 아니다** — 같은 실수를 이 파일에서 두 번째로 했다
        (`test_open_box_marker_matches_the_docs` 주석 참조).

        그렇다고 단언을 지우면 🚧 인식이 무검증으로 남는다. 헤더 형식이 바뀌어도
        아무도 모른다. 그래서 파일이 아니라 파서를 검사한다.
        """
        done, active = phase_status(self.FIXTURE)
        self.assertEqual({"PHASE_PMF01"}, done)
        self.assertEqual({"PHASE_PMF02"}, active)

    def test_real_phases_doc_is_readable_and_consistent(self):
        """실제 파일에는 **항상 참인 것만** 묻는다."""
        if not os.path.exists(PHASES):
            self.skipTest("PHASES.md 없음")
        done, active = phase_status()
        self.assertTrue(done, "완료 Phase 를 하나도 못 읽었다 — 헤더 형식이 바뀌었는지 확인")
        self.assertFalse(done & active, "같은 Phase 가 완료이자 진행 중이다")
        self.assertLessEqual(len(active), 1,
                             f"진행 중 Phase 가 둘 이상이다: {sorted(active)}")

    def test_open_box_marker_matches_the_docs(self):
        """마커가 문서 표기와 어긋나면 이 파일 전체가 조용히 무의미해진다.

        **열린 항목이 지금 존재하는지로 검사하면 안 된다.** 처음엔 그렇게 썼는데,
        Phase 를 다 닫은 순간 PHASES.md 의 열린 항목이 0이 되어 이 테스트가 깨졌다.
        "할 일이 하나도 없다"는 정상 상태지 고장이 아니다.

        그래서 표기 규약 자체를 본다 — 닫힌 마커는 반드시 있고(무언가는 끝났다),
        두 마커는 가운데 글자만 다르다.
        """
        if not os.path.exists(PHASES):
            self.skipTest("PHASES.md 없음")
        body = read("PHASES.md")
        self.assertIn("- [x]", body, "닫힌 체크박스 표기를 못 찾는다 — 형식이 바뀌었나")
        self.assertEqual(OPEN_BOX.replace(" ]", "x]"), "- [x]",
                         "열림/닫힘 마커가 같은 규약이 아니다")


if __name__ == "__main__":
    unittest.main()
