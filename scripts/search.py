#!/usr/bin/env python3
"""search.py — 기록을 통째로 읽지 않고 찾는다. **검색의 정본 구현.**

## 왜 서버 밖으로 나왔나

1단계 검색은 `GET /api/{key}/search` 로만 됐다. 그런데 CLAUDE.md 는 **"서버가 꺼져
있어도 정상"** 이라고 규정하고, system of record 는 JSON 파일이다.
**정상이라고 규정한 상태에서 안 되는 기능**을 두는 것은 앞뒤가 안 맞는다.

그래서 여기가 정본이고 **서버가 이것을 부른다.** 반대가 아니다 — 구현이 둘이면
갈라지고, 갈라지면 한쪽만 코퍼스가 좁아져도 아무도 모른다. 이 레포는 같은 종류의
드리프트(설치 목록이 세 곳, status 리터럴이 네 곳)를 이미 두 번 겪었다.

## 코퍼스를 여기서 직접 읽는 것에 대해

`server.py` 의 `_read_kanban`/`_list_archives` 를 재사용하지 않고 여기서 읽는다.
둘 다 정규화 없는 순수 읽기라 갈라질 여지가 없고, 서버를 import 하면 순환이 된다
(서버가 이 파일을 부르므로).

**대신 "무엇을 코퍼스로 보는가"는 테스트로 고정한다** — 드리프트의 위험은 읽는
방식이 아니라 *보는 범위*에 있기 때문이다.

## 이 파일이 지키는 성질 (PMF10 에서 테스트로 고정된 것들)

- 응답이 코퍼스에 비례하지 않는다. 비례하면 검색이 아니라 그냥 읽기다
- 한 레코드는 한 번만. 필드 수만큼 반복하면 결과가 부풀어 목적이 사라진다
- 어디서 왔는지 함께. `source`·`id` 가 없으면 찾아도 열 수 없다
- 빈 질의는 거부한다. 전량 반환이 이 기능이 막으려던 것이다
- `total` 은 잘려도 진짜 수를 말한다. 실린 것만 세면 "전부 봤다"고 착각한다

    python3 scripts/search.py 이중 계상
    python3 scripts/search.py --limit 20 --json coverage
"""
import argparse
import json
import os
import sys


SNIPPET_CHARS = 160
DEFAULT_LIMIT = 10
MAX_LIMIT = 50

# 검색 대상 필드. 여기 없는 필드는 매칭돼도 스니펫을 못 만든다.
FIELDS = ("title", "description", "details", "why", "review")

# 코퍼스의 출처. **이 목록이 곧 "무엇을 찾을 수 있는가"** 이므로 테스트가 고정한다.
SOURCES = ("task", "archive", "decision", "doc", "commit")

# 마크다운만 본다. **소스코드는 넣지 않는다** — 비용이 아니라 희석 때문이다.
# grep 과 Explore 가 코드를 더 잘 찾고, 넣으면 코퍼스가 수십 MB 로 불어나면서
# 문서 히트가 코드 히트에 묻힌다. 그러면 "왜 그렇게 했더라"에 답하는 능력이 떨어진다.
DOC_SUFFIXES = (".md", ".mdx")

# 걸어 들어가지 않을 디렉토리. 생성물과 의존 트리는 문서가 아니다.
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "dist", "build",
             ".next", "__pycache__", ".check-venv", "vendor", "target",
             "coverage", ".pytest_cache", ".mypy_cache"}

# git 저장소가 아닐 때 걸어 들어갈 파일 수 상한.
#
# **추적 목록이 없으면 경계를 알 수 없다.** `kanban_dir` 이 예상 밖에 있으면
# (예: `~/vibe-harness`) 그 부모는 홈 디렉토리 전체이고, 그러면 검색이 온 집을 훑는다.
# 실제로 테스트에서 났다 — 픽스처가 공유 임시 디렉토리에 보드를 만들자 다른 테스트의
# 파일까지 코퍼스에 들어왔다.
#
# git 저장소면 `git ls-files` 가 경계를 알려주므로 이 상한이 필요 없다.
DOC_SCAN_CAP = 2000

# 한 문서에서 읽을 최대 바이트. 생성된 거대 마크다운(스키마 덤프 등) 하나가
# 코퍼스를 지배하는 것을 막는다.
DOC_MAX_BYTES = 512 * 1024

