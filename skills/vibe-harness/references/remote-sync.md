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
