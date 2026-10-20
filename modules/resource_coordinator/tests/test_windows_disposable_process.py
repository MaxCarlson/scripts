"""Opt-in Windows process integration using a disposable console helper."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import psutil
import pytest
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

pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="requires the Windows process backend"),
    pytest.mark.skipif(
        os.environ.get("RESOURCE_COORDINATOR_RUN_DISPOSABLE_WINDOWS_TEST") != "1",
        reason="opt-in process-control integration test",
    ),
]


def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def _verify_identity(
    info: ProcessInfo,
    expected_exe: Path,
    expected_script: Path,
    expected_token: str,
    expected_cwd: Path,
) -> dict[str, Any]:
    assert info.state == ProcessState.RUNNING
    assert info.lifecycle_owner == ProcessLifecycleOwner.COORDINATOR
    assert info.is_coordinator_owned
    assert info.pid is not None and info.create_time is not None
    process = psutil.Process(info.pid)
    assert process.create_time() == info.create_time
    assert _path_key(process.exe()) == _path_key(expected_exe)
    assert process.ppid() == os.getpid()
    assert _path_key(process.cwd()) == _path_key(expected_cwd)
    command_line = process.cmdline()
    assert any(_path_key(arg) == _path_key(expected_script) for arg in command_line)
    assert expected_token in command_line
    return {
        "pid": process.pid,
        "create_time": process.create_time(),
        "parent_pid": process.ppid(),
        "executable": process.exe(),
        "working_directory": process.cwd(),
        "command_line": command_line,
    }


def _same_live_identity(
    identity: dict[str, Any],
    expected_exe: Path,
    expected_script: Path,
    expected_token: str,
) -> psutil.Process | None:
    try:
        process = psutil.Process(identity["pid"])
        if (
            process.create_time() == identity["create_time"]
            and _path_key(process.exe()) == _path_key(expected_exe)
            and process.ppid() == os.getpid()
            and any(_path_key(arg) == _path_key(expected_script) for arg in process.cmdline())
            and expected_token in process.cmdline()
        ):
            return process
    except psutil.NoSuchProcess:
        return None
    return None


@pytest.mark.asyncio
async def test_windows_disposable_process_gateway_stop_cooldown_restart_and_cleanup(
    tmp_path: Path,
) -> None:
    process_name = f"rc_disposable_{uuid4().hex}"
    executable = Path(os.environ["SystemRoot"]) / "System32" / "cscript.exe"
    assert executable.is_file()
    existing_console_script_hosts = []
    for process in psutil.process_iter(["name", "exe"]):
        try:
            if process.info.get("name", "").casefold() == "cscript.exe" and _path_key(
                process.info.get("exe") or ""
            ) == _path_key(executable):
                existing_console_script_hosts.append(process.pid)
        except psutil.NoSuchProcess:
            continue
    assert not existing_console_script_hosts, (
        "Refusing the disposable test because an unrelated cscript.exe is already running"
    )
    helper_script = tmp_path / f"{process_name}.vbs"
    helper_script.write_text(
        "Do\n    WScript.Sleep 1000\nLoop\n",
        encoding="utf-8",
    )
    config_path = tmp_path / f"{process_name}.json"
    cooldown_seconds = 1.5
    config_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "service": {
                    "listen_host": "127.0.0.1",
                    "listen_port": 18765,
                    "upstream_url": "http://coordinator-mock-upstream.invalid",
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
                        "name": "disposable-process-for-mock-inference",
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
    assert config.service.upstream_url == "http://coordinator-mock-upstream.invalid"
    assert config.service.listen_port not in {1234, 1235}
    assert config.processes[process_name].backend == "windows"
    system = build_system(config)
    supervisor = system.supervisors[process_name]
    backend = supervisor.backend
    assert isinstance(backend, WindowsProcessBackend)
    service = CoordinatorService(
        system,
        start_process_on_ready=process_name,
        stop_process_on_shutdown=process_name,
    )

    evidence: list[dict[str, Any]] = []
    restart_ready = asyncio.Event()
    cooldown_elapsed_ready = asyncio.Event()
    evaluate_count = 0
    original_evaluate = system.gateway.admission_controller.evaluate

    def observe_admission(method: str, path: str):
        nonlocal evaluate_count
        decision = original_evaluate(method, path)
        if path == "/v1/chat/completions" and decision.allowed:
            evaluate_count += 1
            if evaluate_count == 1:
                evidence.append({"event": "request_admitted", "monotonic": time.monotonic()})
        return decision

    system.gateway.admission_controller.evaluate = observe_admission  # type: ignore[method-assign]

    observed_processes: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []

    def record_event(name: str, marker: str) -> None:
        async def handler(event: Any) -> None:
            evidence.append(
                {
                    "event": marker,
                    "wall_time": event.timestamp,
                    "data": dict(event.data),
                }
            )
            if name == "process.started":
                info = await supervisor.status()
                if info.pid is not None and info.create_time is not None:
                    observed_processes.append({"pid": info.pid, "create_time": info.create_time})
                if len([item for item in evidence if item["event"] == "process_started"]) >= 2:
                    restart_ready.set()
            if name == "resource.idle":
                cooldown_elapsed_ready.set()

        system.dispatcher.on(name, handler)

    record_event("resource.lease_requested", "resource_reservation_established")
    record_event("process.stop_requested", "process_stop_requested")
    record_event("process.stopped", "process_stop_verified")
    record_event("resource.acquired", "resource_lease_active")
    record_event("lmstudio.inference_finished", "inference_confirmed_complete")
    record_event("resource.cooldown_started", "cooldown_started")
    record_event("resource.idle", "cooldown_elapsed")
    record_event("process.started", "process_started")

    async def mock_inference(request: Request) -> JSONResponse:
        info = await supervisor.status()
        assert info.state == ProcessState.STOPPED
        assert system.lease_mgr.active_count("gpu.inference") == 1
        evidence.append({"event": "mock_inference_forwarded", "monotonic": time.monotonic()})
        return JSONResponse(
            {
                "id": "disposable-test-response",
                "choices": [{"finish_reason": "stop", "message": {"content": "mock-only"}}],
            }
        )

    mock_upstream = Starlette(routes=[Route("/v1/chat/completions", mock_inference, methods=["POST"])])
    system.gateway._http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_upstream),
        base_url=config.service.upstream_url,
    )
    app = system.gateway.create_app(service)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://coordinator.test")
    completed_monotonic: list[float] = []

    async def capture_completion(event: Any) -> None:
        if event.data.get("status") == "completed":
            completed_monotonic.append(time.monotonic())

    system.dispatcher.on("lmstudio.inference_finished", capture_completion)

    try:
        async with app.router.lifespan_context(app):
            initial_info = await supervisor.status()
            initial_identity = _verify_identity(initial_info, executable, helper_script, process_name, tmp_path)
            identities.append(initial_identity)
            assert backend._console_group_pid == initial_info.pid

            response = await asyncio.wait_for(
                client.post("/v1/chat/completions", json={"model": "mock-only", "messages": []}),
                timeout=10.0,
            )
            assert response.status_code == 200
            assert response.json()["choices"][0]["message"]["content"] == "mock-only"

            stopped_info = await supervisor.status()
            assert stopped_info.state == ProcessState.STOPPED
            assert supervisor.was_stopped_by_coordinator
            assert await supervisor.wait_stopped(timeout=1.0)

            await asyncio.wait_for(restart_ready.wait(), timeout=8.0)
            await asyncio.wait_for(cooldown_elapsed_ready.wait(), timeout=2.0)
            resumed_info = await supervisor.status()
            resumed_identity = _verify_identity(resumed_info, executable, helper_script, process_name, tmp_path)
            identities.append(resumed_identity)
            assert backend._console_group_pid == resumed_info.pid
            assert len(completed_monotonic) == 1

            cooldown_start = next(item for item in evidence if item["event"] == "cooldown_started")
            cooldown_elapsed = next(item for item in evidence if item["event"] == "cooldown_elapsed")
            restarted = [item for item in evidence if item["event"] == "process_started"][-1]
            assert cooldown_elapsed["wall_time"] >= cooldown_start["wall_time"]
            assert restarted["wall_time"] >= cooldown_elapsed["wall_time"]
            elapsed = restarted["wall_time"] - cooldown_start["wall_time"]
            assert elapsed >= cooldown_seconds - 0.15

            event_names = [item["event"] for item in evidence]
            required = [
                "request_admitted",
                "resource_reservation_established",
                "process_stop_requested",
                "process_stop_verified",
                "resource_lease_active",
                "mock_inference_forwarded",
                "inference_confirmed_complete",
                "cooldown_started",
            ]
            first_occurrences = [event_names.index(name) for name in required]
            restarted_index = max(index for index, name in enumerate(event_names) if name == "process_started")
            assert first_occurrences == sorted(first_occurrences)
            assert restarted_index > event_names.index("cooldown_elapsed")

        final_info = await supervisor.status()
        assert final_info.state == ProcessState.STOPPED
        assert all(
            _same_live_identity(identity, executable, helper_script, process_name) is None for identity in identities
        )
        print(
            json.dumps(
                {
                    "launches": identities,
                    "stop_verified": True,
                    "mock_inference_status": response.status_code,
                    "cooldown_elapsed_seconds": elapsed,
                    "restarted_then_stopped_on_shutdown": final_info.state == ProcessState.STOPPED,
                    "event_order": required,
                },
                indent=2,
            )
        )
    finally:
        await client.aclose()
        current = await supervisor.status()
        if current.state != ProcessState.STOPPED:
            assert current.pid is not None and current.create_time is not None
            assert any(
                identity["pid"] == current.pid and identity["create_time"] == current.create_time
                for identity in observed_processes
            ), "Refusing cleanup because the current process does not match a recorded PID/create-time identity"
            process = psutil.Process(current.pid)
            assert process.create_time() == current.create_time
            assert _path_key(process.exe()) == _path_key(executable)
            assert process.ppid() == os.getpid()
            stopped = await supervisor.stop(timeout=5.0)
            if not stopped:
                process = psutil.Process(current.pid)
                assert process.create_time() == current.create_time
                assert _path_key(process.exe()) == _path_key(executable)
                assert process.ppid() == os.getpid()
                process.terminate()
                process.wait(timeout=5.0)
            assert (await supervisor.status()).state == ProcessState.STOPPED
        for identity in observed_processes:
            leftover = _same_live_identity(identity, executable, helper_script, process_name)
            if leftover is not None:
                leftover.terminate()
                leftover.wait(timeout=5.0)
            assert _same_live_identity(identity, executable, helper_script, process_name) is None, (
                f"Recorded disposable PID {identity['pid']} remains alive; retain its executable identity for recovery"
            )
