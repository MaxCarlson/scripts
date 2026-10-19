"""Pinned OpenCode project/session schema tests; no live HTTP or inference."""

import asyncio
from pathlib import Path

import httpx
import pytest

from agent_benchmark.bridge import OpenCodeBridge

PROJECT = "a" * 40


def remote(workspace, overrides=None, requests=None, *, project_id=PROJECT):
    overrides = overrides or {}
    def handle(request):
        if requests is not None:
            requests.append(request)
        key = (request.method, request.url.path)
        payloads = {
            ("GET", "/global/health"): {"version": "1.19.3"},
            ("GET", "/provider"): {"all": [{"id": "lmstudio", "models": {"model-a": {}}}], "connected": ["lmstudio"]},
            ("GET", "/agent"): [{"name": "local-worker", "permission": []}],
            ("GET", "/path"): {"directory": str(workspace), "worktree": str(workspace)},
            ("GET", "/project/current"): {"id": project_id, "worktree": str(workspace), "vcs": "git"},
            ("POST", "/session"): {"id": "session-1", "directory": str(workspace), "projectID": project_id},
            ("GET", "/session/session-1"): {"id": "session-1", "directory": str(workspace), "projectID": project_id},
            ("GET", "/session/session-1/message"): [],
            ("GET", "/session/status"): {},
        }
        return httpx.Response(200, json=overrides.get(key, payloads.get(key)))
    return handle


async def prepare(bridge, workspace):
    await bridge.preflight(workspace, provider="lmstudio", model="model-a", agent="local-worker", project_id=PROJECT)
    return await bridge.prepare_session(workspace, project_id=PROJECT)


def test_header_only_routing_and_validated_empty_session_before_one_mcp_submission(tmp_path):
    requests, calls = [], []
    async def tool(name, args):
        calls.append((name, args))
        assert any(r.method == "GET" and r.url.path == "/session/session-1" for r in requests)
        return {"jobId": "job-1", "sessionId": "session-1", "messageId": "message-1"}
    async def run():
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(remote(tmp_path, requests=requests))) as http:
            bridge = OpenCodeBridge(tool, http)
            session = await prepare(bridge, tmp_path)
            assert session["projectID"] == PROJECT
            handle = await bridge.dispatch(tmp_path, "solve", provider="lmstudio", model="model-a", agent="local-worker")
            assert handle.project_id == PROJECT
            with pytest.raises(RuntimeError, match="already|once|fresh"):
                await bridge.dispatch(tmp_path, "again", provider="lmstudio", model="model-a", agent="local-worker")
    asyncio.run(run())
    assert len(calls) == 1 and calls[0][1]["sessionId"] == "session-1"
    assert sum(r.method == "POST" and r.url.path == "/session" for r in requests) == 1
    assert all(r.headers["x-opencode-directory"] == str(tmp_path) and not r.url.query for r in requests)
    assert not any("prompt" in r.url.path for r in requests)


@pytest.mark.parametrize("endpoint,payload", [
    ("/path", {"directory": "C:/Users/mcarls", "worktree": "C:/Users/mcarls"}),
    ("/path", {"directory": ".", "worktree": "."}),
    ("/path", {}),
    ("/project/current", {"id": "global", "vcs": "git"}),
    ("/project/current", {"id": "b" * 40, "vcs": "git"}),
    ("/project/current", {"id": PROJECT, "vcs": None}),
    ("/project/current", {"id": PROJECT, "worktree": "C:/parent", "vcs": "git"}),
])
def test_bad_project_context_cannot_create_session_or_submit(tmp_path, endpoint, payload):
    requests = []
    async def forbidden(*args):
        pytest.fail("Failed project validation must not submit inference")
    async def run():
        value = payload
        if endpoint == "/project/current":
            value = {"id": PROJECT, "worktree": str(tmp_path), "vcs": "git", **payload}
        overrides = {("GET", endpoint): value}
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(remote(tmp_path, overrides, requests))) as http:
            with pytest.raises(RuntimeError):
                await prepare(OpenCodeBridge(forbidden, http), tmp_path)
    asyncio.run(run())
    assert all(r.method == "GET" for r in requests)


