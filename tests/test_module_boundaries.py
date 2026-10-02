"""모듈 경계 — 넘으면 실패한다.

`/vibe-aa` 의 산출물이다. 다이어그램이 아니라 **검사**여야 한다는 것이 그 스킬의 전제이고,
이 레포의 판단 기준("문서로 대응한 것은 대응이 아니다")과 같다.

## 정적 import 는 거짓말을 한다

2026-09-29 에 의존 그래프를 뽑았더니 깨끗했다 — `server` 가 둘에 의존하고 순환 없음.
**그런데 사실이 아니었다.** 이 레포는 `importlib.spec_from_file_location` 으로 동적
로드를 쓰고, `subprocess` 로 자기 스크립트를 부른다. AST 의 `import` 문만 세면 그 결합이
통째로 안 보인다.

    정적만:  kanban_edit → (없음)
    실제로:  kanban_edit ⇢ server        (importlib)
             enroll      ⇢ setup         (importlib)

그래서 이 검사는 **세 종류의 간선을 전부** 센다: `import` · `spec_from_file_location` ·
`subprocess`.

## 무엇을 강제하나 — 넷

문서에 이미 규정으로 적혀 있고 지금 지켜지고 있는 것만 고정한다. 새 규칙을 여기서
발명하지 않는다.

1. **순환 없음** — 동적 간선을 포함해서
2. **`vibe_runtime` 은 잎이다** — 지금 넷이 여기 의존한다. 이것이 무언가를 부르기
   시작하면 "모든 것이 의존하는 utils" 가 된다. `/vibe-aa` 가 이름 붙인 red flag 그대로다
3. **`setup` 은 로컬 의존이 없다** — 아무것도 설치되지 않은 새 머신에서 도는 설치
   스크립트다. 형제 모듈을 부르면 설치 자체가 깨진다
4. **수집(`reconcile_runs`)은 보드 서버에 의존하지 않는다** — "서버가 꺼져 있어도 정상"
   이 이 레포의 규정이다(`SKILL.md`, `kanban_edit` 독스트링). 수집이 서버를 필요로 하면
   그 규정이 조용히 깨진다

## 왜 방향만 보고 끊지 않나

`kanban_edit ⇢ server` 는 **의도된 재사용**이다 — id 발급과 상태 전이를 두 번 구현하면
갈라진다(실제로 갈라져서 `completed_at` 이 비는 사고가 났다). 그래서 이 간선은 금지하지
않는다. 금지하면 사람이 검사를 끄거나 구현을 복제한다.

**감지는 만들되 막지 않는다** 는 이 레포의 기준을 여기서도 지킨다 — 막는 것은 위 넷뿐이고,
나머지는 그래프를 출력해 보이기만 한다.
"""
import ast
import os
import re
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

# `spec_from_file_location(...)` / `subprocess.run([...])` 뒤쪽에서 스크립트 이름을 집는다.
_NEARBY = 220
_PYFILE = re.compile(r"""["']([a-z_]+\.py)["']""")
_DYNAMIC = re.compile(r"spec_from_file_location.{0,%d}" % _NEARBY, re.S)
_SUBPROC = re.compile(r"subprocess\.(?:run|Popen|check_output|call).{0,%d}" % _NEARBY, re.S)


def modules():
    return sorted(f[:-3] for f in os.listdir(SCRIPTS) if f.endswith(".py"))


def _source(name):
    with open(os.path.join(SCRIPTS, name + ".py"), encoding="utf-8") as fh:
        return fh.read()


def edges(name, local):
    """이 모듈이 실제로 기대는 것. 정적·동적·프로세스를 모두 센다."""
    src = _source(name)
    found = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    for pattern in (_DYNAMIC, _SUBPROC):
        for blob in pattern.finditer(src):
            for target in _PYFILE.findall(blob.group(0)):
                found.add(target[:-3])
    return (found & local) - {name}


def graph():
    local = set(modules())
    return {name: edges(name, local) for name in local}


