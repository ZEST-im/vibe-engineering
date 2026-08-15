#!/usr/bin/env python3
"""
Vibe Engineering Setup — Copy server files to ~/.claude/skills/vibe-harness/ and install launchd agent
"""
import os
import shutil
import subprocess
import sys

import json

DEST = os.path.expanduser("~/.claude/skills/vibe-harness")
SRC = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
PLIST_NAME = "com.vibe-harness.server.plist"
LAUNCH_AGENTS = os.path.expanduser("~/Library/LaunchAgents")
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
HOOKS_DIR = os.path.expanduser("~/.claude/hooks")
REPO_URL = "https://raw.githubusercontent.com/ZEST-im/vibe-engineering/main"

SKILLS_ROOT = os.path.expanduser("~/.claude/skills")
# 설치 대상 스킬 디렉토리 — repo skills/<name>/SKILL.md 가 원본
SKILLS = ["vibe-harness", "vibe-planning", "vibe-design", "vibe-review"]
# 언인스톨 시 디렉토리째 지워도 되는 스킬
# (vibe-harness 는 projects.json/server.log 가 함께 살아서 제외)
REMOVABLE_SKILLS = ["vibe-planning", "vibe-design", "vibe-review"]

# Hook definitions: (src_name, event, entry_dict)
HOOKS = [
    (
        "vibe-harness-scope-guard.sh",
        "PreToolUse",
        {
            "matcher": "Edit|Write",
            "hooks": [{"type": "command", "command": os.path.join(HOOKS_DIR, "vibe-harness-scope-guard.sh")}],
            "_id": "vibe-harness-scope-guard",
        },
    ),
    (
        "vibe-harness-review.sh",
        "PostToolUse",
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": os.path.join(HOOKS_DIR, "vibe-harness-review.sh")}],
            "_id": "vibe-harness-code-review",
        },
    ),
    (
        "vibe-harness-session-start.sh",
        "SessionStart",
        {
            "hooks": [{"type": "command", "command": os.path.join(HOOKS_DIR, "vibe-harness-session-start.sh")}],
            "_id": "vibe-harness-session-start",
        },
    ),
    (
        "vibe-harness-stop-gate.sh",
        "Stop",
        {
            "hooks": [{"type": "command", "command": os.path.join(HOOKS_DIR, "vibe-harness-stop-gate.sh")}],
            "_id": "vibe-harness-stop-gate",
        },
    ),
    (
        "vibe-harness-token-collector.sh",
        "SessionEnd",
        {
            "hooks": [{"type": "command", "command": os.path.join(HOOKS_DIR, "vibe-harness-token-collector.sh")}],
            "_id": "vibe-harness-token-collector",
        },
    ),
]

HOOK_IDS = {entry["_id"] for _, _, entry in HOOKS}

# Helper scripts copied alongside hooks (not registered as hooks themselves).
HOOK_HELPERS = ["vibe-harness-record-run.py"]


def copy_skill_files():
    """각 skills/<name>/SKILL.md 를 ~/.claude/skills/<name>/ 로 복사"""
    for name in SKILLS:
        src = os.path.join(SRC, "..", "skills", name, "SKILL.md")
        if not os.path.exists(src):
            print(f"  SKIP {name} (SKILL.md not found)")
            continue
        dest_dir = os.path.join(SKILLS_ROOT, name)
        os.makedirs(dest_dir, exist_ok=True)
        dst = os.path.join(dest_dir, "SKILL.md")
        shutil.copy2(src, dst)
        print(f"  COPIED {name}/SKILL.md → {dst}")


def remove_added_skills():
    """PHASE_PMF06 에서 추가된 스킬 디렉토리만 제거 (vibe-harness 는 보존)"""
    for name in REMOVABLE_SKILLS:
        d = os.path.join(SKILLS_ROOT, name)
        if os.path.isdir(d):
            shutil.rmtree(d)
            print(f"  REMOVED {d}")


def copy_server_files():
    """Copy server.py and kanban.html to ~/.claude/skills/vibe-harness/"""
    os.makedirs(DEST, exist_ok=True)

    copy_skill_files()

    files = ["server.py", "vibe_runtime.py", "worker.py", "kanban.html", "setup.py"]
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

    # Clean up old ~/.claude/kanban/ directory if it exists
    old_dir = os.path.expanduser("~/.claude/kanban")
    if os.path.isdir(old_dir):
        print(f"  NOTE: Old directory {old_dir} still exists. You can remove it manually.")


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


