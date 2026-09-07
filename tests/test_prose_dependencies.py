"""`depends_on` 이 왜 0%였는지, 그리고 무엇을 고쳤는지 고정한다.

## 실측이 진단을 뒤집었다

PMF08 이 `depends_on` 을 만든 근거는 "484건 중 22건이 선행 관계를 **말로** 적고 있다 —
사람은 읽지만 보드는 모른다"였다. 진단은 맞았다. 그런데 9일 뒤 **사용 0 / 2,141** 이다.

처음엔 "배선이 없어서"라고 봤다(PMF12 #90 과 같은 형태). 표본을 열어보니 더 근본적이었다.
활성 태스크가 본문에 적은 선행조건 **28건 중 `depends_on` 으로 표현 가능한 것은 1건**이다.

    ZEMAT #47        "#46 선행"                    → 옮길 수 있다
    ZEMAT #37        "G2B 수집 완료 후"             → 태스크가 아니다
    codebook #342    "UI 병합 완료 후"              → 태스크가 아니다

**필드의 모양이 실제 필요의 3.5% 만 담는다.** 그것이 0%인 이유다.

## 그래서 고친 것은 필드가 아니라 신호다

`blocked: {}` 는 "아무것도 막혀 있지 않다"로 읽힌다. 그런데 활성 27건이 선행조건을
적어둔 보드에서 그 답은 **거짓 신호**다. 진짜 상태는 "판단할 데이터가 없다"다.

PMF12 에서 검색이 똑같은 실수를 했다 — 없는 경로에 `0건` 을 돌려줘서 "그런 기록은
없구나"로 읽혔다. **"찾았는데 없다"와 "찾을 데가 없다"는 다르다.**

이 파일이 지키는 것 넷:

1. **없는 데이터를 "괜찮다"로 말하지 않는다.**
2. **감지는 하되 옮기라고 시키지 않는다** — 대부분 옮길 수 없는 형태다.
3. **넓게 잡지 않는다.** 넓은 규칙은 hot 511건 중 85건을 잡았고 표본 대부분이 오탐이었다.
   규칙을 넓게 잡으면 규칙이 꺼진다.
4. **번호가 실재해야 한다.** 표본의 `#569`·`#570` 은 PR 번호였다.
"""
import importlib.util
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("vh_server_prose",
                                               os.path.join(SCRIPTS, "server.py"))
server = importlib.util.module_from_spec(_spec)
sys.modules["vh_server_prose"] = server
_spec.loader.exec_module(server)


def task(tid, text="", status="todo", **extra):
    out = {"id": tid, "title": "제목", "details": text, "status": status}
    out.update(extra)
    return out


def candidates(tasks, archived=()):
    return {c["id"]: c for c in server._prose_dependency_candidates(tasks, archived)}


class FindsWhatCanBeMovedTest(unittest.TestCase):
    def test_a_numbered_prerequisite_is_suggested(self):
        """실제 표본: ZEMAT #47 의 `#46 선행`. 이건 옮길 수 있다."""
        found = candidates([task(46, "먼저 할 것", status="done"),
                            task(47, "GCS 반입 코드가 없어 수동 배치 필요. #46 선행.")])
        self.assertEqual(["46"], found[47]["suggests_depends_on"])

    def test_blocked_by_in_english_counts(self):
        found = candidates([task(1, "x", status="done"), task(2, "blocked by #1")])
        self.assertEqual(["1"], found[2]["suggests_depends_on"])

    def test_a_task_that_already_declares_is_left_alone(self):
        """이미 채운 태스크를 다시 제안하면 그 목록은 곧 무시된다."""
        found = candidates([task(1, "x", status="done"),
                            task(2, "#1 선행", depends_on=[1])])
        self.assertNotIn(2, found)


