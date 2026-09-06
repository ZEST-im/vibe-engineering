"""서버를 **HTTP 로** 때린다 — 라우팅 · 요청 파싱 · 오류 응답.

## 왜 함수 호출로는 부족한가

`server.py` 는 커버리지 46% 인데 그중 HTTP 경로는 사실상 0 이었다. 테스트가 전부
내부 함수를 직접 불렀기 때문이다. 그런데 **밖에서 들어오는 입력을 다루는 자리가
실제 표면**이고, 거기서만 나는 고장이 따로 있다.

실제로 이 파일을 쓰면서 둘 나왔다. 둘 다 함수 호출로는 보이지 않는다.

1. **깨진 JSON 을 보내면 응답이 아예 없었다.** `_body()` 의 `json.loads` 가 그대로
   터져 핸들러 밖으로 나갔고, socketserver 는 아무것도 쓰지 않은 채 연결을 끊었다.
   클라이언트가 받는 것은 400 이 아니라 `RemoteDisconnected` 다 — 무엇이 잘못됐는지도,
   서버가 살아 있는지도 알 수 없다.
2. **`Content-Length` 가 숫자가 아니어도 같은 일이 났다.** `int()` 가 터진다.

이 프로젝트가 반복해 온 실패는 '성공처럼 보이는 침묵'인데, 이건 그 HTTP 판이다 —
밖에서 보면 서버가 죽은 것과 구별되지 않는다.

## 규칙

**어떤 요청도 응답 없이 끝나지 않는다.** 500 이라도 돌려주는 편이 낫다. 관측 가능하고,
무엇이 터졌는지 말해주기 때문이다.
"""
import contextlib
import http.client
import importlib.util
import io
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")

sys.path.insert(0, SCRIPTS)
_spec = importlib.util.spec_from_file_location("vh_server_http",
                                               os.path.join(SCRIPTS, "server.py"))
server = importlib.util.module_from_spec(_spec)
sys.modules["vh_server_http"] = server
_spec.loader.exec_module(server)


