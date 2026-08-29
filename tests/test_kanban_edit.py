"""직접 편집 경로의 원자성과 동시성을 고정한다.

규약은 "에이전트가 kanban.json 을 직접 편집"하는 것을 기본 경로로 정하는데, 그 경로가
서버 경로보다 약했다. 서버 쓰기는 tmp + fsync + os.replace 로 원자적인 반면 직접 편집은
truncate-then-write 라 읽는 쪽이 반쪽 파일을 본다.

그리고 원자성만으로는 부족하다. 두 프로세스가 각자 읽고 각자 쓰면 나중 쪽이 앞의 것을
덮고, 같은 next_id 를 둘 다 집는다. 실제로 id 409·410 이 그렇게 겹쳤다.

그래서 이 파일의 중심은 `test_naive_edit_actually_loses_updates` 다. 잠금을 쓴 경로가
통과하는 것만 보면 그 잠금이 실제로 무언가를 막고 있는지 알 수 없다. **잠금 없는 같은
작업이 실제로 깨지는 것**을 나란히 보여야 통과가 의미를 갖는다.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
CLI = os.path.join(SCRIPTS, "kanban_edit.py")

sys.path.insert(0, SCRIPTS)
import kanban_edit  # noqa: E402


NAIVE = """
import json, os, sys, time
path = sys.argv[1]
with open(path) as fh:
    data = json.load(fh)
time.sleep(0.02)                      # 읽고 쓰는 사이의 창 — 실제 편집에도 있다
n = data["next_id"]
data["tasks"].append({"id": n, "title": "naive"})
data["next_id"] = n + 1
with open(path, "w") as fh:           # truncate-then-write. 잠금도 원자성도 없다
    json.dump(data, fh)
