"""어느 모델이 이 태스크를 했는지 기록한다.

## 왜 필요한가

"복잡한 작업에는 센 모델" 같은 매핑을 만들려면 **어느 모델로 했을 때 어땠는지** 가
있어야 한다. 지금은 없다.

`runs.json` 에 `model` 은 잘 채워져 있고(실측 778건, 실제 모델 6종) `task_id` 필드도
있는데 **연결이 5.3% 밖에 안 채워져 있다.** 그래서 과거 데이터로는 못 센다.

시간으로 이어붙이는 것도 시도했다가 접었다. `runs` 의 `ts` 는 세션 구간이 아니라
**transcript 파일의 mtime 한 점**이라(`reconcile_runs.py`), 몇 시간짜리 세션이 끝
시각 하나로만 찍힌다. done 1972건 중 모델 하나로 특정되는 것은 **50건**이고 그나마
한 모델에 쏠려 있어 비교가 성립하지 않는다.

그러니 앞으로 쌓는 수밖에 없다. 이 파일은 그 장치를 고정한다.

## 무엇을 읽는가

transcript 는 메시지마다 `model` 과 `timestamp` 를 갖는다. 태스크가 `in_progress`
였던 구간에 나타난 모델이 그 작업을 한 모델이다.

전량 스캔 비용을 재봤다 — 24.8MB 짜리 활성 transcript 에서 **0.10초**다. 뒤에서부터
읽으면 13배 빠르지만, 잘린 줄 처리 같은 복잡도를 더할 값이 없어서 그냥 읽는다.

## 조용히 비는 것을 경계한다

`done` 으로 가는 경로가 **셋**이다 — 서버 PUT, 워커, `kanban_edit` CLI. 한 곳에만
붙이면 나머지는 기록이 비는데 아무도 모른다. 이 레포가 이미 겪은 사고 모양이다.
"""
import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

os.environ["VIBE_HARNESS_SYNC_CONFIG"] = os.path.join(
    tempfile.gettempdir(), "vibe-harness-task-models-no-sync.json")

import reconcile_runs  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "vh_server_task_models", os.path.join(SCRIPTS, "server.py"))
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

KST = dt.timezone(dt.timedelta(hours=9))


def at(hour, minute=0):
    return dt.datetime(2026, 9, 29, hour, minute, tzinfo=KST).isoformat()


def transcript(dirpath, name, entries):
    """(timestamp, model) 쌍으로 transcript 한 개를 만든다."""
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(dirpath, name)
    with open(path, "w", encoding="utf-8") as fh:
        for ts, model in entries:
            fh.write(json.dumps({
                "timestamp": ts,
                "message": {"model": model, "usage": {"input_tokens": 1, "output_tokens": 1}},
            }, ensure_ascii=False) + "\n")
    return path


class ModelsBetweenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "transcripts")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_models_inside_the_window(self):
        transcript(self.dir, "a.jsonl", [
            (at(9), "claude-haiku-4-5"),      # 구간 앞
            (at(11), "claude-opus-5"),        # 구간 안
            (at(15), "claude-sonnet-5"),      # 구간 뒤
        ])

        got = reconcile_runs.models_between(self.dir, at(10), at(12))

        self.assertEqual(["claude-opus-5"], got)

    def test_several_models_are_all_kept_and_sorted(self):
        transcript(self.dir, "a.jsonl", [
            (at(11), "claude-sonnet-5"),
            (at(11, 30), "claude-opus-5"),
            (at(11, 45), "claude-sonnet-5"),   # 중복
        ])

        got = reconcile_runs.models_between(self.dir, at(10), at(12))

        self.assertEqual(["claude-opus-5", "claude-sonnet-5"], got)

    def test_several_transcripts_are_merged(self):
        transcript(self.dir, "a.jsonl", [(at(11), "claude-opus-5")])
        transcript(self.dir, "b.jsonl", [(at(11), "gpt-5-codex")])

        got = reconcile_runs.models_between(self.dir, at(10), at(12))

        self.assertEqual(["claude-opus-5", "gpt-5-codex"], got)

    def test_boundaries_are_inclusive(self):
        transcript(self.dir, "a.jsonl", [(at(10), "start"), (at(12), "end")])

        got = reconcile_runs.models_between(self.dir, at(10), at(12))

        self.assertEqual(["end", "start"], got)


