"""주간 리뷰를 중앙으로 보내는 클라이언트를 고정한다.

리뷰는 지금까지 이 레포의 `docs/developer-reviews/` 에 쌓였는데 **이 레포는 공개**다.
약점을 짚고 실수치를 인용하고 사람에게 점수를 매기는 문서가 그대로 밖에서 보였다.
지금까지 것은 샘플로 남기고 앞으로는 중앙에 둔다.

이 파일이 지키는 것 셋:

1. **owner 를 클라이언트가 보내지 않는다.** 보내면 남의 이름으로 리뷰를 올릴 수 있다.
   중앙이 개인 토큰으로 판정한다 — `runs` 와 같은 규칙이다.
2. **자격증명을 여기서 다시 구현하지 않는다.** `reconcile_runs.push_credential()` 을
   재사용한다. 두 경로가 갈라지면 한쪽만 공유 secret 으로 떨어져도 아무도 모른다.
3. **기간을 추측하지 않는다.** 파일명에서 못 읽으면 멈춘다. 추측하면 다른 주를 덮어쓴다.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("review_sync", os.path.join(SCRIPTS, "review_sync.py"))
rs = importlib.util.module_from_spec(_spec)
sys.modules["review_sync"] = rs
_spec.loader.exec_module(rs)


def review_dir(period="2026-W37", scores=None, priorities=None, html="<!doctype html>본문"):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, f"{period}.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    with open(os.path.join(d, "history.json"), "w", encoding="utf-8") as fh:
        json.dump({"reviews": [{
            "period": {"label": period},
            "scores": scores or {"overall": 7, "testing": 8},
            "priorities": priorities or [
                {"category": "워킹트리 공유", "severity": "critical",
                 "status": "repeated", "consecutive_weeks": 3, "actions": ["…"]}],
        }]}, fh, ensure_ascii=False)
    return os.path.join(d, f"{period}.html")


class PeriodTest(unittest.TestCase):
    def test_reads_period_from_filename(self):
        self.assertEqual("2026-W37", rs.period_of("/x/2026-W37.html"))

    def test_reads_corrected_period(self):
        self.assertEqual("2026-W35r", rs.period_of("/x/2026-W35r.html"))

    def test_refuses_to_guess(self):
        """추측하면 다른 주를 덮어쓴다."""
        with self.assertRaises(SystemExit):
            rs.period_of("/x/review-latest.html")


class PayloadTest(unittest.TestCase):
    def test_carries_scores_and_priorities_structured(self):
        """HTML 만 보내면 중앙이 점수를 파싱해야 한다 — 파서가 하나 더 생긴다."""
        payload = rs.build_payload(review_dir())
        self.assertEqual("2026-W37", payload["period"])
        self.assertEqual(7, payload["scores"]["overall"])
        self.assertEqual(3, payload["priorities"][0]["consecutive_weeks"])

    def test_never_sends_an_owner_field(self):
        """클라이언트가 owner 를 주장하면 위조된다. 중앙이 토큰으로 판정한다."""
        payload = rs.build_payload(review_dir())
        for forbidden in ("owner", "author", "user", "developer"):
            self.assertNotIn(forbidden, payload,
                             f"payload 에 {forbidden} 가 있다 — 남의 이름으로 올릴 수 있다")

    def test_priorities_carry_only_the_tracking_fields(self):
        """actions 같은 본문은 html 에 있다. 중복해서 실으면 두 곳이 갈라진다."""
        payload = rs.build_payload(review_dir())
        self.assertEqual({"category", "severity", "status", "consecutive_weeks"},
                         set(payload["priorities"][0]))

    def test_html_travels_whole(self):
        body = "<!doctype html>" + "가" * 5000
        payload = rs.build_payload(review_dir(html=body))
        self.assertEqual(body, payload["html"],
                         "리뷰 본문은 자체완결 문서다 — 잘라 보내면 열 수 없다")

    def test_refuses_when_history_has_no_such_period(self):
        """리뷰는 시리즈다. 점수 기록 없이 HTML 만 보내면 추이를 이을 수 없다."""
        path = review_dir(period="2026-W37")
        other = os.path.join(os.path.dirname(path), "2026-W99.html")
        with open(other, "w", encoding="utf-8") as fh:
            fh.write("x")
        with self.assertRaises(SystemExit):
            rs.build_payload(other)

    def test_refuses_when_history_is_missing(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "2026-W37.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x")
        with self.assertRaises(SystemExit):
            rs.build_payload(path)


class CredentialTest(unittest.TestCase):
    def test_does_not_reimplement_credential_selection(self):
        """두 경로가 갈라지면 한쪽만 공유 secret 으로 떨어져도 아무도 모른다."""
        with open(os.path.join(SCRIPTS, "review_sync.py"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("push_credential", body, "runs 의 자격증명 선택을 재사용해야 한다")
        self.assertNotIn("runs_token", body.split('"""', 2)[-1],
                         "자격증명 선택을 여기서 다시 구현하고 있다")

    def test_targets_the_reviews_route(self):
        with open(os.path.join(SCRIPTS, "review_sync.py"), encoding="utf-8") as fh:
            self.assertIn('"/reviews"', fh.read())


class SkillForbidsPublicOutputTest(unittest.TestCase):
    """규칙을 스킬에 적지 않으면 다음 리뷰가 또 공개 레포에 쓰인다."""

    def test_skill_says_not_to_write_into_a_public_repo(self):
        p = os.path.join(ROOT, "skills", "vibe-review", "SKILL.md")
        with open(p, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("public repository", body)
        self.assertIn("review_sync.py", body,
                      "대안 경로를 말하지 않으면 어디 쓰라는 건지 모른다")

    def test_existing_reviews_stay_as_samples(self):
        """지금까지 것은 도구를 보여주는 예시로 남긴다 — 이 테스트는 그 결정을 기록한다."""
        d = os.path.join(ROOT, "docs", "developer-reviews", "hoarchi")
        self.assertTrue(os.path.isdir(d))
        kept = sorted(f for f in os.listdir(d) if f.endswith(".html"))
        self.assertGreaterEqual(len(kept), 4,
                                "샘플로 남기기로 한 기존 리뷰가 사라졌다")


if __name__ == "__main__":
    unittest.main()
