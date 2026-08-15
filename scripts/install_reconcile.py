#!/usr/bin/env python3
"""install_reconcile.py — 이 머신에 토큰 사용량 주기 전송(launchd)을 설치.

3시간마다 reconcile_runs.py --all --push 를 돌려, 이 머신에서 작업한 모든 프로젝트의
Claude 세션 토큰 사용량을 중앙 저장소로 보낸다(session_id로 union → 팀 전체 합산).

전제: sync.json(endpoint+secret)이 설정돼 있어야 함
      (없으면: server.py configure-sync ... 또는 기존 sync 설정 재사용).

사용: python3 scripts/install_reconcile.py            # 설치+로드(즉시 1회 실행)
      python3 scripts/install_reconcile.py --uninstall
"""
import argparse
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
LABEL = "com.vibe-harness.reconcile"
PLIST = os.path.join(HOME, "Library/LaunchAgents", LABEL + ".plist")
RECONCILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "reconcile_runs.py"))
LOG = os.path.join(HOME, ".claude/skills/vibe-harness/reconcile.log")
INTERVAL = 10800  # 3h

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>{reconcile}</string>
    <string>--all</string>
    <string>--push</string>
  </array>
  <key>StartInterval</key><integer>{interval}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()

    if sys.platform != "darwin":
        raise SystemExit("launchd는 macOS 전용 — 다른 OS는 cron으로 "
                         f"'*/180 * * * * /usr/bin/python3 {RECONCILE} --all --push' 등록")

    if os.path.exists(PLIST):
        subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
    if a.uninstall:
        if os.path.exists(PLIST):
            os.remove(PLIST)
        print("제거됨:", PLIST)
        return

    sync = os.path.join(HOME, ".claude/skills/vibe-harness/sync.json")
    if not os.path.exists(sync):
        print("⚠️ sync.json 없음 — 먼저 sync 설정 필요:")
        print("   VIBE_HARNESS_SYNC_SECRET=<시크릿> python3 <repo>/scripts/server.py \\")
        print("     configure-sync https://os.zest.im/api/internal/vibe-harness/sync ax-project <내프로젝트>")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(PLIST, "w") as fh:
        fh.write(TEMPLATE.format(label=LABEL, reconcile=RECONCILE, interval=INTERVAL, log=LOG))
    r = subprocess.run(["launchctl", "load", PLIST], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"설치+로드 완료: {PLIST}")
        print("  → 3시간마다 + 로드 시 1회: reconcile_runs.py --all --push")
        print(f"  로그: {LOG}")
    else:
        print("launchctl load 실패:", r.stderr.strip())


if __name__ == "__main__":
    main()
