"""테스트가 호스트에서 조용히 대받는 것을 고정한다.

## 왜 이 파일이 있는가

`init.defaultBranch` 가 이 머신에서는 `main`, CI 러너에서는 `master` 였다. 그래서
`git init` 뒤의 `checkout main` 이 CI 에서는 **원격 추적 브랜치를 새로 만들어버렸고**,
분기 상황 자체가 만들어지지 않아 두 테스트가 로컬에서만 통과했다. 초록이 두 곳에서
서로 다른 것을 검사하고 있었던 것이다.

**환경에 기대는 테스트는 환경이 다른 곳에서 조용히 다른 것을 검사한다.** 실패하면
차라리 낫다 — 통과하기 때문에 아무도 안 본다.

한 번 고쳤지만 고친 것은 그때 깨진 두 곳뿐이었다. 규율로 남기면 다음에 또 빠진다.

## 무엇을 검사하는가

`git init` 을 부를 때 브랜치 이름을 명시했는가. 문자열을 찾지 않고 **호출을 AST 로**
본다 — `-m "init"` 같은 것을 같이 잡으면 규칙이 곧 무시된다.

인코딩(암묵적 로케일)은 `test_windows_compat.py` 가 이미 본다. 여기서 겹쳐 보지 않는다.
"""
import ast
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")


def string_args(call):
    """호출에 실린 문자열 상수. 리스트로 넘긴 argv 도 펼친다.

    `subprocess.run(["git", "init", ...])` 와 `self.git(d, "init", ...)` 두 형태가
    모두 쓰인다. 한쪽만 보면 다른 쪽이 규칙 밖으로 샌다.
    """
    out = []
    for arg in list(call.args) + [k.value for k in call.keywords]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append(arg.value)
        elif isinstance(arg, (ast.List, ast.Tuple)):
            out += [e.value for e in arg.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return out


def callee_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def is_git_init(strings, callee=""):
    """`init` 이 git 의 하위 명령으로 쓰였는가.

    두 형태를 인정한다 — argv 에 `git` 이 있고 그 다음이 `init` 이거나,
    호출하는 함수 이름이 `git` 이고 첫 문자열이 `init` 이거나(헬퍼가 붙여주는 형태).

    **넓게 잡으면 규칙이 꺼진다.** 처음엔 "첫 문자열이 init"만 봤는데 그러면
    `strings.index("init")` 도 걸린다 — 이 파일 자신의 구현이 첫 위반으로 잡혔다.
    고칠 수 없는 위반이 목록에 남으면 다음 사람은 목록을 무시한다.
    커밋 메시지 `-m "init"` 도 같은 이유로 뺀다.
    """
    if "init" not in strings:
        return False
    i = strings.index("init")
    if i > 0:
        return strings[i - 1] == "git"
    return callee == "git"


def unpinned_git_inits():
    """브랜치 이름을 명시하지 않은 `git init` 호출 — (파일, 줄) 목록."""
    bad = []
    for name in sorted(os.listdir(TESTS)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(TESTS, name)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            strings = string_args(node)
            if is_git_init(strings, callee_name(node)) and "-b" not in strings:
                bad.append((name, node.lineno))
    return bad


class GitBranchNameIsNeverInheritedTest(unittest.TestCase):
    def test_every_git_init_names_its_branch(self):
        bad = unpinned_git_inits()
        self.assertEqual(
            [], bad,
            "브랜치 이름을 호스트의 init.defaultBranch 에 맡긴 곳: "
            + ", ".join("%s:%d" % b for b in bad)
            + " — `git init -b main` 으로 못 박을 것. 여기가 갈리면 두 환경이 "
              "서로 다른 것을 검사하면서 둘 다 초록이 된다")


class TheRuleItselfTest(unittest.TestCase):
    """항상 통과하는 검사는 검사가 아니다. 규칙이 무엇을 잡고 무엇을 안 잡는지 고정한다."""

    def parse_call(self, src):
        return ast.parse(src).body[0].value

    def matches(self, src):
        call = self.parse_call(src)
        return is_git_init(string_args(call), callee_name(call))

    def test_catches_a_bare_init(self):
        self.assertTrue(self.matches('subprocess.run(["git", "init", "-q"])'))

    def test_catches_the_helper_form(self):
        """헬퍼가 `git` 을 붙여주는 형태도 같은 규칙이다."""
        self.assertTrue(self.matches('self.git(d, "init", "-q", "-b", "main")'))

    def test_does_not_catch_a_commit_message_that_says_init(self):
        """이걸 같이 잡으면 고칠 수 없는 위반이 생기고, 그러면 규칙이 꺼진다."""
        self.assertFalse(self.matches('subprocess.run(["git", "commit", "-m", "init"])'))

    def test_does_not_catch_an_unrelated_call_whose_argument_is_init(self):
        """실제로 걸렸다 — 이 파일의 구현 자신이 첫 위반으로 잡혔다."""
        self.assertFalse(self.matches('strings.index("init")'))
        self.assertFalse(self.matches('cfg.get("init", None)'))

    def test_finds_something_to_look_at(self):
        """이 레포에 `git init` 을 부르는 테스트가 실제로 있다.

        없으면 위의 통과는 '검사할 것이 없었다'는 뜻이고, 그건 통과가 아니다.
        """
        seen = 0
        for name in os.listdir(TESTS):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(TESTS, name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            seen += sum(1 for n in ast.walk(tree)
                        if isinstance(n, ast.Call)
                        and is_git_init(string_args(n), callee_name(n)))
        self.assertGreaterEqual(seen, 3,
                                "git init 을 부르는 테스트를 못 찾았다 — 규칙이 헛돌고 있다")


if __name__ == "__main__":
    unittest.main()
