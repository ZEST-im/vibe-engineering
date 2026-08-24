#!/usr/bin/env python3
"""enroll.py — 직원 머신을 토큰 사용량 수집에 등록한다.

한 사람이 여러 머신을 교차 사용하고, 여러 사람이 같은 프로젝트를 작업한다. 각 머신이
자기 transcript 를 중앙(zestim)으로 보내면 중앙에서 합산돼 대시보드에 뜬다. 이 스크립트는
그 "각 머신" 쪽 설정을 한 번에 세운다.

  python3 scripts/enroll.py --token <zestim에서 발급받은 토큰>
  python3 scripts/enroll.py --token <토큰> --machine studio-02
  python3 scripts/enroll.py --repair          # 토큰은 그대로, 에이전트 경로만 교정
  python3 scripts/enroll.py --dry-run --token t   # 무엇이 바뀌는지만 보기

owner(누가 썼는지)는 이 스크립트가 정하지 않는다. 클라이언트는 토큰만 제시하고, 중앙이
토큰으로 사람을 판정한다 — 그래서 남의 이름으로 보고할 수 없고, 퇴사 시 토큰 폐기로
즉시 끊긴다.

재실행해도 안전하다. 에이전트 Label 이 고정이라 두 번 실행해도 두 개가 되지 않고,
sync.json 의 기존 키(dashboards 등)는 보존한다.
"""
import argparse
import json
import os
import plistlib
import subprocess
import sys

SKILL_DIR = os.path.expanduser("~/.claude/skills/vibe-harness")
SYNC_CONFIG = os.path.join(SKILL_DIR, "sync.json")
PROJECTS_CONFIG = os.path.join(SKILL_DIR, "projects.json")
RECONCILE_LOG = os.path.join(SKILL_DIR, "reconcile.log")

AGENT_LABEL = "com.vibe-harness.reconcile"
DEFAULT_INTERVAL = 10800          # 3시간
DEFAULT_ENDPOINT = "https://os.zest.im/api/internal/vibe-harness/sync"


# ── 설정 ─────────────────────────────────────────────

def merge_sync_config(existing, token, endpoint, machine=None, runs_schema=None,
                     shared_secret=None):
    """기존 sync.json 위에 등록 정보를 얹는다. 모르는 키는 건드리지 않는다.

    개인 토큰은 runs_token 에 넣는다. secret 은 스냅샷(/sync)용 프로젝트 공유 값이라
    건드리면 대시보드 동기화가 401 로 죽는다 — 실제로 한 번 깨뜨렸다.
    """
    token = str(token or "").strip()
    endpoint = str(endpoint or "").strip()
    if not token:
        raise ValueError("토큰이 비어 있다 — zestim에서 발급받은 값을 --token 으로 준다")
    if not endpoint:
        raise ValueError("endpoint 가 비어 있다")

    cfg = dict(existing or {})
    cfg["enabled"] = True
    cfg["endpoint"] = endpoint
    cfg["runs_token"] = token
    if shared_secret is not None:
        shared = str(shared_secret).strip()
        if shared:
            cfg["secret"] = shared
    if machine is not None:
        label = str(machine).strip()
        if label:
            cfg["machine"] = label
    if runs_schema is not None:
        cfg["runs_schema"] = int(runs_schema)
    return cfg


def write_sync_config(path, cfg):
    """시크릿이 들어가므로 소유자만 읽을 수 있게 쓴다."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def bootstrap_projects(path):
    """프로젝트 레지스트리가 없으면 빈 것으로 만든다. 있으면 절대 덮지 않는다."""
    if not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({}, fh, ensure_ascii=False, indent=2)
        return "created"
    try:
        read_json(path)
    except Exception as exc:
        raise SystemExit(f"projects.json 파싱 실패 — 덮어쓰지 않고 중단: {path} ({exc})") from exc
    return "kept"


# ── 수집 에이전트 ────────────────────────────────────

def resolve_script_path():
    """이 파일 옆의 reconcile_runs.py 절대경로.

    리포 폴더명이 바뀌면 에이전트가 죽은 경로를 가리키게 된다(실제로 그렇게 터졌다).
    설치 시점의 실제 위치를 쓰고, --repair 로 언제든 다시 맞출 수 있게 한다.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "reconcile_runs.py")


SYSTEM_PYTHON = "/usr/bin/python3"


def default_agent_python(exists=os.path.exists):
    """에이전트가 쓸 인터프리터.

    reconcile_runs.py 는 stdlib 만 쓰므로 시스템 python 으로 충분하고, Homebrew python
    을 가리키면 그쪽이 업그레이드·제거될 때 수집이 조용히 멈춘다.
    """
    return SYSTEM_PYTHON if exists(SYSTEM_PYTHON) else sys.executable