"""


def fresh_board():
    d = os.path.join(tempfile.mkdtemp(), "vibe-harness")
    os.makedirs(d)
    with open(os.path.join(d, "kanban.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "next_id": 1, "tasks": []}, fh)
    return d


def board(kdir):
    with open(os.path.join(kdir, "kanban.json"), encoding="utf-8") as fh:
        return json.load(fh)


def run_parallel(cmds):
    procs = [subprocess.Popen(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for c in cmds]
    for p in procs:
        p.wait()


class ConcurrentEditTest(unittest.TestCase):
    N = 12

    def test_locked_edits_lose_nothing(self):
        kdir = fresh_board()
        run_parallel([[sys.executable, CLI, "--kanban-dir", kdir,
                       "add", f"작업{i}", "--category", "test"] for i in range(self.N)])
        tasks = board(kdir)["tasks"]
        ids = [t["id"] for t in tasks]
        self.assertEqual(self.N, len(tasks), "동시 편집에서 태스크가 유실됐다")
        self.assertEqual(len(ids), len(set(ids)), "id 가 겹쳤다: %s" % ids)

    def test_next_id_stays_above_every_used_id(self):
        kdir = fresh_board()
        run_parallel([[sys.executable, CLI, "--kanban-dir", kdir,
                       "add", f"작업{i}"] for i in range(self.N)])
        data = board(kdir)
        used = [t["id"] for t in data["tasks"] if isinstance(t["id"], int)]
        self.assertGreater(data["next_id"], max(used))

    def test_naive_edit_actually_loses_updates(self):
        """대조군. 잠금 없는 같은 작업은 실제로 깨진다 — 그래야 위 통과가 의미를 갖는다."""
        kdir = fresh_board()
        script = os.path.join(kdir, "naive.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(NAIVE)
        path = os.path.join(kdir, "kanban.json")
        run_parallel([[sys.executable, script, path] for _ in range(self.N)])
        tasks = board(kdir)["tasks"]
        ids = [t["id"] for t in tasks]
        broke = len(tasks) < self.N or len(ids) != len(set(ids))
        self.assertTrue(
            broke,
            "잠금 없는 편집이 %d개 동시 실행에서도 멀쩡했다 — 이 테스트가 재현하려는 "
            "경합이 일어나지 않았다는 뜻이므로, 통과한 다른 테스트도 아무것도 증명하지 "
            "못한다. N 을 올리거나 창을 넓힐 것." % self.N)


class ArchiveAwarenessTest(unittest.TestCase):
    def test_archived_ids_are_not_reused(self):
        """아카이브를 안 보면 이미 쓴 번호를 다시 발급한다 — 조용한 손상이다."""
        kdir = fresh_board()
        adir = os.path.join(kdir, "archive")
        os.makedirs(adir)
        with open(os.path.join(adir, "2026-01.json"), "w", encoding="utf-8") as fh:
            json.dump({"tasks": [{"id": 50, "title": "옛것"}]}, fh)
        # next_id 를 일부러 뒤처지게 둔다 (손으로 고친 파일이 이렇게 된다)
        task = kanban_edit.add_task(kdir, {"title": "새것"})
        self.assertNotEqual(50, task["id"])
        self.assertGreater(task["id"], 50)

    def test_archived_ids_helper_reads_every_month(self):
        kdir = fresh_board()
        adir = os.path.join(kdir, "archive")
        os.makedirs(adir)
        for name, tid in (("2026-01.json", 5), ("2026-02.json", 9)):
            with open(os.path.join(adir, name), "w", encoding="utf-8") as fh:
                json.dump({"tasks": [{"id": tid}]}, fh)
        self.assertEqual({5, 9}, set(kanban_edit.archived_ids(kdir)))

    def test_corrupt_archive_does_not_block_editing(self):
        kdir = fresh_board()
        adir = os.path.join(kdir, "archive")
        os.makedirs(adir)
        with open(os.path.join(adir, "2026-03.json"), "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        self.assertIsNotNone(kanban_edit.add_task(kdir, {"title": "그래도 된다"}))


class LockBehaviourTest(unittest.TestCase):
    def test_lock_is_released_after_exception(self):
        """예외로 빠져나가도 풀려야 한다. 안 그러면 다음 편집이 영영 막힌다.

        **주의 — 이 테스트는 구현의 finally 를 강제하지 못한다.** finally 를 지우고
        돌려봤더니 그대로 통과했다. CPython 은 with 블록을 빠져나갈 때 제너레이터를
        닫고 참조 카운팅이 fd 를 닫아, 잠금이 저절로 풀리기 때문이다. 논블로킹 프로브로
        바꿔도 마찬가지였다.

        그래서 이 테스트가 고정하는 것은 **성질**이지 구현이 아니다 — "예외 뒤에 잠금이
        남아 있지 않다". 구현의 finally 는 참조 카운팅에 기대지 않는 런타임(PyPy 등)과,
        fh 참조가 밖으로 새는 변경을 대비한 방어로 남긴다. 잠금이 실제로 배타적인지는
        아래 test_lock_actually_blocks_a_second_holder 가 본다 (no-op 으로 바꾸면 잡힌다).
        """
        if not kanban_edit.HAVE_FLOCK:
            self.skipTest("fcntl 없음")
        import fcntl as _f
        kdir = fresh_board()
        with self.assertRaises(RuntimeError):
            with kanban_edit.kanban_lock(kdir):
                raise RuntimeError("중단")
        probe = open(os.path.join(kdir, kanban_edit.LOCK_NAME), "a+")
        try:
            _f.flock(probe, _f.LOCK_EX | _f.LOCK_NB)   # 아직 잡혀 있으면 BlockingIOError
            _f.flock(probe, _f.LOCK_UN)
        except BlockingIOError:
            self.fail("예외로 빠져나간 뒤에도 잠금이 남아 있다")
        finally:
            probe.close()

    def test_lock_actually_blocks_a_second_holder(self):
        """잠금이 정말 배타적인가. no-op 이면 이 파일의 동시성 테스트가 전부 무의미하다."""
        if not kanban_edit.HAVE_FLOCK:
            self.skipTest("fcntl 없음")
        import fcntl as _f
        kdir = fresh_board()
        with kanban_edit.kanban_lock(kdir):
            probe = open(os.path.join(kdir, kanban_edit.LOCK_NAME), "a+")
            try:
                with self.assertRaises(BlockingIOError):
                    _f.flock(probe, _f.LOCK_EX | _f.LOCK_NB)
            finally:
                probe.close()

    def test_require_lock_fails_loudly_without_fcntl(self):
        """잠글 수 없으면 조용히 진행하지 않는다 — 조용한 진행이 이 레포의 반복 실패다."""
        kdir = fresh_board()
        saved = kanban_edit.HAVE_FLOCK
        kanban_edit.HAVE_FLOCK = False
        try:
            with self.assertRaises(SystemExit):
                with kanban_edit.kanban_lock(kdir, require=True):
                    pass
            # require 없이는 진행한다 (원자적 교체는 여전히 동작)
            with kanban_edit.kanban_lock(kdir, require=False):
                pass
        finally:
            kanban_edit.HAVE_FLOCK = saved

    def test_write_leaves_no_tmp_file(self):
        kdir = fresh_board()
        kanban_edit.add_task(kdir, {"title": "x"})
        leftovers = [f for f in os.listdir(kdir) if f.endswith(".tmp")]
        self.assertEqual([], leftovers, "tmp 파일이 남았다 — 원자적 교체가 깨졌다")


class CliTest(unittest.TestCase):
    def run_cli(self, kdir, *args):
        return subprocess.run([sys.executable, CLI, "--kanban-dir", kdir, *args],
                              capture_output=True, text=True)

    def test_add_then_set_then_show(self):
        kdir = fresh_board()
        added = json.loads(self.run_cli(kdir, "add", "제목", "--category", "infra").stdout)
        self.run_cli(kdir, "set", str(added["id"]), "--status", "done")
        shown = json.loads(self.run_cli(kdir, "show", str(added["id"])).stdout)
        self.assertEqual("done", shown["status"])
        self.assertEqual("infra", shown["category"])

    def test_missing_task_fails(self):
        kdir = fresh_board()
        self.assertNotEqual(0, self.run_cli(kdir, "set", "999", "--status", "done").returncode)

    def test_id_allocation_matches_server_implementation(self):
        """id 발급을 여기서 다시 구현하면 두 경로가 조용히 갈라진다."""
        with open(CLI, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("_new_task", body, "server 의 태스크 생성을 재사용해야 한다")
        self.assertNotIn("def _mint_id", body, "id 발급을 여기서 다시 구현하면 안 된다")


if __name__ == "__main__":
    unittest.main()
