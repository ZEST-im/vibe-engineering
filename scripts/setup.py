#!/usr/bin/env python3
"""
VibeKanban Setup — Copy server files to ~/.claude/kanban/
"""
import os
import shutil

DEST = os.path.expanduser("~/.claude/kanban")
SRC = os.path.dirname(os.path.abspath(__file__))

def main():
    os.makedirs(DEST, exist_ok=True)

    files = ["server.py", "kanban.html"]
    for f in files:
        src = os.path.join(SRC, f)
        dst = os.path.join(DEST, f)
        if not os.path.exists(src):
            print(f"  SKIP {f} (not found in plugin)")
            continue
        if os.path.exists(dst):
            # Backup existing file
            bak = dst + ".bak"
            shutil.copy2(dst, bak)
            print(f"  BACKUP {f} → {f}.bak")
        shutil.copy2(src, dst)
        print(f"  COPIED {f} → {dst}")

    print()
    print("Setup complete!")
    print(f"  Server: {DEST}/server.py")
    print(f"  UI:     {DEST}/kanban.html")
    print()
    print("Start the server:")
    print(f'  python3 {DEST}/server.py serve 4242 &')
    print()
    print("Then open: http://localhost:4242/kanban")

if __name__ == "__main__":
    main()
