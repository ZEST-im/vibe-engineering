#!/usr/bin/env python3
"""
Vibe Engineering Server v5 — JSON-based Multi-project Kanban Board
Git-friendly: stores tasks as JSON files instead of SQLite.
One server (localhost:4242) serves multiple projects with tab-based switching.
"""

import json
import os
import sys
import signal
import hashlib
import threading
import getpass
try:
    import fcntl
except ImportError:
    # Windows has no fcntl. flock becomes a no-op — the atomic .tmp→os.replace
    # below is the real write guard, and this is a local single-user server.
    class _FcntlShim:
        LOCK_EX = LOCK_UN = 0
        def flock(self, *args, **kwargs):
            pass
    fcntl = _FcntlShim()
import re
import glob as glob_module
from datetime import datetime, timedelta, timezone

# 고정 오프셋이다. ZoneInfo("Asia/Seoul") 은 Windows 에서 tzdata 패키지 없이 죽는다 —
# 시스템 tz DB 가 없기 때문이다. 그리고 이 줄은 모듈 최상단이라 import 자체가 막혀
# 서버가 아예 뜨지 않았다. KST 는 DST 가 없으니 고정 오프셋으로 잃는 것이 없다.
# reconcile_runs.py 가 이미 같은 규율을 쓰고 있었는데 여기만 빠져 있었다.
KST = timezone(timedelta(hours=9))
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from urllib import request as urllib_request
from urllib import error as urllib_error

import subprocess
import traceback


