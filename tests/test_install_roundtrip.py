"""설치 전과 제거 후의 HOME 이 같아지는가 — **깨끗한 HOME 에서 실제로 밟는다.**

`tests/test_setup_skills.py` 가 보는 것은 **파일 복사**다. 그 아래 배선 함수들은
한 줄도 안 돌렸다: `install_hooks` · `uninstall_hooks` · `install_launchd` ·
`uninstall_launchd` · `migrate_projects_json`.

그런데 이 레포가 겪은 설치·배선 사고는 셋이고 **전부 그 자리다**:

1. rename 잔재로 plist 가 없는 경로를 가리켜 **토큰 수집이 4일 정지**(28회 연속 실패)
2. 구 `com.vibekanban.server` plist 가 5월부터 **크래시 루프**, 로그 104MB
3. plist 를 문자열 템플릿으로 조립 — 경로에 `&` 하나면 XML 이 깨지고 **launchd 는 침묵**

셋 다 조용했고, 셋 다 사람이 우연히 발견했다.

## 성질 하나로 고정한다

함수를 하나씩 단언하는 대신 **왕복**을 본다 — 설치했다가 제거하면 HOME 이 원래대로
돌아온다. 훅이 하나 늘어도 검사가 따라오고, "지우는 것을 깜빡한 파일"이 자동으로 잡힌다.

## 실제 머신은 건드리지 않는다

`setup.py` 는 경로를 전부 import 시점에 `expanduser("~")` 로 계산한다. 그래서
**`HOME` 을 임시 디렉토리로 바꿔 다시 import** 한다 — 상수를 하나씩 몽키패치하면
`HOOKS` 안에 박힌 경로가 남아 실제 `~/.claude/hooks/` 를 가리킨다.

`launchctl` 은 **부르지 않는다.** 부르면 이 머신의 실제 수집 잡을 건드린다
(PMF11 에서 `install_reconcile.py` 를 검사할 때 정한 규칙과 같다). 대신 `subprocess` 를
기록기로 갈아끼워 **무엇을 부르려 했는지 단언한다.**

## 여기서 확인하지 못하는 것

`install_launchd` 의 plist 경로는 **darwin 에서만** 돈다. CI 는 ubuntu 라
**그 경로를 CI 가 한 번도 밟지 않는다** — 사고 3건 중 2건이 났던 자리가 그쪽이다.
그 사실을 이 파일 안에 적어두고, plist 단언은 이 머신에서만 실행된다.
"""
import contextlib
import hashlib
import io
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

_LOADS = [0]


class FakeSubprocess:
    """`launchctl` 을 실제로 부르지 않는다. 무엇을 부르려 했는지는 남긴다."""

    def __init__(self):
        self.calls = []

    def run(self, argv, **_kwargs):
        self.calls.append(list(argv))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()


def load_setup(home):
    """`HOME` 이 임시 디렉토리인 상태로 `setup.py` 를 새로 import 한다."""
    _LOADS[0] += 1
    name = "setup_roundtrip_%d" % _LOADS[0]
    saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    try:
        spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, "setup.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    mod.subprocess = FakeSubprocess()

    # **이 파일의 안전장치.** 아래를 통과하지 못하면 모듈을 넘겨주지 않는다.
    #
    # 처음에는 이것을 테스트(`test_the_temp_home_is_actually_used`)로만 뒀다.
    # 그런데 위반을 주입해보니 — HOME 패치를 지웠더니 — 그 테스트는 실패를 **보고**
    # 했지만 같은 파일의 다른 테스트들은 그대로 돌아 **실제 `~/.claude` 를 설치하고
    # 제거했다.** 훅 7개와 스킬 3개가 사라지고 plist 가 지워졌다(복구했다).
    #
    # 보고하는 것과 막는 것은 다르다. 이 레포는 보통 "감지는 만들되 막지 않는다"를
    # 따르지만 그 규칙은 **오탐이 작업을 멈추는 것**을 걱정한 것이고, 여기서 오판의
    # 대가는 사용자 머신의 설치본이다. 그래서 여기서는 막는다.
    for const in ("DEST", "HOOKS_DIR", "SETTINGS_PATH", "SKILLS_ROOT", "LAUNCH_AGENTS"):
        path = getattr(mod, const)
        if not path.startswith(home):
            sys.modules.pop(name, None)
            raise RuntimeError(
                "setup.%s 가 임시 HOME 밖을 가리킨다 (%s) — 실제 머신을 건드리기 전에 멈춘다"
                % (const, path))
    return mod, name


