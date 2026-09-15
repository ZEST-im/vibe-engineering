#!/usr/bin/env python3
"""gh_surface.py — 칸반을 정본으로 두고 GitHub 을 공개 표면으로 쓴다.

## 순수 파생과 네트워크를 가른다

`PHASES.md` → 릴리스 노트, `kanban.json` → 승격 대상은 **입력만 있으면 정해진다.**
그 층은 파일도 네트워크도 건드리지 않아 고정 입력으로 검사할 수 있다.
`gh` 를 부르는 층은 얇게 두고 가용성 게이트 뒤에 둔다 — CI 에는 인증이 없다.

## 외부 행위는 dry-run 이 기본이다

이슈·릴리스·프로젝트는 **만들면 남는다.** `--apply` 가 없으면 무엇을 할지 출력만 한다.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

# Windows cp949 콘솔에서 '—' 같은 문자가 크래시를 낸다. 사용자가 PYTHONUTF8=1 을 손으로
# 붙여야 돌아가던 문제라 스크립트가 직접 보장한다. reconfigure 가 없으면 no-op.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# `git push` 는 유일하게 네트워크로 나가는 git 호출이다 — 자격증명 프롬프트가 뜨면
# 화면에 아무것도 안 보이는 채로 멈춘다. 무인(unattended) 실행에서 그건 "성공도
# 실패도 아닌 채로 영원히 걸림" 이라 시간제한을 둔다.
_PUSH_TIMEOUT = 30

# `gh` 호출 셋도 같은 이유로 시간제한이 필요하다 — 특히 `gh release create` 는
# **태그가 이미 push 된 뒤**에 불린다. 이게 멈추면 태그는 이미 공개돼 있는데 화면엔
# 아무것도 안 보이는 채로 영원히 걸린다 — push 가 실패하는 것보다 나쁘다(실패는
# 최소한 보인다).
_GH_AUTH_TIMEOUT = 15       # `gh auth status` — 로컬 토큰 확인, 가볍다
_GH_RELEASE_VIEW_TIMEOUT = 20   # `gh release view` — 조회 1건
_GH_RELEASE_CREATE_TIMEOUT = 60  # `gh release create` — 쓰기 + 노트 업로드, 느린 회선을 감안해 여유를 둔다
_GH_ISSUE_CREATE_TIMEOUT = 60   # `gh issue create` — 쓰기. 멈추면 번호를 못 읽어 orphan 이 된다
_GH_ISSUE_EDIT_TIMEOUT = 60     # `gh issue edit` — 쓰기(갱신)

DONE_PHASE = re.compile(r"^##\s+(PHASE_\w+)\s+✅\s*DONE\s*\(([0-9-]+)\)\s*$", re.M)
# 상태와 무관하게 Phase 헤딩을 잡는다 — 번호 충돌은 완료 전에 난다.
ANY_PHASE = re.compile(r"^##\s+(PHASE_\w+)", re.M)


class MissingToolFile(RuntimeError):
    """이 도구 **자신의** 파일이 지금 레이아웃에 없다.

    `scripts/setup.py` 는 `gh_surface.py` 를 `~/.claude/skills/vibe-harness/` 에 평평하게
    설치한다 — 거기서는 `ROOT` 가 `~/.claude/skills` 가 되어 `tests/` 도 `scripts/` 도
    없다. 그 자리에서 실행하면 `FileNotFoundError` 트레이스백만 남았다: 무엇이 없는지도,
    뭔가 만들어졌는지도 말해주지 않는 실패다.

    **닫힌 채로 실패한다** — 무엇이 없는지와 "아무것도 만들지 않았다"를 말하고 0 이
    아닌 코드로 끝낸다. 파일을 옮겨서 설치본에서도 돌게 만들지 않는다: 검사 규칙이
    없는 채로 공개 표면에 쓰는 것이 이 도구가 막으려는 바로 그 일이다.
    """


def duplicate_phases(body):
    """같은 Phase 번호로 열린 헤딩이 둘 이상인가. `{이름: 횟수}` 를 돌려준다.

    2026-09-12 에 두 머신이 같은 날 `PHASE_PMF14` 를 각각 열었다. 한쪽은 "공개
    표면", 다른 쪽은 "동시성". `docs/PROGRESS.md` 에 같은 번호의 헤딩이 둘 생겼는데
    **두 헤딩이 파일의 다른 구역에 있어 자동 병합이 충돌로 보지 않았다.** 나중에
    사람이 읽다가 발견했고 수습에 하루가 들었다.

    원인은 `PHASES.md` 가 gitignore 대상이라 **머신마다 따로 있다**는 것이다 —
    다음 번호가 무엇인지 아는 공유된 자리가 없다. 태스크 id 는 접두어로 머신을
    갈라 이미 막고 있는데 Phase 번호에는 그 장치가 없다.

    번호 발급 자체를 공유하려면 `PHASES.md` 를 공개해야 하는데 그 안에 내부 기록이
    있어 그럴 수 없다. 그래서 **발급을 막는 대신 충돌을 소리나게 만든다** — 추적되는
    파일에서 중복을 세고, 검사가 그것을 잡는다. 조용히 지나가지 않는 것이 목표다.

    `✅ DONE` 만 보지 않는다. 실제 사고에서 한쪽은 `🚧 진행 중` 이었다 — 완료된
    것만 세면 정확히 그 사고를 놓친다.
    """
    counts = {}
    for m in ANY_PHASE.finditer(body or ""):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return {name: n for name, n in counts.items() if n > 1}


def phase_sections(body):
    """`PHASES.md` 본문에서 완료 Phase 절을 뽑는다. **파일이 아니라 텍스트를 받는다.**"""
    out = {}
    hits = list(DONE_PHASE.finditer(body or ""))
    for i, m in enumerate(hits):
        start = m.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        section = body[start:end]
        title = ""
        for line in section.splitlines():
            if line.startswith("> "):
                title = line[2:].strip()
                break
        out[m.group(1)] = {
            "title": title,
            "date": m.group(2),
            "body": section.strip(),
        }
    return out


def release_notes(body, phase):
    """한 Phase 의 릴리스 노트(전체 본문). 없으면 **`None`** — 빈 문자열이면 빈 릴리스가
    생긴다.

    **더 이상 공개 표면이 아니다** — 태그·릴리스에는 `release_summary()` 가 뽑아내는
    한 줄만 실린다. 이 함수는 그 요약이 나온 소스로 남아 있을 뿐이다(내부 기록용).
    """
    sec = phase_sections(body).get(phase)
    if sec is None:
        return None
    head = f"## {sec['title']}" if sec["title"] else f"## {phase}"
    return f"{head}\n\n{sec['body']}\n"


def release_summary(body, phase):
    """한 Phase 의 **공개되는** 한 줄 요약 — 태그 메시지와 `gh release create --notes`
    에 실제로 실리는 텍스트다. `release_notes()` 의 ~4KB 본문은 여기 실리지 않는다:
    그 본문은 이 요약이 뽑혀 나온 소스일 뿐, 공개할 필요가 없었다(사용자가 어느
    버전을 쓰는지 알려주는 데는 태그 + 한 줄이면 충분하다).

    Phase 를 못 찾으면 `release_notes()` 와 같은 신호로 **`None`** — 빈 문자열이면
    빈 게 생겼다는 뜻이 되어 버린다. 한 줄 요약이 없으면(`> ` 표시가 없던 절) Phase
    이름 자체로 대체한다 — 빈 태그 메시지보다는 낫다.
    """
    sec = phase_sections(body).get(phase)
    if sec is None:
        return None
    return sec["title"] or phase


# 그 Phase 를 **주어로** 완료를 선언한 표현. 인계·개시 언급과 구별한다.
_CLOSING = ("완료", "종료", "마무리", "완결")
# 이 말이 Phase 이름 **앞이나 뒤** 가까이 있으면 그 Phase 의 경계가 아니다 (인계·개시).
# 예: "PMF14 개시 + PMF13 마무리 뒤" — "개시" 는 PMF13 보다 앞에 있지만 이 커밋을
# "다음 Phase 를 열며 지난 Phase 마무리를 언급"으로 만든다. 뒤쪽 근접("PMF11 이전
# 완료")도 같은 이유로 걸러야 해서 앞·뒤 창을 모두 본다.
_NOT_CLOSING = ("개시", "넘긴다", "넘김", "이전", "선행")

_WINDOW = 12


def boundary_candidates(log_lines, phase):
    """`<sha> <date> <subject>` 줄에서 그 Phase 의 경계 후보를 고른다.

    **추측하지 않는다.** 후보가 없으면 빈 목록이고, 그때는 태깅하지 않는다.
    """
    out = []
    pat = re.compile(r"(?<![A-Z0-9])" + re.escape(phase) + r"(?![0-9])")
    for line in log_lines:
        parts = line.split(" ", 2)
        if len(parts) < 3:
            continue
        sha, date, subject = parts
        m = pat.search(subject)
        if not m:
            continue
        before = subject[max(0, m.start() - _WINDOW):m.start()]
        after = subject[m.end():m.end() + _WINDOW]
        strong = (any(w in after for w in _CLOSING)
                  and not any(w in before for w in _NOT_CLOSING)
                  and not any(w in after for w in _NOT_CLOSING))
        out.append({"sha": sha, "date": date, "subject": subject,
                    "confidence": "strong" if strong else "weak"})
    out.sort(key=lambda c: 0 if c["confidence"] == "strong" else 1)
    return out


def tag_plan(phases_body, log_lines):
    """무엇을 태깅할지. **못 그은 것도 이유와 함께 목록에 남긴다.**

    보류 이유는 두 가지를 구분한다 — "후보가 아예 없다" 와 "후보는 있지만 강한
    것이 없다"(약한 후보 수를 같이 적는다). 실측(PMF02·03·06·09·14)에서 보류 9건
    중 5건이 후자였다 — 뭉뚱그리면 사람이 직접 들여다볼 가치가 있는지 판단할
    신호가 사라진다.
    """
    plan = []
    for phase, _sec in sorted(phase_sections(phases_body).items()):
        short = phase.replace("PHASE_", "")
        all_cands = boundary_candidates(log_lines, short)
        strong = [c for c in all_cands if c["confidence"] == "strong"]
        top = strong[0] if strong else None
        if top:
            reason = None
        elif all_cands:
            reason = (f"완료를 선언한 커밋은 없다 — 약한 후보 {len(all_cands)}건은 있다"
                      "(추측하지 않는다)")
        else:
            reason = "완료를 선언한 커밋이 없다 — 추측하지 않는다"
        plan.append({
            "phase": phase,
            "tag": f"phase/{short}",
            "sha": top["sha"] if top else None,
            "notes": release_notes(phases_body, phase) if top else None,
            "summary": release_summary(phases_body, phase) if top else None,
            "skipped_reason": reason,
        })
    return plan


def promotable(tasks):
    """올릴 것. **`share` 가 참이고 이슈 번호가 없는 것만.**"""
    return [t for t in tasks or [] if t.get("share") and not t.get("issue")]


def updatable(tasks):
    """이미 올라간 것. 번호가 있으면 **갱신이지 생성이 아니다.**"""
    return [t for t in tasks or [] if t.get("share") and t.get("issue")]


# id 가 없을 때 쓰는 대체 문자열. 공개 본문과 로그가 **같은 문자열**을 써야 한다.
_NO_ID = "?"


def board_id(task):
    """보드 id 하나의 **유일한** 파생. 공개되는 본문(`issue_payload`)과 화면 로그가
    각자 다르게 유도하면(`str(t.get("id") or "?")` 대 `str(t.get("id"))`) id 없는
    태스크에서 본문은 `보드 id: ?`, 로그는 `None: 이슈 #N ...` 이 되어 **올라간 이슈를
    어느 태스크로도 되짚을 수 없다** — 승격이 단방향이라 그 추적이 전부다.
    """
    return str((task or {}).get("id") or _NO_ID)


def id_problems(tasks):
    """승격 대상의 **보드 id** 문제. 순수 — 네트워크로 나가기 전에 돈다.

    생성 뒤 칸반에 번호를 되돌려 적는 것이 중복 생성을 막는 유일한 장치인데,
    `kanban_edit.set_task` 는 id 로 **맨 처음 맞는 태스크 하나**를 찾아 거기 적고
    멈춘다. 그래서 id 가 겹치면: 두 이슈가 만들어지고, 나중 번호가 앞 번호를 덮어
    번호는 하나만 남고, 번호를 못 받은 쪽은 **매 실행마다 다시 승격된다** — 끝없는
    중복 생성인데 화면에는 "실패 0" 으로 보인다. id 가 아예 없으면 적을 자리 자체가
    없다(그 쓰기는 `SystemExit("태스크 ? 없음")` 으로 실패한다 — orphan 이슈다).

    둘 다 **보드가 이미 깨져 있다는 뜻**이라 고르는 문제가 아니다. 위생 게이트와 같은
    태도로 전체를 거부한다.
    """
    ids = [board_id(t) for t in tasks or []]
    counts = {}
    for i in ids:
        counts[i] = counts.get(i, 0) + 1
    return {
        "duplicate": sorted(i for i, n in counts.items() if n > 1 and i != _NO_ID),
        "missing": sum(1 for i in ids if i == _NO_ID),
    }


# 승격된 이슈 본문의 마지막 줄. 이슈만 보고 어디가 정본인지 알 수 있어야 한다 —
# 승격은 단방향이라, GitHub 쪽에 적은 진행은 보드로 돌아오지 않는다.
_PROMOTE_FOOTER = ("이 이슈는 vibe-harness 보드에서 승격됐다. 진행 기록의 정본은 보드이고, "
                   "승격은 단방향이다.")


def issue_payload(task):
    """태스크 하나에서 **실제로 공개될 텍스트**를 만든다. 순수 — 파일도 네트워크도
    건드리지 않아 고정 입력으로 검사할 수 있다.

    **`details` 는 싣지 않는다.** 그 필드는 내부 작업 보고서다(변경한 파일, 기술 결정,
    후속 메모). 릴리스 노트에서 이미 같은 실수를 잡았다 — 내부 본문 ~4KB 를 공개
    표면에 그대로 실으려다 한 줄 요약으로 잘라냈다(`release_summary` 참고). 여기서도
    같은 결정을 한다: 공개되는 건 **사람이 제목으로 쓴 한 줄 + 보드에서 파생되는
    분류 몇 개**뿐이다.

    제목이 비면 `gh` 가 거부하거나 제목 없는 이슈가 남는다 — 보드 id 로 대체한다
    (`release_summary` 가 요약 없는 절을 Phase 이름으로 대체하는 것과 같은 태도).
    """
    task = task or {}
    tid = board_id(task)
    title = (task.get("title") or "").strip() or f"(제목 없음) {tid}"
    lines = [f"- 보드 id: {tid}"]
    for label, key in (("Phase", "phase"), ("분류", "category"), ("상태", "status")):
        value = str(task.get(key) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")
    tail = "\n".join(lines) + "\n\n" + _PROMOTE_FOOTER
    note = (task.get("share_note") or "").strip()
    # 사람이 쓴 글이 먼저다. 분류 몇 줄을 앞세우면 정작 읽어야 할 것이 묻힌다.
    return {"title": title, "body": (note + "\n\n---\n" + tail) if note else tail}


def missing_share_note(tasks):
    """공유 표시는 있는데 **공개용 설명이 없는** 태스크의 id.

    설명이 없어도 이슈는 만들어진다 — 막지 않는다. 다만 조용히 내보내지 않는다.
    그렇게 만든 이슈는 id·분류·상태만 담아서, 받는 사람이 무엇을 해야 할지 알 수
    없다(실제로 첫 dry-run 이 그런 이슈 둘을 내놓았고 그래서 이 필드가 생겼다).
    """
    return [board_id(t) for t in tasks or []
            if t.get("share") and not (t.get("share_note") or "").strip()]


def _run(argv, env=None, timeout=None):
    """`env`/`timeout` 은 기본 호출은 그대로 두고 필요한 곳(네트워크로 나가는 `git
    push`)에만 적용하기 위한 것 — 나머지 로컬 전용 git 호출은 손대지 않는다.
    """
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"{timeout}초 동안 응답이 없어 중단했다"
    return done.returncode, done.stdout, done.stderr


def gh_available(runner=None, need_scope=None):
    """`gh` 를 쓸 수 있는가. **없다고 실패시키지 않는다 — 이유를 돌려준다.**

    `runner` 를 안 넘기면(실제 운영 경로) `_run` 을 시간제한과 함께 부른다. 주입된
    `runner`(테스트) 는 그대로 한 인자만 받고 불린다 — 신호(호출 계약)를 바꾸지
    않는다.
    """
    runner = runner or (lambda argv: _run(argv, timeout=_GH_AUTH_TIMEOUT))
    try:
        code, out, err = runner(["gh", "auth", "status"])
    except FileNotFoundError:
        return False, "gh 가 설치돼 있지 않다 — GitHub 표면 작업을 건너뛴다"
    except OSError as exc:
        return False, f"gh 를 실행할 수 없다 ({exc}) — 건너뛴다"
    if code != 0:
        return False, f"gh 인증이 없다 — `gh auth login` 이 필요하다 ({err.strip()[:80]})"
    if need_scope and f"'{need_scope}'" not in out:
        return False, (f"토큰에 `{need_scope}` 스코프가 없다 — "
                       f"`gh auth refresh -s {need_scope}` 로 추가한다")
    return True, "gh 사용 가능" + (f" ({need_scope} 스코프 확인됨)" if need_scope else "")


def _log_lines(root, runner=None):
    """`git log` 를 읽어 `tag_plan` 이 먹을 줄 목록으로 만든다.

    **CLI 층의 일이다** — `tag_plan` 은 파일도 git 도 건드리지 않는다(순수 유지).
    `private/PHASES.md` 가 없을 때와 같은 태도다 — 못 읽으면 **크게 실패한다.**
    조용히 빈 로그로 넘어가면 "경계 후보가 없음" 과 "레포를 못 읽음" 이 똑같아
    보이고, 그러면 `--apply` 는 아무것도 못 만들고도 0 으로 끝나 깨끗한 실행과
    구분이 안 된다.
    """
    runner = runner or _run
    try:
        code, out, err = runner(
            ["git", "-C", root, "log", "--format=%h %ad %s", "--date=short"])
    except OSError as exc:
        raise SystemExit(
            f"git log 를 실행하지 못했다 ({exc}) — {root} 를 git 레포로 읽을 수 있는지 "
            "확인해야 한다. 조용히 빈 로그로 넘어가면 '경계 없음' 과 '못 읽음' 을 구분할 "
            "수 없다."
        ) from exc
    if code != 0:
        raise SystemExit(
            f"git log 가 실패했다 (`{root}` 가 git 레포가 아닐 수 있다): "
            f"{err.strip()[:200]}\n"
            "  조용히 빈 로그로 넘어가면 '경계 없음' 과 '못 읽음' 을 구분할 수 없다.")
    return [line for line in out.splitlines() if line.strip()]


def _tag_exists_locally(root, tag, runner=None):
    """이 이름의 태그가 로컬에 이미 있는가."""
    runner = runner or _run
    code, out, _err = runner(["git", "-C", root, "tag", "-l", tag])
    return code == 0 and out.strip() == tag


def _resolve_full_sha(root, ref, runner=None):
    """짧은 sha(`%h`)든 태그 이름이든, 그게 가리키는 커밋을 40자 전체 형태로 돌려준다.

    **영구히 남는 것(태그 객체)에 쓰기 직전에만 부른다** — dry-run 출력과
    `boundary_candidates` 픽스처는 짧은 sha(`%h`)에 맞춰져 있으니 그쪽은 그대로
    둔다. 애매한 짧은 sha 를 공개 태그에 그대로 박아 넣지 않기 위한 것이고, 이미
    있는 로컬 태그가 **계획과 같은 커밋을 가리키는지** 확인할 때도 같은 방식으로 쓴다
    (이름만 같은 다른 커밋을 그대로 push 하면 안 된다).
    """
    runner = runner or _run
    code, out, _err = runner(["git", "-C", root, "rev-parse", f"{ref}^{{commit}}"])
    if code != 0:
        return None
    return out.strip()


def _repo_slug(root, runner=None):
    """`gh` 호출을 이 레포에 고정하는 `-R` 값. `origin` 이 없으면 `None`.

    `gh` 는 매 호출을 프로세스의 현재 디렉터리로 리포를 판단한다 — `-C root` 를
    받는 git 호출과 달리 아무 근거 없이 다른 레포를 향할 수 있다.
    """
    runner = runner or _run
    code, out, _err = runner(["git", "-C", root, "remote", "get-url", "origin"])
    if code != 0:
        return None
    return out.strip()


def _release_exists(tag, repo_slug, gh_runner):
    code, _out, _err = gh_runner(
        ["gh", "release", "view", tag, "-R", repo_slug], timeout=_GH_RELEASE_VIEW_TIMEOUT)
    return code == 0


def _load_deny_terms(root):
    """`private/DENY.txt` 에서 정확 금칙 문자열을 읽는다.

    이 파일은 gitignore 대상이라 CI 와 다른 머신에는 없다. **없다고 조용히 검사를
    건너뛰지 않는다** — `tests/test_public_hygiene.py` 의 `ExactDenyListTest` 와
    같은 태도다: 없으면 이유를 말하고 건너뛴다("못 본 것"과 "깨끗한 것"은 다르다).
    `None` 은 "파일이 없어 검사 안 함", `[]` 는 "파일은 있지만 항목이 비어 있음"으로
    서로 구분한다 — **호출부가 이 둘을 다르게 다뤄야** 뜻이 있다(`_run_tag` 의
    `deny_corrupted` 참고).
    """
    path = os.path.join(root, "private", "DENY.txt")
    if not os.path.exists(path):
        # 호출부가 둘이다 — `_run_tag`(private/PHASES.md 에서 파생되는 한 줄 요약)와
        # `_run_promote`(kanban.json 에서 파생되는 제목+본문). 한쪽 말로 적으면
        # 나머지 한쪽에서는 **검사 범위를 잘못 알려주는 문장**이 된다: "공개 요약" 이라고
        # 단정하면 promote 출력이 "제목만 봤다"는 뜻으로 읽힌다. 이 줄은 DENY.txt 가
        # 없는 모든 머신(CI 포함)에서 매번 찍히므로 양쪽에 맞는 말이어야 한다.
        return None, ("private/DENY.txt 없음 — 정확 문자열 검사만 건너뛴다 "
                       "(구조 규칙 R1–R4 는 이 게이트가 공개되는 텍스트에 직접 적용한다 — "
                       "tests/test_public_hygiene.py 는 커밋된 추적 파일을 훑을 뿐이라, "
                       "지금 이 실행이 밖으로 내보낼 텍스트를 실제로 보는 건 이 게이트뿐이다; "
                       "CI 와 다른 머신엔 이 파일이 없는 게 정상이다)")
    with open(path, encoding="utf-8") as fh:
        terms = [t.strip() for t in fh if t.strip() and not t.startswith("#")]
    # 호출부가 둘이다(`_run_tag` 의 요약, `_run_promote` 의 제목+본문) — 어느 쪽에도
    # 맞는 말로 적는다. 여기서 "요약"이라고 단정하면 promote 출력이 "제목만 봤다"는
    # 뜻으로 읽혀, 사람이 승인 근거로 읽는 문장이 실제 검사 범위와 어긋난다.
    return terms, f"private/DENY.txt 로드 — 금칙 문자열 {len(terms)}개로 공개 텍스트를 검사한다"


def _deny_hit_count(text, terms):
    """`text`(공개되는 텍스트) 안에 있는 금칙 문자열 적중 **수**. 문자열 자체는
    절대 돌려주지 않는다 —

    세는 것과 드러내는 것은 다르다. 이 값을 로그·리포트에 찍는 건 안전하지만,
    적중한 문자열 자체를 찍으면 그 출력이 새 유출원이 된다.
    """
    if not terms or not text:
        return 0
    return sum(1 for t in terms if t in text)


_STRUCTURAL_RULES = None


def _structural_rules():
    """`tests/test_public_hygiene.py` 의 R1–R4 를 그대로 불러 쓴다 — **사본을 새로
    만들지 않는다.** 두 벌을 두면 반드시 어긋난다: 이 레포가 이미 두 번 겪은 실패이고,
    그 파일 자신이 그 이유로 금칙어 목록을 자기 안에 두지 않는다고 적어 두었다.

    `ROOT`(이 스크립트가 실제로 있는 레포)에서 읽는다 — `_run_tag` 의 `root` 인자
    (태깅 **대상** 레포, 테스트에서는 임시 디렉터리)가 아니다. 이 규칙들은 도구
    자신의 코드지 태깅 대상의 데이터가 아니라서, 대상이 무엇이든 항상 같은 곳에서
    읽는다.

    **설치본에는 이 파일이 없다** — `setup.py` 는 이 스크립트를
    `~/.claude/skills/vibe-harness/` 에 평평하게 복사하고, 거기서 `ROOT` 는
    `~/.claude/skills` 다(`tests/` 가 없다). 그때는 `MissingToolFile` 로 닫힌 채
    실패한다 — 트레이스백으로 죽지도, 검사 없이 공개하지도 않는다.
    """
    global _STRUCTURAL_RULES
    if _STRUCTURAL_RULES is None:
        path = os.path.join(ROOT, "tests", "test_public_hygiene.py")
        if not os.path.exists(path):
            raise MissingToolFile(
                f"공개 텍스트 검사 규칙(R1–R4)을 찾지 못했다: {path}\n"
                "  이 파일은 레포 체크아웃에만 있다 — 설치본"
                "(~/.claude/skills/vibe-harness/)에는 tests/ 가 없다.\n"
                "  검사 없이 공개하지 않는다: 아무것도 만들지 않고 멈춘다. "
                "레포에서 `python3 scripts/gh_surface.py ...` 로 실행한다.")
        spec = importlib.util.spec_from_file_location("_gh_surface_hygiene_rules", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _STRUCTURAL_RULES = mod.RULES
    return _STRUCTURAL_RULES


def _structural_hit_count(text):
    """R1–R4(값이 아니라 모양) 를 **공개되는 텍스트**(요약)에 적용한다 —
    `private/DENY.txt` 유무와 무관하게 **항상** 돈다. 실제 사고 두 건 모두 이
    규칙만으로 잡혔다(`tests/test_public_hygiene.py` 의 기록) — `DENY.txt` 가
    없는 머신(CI 포함)에서도 이 층은 살아 있어야 `--apply` 가 "아무 내용 검사도
    안 하고 공개"하는 구멍이 남지 않는다.
    """
    if not text:
        return 0
    lines = text.splitlines()
    return sum(1 for _name, pattern, _why in _structural_rules()
               for line in lines if pattern.search(line))


def _hygiene_hit_count(text, deny_terms):
    """공개되는 텍스트 검사 총합 — 구조 규칙(항상) + 정확 금칙어(파일 있을 때만).
    **게이트는 실제로 공개되는 텍스트(요약)만 본다** — 공개되지 않는 전체 노트를
    검사하면 아무도 안 볼 텍스트 때문에 거부하거나, 반대로 실제로 나가는 텍스트를
    안 보고 지나칠 수 있다. 문자열 자체는 어느 쪽도 돌려주지 않는다 — 세는 것과
    드러내는 것은 다르다.
    """
    return _structural_hit_count(text) + _deny_hit_count(text, deny_terms)


def _run_tag(plan, root, apply=False, gh_check=None, gh_runner=None):
    """계획을 출력하고, `apply` 일 때만 실제로 태그·push·릴리스를 만든다.

    순서는 **annotated 태그 → `git push origin <tag>` → `gh release create
    --verify-tag`** 다. `gh release create` 는 태그가 없을 때 API 로 lightweight
    태그를 만들어 버리는데, 그러면 로컬의(요약을 담은) annotated 태그와 원격이
    어긋나 이후 `git push --tags` 가 non-fast-forward 로 막힌다. 태그를 먼저
    push 해 두고 `--verify-tag` 로 존재만 확인시키면 이 어긋남이 생기지 않는다.

    idempotency 는 **릴리스 존재 여부**로 판단한다 — 로컬 태그만 보면 "태그는
    있는데 릴리스가 없다"(정확히 복구가 필요한 상태)를 "이미 끝남"으로 잘못
    읽는다. 로컬 태그가 이미 있는데 릴리스가 없으면 이전 실행이 릴리스 단계
    (또는 push 단계)에서 실패했던 것 — 태그 재생성은 건너뛰고 push·릴리스만
    다시 시도한다.

    **공개되는 텍스트는 `p["summary"]`(한 줄) 뿐이다** — `p["notes"]`(전체 본문,
    ~4KB)는 그 요약이 나온 소스로 남을 뿐 태그 메시지에도 `gh release create
    --notes` 에도 실리지 않는다. 게이트도 같은 것만 본다: `p["notes"]` 를 검사하면
    아무도 안 볼 텍스트 때문에 phase 를 거부하거나(오탐), 반대로 실제로 나가는
    한 줄은 검사하지 않고 지나칠 수 있다(누락) — 둘 다 "게이트가 실제 공개 표면과
    어긋난" 상태다.

    공개 텍스트 검사(구조 규칙 + `private/DENY.txt`, 요약에 적용)는 **dry-run
    에서도** 돈다. dry-run 이 보여주는 "N개 태그 가능"은 사용자가 `--apply` 승인
    근거로 보는 숫자다 — 여기서 걸릴 phase 를 숨기면 그 숫자가 거짓말이 된다(실측:
    dry-run 이 "N개" 라고 말하고 `--apply` 가 N−1개만 만드는 사고). 하나라도
    걸리면 `--apply` 는 **아무것도 만들지 않고 전부 멈춘다** — `plan` 은 이름순
    이라, 걸린 phase 뒤로 판정을 미루면 그 앞의(멀쩡한) phase 들은 이미 태그·push·
    릴리스가 끝난 뒤에야 뒤쪽 phase 가 걸렸다는 걸 알게 된다. 한 번 공개되면
    되돌릴 수 없는 작업이라 부분 실행보다 전체 거부가 안전하다.

    `gh_check`/`gh_runner` 는 테스트 주입용 — 기본은 각각 `gh_available`, `_run`.
    git 호출은 로컬 전용(태그·push)이라 실제 `_run` 을 그대로 쓴다.
    """
    gh_check = gh_check or gh_available
    gh_runner = gh_runner or _run

    taggable = [p for p in plan if p["sha"]]
    skipped = [p for p in plan if not p["sha"]]

    # dry-run 에서도 봐야 하므로 `if not apply` 보다 앞에 있다.
    deny_terms, deny_why = _load_deny_terms(root)
    # 파일은 있는데 항목이 없다 — 잘렸거나 손상됐을 수 있다. `None`(파일 없음)과는
    # 다르게 다룬다: `tests/test_public_hygiene.py` 의 `ExactDenyListTest` 도 이
    # 경우를 스킵이 아니라 **하드 실패**로 다룬다. "검사했는데 깨끗하다"와 "검사
    # 자체가 비어 있었다"를 같은 것으로 두면 안 된다.
    deny_corrupted = deny_terms is not None and not deny_terms

    # 구조 규칙(R1–R4)도 같은 함정이 있다 — `RULES` 가 빈 시퀀스면
    # `_structural_hit_count` 는 모든 텍스트에 조용히 0 을 돌려준다. 그러면 "검사했더니
    # 깨끗하다"와 "검사 자체가 비어 있었다"가 겉보기에 똑같아진다. `deny_corrupted`
    # 와 같은 취급 — 몇 개인지 항상 말하고, 0개면 하드 실패한다.
    try:
        structural_rules = _structural_rules()
    except MissingToolFile as exc:
        # 설치본 레이아웃 — 트레이스백 대신 무엇이 없는지 말하고 닫힌 채 끝낸다.
        print(f"\n{exc}")
        return 1
    structural_why = f"구조 규칙(R1–R4) 로드 — {len(structural_rules)}개로 공개 요약을 검사한다"
    structural_corrupted = len(structural_rules) == 0

    # 게이트는 `p["summary"]`(공개되는 한 줄)만 본다 — `p["notes"]`(전체 본문)는
    # 더 이상 어디에도 실리지 않으므로 검사해도 실제 공개 표면과 무관하다.
    hits_by_tag = {}
    for p in taggable:
        hits = _hygiene_hit_count(p["summary"], deny_terms)
        if hits:
            hits_by_tag[p["tag"]] = hits
    clean_count = len(taggable) - len(hits_by_tag)

    for p in plan:
        if p["sha"]:
            if p["tag"] in hits_by_tag:
                print(f"{p['tag']}  {p['sha']}  ({p['phase']})  — 보류: 공개 요약 검사 적중 "
                      f"{hits_by_tag[p['tag']]}건 (문자열은 출력하지 않는다)")
            else:
                print(f"{p['tag']}  {p['sha']}  ({p['phase']})")
        else:
            print(f"{p['phase']}: 보류 — {p['skipped_reason']}")
    print(f"\n{structural_why}")
    if structural_corrupted:
        print("  ⚠ 구조 규칙이 0개다 — R1–R4 가 비었거나 손상됐을 수 있어 이 층을 "
              "신뢰할 수 없다(정확 금칙어 층과는 별개로 무력화된 상태다)")
    print(deny_why)
    if deny_corrupted:
        print("  ⚠ 파일은 있지만 항목이 0개다 — 잘렸거나 손상됐을 수 있어 정확 문자열 "
              "검사를 신뢰할 수 없다(구조 규칙은 위 결과대로 별도로 적용된다)")
    held_back = len(skipped) + len(hits_by_tag)
    print(f"\n{len(plan)}개 Phase 중 {clean_count}개 태그 가능, {held_back}개 보류"
          + (f" (그중 {len(hits_by_tag)}건은 공개 요약 검사 적중)" if hits_by_tag else ""))

    if not apply:
        print("[dry-run] 아무것도 만들지 않았다 — 실행하려면 --apply")
        return 0

    if structural_corrupted:
        print("\n구조 규칙(R1–R4)이 0개다 — 파일이 손상됐을 수 있어 아무것도 만들지 "
              "않는다")
        return 1

    if deny_corrupted:
        print("\nprivate/DENY.txt 가 있지만 비어 있다 — 파일을 확인하기 전엔 아무것도 "
              "만들지 않는다")
        return 1

    if hits_by_tag:
        print(f"\n공개 요약 검사에 걸린 Phase가 {len(hits_by_tag)}개 있다 — "
              f"{', '.join(sorted(hits_by_tag))}. 전부 고치기 전엔 아무것도 만들지 않는다 "
              "(한 번 공개되면 되돌릴 수 없어, 하나라도 걸리면 시작하지 않는다)")
        return 1

    ok, why = gh_check()
    if not ok:
        print(f"\n{why}")
        return 1

    repo_slug = _repo_slug(root)
    if not repo_slug:
        print("\norigin 리모트를 확인하지 못했다 — gh 호출을 이 레포에 고정할 수 없어 "
              "아무것도 만들지 않고 멈춘다")
        return 1

    created = existed = failed = 0
    recovered = []  # 이전 실행이 태그만 만들고 릴리스에서 실패해, 이번에 복구를 시도한 것들
    for p in taggable:
        tag, sha = p["tag"], p["sha"]

        if _release_exists(tag, repo_slug, gh_runner):
            print(f"{tag}: 이미 있다 — 건너뛴다")
            existed += 1
            continue

        full_sha = _resolve_full_sha(root, sha)
        if not full_sha:
            print(f"{tag}: sha({sha}) 를 전체 형태로 확정하지 못해 건너뛴다")
            failed += 1
            continue

        if _tag_exists_locally(root, tag):
            # 이름만 같은 다른 커밋을 가리킬 수 있다 — 그걸 그대로 push 하면 dry-run 이
            # 보여준 sha 와 실제로 공개되는 커밋이 어긋난다. push 전에 반드시 맞춰본다.
            existing_sha = _resolve_full_sha(root, tag)
            if existing_sha != full_sha:
                print(f"{tag}: 로컬에 이미 있는 태그가 계획과 **다른 커밋**을 가리킨다 — "
                      f"push 하지 않는다. 계획: {full_sha}, 기존 태그: "
                      f"{existing_sha or '확인 불가'}. 사람이 직접 태그를 확인해 정리해야 한다 "
                      f"(`git tag -d {tag}` 로 지우고 재실행하거나 그대로 둘지 판단)")
                failed += 1
                continue
            recovered.append(tag)
            print(f"{tag}: 태그는 있지만 릴리스가 없다 — 이전 --apply 가 push·릴리스 "
                  "단계에서 실패했던 것으로 보인다. 태그를 다시 만들지 않고 복구를 시도한다")
        else:
            # 공개되는 건 요약 한 줄뿐이다 — `p["notes"]`(전체 본문)는 태그
            # 메시지에 싣지 않는다. annotated 태그를 push 하면 이 메시지 그대로
            # 공개되므로, "노트는 안 실린다"를 release create 보다 먼저 여기서
            # 지켜야 한다.
            message = f"{tag}\n\n{p['summary']}"
            code, _out, err = _run(
                ["git", "-C", root, "tag", "-a", tag, full_sha, "-m", message])
            if code != 0:
                print(f"{tag}: 태그 생성 실패 ({err.strip()[:120]})")
                failed += 1
                continue

        # 무인(unattended) 실행 중 자격증명 프롬프트가 뜨면 화면에 아무것도 안 보이는 채로
        # 영원히 멈춘다 — 프롬프트를 끄고 시간제한을 둬서 "조용히 멈춤"을 막는다.
        no_prompt_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        code, _out, err = _run(["git", "-C", root, "push", "origin", tag],
                               env=no_prompt_env, timeout=_PUSH_TIMEOUT)
        if code != 0:
            if "[rejected]" in err and "already exists" in err:
                # 원격에 이미 다른 커밋을 가리키는 같은 이름의 태그가 있다 — 재실행은
                # 같은 거부를 반복할 뿐이다. 사람의 결정이 필요하다고 명시한다.
                print(f"{tag}: push 가 거부됐다 — 원격에 이미 다른 커밋을 가리키는 태그가 "
                      f"있다. **재실행으로는 못 고친다.** `git push --delete origin {tag}` "
                      f"로 원격 태그를 지우거나 사람이 직접 정리해야 한다 "
                      f"({err.strip()[:160]})")
            else:
                print(f"{tag}: 태그는 로컬에 있지만 push 에 실패했다 — orphan 상태다. "
                      f"원인을 해결한 뒤 --apply 를 다시 실행하면 복구한다 "
                      f"({err.strip()[:160]})")
            failed += 1
            continue

        code, _out, err = gh_runner(
            ["gh", "release", "create", tag, "--verify-tag",
             "--title", tag, "--notes", p["summary"], "-R", repo_slug],
            timeout=_GH_RELEASE_CREATE_TIMEOUT)
        if code != 0:
            print(f"{tag}: 태그·push 는 됐지만 릴리스 생성에 실패했다 — orphan 상태다. "
                  f"--apply 를 다시 실행하면 복구한다 ({err.strip()[:120]})")
            failed += 1
            continue

        print(f"{tag}: 태그 + push + 릴리스 생성 완료")
        created += 1

    print(f"\n생성 {created}, 이미 있음 {existed}, 실패 {failed}")
    if recovered:
        print(f"복구를 시도한 orphan 태그: {', '.join(recovered)}")
    return 0 if failed == 0 else 1


# `gh issue create` 는 만들어진 이슈의 URL 을 stdout 에 찍는다. 그 URL 이 번호를
# 알 수 있는 유일한 근거이고, 번호는 **중복 생성을 막는 유일한 장치**다.
_ISSUE_URL = re.compile(r"https?://\S*?/issues/([0-9]+)\b")


def _issue_ref(text):
    """`gh issue create` 출력에서 (번호, URL). 못 읽으면 `(None, None)` —
    빈 값이나 0 으로 때우지 않는다. 못 읽었다는 건 **이슈는 이미 만들어졌는데 칸반에
    적을 번호가 없다**는 뜻이라, 조용히 넘어가면 다음 실행이 같은 태스크로 이슈를
    하나 더 만든다.
    """
    last = None
    for m in _ISSUE_URL.finditer(text or ""):
        last = m
    if last is None:
        return None, None
    return int(last.group(1)), last.group(0)


def _kanban_issue_writer(kanban_dir):
    """칸반 쓰기는 `scripts/kanban_edit.py` 의 `set_task` 로만 한다.

    직접 `json.dump` 하면 truncate-then-write 라 **읽는 쪽이 반쪽짜리 파일을 본다**
    (실측: 109,409B 에서 파싱 실패). 읽기-수정-쓰기 전 구간의 잠금도 그 안에 있다 —
    여기서 다시 구현하면 두 경로가 조용히 갈라진다.

    **설치본에는 이 파일이 `ROOT` 기준 경로에 없다**(`_structural_rules` 와 같은 이유).
    그때는 `MissingToolFile` — 그리고 이 확인은 `gh` 를 부르기 **전에** 해야 한다:
    이슈를 만든 뒤에야 쓰기 도구가 없다는 걸 알면 그게 바로 orphan 이슈다.
    """
    path = os.path.join(ROOT, "scripts", "kanban_edit.py")
    if not os.path.exists(path):
        raise MissingToolFile(
            f"칸반 쓰기 도구를 찾지 못했다: {path}\n"
            "  이 파일은 레포 체크아웃에만 있다 — 설치본"
            "(~/.claude/skills/vibe-harness/)에는 scripts/ 가 없다.\n"
            "  생성한 이슈 번호를 보드에 되돌려 적을 방법이 없으면 만드는 족족 "
            "orphan 이다: 아무것도 만들지 않고 멈춘다. "
            "레포에서 `python3 scripts/gh_surface.py ...` 로 실행한다.")
    spec = importlib.util.spec_from_file_location("_gh_surface_kanban_edit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def write(task_id, number):
        mod.set_task(kanban_dir, task_id, {"issue": number})
    return write


def _run_promote(tasks, root, apply=False, kanban_dir=None,
                 gh_check=None, gh_runner=None, kanban_writer=None):
    """공유 표시가 달린 태스크를 이슈로. 기본은 dry-run.

    **dry-run 이 찍는 텍스트가 곧 공개될 텍스트다.** 사용자는 이 출력을 읽고
    `--apply` 승인 여부를 정하므로 제목·본문을 글자 그대로 보여준다 — 요약하거나
    줄여 보여주면 승인 근거가 실제 공개물과 달라진다.

    **위생 게이트는 `_run_tag` 와 같은 전체 사전 검사다.** 하나라도 걸리면 아무것도
    만들지 않는다 — 깨끗한 것부터 만들고 가다 중간에 멈추면, 앞의 것은 이미 공개된
    뒤에 뒤의 것이 걸렸다는 걸 알게 된다. 이슈도 태그처럼 한 번 만들면 남는다.
    검사 대상은 **공개되는 텍스트 전체**(제목 + 본문)다 — 제목만 보면 본문으로
    새는 경로가 그대로 남는다. 적중 문자열 자체는 어디에도 찍지 않는다(세는 것과
    드러내는 것은 다르다).

    생성 성공 뒤 **칸반에 번호를 적는 것이 중복 생성을 막는 유일한 장치**다. 그
    쓰기가 실패하면 orphan 이슈다 — `_run_tag` 의 orphan 태그와 같은 태도로 번호와
    URL 을 크게 보고하고, 실행을 성공으로 끝내지 않는다. 그래서 보드 id 검사
    (`id_problems`)도 위생 게이트와 같은 전체 사전 검사다: 되돌려 적을 자리가
    없거나 겹치면 그 유일한 장치가 처음부터 없는 채로 공개하는 셈이다.

    **출력은 아직 일어나지 않은 일을 완료처럼 말하지 않는다.** 목록과 집계는
    거부 문구보다 **위**에 찍히므로(순서상 어쩔 수 없다), 거부된 실행이 성공한
    실행처럼 읽히지 않으려면 그 줄들이 전부 "후보" 를 말해야 한다 — `_run_tag` 가
    "태그 **가능**" 이라고 적는 것과 같은 이유다.
    """
    creates = promotable(tasks)
    updates = updatable(tasks)
    items = [("create", t) for t in creates] + [("update", t) for t in updates]

    # dry-run 에서도 봐야 하므로 `if not apply` 보다 앞에 있다 — `_run_tag` 와 같다.
    deny_terms, deny_why = _load_deny_terms(root)
    deny_corrupted = deny_terms is not None and not deny_terms
    try:
        structural_rules = _structural_rules()
    except MissingToolFile as exc:
        # 설치본 레이아웃 — 트레이스백 대신 무엇이 없는지 말하고 닫힌 채 끝낸다.
        print(f"\n{exc}")
        return 1
    structural_why = (f"구조 규칙(R1–R4) 로드 — {len(structural_rules)}개로 "
                      "공개 텍스트를 검사한다")
    structural_corrupted = len(structural_rules) == 0

    # 보드 id 검사도 **외부 호출 하나 나가기 전에** 끝낸다 — 겹친 id 로 만들어진
    # 이슈는 번호를 적을 자리가 하나뿐이라 되돌릴 수 없는 중복이 무한히 쌓인다.
    problems = id_problems([t for _kind, t in items])

    # `(kind, task, payload, hits)` 를 **자리 순서로** 들고 간다. id 로 사전을 만들면
    # id 가 겹친 보드에서(이 레포가 실제로 겪은 사고다 — 409·410) 뒤엣것이 앞엣것의
    # 텍스트를 덮어, 검사한 것과 올라가는 것이 달라진다.
    entries = [(kind, t, issue_payload(t)) for kind, t in items]
    entries = [(kind, t, payload,
                _hygiene_hit_count(payload["title"] + "\n" + payload["body"], deny_terms))
               for kind, t, payload in entries]
    blocked = [e for e in entries if e[3]]

    for kind, t, payload, hits in entries:
        tid = board_id(t)
        head = "생성 대상" if kind == "create" else f"갱신 대상 #{t.get('issue')}"
        if hits:
            # 걸린 것은 텍스트를 찍지 않는다 — 여기서 찍으면 출력 자체가 새 유출원이다.
            print(f"[보류] {tid} ({head}) — 공개 텍스트 검사 적중 {hits}건 "
                  "(문자열은 출력하지 않는다)")
            continue
        # **아직 아무것도 안 만들었다.** 이 줄은 거부 문구보다 위에 찍히므로 완료처럼
        # 읽히면 거부된 실행이 성공한 실행과 구분되지 않는다.
        print(f"[{head}] {tid} — 아직 만들지 않았다. 게이트를 통과하고 --apply 가 "
              "있으면 아래 텍스트가 그대로 올라간다")
        print("--- title ---")
        print(payload["title"])
        print("--- body ---")
        print(payload["body"])
        print("--- end ---")

    print(f"\n{structural_why}")
    if structural_corrupted:
        print("  ⚠ 구조 규칙이 0개다 — R1–R4 가 비었거나 손상됐을 수 있어 이 층을 "
              "신뢰할 수 없다(정확 금칙어 층과는 별개로 무력화된 상태다)")
    print(deny_why)
    if deny_corrupted:
        print("  ⚠ 파일은 있지만 항목이 0개다 — 잘렸거나 손상됐을 수 있어 정확 문자열 "
              "검사를 신뢰할 수 없다(구조 규칙은 위 결과대로 별도로 적용된다)")

    noteless = missing_share_note([t for _k, t, _p, _h in entries])
    if noteless:
        print(f"\n⚠ 공개용 설명(share_note)이 없는 태스크 {len(noteless)}개 — "
              f"{', '.join(noteless)}. 본문이 id·분류·상태만 담아 받는 사람이 무엇을 "
              "해야 할지 알 수 없다. 막지는 않는다")

    clean_creates = sum(1 for kind, _t, _p, hits in entries if kind == "create" and not hits)
    clean_updates = sum(1 for kind, _t, _p, hits in entries if kind == "update" and not hits)
    # "생성 N건" 이라고 적으면 거부된 실행이 N건을 만든 것처럼 읽힌다 — 이 줄은 아직
    # 후보 수일 뿐이다(`_run_tag` 의 "태그 가능" 과 같다). 실제로 만든 수는 맨 아래
    # 집계(`생성 N, 갱신 N, 실패 N`)에만 나온다.
    print(f"\n{len(entries)}개 대상 중 생성 가능 {clean_creates}건, "
          f"갱신 가능 {clean_updates}건, 보류 {len(blocked)}건"
          + (" (공개 텍스트 검사 적중)" if blocked else ""))

    if problems["duplicate"]:
        print(f"  ⚠ 보드 id 가 겹친 대상이 있다: {', '.join(problems['duplicate'])} — "
              "번호를 되돌려 적을 자리가 하나뿐이라 올리면 매 실행마다 이슈가 하나씩 "
              "더 생긴다(중복 방지 장치가 없는 상태다)")
    if problems["missing"]:
        print(f"  ⚠ 보드 id 가 없는 대상이 {problems['missing']}건 있다 — 번호를 "
              "되돌려 적을 자리가 없어 만드는 족족 orphan 이슈가 된다")

    if not apply:
        print("[dry-run] 아무것도 만들지 않았다 — 실행하려면 --apply")
        return 0

    if structural_corrupted:
        print("\n구조 규칙(R1–R4)이 0개다 — 파일이 손상됐을 수 있어 아무것도 만들지 "
              "않는다")
        return 1

    if deny_corrupted:
        print("\nprivate/DENY.txt 가 있지만 비어 있다 — 파일을 확인하기 전엔 아무것도 "
              "만들지 않는다")
        return 1

    if blocked:
        print(f"\n공개 텍스트 검사에 걸린 태스크가 {len(blocked)}개 있다 — "
              f"{', '.join(sorted(board_id(t) for _k, t, _p, _h in blocked))}. "
              "전부 고치기 전엔 아무것도 만들지 않는다 "
              "(한 번 공개되면 되돌릴 수 없어, 하나라도 걸리면 시작하지 않는다)")
        return 1

    if problems["duplicate"] or problems["missing"]:
        # 위생 게이트와 같은 모양 — 하나라도 걸리면 시작하지 않는다. 다만 이유가
        # 다르다: 텍스트가 더러운 게 아니라 **보드가 이미 깨져 있다.** 그 상태로
        # 올리면 되돌릴 수 없는 중복 이슈가 실행할 때마다 쌓이는데, 화면에는
        # "실패 0" 으로 보인다.
        why = []
        if problems["duplicate"]:
            why.append(f"겹친 id {', '.join(problems['duplicate'])}")
        if problems["missing"]:
            why.append(f"id 없는 태스크 {problems['missing']}건")
        print(f"\n보드 id 가 성립하지 않는다 — {'; '.join(why)}. 아무것도 만들지 않는다 "
              "(생성 뒤 번호를 되돌려 적는 것이 중복 생성을 막는 유일한 장치인데, "
              "적을 자리가 겹치거나 없다. 보드를 먼저 고쳐야 한다)")
        return 1

    # **외부로 나가기 전에** 쓰기 도구부터 확인한다 — 이슈를 만든 뒤에 "칸반에 적을
    # 방법이 없다"를 알게 되면 그게 곧 orphan 이슈다. 주입된 writer(테스트)는 이
    # 확인을 건너뛴다.
    if kanban_writer is None:
        try:
            kanban_writer = _kanban_issue_writer(
                kanban_dir or os.path.join(root, "vibe-harness"))
        except MissingToolFile as exc:
            print(f"\n{exc}")
            return 1

    gh_check = gh_check or gh_available
    ok, why = gh_check()
    if not ok:
        print(f"\n{why}")
        return 1

    repo_slug = _repo_slug(root)
    if not repo_slug:
        print("\norigin 리모트를 확인하지 못했다 — gh 호출을 이 레포에 고정할 수 없어 "
              "아무것도 만들지 않고 멈춘다")
        return 1

    gh_runner = gh_runner or _run

    created = updated = failed = 0
    orphans = []

    def report():
        """집계와 orphan 목록. **루프가 어떻게 끝나든 반드시 찍는다** — 중간에
        빠져나가면서 이걸 잃으면 '이슈는 공개됐는데 화면엔 아무 말도 없는' 상태가 된다.
        """
        print(f"\n생성 {created}, 갱신 {updated}, 실패 {failed}")
        if orphans:
            print(f"orphan 이슈(칸반에 번호가 없다): {', '.join(orphans)} — 사람이 직접 "
                  "정리하기 전엔 다시 실행하면 중복 생성된다")

    for kind, t, payload, _hits in entries:
        tid = board_id(t)

        if kind == "update":
            number = t.get("issue")
            code, _out, err = gh_runner(
                ["gh", "issue", "edit", str(number), "--title", payload["title"],
                 "--body", payload["body"], "-R", repo_slug],
                timeout=_GH_ISSUE_EDIT_TIMEOUT)
            if code != 0:
                print(f"{tid}: 이슈 #{number} 갱신 실패 ({err.strip()[:120]})")
                failed += 1
                continue
            print(f"{tid}: 이슈 #{number} 갱신 완료")
            updated += 1
            continue

        code, out, err = gh_runner(
            ["gh", "issue", "create", "--title", payload["title"],
             "--body", payload["body"], "-R", repo_slug],
            timeout=_GH_ISSUE_CREATE_TIMEOUT)
        if code != 0:
            # 만들어지지 않았으니 칸반은 그대로 둔다 — 여기서 번호를 적으면 있지도
            # 않은 이슈를 영원히 갱신하려 든다.
            print(f"{tid}: 이슈 생성 실패 — 칸반은 그대로 둔다 ({err.strip()[:120]})")
            failed += 1
            continue

        number, url = _issue_ref(out)
        if number is None:
            orphans.append(tid)
            print(f"{tid}: 이슈는 만들어졌는데 출력에서 번호를 읽지 못했다 — orphan 이슈다. "
                  "칸반에 적을 번호가 없어 다음 실행이 같은 태스크로 이슈를 하나 더 만든다. "
                  f"사람이 직접 확인해야 한다 (gh 출력: {(out or '').strip()[:160]})")
            failed += 1
            continue

        try:
            kanban_writer(tid, number)
        except BaseException as exc:
            # **`except Exception` 은 이 경로의 유일한 실패 신호를 못 잡았다.** 기본
            # writer 인 `kanban_edit.set_task` 는 "보드에 그 태스크가 없다"를
            # `SystemExit` 으로 알리는데 그건 `BaseException` 이라 그대로 빠져나갔다 —
            # 이슈는 이미 만들어졌는데 번호도 URL 도 orphan 표시도 못 찍고, 남은
            # 태스크는 건너뛰고, 다음 실행이 같은 태스크로 하나 더 만든다. 게다가
            # 흔한 경로다: `set_task` 는 자기 안에서 보드를 다시 읽으므로, 여기서
            # 읽은 뒤 `gh issue create` 가 도는 몇 초 사이에 누가(아카이브 작업 등)
            # 보드를 건드리기만 해도 난다.
            #
            # 그래서 **무엇이 오든 orphan 으로 보고한다.** 다만 진짜 인터럽트
            # (Ctrl-C)는 삼키지 않는다 — 보고를 먼저 끝내고 그대로 올린다.
            orphans.append(tid)
            failed += 1
            print(f"{tid}: 이슈 #{number} 는 만들어졌는데 칸반에 번호를 적지 못했다 — "
                  "orphan 이슈다. 그 번호가 중복 생성을 막는 유일한 장치라, 이대로 다시 "
                  f"실행하면 같은 태스크로 이슈가 하나 더 생긴다. 보드의 {tid} 에 "
                  f"issue: {number} 를 직접 적거나 이슈를 닫아야 한다 — {url} "
                  f"(원인: {type(exc).__name__}: {str(exc)[:120]})")
            if isinstance(exc, KeyboardInterrupt):
                report()
                raise
            continue

        print(f"{tid}: 이슈 #{number} 생성 + 칸반 기록 완료 — {url}")
        created += 1

    report()
    return 0 if failed == 0 else 1


def main(argv=None, root=None):
    """`gh_surface.py tag` / `promote` — 어느 쪽이든 기본은 dry-run.

    `root` 는 테스트가 임시 레포를 주입하기 위한 자리다. 기본은 이 파일이
    있는 레포의 루트(`ROOT`) — `private/PHASES.md` 도 그 기준으로 찾는다.
    """
    ap = argparse.ArgumentParser(description="GitHub 표면 — 칸반이 정본이다")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tag", help="Phase 를 태그·릴리스로. 기본은 dry-run")
    t.add_argument("--phases", default=None, help="PHASES.md 경로 (기본: private/PHASES.md)")
    t.add_argument("--apply", action="store_true",
                   help="실제로 만든다. 없으면 무엇을 할지 출력만 한다")

    p = sub.add_parser("promote", help="공유 표시된 태스크를 이슈로. 기본은 dry-run")
    p.add_argument("--kanban-dir", default=None,
                   help="kanban.json 이 있는 디렉터리 (기본: <root>/vibe-harness)")
    p.add_argument("--apply", action="store_true",
                   help="실제로 만든다. 없으면 무엇이 올라갈지 출력만 한다")
    a = ap.parse_args(argv)

    base = root or ROOT

    if a.cmd == "promote":
        kanban_dir = a.kanban_dir or os.path.join(base, "vibe-harness")
        kanban_path = os.path.join(kanban_dir, "kanban.json")
        if not os.path.exists(kanban_path):
            raise SystemExit(
                f"kanban.json 을 찾지 못했다: {kanban_path}\n"
                "  조용히 '올릴 것 없음' 으로 끝나면 '보드를 못 찾음' 과 '올릴 게 없음' 이 "
                "똑같아 보인다 — 추측하지 않고 멈춘다.")
        with open(kanban_path, encoding="utf-8") as fh:
            board = json.load(fh)
        return _run_promote(board.get("tasks") or [], base, apply=a.apply,
                            kanban_dir=kanban_dir)

    phases_path = a.phases or os.path.join(base, "private", "PHASES.md")
    if not os.path.exists(phases_path):
        raise SystemExit(
            f"PHASES.md 를 찾지 못했다: {phases_path}\n"
            "  private/ 는 gitignore 대상이라 이 파일이 없는 환경일 수 있다 — "
            "추측해서 빈 계획으로 진행하지 않고 멈춘다.")
    with open(phases_path, encoding="utf-8") as fh:
        phases_body = fh.read()

    # **중복 번호 위에서는 진행하지 않는다.** `phase_sections()` 가 이름을 키로 쓰는
    # dict 라 같은 번호가 둘이면 뒤엣것만 남는다 — 파서가 충돌을 지워버린다.
    # 그 상태로 태그를 그으면 한쪽 Phase 의 노트가 통째로 사라진 채 공개된다.
    dupes = duplicate_phases(phases_body)
    if dupes:
        raise SystemExit(
            "같은 Phase 번호가 둘 이상이다: "
            + ", ".join(f"{k}×{v}" for k, v in sorted(dupes.items()))
            + f"\n  {phases_path}\n"
            "  두 머신이 같은 번호를 각자 열면 이렇게 된다. 번호를 갈라 적고 다시 돌린다.")

    plan = tag_plan(phases_body, _log_lines(base))
    return _run_tag(plan, base, apply=a.apply)


if __name__ == "__main__":
    sys.exit(main())