# 몇 개의 커밋까지 볼 것인가. 전량을 읽으면 오래된 저장소에서 I/O 가 커지는데,
# 검색이 답해야 할 "왜 그렇게 했더라"는 압도적으로 최근 쪽이다.
COMMIT_LIMIT = 2000

# ── 관측 ──────────────────────────────────────────────────────────────
#
# **캐시를 만들지 않기로 한 결정의 짝이다.**
#
# 가장 큰 프로젝트에서 질의당 ~200ms 이고, 이 도구는 사람이 타이핑하며 쓰는 것이
# 아니라 에이전트가 부르는 것이라 체감이 없다. 반면 캐시는 무효화가 틀리면
# **오래된 답을 조용히 돌려준다** — 검색에서는 틀린 답이 0건보다 알아채기 어렵다.
#
# 그래서 만들지 않되 **관측 가능하게** 한다. 느려지면 숫자가 먼저 말한다.
# 되돌릴 조건을 문서가 아니라 **실행되는 것**으로 둔다 — 이 레포의 규율이
# "문서로 대응한 것은 대응이 아니다" 이기 때문이다.
SLOW_MS = 500

# ── 순위 ──────────────────────────────────────────────────────────────
#
# 코퍼스를 넓히자 순위가 필수가 됐다. codebook_vibe 에서 "마이그레이션" 은
# **138건**이 걸리는데 10건만 실린다(확장 전에는 51건이었다). 정렬이 최신순뿐이면
# 찾던 것이 11번째일 때 못 찾고, `total` 이 정직하게 138이라 말해도 해결되지 않는다 —
# 볼 수 있는 건 10건이다.
#
# **BM25 를 쓰지 않는다.** 토큰 통계(IDF)를 미리 쌓아야 하고 그건 색인인데,
# 실측상 색인이 푸는 문제(스캔 속도)가 존재하지 않는다. 스캔은 초당 1.4 GB 다.
# 임베딩도 같은 이유로 기각 — 의존이 필요하고, 그게 PMF07 에서 qmd 를 반려한 이유다.
#
# 그래서 **설명할 수 있는 점수**를 쓴다. 틀렸을 때 왜 틀렸는지 알 수 있어야 고친다.
FIELD_WEIGHT = {"title": 6.0, "why": 3.0, "description": 2.0,
                "details": 1.0, "review": 1.0}
DEFAULT_FIELD_WEIGHT = 1.0

# 매치 횟수는 로그로 눌러 담는다. 100번 나온 문서가 10번 나온 문서보다 10배 관련 있진
# 않다. 그리고 긴 문서일수록 우연히 많이 걸리므로 길이로 한 번 더 눌러준다.
LENGTH_PIVOT = 4000.0


def repair_query(raw):
    """퍼센트 인코딩 없이 온 질의를 되살린다. (질의, 알림) 을 돌려준다.

    ## 무엇이 났던 일인가

        curl -G --data-urlencode "q=이중 계상"  → 6건
        curl "...?q=이중 계상"                  → {"query": "ì´ì¤", "total": 0}

    `http.server` 는 요청 라인을 **latin-1 로** 디코드한다(HTTP 규격이 그렇다). 퍼센트
    인코딩된 질의는 `parse_qs` 가 UTF-8 로 풀어주지만, 날 바이트로 온 것은 한 글자가
    바이트 수만큼의 latin-1 문자로 흩어진다. 그리고 **아무 말 없이 0건이 나온다.**

    PMF10 의 판단 기준에 적어둔 문장이 그대로 걸린 것이다 — "검색이 빈 결과를 내면
    검색기부터 의심한다." 검색기가 자기한테 그 말을 못 하고 있었다.

    ## 왜 이 판정이 안전한가

    되살릴 수 있을 때만 되살린다. latin-1 로 다시 인코딩해서 **UTF-8 로 읽히면** 그건
    원래 UTF-8 바이트였다는 뜻이다.

    `café` 처럼 정당한 latin-1 질의는 건드리지 않는다 — `b"caf\\xe9"` 는 유효한 UTF-8 이
    아니라 복구가 실패하고, 그러면 원본 그대로 간다. 코드포인트 범위만 봐서는 둘을
    가를 수 없다(퍼센트 인코딩으로 제대로 온 `café` 의 é 도 U+00E9 다).

    ## 400 을 내지 않는 이유

    계획서에는 "복구 못 하면 400" 이라고 적었는데, 구현하며 틀린 것을 알았다. 복구 실패는
    **정당한 latin-1 질의와 구별되지 않는다.** 400 을 내면 `café` 검색이 막힌다.
    조용하지 않게 만드는 것이 목적이었으므로, 되살리고 **되살렸다고 말하는** 것으로 답한다.
    """
    if not raw or all(ord(ch) < 128 for ch in raw):
        return raw, None
    try:
        fixed = raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw, None
    if fixed == raw:
        return raw, None
    return fixed, ("질의가 퍼센트 인코딩 없이 왔다 — %r 로 되살렸다. "
                   "`curl -G --data-urlencode` 를 쓰면 이 단계가 필요 없다" % fixed)


