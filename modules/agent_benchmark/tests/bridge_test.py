"""Installed OpenCode 1.19 / opencode-mcp 3.0 schemas, offline transport."""

import asyncio
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from agent_benchmark.bridge import OpenCodeBridge, parse_observation
from bridge_isolation_test import PROJECT, prepare as prepare_bridge, remote as project_remote
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
    data[0]["info"]["format"] = {"type": "json_schema"}
    data[1]["parts"].append({"type": "tool", "tool": "StructuredOutput", "state": {"status": "completed"}})
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


def test_provider_error_name_and_message_are_preserved_as_diagnostic():
    data = messages()
    data[1]["info"]["error"] = {"name": "ProviderError", "data": {"message": "context window exceeded"}}
    observation = parse_observation(HANDLE, {}, data)
    assert observation.job_status == "failed"
    assert observation.diagnostic == "ProviderError: context window exceeded"


def test_provider_http_rejection_and_generation_limit_are_distinguishable():
    data = messages()
    data[1]["info"]["error"] = {"name": "APIError", "data": {
        "message": "Request rejected", "statusCode": 400, "responseBody": "context window exceeded",
        "headers": {"Authorization": "secret-should-not-be-copied"},
    }}
    observation = parse_observation(HANDLE, {}, data)
    assert "statusCode=400" in observation.diagnostic
    assert "context window exceeded" in observation.diagnostic
    assert "secret" not in observation.diagnostic
    data = messages()
    data[1]["info"]["finish"] = "length"
    observation = parse_observation(HANDLE, {}, data)
    assert observation.job_status == "completed"
    assert "generation limit reached" in observation.diagnostic
    assert "context overflow not established" in observation.diagnostic


@pytest.mark.parametrize("statuses,history", [(None, messages()), ({}, None), ([], messages()), ({}, [{"info": {}}])])
def test_malformed_raw_evidence_fails_closed(statuses, history):
    assert not parse_observation(HANDLE, statuses, history).confirms_termination


def test_dispatch_uses_fresh_session_and_retains_bridge_identifiers(tmp_path):
    received = []

    async def call_tool(name, args):
        received.append((name, args))
        return {"status": "accepted", "jobId": "job-1", "sessionId": "session-1", "messageId": "user-1"}

    async def run():
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(project_remote(tmp_path))) as http:
            bridge = OpenCodeBridge(call_tool, http)
            await prepare_bridge(bridge, tmp_path)
            handle = await bridge.dispatch(tmp_path, "work", provider="lmstudio", model="explicit-model", agent="local-worker")
            assert handle.workspace == tmp_path
            assert handle.job_id == "job-1"
            assert received[0][1]["sessionId"] == "session-1"
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


def test_new_submission_does_not_reuse_previous_transcript(tmp_path):
    async def uncertain(name, args):
        raise RuntimeError("lost submit response")

    async def run():
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(project_remote(tmp_path))) as http:
            bridge = OpenCodeBridge(uncertain, http)
            await prepare_bridge(bridge, tmp_path)
            bridge.last_history = messages()
            from agent_benchmark.bridge import SubmissionUncertain
            with pytest.raises(SubmissionUncertain):
                await bridge.dispatch(tmp_path, "next", provider="lmstudio", model="test", agent="local-worker")
            assert bridge.last_history == []

    asyncio.run(run())


