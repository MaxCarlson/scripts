import argparse
import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from lmstui.cli import (
    build_parser_lmc,
    build_parser_lmst,
    build_parser_lmstui,
    main_lmc,
    main_lmst,
    main_lmstui,
)


class MockCliServerHandler(BaseHTTPRequestHandler):
    models_data = {
        "object": "list",
        "data": [
            {
                "id": "qwen38_23GB",
                "object": "model",
                "type": "llm",
                "state": "loaded",
                "max_context_length": 32768,
            },
            {
                "id": "llama3_8b",
                "object": "model",
                "type": "llm",
                "state": "loaded",
                "max_context_length": 8192,
            },
        ],
    }

    def do_GET(self):
        if self.path in ("/api/v0/models", "/v1/models"):
            self._send(200, self.models_data)
            return
        if self.path == "/api/v0/models/qwen38_23GB":
            self._send(200, self.models_data["data"][0])
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length > 0 else {}

        if self.path in ("/v1/chat/completions", "/api/v0/chat/completions"):
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunk = {
                    "choices": [{"delta": {"content": "Streamed answer"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                return

            self._send(
                200,
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "choices": [{"message": {"role": "assistant", "content": "The answer is 42."}}],
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 6,
                        "total_tokens": 14,
                        "completion_tokens_details": {"reasoning_tokens": 2},
                    },
                    "stats": {"tokens_per_second": 50.0, "time_to_first_token": 0.05},
                },
            )
            return

        self._send(404, {"error": "not found"})

    def _send(self, code: int, obj):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


@pytest.fixture()
def mock_cli_server():
    httpd = HTTPServer(("127.0.0.1", 0), MockCliServerHandler)
    host, port = httpd.server_address
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()


def test_parsers_help():
    p_lmst = build_parser_lmst()
    assert p_lmst.prog == "lmst"

    p_lmstui = build_parser_lmstui()
    assert p_lmstui.prog == "lmstui"


def test_all_lmst_args_have_short_and_long():
    parser = build_parser_lmst()
    # Check top-level optional actions
    for action in parser._actions:
        if action.option_strings:
            shorts = [opt for opt in action.option_strings if len(opt) == 2 and opt.startswith("-")]
            longs = [opt for opt in action.option_strings if opt.startswith("--")]
            assert len(shorts) >= 1, f"Missing short flag for {action.option_strings}"
            assert len(longs) >= 1, f"Missing long flag for {action.option_strings}"

    # Check subcommands
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subp in action.choices.items():
                for sub_action in subp._actions:
                    if sub_action.option_strings:
                        shorts = [opt for opt in sub_action.option_strings if len(opt) == 2 and opt.startswith("-")]
                        longs = [opt for opt in sub_action.option_strings if opt.startswith("--")]
                        assert len(shorts) >= 1, f"Missing short flag for subcommand '{name}': {sub_action.option_strings}"
                        assert len(longs) >= 1, f"Missing long flag for subcommand '{name}': {sub_action.option_strings}"


def test_lmst_models(mock_cli_server, capsys):
    code = main_lmst(["--base-url", mock_cli_server, "models"])
    assert code == 0
    captured = capsys.readouterr()
    assert "qwen38_23GB" in captured.out
    assert "llama3_8b" in captured.out


def test_lmst_models_json(mock_cli_server, capsys):
    code = main_lmst(["--base-url", mock_cli_server, "models", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "data" in data


def test_lmst_chat_oneshot_prompt(mock_cli_server, capsys):
    code = main_lmst([
        "--base-url", mock_cli_server,
        "chat",
        "-m", "qwen38_23GB",
        "-p", "What is the answer?",
        "-N",  # non-streaming
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out


def test_lmst_chat_stats_to_stderr(mock_cli_server, capsys):
    code = main_lmst([
        "--base-url", mock_cli_server,
        "chat",
        "-m", "qwen38_23GB",
        "-p", "test prompt",
        "-N",
        "-a",  # stats
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out
    assert "[stats]" in captured.err
    assert "Prompt tokens:     8" in captured.err
    assert "Reasoning tokens:  2" in captured.err
    assert "Total tokens:      14" in captured.err


def test_lmst_chat_json_output(mock_cli_server, capsys):
    code = main_lmst([
        "--base-url", mock_cli_server,
        "chat",
        "-m", "qwen38_23GB",
        "-p", "test",
        "-j",
    ])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["choices"][0]["message"]["content"] == "The answer is 42."


def test_lmst_chat_auto_select_model_warning(mock_cli_server, capsys):
    # When -m is omitted, auto selects llama3_8b (first sorted) and prints warning to stderr
    code = main_lmst([
        "--base-url", mock_cli_server,
        "chat",
        "-p", "test",
        "-N",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out
    assert "Warning: Multiple models loaded" in captured.err
    assert "llama3_8b" in captured.err


def test_lmst_chat_silent_suppresses_stderr(mock_cli_server, capsys):
    code = main_lmst([
        "--base-url", mock_cli_server,
        "chat",
        "-p", "test",
        "-N",
        "-S",  # silent
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out
    assert captured.err == ""


def test_lmst_chat_streaming(mock_cli_server, capsys):
    code = main_lmst([
        "--base-url", mock_cli_server,
        "chat",
        "-m", "qwen38_23GB",
        "-p", "stream test",
        "-r",  # stream
        "-S",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "Streamed answer" in captured.out


def test_lmst_chat_stdin_piping(mock_cli_server, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("piped prompt text"))
    code = main_lmst([
        "--base-url", mock_cli_server,
        "chat",
        "-m", "qwen38_23GB",
        "-N",
        "-S",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out


def test_lmst_defaults_management(tmp_path: Path, capsys, monkeypatch):
    test_defaults_file = tmp_path / "defaults.json"
    import lmstui.defaults as d_mod
    monkeypatch.setattr(d_mod, "DEFAULT_FILEPATH", test_defaults_file)

    # Set global default
    code = main_lmst(["chat", "-D", "temperature=0.3", "-D", "stream=false"])
    assert code == 0

    # Show defaults
    code = main_lmst(["chat", "-d"])
    assert code == 0
    captured = capsys.readouterr()
    assert "temperature: 0.3" in captured.out

    # Set per-model default
    code = main_lmst(["chat", "-m", "qwen38_23GB", "-M", "-D", "temperature=0.1"])
    assert code == 0

    code = main_lmst(["chat", "-d"])
    assert code == 0
    captured = capsys.readouterr()
    assert "qwen38_23GB" in captured.out
    assert "temperature: 0.1" in captured.out

    # Clear defaults
    code = main_lmst(["chat", "-C"])
    assert code == 0
    code = main_lmst(["chat", "-d"])
    captured = capsys.readouterr()
    assert "No custom defaults configured." in captured.out or "{}" in captured.out


def test_lmstui_backward_compat(mock_cli_server, capsys):
    # Test lmstui server ping
    code = main_lmstui(["--base-url", mock_cli_server, "server", "ping"])
    assert code == 0
    captured = capsys.readouterr()
    assert "online" in captured.out

    # Test lmstui server endpoints
    code = main_lmstui(["--base-url", mock_cli_server, "server", "endpoints"])
    assert code == 0
    captured = capsys.readouterr()
    assert "/v1/chat/completions" in captured.out

    # Test lmstui run
    code = main_lmstui([
        "--base-url", mock_cli_server,
        "run",
        "-m", "qwen38_23GB",
        "-p", "test",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out


def test_all_lmc_args_have_short_and_long():
    parser = build_parser_lmc()
    assert parser.prog == "lmc"
    for action in parser._actions:
        if action.option_strings:
            shorts = [opt for opt in action.option_strings if len(opt) == 2 and opt.startswith("-")]
            longs = [opt for opt in action.option_strings if opt.startswith("--")]
            assert len(shorts) >= 1, f"Missing short flag for {action.option_strings}"
            assert len(longs) >= 1, f"Missing long flag for {action.option_strings}"


def test_lmc_oneshot(mock_cli_server, capsys):
    code = main_lmc([
        "--base-url", mock_cli_server,
        "-m", "qwen38_23GB",
        "-p", "What is the answer?",
        "-N",
        "-S",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out


def test_lmc_auto_model(mock_cli_server, capsys):
    # With multiple loaded models and no -m, lmc resolves deterministically and warns on stderr
    code = main_lmc([
        "--base-url", mock_cli_server,
        "-p", "What is the answer?",
        "-N",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out
    assert "Multiple models loaded" in captured.err
    assert "Using default model 'llama3_8b'" in captured.err


def test_lmc_positional_prompt(mock_cli_server, capsys):
    # Test typing text directly after lmc without -p
    code = main_lmc([
        "--base-url", mock_cli_server,
        "-m", "qwen38_23GB",
        "-N",
        "-S",
        "hello", "world", "what", "is", "the", "answer?",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out


def test_lmst_chat_positional_prompt(mock_cli_server, capsys):
    # Test typing text directly after lmst chat without -p
    code = main_lmst([
        "--base-url", mock_cli_server,
        "chat",
        "-m", "qwen38_23GB",
        "-N",
        "-S",
        "hello", "world",
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "The answer is 42." in captured.out