class ItDoesNotBreakOnBadInputTest(ModelsBetweenTest):
    """읽기 실패가 전이를 막으면 안 된다 — 기록은 부산물이지 본업이 아니다."""

    def test_a_missing_directory_yields_nothing(self):
        self.assertEqual([], reconcile_runs.models_between(
            os.path.join(self.tmp.name, "없음"), at(10), at(12)))

    def test_a_broken_line_only_skips_itself(self):
        path = transcript(self.dir, "a.jsonl", [(at(11), "claude-opus-5")])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("{깨진 줄\n")
            fh.write(json.dumps({"timestamp": at(11, 30),
                                 "message": {"model": "gpt-5-codex"}}) + "\n")

        got = reconcile_runs.models_between(self.dir, at(10), at(12))

        self.assertEqual(["claude-opus-5", "gpt-5-codex"], got)

    def test_messages_without_a_timestamp_are_ignored(self):
        path = transcript(self.dir, "a.jsonl", [(at(11), "claude-opus-5")])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"message": {"model": "시각없음"}}) + "\n")

        self.assertEqual(["claude-opus-5"],
                         reconcile_runs.models_between(self.dir, at(10), at(12)))

    def test_a_naive_timestamp_is_read_as_kst(self):
        """수집기가 이미 KST 를 기준으로 쓴다. 여기만 UTC 로 읽으면 9시간이 어긋난다."""
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "a.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"timestamp": "2026-09-29T11:00:00",
                                 "message": {"model": "naive"}}) + "\n")

        self.assertEqual(["naive"], reconcile_runs.models_between(self.dir, at(10), at(12)))

    def test_an_unreadable_window_yields_nothing(self):
        transcript(self.dir, "a.jsonl", [(at(11), "claude-opus-5")])

        self.assertEqual([], reconcile_runs.models_between(self.dir, "", at(12)))
        self.assertEqual([], reconcile_runs.models_between(self.dir, at(10), "쓰레기"))


