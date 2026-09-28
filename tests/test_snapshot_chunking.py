"""번들이 프로젝트 수에 비례해 자라 전송이 413 으로 막히는 것을 푼다.

## 실측

2026-09-28 기준 이 머신의 `ax-project` 번들은 **5,351,472 bytes · 13 source** 다.
전송이 413 으로 거부되고, `sync-pending.json` 에 쌓인 채 대시보드는 낡은 상태로 남는다.

무게는 태스크가 78.8% 이고, 그 안의 59% 가 아카이브다. 그러나 **어느 쪽을 덜어내도
근본은 같다** — source 를 한 요청에 다 싣는 한 프로젝트가 늘면 언젠가 다시 막힌다.

## 한계선을 모른 채로 푼다

잘못된 토큰으로 크기만 올려 재보니 16MB 까지 401 이 온다 — **전송 계층에는 제한이
없고** 413 은 인증 이후 수신 애플리케이션이 낸다. 그 임계값은 이쪽에서 읽을 수 없다.

그래서 **숫자를 고정하지 않는다.** 예산을 정해 쪼개되, 413 이 오면 예산을 반으로 줄여
다시 쪼갠다. 임계값이 얼마든 몇 번 만에 그 아래로 내려가고, 프로젝트가 더 늘어도
같은 방식으로 버틴다. 상수를 박아두면 그 상수가 다음 사고가 된다.

## 왜 source 단위인가

수신 머지가 **key 단위 upsert** 다 — 한 번에 몇 개를 보내든 다른 키의 행은 건드리지
않는다. 그래서 나눠 보내는 것이 한 번에 보내는 것과 의미가 같다. 실제로 1건(106KB)만
줄여 보낸 우회가 통했던 근거도 그것이다.

한 source 혼자 예산을 넘으면 더 쪼갤 수 없다. 그때는 **버리지 않고 혼자 담아 보낸다** —
막히더라도 무엇이 막혔는지 이름이 남아야 한다. 조용히 빠지면 그 프로젝트는 일을 안 한
것이 된다(같은 계열의 사고를 이미 한 번 겪었다).
"""
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
    tempfile.gettempdir(), "vibe-harness-chunking-no-sync.json")

_spec = importlib.util.spec_from_file_location(
    "vh_server_chunking", os.path.join(SCRIPTS, "server.py"))
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


def source(key, filler=0):
    return {"key": key, "name": key, "tasks": [{"id": 1, "t": "x" * filler}],
            "decisions": [], "context": {}, "velocity": {}, "schema": {}, "runtime": {}}


def body(sources):
    return {"schema_version": 1, "dashboard": "ax-project",
            "generated_at": "2026-09-28T09:00:00+09:00",
            "sources": list(sources), "revision": "original"}


def wire_size(payload):
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class NothingIsLostTest(unittest.TestCase):
    """쪼개는 것이 버리는 것이 되면 안 된다."""

    def test_every_source_appears_exactly_once(self):
        original = body([source(f"p{i}", 500) for i in range(10)])

        chunks = server._snapshot_chunks(original, budget=2000)

        seen = [s["key"] for c in chunks for s in c["sources"]]
        self.assertEqual(sorted(seen), sorted(s["key"] for s in original["sources"]))
        self.assertEqual(len(seen), len(set(seen)), "같은 source 가 두 번 실렸다")

    def test_order_is_preserved(self):
        original = body([source(k, 500) for k in ("alpha", "beta", "gamma", "delta")])

        chunks = server._snapshot_chunks(original, budget=2000)

        self.assertEqual(["alpha", "beta", "gamma", "delta"],
                         [s["key"] for c in chunks for s in c["sources"]])

    def test_a_source_bigger_than_the_budget_is_still_sent(self):
        """더 쪼갤 수 없다고 버리면 그 프로젝트는 일을 안 한 것이 된다."""
        original = body([source("huge", 9000), source("small", 10)])

        chunks = server._snapshot_chunks(original, budget=1000)

        keys = [s["key"] for c in chunks for s in c["sources"]]
        self.assertIn("huge", keys)
        self.assertEqual(1, sum(len(c["sources"]) for c in chunks if
                                any(s["key"] == "huge" for s in c["sources"])),
                         "예산을 넘는 source 는 혼자 담겨야 한다")


