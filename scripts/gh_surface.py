#!/usr/bin/env python3
"""gh_surface.py — 칸반을 정본으로 두고 GitHub 을 공개 표면으로 쓴다.

## 순수 파생과 네트워크를 가른다

`PHASES.md` → 릴리스 노트, `kanban.json` → 승격 대상은 **입력만 있으면 정해진다.**
그 층은 파일도 네트워크도 건드리지 않아 고정 입력으로 검사할 수 있다.
`gh` 를 부르는 층은 얇게 두고 가용성 게이트 뒤에 둔다 — CI 에는 인증이 없다.

## 외부 행위는 dry-run 이 기본이다

이슈·릴리스·프로젝트는 **만들면 남는다.** `--apply` 가 없으면 무엇을 할지 출력만 한다.
"""
import re

DONE_PHASE = re.compile(r"^##\s+(PHASE_\w+)\s+✅\s*DONE\s*\(([0-9-]+)\)\s*$", re.M)


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
    """한 Phase 의 릴리스 노트. 없으면 **`None`** — 빈 문자열이면 빈 릴리스가 생긴다."""
    sec = phase_sections(body).get(phase)
    if sec is None:
        return None
    head = f"## {sec['title']}" if sec["title"] else f"## {phase}"
    return f"{head}\n\n{sec['body']}\n"