class RefusesToGuessTest(unittest.TestCase):
    """넓게 잡으면 규칙이 꺼진다. **오탐 셋은 전부 실제 표본에서 나왔다.**"""

    def test_a_number_that_is_not_a_task_is_ignored(self):
        """impactbook_ai 표본의 `#569`·`#570` 은 PR 번호였다.

        검증 없이 제안하면 보드가 **없는 의존**을 말한다.
        """
        found = candidates([task(2, "#569 를 먼저 정리한 뒤 진행")])
        self.assertNotIn("suggests_depends_on", found.get(2, {}))

    def test_precedent_is_not_a_prerequisite(self):
        """pante_bde #48 **원문 그대로.** 참조와 선행은 다르다.

        문자열을 실제 코퍼스에서 가져온 이유가 있다. 처음엔 짧게 지어 썼는데,
        `PROSE_NOT_DEP` 를 지우는 위반을 주입해도 테스트가 **통과**했다 — 지어낸
        문장은 좁은 정규식이 이미 걸러서, 필터를 검사하고 있지 않았다.
        실측으로 확인한 결과 필터는 전체 코퍼스에서 44건 → 42건으로 2건을 걸러내고,
        그 2건이 정확히 이 테스트와 아래 테스트의 문장이다.
        """
        found = candidates([task(47, "x", status="done"),
                            task(48, "프로덕션 전에 프리뷰 채널에 먼저 올려 우선순위 "
                                     "가정을 실측했다. #47 에서 글롭 가정이 틀렸던 "
                                     "전례가 있어 추측하지 않았다")])
        self.assertEqual({}, found, "'전례가 있어'를 선행조건으로 읽었다")

    def test_a_negation_is_not_a_prerequisite(self):
        """looom_dev #10 **원문 그대로.** 부정문은 반대를 말한다."""
        found = candidates([task(1, "presigned GET 을 지원하는지 순수 파이썬 SigV4 "
                                    "구현으로 먼저 확인했다(내 Rust 코드에 "
                                    "의존하지 않는 검증)")])
        self.assertEqual({}, found, "'의존하지 않는'을 의존으로 읽었다")

    def test_prior_art_never_reaches_the_filter(self):
        """`근접 선행기술 후보 제시` (agent-rnd-dfrn #22).

        이건 **좁은 정규식이 먼저 걸러낸다** — `선행` 뒤에 콜론이 없으므로 후보가 되지
        않는다. 필터가 잡는 것이 아니라는 사실을 적어둔다. 두 방어를 뭉개면 어느 쪽이
        실제로 일하는지 모르게 된다.
        """
        self.assertEqual({}, candidates([task(1, "UI 문구는 '근접 선행기술 후보 제시'에 머문다")]))
        self.assertIsNone(server.PROSE_PREREQ.search("근접 선행기술 후보 제시"))


class NamesWhatCannotBeMovedTest(unittest.TestCase):
    """표본 28건 중 27건이 이 형태였다. **옮기라고 시키면 보드가 거짓말을 한다.**"""

    def test_a_prerequisite_without_a_task_is_reported_separately(self):
        found = candidates([task(1, "G2B 수집 완료 후 프로덕 반영")])
        self.assertIn("prose_prerequisite", found[1])
        self.assertNotIn("suggests_depends_on", found[1],
                         "태스크가 아닌 것을 depends_on 으로 제안했다")

    def test_decision_references_are_their_own_bucket(self):
        """`결정 #7`·`decisions #11` 은 선행이 아니라 결정↔태스크 링크다."""
        found = candidates([task(1, "decisions #11 에 따른 서브시스템 제거")])
        self.assertEqual(["11"], found[1]["mentions_decisions"])
        self.assertNotIn("suggests_depends_on", found[1])

    def test_a_decision_number_is_not_mistaken_for_a_task(self):
        found = candidates([task(7, "x", status="done"),
                            task(1, "결정 #7의 전제")])
        self.assertNotIn("suggests_depends_on", found.get(1, {}))


