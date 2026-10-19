import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from lmstui.api import LMStudioAPI, LmStudioApi, LMStudioClient
from lmstui.config import Config


class MockApiServerHandler(BaseHTTPRequestHandler):
    models_v0 = {
        "object": "list",
        "data": [
            {
                "id": "qwen38_23GB",
                "object": "model",
                "type": "llm",
                "state": "loaded",
                "max_context_length": 32768,
                "quantization": "Q4_K_M",
            },
            {
                "id": "llama3_8b",
                "object": "model",
                "type": "llm",
                "state": "loaded",
                "max_context_length": 8192,
                "quantization": "Q4_K_M",
            },
            {
                "id": "unloaded_model",
                "object": "model",
                "type": "llm",
                "state": "not-loaded",
            },
        ],
    }

    def do_GET(self):
        if self.path == "/api/v0/models":
            self._send_json(200, self.models_v0)
            return
        if self.path == "/api/v0/models/qwen38_23GB":
            self._send_json(200, self.models_v0["data"][0])
            return
        if self.path == "/v1/models":
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "qwen38_23GB", "object": "model"},
                        {"id": "llama3_8b", "object": "model"},
                    ],
                },
            )
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}

        if self.path in ("/v1/chat/completions", "/api/v0/chat/completions"):
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunk1 = {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": "Hello", "reasoning_content": "think"}}],
                }
                chunk2 = {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": " world!"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                        "completion_tokens_details": {"reasoning_tokens": 2},
                    },
                }
                self.wfile.write(f"data: {json.dumps(chunk1)}\n\n".encode("utf-8"))
                self.wfile.flush()
                self.wfile.write(f"data: {json.dumps(chunk2)}\n\n".encode("utf-8"))
                self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                return

            self._send_json(
                200,
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Hello world response"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 8,
                        "total_tokens": 20,
                        "completion_tokens_details": {"reasoning_tokens": 3},
                    },
                    "stats": {"tokens_per_second": 45.2, "time_to_first_token": 0.08},
                },
            )
            return

        if self.path in ("/v1/embeddings", "/api/v0/embeddings"):
            self._send_json(200, {"data": [{"embedding": [0.1, 0.2, 0.3]}]})
            return

        self._send_json(404, {"error": "not found"})

    def _send_json(self, code: int, obj: Any):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


@pytest.fixture()
def mock_api_server():
    httpd = HTTPServer(("127.0.0.1", 0), MockApiServerHandler)
    host, port = httpd.server_address
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()


def test_aliases_exist():
    assert LmStudioApi is LMStudioAPI
    assert LMStudioClient is LMStudioAPI


def test_api_ping(mock_api_server):
    cfg = Config(base_url_root=mock_api_server)
    api = LMStudioAPI(cfg)
    mode, detail = api.ping()
    assert mode == "online"
    assert "REST" in detail or "OpenAI" in detail


def test_api_list_models(mock_api_server):
    api = LMStudioAPI(mock_api_server)
    models = api.list_models()
    assert isinstance(models, dict)
    assert len(models["data"]) >= 2


def test_resolve_default_model_multiple_loaded(mock_api_server):
    api = LMStudioAPI(mock_api_server)
    # When no model is passed and multiple are loaded (llama3_8b and qwen38_23GB):
    # Sorting deterministically by ID puts 'llama3_8b' first
    model_id, warning, info = api.resolve_model(explicit_model=None)
    assert model_id == "llama3_8b"
    assert warning is not None
    assert "Multiple models loaded" in warning
    assert "qwen38_23GB" in warning
    assert info is not None


def test_resolve_default_model_explicit(mock_api_server):
    api = LMStudioAPI(mock_api_server)
    model_id, warning, info = api.resolve_model(explicit_model="qwen38_23GB")
    assert model_id == "qwen38_23GB"
    assert warning is None
    assert info["id"] == "qwen38_23GB"


def test_chat_completions_non_stream(mock_api_server):
    api = LMStudioAPI(mock_api_server)
    res = api.chat_completions(
        model="qwen38_23GB",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.7,
        max_tokens=100,
        stream=False,
    )
    assert isinstance(res, dict)
    assert res["choices"][0]["message"]["content"] == "Hello world response"
    assert res["usage"]["total_tokens"] == 20


def test_chat_completions_stream(mock_api_server):
    api = LMStudioAPI(mock_api_server)
    chunks = list(
        api.chat_completions(
            model="qwen38_23GB",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.7,
            max_tokens=100,
            stream=True,
        )
    )
    assert len(chunks) == 2
    assert chunks[0]["choices"][0]["delta"]["content"] == "Hello"
    assert chunks[1]["choices"][0]["delta"]["content"] == " world!"