def _load_sibling(name, filename):
    """같은 디렉토리의 모듈을 읽는다.

    `import search` 로 하지 않는 이유는 설치본 때문이다 — 스킬 디렉토리에 파일이
    평평하게 깔리고 `sys.path` 에 들어 있다는 보장이 없다. 경로로 읽으면 어디에
    설치돼도 같은 파일을 집는다.
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(name, os.path.join(here, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


from vibe_runtime import (
    approval_required, expires_at, load_policy, new_identity, parse_time,
    read_runtime, run_test_gate, runtime_lock, sanitized_runtime, utc_now,
    valid_token, write_runtime,
)

# Force UTF-8 console I/O so non-ASCII output (em-dash, Korean) survives on
# Windows cp949 terminals. No-op where reconfigure is unavailable/unneeded.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

SKILL_DIR = os.path.expanduser("~/.claude/skills/vibe-harness")
CONFIG_PATH = os.path.join(SKILL_DIR, "projects.json")
SYNC_CONFIG_PATH = os.environ.get(
    "VIBE_HARNESS_SYNC_CONFIG",
    os.path.join(SKILL_DIR, "sync.json"),
)
SYNC_PENDING_PATH = os.path.join(SKILL_DIR, "sync-pending.json")

USERS_CONFIG_PATH = os.environ.get(
    "VIBE_HARNESS_USERS_CONFIG",
    os.path.join(SKILL_DIR, "users.json"),
)

def _load_user_aliases():
    """Load the {alias: canonical} display-name map.

    Optional machine-local file — a missing or malformed users.json simply means
    "no aliases", so behaviour is unchanged for anyone who never configures one.
    """
    if not hasattr(_load_user_aliases, "_cache"):
        aliases = {}
        try:
            with open(USERS_CONFIG_PATH, encoding="utf-8") as f:
                raw = json.load(f).get("aliases", {})
            if isinstance(raw, dict):
                aliases = {
                    str(k).strip().lower(): str(v).strip()
                    for k, v in raw.items()
                    if str(k).strip() and str(v).strip()
                }
        except Exception:
            aliases = {}
        _load_user_aliases._cache = aliases
    return _load_user_aliases._cache

def _canon_user(name):
    """Map a display name onto its canonical form. Unknown names pass through."""
    n = (name or "").strip()
    if not n:
        return ""
    return _load_user_aliases().get(n.lower(), n)

def _git_user():
    """Get git user.name (canonicalized), cached after first call."""
    if not hasattr(_git_user, "_cache"):
        try:
            _git_user._cache = subprocess.check_output(
                ["git", "config", "user.name"], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            _git_user._cache = ""
    return _canon_user(_git_user._cache)

# ── Projects Registry ──────────────────────────────

def load_projects():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_projects(projects):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)

def register_project(key, name, kanban_dir):
    projects = load_projects()
    projects[key] = {"name": name, "kanban_dir": os.path.abspath(kanban_dir)}
    save_projects(projects)
    init_kanban(kanban_dir)
    return projects

# ── JSON Storage ───────────────────────────────────

def _now():
    # KST-aware ISO (e.g. 2026-07-13T09:00:00+09:00). datetime.now(KST) yields the
    # correct Seoul wall-clock on ANY host (local KST Mac or a UTC cloud runner), so
    # date buckets never drift a day just because a run was recorded off-KST.
    return datetime.now(KST).isoformat(timespec="seconds")


def _kst_ymd(ts):
    """KST calendar date (YYYY-MM-DD) for an ISO timestamp.
    tz-aware timestamps are converted to Asia/Seoul; naive legacy timestamps
    (ambiguous source tz — some are UTC cloud runs, some KST local) are taken
    as-is to avoid mis-shifting them the wrong way."""
    if not ts:
        return ""
    s = str(ts)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s[:10]
    if dt.tzinfo is not None:
        dt = dt.astimezone(KST)
    return dt.strftime("%Y-%m-%d")

def _kanban_path(kanban_dir):
    return os.path.join(kanban_dir, "kanban.json")

def _archive_dir(kanban_dir):
    return os.path.join(kanban_dir, "archive")

def init_kanban(kanban_dir):
    os.makedirs(kanban_dir, exist_ok=True)
    kp = _kanban_path(kanban_dir)
    if not os.path.exists(kp):
        _write_kanban(kanban_dir, {"version": 1, "next_id": 1, "tasks": []})

def _read_kanban(kanban_dir):
    kp = _kanban_path(kanban_dir)
    if not os.path.exists(kp):
        return {"version": 1, "next_id": 1, "tasks": []}
    with open(kp, encoding="utf-8") as f:
        data = json.load(f)
    if "next_id" not in data:
        nums = _numeric_ids(data.get("tasks"))
        data["next_id"] = (max(nums) + 1) if nums else 1
    return data

def _write_kanban(kanban_dir, data):
    kp = _kanban_path(kanban_dir)
    os.makedirs(kanban_dir, exist_ok=True)
    tmp = kp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, kp)
    _schedule_remote_sync(kanban_dir)

# 보드가 아는 status 는 이 다섯이 전부다. 세 군데에 같은 리터럴이 흩어져 있었고
# 데이터 불변식 검사는 그중 넷만 알고 있어, 서버 기본값(backlog)으로 만든 태스크를
# 위반으로 잡았다. 정본을 하나 두고 나머지가 파생한다.
BOARD_STATUSES = ("backlog", "todo", "in_progress", "review", "done")
DEFAULT_STATUS = "backlog"

PIPELINE_STATUS_PATH = os.path.join(SKILL_DIR, "pipeline-status.json")
# 수집은 3시간마다 돈다. 노트북이 밤새 잠들면 10시간쯤 비므로 그보다 넉넉히 잡는다.
# 실제 사고는 4일이었다 — 24시간이면 첫날에 잡힌다.
PIPELINE_STALE_HOURS = 24


def _pipeline_health(now=None):
    """수집 파이프라인이 살아 있는지.

    판단 기준은 "기록된 오류"가 아니라 **마지막 성공이 얼마나 오래됐나**다.
    실제로 겪은 고장 세 건은 전부 프로세스가 아예 돌지 않은 경우여서 오류를
    남길 주체가 없었다. 그래서 파일이 아예 없는 것도 stale 로 본다.
    """
    now = now or datetime.now(timezone.utc)
    try:
        with open(PIPELINE_STATUS_PATH, encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict):
            raise ValueError("not an object")
    except (FileNotFoundError, ValueError, OSError):
        return {"state": "unknown", "reason": "상태 파일 없음 — 수집이 한 번도 돌지 않았을 수 있다"}

    last = doc.get("last_success")
    try:
        seen = datetime.fromisoformat(str(last))
    except (TypeError, ValueError):
        return {"state": "stale", "last_success": None,
                "reason": "성공 기록이 없다", "last_error": doc.get("last_error")}
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    hours = (now - seen).total_seconds() / 3600.0
    out = {
        "last_success": last,
        "hours_since_success": round(hours, 1),
        "projects_done": doc.get("projects_done"),
        "last_error": doc.get("last_error"),
    }
    if hours > PIPELINE_STALE_HOURS:
        out["state"] = "stale"
        out["reason"] = ("마지막 수집 성공이 %.0f시간 전 — 3시간마다 돌아야 한다. "
                         "잡이 죽었는지 확인할 것" % hours)
    elif doc.get("last_error"):
        # 성공은 최근인데 그 뒤 시도가 실패했다. 이것을 ok 로 부르면
        # 정확히 이 장치가 잡으려는 "성공처럼 보이는 침묵"이 된다.
        out["state"] = "degraded"
        out["reason"] = "최근 성공은 있으나 그 이후 시도가 실패했다"
    else:
        out["state"] = "ok"
    return out


# 검색 엔지니어링 1단계 — 필요한 만큼만 값을 치른다.
#
# 아카이브를 도입해 세션 시작이 21,446 → 867 tok 이 됐는데, 싸진 이유가 **안 읽어서**다.
# 그 결과 아카이브가 닿을 수 없는 곳에 있다 — "왜 그렇게 했더라"를 물으면 답이 없거나
# 파일을 통째로 읽어야 한다. 절감의 다음 단계는 더 줄이는 게 아니라 안 읽으면서도
# 쓸 수 있게 만드는 것이다.
#
# 그래서 **파일이 아니라 스니펫을 돌려준다.** qmd 검토에서 가져온 유일한 원칙이다.
# 의존은 추가하지 않는다 — 몇 천 건짜리 JSON 에 검색 엔진은 과하고, npm 전역 설치가
# zero-dependencies 를 깬다. 이게 그때 qmd 를 반려한 이유였다.
# 검색은 `scripts/search.py` 가 정본이다. 여기서 다시 구현하지 않는다 —
# 서버가 꺼져 있어도 검색은 돼야 하고(CLAUDE.md 규정), 구현이 둘이면 갈라진다.
# 갈라지면 한쪽만 코퍼스가 좁아져도 아무도 모른다.
_SEARCH = _load_sibling("vh_search", "search.py")

SEARCH_SNIPPET_CHARS = _SEARCH.SNIPPET_CHARS
SEARCH_DEFAULT_LIMIT = _SEARCH.DEFAULT_LIMIT
SEARCH_MAX_LIMIT = _SEARCH.MAX_LIMIT
SEARCH_FIELDS = _SEARCH.FIELDS

repair_query = _SEARCH.repair_query
_snippet = _SEARCH.snippet
_search_records = _SEARCH.records
_search = _SEARCH.search


# 아카이브는 문서로 규정돼 있었다(qq 5단계, done 30건 또는 50KB 초과 시). 2주 뒤
# 다시 재보니 22개 중 4개가 다시 30건을 넘겼고 9개는 아카이브가 아예 없었다.
# **패턴이 재현됐다** — 그런데 그 사실은 "별도 스킬로 뽑자"가 아니라 "문서로는 안 된다"를
# 가리킨다. 스킬을 하나 더 만드는 것은 문서를 하나 더 만드는 것이다. 그래서 검사로 바꾼다.
ARCHIVE_HINT_DONE = 30
ARCHIVE_HINT_BYTES = 50 * 1024


def _archive_hint(kanban_dir, tasks):
    """hot 에 done 이 쌓였는지. 세션 시작에 말하지 않으면 아무도 알아채지 않는다."""
    done = sum(1 for t in tasks if t.get("status") == "done")
    try:
        size = os.path.getsize(_kanban_path(kanban_dir))
    except OSError:
        size = 0
    if done < ARCHIVE_HINT_DONE and size < ARCHIVE_HINT_BYTES:
        return None
    return {
        "done_in_hot": done,
        "bytes": size,
        "reason": ("완료 태스크 %d건(%.0fKB)이 kanban.json 에 남아 세션마다 읽힌다. "
                   "`/vibe-harness archive` 로 월별로 옮긴다" % (done, size / 1024)),
    }


# 칸반은 평면 목록이라 "이걸 하려면 저게 먼저"가 표현되지 않는다. 484건 중 22건이
# 그 관계를 제목·설명에 말로 적고 있었다 — 사람은 읽지만 보드는 모른다.
#
# 그래서 선택 필드 `depends_on: [id, ...]` 을 둔다. 핵심은 표현이 아니라 **구별**이다.
# 지금은 막힌 태스크와 지금 당장 할 수 있는 태스크가 보드에서 똑같아 보인다.
# 말로 적힌 선행관계를 **감지만** 한다. 자동으로 채우지 않는다.
#
# `depends_on` 은 PMF08 이 실측 근거로 만들었는데(당시 484건 중 22건이 선행관계를 말로
# 적고 있었다) **9일 뒤 사용 0건 / 2,141** 이었다. 진단은 맞았고 배선이 없었다.
# 사람이 기억해서 채우는 필드는 안 채워진다 — 그래서 감지를 붙인다.
#
# **넓게 잡지 않는다.** 넓은 규칙(선행|먼저|의존…)은 hot 511건 중 85건을 잡는데,
# 표본을 열어보니 대부분 의존이 아니라 서술이었다. 규칙을 넓게 잡으면 규칙이 꺼진다.
#
# 좁히는 근거 셋 (전부 실제 표본에서 나왔다):
#   1. **번호를 가리키지 않으면 링크를 만들 수 없다.** "마이그레이션 후에 배포"는
#      사람에게는 의존이지만 보드가 옮겨 담을 대상이 없다.
#   2. **번호가 태스크 id 로 실재해야 한다.** impactbook_ai 표본의 `#569`·`#570` 은
#      PR 번호였다. 검증 없이 제안하면 보드가 없는 의존을 말한다.
#   3. **"전례가 있어"는 의존이 아니다.** pante_bde #48 의 `#47 에서 … 틀렸던 전례가
#      있어` 가 그 형태다. 참조와 선행은 다르다.
#
# 결정 참조(`결정 #7`·`decisions #11`)는 **따로 분류한다** — 그건 선행관계가 아니라
# 결정↔태스크 링크가 말로 적힌 것이고, 그쪽은 역방향 조회의 재료다.
PROSE_DEP = re.compile(
    r"(?:(선행|선결|blocked by)\s*[:：]?\s*#(\d+))"
    r"|(?:#(\d+)\s*(?:을|를|이|가)?\s*(선행|선결))"
    r"|(?:#(\d+)\s*[^\n]{0,12}?(?:먼저|끝난 뒤|완료 후|이후에)\s)")
PROSE_DECISION = re.compile(r"(?:결정|decisions?)\s*#(\d+)")

# 선행조건이 지금 판단에 영향을 주는 상태들. done 의 선행조건은 이력이다.
DEPENDENCY_ACTIVE = ("backlog", "todo", "in_progress", "review")

# 백틱 안의 것은 **예시**다. 실제로 걸렸다 — 태스크 hg94 의 details 가 이 기능을
# 설명하며 `결정 #99` 를 예로 적었고, 그것이 유일한 `missing` 참조로 신고됐다.
# 코드로 감싼 참조는 "이렇게 쓴다"는 설명이고 "이걸 가리킨다"가 아니다.
CODE_SPAN = re.compile(r"`[^`\n]*`")


def _without_examples(text):
    """참조를 찾기 전에 코드 스팬을 지운다. 예시를 링크로 읽지 않게."""
    return CODE_SPAN.sub(" ", str(text or ""))

# `/context` 에 실을 표본 수. 총 건수는 `note` 가 말하므로 목록은 표본이면 된다.
PROSE_IN_CONTEXT = 5

# 번호를 안 가리키는 선행 서술. **`depends_on` 으로 옮길 수 없는 것들이다** —
# 표본의 절반이 이 형태였다: "G2B 수집 완료 후", "UI 병합 완료 후".
# 사람에게는 분명한 선행조건인데 가리키는 대상이 태스크가 아니다(활동·단계·외부 사건).
PROSE_PREREQ = re.compile(r"(선행|선결)\s*[:：]|blocked by|완료 후|끝난 뒤|이후에\s|(?<![가-힣])먼저\s")

# 이 말이 근처에 있으면 선행이 아니다. **전부 실제 표본에서 나온 오탐의 형태다.**
#   · "#47 에서 … 틀렸던 **전례**가 있어"        → 참조지 선행이 아니다
#   · "근접 **선행기술** 후보 제시"               → 특허 도메인 용어. 의존과 무관
#   · "다른 항목은 여기 **의존하지 않는다**"      → 부정문. 반대를 말한다
PROSE_NOT_DEP = re.compile(
    r"전례|사례|참고|예전|과거에|같은 형태|처럼"
    r"|선행기술|선행 기술"
    r"|의존하지\s*않|의존 없|영향\s*없")


def _prose_dependency_candidates(tasks, archived=()):
    """`depends_on` 이 비었는데 본문이 선행관계를 말하는 태스크.

    **제안만 한다.** 자동으로 채우면 오탐이 보드에 들어가고, 보드가 틀린 의존을
    말하는 것은 아무 말도 안 하는 것보다 나쁘다.
    """
    known = {str(t.get("id")) for t in list(tasks) + list(archived)
             if t.get("id") is not None}
    out = []
    for t in tasks:
        if t.get("depends_on"):
            continue
        blob = _without_examples(
            " ".join(str(t.get(f) or "") for f in ("title", "description", "details")))
        if not blob.strip():
            continue
        decisions = sorted({d for d in PROSE_DECISION.findall(blob)})
        # 결정 참조는 선행 후보에서 뺀다 — 같은 `#N` 이 양쪽에 잡히지 않게.
        without_decisions = PROSE_DECISION.sub(" ", blob)

        mentions = set()
        for match in PROSE_DEP.finditer(without_decisions):
            near = without_decisions[max(0, match.start() - 30):match.end() + 30]
            if PROSE_NOT_DEP.search(near):
                continue                      # 참조지 선행이 아니다
            for group in match.groups():
                if group and group.isdigit() and group in known:
                    mentions.add(group)

        prereq = None
        if not mentions:
            hit = PROSE_PREREQ.search(without_decisions)
            if hit:
                near = without_decisions[max(0, hit.start() - 40):hit.end() + 60]
                if not PROSE_NOT_DEP.search(near):
                    prereq = " ".join(near.split())

        if not (mentions or decisions or prereq):
            continue
        entry = {"id": t.get("id"), "title": t.get("title"),
                 "status": t.get("status")}
        if mentions:
            entry["suggests_depends_on"] = sorted(mentions, key=lambda x: int(x))
        if prereq:
            # 옮겨 담을 수 없다. **그래서 옮기라고 말하지 않는다** — 있다는 사실만 말한다.
            entry["prose_prerequisite"] = prereq
        if decisions:
            entry["mentions_decisions"] = decisions
        out.append(entry)
    return out


# 결정 본문이 태스크를 말로 가리키는 경우. `task_id` 가 비었을 때의 보조 경로다.
#
# **`#` 를 반드시 요구한다.** 처음엔 `#` 를 선택으로 뒀다가 실제 데이터에서 바로 틀렸다:
#   "결정→태스크 58% 로 연결은 이미 대부분 있다" → 백분율 58 을 태스크 58 로 읽었다.
# 번호 앞의 `#` 는 사람이 "이걸 가리킨다"고 표시한 것이다. 그 표시가 없는 숫자는
# 백분율·개수·연도일 수 있고, 검증 없이 이으면 **보드가 없는 링크를 말한다.**
DECISION_TASKREF = re.compile(r"(?:태스크|task)\s*#(\d+)|#(\d+)\s*(?:번)?\s*(?:태스크|task)")


def links_for_task(task_id, decisions, task_ids=()):
    """이 태스크를 다루는 결정들. **필드를 늘리지 않고 계산한다.**

    ## 왜 역방향 필드를 만들지 않는가

    지금은 결정 → 태스크 한 방향만 저장된다(`task_id`, 채워진 비율 58%). 태스크에서
    거꾸로 물으려면 결정 전체를 훑어야 한다 — 그래서 "역방향 링크 필드를 추가"가
    자연스러운 답처럼 보인다.

    **두 방향을 사람이 맞춰 쓰면 반드시 갈라진다.** 이 레포는 같은 종류의 드리프트를
    이미 두 번 겪었다(설치 목록이 세 곳, status 리터럴이 네 곳). 갈라진 링크는 없는
    링크보다 나쁘다 — 있다고 믿게 만든다.

    그리고 계산 비용이 이미 싸다. 결정은 프로젝트당 최대 68건이고, PMF12 실측에서
    2,600 레코드 전문 스캔이 180ms 였다.

    ## 말로 적힌 링크도 센다

    실측(2026-09-08, 22개 프로젝트): 저장된 `task_id` **133건**, 그 밖에 결정 본문이
    태스크를 말로 가리키는 것 **13건**, 태스크 본문이 결정을 말로 가리키는 것 **14건**.
    **말로 적힌 27건은 필드를 하나도 늘리지 않고 얻는다.**

    ## 어떻게 이어졌는지 함께 돌려준다

    `via` 가 없으면 틀렸을 때 어디를 고쳐야 하는지 모른다 — 검색의 `locator`·순위의
    `why_ranked` 와 같은 규율이다.
    """
    want = str(task_id)
    known = {str(t) for t in task_ids}
    out = []
    for dec in decisions or []:
        via = []
        if str(dec.get("task_id") or "") == want:
            via.append("task_id")
        else:
            blob = _without_examples(" ".join(str(dec.get(f) or "")
                                              for f in ("title", "why", "revisit")))
            for match in DECISION_TASKREF.finditer(blob):
                num = match.group(1) or match.group(2)
                # 실재하는 태스크 번호만. 검증 없이 이으면 없는 링크를 말한다.
                if num == want and (not known or num in known):
                    via.append("decision_text")
                    break
        if via:
            out.append({"id": dec.get("id"), "title": dec.get("title"),
                         "phase": dec.get("phase"), "via": via})
    return out


def task_link_report(task, decisions, task_ids=()):
    """한 태스크의 링크. 저장된 것과 말로 적힌 것을 **구별해서** 돌려준다."""
    tid = task.get("id")
    found = links_for_task(tid, decisions, task_ids)
    seen = {str(d["id"]) for d in found}

    # 태스크 본문이 결정을 가리키는 쪽. 반대 방향에서 못 찾은 것만 더한다.
    blob = _without_examples(" ".join(str(task.get(f) or "")
                                      for f in ("title", "description", "details")))
    by_id = {str(d.get("id")): d for d in decisions or []}
    for num in sorted(set(PROSE_DECISION.findall(blob)), key=lambda x: int(x)):
        if num in seen:
            for entry in found:
                if str(entry["id"]) == num and "task_text" not in entry["via"]:
                    entry["via"].append("task_text")
            continue
        dec = by_id.get(num)
        if dec is None:
            # 없는 결정을 가리킨다. **조용히 버리지 않는다** — 오타이거나 지워진 것이다.
            found.append({"id": num, "title": None, "via": ["task_text"],
                          "missing": True})
        else:
            found.append({"id": dec.get("id"), "title": dec.get("title"),
                          "phase": dec.get("phase"), "via": ["task_text"]})
    return {"task": tid, "decisions": found}


def _dependency_report(tasks, archived=()):
    """의존 관계를 훑어 막힌 것·없는 참조·순환을 돌려준다.

    아카이브된 태스크는 **완료로 친다.** 아카이브는 done 을 옮겨둔 것이므로,
    이걸 빼먹으면 오래된 프로젝트에서 멀쩡한 태스크가 전부 막힌 것으로 보인다.
    """
    done_ids, by_id = set(), {}
    for t in list(tasks) + list(archived):
        tid = t.get("id")
        if tid is None:
            continue
        by_id[str(tid)] = t
        if t.get("status") == "done":
            done_ids.add(str(tid))
    for t in archived:
        if t.get("id") is not None:
            done_ids.add(str(t["id"]))          # 아카이브 = 완료

    blocked, unknown = {}, {}
    edges = {}
    for t in tasks:
        tid = str(t.get("id"))
        deps = t.get("depends_on") or []
        if isinstance(deps, (str, int)):
            deps = [deps]
        edges[tid] = [str(d) for d in deps]
        missing = [str(d) for d in deps if str(d) not in by_id]
        if missing:
            unknown[tid] = missing
        unmet = [str(d) for d in deps
                 if str(d) in by_id and str(d) not in done_ids]
        if unmet and t.get("status") not in ("done",):
            blocked[tid] = unmet

    report = {
        "blocked": blocked,
        "unknown_refs": unknown,
        "cycles": _dependency_cycles(edges),
        "ready": sorted(
            str(t.get("id")) for t in tasks
            if t.get("status") in ("todo", "backlog") and str(t.get("id")) not in blocked
        ),
    }

    # ── "막힌 것 없음" 과 "의존 데이터가 없음" 은 다르다 ───────────────────
    #
    # PMF12 에서 검색이 같은 실수를 했다: 없는 경로를 가리켜도 `0건` 을 돌려줘서
    # "그런 기록은 없구나"로 읽혔다. 여기도 같다 — `blocked: {}` 는 "아무것도 막혀
    # 있지 않다"로 읽히는데, 실제로는 **아무도 의존을 선언하지 않았다**는 뜻일 수 있다.
    #
    # 실측(2026-09-07, 22개 프로젝트): `depends_on` 사용 **0 / 2,141**.
    # 그런데 활성 태스크 **28건**이 선행조건을 본문에 적고 있다. 그 상태에서
    # `blocked: {}` 를 내보내는 것은 침묵이 아니라 **거짓 신호**다.
    if not tasks:
        return report          # 빈 보드에는 오해할 것이 없다. 말을 걸지 않는다.
    declared = sum(1 for t in tasks if t.get("depends_on"))
    report["declared"] = declared
    # 완료된 태스크의 선행조건은 이력이다. 지금 판단에 쓰이는 것만 싣는다.
    candidates = [c for c in _prose_dependency_candidates(tasks, archived)
                  if c.get("status") in DEPENDENCY_ACTIVE]
    stated = [c for c in candidates if c.get("suggests_depends_on")
              or c.get("prose_prerequisite")]
    if not declared:
        # **짧게 쓴다.** 처음엔 문단으로 썼더니 이 문자열 하나가 프로젝트당 600 B 였고,
        # 22개 프로젝트에서 세션마다 값을 치른다. 이유는 SKILL.md 가 설명한다 —
        # 여기 필요한 것은 설명이 아니라 신호다.
        report["note"] = ("의존 미선언 — blocked/ready 는 '없음'이 아니라 '판단 불가'다"
                          + (" · 본문 선행조건 %d건" % len(stated) if stated else ""))
    if candidates:
        # **옮기라고 시키지 않는다.** 대부분은 옮길 수 없는 형태다 —
        # 실측에서 28건 중 depends_on 으로 표현 가능한 것은 1건뿐이었다.
        #
        # **본문 발췌를 여기 싣지 않는다.** 처음엔 실었더니 `/context` 가 프로젝트당
        # 최대 3,278 B(약 1,092 tok) 늘고 pante_bde 는 응답의 41% 가 이 항목이 됐다.
        # PMF10 이 세션 시작을 867 tok 으로 만든 것을 그대로 되돌리는 셈이다.
        #
        # 그래서 "어디에 있다"까지만 말한다. 문장이 필요하면 그때 찾는다 —
        # 검색(PMF12)이 있으니 그 비용이 이미 싸다. PMF10 규칙 3 과 같다:
        # 요약을 읽고, 근거가 실제로 문제될 때 원본을 연다.
        #
        # 목록도 5건까지다. `note` 가 이미 총 건수를 말하므로 목록은 "어떤 종류인지"를
        # 보이는 표본이면 된다. 20건까지 실었을 때 salpim-maru 는 1,890 B 였다.
        # 제목도 싣지 않는다. id 로 열 수 있고, 제목 5개가 300 B 다.
        report["stated_in_prose"] = [
            {k: v for k, v in c.items()
             if k not in ("prose_prerequisite", "title", "status")}
            | ({"prose": True} if c.get("prose_prerequisite") else {})
            for c in candidates[:PROSE_IN_CONTEXT]
        ]
        report["stated_in_prose_total"] = len(candidates)
    return report


def _dependency_cycles(edges):
    """순환을 찾는다. 순환이 있으면 어떤 순서로도 끝나지 않는데 보드는 조용하다."""
    seen, stack, found = set(), [], []

    def walk(node):
        if node in stack:
            cycle = stack[stack.index(node):] + [node]
            if cycle not in found:
                found.append(cycle)
            return
        if node in seen:
            return
        seen.add(node)
        stack.append(node)
        for nxt in edges.get(node, []):
            if nxt in edges:
                walk(nxt)
        stack.pop()

    for node in sorted(edges):
        walk(node)
    return found


# in_progress details 는 "지금 뭘 하고 있나"라 세션 시작에 실제로 필요하다. 그래서
# 일괄 절삭은 답이 아니다 — 필요한 것을 깎는 방향이다.
#
# 다만 규율(담당자당 1건)이 깨지면 이 자리가 무한정 커진다. 실측에서 한 프로젝트가
# in_progress 6건으로 /context 36KB 중 20,899B 를 차지했다.
#
# 그래서 예산제로 간다. 최근 착수한 것부터 details 를 온전히 싣고, 예산을 넘긴 나머지는
# digest 로 떨어뜨리되 **떨어졌다는 사실을 payload 에 남긴다.** 조용히 사라지면
# 이 레포가 반복해 온 실패와 같은 종류가 된다.
IN_PROGRESS_DETAIL_BUDGET = 4000


def _in_progress_payload(tasks):
    """최근 착수 순으로 예산만큼 원문, 나머지는 digest. 무엇이 줄었는지 함께 돌려준다."""
    ordered = sorted(
        tasks,
        key=lambda t: (t.get("started_at") or t.get("updated_at") or ""),
        reverse=True,
    )
    out, spent, trimmed = [], 0, 0
    for task in ordered:
        size = len(task.get("details") or "")
        if spent == 0 or spent + size <= IN_PROGRESS_DETAIL_BUDGET:
            out.append(task)          # 첫 건은 예산을 넘겨도 온전히 싣는다
            spent += size
        else:
            digest = _task_digest(task)
            digest["details_omitted_chars"] = size
            out.append(digest)
            trimmed += 1
    note = None
    if trimmed:
        note = ("in_progress %d건 중 %d건은 details 를 뺐다 (예산 %d자). "
                "개별 조회: /api/{key}/tasks/{id}" % (len(ordered), trimmed,
                                                     IN_PROGRESS_DETAIL_BUDGET))
    return out, note


def _task_digest(task):
    """세션 시작 컨텍스트용 요약. details 를 뺀 최소 필드만 남긴다.

    details 는 태스크당 수천 자라 컨텍스트 응답의 절반 이상을 차지했다.
    전문이 필요하면 개별 태스크를 조회한다 — 늘 필요한 것은 아니다.
    """
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "category": task.get("category"),
        "phase": task.get("phase"),
        "completed_at": task.get("completed_at"),
        "lines_added": task.get("lines_added"),
        "lines_removed": task.get("lines_removed"),
    }


def _list_archives(kanban_dir):
    """Load all archived tasks."""
    adir = _archive_dir(kanban_dir)
    if not os.path.isdir(adir):
        return []
    tasks = []
    for fname in sorted(os.listdir(adir)):
        if fname.endswith(".json"):
            with open(os.path.join(adir, fname), encoding="utf-8") as f:
                data = json.load(f)
                tasks.extend(data.get("tasks", []))
    return tasks

def _archive_tasks(kanban_dir, tasks_to_archive):
    """Move done tasks to monthly archive files."""
    if not tasks_to_archive:
        return
    adir = _archive_dir(kanban_dir)
    os.makedirs(adir, exist_ok=True)
    # Group by month
    by_month = {}
    for t in tasks_to_archive:
        completed = t.get("completed_at") or t.get("updated_at") or _now()
        month = completed[:7]  # YYYY-MM
        by_month.setdefault(month, []).append(t)
    for month, month_tasks in by_month.items():
        fpath = os.path.join(adir, f"{month}.json")
        existing = {"tasks": []}
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f:
                existing = json.load(f)
        existing_ids = {t["id"] for t in existing["tasks"]}
        for t in month_tasks:
            if t["id"] not in existing_ids:
                existing["tasks"].append(t)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

# ── 사람별 ID 접두어 ────────────────────────────────────────────────────────
# 여러 사람이 같은 kanban.json 을 각자 로컬에서 편집하면 next_id 가 각자 증가해
# **같은 번호가 서로 다른 태스크에 붙는다.** 2026-08-25 실제로 #427 이 겹쳤고,
# git 은 서로 다른 위치의 두 태스크를 조용히 둘 다 머지한다 — 에러 없이 하나가 사라진다.
# 접두어를 붙이면 구조적으로 겹칠 수 없다(hg918 / ar12 …).
#
# ⚠️ 이 도구는 20 개 프로젝트가 공용으로 쓴다. **접두어 미설정이 기본이고, 그때는
#    기존 정수 발급과 동작이 완전히 같다.** 기존 950여 건의 정수 id 는 손대지 않는다.
def _parse_id(raw):
    """URL 의 id 조각을 파싱한다. 숫자면 int, 아니면 문자열 그대로(접두어 id).

    ★ 예전에는 int(rest[1]) 이라 접두어 id 가 오면 ValueError 로 500 이 났다.
      기존 정수 id 는 int 로 유지해야 저장된 값과 == 비교가 맞는다.
    """
    raw = str(raw)
    try:
        return int(raw)
    except ValueError:
        return raw


def _id_prefix():
    """sync.json 의 id_prefix. 없으면 None → 기존 정수 발급."""
    try:
        cfg = _load_sync_config() or {}
        v = str(cfg.get("id_prefix", "")).strip()
        return v or None
    except Exception:
        return None


def _numeric_ids(items):
    """정수로 읽히는 id 만 추린다 — 접두어가 섞인 뒤에도 next_id 계산이 깨지지 않게."""
    out = []
    for it in items or []:
        try:
            out.append(int(it.get("id")))
        except (TypeError, ValueError):
            continue
    return out


def _mint_id(data, prefix=None):
    """(발급할 id, 다음 next_id) 를 돌려준다. 접두어가 있으면 문자열, 없으면 정수."""
    n = data.get("next_id", 1)
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 1
    # ★ next_id 가 실제 최대값보다 뒤처져 있으면 중복이 난다(파일을 손으로 고치면 실제로 그렇게 된다).
    #   발급 직전에 항상 실측 최대값과 맞춘다.
    used = _numeric_ids(data.get("tasks")) + _numeric_ids(data.get("decisions"))
    if used:
        n = max(n, max(used) + 1)
    return (f"{prefix}{n}" if prefix else n), n + 1


def _new_task(data, fields):
    """Create a new task, return (updated_data, new_task)."""
    now = _now()
    tid, _next = _mint_id(data, _id_prefix())
    task = {
        "id": tid,
        "title": fields.get("title", ""),
        "description": fields.get("description", ""),
        "details": fields.get("details", ""),
        "status": fields.get("status", DEFAULT_STATUS),
        "priority": fields.get("priority", "medium"),
        "category": fields.get("category", ""),
        "target_date": fields.get("target_date", ""),
        "started_at": fields.get("started_at", ""),
        "completed_at": fields.get("completed_at", ""),
        "lines_added": fields.get("lines_added", 0),
        "lines_removed": fields.get("lines_removed", 0),
        "tokens_used": fields.get("tokens_used", 0),
        "created_at": now,
        "updated_at": now,
        "position": fields.get("position") or 0,
        "phase": fields.get("phase", ""),
        "review": fields.get("review", ""),
        "created_by": _canon_user(fields.get("created_by", "")) or _git_user(),
        "assigned_to": _canon_user(fields.get("assigned_to", "")),
    }
    data["tasks"].append(task)
    data["next_id"] = _next
    return data, task

TASK_FIELDS = ("title", "description", "details", "status", "priority", "category",
               "target_date", "started_at", "completed_at", "lines_added", "lines_removed",
               "tokens_used", "position", "phase", "review", "created_by", "assigned_to",
               "execution_managed", "active_run_id", "last_run_id", "execution_attempts")

def _update_task(task, fields):
    """Update task fields in place."""
    now = _now()
    for k in TASK_FIELDS:
        if k in fields:
            task[k] = fields[k]
    for k in ("created_by", "assigned_to"):
        if k in fields:
            task[k] = _canon_user(task.get(k))
    # Auto-set timestamps and user
    if "status" in fields:
        if fields["status"] == "in_progress":
            if not task.get("started_at"):
                task["started_at"] = now
            if not task.get("assigned_to"):
                task["assigned_to"] = _git_user()
        if fields["status"] == "done" and "completed_at" not in fields:
            task["completed_at"] = now
    task["updated_at"] = now
    return task

# ── Schema Parsing ─────────────────────────────────

def _find_schema_files(kanban_dir):
    """Find schema definition files in the project directory."""
    project_dir = os.path.dirname(os.path.abspath(kanban_dir))
    files = []
    base_patterns = [
        "db/schema.rb", "db/*_schema.rb", "db/structure.sql", "prisma/schema.prisma",
        "schema.prisma", "db/migrations/*.sql", "db/migrate/*.rb",
        "migrations/*.sql", "schema.sql", "sql/*.sql",
    ]
    # Search at project root and one level deeper (e.g., rails_app/db/schema.rb)
    for depth_prefix in ["", "*/", "*/*/"]:
        for pattern in base_patterns:
            for f in sorted(glob_module.glob(os.path.join(project_dir, depth_prefix + pattern))):
                if os.path.isfile(f) and f not in files:
                    files.append(f)
    return files, project_dir

def _split_ddl(body):
    """Split DDL body by commas, respecting parentheses."""
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == '(':
            depth += 1; cur.append(ch)
        elif ch == ')':
            depth -= 1; cur.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(cur)); cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append(''.join(cur))
    return parts

def _parse_column(s):
    """Parse a single SQL column definition."""
    s = s.strip()
    if not s:
        return None
    upper = s.upper().lstrip()
    if any(upper.startswith(kw) for kw in ('CONSTRAINT', 'PRIMARY', 'FOREIGN', 'UNIQUE', 'CHECK', 'EXCLUDE', 'LIKE ')):
        return None
    name_m = re.match(r'"?(\w+)"?\s+', s)
    if not name_m:
        return None
    name = name_m.group(1)
    rest = s[name_m.end():]
    # Extract type: everything until a constraint keyword
    ckw = r'\b(?:NOT\s+NULL|NULL|DEFAULT|PRIMARY\s+KEY|UNIQUE|REFERENCES|CHECK|CONSTRAINT|GENERATED|COLLATE)\b'
    type_end = re.search(ckw, rest, re.IGNORECASE)
    if type_end:
        col_type = rest[:type_end.start()].strip()
        cpart = rest[type_end.start():]
    else:
        col_type = rest.strip()
        cpart = ''
    col_type = col_type.rstrip(',').strip()
    col = {'name': name, 'type': col_type.upper() if col_type else '', 'pk': False,
           'fk': None, 'nullable': True, 'unique': False, 'default': None}
    cu = cpart.upper()
    if 'PRIMARY KEY' in cu:
        col['pk'] = True; col['nullable'] = False
    if 'NOT NULL' in cu:
        col['nullable'] = False
    if re.search(r'\bUNIQUE\b', cu):
        col['unique'] = True
    def_m = re.search(r"DEFAULT\s+('(?:[^'\\]|\\.)*'|\S+(?:\([^)]*\))?)", cpart, re.IGNORECASE)
    if def_m:
        col['default'] = def_m.group(1)
    ref_m = re.search(r'REFERENCES\s+"?(\w+)"?\s*\("?([^)"]+)"?\)', cpart, re.IGNORECASE)
    if ref_m:
        col['fk'] = f"{ref_m.group(1)}({ref_m.group(2).strip()})"
        col['_inline_ref'] = (ref_m.group(1), ref_m.group(2).strip())
    if col['type'] in ('SERIAL', 'BIGSERIAL', 'SMALLSERIAL'):
        col['nullable'] = False
    return col

def _parse_sql_schema(content):
    """Parse SQL DDL into structured schema."""
    tables, relationships = {}, []
    content = re.sub(r'--[^\n]*', '', content)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    # CREATE TABLE
    for m in re.finditer(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:"?(\w+)"?\.)?\"?(\w+)\"?\s*\((.*?)\)\s*;',
        content, re.DOTALL | re.IGNORECASE
    ):
        schema_name, table_name, body = m.group(1) or '', m.group(2), m.group(3)
        columns, constraints = [], []
        for part in _split_ddl(body):
            part = part.strip()
            if not part:
                continue
            up = part.upper().lstrip()
            if any(up.startswith(kw) for kw in ('CONSTRAINT', 'PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE(', 'UNIQUE (', 'CHECK', 'EXCLUDE')):
                constraints.append(part)
            else:
                col = _parse_column(part)
                if col:
                    columns.append(col)
        indexes = []
        for tc in constraints:
            pk_m = re.search(r'PRIMARY\s+KEY\s*\(([^)]+)\)', tc, re.IGNORECASE)
            if pk_m:
                for cn in [c.strip().strip('"') for c in pk_m.group(1).split(',')]:
                    for col in columns:
                        if col['name'] == cn:
                            col['pk'] = True; col['nullable'] = False
            fk_m = re.search(r'FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+"?(?:\w+\.)?"?(\w+)"?\s*\(([^)]+)\)', tc, re.IGNORECASE)
            if fk_m:
                fk_cols = [c.strip().strip('"') for c in fk_m.group(1).split(',')]
                ref_table = fk_m.group(2)
                ref_cols = [c.strip().strip('"') for c in fk_m.group(3).split(',')]
                for i, fc in enumerate(fk_cols):
                    rc = ref_cols[i] if i < len(ref_cols) else ref_cols[0]
                    for col in columns:
                        if col['name'] == fc:
                            col['fk'] = f"{ref_table}({rc})"
                    relationships.append({'from_table': table_name, 'from_column': fc, 'to_table': ref_table, 'to_column': rc})
            uq_m = re.search(r'UNIQUE\s*\(([^)]+)\)', tc, re.IGNORECASE)
            if uq_m:
                uq_cols = [c.strip().strip('"') for c in uq_m.group(1).split(',')]
                if len(uq_cols) == 1:
                    for col in columns:
                        if col['name'] == uq_cols[0]:
                            col['unique'] = True
                else:
                    nm = re.search(r'CONSTRAINT\s+"?(\w+)"?', tc, re.IGNORECASE)
                    indexes.append({'name': nm.group(1) if nm else f"uq_{'_'.join(uq_cols)}", 'columns': uq_cols, 'unique': True})
        # Collect inline REFERENCES as relationships
        for col in columns:
            iref = col.pop('_inline_ref', None)
            if iref:
                relationships.append({'from_table': table_name, 'from_column': col['name'], 'to_table': iref[0], 'to_column': iref[1]})
        tables[table_name] = {'name': table_name, 'schema': schema_name, 'columns': columns, 'indexes': indexes}
    # CREATE INDEX
    for m in re.finditer(
        r'CREATE\s+(UNIQUE\s+)?INDEX\s+(?:(?:IF\s+NOT\s+EXISTS|CONCURRENTLY)\s+)?\"?(\w+)\"?\s+ON\s+\"?(?:\w+\.)?(\w+)\"?\s*(?:USING\s+\w+\s*)?\(([^)]+)\)',
        content, re.IGNORECASE
    ):
        is_uq, idx_name, tname = bool(m.group(1)), m.group(2), m.group(3)
        idx_cols = [c.strip().strip('"').split()[0] for c in m.group(4).split(',')]
        if tname in tables:
            tables[tname]['indexes'].append({'name': idx_name, 'columns': idx_cols, 'unique': is_uq})
    # ALTER TABLE ADD CONSTRAINT FK
    for m in re.finditer(
        r'ALTER\s+TABLE\s+(?:ONLY\s+)?\"?(?:\w+\.)?(\w+)\"?\s+ADD\s+CONSTRAINT\s+\"?(\w+)\"?\s+FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+\"?(?:\w+\.)?(\w+)\"?\s*\(([^)]+)\)',
        content, re.IGNORECASE
    ):
        tname, _, fk_str, ref_table, ref_str = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        for i, fc in enumerate([c.strip().strip('"') for c in fk_str.split(',')]):
            rcs = [c.strip().strip('"') for c in ref_str.split(',')]
            rc = rcs[i] if i < len(rcs) else rcs[0]
            if tname in tables:
                for col in tables[tname]['columns']:
                    if col['name'] == fc:
                        col['fk'] = f"{ref_table}({rc})"
            relationships.append({'from_table': tname, 'from_column': fc, 'to_table': ref_table, 'to_column': rc})
    # ALTER TABLE ADD CONSTRAINT UNIQUE
    for m in re.finditer(
        r'ALTER\s+TABLE\s+(?:ONLY\s+)?\"?(?:\w+\.)?(\w+)\"?\s+ADD\s+CONSTRAINT\s+\"?(\w+)\"?\s+UNIQUE\s*\(([^)]+)\)',
        content, re.IGNORECASE
    ):
        tname, cname = m.group(1), m.group(2)
        uq_cols = [c.strip().strip('"') for c in m.group(3).split(',')]
        if tname in tables:
            if len(uq_cols) == 1:
                for col in tables[tname]['columns']:
                    if col['name'] == uq_cols[0]:
                        col['unique'] = True
            else:
                tables[tname]['indexes'].append({'name': cname, 'columns': uq_cols, 'unique': True})
    return list(tables.values()), relationships

def _parse_schema_rb(content):
    """Parse Rails schema.rb."""
    tables, relationships = {}, []
    current = None
    for line in content.split('\n'):
        line = line.strip()
        m = re.match(r'create_table\s+"(\w+)"(.*)', line)
        if m:
            current = m.group(1)
            opts = m.group(2)
            cols = []
            if 'id: false' not in opts:
                pk_type = 'BIGINT'
                pk_m = re.search(r'primary_key:\s*:(\w+)', opts)
                if pk_m and pk_m.group(1).lower() == 'uuid':
                    pk_type = 'UUID'
                cols.append({'name': 'id', 'type': pk_type, 'pk': True, 'fk': None, 'nullable': False, 'unique': False, 'default': None})
            tables[current] = {'name': current, 'schema': '', 'columns': cols, 'indexes': []}
            continue
        if line == 'end':
            current = None
            continue
        if not current or current not in tables:
            continue
        col_m = re.match(r't\.(\w+)\s+"(\w+)"(.*)', line)
        if col_m:
            rb_type, col_name, opts = col_m.group(1), col_m.group(2), col_m.group(3)
            tmap = {'string': 'VARCHAR', 'text': 'TEXT', 'integer': 'INTEGER', 'bigint': 'BIGINT',
                    'float': 'FLOAT', 'decimal': 'DECIMAL', 'boolean': 'BOOLEAN', 'datetime': 'TIMESTAMP',
                    'date': 'DATE', 'time': 'TIME', 'binary': 'BYTEA', 'jsonb': 'JSONB', 'json': 'JSON',
                    'uuid': 'UUID', 'inet': 'INET', 'references': 'BIGINT', 'belongs_to': 'BIGINT',
                    'citext': 'CITEXT', 'hstore': 'HSTORE', 'interval': 'INTERVAL'}
            ct = tmap.get(rb_type, rb_type.upper())
            is_ref = rb_type in ('references', 'belongs_to')
            actual_name = f"{col_name}_id" if is_ref else col_name
            fk_val = None
            if is_ref:
                # Try to find foreign_key option
                fk_tbl_m = re.search(r'foreign_key:\s*\{?\s*to_table:\s*[:"]+(\w+)', opts)
                fk_tbl = fk_tbl_m.group(1) if fk_tbl_m else col_name + 's'
                fk_val = f"{fk_tbl}(id)"
                relationships.append({'from_table': current, 'from_column': actual_name, 'to_table': fk_tbl, 'to_column': 'id'})
            col = {'name': actual_name, 'type': ct, 'pk': False, 'fk': fk_val,
                   'nullable': 'null: false' not in opts, 'unique': False, 'default': None}
            def_m = re.search(r'default:\s*("([^"]*)"|(\S+))', opts)
            if def_m:
                col['default'] = def_m.group(2) if def_m.group(2) is not None else def_m.group(3)
            tables[current]['columns'].append(col)
            continue
        idx_m = re.match(r't\.index\s+\[([^\]]+)\](.*)', line)
        if idx_m:
            idx_cols = [c.strip().strip('"') for c in idx_m.group(1).split(',')]
            rest = idx_m.group(2)
            nm_m = re.search(r'name:\s*"(\w+)"', rest)
            idx_name = nm_m.group(1) if nm_m else f"idx_{current}_{'_'.join(idx_cols)}"
            is_uq = 'unique: true' in rest
            tables[current]['indexes'].append({'name': idx_name, 'columns': idx_cols, 'unique': is_uq})
            if is_uq and len(idx_cols) == 1:
                for col in tables[current]['columns']:
                    if col['name'] == idx_cols[0]:
                        col['unique'] = True
    # add_foreign_key "from_table", "to_table"[, column: "col"]
    for m in re.finditer(
        r'add_foreign_key\s+"(\w+)",\s+"(\w+)"(.*)', content
    ):
        from_tbl, to_tbl, opts = m.group(1), m.group(2), m.group(3)
        col_m = re.search(r'column:\s*"(\w+)"', opts)
        from_col = col_m.group(1) if col_m else to_tbl.rstrip('s') + '_id'
        relationships.append({'from_table': from_tbl, 'from_column': from_col,
                              'to_table': to_tbl, 'to_column': 'id'})
        if from_tbl in tables:
            for col in tables[from_tbl]['columns']:
                if col['name'] == from_col:
                    col['fk'] = f"{to_tbl}(id)"
    return list(tables.values()), relationships

def _parse_prisma(content):
    """Parse Prisma schema."""
    tables, relationships = {}, []
    current = None
    for line in content.split('\n'):
        line = line.strip()
        m = re.match(r'model\s+(\w+)\s*\{', line)
        if m:
            current = m.group(1)
            tables[current] = {'name': current, 'schema': '', 'columns': [], 'indexes': []}
            continue
        if line == '}':
            current = None
            continue
        if not current or current not in tables:
            continue
        col_m = re.match(r'(\w+)\s+(\w+)(\[\])?\??(.*)$', line)
        if col_m:
            name, ptype, is_arr, attrs = col_m.group(1), col_m.group(2), bool(col_m.group(3)), col_m.group(4) or ''
            if is_arr:
                continue
            tmap = {'Int': 'INTEGER', 'BigInt': 'BIGINT', 'Float': 'FLOAT', 'Decimal': 'DECIMAL',
                    'String': 'TEXT', 'Boolean': 'BOOLEAN', 'DateTime': 'TIMESTAMP', 'Json': 'JSONB', 'Bytes': 'BYTEA'}
            if ptype not in tmap:
                # Relation field
                if '@relation' in attrs:
                    rel_m = re.search(r'@relation\(.*?fields:\s*\[(\w+)\].*?references:\s*\[(\w+)\]', attrs)
                    if rel_m:
                        relationships.append({'from_table': current, 'from_column': rel_m.group(1), 'to_table': ptype, 'to_column': rel_m.group(2)})
                continue
            ct = tmap[ptype]
            is_id = '@id' in attrs
            is_uq = '@unique' in attrs
            nullable = '?' in line.split(name, 1)[1].split('@')[0]
            def_val = None
            def_m = re.search(r'@default\(([^)]+)\)', attrs)
            if def_m:
                def_val = def_m.group(1)
            tables[current]['columns'].append({'name': name, 'type': ct, 'pk': is_id,
                'fk': None, 'nullable': nullable, 'unique': is_uq or is_id, 'default': def_val})
            continue
        idx_m = re.match(r'@@(index|unique)\(\[([^\]]+)\](?:.*name:\s*"(\w+)")?\)', line)
        if idx_m:
            it, cols_str, iname = idx_m.group(1), idx_m.group(2), idx_m.group(3)
            cols = [c.strip().strip('"') for c in cols_str.split(',')]
            tables[current]['indexes'].append({
                'name': iname or f"{'uq' if it == 'unique' else 'idx'}_{current}_{'_'.join(cols)}",
                'columns': cols, 'unique': it == 'unique'})
    # Set FK info on columns
    for r in relationships:
        if r['from_table'] in tables:
            for col in tables[r['from_table']]['columns']:
                if col['name'] == r['from_column']:
                    col['fk'] = f"{r['to_table']}({r['to_column']})"
    return list(tables.values()), relationships

def _get_schema(kanban_dir):
    """Find and parse all schema files for a project."""
    files, project_dir = _find_schema_files(kanban_dir)
    if not files:
        return {"tables": [], "relationships": [], "files": []}
    all_tables, all_rels, file_info = {}, [], []
    # If schema.rb or structure.sql exists, skip migration files
    has_schema = any(os.path.basename(f).endswith("_schema.rb") or os.path.basename(f) in ("schema.rb", "structure.sql") for f in files)
    if has_schema:
        files = [f for f in files if "/migrate/" not in f and "/migrations/" not in f]
    for fpath in files:
        with open(fpath, encoding="utf-8", errors="replace") as f:
            content = f.read()
        fname = os.path.basename(fpath)
        if fname.endswith(".rb"):
            tbls, rels = _parse_schema_rb(content)
        elif fname.endswith(".prisma"):
            tbls, rels = _parse_prisma(content)
        else:
            tbls, rels = _parse_sql_schema(content)
        rel_path = os.path.relpath(fpath, project_dir)
        for t in tbls:
            if t["name"] in all_tables:
                ex = all_tables[t["name"]]
                if t["columns"]:
                    ex["columns"] = t["columns"]
                ex["indexes"].extend(t.get("indexes", []))
            else:
                t["source_file"] = rel_path
                all_tables[t["name"]] = t
        all_rels.extend(rels)
        file_info.append({"path": rel_path, "type": fname.rsplit(".", 1)[-1]})
    # Deduplicate relationships
    seen, unique_rels = set(), []
    for r in all_rels:
        key = (r["from_table"], r["from_column"], r["to_table"], r["to_column"])
        if key not in seen:
            seen.add(key); unique_rels.append(r)
    return {"tables": sorted(all_tables.values(), key=lambda t: t["name"]),
            "relationships": unique_rels, "files": file_info}

# Phase-name extraction tolerant of format drift across projects.
# Naming: PHASE_{SEED|MVP|PMF|SCALE|GTM|...}{NN} (per global rules), but real
# CURRENT_PHASE.md files vary: some omit "## Now:", some bury the phase in an H1
# title or a parallel-track table, some trail status emoji/slugs. We normalize.
_PHASE_FULL = re.compile(r'PHASE_[A-Za-z0-9_]+')
_PHASE_BARE = re.compile(r'\b(?:SEED|MVP|PMF|SCALE|GTM|HR|QUALITY)[A-Za-z]*\d+\b', re.IGNORECASE)

def _normalize_phase(text):
    """Pull a clean phase token out of one line of free text."""
    if not text:
        return ""
    m = _PHASE_FULL.search(text)
    if m:
        return m.group(0)
    m = _PHASE_BARE.search(text)
    if m:
        return m.group(0)
    # No recognizable token — strip status emoji / trailing slug and return the head.
    head = re.split(r'\s*[—/(]\s*|\s{2,}', text.strip())[0]
    head = re.sub(r'[\U0001F000-\U0001FAFF☀-➿️]', '', head).strip()
    return head

def _extract_phase(content):
    """Best-effort current-phase name from a CURRENT_PHASE.md body.

    Priority: `## Now:` line → H1 title token → first PHASE_ token in the body
    (preferring a line marked active with 🚧). Returns "" if nothing found.
    """
    lines = content.splitlines()
    for line in lines:
        m = re.match(r'^##\s*Now:\s*(.+)', line)
        if m:
            return _normalize_phase(m.group(1))
    for line in lines:
        if line.startswith('# '):
            m = _PHASE_FULL.search(line) or _PHASE_BARE.search(line)
            if m:
                return m.group(0)
    active, first = "", ""
    for line in lines:
        m = _PHASE_FULL.search(line)
        if m:
            if not first:
                first = m.group(0)
            if '🚧' in line and not active:
                active = m.group(0)
    return active or first

def _get_context(kanban_dir):
    """Current session context: phase, scope, in-progress tasks, do-not-touch."""
    project_dir = os.path.dirname(os.path.abspath(kanban_dir))
    phase_file = None
    for candidate in [
        os.path.join(project_dir, "private", "CURRENT_PHASE.md"),
        os.path.join(project_dir, "docs", "CURRENT_PHASE.md"),
        os.path.join(project_dir, "CURRENT_PHASE.md"),
    ]:
        if os.path.exists(candidate):
            phase_file = candidate
            break

    phase_name, scope, checklist_items, do_not_touch = "", "", [], []

    if phase_file:
        with open(phase_file, encoding="utf-8") as f:
            content = f.read()
        phase_name = _extract_phase(content)
        section = None
        for line in content.splitlines():
            m = re.match(r"^##\s*Scope:\s*(.+)", line)
            if m: scope = m.group(1).strip(); continue
            if re.match(r"^##\s*Done when", line, re.IGNORECASE): section = "checklist"; continue
            if re.match(r"^##\s*Do NOT touch", line, re.IGNORECASE): section = "do_not_touch"; continue
            if re.match(r"^##", line): section = None; continue
            if line.strip().startswith("<!--"): continue
            if section == "checklist":
                chk = re.match(r"^- \[([xX ])\]\s*(.+)", line)
                if chk:
                    checklist_items.append({"text": chk.group(2).strip(), "done": chk.group(1).lower() == "x"})
            elif section == "do_not_touch":
                bullet = re.match(r"^-\s+(.+)", line)
                if bullet:
                    do_not_touch.append(bullet.group(1).strip())
                elif line.strip() and not line.strip().startswith("#"):
                    do_not_touch.extend(p.strip() for p in line.split(",") if p.strip())

    data = _read_kanban(kanban_dir)
    all_tasks = data.get("tasks", [])
    archived = _list_archives(kanban_dir)

    in_progress = [t for t in all_tasks if t.get("status") == "in_progress"]
    all_done = sorted(
        [t for t in (all_tasks + archived) if t.get("status") == "done"],
        key=lambda t: t.get("completed_at") or t.get("updated_at") or "",
        reverse=True
    )

    stats = {s: 0 for s in BOARD_STATUSES}
    for t in all_tasks + archived:
        s = t.get("status", "")
        if s in stats:
            stats[s] += 1

    done_checks = sum(1 for c in checklist_items if c["done"])
    in_progress_payload, in_progress_note = _in_progress_payload(in_progress)
    # 담당자당 1건이 규율이다. 깨진 것을 조용히 넘기지 않고 세션 시작에 말한다.
    owners = {}
    for t in in_progress:
        who = t.get("assigned_to") or t.get("created_by") or "?"
        owners[who] = owners.get(who, 0) + 1
    over = sorted(k for k, v in owners.items() if v > 1)
    return {
        "phase": phase_name,
        "scope": scope,
        "checklist": {
            "total": len(checklist_items),
            "done": done_checks,
            "items": checklist_items,
        },
        "do_not_touch": do_not_touch,
        "in_progress": in_progress_payload,
        # 세션 시작 컨텍스트에는 제목만 싣는다. details 는 태스크당 수천 자라
        # 요약 응답의 절반 이상을 차지했다. 필요하면 /api/{key}/tasks/{id} 로 개별 조회.
        "recent_done": [_task_digest(t) for t in all_done[:3]],
        "stats": stats,
        "dependencies": _dependency_report(all_tasks, archived),
        "archive_hint": _archive_hint(kanban_dir, all_tasks),
        "in_progress_note": in_progress_note,
        "in_progress_over_limit": over,
        # 보드가 정상으로 보여도 수집은 죽어 있을 수 있다. 세 번 겪었다.
        "pipeline": _pipeline_health(),
    }


def _get_phase_check(kanban_dir):
    """Check phase transition readiness: kanban state + CURRENT_PHASE.md checklist."""
    project_dir = os.path.dirname(os.path.abspath(kanban_dir))
    issues = []
    warnings = []

    # 1. Kanban state
    data = _read_kanban(kanban_dir)
    tasks = data.get("tasks", [])
    in_progress = [t for t in tasks if t.get("status") == "in_progress"]
    review = [t for t in tasks if t.get("status") == "review"]
    if in_progress:
        issues.append(f"in_progress 태스크 {len(in_progress)}개: " +
                      ", ".join(f"#{t['id']} {t['title'][:30]}" for t in in_progress))
    if review:
        issues.append(f"review 미해결 태스크 {len(review)}개: " +
                      ", ".join(f"#{t['id']} {t['title'][:30]}" for t in review))

    # 2. CURRENT_PHASE.md checklist
    phase_file = None
    for candidate in [
        os.path.join(project_dir, "private", "CURRENT_PHASE.md"),
        os.path.join(project_dir, "CURRENT_PHASE.md"),
        os.path.join(project_dir, "docs", "CURRENT_PHASE.md"),
    ]:
        if os.path.exists(candidate):
            phase_file = candidate
            break

    unchecked, total_checks, phase_name = [], 0, ""
    if phase_file:
        with open(phase_file, encoding="utf-8") as f:
            content = f.read()
        phase_name = _extract_phase(content)
        for line in content.splitlines():
            chk = re.match(r"^- \[([ xX])\]\s*(.+)", line)
            if chk:
                total_checks += 1
                if chk.group(1) == " ":
                    unchecked.append(chk.group(2).strip())
        if unchecked:
            issues.append(f"Done when 미완료 {len(unchecked)}/{total_checks}: " +
                          ", ".join(unchecked[:3]) + ("..." if len(unchecked) > 3 else ""))
        if not phase_name:
            warnings.append("CURRENT_PHASE.md에서 Phase를 인식 못함 — '## Now: PHASE_xxx' 형식 권장")
    else:
        warnings.append("CURRENT_PHASE.md 없음 — 수동으로 확인하세요")

    # 3. PHASES.md freshness
    phases_file = next(
        (p for p in (
            os.path.join(project_dir, "private", "PHASES.md"),
            os.path.join(project_dir, "PHASES.md"),
            os.path.join(project_dir, "docs", "PHASES.md"),
        ) if os.path.exists(p)),
        None,
    )
    if not phases_file:
        warnings.append("PHASES.md 없음 — Phase 완료 기록을 남겨야 합니다")

    ready = len(issues) == 0
    return {
        "ready": ready,
        "phase": phase_name,
        "issues": issues,
        "warnings": warnings,
        "kanban": {
            "in_progress": len(in_progress),
            "review": len(review),
            "done": sum(1 for t in tasks if t.get("status") == "done"),
        },
        "checklist": {
            "total": total_checks,
            "unchecked": len(unchecked),
        },
    }

# ── Decision Log ────────────────────────────────────

def _decisions_path(kanban_dir):
    return os.path.join(kanban_dir, "decisions.json")

def _read_decisions(kanban_dir):
    p = _decisions_path(kanban_dir)
    if not os.path.exists(p):
        return {"version": 1, "next_id": 1, "decisions": []}
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def _write_decisions(kanban_dir, data):
    p = _decisions_path(kanban_dir)
    os.makedirs(kanban_dir, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, p)
    _schedule_remote_sync(kanban_dir)

def _new_decision(data, d):
    _did, _dnext = _mint_id(data, _id_prefix())
    dec = {
        "id": _did,
        "title": d.get("title", "").strip(),
        "why": d.get("why", "").strip(),
        "revisit": d.get("revisit", "").strip(),
        "task_id": d.get("task_id"),
        "phase": d.get("phase", "").strip(),
        "tags": d.get("tags", []),
        "created_at": _now(),
        "updated_at": _now(),
    }
    data["next_id"] = _dnext
    data["decisions"].append(dec)
    return data, dec

def _update_decision(dec, d):
    for f in ("title", "why", "revisit", "task_id", "phase", "tags"):
        if f in d:
            dec[f] = d[f]
    dec["updated_at"] = _now()


# ── Runs Log (agent run usage, append-only) ──────────

def _runs_path(kanban_dir):
    return os.path.join(kanban_dir, "runs.json")

def _read_runs(kanban_dir):
    p = _runs_path(kanban_dir)
    if not os.path.exists(p):
        return {"version": 1, "runs": []}
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def _write_runs(kanban_dir, data):
    p = _runs_path(kanban_dir)
    os.makedirs(kanban_dir, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, p)
    _schedule_remote_sync(kanban_dir)

def _safe_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0

def _new_run(data, r):
    """Append an agent run. Agent-agnostic: `agent` is a free string.

    Optional cache_read_tokens/cache_write_tokens enable accurate component-based
    cost (Claude transcripts are cache-heavy). session_id supports idempotent
    auto-collection (skip if already recorded). All extra fields are additive —
    runs.json stays append-only and backward compatible.
    """
    run = {
        "task_id": r.get("task_id"),
        "agent": (r.get("agent") or "").strip(),
        "model": (r.get("model") or "").strip(),
        "tokens": _safe_int(r.get("tokens")),
        "input_tokens": r.get("input_tokens"),
        "output_tokens": r.get("output_tokens"),
        "cache_read_tokens": r.get("cache_read_tokens"),
        "cache_write_tokens": r.get("cache_write_tokens"),
        "time_seconds": r.get("time_seconds"),
        "commit": (r.get("commit") or "").strip(),
        "session_id": (r.get("session_id") or "").strip(),
        "ts": (r.get("ts") or "").strip() or _now(),
    }
    # Additive execution-runtime fields. Existing fields and records stay intact.
    for key in (
        "run_id", "lease_id", "worker_id", "attempt", "status", "started_at",
        "finished_at", "branch", "tests", "failure_reason", "approval",
        "changes",
    ):
        if key in r:
            run[key] = r.get(key)
    data.setdefault("runs", []).append(run)
    return data, run

def _sync_task_tokens(kanban_dir, task_id, runs):
    """Derive a task's tokens_used from the sum of its runs (board stays correct)."""
    if task_id is None:
        return
    total = sum(_safe_int(r.get("tokens")) for r in runs if r.get("task_id") == task_id)
    data = _read_kanban(kanban_dir)
    task = next((t for t in data["tasks"] if t.get("id") == task_id), None)
    if task is not None:
        task["tokens_used"] = total
        task["updated_at"] = _now()
        _write_kanban(kanban_dir, data)


