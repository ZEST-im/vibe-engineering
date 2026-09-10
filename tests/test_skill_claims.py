"""공개 문서가 선언한 것이 실제로 존재하는지 대조한다.

W35 리뷰 P2, 2주 연속 지적: `tests/test_skills.py` 10개는 전부 **포장**을 본다 —
frontmatter, 참조 파일 존재, README 등재. 이 제품이 파는 것은 스크립트가 아니라 그 안의
판단 규칙인데, 규칙이 가리키는 대상이 실재하는지 보는 테스트가 없었다.

문서가 거짓말을 하는 방식은 두 가지다.

1. **없는 것을 있다고 한다** — 문서에 적힌 엔드포인트·플래그·경로가 코드에 없다.
   사용자는 문서대로 했는데 안 되고, 왜 안 되는지 알 방법이 없다.
2. **같은 것을 두 군데 적었다가 갈라진다** — 설치 파일 목록이 세 곳에 흩어져 있었고
   서로 달랐다. `setup.py` 만으로 설치한 머신에는 수집기가 없었다. 실제로 그 상태를
   만났고, "설치본 없음"으로 발견되기까지 며칠이 걸렸다.

여기서 검사하는 것은 전부 **기계적으로 확인 가능한 주장**이다. 산문은 대상이 아니다.

## PMF14 에서 넓힌 것 — 정문이 검사 밖이었다

이 파일은 만들어질 때 `SKILL.md` + `references/*.md` **6개만** 봤다. README 는 이 제품의
정문이고 가장 많이 읽히는 파일인데 범위 밖이었다. 그리고 두 종류의 주장은 **어느 문서에
대해서도** 검사되지 않았다:

- **설치 경로로 부르는 명령** — `~/.claude/skills/vibe-harness/server.py ...`.
  옛 추출 규칙은 `scripts/` 로 시작하는 것만 봤고, 문서의 그런 호출은 19건이다.
- **서브커맨드** — `server.py register`, `setup.py upgrade`, `kanban_edit.py add`.
  플래그는 봤지만 서브커맨드는 한 번도 안 봤다.

**넓히기 전에 쟀고 드리프트는 0 이었다** (엔드포인트·스크립트·플래그·서브커맨드·
설치 경로 전부). 그래서 이 검사의 근거는 "문서가 틀렸다"가 아니라 **"검사가 없으면
낡는다"** 이고, 그 주장은 이 레포가 이미 실증했다 — 넉 달 미체크였던 계획 문서의
유령 항목 49개, 세 곳으로 갈라진 설치 목록. 처음부터 통과하는 검사이므로
**채택 근거는 위반 주입뿐이다.**
"""
import ast
import functools
import importlib.util
import os
import re
import subprocess
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

# 문서가 프로젝트 키 자리에 쓰는 표기들. 전부 같은 뜻이다.
KEY_PLACEHOLDERS = ("{project_key}", "{project}", "{key}", "{p}")

# 문서가 설치본을 부를 때 쓰는 접두어. 종류마다 대조 대상이 다르다.
INSTALL_SKILL_PREFIX = "~/.claude/skills/vibe-harness/"
INSTALL_HOOKS_PREFIX = "~/.claude/hooks/"
PLUGIN_PREFIX = "${CLAUDE_PLUGIN_ROOT}/scripts/"


def public_docs():
    """검사 범위를 **git 에게 묻는다** — 추적되는 마크다운 전부.

    목록을 여기 적지 않는다. 적으면 공개 문서가 하나 늘 때 또 갈라지고, 이 파일 자신이
    6개만 적어둔 탓에 정문을 놓쳤다. `private/` 은 추적되지 않으므로 자동으로 범위
    밖이다 — 경계가 내 판단이 아니라 git 이 정한 것이고, 공개 위생 게이트가 쓰는 것과
    같은 경계다.

    git 이 없거나 실패하면 **멈춘다.** 조용히 빈 목록으로 떨어지면 이 파일의 검사
    전부가 항상 통과한다.
    """
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return [p for p in out.stdout.splitlines() if p.strip()]


