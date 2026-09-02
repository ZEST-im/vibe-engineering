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
import re
import shutil
import subprocess
import sys

# Windows cp949 콘솔에서 '—' 같은 문자가 크래시를 낸다. 사용자가 PYTHONUTF8=1 을 손으로
# 붙여야 돌아가던 문제라 스크립트가 직접 보장한다. reconfigure 가 없으면 no-op.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

SKILL_DIR = os.path.expanduser("~/.claude/skills/vibe-harness")
SYNC_CONFIG = os.path.join(SKILL_DIR, "sync.json")
PROJECTS_CONFIG = os.path.join(SKILL_DIR, "projects.json")
RECONCILE_LOG = os.path.join(SKILL_DIR, "reconcile.log")

AGENT_LABEL = "com.vibe-harness.reconcile"
WINDOWS_TASK_NAME = "VibeHarnessReconcile"
DEFAULT_INTERVAL = 10800          # 3시간
DEFAULT_ENDPOINT = "https://os.zest.im/api/internal/vibe-harness/sync"


# ── 설정 ─────────────────────────────────────────────

ID_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,7}$")


def merge_sync_config(existing, token, endpoint, machine=None, runs_schema=None,
                     shared_secret=None, id_prefix=None):
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
    if id_prefix is not None:
        prefix = str(id_prefix).strip()
        if prefix:
            # 숫자로 시작하거나 공백·구분자가 섞이면 정수 id 와 구분되지 않는다.
            if not ID_PREFIX_RE.match(prefix):
                raise ValueError(
                    "id_prefix 는 영문으로 시작하는 영숫자 1~8자다: %r" % prefix)
            cfg["id_prefix"] = prefix
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


def derive_project_key(repo_path):
    """프로젝트 키를 `git remote get-url origin` 의 리포 이름에서 뽑는다.

    **왜 디렉토리명이 아닌가.** 키는 중앙에서 프로젝트를 식별하는 값인데, 로컬
    디렉토리명은 사람과 머신마다 다르다. 같은 리포가 mac-studio 에서는 `pante`,
    macbook 에서는 `pante_bde` 로 등록돼 있었다. 중앙의 중복 제거는 프로젝트 **안에서만**
    돌고 인별 합계는 프로젝트를 가로질러 더하므로, 두 키에 같은 행이 있으면 그대로
    이중 계상된다. 2026-08-29 에 4쌍을 통합해 46.9억 토큰 / $8,476 을 걷어냈다.

    중앙만 고치면 다음 push 때 stale 키가 되살아난다. 키를 만드는 쪽이 여기다.

    remote 가 없으면(로컬 전용 리포, 초기화 직후) 디렉토리명으로 떨어진다.
    워크트리는 같은 remote 를 공유하므로 같은 키가 나온다 — 의도한 것이다.
    같은 리포의 워크트리는 같은 프로젝트다.
    """
    repo = os.path.abspath(os.path.expanduser(str(repo_path or "")))
    try:
        out = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5)
        url = out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        url = ""
    if url:
        tail = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        name = re.sub(r"\.git$", "", tail).strip()
        if name:
            return name
    return os.path.basename(repo.rstrip(os.sep)) or None


def audit_project_keys(registry):
    """등록된 키와 remote 에서 뽑은 키가 어긋난 곳.

    **자동으로 바꾸지 않는다.** 키를 바꾸면 중앙의 이력이 그 지점에서 끊기고, 되돌릴
    방법이 없다. 알리기만 하고 판단은 사람에게 남긴다.
    """
    drift = []
    for key, meta in sorted((registry or {}).items()):
        kdir = meta.get("kanban_dir") if isinstance(meta, dict) else meta
        if not kdir:
            continue
        derived = derive_project_key(os.path.dirname(os.path.abspath(kdir)))
        if derived and derived != key:
            drift.append({"key": key, "derived": derived, "kanban_dir": kdir})
    return drift