def test_read_only_preflight_requires_connected_explicit_model_and_role(tmp_path):
    connected = ["lmstudio"]

    def remote(request):
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"version": "1.19.3"})
        if request.url.path == "/provider":
            return httpx.Response(200, json={"all": [{"id": "lmstudio", "models": {"model-a": {}}}], "connected": connected})
        if request.url.path in ("/path", "/project/current"):
            return project_remote(tmp_path)(request)
        return httpx.Response(200, json=[{"name": "local-worker", "permission": [{"permission": "task", "action": "deny"}]}])

    async def unused(name, args):
        pytest.fail("Preflight must not dispatch or configure anything")

    async def run():
        async with httpx.AsyncClient(base_url="http://localhost:4096", transport=httpx.MockTransport(remote)) as http:
            bridge = OpenCodeBridge(unused, http)
            facts = await bridge.preflight(tmp_path, project_id=PROJECT, provider="lmstudio", model="model-a", agent="local-worker")
            assert facts["model"] == "model-a" and facts["opencode_version"] == "1.19.3"
            with pytest.raises(ValueError, match="Effective model IDs: model-a"):
                await bridge.preflight(tmp_path, project_id=PROJECT, provider="lmstudio", model="missing", agent="local-worker")
            connected.clear()
            with pytest.raises(ValueError, match="OpenCode provider 'lmstudio' is not connected"):
                await bridge.preflight(tmp_path, project_id=PROJECT, provider="lmstudio", model="model-a", agent="local-worker")
            connected.append("lmstudio")
            with pytest.raises(ValueError):
                await bridge.preflight(tmp_path, project_id=PROJECT, provider="cloud", model="model-a", agent="local-worker")
            with pytest.raises(ValueError):
                await bridge.preflight(tmp_path, project_id=PROJECT, provider="lmstudio", model="model-a", agent="unknown")

    asyncio.run(run())


def test_bridge_error_retains_any_durable_identifiers(tmp_path):
    from agent_benchmark.bridge import SubmissionUncertain
    receipt = {"status": "unknown", "jobId": "durable-job", "sessionId": "known-session", "messageId": "known-turn"}

    async def failed(name, args):
        raise SubmissionUncertain(receipt)

    async def run():
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(project_remote(tmp_path))) as http:
            bridge = OpenCodeBridge(failed, http)
            await prepare_bridge(bridge, tmp_path)
            with pytest.raises(SubmissionUncertain) as error:
                await bridge.dispatch(tmp_path, "work", provider="lmstudio", model="model-a", agent="local-worker")
            assert error.value.receipt["jobId"] == "durable-job"
            assert bridge.last_receipt["messageId"] == "known-turn"

    asyncio.run(run())


def test_intermediate_tool_call_with_null_structured_does_not_confirm_termination():
    data = messages()
    data[1]["info"]["finish"] = "tool-calls"
    data[1]["info"]["structured"] = None
    assert not parse_observation(HANDLE, {}, data).confirms_termination


def test_aborted_assistant_without_completed_time_confirms_when_idle_and_no_running_tools():
    data = messages()
    data[1]["info"]["error"] = {"name": "MessageAbortedError", "message": "Turn aborted"}
    data[1]["info"]["time"] = {"created": 2}  # No "completed" timestamp
    obs = parse_observation(HANDLE, {}, data)
    assert obs.job_status == "cancelled"
    assert obs.turn_finished
    assert obs.confirms_termination


def test_null_and_malformed_time_in_message_history_does_not_crash():
    data = [
        {"info": {"id": "user-1", "sessionID": "session-1", "role": "user", "time": None}, "parts": []},
        {"info": {"id": "assistant-1", "sessionID": "session-1", "parentID": "user-1", "role": "assistant",
                  "time": {"created": 2, "completed": 3}, "finish": "stop"}, "parts": []},
    ]
    obs = parse_observation(HANDLE, {}, data)
    assert obs.confirms_termination


def test_connected_bridge_rejects_non_positive_or_non_finite_timeout():
    from agent_benchmark.bridge import connected_bridge

    async def run():
        with pytest.raises(ValueError, match="Request timeout must be finite and positive"):
            async with connected_bridge(request_seconds=0):
                pass
        with pytest.raises(ValueError, match="Request timeout must be finite and positive"):
            async with connected_bridge(request_seconds=-1):
                pass
        with pytest.raises(ValueError, match="Request timeout must be finite and positive"):
            async with connected_bridge(request_seconds=float("inf")):
                pass

    asyncio.run(run())


def test_connected_bridge_missing_npx_raises_filenotfounderror(monkeypatch):
    import shutil
    from agent_benchmark.bridge import connected_bridge

    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    async def run():
        with pytest.raises(FileNotFoundError, match="npx is unavailable"):
            async with connected_bridge():
                pass

    asyncio.run(run())