@functools.lru_cache(maxsize=1)
def doc_text():
    out = []
    for rel in public_docs():
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            out.append((rel, fh.read()))
    return tuple(out)


def load_module(name, filename):
    sys.path.insert(0, SCRIPTS)
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# 문서에서 명령을 뽑는다
# --------------------------------------------------------------------------

def _logical_lines(text):
    r"""백슬래시로 이어진 셸 명령만 한 줄로 합친다. 그 외에는 줄을 넘지 않는다.

    옛 규칙은 파일 전체에서 `\s+` 로 이어 붙여, 산문에 적힌 `--flag` 가 몇 줄 위의
    스크립트 호출에 딸린 것처럼 읽혔다. 줄을 넘지 않으면 그 오탐이 사라지는데
    여러 줄로 쓴 실제 예시를 놓치므로, `\` 로 이어진 것만 명시적으로 합친다.
    """
    buf = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith("\\"):
            buf.append(line[:-1].rstrip())
            continue
        buf.append(line)
        yield " ".join(buf)
        buf = []
    if buf:
        yield " ".join(buf)


# URL 안의 `.../scripts/setup.py` 는 로컬 호출이 아니다. README 의 부트스트랩
# `curl -sL https://raw.githubusercontent.com/.../scripts/setup.py` 가 그 예다.
# **URL 은 이 검사의 대상이 아니다** — 확인하려면 네트워크를 타야 하고, 테스트가
# 네트워크를 타면 CI 가 남의 가용성에 묶인다. 대조하지 않는다는 것을 여기 적어둔다.
URL = re.compile(r"https?://\S+")


def _command_segments(text):
    """한 줄에 명령이 둘이면 뒤 명령의 플래그가 앞 스크립트에 붙는다. 끊어준다."""
    for logical in _logical_lines(text):
        for seg in re.split(r"&&|\|\||[;|]", URL.sub(" ", logical)):
            yield seg


# 경로 접두어(선택) + 스크립트 이름. 앞 글자가 단어·`.`·`-`·`/`·`~`·`$` 면 매치하지
# 않는다 — 그렇게 하지 않으면 `vibe-harness-record-run.py` 안에서 `run.py` 를 찾아낸다.
SCRIPT_CALL = re.compile(
    r"(?<![\w./~$-])((?:[~$]?[\w.${}/~-]*/)?)([a-z][a-z0-9_]*\.py)(?![\w.-])")

# 생략 표기가 든 경로는 **실재할 수 없다** — 문서가 "이런 자리의 파일"을 가리키는
# 자리표시자다(`~/.claude/skills/.../x.py`). `{project_key}` 를 자리표시자로 다루는 것과
# 같은 이유로 대조 대상이 아니다. 실제로 이 규칙이 없을 때 이 레포의 산문이 걸렸다.
PLACEHOLDER_PATH = ("...", "\u2026")

# 서브커맨드 자리에 올 수 있는 모양. 경로·변수·숫자·따옴표는 값이지 주장이 아니다.
SUBCOMMAND = re.compile(r"^[a-z][a-z0-9_-]*$")
FLAG = re.compile(r"--[a-z][a-z-]*")


@functools.lru_cache(maxsize=1)
def documented_invocations():
    """문서의 스크립트 호출을 `(경로종류, 이름) -> {flags, subcommands, docs}` 로.

    **경로 자체가 주장이다** — 문서가 `~/.claude/skills/...` 로 부르면 그 파일이 설치
    목록에 있어야 한다. 옛 규칙은 `scripts/` 만 봐서 설치 경로 호출이 통째로 검사
    밖이었다. 설치 목록이 갈라져 `reconcile_runs.py` 가 빠진 이력이 있는 레포에서
    가장 아픈 자리다.
    """
    found = {}
    for rel, text in doc_text():
        for seg in _command_segments(text):
            m = SCRIPT_CALL.search(seg)
            if not m:
                continue
            prefix, name = m.group(1), m.group(2)
            if any(mark in prefix for mark in PLACEHOLDER_PATH):
                continue
            rest = seg[m.end():]
            if prefix.startswith(INSTALL_SKILL_PREFIX):
                kind, key = "install", name
            elif prefix.startswith(INSTALL_HOOKS_PREFIX):
                kind, key = "hook", name
            elif prefix in ("", "./") or prefix.startswith(PLUGIN_PREFIX):
                kind, key = "scripts", name
            else:
                kind, key = "repo", prefix + name
            entry = found.setdefault((kind, key),
                                     {"flags": set(), "subcommands": set(), "docs": set()})
            entry["docs"].add(rel)
            entry["flags"].update(FLAG.findall(rest))
            toks = rest.split()
            if toks and SUBCOMMAND.match(toks[0]):
                entry["subcommands"].add(toks[0])
    return tuple(sorted((k, frozenset(v["flags"]), frozenset(v["subcommands"]),
                         frozenset(v["docs"])) for k, v in found.items()))