def install_hooks():
    """Copy all hook scripts to ~/.claude/hooks/ and register them in settings.json"""
    os.makedirs(HOOKS_DIR, exist_ok=True)
    hooks_src_dir = os.path.join(SRC, "hooks")

    # Copy hook scripts
    for script_name, _, _ in HOOKS:
        src = os.path.join(hooks_src_dir, script_name)
        dst = os.path.join(HOOKS_DIR, script_name)
        if not os.path.exists(src):
            print(f"  SKIP {script_name} (not found in hooks/)")
            continue
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755)
        print(f"  INSTALLED {script_name} → {dst}")

    # Copy helper scripts (recorder used by the token-collector hook)
    for helper in HOOK_HELPERS:
        src = os.path.join(hooks_src_dir, helper)
        dst = os.path.join(HOOKS_DIR, helper)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            os.chmod(dst, 0o755)
            print(f"  INSTALLED {helper} → {dst}")

    # Register in settings.json
    settings = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            settings = json.load(f)

    hooks_cfg = settings.setdefault("hooks", {})

    # Remove any existing vibe-harness entries across all event types
    for event in ("PreToolUse", "PostToolUse", "SessionStart", "Stop", "SessionEnd"):
        existing = hooks_cfg.get(event, [])
        hooks_cfg[event] = [h for h in existing if h.get("_id") not in HOOK_IDS]

    # Insert new entries
    for _, event, entry in HOOKS:
        hooks_cfg.setdefault(event, []).append(entry)

    # Clean up empty lists
    for event in list(hooks_cfg.keys()):
        if not hooks_cfg[event]:
            del hooks_cfg[event]

    settings["hooks"] = hooks_cfg

    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    print(f"  REGISTERED all hooks in {SETTINGS_PATH}")


def uninstall_hooks():
    """Remove all vibe-harness hook scripts and their settings.json entries"""
    # Remove scripts
    for script_name, _, _ in HOOKS:
        dst = os.path.join(HOOKS_DIR, script_name)
        if os.path.exists(dst):
            os.remove(dst)
            print(f"  REMOVED {dst}")
    for helper in HOOK_HELPERS:
        dst = os.path.join(HOOKS_DIR, helper)
        if os.path.exists(dst):
            os.remove(dst)
            print(f"  REMOVED {dst}")

    # Remove from settings.json
    if not os.path.exists(SETTINGS_PATH):
        print("  No settings.json found")
        return

    with open(SETTINGS_PATH, encoding="utf-8") as f:
        settings = json.load(f)

    hooks_cfg = settings.get("hooks", {})
    changed = False
    for event in ("PreToolUse", "PostToolUse", "SessionStart", "Stop", "SessionEnd"):
        before = hooks_cfg.get(event, [])
        after = [h for h in before if h.get("_id") not in HOOK_IDS]
        if len(after) < len(before):
            changed = True
            if after:
                hooks_cfg[event] = after
            else:
                hooks_cfg.pop(event, None)

    if changed:
        if hooks_cfg:
            settings["hooks"] = hooks_cfg
        else:
            settings.pop("hooks", None)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        print(f"  REMOVED vibe-harness hooks from {SETTINGS_PATH}")
    else:
        print("  No vibe-harness hooks found in settings")


def uninstall_launchd():
    """Uninstall launchd agent"""
    dst = os.path.join(LAUNCH_AGENTS, PLIST_NAME)
    if os.path.exists(dst):
        subprocess.run(["launchctl", "unload", dst], capture_output=True)
        os.remove(dst)
        print(f"  REMOVED {dst}")
    else:
        print(f"  {PLIST_NAME} not installed")


def migrate_projects_json():
    """Migrate projects.json from old db_path format to new kanban_dir format"""
    config_path = os.path.join(DEST, "projects.json")
    if not os.path.exists(config_path):
        return

    with open(config_path) as f:
        projects = json.load(f)

    changed = False
    for key, info in projects.items():
        if "db_path" in info and "kanban_dir" not in info:
            db_path = info["db_path"]
            info["kanban_dir"] = os.path.dirname(db_path)
            del info["db_path"]
            changed = True
            print(f"  MIGRATED {key}: db_path → kanban_dir ({info['kanban_dir']})")

    if changed:
        with open(config_path, "w") as f:
            json.dump(projects, f, indent=2, ensure_ascii=False)


