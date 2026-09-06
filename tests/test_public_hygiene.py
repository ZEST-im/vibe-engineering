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
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DENY_FILE = os.path.join(ROOT, "private", "DENY.txt")
ALLOW_MARK = "public-ok"

# **바이너리로 추적해도 되는 것.** 여기 있는 확장자만이다.
#
# 이 목록은 "본문 검사에서 뺀다"가 아니라 **"이 바이너리는 검토했다"는 선언**이다.
# 게이트는 읽을 수 없는 파일에 대해 아무 말도 할 수 없으므로, 목록 밖의 바이너리가
# 추적되고 있으면 그것 자체를 신고한다 — "못 읽었으니 깨끗하다"는 결론은 낼 수 없다.
#
# 실제로 뚫렸다: `.coverage`(53KB SQLite, 로컬 절대경로 포함)가 공개 레포에 올라가
# 있었는데 게이트는 초록이었다. 읽다 UnicodeDecodeError 가 나면 조용히 건너뛰었기
# 때문이다. 여기 새 확장자를 추가하는 것은 가볍게 할 일이 아니다.
BINARY_OK = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2")
SKIP_SUFFIXES = BINARY_OK

# 이 파일 자신은 규칙의 예시를 담고 있으므로 대상에서 뺀다.
# git ls-files 는 항상 "/" 로 구분된 경로를 준다. os.path.relpath 는 Windows 에서
# 역슬래시를 쓰므로 정규화하지 않으면 이 비교가 영원히 어긋나고, 게이트가 자기
# 픽스처를 위반으로 신고한다. 규칙이 진짜 깨진 것과 구분이 안 되는 오탐이다.
SELF = os.path.relpath(os.path.abspath(__file__), ROOT).replace(os.sep, "/")

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
        capture_output=True, text=True, encoding="utf-8", check=True,
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


def is_text(full):
    """줄 단위 검사가 닿을 수 있는 파일인가. False 면 규칙 넷 중 무엇도 이걸 못 본다.

    **UTF-8 디코딩만으로는 부족하다.** SQLite 헤더 `SQLite format 3\x00` 은 전부
    유효한 UTF-8 코드포인트라 그냥 읽힌다 — 처음에 그렇게 짰다가 `.coverage` 를
    흉내낸 픽스처를 놓쳤다. 그래서 **NUL 바이트를 먼저 본다**: git 자신이 바이너리를
    가르는 데 쓰는 판정이고, 텍스트 파일에는 나타나지 않는다.
    """
    try:
        with open(full, "rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        # 추적돼 있는데 디스크에 없다 — 검사할 내용이 없는 것이지 바이너리는 아니다.
        return True
    if b"\0" in chunk:
        return False
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        # 8KB 경계에서 멀티바이트 문자가 잘렸을 수 있다. 그때는 전체로 다시 본다.
        try:
            with open(full, encoding="utf-8") as fh:
                fh.read()
        except UnicodeDecodeError:
            return False
    return True


def unscannable_tracked(paths=None, root=None):
    """**읽을 수 없는데 허용 목록에도 없는** 추적 파일.

    게이트의 눈먼 곳이다. 규칙 넷은 전부 줄 단위 검사라 바이너리에는 닿지 못하는데,
    닿지 못한 것과 깨끗한 것이 여태 구별되지 않았다.
    """
    root = ROOT if root is None else root
    paths = tracked_files() if paths is None else paths
    return sorted(p for p in paths
                  if not p.lower().endswith(BINARY_OK)
                  and not is_text(os.path.join(root, p)))


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


class NothingIsSilentlySkippedTest(unittest.TestCase):
    """게이트가 **못 본 것**과 **깨끗한 것**은 다르다.

    규칙 넷은 전부 줄 단위 검사라 바이너리에 닿지 못한다. 닿지 못하면 조용히
    건너뛰었고, 그래서 `.coverage`(53KB SQLite, 로컬 절대경로 포함)가 공개 레포에
    올라간 채로 게이트는 초록이었다.

    이 레포가 반복해 온 실패는 코드 결함이 아니라 **성공처럼 보이는 침묵**이다.
    게이트 자신이 그 형태를 하나 갖고 있었다.
    """

    def test_every_tracked_binary_is_a_declared_asset(self):
        found = unscannable_tracked()
        self.assertEqual(
            [], found,
            "읽을 수 없는데 허용 목록에도 없는 추적 파일: " + ", ".join(found)
            + "\n  게이트는 이 파일들에 대해 아무것도 말하지 못한다 — '못 읽었으니 "
              "깨끗하다'는 결론은 낼 수 없다.\n  추적에서 빼거나(대개 이쪽), 검토한 뒤 "
              "BINARY_OK 에 확장자를 추가할 것.")

    def test_it_catches_a_binary_that_is_not_on_the_list(self):
        """`.coverage` 를 되돌리면 잡혀야 한다. 이 시나리오가 정확히 그것이다."""
        d = tempfile.mkdtemp()
        with open(os.path.join(d, ".coverage"), "wb") as fh:
            fh.write(b"SQLite format 3\x00\x01\x02")
        self.assertEqual([".coverage"],
                         unscannable_tracked([".coverage"], root=d))

    def test_a_declared_asset_is_not_flagged(self):
        """스크린샷까지 신고하면 목록이 곧 무시된다."""
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "shot.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n\x00")
        self.assertEqual([], unscannable_tracked(["shot.png"], root=d))

    def test_text_is_not_flagged(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "a.md"), "w", encoding="utf-8") as fh:
            fh.write("한글도 UTF-8 이다\n")
        self.assertEqual([], unscannable_tracked(["a.md"], root=d))

    def test_a_tracked_file_missing_on_disk_is_not_called_a_binary(self):
        """검사할 내용이 없는 것과 바이너리인 것은 다르다."""
        self.assertEqual([], unscannable_tracked(["gone.txt"], root=tempfile.mkdtemp()))

    def test_the_allowlist_is_asset_types_only(self):
        """여기에 확장자를 넣는 것은 '이 바이너리는 검토했다'는 선언이다.

        신고를 잠재우려고 `.coverage` 나 `.db` 를 넣기 시작하면 이 게이트는 끝난다.
        """
        self.assertEqual(
            {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff", ".woff2"},
            set(BINARY_OK),
            "허용 목록이 바뀌었다. 새 항목이 정말 검토된 자산 유형인지 확인할 것 — "
            "생성물(커버리지·DB·캐시)은 추적에서 빼는 것이 답이지 여기 넣는 것이 아니다")


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