# ── Velocity & Cost Tracking ─────────────────────────

CLAUDE_COST_PER_TOKEN = 0.000009  # ~$9/MTok blended (Sonnet 4.6 avg) — fallback default

# Blended $/token (input+output rough avg) per agent → model substring.
# Used when runs.json carries per-run agent/model attribution; falls back to _default.
COST_PER_TOKEN = {
    "claude": {
        "_default": 0.000009,
        "opus": 0.00003,    # ~$15/$75 in/out blended
        "sonnet": 0.000009,
        "haiku": 0.0000024,
    },
    "codex": {"_default": 0.000006},
    "gpt": {"_default": 0.000006},
    "gemini": {"_default": 0.000004},
    "cursor": {"_default": 0.000006},
    "_default": CLAUDE_COST_PER_TOKEN,
}

def _cost_per_token(agent, model):
    """Resolve blended cost rate from agent + model (substring match)."""
    amap = COST_PER_TOKEN.get((agent or "").lower())
    if not amap:
        return COST_PER_TOKEN["_default"]
    ml = (model or "").lower()
    for key, rate in amap.items():
        if key != "_default" and key in ml:
            return rate
    return amap.get("_default", COST_PER_TOKEN["_default"])

# Per-component $/token (PMF03, cost model A). Used when a run carries a token
# breakdown (input/output/cache_read/cache_write) — accurate because Claude runs
# are cache-dominated and cache reads cost ~10% of input.
#
# 이 표는 reconcile_runs.py 와 값이 같아야 한다. 두 곳에 손으로 적어두었더니 실제로
# 드리프트가 났다 — 2026-08 감사 시점에 opus 가 $15/$75(구 Opus 3)로 남아 비용이 3배
# 부풀려져 있었다. 그래서 reconcile_runs 를 단일 출처로 삼고 여기서는 불러다 쓴다.