class StampedOnTransitionTest(unittest.TestCase):
    """전이 지점에서 실제로 적히는가."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kanban_dir = os.path.join(self.tmp.name, "proj", "vibe-harness")
        os.makedirs(self.kanban_dir)
        self.tdir = os.path.join(self.tmp.name, "transcripts")
        transcript(self.tdir, "a.jsonl", [(at(11), "claude-opus-5")])
        self._saved = server._transcript_dir_for
        server._transcript_dir_for = lambda kanban_dir: self.tdir

    def tearDown(self):
        server._transcript_dir_for = self._saved
        self.tmp.cleanup()

    def task(self, **kw):
        t = {"id": 1, "title": "t", "status": "in_progress",
             "started_at": at(10), "completed_at": ""}
        t.update(kw)
        return t

    def test_moving_to_done_records_the_models(self):
        t = self.task()

        server._update_task(t, {"status": "done", "completed_at": at(12)},
                            kanban_dir=self.kanban_dir)

        self.assertEqual(["claude-opus-5"], t.get("models"))

    def test_without_a_start_time_it_records_nothing(self):
        """구간을 모르면 아무 모델이나 집어오게 된다 — 비워두는 것이 맞다."""
        t = self.task(started_at="")

        server._update_task(t, {"status": "done"}, kanban_dir=self.kanban_dir)

        self.assertEqual([], t.get("models", []))

    def test_other_transitions_do_not_stamp(self):
        t = self.task(status="todo")

        server._update_task(t, {"status": "in_progress"}, kanban_dir=self.kanban_dir)

        self.assertNotIn("models", t)

    def test_transition_still_works_without_a_kanban_dir(self):
        """kanban_dir 를 모르는 호출부가 있다. 거기서 죽으면 안 된다."""
        t = self.task()

        server._update_task(t, {"status": "done"})

        self.assertEqual("done", t["status"])
        self.assertTrue(t["completed_at"])

    def test_an_explicit_models_value_is_not_overwritten(self):
        """사람이 적어 넣은 값을 추정으로 덮지 않는다."""
        t = self.task()

        server._update_task(t, {"status": "done", "models": ["손으로-적음"]},
                            kanban_dir=self.kanban_dir)

        self.assertEqual(["손으로-적음"], t["models"])


class CreatedInProgressHasAStartTest(unittest.TestCase):
    """`in_progress` 로 **바로 생성**하면 시작 시각이 비어 구간을 모른다.

    그러면 `models` 는 늘 빈 목록이 된다 — 테스트는 통과하는데 실제로는 아무것도
    쌓이지 않는다. 에이전트가 태스크를 만들 때 대부분 이 경로를 탄다.

    `status: done` 으로 바로 만들면 `completed_at` 이 비던 것과 같은 계열이고,
    그쪽은 몇 주째 Known Issues 에 있었다.
    """

    def test_creating_in_progress_stamps_the_start(self):
        data = {"version": 1, "next_id": 1, "tasks": []}

        _data, task = server._new_task(data, {"title": "t", "status": "in_progress"})

        self.assertTrue(task["started_at"], "구간을 모르면 기록이 늘 빈다")

    def test_creating_todo_does_not_stamp_a_start(self):
        data = {"version": 1, "next_id": 1, "tasks": []}

        _data, task = server._new_task(data, {"title": "t", "status": "todo"})

        self.assertEqual("", task["started_at"])

    def test_an_explicit_start_is_kept(self):
        data = {"version": 1, "next_id": 1, "tasks": []}

        _data, task = server._new_task(
            data, {"title": "t", "status": "in_progress", "started_at": at(10)})

        self.assertEqual(at(10), task["started_at"])


class UnknownFieldsSurviveTest(unittest.TestCase):
    """CLI 는 서버가 모르는 필드도 받는다. 그 성질을 잃으면 안 된다.

    `gh_surface` 가 이슈 번호를 `set_task` 로 적어 중복 생성을 막는다. `_update_task`
    는 화이트리스트라 모르는 필드를 버리므로, 전이 처리를 합치면서 그 성질이 사라지면
    **같은 이슈가 계속 다시 만들어진다.** 실제로 그렇게 깨뜨렸다가 되돌렸다.
    """

    def test_an_unknown_field_is_kept(self):
        import kanban_edit
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kdir = os.path.join(tmp.name, "vibe-harness")
        os.makedirs(kdir)

        task = kanban_edit.add_task(kdir, {"title": "t"})
        out = kanban_edit.set_task(kdir, task["id"], {"issue": 555})

        self.assertEqual(555, out.get("issue"))

    def test_unknown_fields_and_a_transition_together(self):
        import kanban_edit
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kdir = os.path.join(tmp.name, "vibe-harness")
        os.makedirs(kdir)

        task = kanban_edit.add_task(kdir, {"title": "t", "status": "in_progress"})
        out = kanban_edit.set_task(kdir, task["id"], {"status": "done", "issue": 42})

        self.assertEqual(42, out.get("issue"))
        self.assertTrue(out.get("completed_at"), "전이 처리도 그대로여야 한다")


class EveryDonePathStampsTest(unittest.TestCase):
    """`done` 으로 가는 경로가 셋이다. 한 곳만 붙이면 나머지는 조용히 빈다."""

    def test_the_put_handler_passes_the_kanban_dir(self):
        import re
        src = open(os.path.join(SCRIPTS, "server.py"), encoding="utf-8").read()
        calls = re.findall(r"_update_task\((.*?)\)\s*$", src, re.M)
        stamping = [c for c in calls if "kanban_dir" in c]

        self.assertGreaterEqual(len(stamping), 2,
                                "done 으로 가는 서버 경로가 둘인데 한 곳만 kanban_dir 를 넘긴다")

    def test_kanban_edit_records_models_too(self):
        """문자열이 아니라 **동작**을 본다 — 어떤 경로로 부르든 기록이 남아야 한다.

        패치하지 않고 실제 경로로 검증한다. `_server()` 가 호출마다 새 모듈을 만들어
        패치가 안 먹는 것도 있지만, 무엇보다 **경로 계산까지 포함해서** 봐야 한다.
        실제 `~/.claude/` 를 건드리지 않도록 HOME 을 임시로 돌린다.
        """
        import kanban_edit
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = os.path.join(tmp.name, "home")
        proj = os.path.join(tmp.name, "proj")
        kdir = os.path.join(proj, "vibe-harness")
        os.makedirs(kdir)

        saved_home = os.environ.get("HOME")
        os.environ["HOME"] = home
        self.addCleanup(lambda: os.environ.__setitem__("HOME", saved_home)
                        if saved_home is not None else os.environ.pop("HOME", None))

        slug = reconcile_runs._project_slug(proj)
        transcript(os.path.join(home, ".claude", "projects", slug), "a.jsonl",
                   [(at(11), "claude-opus-5")])

        task = kanban_edit.add_task(kdir, {"title": "t", "status": "in_progress"})
        # started_at 은 상태 전이로 찍힌다. 만든 직후라 지금 시각이므로 구간을 열어준다.
        kanban_edit.set_task(kdir, task["id"], {"started_at": at(10)})
        out = kanban_edit.set_task(kdir, task["id"],
                                   {"status": "done", "completed_at": at(12)})

        self.assertEqual(["claude-opus-5"], out.get("models"))
        self.assertTrue(out.get("completed_at"),
                        "CLI 로 닫으면 completed_at 이 비던 함정도 같이 닫힌다")


if __name__ == "__main__":
    unittest.main()