def snippet(text, needle, width=SNIPPET_CHARS):
    """매칭 지점 주변만 잘라낸다. 파일도 필드 전체도 아니다."""
    body = " ".join(str(text or "").split())
    at = body.lower().find(needle.lower())
    if at < 0:
        return None
    half = max(0, (width - len(needle)) // 2)
    start = max(0, at - half)
    end = min(len(body), at + len(needle) + half)
    return ("…" if start else "") + body[start:end] + ("…" if end < len(body) else "")


def score_record(rec, query, fields=FIELDS):
    """(점수, 근거). **근거를 함께 돌려주는 것이 이 함수의 절반이다.**

    이 레포는 출처를 함께 주는 것을 규율로 삼아왔다(`source`·`id`·`locator`).
    순위도 같아야 한다 — 왜 이게 위인지 말하지 못하면 틀렸을 때 고칠 수가 없다.

    셋을 곱하지 않고 더한다: 어느 필드에서 걸렸나(제목이 본문보다 무겁다),
    몇 번 걸렸나(로그로 누른다), 문서가 얼마나 긴가(길수록 우연이 섞인다).
    """
    import math
    q = str(query).lower()
    if not q:
        return 0.0, {}
    total_hits = 0
    length = 0
    parts = {}
    for field in fields:
        body = str(rec.get(field) or "")
        length += len(body)
        n = body.lower().count(q)
        if not n:
            continue
        total_hits += n
        weight = FIELD_WEIGHT.get(field, DEFAULT_FIELD_WEIGHT)
        parts[field] = {"hits": n, "weight": weight,
                        "points": round(weight * (1.0 + math.log(n)), 2)}
    if not parts:
        return 0.0, {}
    raw = sum(p["points"] for p in parts.values())
    # 긴 문서 보정. 짧은 결정 하나가 거대한 리뷰 문서에 묻히지 않게 한다.
    penalty = 1.0 / (1.0 + max(0, length - LENGTH_PIVOT) / LENGTH_PIVOT)
    return round(raw * penalty, 3), {
        "fields": parts,
        "total_hits": total_hits,
        "length": length,
        "length_factor": round(penalty, 3),
    }


def line_of(text, needle):
    """매칭이 몇 번째 줄인가 (1부터). 없으면 None.

    `snippet()` 은 공백을 접어버려 줄 정보를 잃는다. 문서 히트는 **열 수 있어야**
    의미가 있으므로 원문에서 따로 센다.
    """
    body = str(text or "")
    at = body.lower().find(str(needle).lower())
    if at < 0:
        return None
    return body.count("\n", 0, at) + 1


def locator_for(source, rec, query):
    """찾은 것을 여는 방법. 없으면 찾은 의미가 없다."""
    ident = rec.get("id")
    if source == "doc":
        line = line_of(rec.get("details"), query) or line_of(rec.get("title"), query)
        return "%s:%s" % (ident, line) if line else str(ident)
    if source == "commit":
        return "git show %s" % ident
    return "%s#%s" % (source, ident)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        # 깨진 파일 하나가 검색 전체를 못 죽이게 한다. 못 읽은 것은 안 나올 뿐이다.
        return None


def has_board(kanban_dir):
    """여기에 찾을 것이 있기는 한가.

    **"찾았는데 없다"와 "찾을 데가 없다"는 다르다.** 경로가 틀렸는데 `0건` 을 돌려주면
    "그런 기록은 없구나"로 읽히고, 그게 이 Phase 가 죽이려는 형태다.
    """
    return os.path.exists(os.path.join(kanban_dir or "", "kanban.json"))


def repo_root(kanban_dir):
    """`vibe-harness/` 의 부모. 문서와 커밋은 거기서 찾는다."""
    return os.path.dirname(os.path.abspath(kanban_dir or "."))


def _tracked_docs(root, runner=None):
    """git 이 추적하는 마크다운. 없으면 None (git 저장소가 아니거나 실패).

    **경계를 코드가 아니라 git 에게 묻는다.** `test_public_hygiene.py` 가 쓰는 것과
    같은 원칙이다. 무엇이 진짜 내용이고 무엇이 생성물인지는 프로젝트가 이미
    `.gitignore` 로 답해뒀다 — 그걸 다시 추측하면 프로젝트마다 틀린다.

    실제로 필요했다: e2e 픽스처(`test_temp/`)가 코퍼스에 섞여 들어왔다.
    """
    import subprocess
    runner = runner or subprocess.run
    if not os.path.isdir(os.path.join(root, ".git")):
        return None
    try:
        done = runner(["git", "--no-optional-locks", "-C", root, "ls-files", "-z"],
                      capture_output=True, text=True, timeout=30)
    except (OSError, ValueError):
        return None
    if getattr(done, "returncode", 1) != 0:
        return None
    return [p for p in (done.stdout or "").split("\0")
            if p and p.lower().endswith(DOC_SUFFIXES)]


def _walked_docs(root, cap=None):
    """추적 목록을 못 얻을 때의 대안. 생성물 디렉토리를 걸러내고 **상한을 둔다.**

    (경로들, 상한에 걸렸는가) 를 돌려준다. 경계를 모르는 채로 무한정 걸어 들어가면
    엉뚱한 디렉토리를 통째로 코퍼스에 넣게 된다.
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames)
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if name.lower().endswith(DOC_SUFFIXES):
                out.append(os.path.relpath(os.path.join(dirpath, name), root))
                if cap is not None and len(out) >= cap:
                    return out, True
    return out, False


def _doc_title(rel, body):
    """첫 제목 줄. 없으면 경로.

    경로를 제목으로 쓰면 목록에서 `docs/PROGRESS.md  docs/PROGRESS.md` 가 되어
    한 줄이 낭비된다. 문서는 대개 스스로 이름을 갖고 있다.
    """
    for line in body.split("\n", 40)[:40]:
        line = line.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading:
                return "%s — %s" % (rel, heading)
    return rel


def doc_records(root, max_bytes=DOC_MAX_BYTES, extra_dirs=("private",)):
    """프로젝트의 마크다운.

    실측이 이 결정의 근거다 — codebook_vibe 기준 JSON 547 KB 대 **마크다운 2,918 KB.**
    "왜 그렇게 했더라"의 답이 대부분 밖에 있었다.

    좌표는 파일 경로다. 줄 번호는 매칭 시점에 붙인다 — 여기서 미리 쪼개면 레코드가
    줄 수만큼 불어나고, "한 레코드는 한 번만" 이라는 성질이 깨진다.

    `private/` 는 추적되지 않지만 **일부러 포함한다.** 이 도구의 규약상 Phase 계획과
    결정 근거가 거기 사는데(CLAUDE.md), 그게 정확히 이 검색이 찾아야 할 것이다.
    검색은 로컬에서만 돌고 아무 데도 보내지 않으므로 공개 위험이 없다.
    """
    out = []
    if not root or not os.path.isdir(root):
        return out

    rels = _tracked_docs(root)
    if rels is None:
        # 경계를 모른다. 상한을 걸고, 걸렸으면 그 사실을 남긴다.
        rels, capped = _walked_docs(root, cap=DOC_SCAN_CAP)
        if capped:
            out.append(("doc", {
                "id": "(scan-capped)", "title": "(문서 스캔이 상한에 걸렸다)",
                "details": "", "updated_at": None, "_capped": True}))
    else:
        for extra in extra_dirs:
            base = os.path.join(root, extra)
            if os.path.isdir(base):
                more, _ = _walked_docs(base, cap=DOC_SCAN_CAP)
                rels += [os.path.join(extra, r) for r in more]

    for rel in sorted(set(rels)):
        full = os.path.join(root, rel)
        try:
            if os.path.getsize(full) > max_bytes:
                continue
            with open(full, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError:
            continue
        out.append(("doc", {
            "id": rel,
            "title": _doc_title(rel, body),
            "details": body,
            "updated_at": _mtime_iso(full),
        }))
    return out


def _mtime_iso(path):
    try:
        import datetime
        return datetime.datetime.fromtimestamp(
            os.path.getmtime(path)).isoformat(timespec="seconds")
    except (OSError, ValueError):
        return None


def commit_records(root, limit=COMMIT_LIMIT, runner=None):
    """커밋 메시지.

    **이 프로젝트는 설계 근거를 커밋 본문에 쌓아왔다** (이 레포 147 KB,
    codebook_vibe 619 KB). 문서만 넣고 커밋을 빼면 절반만 닿는다.

    좌표는 SHA 다 — `git show <sha>` 로 열 수 있어야 찾은 의미가 있다.
    """
    import subprocess
    runner = runner or subprocess.run
    if not root or not os.path.isdir(os.path.join(root, ".git")):
        return []
    sep = "\x1e"        # 레코드 구분자. 커밋 본문에 개행이 자유롭게 들어가므로
    try:
        done = runner(["git", "--no-optional-locks", "-C", root, "log",
                       "--max-count=%d" % limit,
                       "--format=%H%x1f%aI%x1f%s%x1f%b" + sep],
                      capture_output=True, text=True, timeout=60)
    except (OSError, Exception):        # noqa: B014 - subprocess 계열 전부
        return []
    if getattr(done, "returncode", 1) != 0:
        return []
    out = []
    for chunk in (done.stdout or "").split(sep):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 4:
            continue
        sha, when, subject, body = parts[0], parts[1], parts[2], parts[3]
        out.append(("commit", {
            "id": sha[:12],
            "title": subject,
            "details": body,
            "updated_at": when,
        }))
    return out


def records(kanban_dir, include_docs=True, include_commits=True, root=None):
    # noqa: D401
    """검색 대상. 어디서 왔는지(source)를 함께 들고 다닌다 — 없으면 찾아도 못 연다."""
    out = []
    board = _load_json(os.path.join(kanban_dir, "kanban.json")) or {}
    for task in board.get("tasks") or []:
        out.append(("task", task))

    adir = os.path.join(kanban_dir, "archive")
    if os.path.isdir(adir):
        for name in sorted(os.listdir(adir)):
            if name.endswith(".json"):
                doc = _load_json(os.path.join(adir, name)) or {}
                for task in doc.get("tasks") or []:
                    out.append(("archive", task))

    doc = _load_json(os.path.join(kanban_dir, "decisions.json")) or {}
    for dec in doc.get("decisions") or []:
        out.append(("decision", dec))

    where = root if root is not None else repo_root(kanban_dir)
    if include_docs:
        out.extend(doc_records(where))
    if include_commits:
        out.extend(commit_records(where))
    return out


def search(kanban_dir, query, limit=DEFAULT_LIMIT,
           include_docs=True, include_commits=True):
    """스니펫 검색. 한 레코드가 여러 필드에서 걸려도 **한 번만** 돌려준다.

    같은 태스크를 필드 수만큼 반복해 실으면 결과가 부풀어 검색의 목적이 사라진다.
    """
    q, repaired = repair_query(str(query or "").strip())
    if not q:
        return {"query": "", "hits": [], "total": 0,
                "note": "q 가 비었다 — 검색어 없이 부르면 전량을 돌려주게 되므로 거부한다"}
    try:
        limit = int(limit or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        # 쿼리스트링은 사용자 입력이다. 숫자가 아니면 500 이 아니라 기본값으로 떨어진다.
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    import time
    started = time.perf_counter()
    corpus = records(kanban_dir, include_docs=include_docs,
                     include_commits=include_commits)
    scanned_bytes = sum(len(str(rec.get(f) or ""))
                        for _src, rec in corpus for f in FIELDS)
    hits = []
    for source, rec in corpus:
        matched = []
        frag = None
        for field in FIELDS:
            piece = snippet(rec.get(field), q)
            if piece is None:
                continue
            matched.append(field)
            if frag is None:
                frag = piece
        if not matched:
            continue
        points, why = score_record(rec, q)
        hits.append({
            "score": points,
            "why_ranked": why,
            "source": source,
            "id": rec.get("id"),
            "title": rec.get("title"),
            "phase": rec.get("phase"),
            "date": rec.get("completed_at") or rec.get("updated_at") or rec.get("created_at"),
            "fields": matched,
            "locator": locator_for(source, rec, q),
            "snippet": frag,
        })

    # 점수가 먼저, **최근성은 동점 처리**다 — 작업 로그에서 최신은 실제로 좋은 신호라
    # 버리지 않는다. 날짜가 없는 레코드는 뒤로.
    hits.sort(key=lambda h: (h["score"], h.get("date") or ""), reverse=True)
    total = len(hits)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    out = {"query": q, "total": total, "hits": hits[:limit],
           "records_scanned": len(corpus),
           "scanned_bytes": scanned_bytes,
           "elapsed_ms": elapsed_ms}
    notes = []
    # 되돌릴 조건을 문서가 아니라 실행되는 것으로 둔다.
    if elapsed_ms > SLOW_MS:
        notes.append("%.0fms 걸렸다 (기준 %dms) — **캐시를 재검토할 시점이다.** "
                     "레코드 %d건 / %.0fKB 를 매 질의 다시 읽는다"
                     % (elapsed_ms, SLOW_MS, len(corpus), scanned_bytes / 1024))
    # 찾을 데가 없었던 것을 "없다"로 말하지 않는다.
    if not has_board(kanban_dir):
        notes.append("이 경로에 kanban.json 이 없다: %s — **0건은 '없다'가 아니라 "
                     "'안 찾았다'는 뜻이다.** 경로를 확인한다" % (kanban_dir or "(빈 경로)"))
    # 되살린 사실을 먼저 말한다. 조용히 고치면 다음에도 같은 방식으로 부른다.
    if repaired:
        notes.append(repaired)
    if total > limit:
        notes.append("%d건 중 %d건만 실었다. limit 로 늘리거나 검색어를 좁힌다"
                     % (total, limit))
    if notes:
        out["note"] = " / ".join(notes)
    return out


def find_kanban_dir(start=None):
    """`vibe-harness/` 를 위로 훑어 찾는다. 프로젝트 어디서든 부를 수 있게."""
    d = os.path.abspath(start or os.getcwd())
    for _ in range(8):
        candidate = os.path.join(d, "vibe-harness")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def render(out):
    lines = []
    if out["total"] == 0:
        lines.append("0건 — %r" % out["query"])
    for hit in out["hits"]:
        lines.append("%-9s %s" % (hit["source"], hit["title"] or ""))
        lines.append("          %s" % hit.get("locator"))
        if hit.get("snippet"):
            lines.append("               %s" % hit["snippet"])
    if out.get("note"):
        lines.append("\n· %s" % out["note"])
    # 캐시를 만들지 않기로 했으므로 비용을 매번 보여준다. 느려지면 숫자가 먼저 말한다.
    lines.append("\n%d건 / 레코드 %s개 %.0fKB / %.0fms"
                 % (out["total"], out.get("records_scanned", 0),
                    out.get("scanned_bytes", 0) / 1024, out.get("elapsed_ms", 0)))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="기록을 통째로 읽지 않고 찾는다")
    ap.add_argument("query", nargs="+", help="검색어")
    ap.add_argument("--dir", help="vibe-harness 디렉토리 (기본: 위로 훑어 찾는다)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--json", action="store_true", help="원본 JSON 으로 출력")
    a = ap.parse_args(argv)

    kanban_dir = a.dir or find_kanban_dir()
    if not kanban_dir:
        raise SystemExit("vibe-harness/ 를 찾지 못했다. --dir 로 지정한다.")
    if not has_board(kanban_dir):
        # 조용히 0건을 내면 "그런 기록은 없구나"로 읽힌다. 찾을 데가 없었을 뿐이다.
        raise SystemExit("kanban.json 이 없다: %s\n"
                         "  0건이 아니라 오류다 — 찾은 게 아니라 찾을 데가 없었다."
                         % kanban_dir)

    out = search(kanban_dir, " ".join(a.query), a.limit)
    print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else render(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
