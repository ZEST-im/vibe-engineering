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
import urllib.request

CONFIG = os.path.expanduser("~/.claude/skills/vibe-harness/projects.json")
SYNC_CONFIG = os.path.expanduser("~/.claude/skills/vibe-harness/sync.json")
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


def _push_central(project, runs):
    """중앙 저장소(zestim)로 runs 전송. sync.json의 endpoint/secret 재사용."""
    try:
        cfg = json.load(open(SYNC_CONFIG))
    except Exception:
        raise SystemExit(f"sync.json 없음/오류 — 중앙 전송 불가: {SYNC_CONFIG}")
    endpoint = str(cfg.get("endpoint", ""))
    secret = str(cfg.get("secret", ""))
    if not endpoint or not secret:
        raise SystemExit("sync.json에 endpoint/secret 없음")
    runs_url = endpoint.rsplit("/", 1)[0] + "/runs"   # .../vibe-harness/sync → .../vibe-harness/runs
    body = json.dumps({"project": project, "runs": runs}).encode("utf-8")
    req = urllib.request.Request(runs_url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {secret}",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def reconcile(project, kanban_dir, transcripts, dry_run=False, push=False):
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
    if os.path.exists(rp):
        shutil.copy2(rp, rp + ".bak")
    with open(rp, "w") as fh:
        json.dump({"runs": runs}, fh, ensure_ascii=False, indent=1)
    print(f"  로컬 기록: {rp}")
    if push:
        res = _push_central(project, runs)
        print(f"  중앙 전송: {res}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", nargs="?", help="projects.json의 프로젝트 키")
    ap.add_argument("--all", action="store_true", help="로컬 transcript 있는 모든 프로젝트")
    ap.add_argument("--kanban-dir")
    ap.add_argument("--transcripts")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--push", action="store_true", help="중앙 저장소로 전송")
    a = ap.parse_args()

    if a.all:
        for key, meta in _projects().items():
            kd = meta.get("kanban_dir") if isinstance(meta, dict) else meta
            if not kd:
                continue
            td = _transcript_dir(os.path.dirname(os.path.abspath(kd)))
            if not os.path.isdir(td) or not glob.glob(td + "/*.jsonl"):
                continue
            reconcile(key, kd, td, dry_run=a.dry_run, push=a.push)
        return

    kd = a.kanban_dir or (_kanban_dir_for(a.project) if a.project else None)
    if not kd:
        raise SystemExit("kanban_dir 해석 실패 — <project_key> 또는 --kanban-dir/--all 필요")
    td = a.transcripts or _transcript_dir(os.path.dirname(os.path.abspath(kd)))
    if not os.path.isdir(td):
        raise SystemExit(f"transcript 디렉토리 없음: {td} (--transcripts로 지정 가능)")
    reconcile(a.project or os.path.basename(os.path.dirname(kd)), kd, td, dry_run=a.dry_run, push=a.push)


if __name__ == "__main__":
    main()