def source_path(kind, key):
    """문서가 부른 것에 대응하는 레포 안의 소스. 없으면 None."""
    if kind in ("install", "scripts"):
        return os.path.join(SCRIPTS, key)
    if kind == "hook":
        return os.path.join(SCRIPTS, "hooks", key)
    return os.path.join(ROOT, key)


# --------------------------------------------------------------------------
# 코드에서 선언을 뽑는다
# --------------------------------------------------------------------------

def _iter_constants(node):
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        vals = [e.value for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if len(vals) == len(node.elts):
            return vals
    return None


def _static_str(node, env):
    """정적으로 값이 정해지는 문자열이면 그 값, 아니면 None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_str(node.left, env)
        right = _static_str(node.right, env)
        return None if left is None or right is None else left + right
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "replace" and len(node.args) == 2):
        base = _static_str(node.func.value, env)
        old = _static_str(node.args[0], env)
        new = _static_str(node.args[1], env)
        if None not in (base, old, new):
            return base.replace(old, new)
    return None


def _walk_add_arguments(node, env, names, unresolved):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.For) and isinstance(child.target, ast.Name):
            values = _iter_constants(child.iter)
            if values is not None:
                for value in values:
                    inner = dict(env, **{child.target.id: value})
                    for stmt in child.body:
                        _walk_add_arguments(stmt, inner, names, unresolved)
                for stmt in child.orelse:
                    _walk_add_arguments(stmt, env, names, unresolved)
                continue
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                and child.func.attr == "add_argument"):
            for arg in child.args:
                value = _static_str(arg, env)
                if value is None:
                    unresolved.append(ast.dump(arg)[:90])
                else:
                    names.add(value)
        _walk_add_arguments(child, env, names, unresolved)


def argparse_options(path):
    """`add_argument` 로 선언된 이름. 읽을 수 없는 선언은 **가려내서 함께 돌려준다.**

    `kanban_edit.py` 는 `"--" + f.replace("_", "-")` 를 루프로 돈다. 그 형태를 못 읽으면
    **정상 문서를 위반이라고 부른다** — 검사가 정상을 위반이라 부르면 고쳐지는 건 데이터
    쪽이라 검사가 없는 것보다 나쁘다(`backlog` 를 다섯 번째 status 로 몰랐던 것과 같은
    종류의 실수다). 그래서 루프 상수를 대입해 정적으로 평가하고, 그래도 못 읽은 것이
    남으면 `unresolved` 로 돌려 **호출자가 침묵하지 못하게** 한다.
    """
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names, unresolved = set(), []
    _walk_add_arguments(tree, {}, names, unresolved)
    return names, unresolved


def declared_subcommands(path):
    """서브커맨드로 받아들이는 이름. argparse 서브파서와 `sys.argv[1]` 비교 둘 다.

    선언이 하나도 없으면 빈 집합이고, 그 스크립트의 첫 위치 인자는 **값**이다
    (`worker.py <project_key>`). 값을 서브커맨드 주장으로 읽으면 고칠 수 없는 위반이
    생기고, 고칠 수 없는 위반이 목록에 남으면 목록이 무시된다.
    """
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    def is_argv1(node):
        return (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute) and node.value.attr == "argv"
                and isinstance(node.slice, ast.Constant) and node.slice.value == 1)

    out = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_parser"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.add(arg.value)
        if isinstance(node, ast.Compare) and is_argv1(node.left):
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    out.add(comparator.value)
                for value in _iter_constants(comparator) or []:
                    out.add(value)
    return out


# --------------------------------------------------------------------------
# 검사
# --------------------------------------------------------------------------

class PublicDocScopeTest(unittest.TestCase):
    """범위가 조용히 줄어들면 아래 검사 전부가 조용히 통과한다."""

    def test_readme_is_in_scope(self):
        """정문이 빠져 있던 것이 이 Phase 의 발견이다. 다시 빠지지 않게 못 박는다."""
        self.assertIn("README.md", public_docs(),
                      "README 가 주장 검증 범위 밖이다 — 가장 많이 읽히는 파일이다")

    def test_skill_docs_are_still_in_scope(self):
        docs = public_docs()
        self.assertIn("skills/vibe-harness/SKILL.md", docs)
        self.assertIn("skills/vibe-harness/references/api.md", docs)

    def test_scope_is_wide_enough_to_be_real(self):
        """범위를 손으로 적던 시절이 6개였다. 추적 문서 전체는 그보다 훨씬 많다."""
        self.assertGreaterEqual(
            len(public_docs()), 15,
            "추적 마크다운이 15개 미만 — git ls-files 가 기대와 다르게 동작한다")

    def test_private_docs_are_out_of_scope(self):
        """`private/` 은 CI 에 없다. 범위에 들어오면 CI 와 로컬 결과가 갈라진다."""
        leaked = [p for p in public_docs() if p.startswith("private/")]
        self.assertEqual([], leaked, "추적되지 않아야 할 내부 문서가 범위에 들어왔다")


class DocumentedEndpointsAreRoutedTest(unittest.TestCase):
    """문서의 curl 예시가 서버에 실제로 닿는가."""

    ENDPOINT = re.compile(r"localhost:4242/api/([A-Za-z0-9{}_-]+)((?:/[A-Za-z0-9{}_.-]+)*)")

    def setUp(self):
        with open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8") as fh:
            self.server = fh.read()

    def documented(self):
        found = set()
        for _path, text in doc_text():
            for first, rest in self.ENDPOINT.findall(text):
                if first == "projects":
                    found.add(("projects",) + tuple(p for p in rest.split("/") if p))
                    continue
                segs = tuple(p for p in rest.split("/") if p)
                if segs:
                    found.add(segs)
        return found

    def routed(self, segs):
        """server.py 가 이 경로를 처리하는가. 동적 세그먼트는 위치로 판정한다."""
        if segs[0] == "projects":
            return '"/api/projects"' in self.server
        head = segs[0]
        if len(segs) == 1:
            return 'rest == ["%s"]' % head in self.server
        tail = segs[1]
        if tail.startswith("{"):
            # /tasks/{id} 류 — 길이와 첫 세그먼트로 라우팅된다
            return 'rest[0] == "%s"' % head in self.server
        return 'rest == ["%s", "%s"]' % (head, tail) in self.server

    def test_every_documented_endpoint_exists(self):
        missing = [segs for segs in sorted(self.documented()) if not self.routed(segs)]
        self.assertEqual(
            [], missing,
            "문서에 있는데 서버가 라우팅하지 않는 경로: "
            + ", ".join("/".join(s) for s in missing))

    def test_documented_set_is_not_empty(self):
        """추출 자체가 깨지면 위 테스트가 조용히 항상 통과한다."""
        self.assertGreaterEqual(len(self.documented()), 5,
                                "엔드포인트 추출이 거의 0건 — 정규식이 문서와 어긋났다")


class DocumentedScriptsAndFlagsTest(unittest.TestCase):
    """문서가 시키는 명령이 실제로 먹히는가."""

    def test_documented_scripts_exist(self):
        missing = []
        for (kind, key), _flags, _subs, docs in documented_invocations():
            path = source_path(kind, key)
            if not os.path.exists(path):
                missing.append("%s (%s) ← %s" % (key, kind, ", ".join(sorted(docs))))
        self.assertEqual([], missing, "문서가 부르는데 없는 스크립트: " + "; ".join(missing))

    def test_documented_flags_exist(self):
        problems = []
        for (kind, key), flags, _subs, _docs in documented_invocations():
            path = source_path(kind, key)
            if not flags or not os.path.exists(path):
                continue
            declared, _unresolved = argparse_options(path)
            problems += ["%s %s" % (key, f) for f in sorted(flags) if f not in declared]
        self.assertEqual([], problems,
                         "문서에 있는데 argparse 에 없는 플래그: " + ", ".join(problems))

    def test_flag_extraction_is_complete_for_documented_scripts(self):
        """읽지 못한 선언이 남으면 위 검사가 정상 문서를 위반이라 부르기 시작한다."""
        incomplete = []
        for (kind, key), flags, _subs, _docs in documented_invocations():
            path = source_path(kind, key)
            if not flags or not os.path.exists(path):
                continue
            _declared, unresolved = argparse_options(path)
            if unresolved:
                incomplete.append("%s: %s" % (key, unresolved[0]))
        self.assertEqual(
            [], incomplete,
            "플래그 선언을 정적으로 읽을 수 없는 스크립트가 문서에 있다 — "
            "_static_str 을 넓히지 않으면 정상 문서가 위반으로 잡힌다: " + "; ".join(incomplete))

    def test_extraction_found_something(self):
        names = {key for (_kind, key), _f, _s, _d in documented_invocations()}
        self.assertIn("reconcile_runs.py", names,
                      "스크립트 호출 추출이 깨졌다 — 문서 형식이 바뀌었는지 확인")

    def test_flags_are_attributed_to_the_right_script(self):
        """여러 줄로 쓴 예시의 플래그를 잡아야 한다 — `\\` 로 이어진 것.

        같은 스크립트가 경로 종류별로 따로 잡히므로(설치 경로 호출과 산문 언급) 이름으로
        합쳐서 본다. 하나로 덮으면 산문 쪽 빈 집합이 실제 호출을 지운다.
        """
        by_name = {}
        for (_kind, key), flags, _s, _d in documented_invocations():
            by_name.setdefault(key, set()).update(flags)
        self.assertIn("--project-root", by_name.get("worker.py", set()),
                      "백슬래시로 이어진 예시의 플래그를 놓쳤다")


class DocumentedSubcommandsTest(unittest.TestCase):
    """서브커맨드는 지금까지 어느 문서에 대해서도 검사되지 않았다.

    `server.py register` 가 사라지면 README 의 3단계가 그대로 안 먹는데, 플래그만 보던
    검사는 아무 말도 하지 않았다.
    """

    def claims(self):
        out = []
        for (kind, key), _flags, subs, docs in documented_invocations():
            path = source_path(kind, key)
            if not subs or not os.path.exists(path):
                continue
            declared = declared_subcommands(path)
            if not declared:
                # 서브커맨드를 선언하지 않는 스크립트의 첫 인자는 값이다
                continue
            out.append((key, subs, declared, docs))
        return out

    def test_documented_subcommands_exist(self):
        problems = []
        for key, subs, declared, docs in self.claims():
            for sub in sorted(subs):
                if sub not in declared:
                    problems.append("%s %s (선언: %s) ← %s"
                                    % (key, sub, sorted(declared), ", ".join(sorted(docs))))
        self.assertEqual([], problems,
                         "문서에 있는데 스크립트가 받지 않는 서브커맨드: " + "; ".join(problems))

    def test_subcommand_claims_were_actually_found(self):
        total = sum(len(subs) for _k, subs, _d, _docs in self.claims())
        self.assertGreaterEqual(
            total, 8, "서브커맨드 주장이 8건 미만 — 추출이 깨졌다. "
                      "register/serve/sync/configure-sync/upgrade/uninstall/add/set 는 문서에 있다")

    def test_value_positionals_are_not_read_as_subcommands(self):
        """`worker.py impactbook_ai` 의 프로젝트 키를 주장으로 읽으면 고칠 수 없는
        위반이 생기고, 고칠 수 없는 위반이 목록에 남으면 목록이 무시된다."""
        declared = declared_subcommands(os.path.join(SCRIPTS, "worker.py"))
        self.assertEqual(set(), declared,
                         "worker.py 가 서브커맨드를 선언하기 시작했다면 이 예외를 다시 볼 것")


class InstallPathClaimsTest(unittest.TestCase):
    """문서가 **설치 경로**로 부르는 파일은 설치 목록에 있어야 한다.

    이 레포는 설치 목록이 갈라져 `setup.py` 단독 설치가 `reconcile_runs.py` 를 빠뜨린
    이력이 있다. 그때는 목록끼리 대조해서 잡았고, 이번에는 **문서와 목록**을 대조한다 —
    문서가 있다고 한 경로에 파일이 없으면 사용자는 "No such file" 만 본다.
    """

    SKILL_CALL = re.compile(re.escape(INSTALL_SKILL_PREFIX) + r"([A-Za-z0-9_.-]+\.py)")
    HOOK_CALL = re.compile(re.escape(INSTALL_HOOKS_PREFIX) + r"([A-Za-z0-9_.-]+\.py)")

    def setUp(self):
        self.setup = load_module("setup_claims", "setup.py")

    def found(self, pattern):
        out = {}
        for rel, text in doc_text():
            for name in pattern.findall(text):
                out.setdefault(name, set()).add(rel)
        return out

    def test_install_path_calls_are_in_the_install_list(self):
        runtime = set(self.setup.SKILL_RUNTIME_FILES)
        missing = ["%s ← %s" % (n, ", ".join(sorted(d)))
                   for n, d in sorted(self.found(self.SKILL_CALL).items()) if n not in runtime]
        self.assertEqual(
            [], missing,
            "문서가 설치 경로로 부르는데 설치 목록에 없는 파일: " + "; ".join(missing)
            + " — 설치한 사용자는 'No such file' 만 본다")

    def test_hook_path_calls_are_in_the_helper_list(self):
        helpers = set(self.setup.HOOK_HELPERS)
        missing = ["%s ← %s" % (n, ", ".join(sorted(d)))
                   for n, d in sorted(self.found(self.HOOK_CALL).items()) if n not in helpers]
        self.assertEqual([], missing,
                         "문서가 훅 경로로 부르는데 헬퍼 목록에 없는 파일: " + "; ".join(missing))

    def test_install_path_claims_were_actually_found(self):
        self.assertGreaterEqual(
            len(self.found(self.SKILL_CALL)), 4,
            "설치 경로 호출이 4건 미만 — 추출이 깨졌다. README 와 SKILL.md 에 있다")


class InstallListsAgreeTest(unittest.TestCase):
    """같은 목록을 두 군데 적었다. 갈라지면 설치본에 파일이 빠진다.

    `setup.py` 가 정본(`SKILL_RUNTIME_FILES`)이고, `enroll.py --update-skill` 은
    그중 `setup.py` 자신만 **의도적으로** 뺀다 — 훅을 중복 등록한 이력이 있어 잠긴
    파일이고, 설치본에 최신을 두면 누군가 그걸 실행한다. 그 예외를 여기 고정해서,
    없애려면 테스트를 고치며 한 번 더 생각하게 한다.
    """

    EXCLUDED_FROM_UPDATE = {"setup.py"}

    def setUp(self):
        self.setup = load_module("setup_claims", "setup.py")
        self.enroll = load_module("enroll_claims", "enroll.py")
        self.enroll_names = {name for _src, name in self.enroll.SKILL_CODE_FILES}

    def test_runtime_files_exist_in_repo(self):
        missing = [f for f in self.setup.SKILL_RUNTIME_FILES
                   if not os.path.exists(os.path.join(SCRIPTS, f))]
        self.assertEqual([], missing, "정본 목록에 있는데 scripts/ 에 없는 파일: " + str(missing))

    def test_enroll_sources_exist_in_repo(self):
        missing = [src for src, _n in self.enroll.SKILL_CODE_FILES
                   if not os.path.exists(os.path.join(ROOT, src))]
        self.assertEqual([], missing, "enroll 목록에 있는데 레포에 없는 경로: " + str(missing))

    def test_update_skill_covers_every_runtime_file(self):
        expected = set(self.setup.SKILL_RUNTIME_FILES) - self.EXCLUDED_FROM_UPDATE
        gap = sorted(expected - self.enroll_names)
        self.assertEqual(
            [], gap,
            "setup.py 가 설치하는데 enroll --update-skill 이 갱신하지 않는 파일: "
            + ", ".join(gap) + " — 이 머신은 그 파일만 옛 버전으로 남는다")

    def test_excluded_file_stays_excluded(self):
        overlap = sorted(self.EXCLUDED_FROM_UPDATE & self.enroll_names)
        self.assertEqual(
            [], overlap,
            "의도적으로 제외한 파일이 enroll 목록에 들어왔다: " + ", ".join(overlap)
            + " — 정말 넣을 거라면 EXCLUDED_FROM_UPDATE 도 함께 고칠 것")

    def test_local_install_and_remote_upgrade_use_the_same_source(self):
        """두 경로가 각자 목록을 들면 다시 갈라진다. 상수 하나에서 파생돼야 한다.

        문자열 개수를 세면 표기만 바뀌어도 깨지므로, 함수 본문에서 이름을
        실제로 참조하는지를 AST 로 본다.
        """
        with open(os.path.join(SCRIPTS, "setup.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        users = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and any(isinstance(n, ast.Name) and n.id == "SKILL_RUNTIME_FILES"
                    for n in ast.walk(node))
        }
        for fn in ("copy_server_files", "upgrade"):
            self.assertIn(
                fn, users,
                f"{fn}() 이 SKILL_RUNTIME_FILES 를 쓰지 않는다 — 목록이 다시 갈라졌다")


class SiblingModulesAreInstalledTest(unittest.TestCase):
    """`server.py` 가 경로로 읽는 형제 모듈은 **설치 목록에 반드시 있어야 한다.**

    검색을 `search.py` 로 뽑으면서 서버가 그것을 부르게 됐다. 이제 그 파일이 없으면
    서버는 **import 조차 안 된다** — 기능 하나가 빠지는 게 아니라 보드 전체가 안 뜬다.

    이 레포는 같은 계열로 이미 한 번 당했다: 설치 목록이 세 곳에 흩어져
    `setup.py` 단독 설치가 `reconcile_runs.py` 를 빠뜨렸다. 그때는 조용한 결손이었고
    이번엔 즉사라 더 나쁘다.

    파일명을 여기 다시 적지 않는다. **소스에서 뽑아 대조한다** — 적으면 갈라진다.
    """

    def sibling_names(self):
        with open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        found = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_load_sibling"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and str(arg.value).endswith(".py"):
                        found.add(arg.value)
        return found

    def test_server_actually_loads_siblings(self):
        """이 검사가 무의미해지지 않게. 하나도 못 찾으면 대조할 것이 없다."""
        self.assertTrue(self.sibling_names(),
                        "_load_sibling 호출을 하나도 못 찾았다 — 이름이 바뀌었는지 확인")

    def test_every_sibling_is_in_the_install_list(self):
        with open(os.path.join(SCRIPTS, "setup.py"), encoding="utf-8") as fh:
            setup_src = fh.read()
        for name in sorted(self.sibling_names()):
            self.assertIn('"%s"' % name, setup_src,
                          "server.py 가 %s 를 읽는데 설치 목록에 없다 — "
                          "설치본에서 서버가 import 조차 안 된다" % name)

    def test_every_sibling_exists(self):
        for name in sorted(self.sibling_names()):
            self.assertTrue(os.path.exists(os.path.join(SCRIPTS, name)),
                            "server.py 가 없는 파일을 읽으려 한다: %s" % name)


if __name__ == "__main__":
    unittest.main()