def _tier(inp, out):
    return {"in": inp, "out": out, "cw": inp * 1.25, "cr": inp * 0.1}


def _load_component_rates():
    """reconcile_runs 의 표를 재사용한다. 못 불러오면 같은 값으로 적은 사본을 쓴다."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import reconcile_runs
        return dict(reconcile_runs.COMPONENT_RATES), tuple(reconcile_runs._RATE_ORDER)
    except Exception:
        rates = {
            "fable": _tier(0.000010, 0.000050), "mythos": _tier(0.000010, 0.000050),
            "opus": _tier(0.000005, 0.000025), "sonnet-5": _tier(0.000002, 0.000010),
            "sonnet": _tier(0.000003, 0.000015), "haiku": _tier(0.000001, 0.000005),
            "_default": _tier(0.000003, 0.000015),
        }
        return rates, ("fable", "mythos", "opus", "sonnet-5", "sonnet", "haiku")


_CLAUDE_RATES, _RATE_ORDER = _load_component_rates()
COMPONENT_RATES = {"claude": _CLAUDE_RATES}

def _component_rates(agent, model):
    amap = COMPONENT_RATES.get((agent or "").lower())
    if not amap:
        return None
    ml = (model or "").lower()
    for key in _RATE_ORDER:
        if key in ml and key in amap:
            return amap[key]
    return amap.get("_default")

def _run_cost(run):
    """Cost of one run. Uses component rates when a breakdown is present,
    else falls back to the blended flat rate on `tokens` (e.g. Codex/Gemini)."""
    agent, model = run.get("agent"), run.get("model")
    rates = _component_rates(agent, model)
    has_breakdown = any(run.get(k) is not None for k in
                        ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))
    if rates and has_breakdown:
        return (_safe_int(run.get("input_tokens")) * rates["in"]
                + _safe_int(run.get("output_tokens")) * rates["out"]
                + _safe_int(run.get("cache_read_tokens")) * rates["cr"]
                + _safe_int(run.get("cache_write_tokens")) * rates["cw"])
    return _safe_int(run.get("tokens")) * _cost_per_token(agent, model)

def _get_velocity(kanban_dir):
    """Phase burndown + token cost stats. Tokens/cost derive from runs.json when present."""
    from collections import defaultdict
    data = _read_kanban(kanban_dir)
    archived = _list_archives(kanban_dir)
    all_tasks = data.get("tasks", []) + archived

    runs = _read_runs(kanban_dir).get("runs", [])
    runs_by_task = defaultdict(list)
    for r in runs:
        runs_by_task[r.get("task_id")].append(r)

    def task_tokens(t):
        rs = runs_by_task.get(t.get("id"))
        if rs:
            return sum(_safe_int(r.get("tokens")) for r in rs)
        return t.get("tokens_used") or 0

    def task_cost(t):
        rs = runs_by_task.get(t.get("id"))
        if rs:
            return sum(_run_cost(r) for r in rs)
        return (t.get("tokens_used") or 0) * CLAUDE_COST_PER_TOKEN

    # ── Phase stats ──
    phase_map = {}
    for t in all_tasks:
        ph = t.get("phase") or "No Phase"
        if ph not in phase_map:
            phase_map[ph] = {"phase": ph, "total": 0, "done": 0, "tokens": 0, "cost": 0.0, "dates": []}
        phase_map[ph]["total"] += 1
        if t.get("status") == "done":
            phase_map[ph]["done"] += 1
            cd = _kst_ymd(t.get("completed_at") or t.get("updated_at") or "")
            if cd:
                phase_map[ph]["dates"].append(cd)
        phase_map[ph]["tokens"] += task_tokens(t)
        phase_map[ph]["cost"] += task_cost(t)

    phases = []
    for ph, s in sorted(phase_map.items()):
        pct = round(s["done"] / s["total"] * 100) if s["total"] else 0
        phases.append({
            "phase": ph,
            "total": s["total"],
            "done": s["done"],
            "remaining": s["total"] - s["done"],
            "pct": pct,
            "tokens": s["tokens"],
            "cost_usd": round(s["cost"], 4),
        })

    # ── Daily done trend (last 30 days) ──
    daily = defaultdict(int)
    for t in all_tasks:
        if t.get("status") == "done":
            cd = _kst_ymd(t.get("completed_at") or t.get("updated_at") or "")
            if cd:
                daily[cd] += 1
    daily_trend = [{"date": k, "count": v} for k, v in sorted(daily.items())[-30:]]

    # ── Daily token usage (runs.json, last 30 recorded days) ──
    daily_tokens = defaultdict(int)
    daily_cost = defaultdict(float)
    for r in runs:
        day = _kst_ymd(r.get("ts") or "")
        if day:
            daily_tokens[day] += _safe_int(r.get("tokens"))
            daily_cost[day] += _run_cost(r)
    daily_token_trend = [
        {"date": day, "tokens": daily_tokens[day], "cost_usd": round(daily_cost[day], 4)}
        for day in sorted(daily_tokens)[-30:]
    ]

    # ── Category token breakdown ──
    cat_tokens = defaultdict(int)
    cat_cost = defaultdict(float)
    for t in all_tasks:
        cat = t.get("category") or "기타"
        cat_tokens[cat] += task_tokens(t)
        cat_cost[cat] += task_cost(t)
    category_breakdown = [
        {"category": k, "tokens": v, "cost_usd": round(cat_cost[k], 4)}
        for k, v in sorted(cat_tokens.items(), key=lambda x: -x[1])
    ]

    # ── Agent / model breakdown (from runs.json) ──
    agent_tok = defaultdict(int); agent_cost = defaultdict(float); agent_runs = defaultdict(int)
    model_tok = defaultdict(int); model_cost = defaultdict(float); model_runs = defaultdict(int)
    for r in runs:
        ag = r.get("agent") or "unknown"
        md = r.get("model") or "—"
        tok = _safe_int(r.get("tokens"))
        c = _run_cost(r)
        agent_tok[ag] += tok; agent_cost[ag] += c; agent_runs[ag] += 1
        mk = (ag, md)
        model_tok[mk] += tok; model_cost[mk] += c; model_runs[mk] += 1
    agent_breakdown = [
        {"agent": k, "tokens": v, "cost_usd": round(agent_cost[k], 4), "runs": agent_runs[k]}
        for k, v in sorted(agent_tok.items(), key=lambda x: -x[1])
    ]
    model_breakdown = [
        {"agent": k[0], "model": k[1], "tokens": v, "cost_usd": round(model_cost[k], 4), "runs": model_runs[k]}
        for k, v in sorted(model_tok.items(), key=lambda x: -x[1])
    ]

    # 토큰 집계 소스가 프로젝트마다 다름:
    #  - task 기반(tokens_used, git 공유·누적): 예 어떤 프로젝트는 task 쪽에만 값이 있고 (여러 머신 run에서 파생)
    #  - run 기반(runs.json, 머신 로컬): 어떤 프로젝트는 run 쪽에만 있다 (run이 task 미연결이라 tokens_used엔 없음)
    # 단순 합산하면 둘 다 채워진 경우 이중집계됨 → 더 완전한 쪽(max)을 사용.
    runs_total = sum(_safe_int(r.get("tokens")) for r in runs)
    runs_cost = sum(_run_cost(r) for r in runs)
    tasks_total = sum(task_tokens(t) for t in all_tasks)
    tasks_cost = sum(task_cost(t) for t in all_tasks)
    if runs_total >= tasks_total:
        total_tokens, total_cost = runs_total, runs_cost
    else:
        total_tokens, total_cost = tasks_total, tasks_cost
    return {
        "phases": phases,
        "daily_trend": daily_trend,
        "daily_token_trend": daily_token_trend,
        "category_breakdown": category_breakdown,
        "agent_breakdown": agent_breakdown,
        "model_breakdown": model_breakdown,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "total_runs": len(runs),
        "total_tasks": len(all_tasks),
        "total_done": sum(1 for t in all_tasks if t.get("status") == "done"),
    }


# ── Thin agent execution runtime ───────────────────

def _runtime_task(data, task_id):
    return next((task for task in data.get("tasks", []) if task.get("id") == task_id), None)


def _terminal_run_exists(kanban_dir, run_id):
    return any(run.get("run_id") == run_id for run in _read_runs(kanban_dir).get("runs", []))


def _append_terminal_run(kanban_dir, execution, payload=None):
    """Append exactly one terminal record for a managed execution."""
    run_id = execution.get("run_id")
    if not run_id or _terminal_run_exists(kanban_dir, run_id):
        return None
    payload = payload or {}
    fields = {
        "run_id": run_id,
        "lease_id": execution.get("lease_id"),
        "task_id": execution.get("task_id"),
        "worker_id": execution.get("worker_id"),
        "agent": payload.get("agent") or execution.get("agent") or "worker",
        "model": payload.get("model", ""),
        "attempt": execution.get("attempt", 1),
        "status": execution.get("status"),
        "started_at": execution.get("started_at"),
        "finished_at": execution.get("finished_at") or utc_now(),
        "tokens": payload.get("tokens", 0),
        "input_tokens": payload.get("input_tokens"),
        "output_tokens": payload.get("output_tokens"),
        "cache_read_tokens": payload.get("cache_read_tokens"),
        "cache_write_tokens": payload.get("cache_write_tokens"),
        "time_seconds": payload.get("time_seconds"),
        "commit": payload.get("commit", ""),
        "branch": payload.get("branch", ""),
        "changes": payload.get("changes"),
        "session_id": payload.get("session_id", ""),
        "tests": execution.get("tests"),
        "failure_reason": execution.get("failure_reason"),
        "approval": execution.get("approval"),
        "ts": execution.get("finished_at") or utc_now(),
    }
    runs = _read_runs(kanban_dir)
    runs, run = _new_run(runs, fields)
    _write_runs(kanban_dir, runs)
    _sync_task_tokens(kanban_dir, execution.get("task_id"), runs.get("runs", []))
    return run


def _failure_status(policy, attempt):
    return "todo" if int(attempt or 1) < int(policy.get("max_attempts", 2)) else "review"


def _expire_runtime_locked(kanban_dir, runtime, tasks, policy, now=None):
    """Expire stale leases. Caller must hold runtime_lock."""
    now_dt = parse_time(now or utc_now())
    changed = False
    for lease in runtime.get("leases", {}).values():
        expiry = parse_time(lease.get("expires_at"))
        if lease.get("status") != "active" or not expiry or not now_dt or expiry > now_dt:
            continue
        lease["status"] = "expired"
        lease["expired_at"] = utc_now()
        execution = runtime.get("executions", {}).get(lease.get("run_id"))
        if execution and execution.get("status") == "running":
            execution["status"] = "expired"
            execution["finished_at"] = utc_now()
            execution["failure_reason"] = "lease_expired"
            task = _runtime_task(tasks, execution.get("task_id"))
            if task and task.get("active_run_id") == execution.get("run_id"):
                destination = _failure_status(policy, execution.get("attempt"))
                _update_task(task, {
                    "status": destination,
                    "active_run_id": "",
                    "last_run_id": execution.get("run_id"),
                    "review": "Lease expired; human review required" if destination == "review" else "",
                })
            _append_terminal_run(kanban_dir, execution)
        changed = True
    return changed


def _runtime_view(kanban_dir):
    with runtime_lock(kanban_dir):
        runtime = read_runtime(kanban_dir)
        tasks = _read_kanban(kanban_dir)
        policy = load_policy(kanban_dir)
        if _expire_runtime_locked(kanban_dir, runtime, tasks, policy):
            write_runtime(kanban_dir, runtime)
            _write_kanban(kanban_dir, tasks)
        return sanitized_runtime(runtime, policy)


def _runtime_claim(kanban_dir, request_data):
    worker_id = str(request_data.get("worker_id") or "").strip()
    agent = str(request_data.get("agent") or "").strip()
    requested_id = request_data.get("task_id")
    if not worker_id or not agent:
        return None, "worker_id and agent required", 400
    with runtime_lock(kanban_dir):
        runtime = read_runtime(kanban_dir)
        tasks = _read_kanban(kanban_dir)
        policy = load_policy(kanban_dir)
        _expire_runtime_locked(kanban_dir, runtime, tasks, policy)
        candidates = [task for task in tasks.get("tasks", []) if task.get("status") == "todo"]
        if requested_id is not None:
            candidates = [task for task in candidates if str(task.get("id")) == str(requested_id)]
        candidates.sort(key=lambda task: (
            {"high": 0, "medium": 1, "low": 2}.get(task.get("priority"), 1),
            task.get("position") or 0, str(task.get("id", 0)),
        ))
        active_task_ids = {
            lease.get("task_id") for lease in runtime.get("leases", {}).values()
            if lease.get("status") == "active"
        }
        task = next((item for item in candidates if item.get("id") not in active_task_ids), None)
        if not task:
            write_runtime(kanban_dir, runtime)
            _write_kanban(kanban_dir, tasks)
            return None, "no claimable task", 409
        attempt = 1 + max(
            [int(item.get("attempt", 0)) for item in runtime.get("executions", {}).values() if item.get("task_id") == task.get("id")]
            or [0]
        )
        identity = new_identity()
        now = utc_now()
        lease = {
            "lease_id": identity["lease_id"],
            "run_id": identity["run_id"],
            "task_id": task.get("id"),
            "worker_id": worker_id,
            "token_hash": identity["token_hash"],
            "status": "active",
            "claimed_at": now,
            "heartbeat_at": now,
            "expires_at": expires_at(policy.get("lease_ttl_seconds", 120)),
        }
        execution = {
            "run_id": identity["run_id"],
            "lease_id": identity["lease_id"],
            "task_id": task.get("id"),
            "worker_id": worker_id,
            "agent": agent,
            "attempt": attempt,
            "status": "running",
            "started_at": now,
            "tests": None,
            "approval": "pending" if approval_required(policy, task.get("category")) else "not_required",
        }
        runtime.setdefault("leases", {})[identity["lease_id"]] = lease
        runtime.setdefault("executions", {})[identity["run_id"]] = execution
        _update_task(task, {
            "status": "in_progress",
            "execution_managed": True,
            "active_run_id": identity["run_id"],
            "last_run_id": identity["run_id"],
            "execution_attempts": attempt,
            "review": "",
        })
        write_runtime(kanban_dir, runtime)
        _write_kanban(kanban_dir, tasks)
        context = _get_context(kanban_dir)
        adapter = policy.get("adapters", {}).get(agent)
        response = {
            "run_id": identity["run_id"],
            "lease_id": identity["lease_id"],
            "lease_token": identity["lease_token"],
            "lease": {key: value for key, value in lease.items() if key != "token_hash"},
            "execution": execution,
            "task": task,
            "context": context,
            "adapter": adapter,
            "heartbeat_seconds": policy.get("heartbeat_seconds", 30),
        }
        return response, None, 201


def _runtime_credentials(runtime, data):
    lease = runtime.get("leases", {}).get(str(data.get("lease_id") or ""))
    run_id = str(data.get("run_id") or "")
    execution = runtime.get("executions", {}).get(run_id)
    if not lease or lease.get("run_id") != run_id or not execution:
        return None, None, "run or lease not found", 404
    if not valid_token(lease, data.get("lease_token")):
        return None, None, "invalid lease token", 403
    return lease, execution, None, 200


def _runtime_heartbeat(kanban_dir, data):
    with runtime_lock(kanban_dir):
        runtime = read_runtime(kanban_dir)
        policy = load_policy(kanban_dir)
        lease, execution, error, status = _runtime_credentials(runtime, data)
        if error:
            return None, error, status
        if lease.get("status") != "active" or execution.get("status") != "running":
            return None, "lease is not active", 409
        lease["heartbeat_at"] = utc_now()
        lease["expires_at"] = expires_at(policy.get("lease_ttl_seconds", 120))
        write_runtime(kanban_dir, runtime)
        return {key: value for key, value in lease.items() if key != "token_hash"}, None, 200


def _execution_workdir(kanban_dir, candidate):
    """Accept the project root or a Git worktree sharing the same common dir."""
    project_dir = os.path.dirname(os.path.abspath(kanban_dir))
    if not candidate:
        return project_dir
    candidate = os.path.realpath(str(candidate))
    if not os.path.isdir(candidate):
        return None
    try:
        def common(path):
            raw = subprocess.check_output(
                ["git", "-C", path, "rev-parse", "--git-common-dir"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            return os.path.realpath(os.path.join(path, raw))
        return candidate if common(candidate) == common(project_dir) else None
    except (OSError, subprocess.CalledProcessError):
        return candidate if candidate == os.path.realpath(project_dir) else None


def _runtime_finish(kanban_dir, data, outcome):
    with runtime_lock(kanban_dir):
        runtime = read_runtime(kanban_dir)
        tasks = _read_kanban(kanban_dir)
        policy = load_policy(kanban_dir)
        lease, execution, error, status = _runtime_credentials(runtime, data)
        if error:
            return None, error, status
        if execution.get("status") != "running":
            return {"execution": execution, "task": _runtime_task(tasks, execution.get("task_id"))}, None, 200
        task = _runtime_task(tasks, execution.get("task_id"))
        if not task or task.get("active_run_id") != execution.get("run_id"):
            return None, "task is no longer owned by this run", 409
        for key in ("branch", "commit", "changes", "time_seconds"):
            if key in data:
                execution[key] = data.get(key)
        if outcome == "complete":
            workdir = _execution_workdir(kanban_dir, data.get("worktree_path"))
            if not workdir:
                return None, "worktree_path is not part of the registered Git repository", 400
            execution["worktree_path"] = workdir
            gate = run_test_gate(kanban_dir, policy, workdir=workdir)
            execution["tests"] = gate
            passed = bool(gate.get("passed"))
            if passed:
                needs_approval = approval_required(policy, task.get("category"))
                execution["status"] = "awaiting_approval" if needs_approval else "passed"
                execution["approval"] = "pending" if needs_approval else "not_required"
                destination = "review" if needs_approval else "done"
                review = "Worker tests passed; awaiting approval" if needs_approval else ""
            else:
                execution["status"] = "test_failed"
                execution["failure_reason"] = "test_gate_" + str(gate.get("status", "failed"))
                destination = _failure_status(policy, execution.get("attempt"))
                review = "Test gate failed after final attempt" if destination == "review" else ""
        else:
            execution["status"] = "failed"
            execution["failure_reason"] = str(data.get("failure_reason") or "agent_failed")[:1000]
            destination = _failure_status(policy, execution.get("attempt"))
            review = "Worker failed after final attempt" if destination == "review" else ""
        now = utc_now()
        execution["finished_at"] = now
        lease["status"] = "released"
        lease["released_at"] = now
        _update_task(task, {
            "status": destination,
            "active_run_id": "",
            "last_run_id": execution.get("run_id"),
            "review": review,
        })
        write_runtime(kanban_dir, runtime)
        _write_kanban(kanban_dir, tasks)
        _append_terminal_run(kanban_dir, execution, data)
        return {"execution": execution, "task": task}, None, 200


def _runtime_action(kanban_dir, data):
    action = str(data.get("action") or "").lower()
    run_id = str(data.get("run_id") or "")
    command_id = str(data.get("command_id") or "")
    if action not in ("approve", "reject", "retry", "cancel") or not run_id:
        return None, "action and run_id required", 400
    with runtime_lock(kanban_dir):
        runtime = read_runtime(kanban_dir)
        if command_id and command_id in runtime.get("applied_commands", []):
            return {"idempotent": True, "run_id": run_id, "action": action}, None, 200
        execution = runtime.get("executions", {}).get(run_id)
        if not execution:
            return None, "run not found", 404
        tasks = _read_kanban(kanban_dir)
        task = _runtime_task(tasks, execution.get("task_id"))
        if not task or task.get("last_run_id") != run_id:
            return None, "run is not current for task", 409
        if action == "approve":
            if execution.get("status") != "awaiting_approval" or not execution.get("tests", {}).get("passed"):
                return None, "only a test-passed awaiting run can be approved", 409
            execution["status"] = "approved"
            execution["approval"] = "approved"
            execution["approved_at"] = utc_now()
            _update_task(task, {"status": "done", "review": ""})
        elif action in ("reject", "retry"):
            if task.get("status") not in ("review", "todo"):
                return None, "task is not reviewable", 409
            execution["approval"] = "rejected" if action == "reject" else "retry_requested"
            execution["status"] = "rejected" if action == "reject" else "retry_requested"
            _update_task(task, {"status": "todo", "active_run_id": "", "review": str(data.get("reason") or "")[:1000]})
        else:
            execution["status"] = "cancelled"
            execution["approval"] = "cancelled"
            _update_task(task, {"status": "backlog", "active_run_id": "", "review": str(data.get("reason") or "")[:1000]})
        if command_id:
            applied = runtime.setdefault("applied_commands", [])
            applied.append(command_id)
            runtime["applied_commands"] = applied[-1000:]
        write_runtime(kanban_dir, runtime)
        _write_kanban(kanban_dir, tasks)
        return {"execution": execution, "task": task, "action": action}, None, 200


def _managed_done_allowed(kanban_dir, task):
    if not task.get("execution_managed"):
        return True
    runtime = read_runtime(kanban_dir)
    execution = runtime.get("executions", {}).get(task.get("last_run_id"))
    return bool(execution and execution.get("status") in ("passed", "approved") and execution.get("tests", {}).get("passed"))


def _runtime_reaper():
    while True:
        for info in load_projects().values():
            kanban_dir = info.get("kanban_dir", "")
            if not kanban_dir:
                continue
            try:
                _runtime_view(kanban_dir)
            except Exception as exc:
                print(f"  Runtime reaper warning: {type(exc).__name__}", file=sys.stderr)
        threading.Event().wait(5)


def _start_runtime_reaper():
    thread = threading.Thread(target=_runtime_reaper, name="vibe-harness-runtime-reaper", daemon=True)
    thread.start()
    return thread


# ── Remote dashboard snapshot sync ──────────────────

_sync_lock = threading.Lock()
_sync_timer = None
_sync_dirty_dirs = set()
_mission_watch_interval = 1.0


def _load_sync_config():
    """Load optional remote sync config. Missing/disabled config is a no-op.

    Format:
      {"enabled": true, "endpoint": "https://.../sync", "secret": "...",
       "dashboards": {"ax-project": ["zesty-os", "zestim"]}}
    """
    if not os.path.exists(SYNC_CONFIG_PATH):
        return None
    try:
        with open(SYNC_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if not cfg.get("enabled", True):
            return None
        if not str(cfg.get("endpoint", "")).startswith(("https://", "http://localhost", "http://127.0.0.1")):
            return None
        if not cfg.get("secret") or not isinstance(cfg.get("dashboards"), dict):
            return None
        return cfg
    except (OSError, ValueError, TypeError):
        return None


def _project_key_for_dir(kanban_dir):
    target = os.path.abspath(kanban_dir)
    for key, info in load_projects().items():
        if os.path.abspath(info.get("kanban_dir", "")) == target:
            return key
    return None


def _sort_position(task):
    """정렬용 position. 타입이 섞여도 숫자로 비교한다.

    칸반은 사람이 손으로도 고치고 여러 세션이 동시에 쓴다. 실제로 한 보드에 int 159 개와
    str 7 개가 섞여 있었고, 그대로 비교하다 sync 가 통째로 죽었다 — 보드 하나의 흠이 그
    머신의 동기화 전체를 멈춘다. 읽는 쪽이 견딘다.
    """
    try:
        return float(task.get("position") or 0)
    except (TypeError, ValueError):
        return 0.0


def _snapshot_source(key, info):
    kanban_dir = info.get("kanban_dir", "")
    data = _read_kanban(kanban_dir)
    tasks = data.get("tasks", []) + _list_archives(kanban_dir)
    tasks.sort(key=lambda t: (_sort_position(t), str(t.get("id", 0))))
    decisions = _read_decisions(kanban_dir).get("decisions", [])
    return {
        "key": key,
        "name": info.get("name") or key,
        "context": _get_context(kanban_dir),
        "tasks": tasks,
        "decisions": decisions,
        "velocity": _get_velocity(kanban_dir),
        "schema": _get_schema(kanban_dir),
        "runtime": _runtime_view(kanban_dir),
    }


def _build_dashboard_snapshot(dashboard, project_keys):
    projects = load_projects()
    sources = []
    for key in project_keys:
        info = projects.get(key)
        if info and os.path.isdir(info.get("kanban_dir", "")):
            sources.append(_snapshot_source(key, info))
    body = {
        "schema_version": 1,
        "dashboard": dashboard,
        "generated_at": _now(),
        "sources": sources,
    }
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    body["revision"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return body


def _atomic_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_pending_sync():
    try:
        with open(SYNC_PENDING_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _post_snapshot(cfg, payload):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        cfg["endpoint"],
        data=raw,
        headers={
            "Authorization": "Bearer " + cfg["secret"],
            "Content-Type": "application/json",
            "User-Agent": "Vibe-Engineering-Sync/1",
        },
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=10) as resp:
        if not 200 <= resp.status < 300:
            raise RuntimeError("sync HTTP " + str(resp.status))


def _remote_request(cfg, method, query=None, payload=None):
    url = cfg["endpoint"]
    if query:
        url += ("&" if "?" in url else "?") + urlencode(query)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib_request.Request(
        url,
        data=raw,
        headers={
            "Authorization": "Bearer " + cfg["secret"],
            "Content-Type": "application/json",
            "User-Agent": "Vibe-Engineering-Sync/1",
        },
        method=method,
    )
    with urllib_request.urlopen(req, timeout=10) as resp:
        if not 200 <= resp.status < 300:
            raise RuntimeError("sync HTTP " + str(resp.status))
        body = resp.read()
        return json.loads(body.decode("utf-8")) if body else {}


def _poll_remote_commands_once():
    cfg = _load_sync_config()
    if not cfg:
        return 0
    projects = load_projects()
    applied_total = 0
    for dashboard, keys in cfg.get("dashboards", {}).items():
        try:
            body = _remote_request(cfg, "GET", query={"dashboard": dashboard})
        except (OSError, ValueError, urllib_error.URLError, urllib_error.HTTPError, RuntimeError):
            continue
        commands = body.get("commands", []) if isinstance(body, dict) else []
        acknowledged = []
        for command in commands:
            if not isinstance(command, dict) or command.get("source_key") not in keys:
                continue
            info = projects.get(command.get("source_key")) or {}
            kanban_dir = info.get("kanban_dir", "")
            if not kanban_dir:
                continue
            result, error, status = _runtime_action(kanban_dir, {
                "command_id": command.get("id"),
                "run_id": command.get("run_id"),
                "action": command.get("action"),
                "reason": command.get("reason", ""),
            })
            # A different host may own this source/run. Never acknowledge 404/409:
            # the host holding the matching runtime must be the one to consume it.
            # Only success/idempotency or a structurally invalid command is final.
            if not error or status == 400:
                acknowledged.append(command.get("id"))
                if result and not result.get("idempotent"):
                    applied_total += 1
        acknowledged = [item for item in acknowledged if item]
        if acknowledged:
            try:
                _remote_request(cfg, "DELETE", payload={"dashboard": dashboard, "command_ids": acknowledged})
            except (OSError, ValueError, urllib_error.URLError, urllib_error.HTTPError, RuntimeError):
                pass
    return applied_total


def _remote_command_poller():
    while True:
        try:
            _poll_remote_commands_once()
        except Exception as exc:
            print(f"  Remote command poll warning: {type(exc).__name__}", file=sys.stderr)
        threading.Event().wait(5)


def _start_remote_command_poller():
    thread = threading.Thread(target=_remote_command_poller, name="vibe-harness-command-poll", daemon=True)
    thread.start()
    return thread


def _sync_worker(dirty_dirs):
    cfg = _load_sync_config()
    if not cfg:
        return
    changed_keys = {_project_key_for_dir(d) for d in dirty_dirs}
    changed_keys.discard(None)
    pending = _read_pending_sync()
    dashboards = cfg.get("dashboards", {})
    for dashboard, keys in dashboards.items():
        if not isinstance(keys, list):
            continue
        # Empty dirty set means startup/manual flush. Otherwise only rebuild affected bundles.
        if changed_keys and not changed_keys.intersection(keys):
            continue
        pending[dashboard] = _build_dashboard_snapshot(dashboard, keys)

    completed = []
    for dashboard, payload in list(pending.items()):
        try:
            _post_snapshot(cfg, payload)
            completed.append(dashboard)
        except (OSError, urllib_error.URLError, urllib_error.HTTPError, RuntimeError) as exc:
            print(f"  Sync pending ({dashboard}): {type(exc).__name__}", file=sys.stderr)
    for dashboard in completed:
        pending.pop(dashboard, None)

    if pending:
        _atomic_json(SYNC_PENDING_PATH, pending)
        try:
            os.chmod(SYNC_PENDING_PATH, 0o600)
        except OSError:
            pass
    elif os.path.exists(SYNC_PENDING_PATH):
        try:
            os.remove(SYNC_PENDING_PATH)
        except OSError:
            pass


def _run_scheduled_sync():
    global _sync_timer
    with _sync_lock:
        dirty = set(_sync_dirty_dirs)
        _sync_dirty_dirs.clear()
        _sync_timer = None
    _sync_worker(dirty)


def _schedule_remote_sync(kanban_dir=None, delay=0.4):
    """Debounce writes and sync in a daemon thread so local API stays responsive."""
    global _sync_timer
    if not _load_sync_config():
        return
    with _sync_lock:
        if kanban_dir:
            _sync_dirty_dirs.add(os.path.abspath(kanban_dir))
        if _sync_timer:
            _sync_timer.cancel()
        _sync_timer = threading.Timer(delay, _run_scheduled_sync)
        _sync_timer.daemon = True
        _sync_timer.start()


def _mission_paths(kanban_dir):
    """Mission files whose contents feed the remote context snapshot."""
    project_dir = os.path.dirname(os.path.abspath(kanban_dir))
    return [
        os.path.join(project_dir, "private", "CURRENT_PHASE.md"),
        os.path.join(project_dir, "docs", "CURRENT_PHASE.md"),
        os.path.join(project_dir, "CURRENT_PHASE.md"),
    ]


def _mission_fingerprint(kanban_dir):
    """Cheap signature that also detects creation, replacement, and deletion."""
    signature = []
    for path in _mission_paths(kanban_dir):
        try:
            stat = os.stat(path)
            signature.append((path, stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((path, None, None))
    return tuple(signature)


def _watch_mission_files():
    """Poll configured projects and debounce-sync direct Mission file edits."""
    previous = {}
    while True:
        cfg = _load_sync_config()
        projects = load_projects()
        watched_keys = {
            key
            for keys in (cfg or {}).get("dashboards", {}).values()
            if isinstance(keys, list)
            for key in keys
        }
        current = {}
        for key in watched_keys:
            info = projects.get(key) or {}
            kanban_dir = info.get("kanban_dir", "")
            if not kanban_dir:
                continue
            fingerprint = _mission_fingerprint(kanban_dir)
            current[key] = fingerprint
            if key in previous and previous[key] != fingerprint:
                _schedule_remote_sync(kanban_dir)
        previous = current
        threading.Event().wait(_mission_watch_interval)


def _start_mission_watcher():
    watcher = threading.Thread(
        target=_watch_mission_files,
        name="vibe-harness-mission-watch",
        daemon=True,
    )
    watcher.start()
    return watcher


# ── Handler ─────────────────────────────────────────

class BadRequest(Exception):
    """클라이언트가 보낸 것을 읽을 수 없다. 500 이 아니라 400 이다."""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _body(self):
        """요청 본문을 JSON 으로. **읽을 수 없으면 400 이지 침묵이 아니다.**

        여기가 뚫려 있었다. 깨진 JSON 이나 숫자가 아닌 Content-Length 가 오면 예외가
        핸들러 밖으로 나가고, socketserver 는 **응답을 하나도 쓰지 않은 채 연결을
        끊었다.** 클라이언트가 받는 것은 400 이 아니라 `RemoteDisconnected` 다.

        Content-Length 를 못 읽으면 **남은 본문을 비우고 나서** 400 을 낸다. 읽지 않은
        본문이 소켓에 남은 채 연결을 닫으면 macOS 는 FIN 이 아니라 **RST** 를 보내고,
        그러면 이미 보낸 응답까지 함께 날아가 클라이언트가 `ConnectionResetError` 를
        맞는다. 길이를 모르니 정확히 비울 수 없어 짧은 시한 안에 최선으로 버린다.

        **인과는 증명하지 못했다.** 전체 스위트를 커버리지와 함께 돌릴 때 이 경로에서
        `ConnectionResetError` 가 두 번 났고, 이 조치 뒤로는 안 난다. 다만 **옛 코드로
        되돌려도 재현되지 않아** 이 조치가 원인을 없앤 것인지 확인할 수 없다.
        기전(읽지 않은 수신 데이터 + close → RST)은 분명하고 조치는 그 자체로 옳지만,
        "고쳤다"고 적지는 않는다.
        """
        raw = self.headers.get("Content-Length", 0)
        try:
            n = int(raw)
        except (TypeError, ValueError) as exc:
            # 길이를 모르니 정확히 비워낼 수 없다. 남은 것을 짧은 시한 안에 버린다.
            self._drain()
            raise BadRequest("Content-Length 가 숫자가 아니다: %r" % (raw,)) from exc
        if n <= 0:
            return {}
        body = self.rfile.read(n)          # 파싱보다 먼저 — 남기면 RST 가 된다
        try:
            return json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BadRequest("본문이 JSON 이 아니다: %s" % exc) from exc

    def _drain(self, limit=1 << 20):
        """길이를 모르는 남은 본문을 버린다. 못 버려도 넘어간다 — 최선 노력이다."""
        try:
            saved = self.connection.gettimeout()
            self.connection.settimeout(0.2)
        except OSError:
            return
        try:
            dropped = 0
            while dropped < limit:
                chunk = self.rfile.read1(65536)
                if not chunk:
                    break
                dropped += len(chunk)
        except (OSError, ValueError):
            pass
        finally:
            try:
                self.connection.settimeout(saved)
            except OSError:
                pass

    def _resolve_project(self, parts):
        if len(parts) < 1:
            return None, None, parts
        projects = load_projects()
        key = parts[0]
        if key in projects:
            return key, projects[key]["kanban_dir"], parts[1:]
        return None, None, parts

    def _guarded(self, handler):
        """모든 요청의 마지막 방어선.

        핸들러에서 예외가 새어 나가면 socketserver 는 **응답 없이 연결을 끊는다.**
        그건 이 프로젝트가 반복해 온 '성공처럼 보이는 침묵'의 HTTP 판이다 — 밖에서
        보면 서버가 죽은 것과 구별되지 않는다.

        500 을 돌려주는 것이 조용히 끊는 것보다 낫다. 관측 가능하기 때문이다.
        """
        try:
            return handler()
        except BadRequest as exc:
            return self._error(400, str(exc))
        except BrokenPipeError:
            raise                      # 클라이언트가 끊은 것 — 여기서 쓸 곳이 없다
        except Exception as exc:
            traceback.print_exc()
            return self._error(500, "%s: %s" % (type(exc).__name__, exc))

    def _error(self, status, message):
        """오류 응답. **연결을 닫는다.**

        본문을 읽다 실패했으면 그 본문이 소켓에 남아 있을 수 있다. keep-alive 로 연결을
        재사용하면 남은 바이트가 **다음 요청의 시작으로 읽힌다.** 무엇이 남았는지 모르는
        채로 연결을 이어 쓰는 것보다 닫는 편이 낫다.
        """
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        for h, v in [("Access-Control-Allow-Origin", "*"),
                      ("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS"),
                      ("Access-Control-Allow-Headers", "Content-Type")]:
            self.send_header(h, v)
        self.end_headers()

    def do_GET(self):
        return self._guarded(self._get)

    def _get(self):
        parsed = urlparse(self.path)
        p = parsed.path.rstrip("/")

        # ── UI ──
        if p in ("", "/kanban"):
            html_path = os.path.join(os.path.dirname(__file__), "kanban.html")
            with open(html_path, encoding="utf-8") as f:
                return self._html(f.read())

        # ── API: projects list ──
        if p == "/api/projects":
            projects = load_projects()
            result = []
            for key, info in projects.items():
                exists = os.path.exists(_kanban_path(info["kanban_dir"]))
                result.append({"key": key, "name": info["name"], "kanban_dir": info["kanban_dir"], "exists": exists})
            return self._json(result)

        # ── API: /api/{project}/... ──
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, kanban_dir, rest = self._resolve_project(parts)
            if not pkey or not kanban_dir:
                return self._json({"error": "unknown project"}, 404)

            if rest == ["tasks"] or rest == []:
                # Return active + archived tasks
                data = _read_kanban(kanban_dir)
                all_tasks = data["tasks"] + _list_archives(kanban_dir)
                all_tasks.sort(key=lambda t: (t.get("position") or 0, str(t.get("id", 0))))
                return self._json(all_tasks)

            if rest == ["export"]:
                data = _read_kanban(kanban_dir)
                all_tasks = data["tasks"] + _list_archives(kanban_dir)
                return self._json({
                    "version": 1,
                    "project": pkey,
                    "exported_at": _now(),
                    "tasks": all_tasks
                })

            if rest == ["stats"]:
                data = _read_kanban(kanban_dir)
                all_tasks = data["tasks"] + _list_archives(kanban_dir)
                stats = {}
                for s in BOARD_STATUSES:
                    stats[s] = sum(1 for t in all_tasks if t.get("status") == s)
                stats["total"] = len(all_tasks)
                return self._json(stats)

            if rest == ["archive"]:
                data = _read_kanban(kanban_dir)
                done_tasks = [t for t in data["tasks"] if t.get("status") == "done"]
                if not done_tasks:
                    return self._json({"archived": 0, "message": "no done tasks to archive"})
                _archive_tasks(kanban_dir, done_tasks)
                data["tasks"] = [t for t in data["tasks"] if t.get("status") != "done"]
                _write_kanban(kanban_dir, data)
                return self._json({"archived": len(done_tasks)})

            if rest == ["schema"]:
                return self._json(_get_schema(kanban_dir))

            if rest == ["phase-check"]:
                return self._json(_get_phase_check(kanban_dir))

            if rest == ["context"]:
                return self._json(_get_context(kanban_dir))

            if rest == ["search"]:
                # 검색은 물었을 때만 값을 치른다 — /context 는 867 tok 그대로다.
                qs = parse_qs(urlparse(self.path).query)
                return self._json(_search(kanban_dir,
                                          (qs.get("q") or [""])[0],
                                          (qs.get("limit") or [SEARCH_DEFAULT_LIMIT])[0]))

            if rest == ["decisions"]:
                decisions = _read_decisions(kanban_dir)["decisions"]
                # `?task=<id>` — 이 태스크를 다루는 결정만. **역방향 필드가 아니라 계산이다.**
                want = (parse_qs(parsed.query).get("task") or [""])[0].strip()
                if want:
                    data = _read_kanban(kanban_dir)
                    tasks = data.get("tasks", []) + _list_archives(kanban_dir)
                    ids = {str(t.get("id")) for t in tasks}
                    match = next((t for t in tasks if str(t.get("id")) == want), None)
                    if match is None:
                        # 없는 태스크에 빈 목록을 돌려주면 "관련 결정이 없다"로 읽힌다.
                        return self._json({"error": "unknown task", "task": want}, 404)
                    return self._json(task_link_report(match, decisions, ids))
                return self._json(decisions)

            if rest == ["velocity"]:
                return self._json(_get_velocity(kanban_dir))

            if rest == ["runs"]:
                qs = parse_qs(parsed.query)
                runs = _read_runs(kanban_dir)["runs"]
                tid = qs.get("task_id", [None])[0]
                if tid is not None:
                    runs = [r for r in runs if str(r.get("task_id")) == str(tid)]
                return self._json(runs)

            if rest == ["runtime"]:
                return self._json(_runtime_view(kanban_dir))

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        return self._guarded(self._post)

    def _post(self):
        p = urlparse(self.path).path.rstrip("/")

        # ── Register project ──
        if p == "/api/projects":
            d = self._body()
            key = d.get("key", "")
            name = d.get("name", key)
            kanban_dir = d.get("kanban_dir", d.get("db_path", ""))
            # Backward compat: if db_path given, convert to kanban_dir
            if kanban_dir.endswith(".db") or kanban_dir.endswith("/kanban.db"):
                kanban_dir = os.path.dirname(kanban_dir)
            if not key or not kanban_dir:
                return self._json({"error": "key and kanban_dir required"}, 400)
            projects = register_project(key, name, kanban_dir)
            return self._json({"registered": key, "total": len(projects)}, 201)

        # ── API: /api/{project}/... ──
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, kanban_dir, rest = self._resolve_project(parts)
            if not pkey:
                return self._json({"error": "unknown project"}, 404)

            if rest == ["tasks"]:
                d = self._body()
                data = _read_kanban(kanban_dir)
                data, task = _new_task(data, d)
                _write_kanban(kanban_dir, data)
                return self._json(task, 201)

            if rest == ["import"]:
                d = self._body()
                imp_tasks = d.get("tasks", [])
                mode = d.get("mode", "merge")
                data = _read_kanban(kanban_dir)

                if mode == "replace":
                    data["tasks"] = []
                    data["next_id"] = 1

                imported, skipped, updated = 0, 0, 0
                existing_by_id = {t["id"]: t for t in data["tasks"]}

                for t in imp_tasks:
                    orig_id = t.get("id")
                    if mode == "merge" and orig_id and orig_id in existing_by_id:
                        existing = existing_by_id[orig_id]
                        if t.get("updated_at", "") > (existing.get("updated_at") or ""):
                            _update_task(existing, t)
                            updated += 1
                        else:
                            skipped += 1
                        continue
                    data, _ = _new_task(data, t)
                    imported += 1

                _write_kanban(kanban_dir, data)
                return self._json({"imported": imported, "updated": updated, "skipped": skipped, "mode": mode})

            if rest == ["tasks", "bulk"]:
                d = self._body()
                data = _read_kanban(kanban_dir)
                ids = []
                for item in d.get("tasks", []):
                    data, task = _new_task(data, item)
                    ids.append(task["id"])
                _write_kanban(kanban_dir, data)
                return self._json({"created": len(ids), "ids": ids}, 201)

            if rest == ["decisions"]:
                d = self._body()
                data = _read_decisions(kanban_dir)
                data, dec = _new_decision(data, d)
                _write_decisions(kanban_dir, data)
                return self._json(dec, 201)

            if rest == ["runs"]:
                d = self._body()
                if not (d.get("agent") or "").strip():
                    return self._json({"error": "agent required"}, 400)
                data = _read_runs(kanban_dir)
                data, run = _new_run(data, d)
                _write_runs(kanban_dir, data)
                # Derive the linked task's tokens_used from its runs (board stays correct).
                _sync_task_tokens(kanban_dir, run.get("task_id"), data["runs"])
                return self._json(run, 201)

            if rest == ["worker", "claim"]:
                result, error, status = _runtime_claim(kanban_dir, self._body())
                return self._json(result if not error else {"error": error}, status)

            if rest == ["worker", "heartbeat"]:
                result, error, status = _runtime_heartbeat(kanban_dir, self._body())
                return self._json(result if not error else {"error": error}, status)

            if rest in (["worker", "complete"], ["worker", "fail"]):
                outcome = "complete" if rest[-1] == "complete" else "fail"
                result, error, status = _runtime_finish(kanban_dir, self._body(), outcome)
                return self._json(result if not error else {"error": error}, status)

            if rest == ["runtime", "action"]:
                result, error, status = _runtime_action(kanban_dir, self._body())
                return self._json(result if not error else {"error": error}, status)

            if rest == ["archive"]:
                # POST to archive = archive done tasks
                data = _read_kanban(kanban_dir)
                done_tasks = [t for t in data["tasks"] if t.get("status") == "done"]
                if not done_tasks:
                    return self._json({"archived": 0, "message": "no done tasks to archive"})
                _archive_tasks(kanban_dir, done_tasks)
                data["tasks"] = [t for t in data["tasks"] if t.get("status") != "done"]
                _write_kanban(kanban_dir, data)
                return self._json({"archived": len(done_tasks)})

        self.send_response(404)
        self.end_headers()

    def do_PUT(self):
        return self._guarded(self._put)

    def _put(self):
        p = urlparse(self.path).path.rstrip("/")
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, kanban_dir, rest = self._resolve_project(parts)
            if not pkey:
                return self._json({"error": "unknown project"}, 404)

            # /api/{project}/tasks/{id}
            if len(rest) == 2 and rest[0] == "tasks":
                tid = _parse_id(rest[1])
                d = self._body()
                data = _read_kanban(kanban_dir)
                task = next((t for t in data["tasks"] if t["id"] == tid), None)
                if not task:
                    return self._json({"error": "not found"}, 404)
                if d.get("status") == "done" and not _managed_done_allowed(kanban_dir, task):
                    return self._json({"error": "managed task requires a passed test gate and approval"}, 409)
                _update_task(task, d)
                _write_kanban(kanban_dir, data)
                return self._json(task)

            if len(rest) == 2 and rest[0] == "decisions":
                did = _parse_id(rest[1])
                d = self._body()
                data = _read_decisions(kanban_dir)
                dec = next((x for x in data["decisions"] if x["id"] == did), None)
                if not dec:
                    return self._json({"error": "not found"}, 404)
                _update_decision(dec, d)
                _write_decisions(kanban_dir, data)
                return self._json(dec)

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        return self._guarded(self._delete)

    def _delete(self):
        p = urlparse(self.path).path.rstrip("/")
        if p.startswith("/api/"):
            parts = p[5:].split("/")
            pkey, kanban_dir, rest = self._resolve_project(parts)
            if not pkey:
                return self._json({"error": "unknown project"}, 404)

            if len(rest) == 2 and rest[0] == "tasks":
                tid = _parse_id(rest[1])
                data = _read_kanban(kanban_dir)
                data["tasks"] = [t for t in data["tasks"] if t["id"] != tid]
                _write_kanban(kanban_dir, data)
                return self._json({"deleted": tid})

            if len(rest) == 2 and rest[0] == "decisions":
                did = _parse_id(rest[1])
                data = _read_decisions(kanban_dir)
                data["decisions"] = [x for x in data["decisions"] if x["id"] != did]
                _write_decisions(kanban_dir, data)
                return self._json({"deleted": did})

        self.send_response(404)
        self.end_headers()


# ── Main ────────────────────────────────────────────

def main():
    port = 4242

    if len(sys.argv) > 1 and sys.argv[1] == "configure-sync":
        if len(sys.argv) < 5:
            print("Usage: server.py configure-sync <endpoint> <dashboard> <project_key> [project_key...]", file=sys.stderr)
            raise SystemExit(2)
        secret = os.environ.get("VIBE_HARNESS_SYNC_SECRET") or getpass.getpass("Upload secret: ")
        if not secret:
            print("Upload secret is required", file=sys.stderr)
            raise SystemExit(2)
        cfg = {
            "enabled": True,
            "endpoint": sys.argv[2],
            "secret": secret,
            "dashboards": {sys.argv[3]: sys.argv[4:]},
        }
        _atomic_json(SYNC_CONFIG_PATH, cfg)
        try:
            os.chmod(SYNC_CONFIG_PATH, 0o600)
        except OSError:
            pass
        print(f"Remote sync configured: {SYNC_CONFIG_PATH}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        if not _load_sync_config():
            print(f"Remote sync is not configured: {SYNC_CONFIG_PATH}", file=sys.stderr)
            raise SystemExit(2)
        _sync_worker(set())
        if os.path.exists(SYNC_PENDING_PATH):
            print(f"Remote sync failed; pending snapshot: {SYNC_PENDING_PATH}", file=sys.stderr)
            raise SystemExit(1)
        print("Remote sync complete")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "register":
        key = sys.argv[2]
        name = sys.argv[3] if len(sys.argv) > 3 else key
        kanban_dir = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.getcwd(), "vibe-harness")
        projects = register_project(key, name, kanban_dir)
        print(f"Registered: {key} → {kanban_dir}")
        print(f"Total projects: {len(projects)}")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 4242
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        # Legacy mode: server.py <path> <port> <name>
        path_arg = sys.argv[1]
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 4242
        name = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(os.path.dirname(os.path.dirname(path_arg)))
        key = name.replace(".", "_").replace(" ", "_").replace("-", "_").lower()
        # Convert old db_path to kanban_dir
        kanban_dir = os.path.dirname(path_arg) if path_arg.endswith(".db") else path_arg
        register_project(key, name, kanban_dir)
        print(f"Auto-registered: {key} ({name})")

    # Init all registered projects
    projects = load_projects()
    for _key, info in projects.items():
        kdir = info.get("kanban_dir", "")
        # Backward compat: convert old db_path
        if not kdir and "db_path" in info:
            kdir = os.path.dirname(info["db_path"])
        if kdir and os.path.exists(os.path.dirname(kdir)):
            init_kanban(kdir)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    def shutdown(sig, frame):
        server.shutdown()
        sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Vibe Engineering v5 — http://localhost:{port}/kanban")
    print(f"  Projects: {', '.join(projects.keys()) if projects else '(none)'}")
    print("  Storage: JSON (git-friendly)")
    if _load_sync_config():
        print(f"  Remote sync: enabled ({SYNC_CONFIG_PATH})")
        _schedule_remote_sync(delay=0.1)
        _start_mission_watcher()
        print("  Mission watch: enabled (1s polling)")
        _start_remote_command_poller()
        print("  Remote approvals: enabled (5s polling)")
    _start_runtime_reaper()
    print("  Worker runtime: enabled (5s lease reaper)")
    print("  Ctrl+C to stop")
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
