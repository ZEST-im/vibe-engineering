#!/usr/bin/env python3
"""reconcile_runs.py — Claude Code transcript에서 프로젝트 토큰 사용량 재구성 + 중앙 전송.

record-run 훅/agentcat이 세션을 놓쳐 토큰 집계가 누락될 때, 실제 세션 transcript(.jsonl)를
파싱해 세션별 run을 재구성한다. 세션당 run 1건(tokens=input+output+cache 합, cost=컴포넌트 요율,
ts=파일 mtime KST). 로컬 runs.json에 쓰고, --push면 중앙 저장소(zestim)로 전송(session_id dedup).

여러 사람/머신이 한 프로젝트를 작업해도, 각자 --push하면 중앙에서 session_id로 union돼
대시보드에 팀 전체 사용량이 합산된다.

사용:
  python scripts/reconcile_runs.py <project_key>              # 로컬 runs.json 재구성(미리보기 겸)
  python scripts/reconcile_runs.py <project_key> --push       # + 중앙 저장소로 전송
  python scripts/reconcile_runs.py --all --push               # 로컬 transcript 있는 모든 프로젝트
  python scripts/reconcile_runs.py <project_key> --dry-run    # 미리보기(변경/전송 없음)

※ 토큰은 cache-read 포함 throughput. 중앙엔 토큰 숫자·session_id·model·시각·commit만 전송
  (transcript 내용은 절대 안 감).
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import socket
import urllib.request

CONFIG = os.path.expanduser("~/.claude/skills/vibe-harness/projects.json")
SYNC_CONFIG = os.path.expanduser("~/.claude/skills/vibe-harness/sync.json")
# 증분 push 상태 — 프로젝트별로 "이미 보낸 행"을 기억한다 (테스트에서 교체)
PUSH_STATE_PATH = os.path.expanduser("~/.claude/skills/vibe-harness/push-state.json")
KST = datetime.timezone(datetime.timedelta(hours=9))

# 컴포넌트별 $/token (server.py COMPONENT_RATES와 동일 — 캐시가 지배적이라 정확)
COMPONENT_RATES = {
    "opus":     {"in": 0.000015, "out": 0.000075, "cw": 0.00001875, "cr": 0.0000015},
    "sonnet":   {"in": 0.000003, "out": 0.000015, "cw": 0.00000375, "cr": 0.0000003},
    "haiku":    {"in": 0.000001, "out": 0.000005, "cw": 0.00000125, "cr": 0.0000001},
    "_default": {"in": 0.000003, "out": 0.000015, "cw": 0.00000375, "cr": 0.0000003},
}


def _rates(model):
    ml = (model or "").lower()
    for key, r in COMPONENT_RATES.items():
        if key != "_default" and key in ml:
            return r
    return COMPONENT_RATES["_default"]


def _projects():
    try:
        return json.load(open(CONFIG))
    except Exception:
        return {}


def _kanban_dir_for(key):
    p = _projects().get(key)
    if not p:
        return None
    return p.get("kanban_dir") if isinstance(p, dict) else p


def _transcript_dir(cwd):
    # Claude Code는 cwd의 '/', '.', '_'를 '-'로 치환해 ~/.claude/projects/ 하위로 씀
    return os.path.expanduser("~/.claude/projects/" + re.sub(r"[/._]", "-", cwd))


def _summarize(path):
    tot = inp = out = cr = cw = 0
    model = ""
    try:
        with open(path, errors="ignore") as fh:
            for line in fh:
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                msg = m.get("message") or m
                if not isinstance(msg, dict):
                    continue
                u = msg.get("usage")
                if u:
                    i = int(u.get("input_tokens") or 0)
                    o = int(u.get("output_tokens") or 0)
                    a = int(u.get("cache_read_input_tokens") or 0)
                    b = int(u.get("cache_creation_input_tokens") or 0)
                    inp += i; out += o; cr += a; cw += b; tot += i + o + a + b
                    model = msg.get("model", model) or model
    except Exception:
        pass
    return tot, inp, out, cr, cw, model


def build_runs(transcripts):
    files = sorted(set(glob.glob(transcripts + "/*.jsonl")
                       + glob.glob(transcripts + "/**/*.jsonl", recursive=True)))
    runs = []
    for f in files:
        tot, inp, out, cr, cw, model = _summarize(f)
        if tot <= 0:
            continue
        rt = _rates(model)
        cost = inp * rt["in"] + out * rt["out"] + cr * rt["cr"] + cw * rt["cw"]
        sid = os.path.splitext(os.path.basename(f))[0]
        ts = datetime.datetime.fromtimestamp(os.path.getmtime(f), KST).isoformat(timespec="seconds")
        runs.append({
            "task_id": None, "agent": "claude", "model": model or "claude",
            "tokens": tot, "input_tokens": inp, "output_tokens": out,
            "cache_read_tokens": cr, "cache_write_tokens": cw,
            "cost_usd": round(cost, 4),
            "session_id": sid, "commit": "", "ts": ts, "source": "transcript-reconcile",
        })
    runs.sort(key=lambda r: r["ts"])
    return runs


def _sync_cfg():
    """sync.json 로드. 없거나 깨져도 기능이 멈추면 안 되므로 빈 dict."""
    try:
        with open(SYNC_CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def machine_id(cfg=None):
    """이 머신의 라벨. sync.json의 machine이 있으면 그걸, 없으면 hostname.

    한 사람이 여러 머신을 교차 사용해도 사람 단위로 합산되도록, 이 값은 귀속이 아니라
    운영·디버그용 라벨이다. owner는 중앙이 토큰으로 판정한다.
    """
    if cfg is None:
        cfg = _sync_cfg()
    label = str((cfg or {}).get("machine") or "").strip()
    if label:
        return label
    return socket.gethostname()


def _kst_date(ts):
    """transcript 메시지의 timestamp를 KST 달력 날짜로. 해석 불가면 None."""
    if not ts:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).date().isoformat()


def build_daily_runs(transcripts, machine=None):
    """중앙 저장소로 보낼 (세션 × 일자) 행을 만든다.

    build_runs()는 세션당 1건이고 ts가 파일 mtime이라, 여러 날에 걸친 세션은 마지막
    날에 전액이 몰린다. 일별 레이스가 그걸 그대로 그리면 거짓말이 되므로, 메시지별
    timestamp를 KST 달력 날짜로 버킷팅해 일자별로 쪼갠다.

    owner는 넣지 않는다 — 클라이언트가 신원을 주장하면 위조 경로가 된다.
    """
    if machine is None:
        machine = machine_id()
    files = sorted(set(glob.glob(transcripts + "/*.jsonl")
                       + glob.glob(transcripts + "/**/*.jsonl", recursive=True)))
    buckets = {}
    for path in files:
        sid = os.path.splitext(os.path.basename(path))[0]
        try:
            fh = open(path, errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                msg = m.get("message") or m
                if not isinstance(msg, dict):
                    continue
                u = msg.get("usage")
                if not u:
                    continue
                day = _kst_date(m.get("timestamp") or msg.get("timestamp"))
                if not day:
                    continue
                agg = buckets.setdefault((sid, day), {
                    "input_tokens": 0, "output_tokens": 0,
                    "cache_read_tokens": 0, "cache_write_tokens": 0, "model": "",
                })
                agg["input_tokens"] += int(u.get("input_tokens") or 0)
                agg["output_tokens"] += int(u.get("output_tokens") or 0)
                agg["cache_read_tokens"] += int(u.get("cache_read_input_tokens") or 0)
                agg["cache_write_tokens"] += int(u.get("cache_creation_input_tokens") or 0)
                agg["model"] = msg.get("model", agg["model"]) or agg["model"]

    rows = []
    for (sid, day), agg in buckets.items():
        total = (agg["input_tokens"] + agg["output_tokens"]
                 + agg["cache_read_tokens"] + agg["cache_write_tokens"])
        if total <= 0:
            continue
        rt = _rates(agg["model"])
        cost = (agg["input_tokens"] * rt["in"] + agg["output_tokens"] * rt["out"]
                + agg["cache_read_tokens"] * rt["cr"] + agg["cache_write_tokens"] * rt["cw"])
        rows.append({
            "session_id": sid,
            "date": day,
            "agent": "claude",
            "model": agg["model"] or "claude",
            "tokens": total,
            "input_tokens": agg["input_tokens"],
            "output_tokens": agg["output_tokens"],
            "cache_read_tokens": agg["cache_read_tokens"],
            "cache_write_tokens": agg["cache_write_tokens"],
            "cost_usd": round(cost, 6),
            "machine": machine,
            "source": "transcript-daily",
        })
    rows.sort(key=lambda r: (r["date"], r["session_id"]))
    return rows


# ── 증분 push ────────────────────────────────────────
# 3시간마다 전량을 재전송하던 낭비를 없앤다. 지난 날짜의 행은 확정되면 다시 안 바뀌므로
# 정상 상태에서는 "오늘" 행만 전송된다.

def _row_key(row):
    return "%s|%s" % (row.get("session_id") or "", row.get("date") or "")


def _row_fingerprint(row):
    # JSON round-trip을 견디도록 문자열로 둔다 (float 재현 문제 회피)
    return "%d:%s" % (int(row.get("tokens") or 0), repr(row.get("cost_usd")))


def push_state_for(rows):
    """이 행들을 보낸 뒤 저장할 상태."""
    return {_row_key(r): _row_fingerprint(r) for r in rows}


def changed_rows(state, rows):
    """상태와 비교해 새로 생겼거나 값이 바뀐 행만 고른다."""
    state = state or {}
    return [r for r in rows if state.get(_row_key(r)) != _row_fingerprint(r)]


# 매칭된 run에서 "더 완전한 쪽"을 고를 수치 필드 (server.py velocity 집계와 같은 max 규칙)
MERGE_MAX_FIELDS = ("tokens", "input_tokens", "output_tokens",
                    "cache_read_tokens", "cache_write_tokens", "cost_usd")


def merge_runs(existing, new_runs):
    """기존 runs.json에 재구성한 run을 append-only로 합친다.

    기존 run은 삭제하지 않고 필드도 지우지 않는다. session_id가 같으면 토큰/비용만
    더 큰 값으로 올리고(훅이 세션 도중 기록해 과소집계된 경우 보정), 나머지 필드는
    기존 값을 유지한다. transcript에만 있는 세션은 뒤에 추가한다.
    """
    merged = dict(existing or {})
    merged.setdefault("version", 1)
    kept = [dict(r) for r in merged.get("runs") or []]

    by_sid = {}
    for run in kept:
        sid = run.get("session_id")
        if sid:
            by_sid.setdefault(sid, run)

    appended = []
    for new in new_runs:
        sid = new.get("session_id")
        old = by_sid.get(sid) if sid else None
        if old is None:
            appended.append(dict(new))
            continue
        for field in MERGE_MAX_FIELDS:
            nv = new.get(field)
            if nv is None:
                continue
            ov = old.get(field)
            old[field] = nv if ov is None else max(ov, nv)

    appended.sort(key=lambda r: r.get("ts") or "")
    merged["runs"] = kept + appended
    return merged


def _load_runs(path):
    """기존 runs.json 로드. 없으면 {} — 단, 읽거나 파싱하지 못하면 예외를 올린다.

    파싱 실패를 "빈 파일"로 삼키면 기존 run 전체가 사라진 채 덮어써진다. append-only
    보장을 위해 이 경우엔 쓰지 않고 중단해야 한다.
    """
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict):
        raise ValueError("최상위가 JSON object가 아님")
    return doc


def load_push_state(project):
    """이 프로젝트에서 이미 보낸 행들의 지문. 없거나 깨졌으면 빈 상태(=전량 재전송)."""
    try:
        with open(PUSH_STATE_PATH, encoding="utf-8") as fh:
            doc = json.load(fh)
        state = doc.get(project) if isinstance(doc, dict) else None
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def save_push_state(project, state):
    """전송 성공 후에만 호출한다. 실패한 전송을 보냈다고 적으면 그 행은 영구 유실된다."""
    try:
        with open(PUSH_STATE_PATH, encoding="utf-8") as fh:
            doc = json.load(fh)
        if not isinstance(doc, dict):
            doc = {}
    except Exception:
        doc = {}
    doc[project] = state
    tmp = PUSH_STATE_PATH + ".tmp"
    os.makedirs(os.path.dirname(PUSH_STATE_PATH) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, PUSH_STATE_PATH)


def build_push_payload(project, runs, schema=1, machine=None):
    """중앙 전송 payload.

    schema 1 은 지금 중앙이 이해하는 형태 그대로다(세션 단위 전량). 중앙이 일자별
    스키마를 받을 준비가 되면 sync.json 에 runs_schema=2 를 켜서 전환한다.
    """
    if schema < 2:
        return {"project": project, "runs": runs}
    return {"project": project, "schema": 2, "machine": machine, "runs": runs}


def _http_post(url, payload, secret):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {secret}",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _push_central(cfg, payload, sender=None):
    """중앙 저장소(zestim)로 payload 전송. sync.json의 endpoint/secret 재사용."""
    endpoint = str((cfg or {}).get("endpoint", ""))
    secret = str((cfg or {}).get("secret", ""))
    if not endpoint or not secret:
        raise SystemExit("sync.json에 endpoint/secret 없음")
    runs_url = endpoint.rsplit("/", 1)[0] + "/runs"   # .../vibe-harness/sync → .../vibe-harness/runs
    if sender is not None:
        return sender(runs_url, payload)
    return _http_post(runs_url, payload, secret)


def _push_central_legacy(project, runs):

    """하위 호환 진입점 — 세션 단위 전량 전송."""
    cfg = _sync_cfg()
    if not cfg:
        raise SystemExit(f"sync.json 없음/오류 — 중앙 전송 불가: {SYNC_CONFIG}")
    return _push_central(cfg, build_push_payload(project, runs))


def reconcile(project, kanban_dir, transcripts, dry_run=False, push=False,
              sender=None, force_full=False):
    runs = build_runs(transcripts)
    total = sum(r["tokens"] for r in runs)
    cost = sum(r["cost_usd"] for r in runs)
    print(f"[{project}] transcript {transcripts}")
    print(f"  세션 {len(runs)}개 · {total:,} 토큰 ({total/1e8:.2f}억) · ${cost:,.2f}")
    if dry_run:
        byday = {}
        for r in runs:
            byday[r["ts"][:10]] = byday.get(r["ts"][:10], 0) + r["tokens"]
        for d, v in sorted(byday.items())[-14:]:
            print(f"    {d}: {v:,}")
        print("  [dry-run] 변경/전송 없음")
        return
    if not runs:
        print("  재구성할 run 없음 — skip")
        return
    rp = os.path.join(kanban_dir, "runs.json")
    try:
        existing = _load_runs(rp)
    except Exception as exc:
        raise SystemExit(f"  runs.json 파싱 실패 — 덮어쓰지 않고 중단: {rp} ({exc})") from exc
    before = len(existing.get("runs") or [])
    if os.path.exists(rp):
        shutil.copy2(rp, rp + ".bak")
    merged = merge_runs(existing, runs)
    with open(rp, "w") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=2)
    added = len(merged["runs"]) - before
    print(f"  로컬 기록: {rp} (기존 {before}건 유지 + 신규 {added}건)")
    if push:
        _push(project, transcripts, runs, sender=sender, force_full=force_full)


def _push(project, transcripts, runs, sender=None, force_full=False):
    """중앙 전송. schema 2 를 켠 머신만 일자별 증분으로 보낸다.

    중앙이 일자별 스키마를 받을 준비가 되기 전에 클라이언트가 먼저 바뀌면 전사 수집이
    조용히 멈춘다. 그래서 기본값은 지금과 동일한 세션 단위 전량 전송이다.
    """
    cfg = _sync_cfg()
    if not cfg:
        raise SystemExit(f"sync.json 없음/오류 — 중앙 전송 불가: {SYNC_CONFIG}")

    try:
        schema = int(cfg.get("runs_schema") or 1)
    except (TypeError, ValueError):
        schema = 1

    if schema < 2:
        res = _push_central(cfg, build_push_payload(project, runs), sender)
        print(f"  중앙 전송: {res}")
        return

    machine = machine_id(cfg)
    rows = build_daily_runs(transcripts, machine=machine)
    state = {} if force_full else load_push_state(project)
    outgoing = changed_rows(state, rows)
    if not outgoing:
        print(f"  중앙 전송: 변경 없음 — skip ({len(rows)}행 모두 최신)")
        return

    payload = build_push_payload(project, outgoing, schema=2, machine=machine)
    res = _push_central(cfg, payload, sender)
    # 전송 성공 이후에만 상태를 갱신한다. 보낸 행만 기록해 실패분이 유실되지 않게 한다.
    merged = load_push_state(project)
    merged.update(push_state_for(outgoing))
    save_push_state(project, merged)
    print(f"  중앙 전송: {res} ({len(outgoing)}/{len(rows)}행)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", nargs="?", help="projects.json의 프로젝트 키")
    ap.add_argument("--all", action="store_true", help="로컬 transcript 있는 모든 프로젝트")
    ap.add_argument("--kanban-dir")
    ap.add_argument("--transcripts")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--push", action="store_true", help="중앙 저장소로 전송")
    ap.add_argument("--force-full-push", action="store_true",
                    help="증분 상태를 무시하고 전량 재전송 (복구용)")
    a = ap.parse_args()

    if a.all:
        failed = []
        for key, meta in _projects().items():
            kd = meta.get("kanban_dir") if isinstance(meta, dict) else meta
            if not kd:
                continue
            td = _transcript_dir(os.path.dirname(os.path.abspath(kd)))
            if not os.path.isdir(td) or not glob.glob(td + "/*.jsonl"):
                continue
            # 한 프로젝트가 실패해도 나머지는 계속 — 단, 마지막에 비정상 종료로 알린다
            try:
                reconcile(key, kd, td, dry_run=a.dry_run, push=a.push,
                          force_full=a.force_full_push)
            except SystemExit as exc:
                print(f"[{key}] 건너뜀: {exc}")
                failed.append(key)
        if failed:
            raise SystemExit("실패한 프로젝트: " + ", ".join(failed))
        return

    kd = a.kanban_dir or (_kanban_dir_for(a.project) if a.project else None)
    if not kd:
        raise SystemExit("kanban_dir 해석 실패 — <project_key> 또는 --kanban-dir/--all 필요")
    td = a.transcripts or _transcript_dir(os.path.dirname(os.path.abspath(kd)))
    if not os.path.isdir(td):
        raise SystemExit(f"transcript 디렉토리 없음: {td} (--transcripts로 지정 가능)")
    reconcile(a.project or os.path.basename(os.path.dirname(kd)), kd, td,
              dry_run=a.dry_run, push=a.push, force_full=a.force_full_push)


if __name__ == "__main__":
    main()