def parse_project_arg(pair):
    """'<키>=<리포경로>' 를 쪼갠다."""
    text = str(pair or "").strip()
    if not text:
        raise ValueError("형식은 <리포경로> 또는 <키>=<리포경로> 다")
    if "=" not in text:
        # 키를 생략하면 remote 에서 뽑는다. 손으로 정하면 머신마다 갈라진다.
        derived = derive_project_key(text)
        if not derived:
            raise ValueError(f"키를 뽑지 못했다 — <키>=<리포경로> 로 지정한다: {text}")
        return derived, text
    key, path = text.split("=", 1)
    return key.strip(), path.strip()


def add_project(registry_path, key, repo_path):
    """수집 대상 프로젝트를 등록한다.

    수집은 projects.json 에 등록된 프로젝트만 훑는다. 손으로 JSON 을 고치게 하면
    빠뜨리고, 빠뜨리면 조용히 0건이 된다. 키는 대시보드가 참조하는 공유 프로젝트 키를
    그대로 쓴다 — 머신마다 리포 경로는 달라도 키는 같아야 한 프로젝트로 합쳐진다.
    """
    key = str(key or "").strip()
    if not key:
        raise ValueError("프로젝트 키가 비어 있다")
    repo = os.path.abspath(os.path.expanduser(str(repo_path or "").strip()))
    if not os.path.isdir(repo):
        raise ValueError(f"리포 경로가 없다: {repo}")

    try:
        data = read_json(registry_path) or {}
    except Exception as exc:
        raise SystemExit(f"projects.json 파싱 실패 — 덮어쓰지 않고 중단: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("projects.json 최상위가 object 가 아니다")

    kdir = os.path.join(repo, "vibe-harness")
    existing = data.get(key)
    if isinstance(existing, dict):
        prev = os.path.abspath(existing.get("kanban_dir") or "")
        if prev and prev != os.path.abspath(kdir):
            # 같은 키가 다른 디렉토리를 가리키고 있다. 조용히 덮으면 앞의 프로젝트가
            # 수집에서 사라진다 — 워크트리는 remote 가 같아 같은 키가 나오므로
            # 실제로 일어나는 일이다.
            raise SystemExit(
                f"키 '{key}' 가 이미 다른 경로에 등록돼 있다.\n"
                f"  기존: {prev}\n  요청: {os.path.abspath(kdir)}\n"
                "  같은 리포의 워크트리라면 등록하지 않는다 — 본체 하나면 충분하다.\n"
                "  정말 옮기려면 projects.json 에서 기존 항목을 먼저 지운다.")
    # JSON 에는 항상 "/" 로 적는다. Windows 의 os.path.join 은 역슬래시를 주는데,
    # 그대로 넣으면 JSON 이스케이프가 필요해지고 같은 파일 안에서 머신마다 표기가
    # 갈린다. 읽는 쪽은 전부 os.path.abspath 를 거치므로 "/" 로 적어도 Windows 에서
    # 그대로 동작한다.
    data[key] = {"name": key, "kanban_dir": kdir.replace(os.sep, "/")}
    parent = os.path.dirname(registry_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = registry_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, registry_path)
    return data[key]


# ── 스킬 설치본 갱신 ────────────────────────────────
# 서버는 레포가 아니라 설치본에서 돈다. `git pull` 만으로는 서버가 바뀌지 않는다.
#
# 설치 디렉토리에는 코드와 머신 로컬 상태가 같이 있다 — sync.json(개인 토큰),
# projects.json(수집 대상), users.json(실명 별칭), push-state.json(전송 이력). 통째로
# 덮으면 그게 날아간다. 그래서 복사는 화이트리스트다. 새 파일이 생기면 여기에 명시적으로
# 추가해야 하고, 모르는 파일은 건드리지 않는다.
#
# setup.py 는 넣지 않는다. 훅을 중복 등록한 이력이 있어 잠긴 파일이고, 설치본에 최신을
# 두면 누군가 그걸 실행하게 된다.
SKILL_CODE_FILES = (
    ("scripts/server.py", "server.py"),
    ("scripts/kanban.html", "kanban.html"),
    ("scripts/worker.py", "worker.py"),
    ("scripts/vibe_runtime.py", "vibe_runtime.py"),
    ("scripts/reconcile_runs.py", "reconcile_runs.py"),
    ("scripts/kanban_edit.py", "kanban_edit.py"),
    ("scripts/enroll.py", "enroll.py"),
    ("skills/vibe-harness/SKILL.md", "SKILL.md"),
)


def skill_install_plan(repo_root, dest=SKILL_DIR):
    """(원본, 대상) 목록. 존재하는 것만 담는다."""
    plan = []
    for rel, name in SKILL_CODE_FILES:
        src = os.path.join(repo_root, rel)
        if os.path.exists(src):
            plan.append((src, os.path.join(dest, name)))
    return plan


def install_skill_files(repo_root, dest=SKILL_DIR):
    """레포의 코드를 설치본으로 반영한다. 머신 로컬 파일은 목록에 없으므로 보존된다."""
    os.makedirs(dest, exist_ok=True)
    copied = []
    for src, target in skill_install_plan(repo_root, dest):
        shutil.copy2(src, target)
        copied.append(target)
    return copied


def repo_root_of_this_script():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def build_schtasks_argv(script, python=None, interval=DEFAULT_INTERVAL,
                        task_name=WINDOWS_TASK_NAME):
    r"""Windows 작업 스케줄러 등록 명령.

    /F 로 같은 이름을 덮어쓴다 — launchd 의 고정 Label 과 같은 규율이라 재실행해도
    작업이 두 개가 되지 않는다. 경로에 공백이 흔하므로(C:\Program Files\...) /TR 안의
    실행 문자열은 각 경로를 따옴표로 감싼다.
    """
    py = python or default_agent_python()
    seconds = max(60, int(interval))
    if seconds % 3600 == 0:
        schedule, modifier = "HOURLY", seconds // 3600
    else:
        schedule, modifier = "MINUTE", max(1, seconds // 60)
    run = '"%s" "%s" --all --push' % (py, script)
    return ["schtasks", "/Create", "/F",
            "/SC", schedule, "/MO", str(modifier),
            "/TN", task_name, "/TR", run]


def install_windows_task(script, interval=DEFAULT_INTERVAL, dry_run=False):
    """작업 스케줄러에 수집 작업을 등록한다."""
    argv = build_schtasks_argv(script, interval=interval)
    if dry_run:
        return "would-install"
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip()[-300:]
        return f"실패 — 직접 등록이 필요하다: {' '.join(argv)}\n            {detail}"
    return "installed"


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
    ap.add_argument("--add-project", action="append", metavar="키=리포경로",
                    help="수집 대상 프로젝트 등록 (여러 번 지정 가능)")
    ap.add_argument("--id-prefix", metavar="접두어",
                    help="칸반 태스크 ID 접두어 (중앙이 배정한 값). 사람마다 달라야 한다")
    ap.add_argument("--update-skill", action="store_true",
                    help="레포의 코드를 설치본으로 반영 (서버는 설치본에서 돈다)")
    ap.add_argument("--repair", action="store_true",
                    help="토큰 변경 없이 에이전트 경로만 교정")
    ap.add_argument("--check-keys", action="store_true",
                    help="등록된 키와 git remote 에서 뽑은 키가 어긋난 곳을 보고한다 "
                         "(바꾸지는 않는다 — 키는 되돌릴 수 없다)")
    ap.add_argument("--dry-run", action="store_true", help="변경 없이 계획만 출력")
    a = ap.parse_args(argv)

    if a.check_keys:
        try:
            registry = read_json(PROJECTS_CONFIG) or {}
        except Exception as exc:
            raise SystemExit(f"projects.json 파싱 실패: {exc}") from exc
        drift = audit_project_keys(registry)
        if not drift:
            print("키 드리프트 없음 — 등록 %d개 전부 remote 와 일치" % len(registry))
            return 0
        print("키 드리프트 %d건 — 머신마다 다른 키로 보내면 인별 합계가 이중 계상된다:"
              % len(drift))
        for row in drift:
            print(f"  등록 '{row['key']}'  vs  remote '{row['derived']}'")
            print(f"    {row['kanban_dir']}")
        print("\n자동으로 바꾸지 않는다 — 키를 바꾸면 중앙 이력이 끊기고 되돌릴 수 없다.")
        print("통합하려면 중앙에서 두 키의 run 을 합친 뒤 여기 등록을 정리한다.")
        return 1

    if not a.repair and not a.token and not a.add_project and not a.update_skill:
        ap.error("--token 이 필요하다 (또는 --repair / --add-project / "
                 "--update-skill / --check-keys)")

    # 코드 반영은 다른 단계와 독립이다. 서버가 최신이어야 나머지가 의미를 갖는다.
    if a.update_skill:
        if a.dry_run:
            plan = skill_install_plan(repo_root_of_this_script())
            print("skill     : %d개 파일 반영 예정" % len(plan))
            for _src, dest in plan:
                print("            %s" % os.path.basename(dest))
        else:
            copied = install_skill_files(repo_root_of_this_script())
            print("skill     : %d개 파일 반영 → %s" % (len(copied), SKILL_DIR))
            print("            머신 로컬(sync.json·projects.json·users.json)은 보존됐다")

    if a.update_skill and not a.token and not a.repair and not a.add_project:
        print("\n확인:  python3 %s --all --dry-run" % resolve_script_path())
        return 0

    # 프로젝트 등록만 하는 경우 — 토큰 없이도 쓸 수 있다
    if a.add_project and not a.token and not a.repair:
        for pair in a.add_project:
            key, repo = parse_project_arg(pair)
            info = add_project(PROJECTS_CONFIG, key, repo)
            print(f"projects  : {key} → {info['kanban_dir']}")
        print("\n확인:  python3 %s --all --dry-run" % resolve_script_path())
        return 0

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
                                shared_secret=a.shared_secret, id_prefix=a.id_prefix)
        if a.dry_run:
            preview = dict(cfg)
            for masked in ("secret", "runs_token"):
                if masked in preview:
                    preview[masked] = "***"
            print(f"sync.json : 예정 → {json.dumps(preview, ensure_ascii=False)}")
        else:
            write_sync_config(SYNC_CONFIG, cfg)
            print(f"sync.json : 기록 (0600) — machine={cfg.get('machine') or 'hostname'}"
                  f", id_prefix={cfg.get('id_prefix') or '(없음 → 정수 발급)'}")

    # 2.5) 프로젝트 등록
    for pair in (a.add_project or []):
        key, repo = parse_project_arg(pair)
        info = add_project(PROJECTS_CONFIG, key, repo)
        print(f"projects  : {key} → {info['kanban_dir']}")

    # 3) 수집 에이전트
    script = resolve_script_path()
    if not os.path.isfile(script):
        raise SystemExit(f"reconcile_runs.py 를 찾지 못했다: {script}")
    if sys.platform == "darwin":
        result = install_launch_agent(script, RECONCILE_LOG, a.interval, dry_run=a.dry_run)
    elif os.name == "nt":
        result = install_windows_task(script, a.interval, dry_run=a.dry_run)
    else:
        result = (f"{sys.platform} 는 자동 등록 미지원 — "
                  f"`{sys.executable} {script} --all --push` 를 "
                  f"{a.interval}초 간격으로 직접 걸어야 한다")
    print(f"agent     : {result} → {script}")

    if os.name == "nt":
        print("주의      : Windows 는 POSIX 권한이 적용되지 않아 sync.json 이 0600 으로"
              " 보호되지 않는다. 토큰이 든 파일이니 계정 밖에 노출되지 않게 둔다.")

    print("\n확인:  python3 %s --all --dry-run" % script)
    return 0


if __name__ == "__main__":
    sys.exit(main())