def upgrade():
    """Download latest files from GitHub and reinstall"""
    import urllib.request
    import tempfile

    print("Upgrading Vibe Engineering from GitHub...")
    print()

    files = {
        "server.py": f"{REPO_URL}/scripts/server.py",
        "vibe_runtime.py": f"{REPO_URL}/scripts/vibe_runtime.py",
        "worker.py": f"{REPO_URL}/scripts/worker.py",
        "kanban.html": f"{REPO_URL}/scripts/kanban.html",
        "setup.py": f"{REPO_URL}/scripts/setup.py",
    }

    os.makedirs(DEST, exist_ok=True)
    downloaded = 0

    for fname, url in files.items():
        dst = os.path.join(DEST, fname)
        try:
            print(f"  Downloading {fname}...")
            req = urllib.request.Request(url, headers={"User-Agent": "Vibe-Engineering-Setup"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read()
            # Backup existing
            if os.path.exists(dst):
                shutil.copy2(dst, dst + ".bak")
            with open(dst, "wb") as f:
                f.write(content)
            downloaded += 1
            print(f"  OK {fname} ({len(content)} bytes)")
        except Exception as e:
            print(f"  FAIL {fname}: {e}")

    # 스킬은 각자 ~/.claude/skills/<name>/SKILL.md 로 내려받는다 (DEST 하위가 아님)
    for name in SKILLS:
        dest_dir = os.path.join(SKILLS_ROOT, name)
        dst = os.path.join(dest_dir, "SKILL.md")
        try:
            print(f"  Downloading {name}/SKILL.md...")
            req = urllib.request.Request(f"{REPO_URL}/skills/{name}/SKILL.md",
                                         headers={"User-Agent": "Vibe-Engineering-Setup"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read()
            os.makedirs(dest_dir, exist_ok=True)
            if os.path.exists(dst):
                shutil.copy2(dst, dst + ".bak")
            with open(dst, "wb") as f:
                f.write(content)
            downloaded += 1
            print(f"  OK {name}/SKILL.md ({len(content)} bytes)")
        except Exception as e:
            print(f"  FAIL {name}/SKILL.md: {e}")

    print()
    if downloaded == 0:
        print("No files downloaded. Check your network connection.")
        return

    print(f"Updated {downloaded}/{len(files) + len(SKILLS)} files.")

    # Restart server if running
    try:
        result = subprocess.run(["lsof", "-ti:4242"], capture_output=True, text=True)
        pids = result.stdout.strip()
        if pids:
            for pid in pids.split("\n"):
                subprocess.run(["kill", pid.strip()], capture_output=True)
            print("Stopped running server.")
            # Restart via launchd if available
            plist = os.path.join(LAUNCH_AGENTS, PLIST_NAME)
            if os.path.exists(plist):
                subprocess.run(["launchctl", "unload", plist], capture_output=True)
                subprocess.run(["launchctl", "load", plist], capture_output=True)
                print("Restarted server via launchd.")
            else:
                print("Restart the server manually: python3 ~/.claude/skills/vibe-harness/server.py serve &")
    except Exception:
        pass

    print()
    print("Upgrade complete!")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "uninstall":
        print("Uninstalling Vibe Engineering...")
        uninstall_launchd()
        uninstall_hooks()
        remove_added_skills()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "upgrade":
        upgrade()
        return

    print("Setting up Vibe Engineering...")
    print()

    # Step 1: Copy server files
    print("[1/4] Copying server files...")
    copy_server_files()
    print()

    # Step 2: Migrate projects.json if needed
    print("[2/4] Migrating project registry...")
    migrate_projects_json()
    print()

    # Step 3: Install launchd agent
    print("[3/4] Installing launchd agent (auto-start on login)...")
    install_launchd()
    print()

    # Step 4: Install hooks (scope guard, session start, stop gate, code review)
    print("[4/4] Installing hooks...")
    install_hooks()
    print()

    print("Setup complete!")
    print(f"  Server: {DEST}/server.py")
    print(f"  UI:     {DEST}/kanban.html")
    print(f"  Log:    {DEST}/server.log")
    print()
    print("Hooks installed:")
    print("  PreToolUse  → vibe-harness-scope-guard.sh   (blocks Do NOT touch file edits)")
    print("  PostToolUse → vibe-harness-review.sh         (code review gate on git push)")
    print("  SessionStart→ vibe-harness-session-start.sh  (loads CURRENT_PHASE.md)")
    print("  Stop        → vibe-harness-stop-gate.sh      (warns on in_progress tasks)")
    print()
    print("The server will auto-start on login (port 4242).")
    print("Open: http://localhost:4242/kanban")
    print()
    print("Storage: JSON files (git-friendly)")
    print("  Active tasks: {project}/vibe-harness/kanban.json")
    print("  Archives:     {project}/vibe-harness/archive/YYYY-MM.json")
    print()
    print("To uninstall:")
    print(f"  python3 {os.path.abspath(__file__)} uninstall")


if __name__ == "__main__":
    main()