class ServedOverHttpTest(unittest.TestCase):
    """실제 소켓으로 요청한다. 프로젝트 등록은 격리한다 — 이 머신의 실제 보드를
    건드리면 테스트가 운영 데이터를 읽고 쓰게 된다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.kanban = os.path.join(cls.tmp, "vibe-harness")
        os.makedirs(cls.kanban)
        server._write_kanban(cls.kanban, {
            "version": 1, "next_id": 2,
            "tasks": [{"id": 1, "title": "이중 계상 정리", "status": "todo",
                       "details": "", "category": "qa"}],
        })
        cls._projects = server.load_projects
        server.load_projects = lambda: {"demo": {"name": "Demo",
                                                 "kanban_dir": cls.kanban}}
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
        server.load_projects = cls._projects

    def call(self, method, path, body=None, headers=None):
        """(status, bytes). **연결이 끊기면 그 자체를 결과로 돌려준다** —
        응답 없음과 오류 응답을 구별해야 하기 때문이다."""
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers=headers or {"Content-Type": "application/json"})
        # 커버리지 추적이 붙으면 스위트가 눈에 띄게 느려진다. 짧은 타임아웃은 그때
        # "연결 끊김"으로 오독돼 게이트를 간헐적으로 빨갛게 만든다 — 간헐적으로
        # 빨간 게이트는 곧 무시된다.
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, exc.read(), dict(exc.headers)
            finally:
                exc.close()
        except (http.client.RemoteDisconnected, ConnectionError) as exc:
            return "NO RESPONSE", str(exc).encode(), {}


class RoutingTest(ServedOverHttpTest):
    def test_context_is_served(self):
        status, body, _h = self.call("GET", "/api/demo/context")
        self.assertEqual(200, status)
        self.assertIn("phase", json.loads(body))

    def test_tasks_are_served(self):
        status, body, _h = self.call("GET", "/api/demo/tasks")
        self.assertEqual(200, status)
        self.assertEqual(1, len(json.loads(body)))

    def test_stats_are_served(self):
        status, body, _h = self.call("GET", "/api/demo/stats")
        self.assertEqual(200, status)
        self.assertIn("todo", json.loads(body))

    def test_unknown_project_is_404_with_a_reason(self):
        status, body, _h = self.call("GET", "/api/nope/context")
        self.assertEqual(404, status)
        self.assertEqual("unknown project", json.loads(body)["error"])

    def test_unknown_route_is_404_not_a_crash(self):
        status, _b, _h = self.call("GET", "/api/demo/there-is-no-such-thing")
        self.assertEqual(404, status)

    def test_a_trailing_slash_is_the_same_route(self):
        self.assertEqual(200, self.call("GET", "/api/demo/context/")[0])

    def test_json_responses_say_they_are_json(self):
        _s, _b, headers = self.call("GET", "/api/demo/context")
        self.assertEqual("application/json", headers.get("Content-Type"))


class RequestParsingTest(ServedOverHttpTest):
    def test_a_query_string_survives_url_encoding(self):
        """한글 검색어가 퍼센트 인코딩으로 온다. 여기가 깨지면 검색이 조용히 0건이 된다."""
        status, body, _h = self.call(
            "GET", "/api/demo/search?q=%EC%9D%B4%EC%A4%91%20%EA%B3%84%EC%83%81")
        self.assertEqual(200, status)
        doc = json.loads(body)
        self.assertEqual("이중 계상", doc["query"])
        self.assertGreaterEqual(doc["total"], 1, "인코딩된 질의가 아무것도 못 찾았다")

    def test_a_raw_utf8_query_is_repaired_over_the_wire(self):
        """퍼센트 인코딩 없이 URL 에 한글을 그대로 넣는 경로. 손으로 curl 을 치면 여기다.

        함수 단위 테스트만으로는 부족하다 — 깨뜨리는 주체가 `http.server` 의 요청 라인
        디코딩이라 **실제로 소켓으로 보내봐야** 그 경로를 지난다.

        `urllib` 도 `http.client` 도 URL 을 ASCII 로 인코딩하려다 거부한다. 그래서 소켓에
        직접 쓴다 — curl 이 하는 것이 정확히 이것이고, 이 결함이 사는 곳도 여기다.
        """
        raw = "계상".encode("utf-8")                     # 퍼센트 인코딩 없이 날 바이트
        sock = socket.create_connection(("127.0.0.1", self.httpd.server_port), timeout=30)
        try:
            sock.sendall(b"GET /api/demo/search?q=" + raw + b" HTTP/1.1\r\n"
                         b"Host: localhost\r\nConnection: close\r\n\r\n")
            chunks = []
            while True:
                part = sock.recv(65536)
                if not part:
                    break
                chunks.append(part)
        finally:
            sock.close()
        head, _sep, body = b"".join(chunks).partition(b"\r\n\r\n")
        self.assertIn(b"200", head.split(b"\r\n")[0])
        doc = json.loads(body)
        self.assertEqual("계상", doc["query"],
                         "날 UTF-8 질의가 되살아나지 않았다 — 조용히 0건이 된다")
        self.assertGreaterEqual(doc["total"], 1)
        self.assertIn("퍼센트 인코딩", doc.get("note", ""),
                      "되살렸으면 되살렸다고 말해야 한다")

    def test_a_well_formed_post_creates_a_task(self):
        status, body, _h = self.call("POST", "/api/demo/tasks", {"title": "새 태스크"})
        self.assertEqual(201, status)
        self.assertEqual("새 태스크", json.loads(body)["title"])

    def test_an_empty_body_is_not_a_parse_error(self):
        """본문 없는 POST 는 흔하다. 그것까지 400 이면 정상 호출이 막힌다."""
        status, _b, _h = self.call("POST", "/api/demo/tasks", b"")
        self.assertIn(status, (200, 201))

    def test_missing_required_fields_are_400_not_500(self):
        status, body, _h = self.call("POST", "/api/projects", {"key": "x"})
        self.assertEqual(400, status)
        self.assertIn("required", json.loads(body)["error"])


class NoRequestEndsInSilenceTest(ServedOverHttpTest):
    """**둘 다 실제로 응답 없이 연결이 끊기던 것이다.** 이 파일이 찾아냈다."""

    def test_malformed_json_answers_400(self):
        status, body, _h = self.call("POST", "/api/demo/tasks", b"{not json")
        self.assertNotEqual("NO RESPONSE", status,
                            "깨진 JSON 에 응답 없이 연결을 끊었다 — 밖에서 보면 "
                            "서버가 죽은 것과 구별되지 않는다")
        self.assertEqual(400, status)
        self.assertIn("JSON", json.loads(body)["error"])

    def test_a_non_numeric_content_length_answers_400(self):
        status, body, _h = self.call("POST", "/api/demo/tasks", b"{}",
                                     {"Content-Length": "abc"})
        self.assertNotEqual("NO RESPONSE", status)
        self.assertEqual(400, status)
        self.assertIn("Content-Length", json.loads(body)["error"])

    def test_an_unexpected_failure_is_a_500_not_a_dropped_connection(self):
        """500 을 돌려주는 것이 조용히 끊는 것보다 낫다 — 관측 가능하기 때문이다."""
        original = server._get_context

        def boom(_dir):
            raise RuntimeError("의도한 폭발")

        server._get_context = boom
        # 서버는 스택을 찍는 것이 맞다(운영에서 필요하다). 테스트 출력만 조용히 한다.
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                status, body, _h = self.call("GET", "/api/demo/context")
            finally:
                server._get_context = original
        self.assertEqual(500, status)
        self.assertIn("의도한 폭발", json.loads(body)["error"])

    def test_an_error_response_body_is_actually_readable(self):
        """400 을 받고도 본문을 못 읽으면 400 을 안 준 것과 비슷하다.

        **읽지 않은 요청 본문이 소켓에 남은 채 닫으면 macOS 는 FIN 이 아니라 RST 를
        보내고, 이미 보낸 응답까지 함께 날아간다.** 클라이언트는 상태 코드를 받고도
        본문을 읽다 `ConnectionResetError` 를 맞는다.

        그래서 `_body()` 는 **파싱보다 먼저 본문을 읽고**, 길이를 모를 때만 짧은 시한
        안에 비워낸다.

        **인과는 증명하지 못했다.** 전체 스위트를 커버리지와 함께 돌릴 때 이 경로에서
        `ConnectionResetError` 가 두 번 났고 조치 뒤로는 안 나는데, **옛 코드로 되돌려도
        재현되지 않는다.** 그러니 이 테스트가 지키는 것은 "그 flaky 를 고쳤다"가 아니라
        **"오류 응답은 읽을 수 있어야 한다"는 성질**이다. 성질은 그 자체로 옳고,
        flaky 는 재발하면 그때 다시 본다.
        """
        for body, headers in ((b"{not json", None),
                              (b"{}", {"Content-Length": "abc"})):
            with self.subTest(body=body):
                status, raw, _h = self.call("POST", "/api/demo/tasks", body, headers)
                self.assertEqual(400, status)
                self.assertIn("error", json.loads(raw),
                              "400 은 왔는데 본문을 읽지 못했다 — RST 로 끊긴 것이다")

    def test_an_error_response_closes_the_connection(self):
        """본문을 읽다 실패했으면 그 본문이 소켓에 남는다.

        keep-alive 로 연결을 재사용하면 남은 바이트가 **다음 요청의 시작으로 읽히고**,
        클라이언트는 응답 본문을 읽는 도중 리셋을 맞는다. `Content-Length` 가 숫자가
        아닐 때는 얼마나 남았는지조차 몰라 비워낼 수 없다 — 닫는 것이 유일하게 옳다.

        **전체 스위트를 커버리지와 함께 돌릴 때만 재현됐다.** 느려진 타이밍이 드러낸
        것이지 느려서 생긴 문제가 아니다 — 빠를 때는 운으로 지나가고 있었다.
        간헐적으로 빨간 게이트는 곧 무시되므로, 원인을 찾을 때까지 flaky 로 두지 않았다.
        """
        for body, headers in ((b"{not json", None),
                              (b"{}", {"Content-Length": "abc"})):
            with self.subTest(body=body):
                status, _b, resp_headers = self.call("POST", "/api/demo/tasks",
                                                     body, headers)
                self.assertEqual(400, status)
                self.assertEqual("close", resp_headers.get("Connection"),
                                 "오류 응답이 연결을 닫지 않는다 — 안 읽은 본문이 "
                                 "다음 요청으로 새어 들어간다")

    def test_the_server_still_serves_after_a_failed_request(self):
        """한 요청이 터졌다고 다음 요청까지 죽으면 그건 다른 종류의 고장이다."""
        self.call("POST", "/api/demo/tasks", b"{broken")
        self.assertEqual(200, self.call("GET", "/api/demo/context")[0])


if __name__ == "__main__":
    unittest.main()