def snapshot(root):
    """상대경로 → 내용 해시. 내용까지 봐야 '되돌렸다'를 말할 수 있다."""
    out = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            try:
                with open(path, "rb") as fh:
                    out[rel] = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                out[rel] = "unreadable"
    return out


class InstallRoundTripTest(unittest.TestCase):
    """설치 → 제거 후 HOME 이 원래대로 돌아오는가."""

    # 제거해도 남는 것. **의도된 것이고, 목록을 손으로 적지 않는다** —
    # `~/.claude/skills/vibe-harness/` 는 `projects.json` 과 서버 로그가 함께 살아서
    # 통째로 남긴다(`REMOVABLE_SKILLS` 에 없다). 그 디렉토리 아래가 아닌 잔재가
    # 하나라도 있으면 실패해야 한다.
    RETAINED_PREFIX = os.path.join(".claude", "skills", "vibe-harness")

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="vh-roundtrip-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.claude = os.path.join(self.home, ".claude")
        os.makedirs(self.claude)
        # 사용자가 이미 갖고 있던 설정 — 남의 훅과 무관한 키가 살아남아야 한다
        self.settings_path = os.path.join(self.claude, "settings.json")
        self.original_settings = {
            "model": "opus",
            "permissions": {"allow": ["Bash(ls:*)"]},
            "hooks": {"PreToolUse": [{"matcher": "Edit", "_id": "someone-elses-tool",
                                      "hooks": [{"type": "command", "command": "/bin/true"}]}]},
        }
        with open(self.settings_path, "w", encoding="utf-8") as fh:
            json.dump(self.original_settings, fh, indent=2)
        self.mod, self.mod_name = load_setup(self.home)
        self.addCleanup(sys.modules.pop, self.mod_name, None)

    def install(self):
        """`main()` 이 하는 네 단계. 순서까지 같게.

        설치기의 표준출력은 삼킨다 — 스위트 출력이 읽을 수 없게 되면 실패도 눈에 안 띈다.
        """
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.copy_server_files()
            self.mod.migrate_projects_json()
            self.mod.install_launchd()
            self.mod.install_hooks()

    def uninstall(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.uninstall_launchd()
            self.mod.uninstall_hooks()
            self.mod.remove_added_skills()

    def test_the_temp_home_is_actually_used(self):
        """성질을 문서로 남긴다. **실제 방어는 `load_setup()` 안에 있다** —
        보고만 하면 같은 파일의 다른 테스트가 그대로 실제 HOME 을 건드린다(경험).
        """
        for path in (self.mod.DEST, self.mod.HOOKS_DIR, self.mod.SETTINGS_PATH,
                     self.mod.SKILLS_ROOT, self.mod.LAUNCH_AGENTS):
            self.assertTrue(path.startswith(self.home),
                            "임시 HOME 밖을 가리킨다: %s" % path)

    def test_uninstall_restores_home(self):
        before = snapshot(self.home)
        self.install()
        after_install = snapshot(self.home)
        self.assertGreater(len(after_install), len(before) + 15,
                           "설치가 거의 아무것도 하지 않았다 — 왕복 검사가 무의미해진다")
        self.uninstall()
        after = snapshot(self.home)

        leftover = sorted(set(after) - set(before))
        stray = [f for f in leftover if not f.startswith(self.RETAINED_PREFIX)]
        self.assertEqual(
            [], stray,
            "제거 후에도 남은 파일: " + ", ".join(stray)
            + " — 지우는 것을 깜빡한 자리다")

    def test_files_that_existed_are_not_modified(self):
        """남의 파일을 고쳐놓고 제거하면 되돌릴 수 없다."""
        before = snapshot(self.home)
        self.install()
        self.uninstall()
        after = snapshot(self.home)
        changed = sorted(f for f in set(before) & set(after) if before[f] != after[f])
        self.assertEqual([], changed,
                         "원래 있던 파일의 내용이 바뀐 채로 남았다: " + ", ".join(changed))

    def test_unrelated_settings_survive(self):
        """`settings.json` 은 **공유 파일이다.** 다른 도구도 여기에 훅을 쓴다.

        설치가 이 파일을 통째로 다시 쓰므로, 남의 항목을 지우면 그 도구가 조용히
        멈춘다 — 그리고 원인을 우리에게서 찾을 사람은 없다.
        """
        self.install()
        with open(self.settings_path, encoding="utf-8") as fh:
            mid = json.load(fh)
        ids = [h.get("_id") for h in mid["hooks"]["PreToolUse"]]
        self.assertIn("someone-elses-tool", ids, "설치가 남의 훅을 지웠다")
        self.assertEqual("opus", mid.get("model"), "설치가 무관한 설정을 지웠다")

        self.uninstall()
        with open(self.settings_path, encoding="utf-8") as fh:
            end = json.load(fh)
        self.assertEqual(self.original_settings, end,
                         "제거 후 settings.json 이 원래와 다르다")

    def test_every_hook_is_registered_and_removed(self):
        self.install()
        with open(self.settings_path, encoding="utf-8") as fh:
            registered = json.load(fh)["hooks"]
        seen = {h.get("_id") for entries in registered.values() for h in entries}
        missing = sorted(self.mod.HOOK_IDS - seen)
        self.assertEqual([], missing, "등록되지 않은 훅: " + ", ".join(missing))

        self.uninstall()
        with open(self.settings_path, encoding="utf-8") as fh:
            left = json.load(fh).get("hooks", {})
        still = sorted({h.get("_id") for entries in left.values() for h in entries}
                       & self.mod.HOOK_IDS)
        self.assertEqual([], still, "제거 후에도 남은 훅 등록: " + ", ".join(still))

    def test_hook_scripts_land_executable(self):
        """실행 권한이 없는 훅은 **조용히 안 돈다.** 설치는 성공한 것처럼 보인다."""
        self.install()
        for script_name, _event, _entry in self.mod.HOOKS:
            path = os.path.join(self.mod.HOOKS_DIR, script_name)
            self.assertTrue(os.path.exists(path), "훅 스크립트가 설치되지 않았다: " + script_name)
            self.assertTrue(os.access(path, os.X_OK), "실행 권한이 없다: " + script_name)
        for helper in self.mod.HOOK_HELPERS:
            path = os.path.join(self.mod.HOOKS_DIR, helper)
            self.assertTrue(os.access(path, os.X_OK), "실행 권한이 없다: " + helper)

    def test_installing_twice_does_not_duplicate(self):
        """훅을 중복 등록한 이력이 있다. 두 번 등록되면 같은 훅이 두 번 돈다."""
        self.install()
        self.install()
        with open(self.settings_path, encoding="utf-8") as fh:
            registered = json.load(fh)["hooks"]
        for event, entries in registered.items():
            ids = [h.get("_id") for h in entries if h.get("_id") in self.mod.HOOK_IDS]
            self.assertEqual(len(ids), len(set(ids)),
                             "%s 에 같은 훅이 두 번 등록됐다: %s" % (event, ids))

    def test_uninstall_without_install_is_harmless(self):
        """설치하지 않은 상태에서 제거를 부르는 것은 흔하다. 터지면 안 된다."""
        before = snapshot(self.home)
        self.uninstall()
        self.assertEqual(before, snapshot(self.home), "제거가 아무것도 안 바꿔야 한다")

    def test_launchctl_is_never_really_called(self):
        """이 파일이 실제 launchd 를 건드리지 않는다는 것 자체를 검사한다."""
        self.install()
        self.uninstall()
        self.assertIsInstance(self.mod.subprocess, FakeSubprocess,
                              "subprocess 가 진짜다 — 이 머신의 수집 잡을 건드린다")
        for call in self.mod.subprocess.calls:
            if call and call[0] == "launchctl":
                self.assertTrue(call[-1].startswith(self.home),
                                "임시 HOME 밖의 plist 를 건드리려 했다: %s" % call)

    @unittest.skipUnless(sys.platform == "darwin", "launchd 는 macOS 전용 — CI(ubuntu)는 못 본다")
    def test_plist_is_written_and_removed(self):
        """**CI 가 밟지 않는 경로다.** 사고 3건 중 2건이 여기서 났다."""
        plist = os.path.join(self.mod.LAUNCH_AGENTS, self.mod.PLIST_NAME)
        self.install()
        self.assertTrue(os.path.exists(plist), "plist 가 설치되지 않았다")
        with open(plist, encoding="utf-8") as fh:
            content = fh.read()
        self.assertNotIn("__HOME__", content, "plist 템플릿의 __HOME__ 이 치환되지 않았다")
        self.assertIn(self.home, content, "plist 가 이 HOME 을 가리키지 않는다")

        loads = [c for c in self.mod.subprocess.calls if c[:2] == ["launchctl", "load"]]
        self.assertTrue(loads, "설치가 launchctl load 를 부르지 않았다 — 등록만 하고 켜지 않는다")

        self.uninstall()
        self.assertFalse(os.path.exists(plist), "제거 후에도 plist 가 남았다")
        unloads = [c for c in self.mod.subprocess.calls if c[:2] == ["launchctl", "unload"]]
        self.assertTrue(unloads, "제거가 launchctl unload 를 부르지 않았다 — "
                                 "파일만 지우면 잡은 살아 있고 다음 로그인까지 조용히 실패한다")


class MigrateProjectsTest(unittest.TestCase):
    """`migrate_projects_json` — 지금까지 한 번도 실행되지 않은 함수.

    옛 형식(`db_path`)은 SQLite 시절의 것이다. 마이그레이션이 조용히 안 돌면 등록이
    전부 무효가 되고, 서버는 프로젝트를 하나도 못 찾는다.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="vh-migrate-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.mod, self.mod_name = load_setup(self.home)
        self.addCleanup(sys.modules.pop, self.mod_name, None)
        os.makedirs(self.mod.DEST, exist_ok=True)
        self.config = os.path.join(self.mod.DEST, "projects.json")

    def write(self, data):
        with open(self.config, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def read(self):
        with open(self.config, encoding="utf-8") as fh:
            return json.load(fh)

    def test_db_path_becomes_kanban_dir(self):
        self.write({"proj": {"name": "P", "db_path": "/x/y/vibe-harness/kanban.db"}})
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.migrate_projects_json()
        info = self.read()["proj"]
        self.assertEqual("/x/y/vibe-harness", info["kanban_dir"])
        self.assertNotIn("db_path", info, "옛 필드가 남으면 어느 쪽이 정본인지 알 수 없다")

    def test_already_migrated_is_left_alone(self):
        data = {"proj": {"name": "P", "kanban_dir": "/x/y/vibe-harness"}}
        self.write(data)
        self.mod.migrate_projects_json()
        self.assertEqual(data, self.read())

    def test_both_fields_keeps_kanban_dir(self):
        """둘 다 있으면 새 필드가 정본이다. 덮어쓰면 등록이 옛 경로로 돌아간다."""
        self.write({"proj": {"kanban_dir": "/new/vibe-harness",
                             "db_path": "/old/vibe-harness/kanban.db"}})
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.migrate_projects_json()
        self.assertEqual("/new/vibe-harness", self.read()["proj"]["kanban_dir"])

    def test_missing_file_is_not_an_error(self):
        """설치 직후엔 파일이 없다. 여기서 터지면 설치가 3단계에서 멈춘다."""
        self.assertFalse(os.path.exists(self.config))
        self.mod.migrate_projects_json()


if __name__ == "__main__":
    unittest.main()