class ChunksFitTheBudgetTest(unittest.TestCase):
    def test_a_small_bundle_stays_one_request(self):
        original = body([source("a", 10), source("b", 10)])

        chunks = server._snapshot_chunks(original, budget=1_000_000)

        self.assertEqual(1, len(chunks))

    def test_a_large_bundle_is_split(self):
        original = body([source(f"p{i}", 2000) for i in range(6)])

        chunks = server._snapshot_chunks(original, budget=5000)

        self.assertGreater(len(chunks), 1)

    def test_each_chunk_fits_unless_a_single_source_cannot(self):
        original = body([source(f"p{i}", 1500) for i in range(8)])
        budget = 6000

        for chunk in server._snapshot_chunks(original, budget=budget):
            if len(chunk["sources"]) > 1:
                self.assertLessEqual(wire_size(chunk), budget,
                                     "여러 개를 담았는데 예산을 넘었다")


class EachChunkIsAValidBundleTest(unittest.TestCase):
    """수신 쪽은 덩어리를 번들로 받는다 — 봉투가 온전해야 한다."""

    def setUp(self):
        self.original = body([source(f"p{i}", 2000) for i in range(6)])
        self.chunks = server._snapshot_chunks(self.original, budget=5000)

    def test_envelope_fields_survive(self):
        for chunk in self.chunks:
            self.assertEqual("ax-project", chunk["dashboard"])
            self.assertEqual(1, chunk["schema_version"])
            self.assertEqual(self.original["generated_at"], chunk["generated_at"])

    def test_each_chunk_has_its_own_revision(self):
        revisions = [c["revision"] for c in self.chunks]

        self.assertTrue(all(revisions), "revision 이 비면 수신이 비교할 수 없다")
        self.assertEqual(len(revisions), len(set(revisions)),
                         "내용이 다른데 revision 이 같으면 변화를 못 본다")
        self.assertNotIn("original", revisions, "원본 revision 을 그대로 물려주면 안 된다")

    def test_the_original_is_not_mutated(self):
        self.assertEqual(6, len(self.original["sources"]))
        self.assertEqual("original", self.original["revision"])


class EmptyBundleTest(unittest.TestCase):
    def test_no_sources_still_yields_one_request(self):
        """보낼 것이 없다는 사실도 수신이 알아야 한다 — 침묵과 구분되지 않는다."""
        chunks = server._snapshot_chunks(body([]), budget=1000)

        self.assertEqual(1, len(chunks))
        self.assertEqual([], chunks[0]["sources"])


class ShrinkOnRejectionTest(unittest.TestCase):
    """413 은 '예산이 틀렸다'는 유일한 신호다. 임계값을 모르므로 그것으로 배운다."""

    def test_budget_halves_until_it_fits(self):
        sizes = list(server._budget_ladder(start=1_000_000, floor=50_000))

        self.assertEqual(1_000_000, sizes[0])
        for i in range(1, len(sizes)):
            self.assertLess(sizes[i], sizes[i - 1],
                            "예산이 줄지 않으면 같은 요청을 반복한다")

    def test_the_ladder_is_finite(self):
        sizes = list(server._budget_ladder(start=1_000_000, floor=50_000))

        self.assertLess(len(sizes), 20, "끝없이 재시도하면 전송이 멈추지 않는다")
        self.assertGreaterEqual(sizes[-1], 1, "예산이 0 이 되면 아무것도 못 담는다")

    def test_it_stops_at_the_floor(self):
        sizes = list(server._budget_ladder(start=800, floor=100))

        self.assertLessEqual(sizes[-1], 100 * 2,
                             "하한 아래로 계속 줄이면 source 하나도 못 담는 예산이 된다")