class TheGraphIsAcyclicTest(unittest.TestCase):
    """동적 간선을 포함해서 순환이 없어야 한다."""

    def test_no_cycles(self):
        g = graph()
        cycles = set()
        seen = set()

        def walk(node, path):
            if node in path:
                cycles.add(tuple(sorted(set(path[path.index(node):] + [node]))))
                return
            if node in seen:
                return
            for nxt in sorted(g.get(node, ())):
                walk(nxt, path + [node])
            seen.add(node)

        for start in sorted(g):
            walk(start, [])

        self.assertEqual(set(), cycles,
                         "순환이 생기면 어느 쪽을 먼저 로드해도 반쪽이 된다")


class LeafStaysALeafTest(unittest.TestCase):
    """`vibe_runtime` 이 무언가를 부르기 시작하면 모든 것이 의존하는 utils 가 된다."""

    def test_vibe_runtime_depends_on_nothing_local(self):
        self.assertEqual(set(), graph()["vibe_runtime"],
                         "여기에 의존이 생기면 그 대상이 사실상 모든 모듈의 하위가 된다")

    def test_it_is_actually_depended_on(self):
        """전제 확인 — 아무도 안 쓰면 위 규칙은 의미가 없다."""
        g = graph()
        users = {m for m, deps in g.items() if "vibe_runtime" in deps}

        self.assertGreaterEqual(len(users), 2, "vibe_runtime 을 쓰는 곳이 없다")


class TheInstallerStandsAloneTest(unittest.TestCase):
    """`setup.py` 는 아무것도 설치되지 않은 머신에서 돈다."""

    def test_setup_has_no_local_dependency(self):
        self.assertEqual(set(), graph()["setup"],
                         "설치 스크립트가 형제 모듈을 부르면 새 머신에서 설치가 깨진다")

    def test_enroll_may_use_setup_not_the_other_way(self):
        """방향이 뒤집히면 위 규칙이 무너진다 — 한쪽만 허용한다."""
        g = graph()

        self.assertIn("setup", g["enroll"], "enroll 이 설치 목록의 정본을 읽어야 한다")
        self.assertNotIn("enroll", g["setup"])


class CollectionRunsWithoutTheServerTest(unittest.TestCase):
    """"서버가 꺼져 있어도 정상" 이 이 레포의 규정이다."""

    def test_reconcile_runs_does_not_need_the_server(self):
        self.assertNotIn("server", graph()["reconcile_runs"],
                         "수집이 보드 서버를 필요로 하면 규정이 조용히 깨진다")

    def test_search_does_not_need_the_server(self):
        self.assertNotIn("server", graph()["search"],
                         "검색도 서버 없이 도는 것이 규정이다")


class TheCheckActuallySeesDynamicEdgesTest(unittest.TestCase):
    """정적 import 만 보면 이 검사는 아무것도 못 잡는다.

    여기가 이 파일의 핵심이다. 아래가 깨지면 위의 네 규칙이 전부 헛돈다 —
    통과하지만 보지 않는 검사가 된다.
    """

    def test_it_finds_a_dynamic_edge(self):
        """`kanban_edit ⇢ server` 는 `import` 문에 없다. 그래도 잡혀야 한다."""
        self.assertIn("server", graph()["kanban_edit"],
                      "importlib 결합을 못 보면 이 검사는 정적 그래프의 거짓말을 그대로 믿는다")

    def test_the_dynamic_edge_is_not_a_plain_import(self):
        """전제 확인 — 정말로 `import` 문이 아니어야 위 테스트가 의미를 갖는다."""
        src = _source("kanban_edit")
        static = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    static.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                static.add(node.module.split(".")[0])

        self.assertNotIn("server", static,
                         "평범한 import 가 됐다면 이 테스트는 더 이상 동적 탐지를 증명하지 않는다")


class EveryModuleIsAccountedForTest(unittest.TestCase):
    """새 스크립트가 생기면 이 검사의 대상에 자동으로 들어온다."""

    def test_the_graph_covers_every_script(self):
        self.assertEqual(set(modules()), set(graph()))

    def test_there_are_modules_to_check(self):
        self.assertGreaterEqual(len(modules()), 8)


if __name__ == "__main__":
    unittest.main()
