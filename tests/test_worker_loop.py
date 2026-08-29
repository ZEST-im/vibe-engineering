"""워커 폴링 루프의 정지 조건과 재시도를 고정한다.

루프 엔지니어링에서 답해야 할 것은 셋이다 — **언제 다시 돌고, 언제 멈추고, 무엇을
근거로 다음 반복을 정하는가.** 기존 루프는 셋 다 답하지 않았다.

    while True:
        worked = run_once(args)
        if not worked:
            time.sleep(poll_seconds)

여기서 두 가지가 동시에 잘못돼 있었다.

1. **일시적 오류 하나로 워커가 죽었다.** claim 이 500 을 한 번 내면 예외가 최상위까지
   올라가 프로세스가 끝났다. 재시도도 백오프도 없었다.
2. **영구 오류로 영원히 돌 수 있었다.** `run_once` 는 "할 일 없음(409)"과 "서버가 안
   받음"을 구별하지 않고 둘 다 falsy 로 돌려줬다. 그래서 놀고 있는 워커와 아무것도
   못 하는 워커가 밖에서 같아 보였다 — 이 레포가 반복해 온 실패 방식 그대로다.

루프는 실제로 돌면 느리므로, `run_loop` 에 runner/sleeper/시계를 주입해 검사한다.
잠들지 않으니 빠르고, **얼마나 잠들었는지**까지 단언할 수 있다.
"""
import argparse
import importlib.util
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("worker_loop", os.path.join(SCRIPTS, "worker.py"))
worker = importlib.util.module_from_spec(_spec)
sys.modules["worker_loop"] = worker
_spec.loader.exec_module(worker)


def make_args(**over):
    base = dict(once=False, poll_seconds=1.0, max_consecutive_errors=3,
                max_backoff_seconds=60.0, max_idle_seconds=0.0)
    base.update(over)
    return argparse.Namespace(**base)


class Clock:
    """주입용 시계 — sleep 이 실제로 자지 않고 시간만 앞으로 민다."""

    def __init__(self):
        self.t = 0.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds

    def now(self):
        return self.t


class Exhausted(BaseException):
    """대본이 떨어졌다는 신호.

    `Exception` 을 상속하면 안 된다 — 루프가 런타임 오류를 삼키고 살아남는 것이
    설계이므로, 평범한 예외로 신호를 보내면 루프가 그것마저 ERROR 로 세어버린다.
    실제로 그렇게 만들었다가 테스트 네 개가 구현이 아니라 스캐폴딩 때문에 실패했다.
    """


def scripted(*outcomes):
    """정해진 순서대로 결과를 내는 runner. 문자열은 결과, 예외 인스턴스는 raise."""
    seq = list(outcomes)

    def runner(_args):
        if not seq:
            raise Exhausted()
        item = seq.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return runner