@pytest.mark.parametrize("endpoint,payload", [
    ("/session", {"id": "session-1", "directory": "C:/other", "projectID": PROJECT}),
    ("/session", {"id": "session-1", "directory": "", "projectID": PROJECT}),
    ("/session/session-1", {"id": "session-1", "directory": "C:/other", "projectID": PROJECT}),
    ("/session/session-1", {"id": "session-1", "projectID": "global"}),
    ("/session/session-1", {"id": "other", "projectID": PROJECT}),
    ("/session/session-1/message", [{"info": {"role": "user"}}]),
    ("/session/status", {"session-1": {"type": "busy"}}),
])
def test_mismatched_or_nonempty_session_is_rejected_without_prompt(tmp_path, endpoint, payload):
    requests = []
    async def forbidden(*args):
        pytest.fail("Session validation must precede inference")
    async def run():
        method = "POST" if endpoint == "/session" else "GET"
        value = payload
        if endpoint in ("/session", "/session/session-1"):
            value = {"id": "session-1", "directory": str(tmp_path), "projectID": PROJECT, **payload}
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(remote(tmp_path, {(method, endpoint): value}, requests))) as http:
            with pytest.raises(RuntimeError):
                await prepare(OpenCodeBridge(forbidden, http), tmp_path)
    asyncio.run(run())
    assert not any("prompt" in r.url.path for r in requests)
    assert sum(r.method == "POST" for r in requests) == 1


def test_windows_case_and_separator_variants_identify_same_workspace():
    workspace = Path("C:/Owned/Trial Space")
    async def forbidden(*args):
        pytest.fail("Read-only preflight must not submit")
    async def run():
        overrides = {("GET", "/path"): {"directory": "c:\\owned\\trial space", "worktree": "C:/OWNED/TRIAL SPACE"}}
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(remote(workspace, overrides))) as http:
            facts = await OpenCodeBridge(forbidden, http).preflight(
                workspace, provider="lmstudio", model="model-a", agent="local-worker", project_id=PROJECT)
            assert facts["project"]["id"] == PROJECT
    asyncio.run(run())



def test_session_creation_transport_failure_is_not_retried(tmp_path):
    requests = []
    default = remote(tmp_path, requests=requests)
    def failing(request):
        if request.method == "POST":
            requests.append(request)
            raise httpx.ReadTimeout("empty session creation uncertain", request=request)
        return default(request)
    async def forbidden(*args):
        pytest.fail("No prompt may follow uncertain session creation")
    async def run():
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(failing)) as http:
            bridge = OpenCodeBridge(forbidden, http)
            await bridge.preflight(tmp_path, provider="lmstudio", model="model-a", agent="local-worker", project_id=PROJECT)
            with pytest.raises(httpx.ReadTimeout):
                await bridge.prepare_session(tmp_path, project_id=PROJECT)
            with pytest.raises(RuntimeError, match="fresh|already"):
                await bridge.prepare_session(tmp_path, project_id=PROJECT)
    asyncio.run(run())
    assert sum(r.method == "POST" for r in requests) == 1


def test_mismatched_receipt_keeps_original_session_and_blocks_resubmission(tmp_path):
    from agent_benchmark.bridge import SubmissionUncertain
    calls = []
    async def tool(name, args):
        calls.append(args)
        return {"jobId": "job-wrong", "sessionId": "other-session", "messageId": "message-other"}
    async def run():
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(remote(tmp_path))) as http:
            bridge = OpenCodeBridge(tool, http)
            await prepare(bridge, tmp_path)
            with pytest.raises(SubmissionUncertain):
                await bridge.dispatch(tmp_path, "solve", provider="lmstudio", model="model-a", agent="local-worker")
            assert bridge.last_receipt["sessionId"] == "session-1"
            assert bridge.last_receipt["received_receipt"]["sessionId"] == "other-session"
            with pytest.raises(RuntimeError):
                await bridge.dispatch(tmp_path, "retry", provider="lmstudio", model="model-a", agent="local-worker")
    asyncio.run(run())
    assert len(calls) == 1



def test_reconciliation_and_cancel_refuse_project_rebinding(tmp_path):
    from agent_benchmark.lifecycle import WorkerHandle
    handle = WorkerHandle("job-1", "session-1", "message-1", tmp_path, PROJECT)
    async def forbidden(*args):
        pytest.fail("A rebound session cannot authorize cancellation")
    async def run():
        override = {("GET", "/session/session-1"): {"id": "session-1", "directory": str(tmp_path), "projectID": "b" * 40}}
        async with httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(remote(tmp_path, override))) as http:
            bridge = OpenCodeBridge(forbidden, http)
            assert not (await bridge.observe(handle)).confirms_termination
            with pytest.raises(RuntimeError, match="mismatch"):
                await bridge.cancel(handle)
    asyncio.run(run())
