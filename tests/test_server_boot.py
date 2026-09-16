"""서버를 **프로세스로 띄운다** — 시작이 실제로 되는가.

## 왜 함수 검사로는 부족했는가

`init_registered_projects()` 에는 검사가 셋 있었다(`test_http_routes.py`). 셋 다
통과했다. 그런데 그 함수를 **부르는 자리**인 `main()` 은 아무도 밟지 않았고,
거기서 서버가 시작마다 죽고 있었다.

    UnboundLocalError: local variable 'projects' referenced before assignment

시작 루프를 함수로 꺼내면서 `projects = load_projects()` 가 같이 사라졌는데,
바로 아래 배너 줄이 아직 `projects` 를 쓰고 있었다. `serve` 모드에서는 그 이름이
**한 번도 대입되지 않는다.**

추출한 함수는 검사했고 호출부는 검사하지 않았다. 그래서 커버리지는 올라갔고
서버는 뜨지 않았다.

## 왜 아무도 몰랐는가

이미 떠 있던 프로세스가 옛 코드로 계속 돌고 있었다. 새 코드는 **재시작하는
순간에만** 실행된다 — 로그인, 배포, 설치 직후. 테스트도 CI 도 서버를 띄운 적이
없으니, 이 고장은 사람이 재시작할 때까지 기다렸다가 난다.

이 저장소의 표현으로 **CI 가 안 보는 자리**가 하나 더 있었다. `launchd`/설치 경로와
같은 계열이다.

## 규칙

**시작은 밖에서 확인한다.** 내부 함수를 부르는 것으로는 시작을 확인한 것이 아니다.
프로세스로 띄우고, 살아 있는지, 대답하는지 본다.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "scripts", "server.py")

BOOT_TIMEOUT = 20.0
REAPER_PERIOD = 5.0   # server._runtime_reaper 의 주기


def _free_port():
    """포트를 잡았다 놓아 번호만 얻는다. 병렬 실행에서 고정 포트는 충돌한다."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerBootTest(unittest.TestCase):
    """`server.py serve` 가 뜨고, 대답하고, 지운 것을 되살리지 않는가."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vh-boot-")
        self.addCleanup(self._rmtree, self.tmp)

        # **임시 HOME.** 실제 `~/.claude/` 를 건드리지 않는다 — 이 저장소의 규약이다.
        self.home = os.path.join(self.tmp, "home")
        skill_dir = os.path.join(self.home, ".claude", "skills", "vibe-harness")
        os.makedirs(skill_dir)

        # 살아 있는 등록 하나, 죽은 등록 하나. 시작이 죽은 쪽을 되살리면 안 된다.
        self.live = os.path.join(self.home, "live", "vibe-harness")
        os.makedirs(self.live)
        self.dead = os.path.join(self.home, "gone", "vibe-harness")
        os.makedirs(os.path.dirname(self.dead))  # 부모만 만든다 — 되살리기의 조건

        with open(os.path.join(skill_dir, "projects.json"), "w", encoding="utf-8") as f:
            json.dump({
                "live": {"name": "live", "kanban_dir": self.live},
                "gone": {"name": "gone", "kanban_dir": self.dead},
            }, f)

        self.port = _free_port()
        self.log = os.path.join(self.tmp, "server.log")

    def _rmtree(self, path):
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    def _boot(self):
        """서버를 띄우고 응답할 때까지 기다린다. 못 뜨면 **로그를 함께** 실패시킨다."""
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home          # Windows 의 `~`
        # 원격 동기화는 이 검사의 대상이 아니다. 임시 HOME 안의 없는 파일로 못 박는다.
        env["VIBE_HARNESS_SYNC_CONFIG"] = os.path.join(self.tmp, "no-sync.json")

        out = open(self.log, "w", encoding="utf-8")
        self.addCleanup(out.close)
        proc = subprocess.Popen(
            [sys.executable, SERVER, "serve", str(self.port)],
            stdout=out, stderr=subprocess.STDOUT, env=env, cwd=self.tmp,
        )
        self.addCleanup(self._stop, proc)

        url = f"http://127.0.0.1:{self.port}/api/projects"
        deadline = time.time() + BOOT_TIMEOUT
        last = None
        while time.time() < deadline:
            if proc.poll() is not None:
                self.fail(
                    "서버가 시작하다 죽었다 (exit %s) — 시작 경로가 실행되지 않는다.\n"
                    "--- server 출력 ---\n%s" % (proc.returncode, self._log())
                )
            try:
                with urllib.request.urlopen(url, timeout=1) as r:
                    return proc, r.status, r.read()
            except (urllib.error.URLError, ConnectionError, OSError) as exc:
                last = exc
                time.sleep(0.1)

        self.fail("서버가 %.0f초 안에 대답하지 않았다 (마지막 오류 %r)\n"
                  "--- server 출력 ---\n%s" % (BOOT_TIMEOUT, last, self._log()))

    def _log(self):
        try:
            with open(self.log, encoding="utf-8", errors="replace") as f:
                return f.read().strip() or "(비어 있음)"
        except OSError:
            return "(로그를 읽지 못했다)"

    def _stop(self, proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

    def test_serve_starts_and_answers(self):
        """뜨고, 살아 있고, 대답한다. 이것이 안 되면 나머지 검사는 의미가 없다."""
        proc, status, body = self._boot()

        self.assertEqual(200, status)
        self.assertIsNone(proc.poll(), "대답한 뒤 곧바로 죽었다")
        keys = {row["key"] for row in json.loads(body)}
        self.assertIn("live", keys)

    def test_boot_banner_does_not_crash_on_registered_projects(self):
        """시작 배너가 등록 목록을 출력하는 자리에서 죽지 않는다.

        이 고장이 난 정확한 지점이다. 배너는 `Projects: ...` 를 찍는데, 그 이름이
        `serve` 경로에서는 대입되지 않았다.
        """
        self._boot()

        log = self._log()
        self.assertNotIn("Traceback", log, "시작 중 예외가 났다:\n%s" % log)
        self.assertIn("Projects:", log, "시작 배너가 등록 목록까지 가지 못했다:\n%s" % log)
        self.assertIn("live", log)

    def test_boot_does_not_recreate_a_deleted_project(self):
        """되살리지 않는다 — 함수가 아니라 **실제 시작**에서 확인한다.

        시작 함수만 보면 이 검사는 통과한다. 실제로 되살리는 것은 5초마다 도는
        runtime reaper 였고, 그건 프로세스로 띄워야만 돈다. **한 주기를 넘겨서**
        확인하는 이유다 — 첫 패스만 보면 5초 뒤의 재생성을 놓친다.
        """
        self._boot()

        deadline = time.time() + REAPER_PERIOD * 1.5
        while time.time() < deadline:
            self.assertFalse(
                os.path.exists(self.dead),
                "지운 디렉토리가 되살아났다 (5초 주기 reaper 가 다시 만든다)",
            )
            time.sleep(0.25)

    def test_boot_reports_a_dead_registration(self):
        """되살리기를 멈춘 등록은 **조용해진다.** 시작에서 한 번은 소리를 내야 한다.

        디렉토리를 다시 만들지 않기로 한 순간, 죽은 등록은 아무 흔적도 남기지
        않는다. 그 등록은 계속 수집 대상으로 남아 있는데 화면에는 안 보인다 —
        고쳐야 할 것이 조용해진 것이지 사라진 것이 아니다.
        """
        self._boot()

        log = self._log()
        self.assertIn("Dead registrations: 1", log,
                      "디렉토리가 없는 등록 1건을 시작에서 알리지 않았다:\n%s" % log)


if __name__ == "__main__":
    unittest.main()
