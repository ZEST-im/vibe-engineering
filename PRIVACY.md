# Privacy Policy — Vibe-Engineering

**Last updated**: 2026-08-24

## Summary

Vibe-Engineering runs on your local machine and makes **no network requests by default**.

It has one optional feature that transmits data: **token usage collection**. It is off until you
explicitly configure it, and even then it sends only counters — never the content of your
conversations, prompts, or code. This document describes both states.

## Default state — nothing leaves your machine

Out of the box:

- All task data lives in JSON files (`vibe-harness/kanban.json`, `decisions.json`, `runs.json`,
  `archive/YYYY-MM.json`) inside your own project directories, git-tracked alongside your code.
- The project registry lives at `~/.claude/skills/vibe-harness/projects.json` on your filesystem.
- The web server binds to `127.0.0.1` (localhost only) and is not reachable from the network.
- No analytics, no tracking, no crash reporting, no update pings.
- `localStorage` is used only for view preferences such as theme.
- No account and no authentication are required.

## Optional — token usage collection

Claude Code writes a transcript for each session under `~/.claude/projects/`. Those files already
sit on your disk and already contain token counts. `scripts/reconcile_runs.py` reads them to
rebuild how many tokens each session used per calendar day, and writes the result to your local
`runs.json`. **This part is still entirely local.**

Transmission happens only if `~/.claude/skills/vibe-harness/sync.json` exists with an endpoint and
a credential. That file is created when you run `scripts/enroll.py` or
`server.py configure-sync` — both are deliberate acts. If you never run them, nothing is ever sent.

### What is transmitted, when enabled

| Field | Example |
|---|---|
| project key | `codebook` |
| session id | the transcript's filename UUID |
| date | `2026-08-24` |
| model | `claude-opus-5` |
| token counts | input / output / cache-read / cache-write |
| computed cost | derived from the token counts |
| machine label | `mba-01` |
| commit hash | when the recording hook captured one |
| agent name | `claude` |
| record source | `transcript-daily` |

Dashboard snapshots, if you enable them separately, additionally send your kanban task titles,
statuses, and phase names — the same data already stored in your git-tracked JSON files.

### What is never transmitted

- Transcript content, prompt text, or model responses
- Source code, file contents, or file paths
- Environment variables, credentials, or the contents of any `.env`
- Anything from projects you have not registered with `--add-project`

### Where it is transmitted

To the endpoint **you** configure. The default value in `enroll.py` points at ZEST's internal
server and will reject anyone outside that organization; if you are running your own, pass
`--endpoint`. This project does not send data to any third-party service.

### Authentication, when enabled

Enabling collection means holding a credential in `sync.json`:

- `secret` — authenticates dashboard snapshots, shared per project.
- `runs_token` — authenticates usage rows, personal to one person and machine.

The file is written with `0600` permissions. **On Windows this does not apply** — Windows does not
enforce POSIX permissions, so the file is readable by anything running under your account. Treat
that machine's profile accordingly.

### Turning it off

Delete `~/.claude/skills/vibe-harness/sync.json`. Collection stops immediately and the rest of the
tool keeps working. Remove the scheduled collector as well:

```bash
# macOS
launchctl bootout gui/$UID ~/Library/LaunchAgents/com.vibe-harness.reconcile.plist
rm ~/Library/LaunchAgents/com.vibe-harness.reconcile.plist

# Windows
schtasks /Delete /TN VibeHarnessReconcile /F
```

Data already sent stays on the endpoint you sent it to; ask that endpoint's operator to remove it.

## Data retention on your machine

`runs.json` and the archives grow indefinitely until you delete them. They are ordinary files in
your repository — you control them the same way you control any other file you commit.

## Contact

- Email: info@zest.im
- GitHub: https://github.com/ZEST-im/vibe-engineering/issues
