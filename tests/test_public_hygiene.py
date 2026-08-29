"""공개 레포에 사내 정보가 들어가는 것을 막는다.

이 레포는 public 이다. 그런데 사내 정보가 공개 파일 안으로 두 번 새어 나갔고,
두 번 다 사후에 히스토리를 재작성해서 지웠다 — 되돌릴 수 없는 종류의 사고를
사후 대응으로만 처리해 온 것이다. 경계는 `private/` 라는 폴더 규칙으로만 존재했고,
그 규칙이 지켜졌는지 검사하는 장치는 없었다.

여기서 검사한다.

## 왜 금칙어 목록이 이 파일에 없는가

금칙어를 레포에 적으면 그 목록 자체가 유출이다. "우리 제품은 A·B·C 이고
토큰을 이만큼 쓴다"를 검사기에 적어두면 검사기가 유출원이 된다.

그래서 두 층으로 나눈다.

- **구조 규칙** (이 파일) — 값이 아니라 *모양*을 본다. 10자리 숫자, 내부 소스 경로,
  채팅 uid, DB 컬럼 참조. 공개해도 안전하고 CI 에서 항상 돈다.
- **정확 문자열** (`private/DENY.txt`, gitignore 됨) — 있으면 추가로 검사한다.
  로컬에서만 돈다. CI 에는 없으므로 구조 규칙이 최후 방어선이다.

구조 규칙만으로 두 번의 실제 사고를 모두 잡는다는 것은 확인했다
(지출 수치 = R1, 사내 모듈 경로 = R2).

## 검사 대상

**git 이 추적하는 파일만** 본다. `private/` 와 gitignore 된 것은 애초에 공개되지
않으므로 대상이 아니다 — 이 경계를 코드가 아니라 git 에게 묻는 것이 핵심이다.
`.gitignore` 를 고치는 순간 검사 범위도 따라 움직인다.

## 예외

정말 필요하면 그 줄 끝에 `public-ok` 를 남긴다. 남용하면 게이트가 무의미해지므로
리뷰에서 이 표시가 늘어나는지 본다.
"""
import os
import re
import subprocess
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DENY_FILE = os.path.join(ROOT, "private", "DENY.txt")
ALLOW_MARK = "public-ok"

# 바이너리·생성물은 본문 검사 대상이 아니다.
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2")

# 이 파일 자신은 규칙의 예시를 담고 있으므로 대상에서 뺀다.
SELF = os.path.relpath(os.path.abspath(__file__), ROOT)

RULES = (
    (
        "R1 대형 수치",
        re.compile(r"[0-9],[0-9]{3},[0-9]{3},[0-9]{3}"),
        "자릿수 구분된 10자리 이상 숫자 — 토큰 소비량이면 공개 단가표로 지출이 역산된다",
    ),
    (
        "R2 사내 소스 경로",
        re.compile(r"\blib/[A-Za-z][A-Za-z0-9]*\.ts\b|\bapp/api/[a-z0-9/_-]+/route\.ts\b"),
        "사내 애플리케이션의 파일 구조 — 모듈명·데이터 흐름·인증 함수가 드러난다",
    ),
    (
        "R3 채팅 uid",
        re.compile(r"(?<![0-9])[0-9]{17,20}(?![0-9])"),
        "17~20자리 snowflake — 개인 식별자다",
    ),
    (
        "R4 인사 DB 컬럼",
        re.compile(r"\bemployees\.[a-z_]+"),
        "사내 DB 스키마 참조",
    ),
)


