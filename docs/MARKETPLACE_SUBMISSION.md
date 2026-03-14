# Anthropic Marketplace Submission — VibeKanban

제출 URL: https://platform.claude.com/plugins/submit
레포: https://github.com/hoarchi/vibekanban

---

## Description

VibeKanban is a dev progress kanban board that runs entirely inside Claude Code. When you code with Claude, every task is automatically tracked — started, completed, and reported — on a local kanban board with a browser-based UI.

No cloud service, no sign-up, no npm install. Just a Python server on localhost and a single HTML file. Claude creates tasks when you ask for work, moves them through columns as progress happens, records git diff stats on completion, and writes work reports you can review later in the web UI.

Multi-project support lets you manage several codebases from one board. Switch between projects with tabs, drag cards between columns, and view completed work grouped by date, category, or development phase.

---

## Use Cases

### 1. Solo Developer — Daily Progress Tracking

You're building a side project and want to see what you actually accomplished each day. Instead of maintaining a PROGRESS.md by hand, VibeKanban captures every task Claude works on. At the end of the day, open `localhost:4242/kanban` and see your done column with code change stats (+142 / -38 lines), elapsed time, and work reports for each task.

### 2. Vibe Coding Sessions — Staying Organized

During a long vibe coding session, it's easy to lose track of what's done and what's left. VibeKanban keeps a live board that auto-refreshes every 5 seconds. You can see at a glance: 2 tasks in progress, 5 in backlog, 12 done today. The list view gives you a spreadsheet-style overview of everything, with inline editing.

### 3. Multi-Project Management — One Dashboard

You're working on 3 projects this week. Each has its own SQLite DB, but one VibeKanban server serves them all. Tab between projects in the header, see per-project stats, and never mix up which tasks belong where.

### 4. Team Standups — Work Reports

When you need to report what you did, click any completed task in the kanban UI. The detail panel shows exactly which files changed, what technical decisions were made, and what follow-up work remains. Copy-paste ready for Slack, Linear, or standup notes.

### 5. PROGRESS.md Replacement

Tired of manually updating PROGRESS.md? Run `/vibekanban sync` to import existing records, then let the kanban handle all future tracking. Claude automatically writes work details on task completion — no more "update the progress doc" at the end of every session.

---

## Key Differentiators

- **Zero dependencies**: No npm, no pip install, no Docker. Python 3.6+ and a browser.
- **Fully local**: Everything runs on localhost. No data leaves your machine.
- **Auto-tracking**: Claude records tasks, code changes, and work reports without manual input.
- **Multi-project**: One server, multiple projects, tab-based switching.
- **Two views**: Kanban (drag & drop) + List (inline spreadsheet editing).
- **Dark/Light mode**: Respects your preference.
