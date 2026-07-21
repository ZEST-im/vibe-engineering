#!/usr/bin/env python3
"""reconcile_runs.py — Claude Code transcript에서 프로젝트 runs.json 재구성.

record-run 훅/agentcat이 세션을 놓쳐 토큰 집계가 누락될 때(대시보드에 실사용이 안 뜰 때),
실제 세션 transcript(.jsonl)를 파싱해 runs.json을 다시 만든다.
세션 파일당 run 1건: tokens = input+output+cache_read+cache_write 합, ts = 파일 mtime(KST).

사용:
  python scripts/reconcile_runs.py <project_key>            # projects.json에서 경로 해석
  python scripts/reconcile_runs.py <project_key> --dry-run  # 미리보기(파일 미변경)
  python scripts/reconcile_runs.py --kanban-dir <DIR>       # 경로 직접 지정
  python scripts/reconcile_runs.py --kanban-dir <DIR> --transcripts <DIR>

재구성 후 vibe-harness sync(자동/수동)로 push하면 대시보드에 반영된다.
※ 토큰은 cache-read 포함 throughput 기준(vibe-harness 기존 집계와 동일). 과금은 cost($) 참고.
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil

CONFIG = os.path.expanduser("~/.claude/skills/vibe-harness/projects.json")
KST = datetime.timezone(datetime.timedelta(hours=9))


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
    # Claude Code는 프로젝트 cwd의 '/', '.', '_'를 '-'로 치환해 ~/.claude/projects/ 하위 디렉토리로 씀
    enc = re.sub(r"[/._]", "-", cwd)
    return os.path.expanduser(f"~/.claude/projects/{enc}")


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
        sid = os.path.splitext(os.path.basename(f))[0]
        ts = datetime.datetime.fromtimestamp(os.path.getmtime(f), KST).isoformat(timespec="seconds")
        runs.append({
            "task_id": None, "agent": "claude", "model": model or "claude",
            "tokens": tot, "input_tokens": inp, "output_tokens": out,
            "cache_read_tokens": cr, "cache_write_tokens": cw,
            "session_id": sid, "commit": "", "ts": ts, "source": "transcript-reconcile",
        })
    runs.sort(key=lambda r: r["ts"])
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", nargs="?", help="projects.json의 프로젝트 키")
    ap.add_argument("--kanban-dir", help="프로젝트 vibe-harness 디렉토리(직접 지정)")
    ap.add_argument("--transcripts", help="Claude transcript 디렉토리(직접 지정)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    kd = a.kanban_dir or (_kanban_dir_for(a.project) if a.project else None)
    if not kd:
        raise SystemExit("kanban_dir 해석 실패 — <project_key> 또는 --kanban-dir 필요")
    cwd = os.path.dirname(os.path.abspath(kd))
    td = a.transcripts or _transcript_dir(cwd)
    if not os.path.isdir(td):
        raise SystemExit(f"transcript 디렉토리 없음: {td}\n(--transcripts로 직접 지정 가능)")

    runs = build_runs(td)
    total = sum(r["tokens"] for r in runs)
    print(f"transcript: {td}")
    print(f"세션 {len(runs)}개 · 총 {total:,} 토큰 ({total/1e8:.2f}억)")
    byday = {}
    for r in runs:
        byday[r["ts"][:10]] = byday.get(r["ts"][:10], 0) + r["tokens"]
    for d, v in sorted(byday.items())[-14:]:
        print(f"  {d}: {v:,}")

    if a.dry_run:
        print("[dry-run] runs.json 미변경")
        return
    if not runs:
        raise SystemExit("재구성할 run 없음 — 중단(기존 runs.json 유지)")
    rp = os.path.join(kd, "runs.json")
    if os.path.exists(rp):
        shutil.copy2(rp, rp + ".bak")
        print(f"백업: {rp}.bak")
    with open(rp, "w") as fh:
        json.dump({"runs": runs}, fh, ensure_ascii=False, indent=1)
    print(f"기록: {rp} ({len(runs)} runs)")
    print("→ vibe-harness sync로 push하면 대시보드에 반영됩니다.")


if __name__ == "__main__":
    main()