def build_launchd_plist(script, log, interval=DEFAULT_INTERVAL, python=None):
    plist = {
        "Label": AGENT_LABEL,
        "ProgramArguments": [python or default_agent_python(), script, "--all", "--push"],
        "StartInterval": int(interval),
        "RunAtLoad": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
    return plistlib.dumps(plist, sort_keys=True).decode("utf-8")


def agent_needs_update(existing_text, expected_text):
    """설치된 에이전트가 원하는 것과 다른가. 없으면 당연히 다르다."""
    if existing_text is None:
        return True
    try:
        return (plistlib.loads(existing_text.encode("utf-8"))
                != plistlib.loads(expected_text.encode("utf-8")))
    except Exception:
        return existing_text.strip() != expected_text.strip()


def agent_plist_path():
    return os.path.expanduser(f"~/Library/LaunchAgents/{AGENT_LABEL}.plist")


def install_launch_agent(script, log, interval=DEFAULT_INTERVAL, dry_run=False):
    """launchd 에이전트를 설치하거나 경로를 교정한다. Label 고정이라 중복되지 않는다."""
    path = agent_plist_path()
    expected = build_launchd_plist(script, log, interval)
    existing = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            existing = fh.read()

    if not agent_needs_update(existing, expected):
        return "unchanged"
    if dry_run:
        return "would-install" if existing is None else "would-update"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    if existing is not None:
        with open(path + ".bak", "w", encoding="utf-8") as fh:
            fh.write(existing)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(expected)

    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, path],
                   capture_output=True, check=False)
    loaded = subprocess.run(["launchctl", "bootstrap", domain, path],
                            capture_output=True, check=False)
    if loaded.returncode != 0:
        subprocess.run(["launchctl", "load", path], capture_output=True, check=False)
    return "installed" if existing is None else "updated"


# ── CLI ──────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="직원 머신을 토큰 사용량 수집에 등록")
    ap.add_argument("--token", help="zestim에서 발급받은 개인 토큰")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--shared-secret",
                    help="스냅샷 동기화용 프로젝트 공유 secret (새 머신 최초 설정 시에만)")
    ap.add_argument("--machine", help="이 머신의 라벨 (기본: hostname)")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                    help="수집 주기(초). 기본 10800(3시간)")
    ap.add_argument("--runs-schema", type=int,
                    help="중앙이 일자별 스키마를 받을 준비가 된 뒤에만 2 로 켠다")
    ap.add_argument("--repair", action="store_true",
                    help="토큰 변경 없이 에이전트 경로만 교정")
    ap.add_argument("--dry-run", action="store_true", help="변경 없이 계획만 출력")
    a = ap.parse_args(argv)

    if not a.repair and not a.token:
        ap.error("--token 이 필요하다 (또는 --repair)")

    print(f"skill dir : {SKILL_DIR}")

    # 1) 프로젝트 레지스트리
    if a.dry_run:
        print(f"projects  : {'있음' if os.path.exists(PROJECTS_CONFIG) else '없음 → 생성 예정'}")
    else:
        print(f"projects  : {bootstrap_projects(PROJECTS_CONFIG)}")

    # 2) sync.json
    if a.repair and not a.token:
        print("sync.json : 유지 (--repair)")
    else:
        try:
            existing = read_json(SYNC_CONFIG) or {}
        except Exception as exc:
            raise SystemExit(f"sync.json 파싱 실패 — 덮어쓰지 않고 중단: {exc}") from exc
        cfg = merge_sync_config(existing, a.token, a.endpoint,
                                machine=a.machine, runs_schema=a.runs_schema,
                                shared_secret=a.shared_secret)
        if a.dry_run:
            preview = dict(cfg)
            for masked in ("secret", "runs_token"):
                if masked in preview:
                    preview[masked] = "***"
            print(f"sync.json : 예정 → {json.dumps(preview, ensure_ascii=False)}")
        else:
            write_sync_config(SYNC_CONFIG, cfg)
            print(f"sync.json : 기록 (0600) — machine={cfg.get('machine') or 'hostname'}")

    # 3) 수집 에이전트
    script = resolve_script_path()
    if not os.path.isfile(script):
        raise SystemExit(f"reconcile_runs.py 를 찾지 못했다: {script}")
    if sys.platform != "darwin":
        print(f"agent     : {sys.platform} 는 자동 등록 미지원 — "
              f"cron 등으로 `{sys.executable} {script} --all --push` 를 "
              f"{a.interval}초 간격 실행")
    else:
        result = install_launch_agent(script, RECONCILE_LOG, a.interval, dry_run=a.dry_run)
        print(f"agent     : {result} → {script}")

    print("\n확인:  python3 %s --all --dry-run" % script)
    return 0


if __name__ == "__main__":
    sys.exit(main())