def test_connected_bridge_fails_if_health_check_fails(monkeypatch):
    import shutil
    from agent_benchmark.bridge import connected_bridge

    monkeypatch.setattr(shutil, "which", lambda cmd: "mock-npx")

    def mock_transport_handler(request):
        if request.url.path == "/global/health":
            return httpx.Response(500, json={"error": "service down"})
        return httpx.Response(200)

    original_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_transport_handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_client)

    async def run():
        with pytest.raises(httpx.HTTPStatusError):
            async with connected_bridge():
                pass

    asyncio.run(run())


def test_connected_bridge_tool_error_preserves_content_and_masks_password(monkeypatch):
    from contextlib import asynccontextmanager
    import shutil
    from unittest.mock import AsyncMock, MagicMock
    from agent_benchmark.bridge import SubmissionUncertain, connected_bridge

    monkeypatch.setattr(shutil, "which", lambda cmd: "mock-npx")
    monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", "super_secret_token_123")

    def mock_transport_handler(request):
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"version": "1.19.3"})
        return httpx.Response(200)

    original_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_transport_handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_client)

    mock_result = MagicMock()
    mock_result.isError = True
    mock_result.structuredContent = None
    text_content = MagicMock()
    text_content.type = "text"
    text_content.text = "Error: authentication failed with super_secret_token_123 in request"
    mock_result.content = [text_content]

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def mock_stdio_client(params):
        yield (MagicMock(), MagicMock())

    @asynccontextmanager
    async def mock_client_session(read, write, read_timeout_seconds=None):
        yield mock_session

    import mcp
    import mcp.client.stdio

    monkeypatch.setattr(mcp.client.stdio, "stdio_client", mock_stdio_client)
    monkeypatch.setattr(mcp, "ClientSession", mock_client_session)

    async def run():
        async with connected_bridge() as bridge:
            with pytest.raises(SubmissionUncertain) as exc_info:
                await bridge.call_tool("opencode_fire", {})
            receipt = exc_info.value.receipt
            assert "error" in receipt
            assert "super_secret_token_123" not in receipt["error"]
            assert "***" in receipt["error"]
            assert receipt["error"] == "Error: authentication failed with *** in request"

    asyncio.run(run())



def test_nonnull_structured_on_unproven_tool_step_is_not_cleanup_evidence():
    data = messages()
    data[1]["info"].update(finish="tool-calls", structured={"answer": "looks done"})
    assert not parse_observation(HANDLE, {}, data).confirms_termination


def test_structured_output_terminal_step_requires_matched_format_and_completed_tool():
    data = messages()
    data[0]["info"]["format"] = {"type": "json_schema", "schema": {"type": "object"}}
    data[1]["info"].update(finish="tool-calls", structured={"answer": "done"})
    data[1]["parts"].append({"type": "tool", "tool": "StructuredOutput", "state": {"status": "running"}})
    assert not parse_observation(HANDLE, {}, data).confirms_termination
    data[1]["parts"][-1]["state"]["status"] = "completed"
    assert parse_observation(HANDLE, {}, data).confirms_termination


def test_multiple_assistants_with_missing_ordering_cannot_confirm_old_terminal_step():
    data = messages()
    data.append({"info": {"id": "assistant-2", "sessionID": "session-1", "parentID": "user-1",
                          "role": "assistant", "time": None}, "parts": []})
    assert not parse_observation(HANDLE, {}, data).confirms_termination


@pytest.mark.parametrize("rules", [[], [{"permission": "*", "pattern": "*", "action": "allow"}]])
def test_file_role_readiness_failure_is_actionable_before_session_creation(tmp_path, rules):
    from agent_benchmark.bridge import ModelConfigurationError
    from agent_benchmark.tool_profile import FILE_AGENT, FILE_PROMPT

    requests = []

    def remote_profile(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"version": "1.19.3"})
        if request.url.path == "/provider":
            return httpx.Response(200, json={"all": [{"id": "lmstudio", "models": {"model-a": {}}}],
                                             "connected": ["lmstudio"]})
        if request.url.path == "/path":
            return httpx.Response(200, json={})
        if request.url.path == "/agent":
            return httpx.Response(200, json=[{"name": FILE_AGENT, "mode": "primary", "prompt": FILE_PROMPT, "permission": rules}])
        pytest.fail("Invalid effective profile must fail before project/session operations")

    async def unused(*args):
        pytest.fail("Invalid profile must never submit inference")

    async def run():
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(remote_profile)) as http:
            bridge = OpenCodeBridge(unused, http)
            with pytest.raises(ModelConfigurationError, match="file-tools-v1"):
                await bridge.preflight(tmp_path, project_id=PROJECT, provider="lmstudio", model="model-a", agent=FILE_AGENT)

    asyncio.run(run())
    assert not any(method == "POST" for method, _ in requests)