class EmptyIsNotFineTest(unittest.TestCase):
    """**"막힌 것 없음" 과 "판단할 데이터가 없음" 은 다르다.**

    PMF12 에서 검색이 같은 실수를 했다 — 없는 경로에 `0건` 을 돌려줬다.
    """

    def test_no_declarations_says_there_is_nothing_to_judge(self):
        rep = server._dependency_report([task(1, "G2B 수집 완료 후 반영")])
        self.assertEqual({}, rep["blocked"])
        self.assertEqual(0, rep["declared"])
        self.assertIn("판단 불가", rep["note"])

    def test_it_says_how_many_stated_a_prerequisite_anyway(self):
        """반증을 함께 싣지 않으면 "데이터 없음"이 "필요 없음"으로 읽힌다."""
        rep = server._dependency_report([task(1, "UI 병합 완료 후 진행"),
                                         task(2, "관계 없는 일")])
        self.assertIn("1건", rep["note"])
        self.assertEqual(1, rep["stated_in_prose_total"])

    def test_a_declared_board_gets_no_such_note(self):
        """선언이 있으면 blocked 는 진짜 답이다. 그때 경고하면 소음이다."""
        rep = server._dependency_report([task(1, "x", status="done"),
                                         task(2, "y", depends_on=[1])])
        self.assertEqual(1, rep["declared"])
        self.assertNotIn("note", rep)

    def test_an_empty_board_is_left_alone(self):
        self.assertEqual({"blocked": {}, "unknown_refs": {}, "cycles": [], "ready": []},
                         server._dependency_report([]))

    def test_done_tasks_prerequisites_are_history_not_signal(self):
        rep = server._dependency_report([task(1, "G2B 수집 완료 후 반영", status="done")])
        self.assertNotIn("stated_in_prose", rep)

    def test_the_prose_list_is_a_sample_not_the_whole_thing(self):
        """**세션 시작 비용이 이 결정의 전부다.**

        처음엔 본문 발췌를 20건까지 실었더니 `/context` 가 프로젝트당 최대 3,278 B
        (약 1,092 tok) 늘고 pante_bde 는 응답의 41% 가 이 항목이 됐다 —
        PMF10 이 세션 시작을 867 tok 으로 만든 것을 그대로 되돌리는 셈이었다.
        발췌를 빼서 1,890 B, 표본을 5건으로 줄여 더 낮췄다.
        """
        rep = server._dependency_report(
            [task(i, "UI 병합 완료 후 진행") for i in range(1, 31)])
        self.assertEqual(30, rep["stated_in_prose_total"], "총 건수는 진실을 말해야 한다")
        self.assertEqual(5, len(rep["stated_in_prose"]))

    def test_context_does_not_carry_the_prose_text(self):
        """발췌는 여기 싣지 않는다. 문장이 필요하면 검색으로 찾는다."""
        rep = server._dependency_report([task(1, "UI 병합 완료 후 진행")])
        entry = rep["stated_in_prose"][0]
        self.assertNotIn("prose_prerequisite", entry,
                         "본문 발췌가 /context 로 새어 들어갔다 — 세션마다 값을 치른다")
        self.assertTrue(entry["prose"])

    def test_the_function_still_gives_the_text_when_asked(self):
        """/context 에서 뺀 것이 아예 없어지면 조사할 방법이 없다."""
        found = candidates([task(1, "UI 병합 완료 후 진행")])
        self.assertIn("완료 후", found[1]["prose_prerequisite"])


class SessionStartStaysCheapTest(unittest.TestCase):
    """**이 검사가 없어서 내가 867 tok 을 깨뜨렸다.**

    본문 발췌를 20건까지 실었더니 `/context` 의 이 절이 프로젝트당 최대 3,278 B
    (약 1,092 tok)가 됐고 pante_bde 는 응답의 41% 였다. PMF10 이 세션 시작을
    21,446 → 867 tok 으로 만든 것을 그대로 되돌리는 셈이었다.

    발췌·제목을 빼고 표본을 5건으로 줄이고 note 를 한 줄로 압축해 내려왔다.
    **예산을 숫자로 못 박는다** — 다음에 누가 여기 뭘 더 실으면 이 테스트가 먼저 깨진다.
    """

    BUDGET = 400          # 바이트. 22개 프로젝트가 세션마다 치르는 값이다.

    def test_the_section_fits_its_budget_at_scale(self):
        import json
        tasks = [task(i, "UI 병합 완료 후 진행 — " + "긴 설명 " * 40)
                 for i in range(1, 71)]
        rep = server._dependency_report(tasks)
        size = len(json.dumps({k: v for k, v in rep.items()
                               if k in ("declared", "note", "stated_in_prose",
                                        "stated_in_prose_total")},
                              ensure_ascii=False).encode())
        self.assertLess(size, self.BUDGET,
                        "의존 보고가 %d B 다 (예산 %d) — 세션 시작이 다시 비싸진다"
                        % (size, self.BUDGET))

    def test_the_total_is_still_honest_under_budget(self):
        """예산을 지키려고 숫자를 줄이면 그게 조용히 틀린 답이다."""
        rep = server._dependency_report([task(i, "UI 병합 완료 후") for i in range(1, 71)])
        self.assertEqual(70, rep["stated_in_prose_total"])


class TheRuleIsWrittenWhereTheAgentReadsItTest(unittest.TestCase):
    """규칙이 스킬에 없으면 다음 세션이 또 `blocked: {}` 를 초록으로 읽는다."""

    def skill(self):
        with open(os.path.join(ROOT, "skills", "vibe-harness", "SKILL.md"),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_the_skill_explains_what_the_field_cannot_hold(self):
        body = self.skill()
        self.assertIn("depends_on", body,
                      "SKILL.md 가 필드를 한 번도 언급하지 않는다 — 그게 0%의 원인이었다")
        self.assertIn("27", body, "'대부분 옮길 수 없다'는 실측 근거가 없다")

    def test_the_skill_warns_about_reading_blocked(self):
        self.assertIn("dependencies.note", self.skill(),
                      "빈 blocked 를 그냥 믿으라고 두면 거짓 신호가 유지된다")

    def test_the_skill_does_not_tell_you_to_force_the_field(self):
        self.assertIn("Do not force other shapes into it", self.skill())


if __name__ == "__main__":
    unittest.main()
