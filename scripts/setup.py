#!/usr/bin/env python3
"""
VibeKanban Setup — Copy server files to ~/.claude/kanban/ and install launchd agent
"""
import os
import shutil
import subprocess
import sys

import json

DEST = os.path.expanduser("~/.claude/kanban")
SRC = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
PLIST_NAME = "com.vibekanban.server.plist"
LAUNCH_AGENTS = os.path.expanduser("~/Library/LaunchAgents")
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")


def copy_server_files():
    """Copy server.py and kanban.html to ~/.claude/kanban/"""
    os.makedirs(DEST, exist_ok=True)

    files = ["server.py", "kanban.html"]
    for f in files:
        src = os.path.join(SRC, f)
        dst = os.path.join(DEST, f)
        if not os.path.exists(src):
            print(f"  SKIP {f} (not found in plugin)")
            continue
        if os.path.exists(dst):
            bak = dst + ".bak"
            shutil.copy2(dst, bak)
            print(f"  BACKUP {f} → {f}.bak")
        shutil.copy2(src, dst)
        print(f"  COPIED {f} → {dst}")


def install_launchd():
    """Install launchd agent for auto-starting kanban server on login"""
    os.makedirs(LAUNCH_AGENTS, exist_ok=True)

    # Read template and expand __HOME__
    template_path = os.path.join(SRC, PLIST_NAME)
    if not os.path.exists(template_path):
        print(f"  SKIP launchd (template {PLIST_NAME} not found)")
        return False

    with open(template_path, encoding="utf-8") as f:
        content = f.read().replace("__HOME__", HOME)

    dst = os.path.join(LAUNCH_AGENTS, PLIST_NAME)

    # Unload existing agent if present
    if os.path.exists(dst):
        subprocess.run(["launchctl", "unload", dst], capture_output=True)
        print(f"  UNLOADED existing {PLIST_NAME}")

    with open(dst, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  INSTALLED {dst}")

    # Load the agent
    result = subprocess.run(["launchctl", "load", dst], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  LOADED {PLIST_NAME} — server will auto-start on login")
        return True
    else:
        print(f"  WARN: launchctl load failed: {result.stderr.strip()}")
        return False


HOOKS_DIR = os.path.expanduser("~/.claude/hooks")
HOOK_SCRIPT = os.path.join(HOOKS_DIR, "vibekanban-review.sh")

HOOK_SCRIPT_CONTENT = r'''#!/bin/bash
# VibeKanban Code Review Hook
# Triggers after git push or gh pr create
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

if echo "$COMMAND" | grep -qE '^\s*(git\s+push|gh\s+pr\s+create)'; then
  echo "[VibeKanban] Code review triggered. Please perform a code review now:"
  echo "1. Run git diff to see all pushed changes"
  echo "2. Check for: security issues, code quality, architecture concerns"
  echo "3. Store review findings in the current kanban task's review field"
  echo "4. Print review summary with severity levels"
fi
exit 0
'''

REVIEW_HOOK_ENTRY = {
    "matcher": "Bash",
    "hooks": [
        {
            "type": "command",
            "command": HOOK_SCRIPT,
        }
    ],
}

HOOK_ID = "vibekanban-code-review"


def install_hooks():
    """Install code review hook script and register in settings.json"""
    # Step 1: Write hook script
    os.makedirs(HOOKS_DIR, exist_ok=True)
    with open(HOOK_SCRIPT, "w", encoding="utf-8") as f:
        f.write(HOOK_SCRIPT_CONTENT)
    os.chmod(HOOK_SCRIPT, 0o755)
    print(f"  INSTALLED hook script: {HOOK_SCRIPT}")

    # Step 2: Register in settings.json
    settings = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            settings = json.load(f)

    hooks = settings.setdefault("hooks", {})
    post_hooks = hooks.setdefault("PostToolUse", [])

    # Remove existing vibekanban hook if present
    post_hooks = [h for h in post_hooks if not _is_vibekanban_hook(h)]

    entry = dict(REVIEW_HOOK_ENTRY)
    entry["_id"] = HOOK_ID  # marker for identification
    post_hooks.append(entry)

    hooks["PostToolUse"] = post_hooks
    settings["hooks"] = hooks

    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    print(f"  REGISTERED hook in {SETTINGS_PATH}")


def _is_vibekanban_hook(h):
    """Check if a hook entry is a vibekanban hook"""
    if h.get("_id") == HOOK_ID:
        return True
    for hook in h.get("hooks", []):
        if hook.get("command", "").endswith("vibekanban-review.sh"):
            return True
    return False


def uninstall_hooks():
    """Remove code review hook from settings.json and delete script"""
    # Remove script
    if os.path.exists(HOOK_SCRIPT):
        os.remove(HOOK_SCRIPT)
        print(f"  REMOVED {HOOK_SCRIPT}")

    # Remove from settings.json
    if not os.path.exists(SETTINGS_PATH):
        print("  No settings.json found")
        return

    with open(SETTINGS_PATH, encoding="utf-8") as f:
        settings = json.load(f)

    hooks = settings.get("hooks", {})
    post_hooks = hooks.get("PostToolUse", [])
    before = len(post_hooks)
    post_hooks = [h for h in post_hooks if not _is_vibekanban_hook(h)]

    if len(post_hooks) < before:
        hooks["PostToolUse"] = post_hooks
        if not post_hooks:
            del hooks["PostToolUse"]
        if not hooks:
            del settings["hooks"]
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        print(f"  REMOVED hook from {SETTINGS_PATH}")
    else:
        print("  Code review hook not found in settings")


def uninstall_launchd():
    """Uninstall launchd agent"""
    dst = os.path.join(LAUNCH_AGENTS, PLIST_NAME)
    if os.path.exists(dst):
        subprocess.run(["launchctl", "unload", dst], capture_output=True)
        os.remove(dst)
        print(f"  REMOVED {dst}")
    else:
        print(f"  {PLIST_NAME} not installed")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "uninstall":
        print("Uninstalling VibeKanban...")
        uninstall_launchd()
        uninstall_hooks()
        return

    print("Setting up VibeKanban...")
    print()

    # Step 1: Copy server files
    print("[1/3] Copying server files...")
    copy_server_files()
    print()

    # Step 2: Install launchd agent
    print("[2/3] Installing launchd agent (auto-start on login)...")
    install_launchd()
    print()

    # Step 3: Install code review hook
    print("[3/3] Installing code review hook...")
    install_hooks()
    print()

    print("Setup complete!")
    print(f"  Server: {DEST}/server.py")
    print(f"  UI:     {DEST}/kanban.html")
    print(f"  Log:    {DEST}/server.log")
    print()
    print("The server will auto-start on login (port 4242).")
    print("Open: http://localhost:4242/kanban")
    print()
    print("To uninstall auto-start:")
    print(f"  python3 {os.path.abspath(__file__)} uninstall")


if __name__ == "__main__":
    main()