class StopsOnRepeatedErrorTest(unittest.TestCase):
    def test_gives_up_after_max_consecutive_errors(self):
        clock = Clock()
        code = worker.run_loop(
            make_args(max_consecutive_errors=3),
            runner=scripted(RuntimeError("500"), RuntimeError("500"), RuntimeError("500")),
            sleeper=clock.sleep, now=clock.now)
        self.assertEqual(1, code, "영원히 도는 대신 비정상 종료해야 한다")

    def test_backoff_grows_and_is_capped(self):
        clock = Clock()
        worker.run_loop(
            make_args(max_consecutive_errors=5, poll_seconds=1.0, max_backoff_seconds=4.0),
            runner=scripted(*[RuntimeError("x")] * 5),
            sleeper=clock.sleep, now=clock.now)
        self.assertEqual([1.0, 2.0, 4.0, 4.0], clock.slept,
                         "지수로 늘되 상한에서 멈춰야 한다")

    def test_one_error_does_not_kill_the_worker(self):
        """예전에는 여기서 프로세스가 끝났다. 이제는 계속 돈다 (대본이 떨어질 때까지)."""
        clock = Clock()
        with self.assertRaises(Exhausted):
            worker.run_loop(
                make_args(max_consecutive_errors=3),
                runner=scripted(RuntimeError("일시적"), worker.WORKED, worker.IDLE),
                sleeper=clock.sleep, now=clock.now)

    def test_success_resets_the_error_budget(self):
        """오류가 흩어져 있으면 중단하지 않는다 — 연속일 때만 문제다.

        max_consecutive_errors=2 인데 오류가 총 3번 나온다. 카운터가 안 돌아가면
        중단(1)하고, 돌아가면 대본이 떨어질 때까지 돈다.
        """
        clock = Clock()
        with self.assertRaises(Exhausted):
            worker.run_loop(
                make_args(max_consecutive_errors=2),
                runner=scripted(RuntimeError("a"), worker.WORKED,
                                RuntimeError("b"), worker.WORKED,
                                RuntimeError("c"), worker.WORKED),
                sleeper=clock.sleep, now=clock.now)

    def test_idle_also_resets_the_error_budget(self):
        """IDLE 은 정상이므로 오류 카운터를 되돌린다."""
        clock = Clock()
        with self.assertRaises(Exhausted):
            worker.run_loop(
                make_args(max_consecutive_errors=2),
                runner=scripted(RuntimeError("a"), worker.IDLE,
                                RuntimeError("b"), worker.IDLE,
                                RuntimeError("c"), worker.IDLE),
                sleeper=clock.sleep, now=clock.now)


class IdleIsNotAnErrorTest(unittest.TestCase):
    def test_idle_does_not_count_toward_error_budget(self):
        clock = Clock()
        code = worker.run_loop(
            make_args(max_consecutive_errors=2, max_idle_seconds=5, poll_seconds=1.0),
            runner=scripted(*[worker.IDLE] * 10),
            sleeper=clock.sleep, now=clock.now)
        self.assertEqual(0, code, "할 일이 없는 것은 고장이 아니다")

    def test_exits_cleanly_after_max_idle(self):
        clock = Clock()
        code = worker.run_loop(
            make_args(poll_seconds=1.0, max_idle_seconds=3.0),
            runner=scripted(*[worker.IDLE] * 10),
            sleeper=clock.sleep, now=clock.now)
        self.assertEqual(0, code)
        self.assertLessEqual(len(clock.slept), 5, "한도를 넘겨서까지 돌면 안 된다")

    def test_zero_max_idle_means_unlimited(self):
        clock = Clock()
        with self.assertRaises(Exhausted):          # runner 가 고갈될 때까지 돈다 = 무제한
            worker.run_loop(make_args(max_idle_seconds=0),
                            runner=scripted(*[worker.IDLE] * 4),
                            sleeper=clock.sleep, now=clock.now)


class OnceModeTest(unittest.TestCase):
    def test_once_worked_is_zero(self):
        self.assertEqual(0, worker.run_loop(make_args(once=True),
                                            runner=scripted(worker.WORKED)))

    def test_once_idle_is_three(self):
        """기존 계약. 할 일 없음을 오류와 같은 코드로 돌려주면 호출자가 구별 못 한다."""
        self.assertEqual(3, worker.run_loop(make_args(once=True),
                                            runner=scripted(worker.IDLE)))

    def test_once_error_is_one_and_distinct_from_idle(self):
        self.assertEqual(1, worker.run_loop(make_args(once=True),
                                            runner=scripted(RuntimeError("x"))))


class OutcomeContractTest(unittest.TestCase):
    def test_three_outcomes_are_distinct(self):
        self.assertEqual(3, len({worker.WORKED, worker.IDLE, worker.ERROR}))

    def test_no_work_maps_to_idle_not_false(self):
        """409 를 falsy 로 돌려주면 오류와 구별되지 않는다 — 원래 그게 문제였다."""
        with open(os.path.join(SCRIPTS, "worker.py"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("if status == 409:\n        return IDLE", body)
        self.assertNotIn("if status == 409:\n        return False", body)


if __name__ == "__main__":
    unittest.main()
