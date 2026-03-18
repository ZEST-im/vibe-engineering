#!/usr/bin/env python3
"""
VibeKanban Setup — Copy server files to ~/.claude/kanban/ and install launchd agent
"""
import os
import shutil
import subprocess
import sys

DEST = os.path.expanduser("~/.claude/kanban")
SRC = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
PLIST_NAME = "com.vibekanban.server.plist"
LAUNCH_AGENTS = os.path.expanduser("~/Library/LaunchAgents")


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
        print("Uninstalling VibeKanban launchd agent...")
        uninstall_launchd()
        return

    print("Setting up VibeKanban...")
    print()

    # Step 1: Copy server files
    print("[1/2] Copying server files...")
    copy_server_files()
    print()

    # Step 2: Install launchd agent
    print("[2/2] Installing launchd agent (auto-start on login)...")
    install_launchd()
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
