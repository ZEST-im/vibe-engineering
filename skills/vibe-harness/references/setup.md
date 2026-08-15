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
