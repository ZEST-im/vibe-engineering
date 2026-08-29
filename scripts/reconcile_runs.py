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
import sys
import urllib.request

# Windows cp949 콘솔에서 '—' 같은 문자가 크래시를 낸다. 사용자가 PYTHONUTF8=1 을 손으로
# 붙여야 돌아가던 문제라 스크립트가 직접 보장한다. reconfigure 가 없으면 no-op.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

CONFIG = os.path.expanduser("~/.claude/skills/vibe-harness/projects.json")
SYNC_CONFIG = os.path.expanduser("~/.claude/skills/vibe-harness/sync.json")
# 증분 push 상태 — 프로젝트별로 "이미 보낸 행"을 기억한다 (테스트에서 교체)
PUSH_STATE_PATH = os.path.expanduser("~/.claude/skills/vibe-harness/push-state.json")
# 수집이 마지막으로 성공한 시각. 이 파일이 없거나 오래됐다는 것 자체가 신호다 —
# 실제로 겪은 고장은 스크립트 경로가 어긋나 **아예 실행되지 않은** 것이라, 오류를
# 기록할 주체가 없었다. 그래서 "기록된 실패"가 아니라 "성공의 부재"를 본다.
PIPELINE_STATUS_PATH = os.path.expanduser("~/.claude/skills/vibe-harness/pipeline-status.json")
KST = datetime.timezone(datetime.timedelta(hours=9))

# 컴포넌트별 $/token. 캐시 읽기 0.1x · 캐시 쓰기 1.25x 는 입력 단가에서 파생된다.
#
# 2026-08 감사에서 표가 낡아 있던 것을 발견했다 — opus 가 $15/$75(구 Opus 3 시절)로 잡혀
# 있어 비용이 3배로 부풀려졌고, fable-5 는 표에 없어 _default 로 떨어져 3.3배 과소계상됐다.
# 모델을 새로 쓰기 시작하면 여기에 먼저 추가할 것. 빠지면 조용히 _default 로 떨어진다.
#
# 매칭은 순서가 있다 — "sonnet-5"($2/$10)를 "sonnet"($3/$15)보다 먼저 봐야 한다.


def _tier(inp, out):
    """입력 단가에서 4종 단가를 만든다. 캐시 배수를 한 곳에서만 정의하기 위해서."""
    return {"in": inp, "out": out, "cw": inp * 1.25, "cr": inp * 0.1}


COMPONENT_RATES = {
    "fable":      _tier(0.000010, 0.000050),
    "mythos":     _tier(0.000010, 0.000050),
    "opus":       _tier(0.000005, 0.000025),
    "sonnet-5":   _tier(0.000002, 0.000010),
    "sonnet":     _tier(0.000003, 0.000015),
    "haiku":      _tier(0.000001, 0.000005),
    "_default":   _tier(0.000003, 0.000015),
}

# 긴 이름이 먼저 오도록 고정 — "sonnet-5" 가 "sonnet" 보다 앞이어야 한다.
_RATE_ORDER = ("fable", "mythos", "opus", "sonnet-5", "sonnet", "haiku")


def _rates(model):
    ml = (model or "").lower()
    for key in _RATE_ORDER:
        if key in ml:
            return COMPONENT_RATES[key]
    return COMPONENT_RATES["_default"]


def cost_breakdown(model, input_tokens=0, output_tokens=0,
                   cache_read_tokens=0, cache_write_tokens=0):
    """토큰 타입별 비용. total 은 합계.

    총액만 기록하면 "무엇이 비용을 끌었는지" 사후 분해가 추정이 된다. 실제로 캐시 읽기가
    비용의 대부분인데 화면에는 총 토큰과 총 비용만 있어 해석이 어긋났다.
    """
    rt = _rates(model)
    parts = {
        "in": input_tokens * rt["in"],
        "out": output_tokens * rt["out"],
        "cr": cache_read_tokens * rt["cr"],
        "cw": cache_write_tokens * rt["cw"],
    }
    parts["total"] = sum(parts.values())
    return parts


