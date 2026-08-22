# First-time setup

> Reference for the `vibe-harness` skill. Load when you need it — not at session start.

## Setup (First Time)

After installing the plugin, run the setup script to copy server files (only needed if you want the Board UI / auto-start):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py
```

This will:
1. Copy `server.py`, `kanban.html`, `SKILL.md` to `~/.claude/skills/vibe-harness/`
2. Install a macOS LaunchAgent (`com.vibe-harness.server`) that auto-starts the server on login
3. Register a code review hook in `~/.claude/settings.json`

To uninstall auto-start:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup.py uninstall
```

You can skip setup entirely if you only want to edit the JSON files directly — the kanban data still lives in `{project}/vibe-harness/kanban.json` regardless.

## Moving or renaming a project directory

Background jobs hold **absolute paths** and fail silently when the directory moves.
Nothing surfaces the failure — the board keeps working, so the loss is invisible.
After a move or rename, check all four:

```bash
# 1. Server project registration (the key is derived from the directory name)
curl -X POST localhost:4242/api/projects \
  -d '{"key":"...","name":"...","kanban_dir":"<abs>/vibe-harness"}'

# 2. Periodic token reconciliation — the plist stores the old script path.
#    Re-run from the NEW location; install_reconcile.py derives the path from its own
#    file, so it repairs itself.
python3 scripts/install_reconcile.py

# 3. Confirm every job actually succeeded. A crash-looping job looks identical to a
#    healthy one in `launchctl list` unless you read the exit status.
launchctl list | grep vibe          # column 2 is the last exit status; 0 is healthy
tail -20 ~/.claude/skills/vibe-harness/reconcile.log

# 4. Redeploy, then restart — in that order. Restarting first makes launchd
#    reload the OLD code before the new files land.
python3 scripts/setup.py
launchctl kickstart -k gui/$(id -u)/com.vibe-harness.server
```

Watch for **stale jobs from an earlier install name**. A LaunchAgent whose target no
longer exists but has `KeepAlive` set will restart forever, appending the same error to
its log — one such job reached 104 MB before anyone noticed. `launchctl bootout` it and
move the plist aside.

## Detecting a project's data directory

A directory named `vibe-harness/` is not proof it belongs to this tool — the name
collides with hand-rolled coordination folders. Check for the **file**, not the
directory: `{project}/vibe-harness/kanban.json`. Registering a look-alike drops an
empty board into someone else's folder.