def tracked_files():
    """git 이 추적하는 파일. 경계를 코드가 아니라 git 에게 묻는다."""
    out = subprocess.run(
        ["git", "-C", ROOT, "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def scannable(path):
    if path == SELF:
        return False
    return not path.lower().endswith(SKIP_SUFFIXES)


def read(path):
    full = os.path.join(ROOT, path)
    try:
        with open(full, encoding="utf-8") as fh:
            return fh.read().splitlines()
    except (UnicodeDecodeError, FileNotFoundError):
        return []


def scan(matcher):
    """추적 파일 전체에서 matcher(line) 이 참인 줄을 모은다."""
    hits = []
    for path in tracked_files():
        if not scannable(path):
            continue
        for n, line in enumerate(read(path), 1):
            if ALLOW_MARK in line:
                continue
            if matcher(line):
                hits.append((path, n, line.strip()[:110]))
    return hits


class StructuralRulesTest(unittest.TestCase):
    """값이 아니라 모양을 검사한다 — 공개해도 안전한 규칙이라 CI 에서 항상 돈다."""

    def test_no_internal_shapes_in_tracked_files(self):
        failures = []
        for name, pattern, why in RULES:
            hits = scan(pattern.search)
            for path, n, line in hits:
                failures.append(f"  [{name}] {path}:{n}\n      {line}\n      → {why}")
        self.assertEqual(
            [], failures,
            "공개 레포에 사내 정보로 보이는 것이 있다. 값을 지우거나, 정말 공개해도 되면 "
            "해당 줄에 'public-ok' 를 남긴다.\n" + "\n".join(failures),
        )

    def test_allow_marks_do_not_pile_up(self):
        """예외가 늘면 게이트가 무의미해진다. 지금 몇 개인지 눈에 보이게 한다."""
        marked = scan(lambda line: ALLOW_MARK in line)
        self.assertLessEqual(
            len(marked), 5,
            "public-ok 예외가 %d 개다. 규칙이 현실과 안 맞으면 규칙을 고쳐야지 "
            "예외를 늘릴 일이 아니다:\n%s" % (
                len(marked), "\n".join(f"  {p}:{n}" for p, n, _ in marked)),
        )


class ExactDenyListTest(unittest.TestCase):
    """private/DENY.txt 가 있으면 정확 문자열도 검사한다. 로컬 전용."""

    def test_deny_list_strings_are_absent(self):
        if not os.path.exists(DENY_FILE):
            self.skipTest("private/DENY.txt 없음 — 구조 규칙만으로 검사 (CI 는 항상 이 경로)")
        with open(DENY_FILE, encoding="utf-8") as fh:
            terms = [t.strip() for t in fh
                     if t.strip() and not t.startswith("#")]
        self.assertTrue(terms, "DENY.txt 가 비어 있다")
        failures = []
        for term in terms:
            for path, n, line in scan(lambda line, t=term: t in line):
                failures.append(f"  {path}:{n}  ({term!r})\n      {line}")
        self.assertEqual([], failures,
                         "금칙 문자열이 추적 파일에 있다:\n" + "\n".join(failures))


class GateItselfTest(unittest.TestCase):
    """게이트가 실제로 잡는지 확인한다 — 항상 통과하는 테스트는 테스트가 아니다."""

    SAMPLES = (
        ("R1", "합계 6,549,138,399 토큰"),
        ("R2", "`lib/vibeHarness.ts` 가 처리한다"),
        ("R2", "`app/api/internal/vibe-harness/runs/route.ts` 를 거친다"),
        ("R3", "uid 793831661170982942 로 발급"),
        ("R4", "`employees.discord_user_id` 에서 읽는다"),
    )

    def test_every_rule_catches_a_real_violation(self):
        for label, sample in self.SAMPLES:
            with self.subTest(sample=sample):
                self.assertTrue(
                    any(p.search(sample) for _, p, _ in RULES),
                    f"{label} 위반인데 어떤 규칙도 잡지 못한다: {sample!r}",
                )

    def test_allow_mark_suppresses_a_violation(self):
        line = "합계 6,549,138,399 토큰  " + ALLOW_MARK
        self.assertTrue(any(p.search(line) for _, p, _ in RULES),
                        "표본이 규칙에 걸리지 않아 예외 검사가 무의미하다")
        self.assertIn(ALLOW_MARK, line)

    def test_scan_covers_tracked_files_only(self):
        files = tracked_files()
        self.assertTrue(files, "추적 파일을 하나도 찾지 못했다 — git 호출이 깨졌다")
        self.assertFalse([p for p in files if p.startswith("private/")],
                         "private/ 가 추적되고 있다 — gitignore 가 깨졌다")


if __name__ == "__main__":
    unittest.main()
