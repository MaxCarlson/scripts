"""Opt-in Windows HTTP integration with mocked and explicitly gated LM Studio upstreams."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import psutil
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from resource_coordinator.config import build_system, load_config
from resource_coordinator.core.processes import (
    ProcessInfo,
    ProcessLifecycleOwner,
    ProcessState,
    WindowsProcessBackend,
)
from resource_coordinator.core.service import CoordinatorService

MOCK_OPT_IN = "RESOURCE_COORDINATOR_RUN_DISPOSABLE_WINDOWS_TEST"
LIVE_OPT_IN = "RESOURCE_COORDINATOR_RUN_LIVE_LMSTUDIO_TEST"
DEFAULT_LMSTUDIO_URL = "http://127.0.0.1:1234"
DEFAULT_QWEN_MODEL_ID = "qwen38-27b-q4km"
UPSTREAM_TIMEOUT_SECONDS = 120.0
REQUEST_TIMEOUT_SECONDS = 130.0


def _model_state(payload: Any, model_id: str) -> str | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    for item in payload["data"]:
        if isinstance(item, dict) and item.get("id") == model_id:
            state = item.get("state")
            return state if isinstance(state, str) else None
    return None


def _validate_loopback_upstream(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Live LM Studio upstream must be a plain HTTP loopback origin")
    return url.rstrip("/")


@pytest.mark.parametrize(
    ("payload", "model_id", "expected"),
    [
        (
            {"data": [{"id": "qwen38-27b-q4km", "state": "loaded"}]},
            "qwen38-27b-q4km",
            "loaded",
        ),
        (
            {"data": [{"id": "qwen38-27b-q4km", "state": "not-loaded"}]},
            "qwen38-27b-q4km",
            "not-loaded",
        ),
        ({"data": [{"id": "other", "state": "loaded"}]}, "qwen38-27b-q4km", None),
        ({"data": "invalid"}, "qwen38-27b-q4km", None),
    ],
)
def test_model_state_reads_exact_read_only_api_model_record(payload: Any, model_id: str, expected: str | None) -> None:
    assert _model_state(payload, model_id) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:1234",
        "http://192.168.1.10:1234",
        "http://127.0.0.1:1234/v1",
        "http://user:password@127.0.0.1:1234",
    ],
)
def test_live_upstream_rejects_nonlocal_or_ambiguous_origins(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_loopback_upstream(url)


def test_live_upstream_accepts_local_lmstudio_origin() -> None:
    assert _validate_loopback_upstream("http://127.0.0.1:1234/") == "http://127.0.0.1:1234"


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def _verify_identity(
    info: ProcessInfo,
    executable: Path,
    script: Path,
    token: str,
    working_directory: Path,
) -> dict[str, Any]:
    assert info.state == ProcessState.RUNNING
    assert info.lifecycle_owner == ProcessLifecycleOwner.COORDINATOR
    assert info.is_coordinator_owned
    assert info.pid is not None and info.create_time is not None
    process = psutil.Process(info.pid)
    command_line = process.cmdline()
    assert process.create_time() == info.create_time
    assert _path_key(process.exe()) == _path_key(executable)
    assert process.ppid() == os.getpid()
    assert _path_key(process.cwd()) == _path_key(working_directory)
    assert any(_path_key(arg) == _path_key(script) for arg in command_line)
    assert token in command_line
    return {
        "pid": process.pid,
        "create_time": process.create_time(),
        "parent_pid": process.ppid(),
        "executable": process.exe(),
        "working_directory": process.cwd(),
        "command_line": command_line,
    }


def _same_live_identity(identity: dict[str, Any], executable: Path, script: Path, token: str) -> psutil.Process | None:
    try:
        process = psutil.Process(identity["pid"])
        command_line = process.cmdline()
        if (
            process.create_time() == identity["create_time"]
            and _path_key(process.exe()) == _path_key(executable)
            and process.ppid() == os.getpid()
            and any(_path_key(arg) == _path_key(script) for arg in command_line)
            and token in command_line
        ):
            return process
    except psutil.NoSuchProcess:
        return None
    return None


class _VerifiedForwardTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        supervisor: Any,
        lease_manager: Any,
        events: list[dict[str, Any]],
        before_forward: Any = None,
    ) -> None:
        self.inner = inner
        self.supervisor = supervisor
        self.lease_manager = lease_manager
        self.events = events
        self.before_forward = before_forward

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        info = await self.supervisor.status()
        if info.state != ProcessState.STOPPED:
            raise RuntimeError("Refusing upstream send before verified process stop")
        if self.lease_manager.active_count("gpu.inference") != 1:
            raise RuntimeError("Refusing upstream send without the inference lease")
        if self.before_forward is not None:
            await self.before_forward()
        self.events.append({"event": "upstream_forwarded", "monotonic": time.monotonic()})
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


async def _fetch_model_state(base_url: str, model_id: str, api_key: str | None) -> str | None:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(trust_env=False, timeout=5.0) as client:
        response = await client.get(f"{base_url}/api/v0/models", headers=headers)
    response.raise_for_status()
    return _model_state(response.json(), model_id)


async def _run_gateway_case(tmp_path: Path, case: str) -> None:
    if os.name != "nt":
        pytest.skip("requires the Windows process backend")

    process_name = f"rc_http_disposable_{uuid4().hex}"
    executable = Path(os.environ["SystemRoot"]) / "System32" / "cscript.exe"
    if not executable.is_file():
        pytest.skip("Windows console script host is unavailable")
    for process in psutil.process_iter(["name", "exe"]):
        try:
            if process.info.get("name", "").casefold() == "cscript.exe":
                if not process.info.get("exe"):
                    pytest.skip("cannot verify an existing cscript.exe identity")
                if _path_key(process.info["exe"]) == _path_key(executable):
                    pytest.skip("another cscript.exe is running; refusing ambiguous process identity")
        except psutil.NoSuchProcess:
            continue

    live = case == "live"
    upstream_url = os.environ.get("RESOURCE_COORDINATOR_LMSTUDIO_URL", DEFAULT_LMSTUDIO_URL)
    api_key = os.environ.get("RESOURCE_COORDINATOR_LMSTUDIO_API_KEY")
    model_id = os.environ.get("RESOURCE_COORDINATOR_LMSTUDIO_MODEL", DEFAULT_QWEN_MODEL_ID)
    if live:
        upstream_url = _validate_loopback_upstream(upstream_url)
        model_state = await _fetch_model_state(upstream_url, model_id, api_key)
        if model_state != "loaded":
            pytest.fail(
                f"Live test requires preloaded model {model_id!r}; current read-only state is {model_state!r}. "
                "No process was started and no model operation was attempted."
            )
        cooldown_seconds = 5.0
    else:
        upstream_url = "http://coordinator-mock-upstream.invalid"
        api_key = "mock-only-token" if case == "mock-success" else None
        model_id = "mock-only"
        cooldown_seconds = 1.5

    host_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    host_socket.bind(("127.0.0.1", 0))
    host_socket.listen()
    listen_port = int(host_socket.getsockname()[1])
    assert listen_port not in {1234, 1235}

    helper_script = tmp_path / f"{process_name}.vbs"
    helper_script.write_text("Do\n    WScript.Sleep 1000\nLoop\n", encoding="utf-8")
    config_path = tmp_path / f"{process_name}.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "service": {
                    "listen_host": "127.0.0.1",
                    "listen_port": listen_port,
                    "upstream_url": upstream_url,
                },
                "processes": {
                    process_name: {
                        "backend": "windows",
                        "executable": str(executable),
                        "arguments": [
                            "//B",
                            "//NoLogo",
                            str(helper_script),
                            process_name,
                        ],
                        "working_directory": str(tmp_path),
                        "new_console": False,
                        "allow_external_stop": False,
                        "allow_external_restart": False,
                        "adopt_external": False,
                        "allow_force_termination": False,
                        "stop_timeout_seconds": 5.0,
                    }
                },
                "policies": [
                    {
                        "name": "stop-disposable-before-inference",
                        "trigger_event": "lmstudio.inference_requested",
                        "target_process": process_name,
                        "stop_process": True,
                        "restart_process": True,
                        "only_if_stopped_by_coordinator": True,
                        "resource": "gpu.inference",
                        "lease_type": "shared",
                        "cooldown_seconds": cooldown_seconds,
                        "stop_timeout_seconds": 5.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    system = build_system(config)
    supervisor = system.supervisors[process_name]
    backend = supervisor.backend
    assert isinstance(backend, WindowsProcessBackend)
    service = CoordinatorService(
        system,
        start_process_on_ready=process_name,
        stop_process_on_shutdown=process_name,
    )

    events: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    restart_ready = asyncio.Event()
    cooldown_elapsed = asyncio.Event()
    admission_count = 0
    original_evaluate = system.gateway.admission_controller.evaluate

    def observe_admission(method: str, path: str):
        nonlocal admission_count
        decision = original_evaluate(method, path)
        if path == "/v1/chat/completions" and decision.allowed:
            admission_count += 1
            if admission_count == 1:
                events.append({"event": "request_admitted", "monotonic": time.monotonic()})
        return decision

    system.gateway.admission_controller.evaluate = observe_admission  # type: ignore[method-assign]

    def record_event(name: str, marker: str) -> None:
        async def handler(event: Any) -> None:
            events.append(
                {
                    "event": marker,
                    "wall_time": event.timestamp,
                    "status": event.data.get("status"),
                }
            )
            if name == "process.started":
                info = await supervisor.status()
                if info.pid is not None and info.create_time is not None:
                    identities.append(
                        {
                            "pid": info.pid,
                            "create_time": info.create_time,
                            "parent_pid": os.getpid(),
                            "executable": str(executable),
                            "script": str(helper_script),
                        }
                    )
                if len([item for item in events if item["event"] == "process_started"]) >= 2:
                    restart_ready.set()
            if name == "resource.idle":
                cooldown_elapsed.set()

        system.dispatcher.on(name, handler)

    for name, marker in [
        ("resource.lease_requested", "reservation_established"),
        ("process.stop_requested", "process_stop_requested"),
        ("process.stopped", "process_stop_verified"),
        ("resource.acquired", "inference_lease_active"),
        ("lmstudio.inference_finished", "inference_finished"),
        ("resource.cooldown_started", "cooldown_started"),
        ("resource.idle", "cooldown_elapsed"),
        ("process.started", "process_started"),
    ]:
        record_event(name, marker)

    if case.startswith("mock-"):
        status_code = 500 if case == "mock-failure" else 200

        async def mock_upstream(request: Request) -> JSONResponse:
            info = await supervisor.status()
            assert info.state == ProcessState.STOPPED
            assert system.lease_mgr.active_count("gpu.inference") == 1
            if case == "mock-success":
                assert request.headers.get("authorization") == "Bearer mock-only-token"
            if status_code != 200:
                return JSONResponse({"error": {"message": "mock failure"}}, status_code=status_code)
            return JSONResponse(
                {
                    "id": "mock-response",
                    "choices": [{"finish_reason": "stop", "message": {"content": "mock-only"}}],
                }
            )

        upstream_app = Starlette(routes=[Route("/v1/chat/completions", mock_upstream, methods=["POST"])])
        inner_transport: httpx.AsyncBaseTransport = httpx.ASGITransport(app=upstream_app)
        before_forward = None
    else:
        status_code = 200
        inner_transport = httpx.AsyncHTTPTransport(retries=0)

        async def before_forward() -> None:
            state = await _fetch_model_state(upstream_url, model_id, api_key)
            if state != "loaded":
                raise RuntimeError(
                    f"Model {model_id!r} became {state!r} before forwarding; refusing an implicit model load"
                )

    verified_transport = _VerifiedForwardTransport(
        inner_transport, supervisor, system.lease_mgr, events, before_forward
    )
    upstream_headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    system.gateway._http_client = httpx.AsyncClient(
        transport=verified_transport,
        base_url=upstream_url,
        headers=upstream_headers,
        timeout=httpx.Timeout(UPSTREAM_TIMEOUT_SECONDS, connect=5.0),
        follow_redirects=False,
        trust_env=False,
    )
    app = system.gateway.create_app(service)
    server = uvicorn.Server(uvicorn.Config(app, lifespan="on", log_level="warning", access_log=False, ws="none"))
    server_task: asyncio.Task[None] | None = None
    client: httpx.AsyncClient | None = None
    response: httpx.Response | None = None
    cooldown_elapsed_seconds: float | None = None

    try:
        server_task = asyncio.create_task(server.serve(sockets=[host_socket]))
        deadline = asyncio.get_running_loop().time() + 10.0
        while not server.started:
            if server_task.done():
                await server_task
                raise RuntimeError("Coordinator HTTP server stopped before becoming ready")
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Coordinator HTTP server did not become ready within 10 seconds")
            await asyncio.sleep(0.01)

        client = httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{listen_port}",
            timeout=REQUEST_TIMEOUT_SECONDS if live else 10.0,
            trust_env=False,
        )
        request_headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        request_body = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with exactly READY."}],
            "temperature": 0,
            "max_tokens": 16,
            "stream": False,
        }
        initial_info = await supervisor.status()
        identities.append(_verify_identity(initial_info, executable, helper_script, process_name, tmp_path))
        assert backend._console_group_pid == initial_info.pid
        response = await client.post("/v1/chat/completions", json=request_body, headers=request_headers)
        assert response.status_code == status_code

        if status_code == 200:
            payload = response.json()
            choices = payload.get("choices")
            assert isinstance(choices, list) and choices
            assert isinstance(choices[0], dict) and choices[0].get("finish_reason")
            if not live:
                assert choices[0]["message"]["content"] == "mock-only"

            if case == "mock-success":
                # Exercise the real gateway while the first cooldown is pending.
                await asyncio.sleep(cooldown_seconds / 3)
                assert (await supervisor.status()).state == ProcessState.STOPPED
                second_response = await client.post(
                    "/v1/chat/completions",
                    json=request_body,
                    headers=request_headers,
                )
                assert second_response.status_code == 200
                assert len([event for event in events if event["event"] == "upstream_forwarded"]) == 2
                assert (await supervisor.status()).state == ProcessState.STOPPED
                assert len([event for event in events if event["event"] == "process_started"]) == 1

            stopped_info = await supervisor.status()
            assert stopped_info.state == ProcessState.STOPPED
            assert supervisor.was_stopped_by_coordinator
            assert await supervisor.wait_stopped(timeout=1.0)
            await asyncio.wait_for(restart_ready.wait(), timeout=cooldown_seconds + 8.0)
            await asyncio.wait_for(cooldown_elapsed.wait(), timeout=cooldown_seconds + 2.0)
            resumed_info = await supervisor.status()
            identities.append(_verify_identity(resumed_info, executable, helper_script, process_name, tmp_path))
            assert backend._console_group_pid == resumed_info.pid
            cooldown_start = [e for e in events if e["event"] == "cooldown_started"][-1]
            idle_event = next(e for e in events if e["event"] == "cooldown_elapsed")
            restart_event = [e for e in events if e["event"] == "process_started"][-1]
            cooldown_elapsed_seconds = restart_event["wall_time"] - cooldown_start["wall_time"]
            assert idle_event["wall_time"] >= cooldown_start["wall_time"]
            assert restart_event["wall_time"] >= idle_event["wall_time"]
            assert cooldown_elapsed_seconds >= cooldown_seconds - 0.25
        else:
            assert system.lease_mgr.is_restart_inhibited("gpu.inference")
            assert (await supervisor.status()).state == ProcessState.STOPPED
            await asyncio.sleep(cooldown_seconds + 0.25)
            assert (await supervisor.status()).state == ProcessState.STOPPED
            assert len([e for e in events if e["event"] == "process_started"]) == 1

        event_names = [e["event"] for e in events]
        assert event_names.index("process_stop_verified") < event_names.index("upstream_forwarded")
        if status_code == 200:
            assert event_names.index("upstream_forwarded") < event_names.index("inference_finished")
            assert event_names.index("inference_finished") < event_names.index("cooldown_started")
            assert event_names.index("cooldown_elapsed") < max(
                i for i, name in enumerate(event_names) if name == "process_started"
            )
        else:
            assert "cooldown_started" not in event_names
            finish_event = next(e for e in events if e["event"] == "inference_finished")
            assert finish_event["status"] == "uncertain"
    finally:
        if client is not None:
            await client.aclose()
        if server_task is not None:
            server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(server_task), timeout=40.0)
            except TimeoutError:
                server.force_exit = True
                server_task.cancel()
                try:
                    await asyncio.wait_for(server_task, timeout=5.0)
                except (asyncio.CancelledError, TimeoutError):
                    pass
            except Exception:
                # Preserve the original startup/request failure and continue exact-process cleanup.
                pass
        host_socket.close()

        current = await supervisor.status()
        if current.state != ProcessState.STOPPED:
            assert current.pid is not None and current.create_time is not None
            assert any(
                identity["pid"] == current.pid and identity["create_time"] == current.create_time
                for identity in identities
            ), "Refusing cleanup: current PID/create-time was not recorded by this test"
            process = psutil.Process(current.pid)
            assert process.create_time() == current.create_time
            assert _path_key(process.exe()) == _path_key(executable)
            assert process.ppid() == os.getpid()
            assert any(_path_key(arg) == _path_key(helper_script) for arg in process.cmdline())
            stopped = await supervisor.stop(timeout=5.0)
            if not stopped:
                process = psutil.Process(current.pid)
                assert process.create_time() == current.create_time
                assert _path_key(process.exe()) == _path_key(executable)
                assert process.ppid() == os.getpid()
                assert any(_path_key(arg) == _path_key(helper_script) for arg in process.cmdline())
                process.terminate()
                process.wait(timeout=5.0)
            assert (await supervisor.status()).state == ProcessState.STOPPED
        for identity in identities:
            leftover = _same_live_identity(identity, executable, helper_script, process_name)
            if leftover is not None:
                leftover.terminate()
                leftover.wait(timeout=5.0)
            assert _same_live_identity(identity, executable, helper_script, process_name) is None

    unique_identities = {(identity["pid"], identity["create_time"]): identity for identity in identities}
    print(
        json.dumps(
            {
                "case": case,
                "model": model_id,
                "mocked_upstream": not live,
                "gateway_status": response.status_code if response else None,
                "process_launches": list(unique_identities.values()),
                "cooldown_elapsed_seconds": cooldown_elapsed_seconds,
                "final_process_state": "stopped",
                "event_order": [event["event"] for event in events],
                "response_body_logged": False,
            },
            indent=2,
        )
    )


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="requires Windows process control")
@pytest.mark.skipif(os.environ.get(MOCK_OPT_IN) != "1", reason="opt-in disposable Windows process test")
async def test_windows_http_gateway_real_listener_with_mocked_success_and_cleanup(
    tmp_path: Path,
) -> None:
    await _run_gateway_case(tmp_path, "mock-success")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="requires Windows process control")
@pytest.mark.skipif(os.environ.get(MOCK_OPT_IN) != "1", reason="opt-in disposable Windows process test")
async def test_windows_http_gateway_mock_failure_keeps_restart_inhibited(
    tmp_path: Path,
) -> None:
    await _run_gateway_case(tmp_path, "mock-failure")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="requires Windows process control")
@pytest.mark.skipif(
    os.environ.get(LIVE_OPT_IN) != "1",
    reason="requires separate explicit live-inference authorization",
)
async def test_windows_http_gateway_single_preloaded_qwen_inference(
    tmp_path: Path,
) -> None:
    await _run_gateway_case(tmp_path, "live")
