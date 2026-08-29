"""스킬 문서가 선언한 것이 실제로 존재하는지 대조한다.

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
"""
import ast
import importlib.util
import os
import re
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SKILL_DOCS = [os.path.join(ROOT, "skills", "vibe-harness", "SKILL.md")]
_REFS = os.path.join(ROOT, "skills", "vibe-harness", "references")
if os.path.isdir(_REFS):
    SKILL_DOCS += [os.path.join(_REFS, f) for f in sorted(os.listdir(_REFS)) if f.endswith(".md")]

# 문서가 프로젝트 키 자리에 쓰는 표기들. 전부 같은 뜻이다.
KEY_PLACEHOLDERS = ("{project_key}", "{project}", "{key}", "{p}")


def doc_text():
    out = []
    for path in SKILL_DOCS:
        with open(path, encoding="utf-8") as fh:
            out.append((os.path.relpath(path, ROOT), fh.read()))
    return out


def load_module(name, filename):
    sys.path.insert(0, SCRIPTS)
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def argparse_options(filename):
    """소스를 파싱해 add_argument 로 선언된 이름을 모은다. import 부작용을 피한다."""
    with open(os.path.join(SCRIPTS, filename), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names.add(arg.value)
    return names


class DocumentedEndpointsAreRoutedTest(unittest.TestCase):
    """문서의 curl 예시가 서버에 실제로 닿는가."""

    ENDPOINT = re.compile(r"localhost:4242/api/([A-Za-z0-9{}_-]+)((?:/[A-Za-z0-9{}_.-]+)*)")

    def setUp(self):
        with open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8") as fh:
            self.server = fh.read()

    def documented(self):
        found = set()
        for path, text in doc_text():
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

    INVOCATION = re.compile(r"scripts/([a-z_]+\.py)((?:\s+--?[a-z][a-z-]*)*)")

    def invocations(self):
        seen = {}
        for path, text in doc_text():
            for script, flags in self.INVOCATION.findall(text):
                bucket = seen.setdefault(script, set())
                bucket.update(re.findall(r"--[a-z][a-z-]*", flags))
        return seen

    def test_documented_scripts_exist(self):
        missing = [s for s in sorted(self.invocations())
                   if not os.path.exists(os.path.join(SCRIPTS, s))]
        self.assertEqual([], missing, "문서가 부르는데 없는 스크립트: " + ", ".join(missing))

    def test_documented_flags_exist(self):
        problems = []
        for script, flags in sorted(self.invocations().items()):
            if not os.path.exists(os.path.join(SCRIPTS, script)):
                continue
            declared = argparse_options(script)
            for flag in sorted(flags):
                if flag not in declared:
                    problems.append(f"{script} {flag}")
        self.assertEqual([], problems,
                         "문서에 있는데 argparse 에 없는 플래그: " + ", ".join(problems))

    def test_extraction_found_something(self):
        self.assertIn("reconcile_runs.py", self.invocations(),
                      "스크립트 호출 추출이 깨졌다 — 문서 형식이 바뀌었는지 확인")


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


if __name__ == "__main__":
    unittest.main()
