"""Installed OpenCode 1.19 / opencode-mcp 3.0 schemas, offline transport."""

import asyncio
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from agent_benchmark.bridge import OpenCodeBridge, parse_observation
from agent_benchmark.lifecycle import WorkerHandle

HANDLE = WorkerHandle("job-1", "session-1", "user-1", Path("C:/owned/trial-1"))


def messages():
    return [
        {"info": {"id": "user-1", "sessionID": "session-1", "role": "user", "time": {"created": 1}}, "parts": []},
        {"info": {"id": "assistant-1", "sessionID": "session-1", "parentID": "user-1", "role": "assistant",
                  "time": {"created": 2, "completed": 3}, "finish": "stop"},
         "parts": [{"type": "text", "text": "done"}]},
    ]


def test_fresh_empty_status_map_means_idle_only_with_exact_finished_turn():
    assert parse_observation(HANDLE, {}, messages()).confirms_termination
    assert not parse_observation(HANDLE, {}, []).confirms_termination


@pytest.mark.parametrize("state", ["busy", "retry", "running"])
def test_live_busy_session_beats_finished_assistant_and_cached_job(state):
    assert not parse_observation(HANDLE, {"session-1": {"type": state}}, messages()).confirms_termination


def test_incomplete_tool_and_tool_call_step_are_not_termination():
    data = messages()
    data[1]["parts"].append({"type": "tool", "state": {"status": "running"}})
    assert not parse_observation(HANDLE, {}, data).confirms_termination
    data = messages()
    data[1]["info"]["finish"] = "tool-calls"
    assert not parse_observation(HANDLE, {}, data).confirms_termination
    data[1]["info"]["structured"] = {"outcome": "completed"}
    assert parse_observation(HANDLE, {}, data).confirms_termination


def test_newer_turn_or_wrong_session_never_satisfies_old_job():
    data = messages()
    data.append({"info": {"id": "user-2", "role": "user", "sessionID": "session-1", "time": {"created": 4}}, "parts": []})
    assert not parse_observation(HANDLE, {}, data).confirms_termination
    data = messages()
    data[1]["info"]["sessionID"] = "another-session"
    assert not parse_observation(HANDLE, {}, data).confirms_termination


def test_aborted_assistant_still_needs_idle_and_finished_tools():
    data = messages()
    data[1]["info"]["error"] = {"name": "MessageAbortedError"}
    assert parse_observation(HANDLE, {}, data).job_status == "cancelled"
    assert not parse_observation(HANDLE, {"session-1": "busy"}, data).confirms_termination


@pytest.mark.parametrize("statuses,history", [(None, messages()), ({}, None), ([], messages()), ({}, [{"info": {}}])])
def test_malformed_raw_evidence_fails_closed(statuses, history):
    assert not parse_observation(HANDLE, statuses, history).confirms_termination


def test_dispatch_uses_fresh_session_and_retains_bridge_identifiers(tmp_path):
    received = []

    async def call_tool(name, args):
        received.append((name, args))
        return {"status": "accepted", "jobId": "job-1", "sessionId": "session-1", "messageId": "user-1"}

    async def run():
        async with httpx.AsyncClient() as http:
            bridge = OpenCodeBridge(call_tool, http)
            handle = await bridge.dispatch(tmp_path, "work", provider="lmstudio", model="explicit-model", agent="local-worker")
            assert handle.workspace == tmp_path
            assert handle.job_id == "job-1"
            assert "sessionId" not in received[0][1]
            assert received[0][1]["modelID"] == "explicit-model"

    asyncio.run(run())


def test_reconciliation_reads_remote_session_not_terminal_job_cache():
    requests = []

    def remote(request):
        requests.append(request.url.path)
        if request.url.path == "/session/status":
            return httpx.Response(200, json={"session-1": {"type": "busy"}})
        if request.url.path.endswith("/message"):
            return httpx.Response(200, json=messages())
        return httpx.Response(200, json={"id": "session-1", "directory": str(HANDLE.workspace)})

    async def no_tool(name, args):
        pytest.fail("Reconciliation must bypass cached MCP jobs")

    async def run():
        async with httpx.AsyncClient(base_url="http://localhost:4096", transport=httpx.MockTransport(remote)) as http:
            bridge = OpenCodeBridge(no_tool, http)
            assert not (await bridge.observe(HANDLE)).confirms_termination
            assert "/session/status" in requests
            assert "/session/session-1/message" in requests

    asyncio.run(run())


def test_abort_refuses_newer_turn_before_calling_session_wide_cancel():
    history = deepcopy(messages())
    history.append({"info": {"id": "user-2", "role": "user", "sessionID": "session-1", "time": {"created": 5}}})

    def remote(request):
        return httpx.Response(200, json=history)

    async def no_tool(name, args):
        pytest.fail("Newer session work must never be cancelled")

    async def run():
        async with httpx.AsyncClient(base_url="http://localhost:4096", transport=httpx.MockTransport(remote)) as http:
            with pytest.raises(RuntimeError, match="newer|ownership"):
                await OpenCodeBridge(no_tool, http).cancel(HANDLE)

    asyncio.run(run())
