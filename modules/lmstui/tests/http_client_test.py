import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lmstui.http_client import HttpClient, HttpError, now_seconds


class MockServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return
        if self.path == "/error":
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "internal error"}')
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/echo":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: {\"chunk\": 1}\n\n")
            self.wfile.flush()
            self.wfile.write(b"data: {\"chunk\": 2}\n\n")
            self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


@pytest.fixture()
def mock_server():
    httpd = HTTPServer(("127.0.0.1", 0), MockServerHandler)
    host, port = httpd.server_address
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()


def test_now_seconds_returns_recent_timestamp():
    t0 = time.time()
    val = now_seconds()
    t1 = time.time()
    assert isinstance(val, float)
    assert t0 <= val <= t1


def test_http_client_get_json(mock_server):
    client = HttpClient(timeout_seconds=5.0)
    data = client.get_json(f"{mock_server}/health")
    assert data == {"status": "ok"}


def test_http_client_post_json(mock_server):
    client = HttpClient(timeout_seconds=5.0)
    data = client.post_json(f"{mock_server}/echo", {"message": "hello"})
    assert data == {"message": "hello"}


def test_http_client_stream_lines(mock_server):
    client = HttpClient(timeout_seconds=5.0)
    lines = list(client.stream_lines("POST", f"{mock_server}/stream", json_body={"test": True}))
    assert "data: {\"chunk\": 1}" in lines
    assert "data: [DONE]" in lines


def test_http_client_error_500(mock_server):
    client = HttpClient(timeout_seconds=5.0)
    with pytest.raises(HttpError) as exc_info:
        client.get_json(f"{mock_server}/error")
    assert exc_info.value.status == 500


def test_http_client_connection_error():
    # Unreachable port
    client = HttpClient(timeout_seconds=0.5)
    with pytest.raises(HttpError) as exc_info:
        client.get_json("http://127.0.0.1:59999/health")
    assert "Network error" in str(exc_info.value)