def _projects():
    try:
        return json.load(open(CONFIG))
    except Exception:
        return {}


def _atomic_json(path, data):
    """JSON을 같은 디렉토리의 임시 파일에 쓴 뒤 원자적으로 교체한다."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


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
        with open(path, encoding="utf-8", errors="ignore") as fh:
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
        parts = cost_breakdown(model, inp, out, cr, cw)
        cost = parts.pop("total")
        sid = os.path.splitext(os.path.basename(f))[0]
        ts = datetime.datetime.fromtimestamp(os.path.getmtime(f), KST).isoformat(timespec="seconds")
        runs.append({
            "task_id": None, "agent": "claude", "model": model or "claude",
            "tokens": tot, "input_tokens": inp, "output_tokens": out,
            "cache_read_tokens": cr, "cache_write_tokens": cw,
            "cost_usd": round(cost, 4),
            "cost_breakdown": {k: round(v, 6) for k, v in parts.items()},
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


def recost_rows(rows):
    """기록된 cost_usd 를 현행 단가로 다시 계산한다. (rows, 변경건수) 반환.

    낡은 단가로 계산된 과거 행을 고치기 위한 것이다. 파괴적이므로 규칙을 좁게 잡는다.

    - 토큰 분해가 없는 행은 건드리지 않는다. 총 tokens 만으로 되돌리려면 당시 단가를
      알아야 하는데 그건 추정이다.
    - agent 가 claude 가 아니면 건드리지 않는다. codex 는 단가가 아직 없다.
    - 토큰 값 자체는 절대 바꾸지 않는다. 여기서 하는 일은 비용을 다시 세는 것뿐이다.
    """
    fields = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    changed = 0
    for row in rows:
        if (row.get("agent") or "").lower() != "claude":
            continue
        if not any(row.get(f) is not None for f in fields):
            continue
        parts = cost_breakdown(row.get("model"),
                               int(row.get("input_tokens") or 0),
                               int(row.get("output_tokens") or 0),
                               int(row.get("cache_read_tokens") or 0),
                               int(row.get("cache_write_tokens") or 0))
        total = round(parts.pop("total"), 6)
        breakdown = {k: round(v, 6) for k, v in parts.items()}
        if row.get("cost_usd") != total or row.get("cost_breakdown") != breakdown:
            changed += 1
        row["cost_usd"] = total
        row["cost_breakdown"] = breakdown
    return rows, changed


# ── Codex(OpenAI) ────────────────────────────────────
# OpenAI 공식 API 단가, USD/token (2026-08-29 확인).
# _tier 는 cached input 0.1x, cache write 1.25x 정책도 함께 반영한다.
# GPT-5.6 Sol의 $4/$20은 2026-11-21까지 최소 유지되는 프로모션 단가다.
# 공식 단가가 없는 모델은 추정하지 않고 cost_usd=0으로 남긴다.
CODEX_RATES = {
    "gpt-5.6-terra": _tier(0.000002, 0.000012),
    "gpt-5.6-luna": _tier(0.0000002, 0.0000012),
    "gpt-5.6-sol": _tier(0.000004, 0.000020),
    "gpt-5.3-codex": _tier(0.00000175, 0.000014),
    "gpt-5.6": _tier(0.000004, 0.000020),  # official alias → GPT-5.6 Sol
    "gpt-5.5": _tier(0.000005, 0.000030),
    "gpt-5.4": _tier(0.0000025, 0.000015),
}

CODEX_SESSIONS = os.path.expanduser("~/.codex/sessions")


def _codex_sessions_dir():
    """Codex 세션 경로. 환경변수를 **호출 시점에** 읽는다.

    모듈 상수로 굳히면 import 이후에 설정한 값이 반영되지 않는다. 실제로 테스트가
    개발자 홈의 실제 세션(40MB)을 스캔해 0.04초짜리 스위트가 45초가 됐다.
    """
    return os.environ.get("VIBE_CODEX_SESSIONS") or CODEX_SESSIONS


def _codex_rates(model):
    ml = (model or "").lower()
    # alias `gpt-5.6` 가 `gpt-5.6-luna` 보다 먼저 맞지 않게 구체적인 키 우선.
    for key in sorted(CODEX_RATES, key=len, reverse=True):
        if key.lower() in ml:
            return CODEX_RATES[key]
    return None


def _kst_date(iso_ts):
    """UTC ISO 타임스탬프 → KST 업무일자(YYYY-MM-DD)."""
    if not iso_ts:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    kst = datetime.timezone(datetime.timedelta(hours=9))
    return dt.astimezone(kst).date().isoformat()


def build_codex_daily_runs(sessions_dir=None, cwd=None, machine=None):
    """Codex 세션(~/.codex/sessions/**/*.jsonl) → 일자별 run 행.

    ⚠️ 토큰 의미가 Claude 와 다르다.
      Claude: input_tokens(캐시 제외) + cache_read_input_tokens(별도 필드)
      Codex : input_tokens 가 캐시를 포함한 총 입력, cached_input_tokens 는 그 부분집합

    그대로 옮기면 캐시가 이중계상된다. 여기서 실입력 = input - cached 로 쪼갠다.

    total_token_usage 는 세션 누적값이라 마지막 이벤트만 취한다. 이벤트를 합치면 폭증한다.
    """
    root = sessions_dir or _codex_sessions_dir()
    rows = []
    files = sorted(set(glob.glob(root + "/*.jsonl")
                       + glob.glob(root + "/**/*.jsonl", recursive=True)))
    for path in files:
        meta, last, turn_models = {}, None, set()
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    payload = obj.get("payload") or {}
                    if obj.get("type") == "session_meta" and not meta:
                        meta = payload
                    elif obj.get("type") == "turn_context" and payload.get("model"):
                        turn_models.add(payload["model"])
                    elif payload.get("type") == "token_count":
                        usage = (payload.get("info") or {}).get("total_token_usage")
                        if usage:
                            last = usage
        except OSError:
            continue
        if not last:
            continue
        if cwd and (meta.get("cwd") or "") != cwd:
            continue

        total_in = int(last.get("input_tokens") or 0)
        cached = int(last.get("cached_input_tokens") or 0)
        out = int(last.get("output_tokens") or 0)
        cw = int(last.get("cache_write_input_tokens") or 0)
        # 실제 Codex rollout은 모델을 session_meta가 아니라 turn_context에 둔다.
        # 세션 중 모델이 바뀐 경우 누적 토큰을 한 단가로 추정하지 않는다.
        model = meta.get("model")
        if not model and len(turn_models) == 1:
            model = next(iter(turn_models))
        model = model or ("codex-mixed" if turn_models else "codex")

        row_date = _kst_date(meta.get("timestamp"))
        row = {
            "session_id": meta.get("session_id") or os.path.basename(path),
            "date": row_date,
            "agent": "codex",
            "model": model,
            "tokens": total_in + out,
            "input_tokens": max(total_in - cached, 0),
            "output_tokens": out,
            "cache_read_tokens": cached,
            "cache_write_tokens": cw,
            "cost_usd": 0,
            # merge_runs 는 session_id 로 묶고 dry-run 은 ts[:10] 을 읽는다.
            # Claude 행과 같은 모양이어야 한 목록에 섞일 수 있다.
            "ts": (row_date + "T00:00:00+09:00") if row_date else None,
            "machine": machine,
            "source": "codex-session",
        }
        rates = _codex_rates(model)
        if rates:
            parts = {
                "in": row["input_tokens"] * rates["in"],
                "out": out * rates["out"],
                "cr": cached * rates["cr"],
                "cw": cw * rates["cw"],
            }
            row["cost_usd"] = round(sum(parts.values()), 6)
            row["cost_breakdown"] = {k: round(v, 6) for k, v in parts.items()}
        rows.append(row)
    rows.sort(key=lambda r: (r["date"] or "", r["session_id"]))
    return rows


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
            fh = open(path, encoding="utf-8", errors="ignore")
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
        parts = cost_breakdown(agg["model"], agg["input_tokens"], agg["output_tokens"],
                               agg["cache_read_tokens"], agg["cache_write_tokens"])
        cost = parts.pop("total")
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
            "cost_breakdown": {k: round(v, 6) for k, v in parts.items()},
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
    with open(path, encoding="utf-8") as fh:
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


def push_credential(cfg):
    """run 전송에 쓸 자격증명.

    스냅샷(/sync)은 프로젝트 단위 공유 secret 만 인정하고, run(/runs)은 사람별 귀속을
    위해 개인 토큰을 요구한다. 두 값을 한 필드에 뭉개면 개인 토큰으로 덮어쓰는 순간
    스냅샷이 401 로 죽는다. 그래서 runs_token 을 따로 두고, 없으면 secret 으로 떨어진다.
    """
    cfg = cfg or {}
    token = str(cfg.get("runs_token") or "").strip()
    return token or str(cfg.get("secret") or "").strip()


def _push_central(cfg, payload, sender=None):
    """중앙 저장소(zestim)로 payload 전송. sync.json의 endpoint 와 자격증명을 쓴다."""
    endpoint = str((cfg or {}).get("endpoint", ""))
    secret = push_credential(cfg)
    if not endpoint or not secret:
        raise SystemExit("sync.json에 endpoint 또는 자격증명(runs_token/secret) 없음")
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


def collect_runs(transcripts, cwd=None, codex_sessions=None):
    """한 프로젝트의 run 을 에이전트 구분 없이 모아 돌려준다.

    Codex 를 따로 돌려야 하는 구조는 결국 빠뜨린다 — 실제로 수집기를 만들고도 연결하지
    않아 사용량이 통째로 빠져 있었다. 에이전트가 늘면 여기에 한 줄 더한다.

    cwd 가 없으면 Codex 는 건너뛴다. Codex 세션은 cwd 로만 프로젝트를 가릴 수 있어서,
    특정하지 못한 채 모으면 남의 프로젝트 사용량을 끌어온다.
    """
    runs = list(build_runs(transcripts))
    if cwd:
        runs.extend(build_codex_daily_runs(codex_sessions, cwd=cwd))
    return runs


def reconcile(project, kanban_dir, transcripts, dry_run=False, push=False,
              sender=None, force_full=False):
    # 프로젝트 cwd = kanban_dir 의 부모. Codex 세션을 이 프로젝트로 가리는 기준이다.
    runs = collect_runs(transcripts, cwd=os.path.dirname(os.path.abspath(kanban_dir)))
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


def recost_all(dry_run=False):
    """등록된 모든 프로젝트의 runs.json 을 현행 단가로 재계산한다. 0=정상.

    단가표가 낡은 채로 굴러간 기간의 행을 고치기 위한 것이다. 토큰은 건드리지 않고
    비용만 다시 센다. 멱등이므로 여러 번 돌려도 안전하다.
    """
    total_before = total_after = 0.0
    changed_rows = touched = 0
    for key, meta in (_projects() or {}).items():
        kd = meta.get("kanban_dir") if isinstance(meta, dict) else meta
        if not kd:
            continue
        path = os.path.join(kd, "runs.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"[{key}] 건너뜀: {exc}")
            continue
        runs = data.get("runs") or []
        if not runs:
            continue
        before = sum(float(r.get("cost_usd") or 0) for r in runs)
        rows, changed = recost_rows(runs)
        after = sum(float(r.get("cost_usd") or 0) for r in rows)
        total_before += before
        total_after += after
        changed_rows += changed
        if changed and not dry_run:
            shutil.copy(path, path + ".bak-recost")
            data["runs"] = rows
            _atomic_json(path, data)
            touched += 1
        print(f"  {key:<24} {len(runs):>4}행 변경 {changed:>4}  ${before:>9,.0f} → ${after:>9,.0f}")
    mode = "(dry-run — 파일 미변경)" if dry_run else f"(파일 {touched}개 갱신, 백업 *.bak-recost)"
    print(f"  합계: {changed_rows}행  ${total_before:,.0f} → ${total_after:,.0f}  {mode}")
    return 0


def read_pipeline_status(path=None):
    """마지막 수집 결과. 파일이 없으면 빈 dict — "한 번도 안 돌았다"도 정보다."""
    path = path or PIPELINE_STATUS_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def record_pipeline_status(ok, error=None, done=0, failed=(), path=None):
    """수집 시도 결과를 남긴다.

    `last_success` 는 성공했을 때만 갱신한다. 실패해도 지우지 않는 이유는, 이 값의
    쓸모가 "마지막으로 데이터가 들어온 게 언제냐"이기 때문이다. 실패로 덮으면
    그 질문에 답할 수 없다.
    """
    path = path or PIPELINE_STATUS_PATH
    now = datetime.datetime.now(KST).isoformat(timespec="seconds")
    doc = read_pipeline_status(path)
    doc["version"] = 1
    doc["last_attempt"] = now
    doc["projects_done"] = int(done)
    doc["projects_failed"] = list(failed)
    if ok:
        doc["last_success"] = now
        doc["last_error"] = None
    else:
        doc["last_error"] = str(error)[:500] if error else "unknown"
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return doc


def _reconcile_all(a):
    """등록된 전 프로젝트 수집. 성공/실패 집계를 돌려준다."""
    failed = []
    done = 0
    projects = _projects()
    if not projects:
        raise SystemExit(
            "projects.json 이 비어 있다 — 수집할 프로젝트가 없다.\n"
            "  등록: python3 scripts/enroll.py --add-project <키>=<리포경로>\n"
            f"  파일: {CONFIG}")
    for key, meta in projects.items():
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
            done += 1
        except SystemExit as exc:
            print(f"[{key}] 건너뜀: {exc}")
            failed.append(key)
    if failed:
        raise SystemExit("실패한 프로젝트: " + ", ".join(failed))
    # 조용한 0건은 "성공했는데 데이터가 없는" 상태를 만든다. 크게 실패시킨다.
    if done == 0:
        raise SystemExit(
            f"등록된 {len(projects)}개 프로젝트 중 transcript 가 잡힌 것이 0개다.\n"
            "  kanban_dir 경로가 이 머신의 실제 리포와 맞는지 확인한다.\n"
            f"  파일: {CONFIG}")
    return {"done": done, "failed": failed}


def _run_all(a, status_path=None):
    """--all 경로. 결과를 pipeline-status.json 에 남기고 예외는 그대로 올린다.

    `status_path` 를 주입받는 이유: 이 함수는 사용자의 실제 운영 상태를 쓴다.
    테스트가 경로를 갈아끼우지 못하면 테스트 실행이 실제 파이프라인 건강 신호를
    "degraded" 로 오염시킨다. 실제로 그렇게 만들었다 — 감시 신호를 테스트가
    더럽힐 수 있으면 그 신호는 곧 무시된다.
    """
    try:
        result = _reconcile_all(a)
    except SystemExit as exc:
        record_pipeline_status(False, error=exc, path=status_path)
        raise
    record_pipeline_status(True, done=result["done"], failed=result["failed"],
                           path=status_path)
    return result


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
    ap.add_argument("--recost", action="store_true",
                    help="등록된 모든 프로젝트의 runs.json cost_usd 를 현행 단가로 재계산")
    a = ap.parse_args()

    if a.recost:
        raise SystemExit(recost_all(dry_run=a.dry_run))

    if a.all:
        _run_all(a)
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
