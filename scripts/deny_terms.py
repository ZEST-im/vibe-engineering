"""금칙 문자열 목록을 **손으로 적지 않고 파생시킨다.**

`tests/test_public_hygiene.py` 는 두 층으로 되어 있다 — 공개해도 안전한 **구조 규칙**
(CI 에서 항상 돈다)과, 값 자체를 보는 **정확 문자열** 층(`private/DENY.txt`, gitignore).
설계는 옳았다. 깨진 것은 그 목록을 **사람이 손으로 채운다**는 점이다.

2026-10-02 에 실제로 뚫렸다. 아키텍처 문서에 사내 프로젝트명 5종과 동료 실명 3인을
적었는데 게이트가 초록이었다. DENY.txt 에 17항목이 있었지만 **등록된 프로젝트 21개가
거기 없었다.** 구조 규칙은 모양만 보므로 프로젝트명 같은 평범한 식별자를 잡을 수 없고,
정확 문자열 층은 목록에 없는 것을 잡을 수 없다. 둘 다 제 일을 했고 그래도 샜다.

손으로 관리하는 목록은 갈라진다 — 이 레포는 설치 파일 목록이 세 군데로 갈려 머신 하나가
수집기 없이 남았던 사고를 이미 겪었다. 그래서 **목록을 사실에서 파생시킨다.**

## 재료는 전부 레포 밖에 있다

- **프로젝트 key** — `~/.claude/skills/vibe-harness/projects.json` (설치 디렉토리)
- **사람 이름** — 각 보드의 `created_by` / `assigned_to`

둘 다 공개 레포에 없으므로 *"금칙어 목록을 레포에 적으면 그 목록 자체가 유출"* 이라는
원래 설계가 그대로 유지된다. 이 파일에는 **값이 하나도 들어 있지 않다.**

## 어디서 도나

`scripts/check.py` 의 `deny-coverage` 단계. **테스트가 아니다** — 테스트는 실제
`~/.claude/` 를 건드리지 않는 것이 이 레포의 규칙이라 레지스트리를 읽을 수 없다.
그래서 읽는 쪽은 로컬 게이트가 맡고, 테스트는 아래 함수들의 **로직만** 픽스처로 검증한다.

CI 에는 레지스트리도 보드도 없으므로 이 단계는 거기서 돌지 않는다. `check.py` 가
「여기서 확인하지 못한 것」에 그 사실을 적는다 — **못 본 것과 깨끗한 것은 다르다.**
"""
import json
import os
import re


# 너무 짧거나 흔한 것은 금칙어로 쓸 수 없다. `qa`·`web` 같은 key 가 들어가면 모든
# 문서가 걸리고, 그러면 게이트는 꺼진다 — 규칙을 넓게 잡으면 규칙이 꺼진다.
MIN_TERM = 5

# 도구가 쓰는 말. 사람도 프로젝트도 아니다.
NEVER_DENY = frozenset({
    "claude", "codex", "gemini", "agent", "unknown", "none",
})

# **이 레포가 스스로 공개한 신원**은 금칙어가 될 수 없다.
#
# 손으로 적지 않고 레포의 신원 표면에서 뽑는다 — 원격 URL·`plugin.json`·`LICENSE`.
# 거기 적혀 있다는 것은 **이미 공개하기로 한 것**이라는 뜻이고, 그것을 금칙어로 두면
# README 와 LICENSE 부터 걸려서 게이트가 즉시 꺼진다.
#
# 처음에 손으로 적으려다 말았다. 작성자 이름 하나를 빠뜨리면 425건이 뜨고, 그 숫자를
# 본 사람은 규칙을 고치는 대신 게이트를 끈다.
IDENTITY_FILES = ("LICENSE", ".claude-plugin/plugin.json", "README.md")

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9._-]{3,}")


def self_identity(root, remote_url=""):
    """이 레포가 스스로 공개한 식별자. 금칙어 후보에서 뺀다.

    `README.md` 까지 포함하는 이유: 설치·설정 예시가 거기 있고, 그 예시에 쓰인 이름은
    이미 공개된 것이다. 새 유출을 README 에 적으면 이 함수가 그것도 공개로 쳐 버리는
    약점이 있다 — 그래서 **README 변경은 사람이 본다**는 전제에 기댄다. 전제를 적어
    둔다: 전제가 깨지면 이 게이트도 깨진다.
    """
    found = set()
    for token in _WORD.findall(remote_url or ""):
        found.add(token)
    for rel in IDENTITY_FILES:
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        found.update(_WORD.findall(text))
    return {t.lower() for t in found}


def _usable(term, public=frozenset()):
    term = (term or "").strip()
    if len(term) < MIN_TERM or term.lower() in NEVER_DENY:
        return ""
    if term.lower() in public:
        return ""
    # 공백이 들어간 값은 사람 이름이 아니라 설명문일 때가 많다. 한 토큰만 받는다.
    if re.search(r"\s", term):
        return ""
    return term


def terms_from_registry(registry, public=frozenset()):
    """등록된 프로젝트 key. `registry` 는 projects.json 을 읽은 dict 다."""
    if not isinstance(registry, dict):
        return []
    return sorted({t for t in (_usable(k, public) for k in registry) if t})


def terms_from_boards(boards, public=frozenset()):
    """보드에 적힌 사람 이름. `boards` 는 kanban dict 들의 iterable 이다.

    에이전트 이름(`claude`·`codex`)은 `NEVER_DENY` 가 걸러낸다 — 공개 문서에
    정상적으로 등장하는 말이고, 사람이 아니다.
    """
    found = set()
    for board in boards:
        if not isinstance(board, dict):
            continue
        for task in board.get("tasks", []) or []:
            if not isinstance(task, dict):
                continue
            for field in ("created_by", "assigned_to"):
                term = _usable(task.get(field), public)
                if term:
                    found.add(term)
    return sorted(found)


def offenders(terms, files):
    """금칙어가 들어 있는 줄. `files` 는 {경로: [줄, ...]}.

    `public-ok` 가 붙은 줄은 건너뛴다 — 구조 규칙 층과 같은 예외 표시를 쓴다.
    """
    hits = []
    for path in sorted(files):
        for n, line in enumerate(files[path], 1):
            if "public-ok" in line:
                continue
            for term in terms:
                if term in line:
                    hits.append((path, n, term, line.strip()[:110]))
                    break
    return hits


def load_registry(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def load_boards(registry):
    """레지스트리가 가리키는 각 보드의 kanban.json."""
    boards = []
    for entry in (registry or {}).values():
        kdir = entry.get("kanban_dir") if isinstance(entry, dict) else None
        if not kdir:
            continue
        try:
            with open(os.path.join(os.path.expanduser(kdir), "kanban.json"),
                      encoding="utf-8") as fh:
                boards.append(json.load(fh))
        except (OSError, ValueError):
            continue
    return boards


def derived_terms(registry_path, root=None, remote_url=""):
    """레지스트리 + 보드에서 금칙어를 뽑고, 자기 신원은 뺀다. 못 읽으면 빈 목록."""
    registry = load_registry(registry_path)
    if not registry:
        return []
    public = self_identity(root, remote_url) if root else frozenset()
    terms = set(terms_from_registry(registry, public))
    terms.update(terms_from_boards(load_boards(registry), public))
    return sorted(terms)