def test_retrieval_role_preflight_preserves_default_deny_and_named_tools(tmp_path):
    from agent_benchmark.tool_profile import RETRIEVAL_AGENT, RETRIEVAL_PROMPT

    requests = []
    rules = [
        {"permission": "*", "pattern": "*", "action": "deny"},
        *({"permission": name, "pattern": "*", "action": "allow"}
          for name in ("read", "edit", "code_locate", "code_context")),
    ]

    def remote(request):
        requests.append(request.method)
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"version": "1.19.3"})
        if request.url.path == "/provider":
            return httpx.Response(200, json={"all": [{"id": "lmstudio", "models": {"model-a": {}}}],
                                             "connected": ["lmstudio"]})
        if request.url.path == "/path":
            return httpx.Response(200, json={"directory": str(tmp_path), "worktree": str(tmp_path)})
        if request.url.path == "/agent":
            return httpx.Response(200, json=[{"name": RETRIEVAL_AGENT, "mode": "primary",
                                              "prompt": RETRIEVAL_PROMPT, "permission": rules}])
        return project_remote(tmp_path)(request)

    async def unused(*args):
        pytest.fail("Read-only preflight must not dispatch")

    async def run():
        async with httpx.AsyncClient(base_url="http://localhost:4096", transport=httpx.MockTransport(remote)) as http:
            bridge = OpenCodeBridge(unused, http)
            facts = await bridge.preflight(tmp_path, project_id=PROJECT, provider="lmstudio",
                                           model="model-a", agent=RETRIEVAL_AGENT)
            assert facts["agent"] == RETRIEVAL_AGENT
            assert facts["permissions"] == rules

    asyncio.run(run())
    assert "POST" not in requests


@pytest.mark.parametrize("grant_shell, omit_tool, expected_error", [
    (True, None, "bash"),
    (False, "code_map", "code_map"),
])
def test_structural_role_preflight_requires_named_retrieval_tools_and_rejects_shell(
    tmp_path, grant_shell, omit_tool, expected_error
):
    from agent_benchmark.bridge import ModelConfigurationError
    from agent_benchmark.tool_profile import STRUCTURAL_AGENT, STRUCTURAL_PROMPT

    requests = []
    rules = [
        {"permission": "*", "pattern": "*", "action": "deny"},
        *({"permission": name, "pattern": "*", "action": "allow"}
          for name in ("read", "edit", "code_locate", "code_context", "code_symbols", "code_map")
          if name != omit_tool),
    ]
    if grant_shell:
        rules.append({"permission": "bash", "pattern": "*", "action": "allow"})

    def remote(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"version": "1.19.3"})
        if request.url.path == "/provider":
            return httpx.Response(200, json={"all": [{"id": "lmstudio", "models": {"model-a": {}}}],
                                             "connected": ["lmstudio"]})
        if request.url.path == "/path":
            return httpx.Response(200, json={"directory": str(tmp_path), "worktree": str(tmp_path)})
        if request.url.path == "/agent":
            return httpx.Response(200, json=[{"name": STRUCTURAL_AGENT, "mode": "primary",
                                              "prompt": STRUCTURAL_PROMPT, "permission": rules}])
        return project_remote(tmp_path)(request)

    async def unused(*args):
        pytest.fail("Invalid structural preflight must never submit inference")

    async def run():
        async with httpx.AsyncClient(base_url="http://localhost:4096", transport=httpx.MockTransport(remote)) as http:
            bridge = OpenCodeBridge(unused, http)
            with pytest.raises(ModelConfigurationError, match=expected_error):
                await bridge.preflight(tmp_path, project_id=PROJECT, provider="lmstudio", model="model-a",
                                       agent=STRUCTURAL_AGENT)

    asyncio.run(run())
    assert not any(method == "POST" for method, _ in requests)
