#!/usr/bin/env python3
"""review_sync.py — 주간 리뷰를 중앙(zestim)으로 보낸다.

## 왜 옮기는가

리뷰는 지금까지 이 레포의 `docs/developer-reviews/` 에 쌓였는데, **이 레포는 공개**다.
자기 평가 점수와 지적이 그대로 밖에서 보인다. 지금까지 것은 도구가 무엇을 하는지 보여주는
샘플로 남기고, 앞으로는 중앙에 둔다.

## 어디까지 이 레포의 몫인가

- **여기(클라이언트)**: 리뷰를 읽어 payload 로 만들고 개인 토큰으로 전송한다
- **중앙(zestim, 다른 레포)**: 수신 라우트·저장·조회 화면

**중앙 라우트는 아직 없다** (`/api/internal/vibe-harness/reviews` → 404). 그래서 전송은
실패할 수 있고, 실패해도 로컬 파일은 남는다. 계약은 아래 `PAYLOAD` 주석에 적어둔다 —
중앙이 구현할 때 이 형태를 받으면 된다.

## 자격증명

`runs` 와 같다. 리뷰는 사람에 귀속되므로 **공유 secret 이 아니라 개인 토큰**이어야 한다.
공유 secret 하나로는 누구나 남의 이름으로 리뷰를 올릴 수 있다. `reconcile_runs.py` 의
`push_credential()` 을 그대로 재사용한다 — 여기서 다시 구현하면 두 경로가 갈라진다.

    python3 scripts/review_sync.py private/reviews/2026-W37.html
    python3 scripts/review_sync.py --dry-run <파일>
"""
import argparse
import importlib.util
import json
import os
import re
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 중앙이 받을 형태. 라우트가 생기면 이 계약대로 파싱하면 된다.
#
#   POST /api/internal/vibe-harness/reviews
#   Authorization: Bearer <개인 토큰>          ← owner 는 중앙이 토큰으로 판정한다
#   {
#     "period": "2026-W37",                    ← 같은 period 재전송은 갱신(upsert)
#     "repo":   "vibe-engineering",
#     "machine": "macbook",
#     "scores": {…9축…},
#     "priorities": [{category, severity, status, consecutive_weeks}, …],
#     "html":   "<!doctype html>…"             ← 자체완결 문서 전체
#   }
#
# 클라이언트가 owner 를 보내지 않는 것이 핵심이다. 보내면 위조된다.
PERIOD = re.compile(r"(\d{4}-W\d{2}r?)")


def load_module(name, filename):
    sys.path.insert(0, HERE)
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def period_of(path):
    """파일명에서 기간을 뽑는다. 못 뽑으면 추측하지 않는다 — 엉뚱한 주를 덮어쓴다."""
    m = PERIOD.search(os.path.basename(path))
    if not m:
        raise SystemExit(
            f"파일명에서 기간을 읽지 못했다: {os.path.basename(path)}\n"
            "  `2026-W37.html` 형식이어야 한다. 추측하면 다른 주를 덮어쓴다.")
    return m.group(1)


def history_entry(history_path, period):
    """history.json 에서 같은 기간의 점수·지적을 가져온다.

    HTML 만 보내면 중앙이 점수를 파싱해야 한다. 이미 구조화된 것이 있으므로 그것을 보낸다.
    """
    try:
        with open(history_path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (FileNotFoundError, ValueError):
        return None
    for entry in reversed(doc.get("reviews") or []):
        if entry.get("period", {}).get("label") == period:
            return entry
    return None


def build_payload(html_path, repo=None):
    period = period_of(html_path)
    with open(html_path, encoding="utf-8") as fh:
        html = fh.read()

    entry = history_entry(os.path.join(os.path.dirname(html_path), "history.json"), period)
    if entry is None:
        raise SystemExit(
            f"history.json 에 {period} 항목이 없다.\n"
            "  리뷰는 시리즈다 — HTML 만 있고 점수 기록이 없으면 추이를 이을 수 없다.")

    rr = load_module("rr_review", "reconcile_runs.py")
    cfg = rr._sync_cfg() or {}
    return {
        "period": period,
        "repo": repo or os.path.basename(ROOT),
        "machine": cfg.get("machine"),
        "scores": entry.get("scores"),
        "priorities": [
            {k: p.get(k) for k in ("category", "severity", "status", "consecutive_weeks")}
            for p in entry.get("priorities") or []
        ],
        "html": html,
    }


def push(payload):
    """중앙 전송. runs 와 같은 자격증명을 쓴다 — 여기서 다시 구현하지 않는다."""
    rr = load_module("rr_review", "reconcile_runs.py")
    cfg = rr._sync_cfg()
    if not cfg:
        raise SystemExit("sync.json 없음 — 중앙 전송 불가")
    endpoint = str(cfg.get("endpoint") or "")
    if not endpoint:
        raise SystemExit("sync.json 에 endpoint 없음")
    url = endpoint.rsplit("/", 1)[0] + "/reviews"
    return url, rr._http_post(url, payload, rr.push_credential(cfg))


def main(argv=None):
    ap = argparse.ArgumentParser(description="주간 리뷰를 중앙으로 전송")
    ap.add_argument("html", help="리뷰 HTML 경로 (파일명에 2026-W37 형식 포함)")
    ap.add_argument("--repo", help="중앙에 보고할 프로젝트 이름 (기본: 디렉토리명)")
    ap.add_argument("--dry-run", action="store_true", help="보내지 않고 payload 만 보여준다")
    a = ap.parse_args(argv)

    if not os.path.exists(a.html):
        raise SystemExit(f"파일 없음: {a.html}")
    payload = build_payload(a.html, a.repo)

    summary = {k: v for k, v in payload.items() if k != "html"}
    summary["html_bytes"] = len(payload["html"].encode("utf-8"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if a.dry_run:
        print("\n[dry-run] 전송하지 않았다")
        return 0

    url, result = push(payload)
    print(f"\n전송: {url}\n{json.dumps(result, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