class FakeReject:
    """413 을 n 번 낸 뒤 통과시키는 가짜 전송. HTTP 는 흉내 내지 않고 결과만 준다."""

    def __init__(self, reject_above=None):
        self.reject_above = reject_above
        self.sent = []

    def __call__(self, cfg, chunk):
        size = wire_size(chunk)
        self.sent.append((size, [s["key"] for s in chunk["sources"]]))
        if self.reject_above is not None and size > self.reject_above:
            raise server.urllib_error.HTTPError(
                "https://example.test", 413, "Payload Too Large", {}, None)


class SendShrinksUntilItFitsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {"endpoint": "https://example.test", "secret": "s"}
        self.payload = body([source(f"p{i}", 40_000) for i in range(8)])

    def test_one_request_when_it_already_fits(self):
        post = FakeReject()

        sent = server._send_snapshot(self.cfg, self.payload, post=post)

        self.assertEqual(1, sent)
        self.assertEqual(1, len(post.sent))

    def test_it_retries_smaller_after_413(self):
        """임계값을 모르므로 413 으로 배운다."""
        post = FakeReject(reject_above=150_000)

        sent = server._send_snapshot(self.cfg, self.payload, post=post)

        self.assertGreater(sent, 1, "쪼개지 않고 통과했다면 테스트가 거짓이다")
        for size, _keys in post.sent[-sent:]:
            self.assertLessEqual(size, 150_000)

    def test_everything_arrives_after_the_retry(self):
        post = FakeReject(reject_above=150_000)

        sent = server._send_snapshot(self.cfg, self.payload, post=post)

        delivered = [k for _size, keys in post.sent[-sent:] for k in keys]
        self.assertEqual(sorted(s["key"] for s in self.payload["sources"]),
                         sorted(delivered))

    def test_a_non_413_error_is_not_swallowed(self):
        def post(cfg, chunk):
            raise server.urllib_error.HTTPError("https://example.test", 401,
                                                "Unauthorized", {}, None)

        with self.assertRaises(server.urllib_error.HTTPError) as caught:
            server._send_snapshot(self.cfg, self.payload, post=post)
        self.assertEqual(401, caught.exception.code)

    def test_it_gives_up_instead_of_looping_forever(self):
        """하한까지 줄여도 막히면 멈추고 알린다 — 조용히 포기하면 안 된다."""
        post = FakeReject(reject_above=10)

        with self.assertRaises(server.urllib_error.HTTPError) as caught:
            server._send_snapshot(self.cfg, self.payload, post=post)
        self.assertEqual(413, caught.exception.code)


class ItNamesWhatIsStuckTest(unittest.TestCase):
    """더 쪼갤 수 없는 source 가 막히면 이름이 남아야 한다.

    조용히 실패하면 "동기화가 안 된다" 까지만 알고 **어느 프로젝트가 원인인지** 모른다.
    그 상태로는 아카이브를 덜지, 그 보드를 줄일지 판단할 수가 없다.
    """

    def test_the_oversized_source_is_named(self):
        cfg = {"endpoint": "https://example.test"}
        payload = body([source("tiny", 10), source("enormous", 200_000)])
        post = FakeReject(reject_above=60_000)

        with self.assertRaises(server.urllib_error.HTTPError):
            server._send_snapshot(cfg, payload, post=post)

        stuck = server._oversized_sources(payload, budget=60_000)

        self.assertEqual(["enormous"], stuck)

    def test_nothing_is_named_when_everything_fits(self):
        payload = body([source("a", 10), source("b", 10)])

        self.assertEqual([], server._oversized_sources(payload, budget=1_000_000))


if __name__ == "__main__":
    unittest.main()
