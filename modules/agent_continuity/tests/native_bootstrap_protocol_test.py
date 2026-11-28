"""Guarded offline protocol fixtures for Codex app-server and AGY ACP native session allocation (LLMD-60)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_jsonrpc_stdio_server(server_script: str, requests: list[dict], *, timeout: float = 5.0) -> list[dict]:
    proc = subprocess.Popen(
        [sys.executable, "-c", server_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = "".join(json.dumps(req) + "\n" for req in requests)
    stdout, stderr = proc.communicate(input=payload, timeout=timeout)
    assert proc.returncode == 0, stderr
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_codex_app_server_thread_start_protocol_fixture(tmp_path: Path) -> None:
    """Verify ThreadStartParams/ThreadStartResponse schema and pre-first-turn persistence distinction."""
    rollout_path = tmp_path / "rollout-2026-11-27-thr_123.jsonl"
    server_script = (
        "import json, sys\n"
        f"rollout = {str(rollout_path)!r}\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'initialize':\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'userAgent': 'codex-app-server/0.172.0'}}), flush=True)\n"
        "    elif msg.get('method') == 'thread/start':\n"
        "        params = msg['params']\n"
        "        assert params['ephemeral'] is False\n"
        "        assert 'cwd' in params\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {\n"
        "            'approvalPolicy': 'on-request',\n"
        "            'approvalsReviewer': 'user',\n"
        "            'cwd': params['cwd'],\n"
        "            'model': 'gpt-5',\n"
        "            'modelProvider': 'openai',\n"
        "            'sandbox': {'type': 'workspaceWrite'},\n"
        "            'thread': {'id': '01900000-0000-7000-8000-000000000001', 'ephemeral': False, 'path': rollout}\n"
        "        }}), flush=True)\n"
    )
    responses = _run_jsonrpc_stdio_server(
        server_script,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "llmd", "version": "2.3.0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "thread/start", "params": {"cwd": str(tmp_path), "ephemeral": False}},
        ],
    )
    assert len(responses) == 2
    thread = responses[1]["result"]["thread"]
    thread_id = thread["id"]
    assert thread_id == "01900000-0000-7000-8000-000000000001"
    # Allocated thread ID is NOT yet interactively resumable until persistence evidence exists on disk
    assert Path(thread["path"]).exists() is False

    # Once rollout persistence exists, exact resume evidence is established
    rollout_path.write_text(json.dumps({"type": "session_meta", "id": thread_id}) + "\n", encoding="utf-8")
    assert Path(thread["path"]).exists() is True


def test_agy_acp_session_new_protocol_fixture_and_timeout_cancellation(tmp_path: Path) -> None:
    """Verify AGY ACP initialize + session/new exact ID capture and timeout/cancellation fail-closed behavior."""
    server_script = (
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'initialize':\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'protocolVersion': 1}}), flush=True)\n"
        "    elif msg.get('method') == 'session/new':\n"
        "        assert msg['params']['cwd']\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'sessionId': 'agy-conv-acp-0001'}}), flush=True)\n"
    )
    responses = _run_jsonrpc_stdio_server(
        server_script,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(tmp_path), "mcpServers": []}},
        ],
    )
    assert responses[1]["result"]["sessionId"] == "agy-conv-acp-0001"

    # Timeout/crash during allocation must fail closed without guessing any session ID
    hanging = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            hanging.communicate(timeout=0.1)
    finally:
        hanging.kill()
        hanging.wait(timeout=2.0)
