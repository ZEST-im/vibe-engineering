# Remote snapshot sync

> Reference for the `vibe-harness` skill. Load when you need it — not at session start.

## Optional Remote Snapshot Sync

Remote dashboards use an outbound, read-only snapshot publisher. Never expose
the localhost server or reuse an end-user login token as the upload secret.

Configuration: `~/.claude/skills/vibe-harness/sync.json` (chmod `600`):

```json
{
  "enabled": true,
  "endpoint": "https://example.com/api/internal/vibe-harness/sync",
  "secret": "dedicated-upload-secret",
  "dashboards": {"ax-project": ["impactbook_ai"]}
}
```

- A write to tasks, decisions, or runs schedules a debounced bundle upload.
- Archives are included with active tasks.
- Failed uploads are persisted to `sync-pending.json` and retried.
- Run `python3 ~/.claude/skills/vibe-harness/server.py sync` for a manual flush.
- Run `server.py configure-sync <endpoint> <dashboard> <project_key>...` to
  create the mode-0600 config without placing the secret in shell history.
- Dashboard access control belongs to the receiving application; the publisher
  only authenticates with its dedicated bearer secret.

## Weekly reviews

Reviews are written to a path the repository does not track and pushed to the central
store, because a review names weaknesses and scores a person — material that does not
belong in a public repo.

```bash
python3 scripts/review_sync.py private/reviews/2026-W37.html --dry-run
python3 scripts/review_sync.py private/reviews/2026-W37.html
```

`POST /api/internal/vibe-harness/reviews` with the **personal token**, not the shared
secret: a review is attributed to a person, and a shared secret would let anyone file one
under someone else's name. The client never sends an owner field — the server decides from
the token, the same rule `runs` follows.

The payload carries `period`, `repo`, `machine`, the nine `scores`, the `priorities` with
their consecutive-week counts, and the self-contained `html`. Scores travel structured
rather than parsed out of the document, because `history.json` already has them and a
second parser is a second thing to keep in step.

**The receiving route does not exist yet** (404 as of 2026-09-06). Until it does, pushes
fail and the local file remains the artifact. That is the intended failure mode: the review
is written first and sent second, never the reverse.
