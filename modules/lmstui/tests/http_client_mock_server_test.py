import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lmstui.http_client import HttpClient


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/api/v0/models":
            self._send(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "m1",
                            "object": "model",
                            "state": "loaded",
                            "type": "llm",
                            "max_context_length": 4096,
                            "quantization": "Q4_K_M",
                        }
                    ],
                },
            )
            return
        if self.path == "/v1/models":
            self._send(
                200,
                {"object": "list", "data": [{"id": "m1", "object": "model", "owned_by": "org"}]},
            )
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/v0/chat/completions":
            self._send(
                200,
                {
                    "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "stats": {"tokens_per_second": 10.0, "time_to_first_token": 0.1},
                },
            )
            return
        self._send(404, {"error": "not found"})

    def log_message(self, format, *args):
        return


@pytest.fixture()
def mock_server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    host, port = httpd.server_address
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()


def test_http_client_get_json(mock_server):
    c = HttpClient(timeout_seconds=5.0)
    data = c.get_json(f"{mock_server}/api/v0/models")
    assert data["object"] == "list"
    assert data["data"][0]["id"] == "m1"
