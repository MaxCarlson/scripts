"""
Real TCP loopback service integration test on 127.0.0.1:1235.

Validates the Resource Coordinator operating as a real network listening
service over TCP against real LM Studio on http://127.0.0.1:1234:
1. Server startup and GET /_coordinator/status health & readiness.
2. Read-only passthrough (GET /api/v0/models, GET /v1/models) without leases or process stops.
3. Non-streaming POST /v1/chat/completions with real stop-before-forward barrier and cooldown.
4. Streaming POST /v1/chat/completions (stream=True) over TCP with chunk-by-chunk SSE delivery,
   process held stopped, terminal [DONE] marker, and cooldown on completion.
5. Concurrent overlapping inference requests with concurrent leases and delayed cooldown.
6. Refusal of uncoordinated model mutation / loading operations.
7. Clean server and process teardown without orphaned processes or port leaks.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

import httpx
import psutil
import pytest
import uvicorn
from starlette.applications import Starlette

from resource_coordinator.acceptance_harness import discover_live_model
from resource_coordinator.config import (
    CoordinatorConfig,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
    build_system,
)
from resource_coordinator.core.durable_state import StateCodec
from resource_coordinator.core.processes import ProcessState, WindowsProcessBackend
from resource_coordinator.core.service import CoordinatorService


LMSTUDIO_URL = "http://127.0.0.1:1234"
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 1235


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


async def _probe_lmstudio() -> Optional[Dict[str, Any]]:
    """Probe LM Studio on 127.0.0.1:1234 and discover the preloaded model."""
    try:
        async with httpx.AsyncClient(base_url=LMSTUDIO_URL, timeout=3.0) as client:
            return await discover_live_model(client)
    except Exception:
        return None


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_live_loopback_service_e2e(tmp_path_factory: pytest.TempPathFactory):
    """
    Comprehensive real loopback integration test validating CoordinatorService
    listening on 127.0.0.1:1235 over real TCP.
    """
    # 1. Prerequisite checks
    loaded_model_info = await _probe_lmstudio()
    if loaded_model_info is None:
        pytest.skip(
            f"LM Studio is not listening on {LMSTUDIO_URL} or has no preloaded model; skipping live loopback test"
        )

    model_id = loaded_model_info["model_id"]

    if _is_port_in_use(LOOPBACK_PORT):
        pytest.fail(f"Port {LOOPBACK_PORT} is already in use by another process; cannot start loopback service")

    # 2. Configure isolated environment and disposable Windows helper process
    tmp_path = tmp_path_factory.mktemp("loopback_svc")
    journal_path = tmp_path / "journal_loopback.json"
    StateCodec.initialize(journal_path)
    log_path = tmp_path / "miner_stdout.log"

    vbs_path = (
        Path(__file__).parent.parent
        / "resource_coordinator"
        / "adapters"
        / "miners"
        / "windows_miner_helper.vbs"
    )
    cscript_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cscript.exe")

    proc_name = f"helper_proc_{uuid4().hex[:8]}"
    proc_cfg = ProcessConfig(
        name=proc_name,
        backend="windows" if os.name == "nt" else "fake",
        executable=cscript_exe if os.name == "nt" else "fake_exe",
        arguments=["//B", "//NoLogo", str(vbs_path), proc_name] if os.name == "nt" else [],
        working_directory=str(tmp_path),
        stop_timeout_seconds=5.0,
        allow_force_termination=True,
        stdout_log_path=str(log_path),
    )

    cooldown_seconds = 2.0
    cfg = CoordinatorConfig(
        service=ServiceConfig(
            listen_host=LOOPBACK_HOST,
            listen_port=LOOPBACK_PORT,
            upstream_url=LMSTUDIO_URL,
            state_persistence_path=str(journal_path),
        ),
        processes={proc_name: proc_cfg},
        policies=[
            PolicyConfig(
                name="stop-miner-on-inference",
                trigger_event="lmstudio.inference_requested",
                target_process=proc_name,
                stop_process=True,
                restart_process=True,
                resource="gpu.inference",
                lease_type="shared",
                cooldown_seconds=cooldown_seconds,
                only_if_stopped_by_coordinator=True,
            )
        ],
    )

    system = build_system(cfg, use_fake_processes=(os.name != "nt"))
    supervisor = system.supervisors[proc_name]

    service = CoordinatorService(
        system,
        start_process_on_ready=proc_name,
        stop_process_on_shutdown=proc_name,
        first_boot=True,
    )

    # Telemetry tracking on system dispatcher
    telemetry: Dict[str, Any] = {
        "active_leases": 0,
        "peak_active_leases": 0,
        "stopped_before_forward": True,
        "cooldown_started_count": 0,
        "restarted_count": 0,
    }

    async def on_acq(event: Any) -> None:
        telemetry["active_leases"] += 1
        if telemetry["active_leases"] > telemetry["peak_active_leases"]:
            telemetry["peak_active_leases"] = telemetry["active_leases"]

    async def on_rel(event: Any) -> None:
        telemetry["active_leases"] = max(0, telemetry["active_leases"] - 1)

    async def on_fwd(event: Any) -> None:
        st = await supervisor.status()
        if st.state != ProcessState.STOPPED:
            telemetry["stopped_before_forward"] = False

    async def on_cd(event: Any) -> None:
        telemetry["cooldown_started_count"] += 1

    async def on_started(event: Any) -> None:
        telemetry["restarted_count"] += 1

    system.dispatcher.on("resource.acquired", on_acq)
    system.dispatcher.on("resource.released", on_rel)
    system.dispatcher.on("lmstudio.inference_forwarded", on_fwd)
    system.dispatcher.on("resource.cooldown_started", on_cd)
    system.dispatcher.on("process.started", on_started)

    app = system.gateway.create_app(service)

    # 3. Start real Uvicorn server in background task
    uvicorn_config = uvicorn.Config(
        app=app,
        host=LOOPBACK_HOST,
        port=LOOPBACK_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    server_task = asyncio.create_task(server.serve())

    base_url = f"http://{LOOPBACK_HOST}:{LOOPBACK_PORT}"

    try:
        # Wait for service readiness
        ready = False
        async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
            for _ in range(50):
                try:
                    resp = await client.get("/_coordinator/status")
                    if resp.status_code == 200 and resp.json().get("is_ready") is True:
                        ready = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)

            assert ready, "Coordinator service failed to become ready on 127.0.0.1:1235 within 5 seconds"

            # -------------------------------------------------------------
            # STEP 2A: Verify GET /_coordinator/status
            # -------------------------------------------------------------
            resp_status = await client.get("/_coordinator/status")
            assert resp_status.status_code == 200
            data_status = resp_status.json()
            assert data_status["status"] == "online"
            assert data_status["is_ready"] is True
            assert data_status["service_state"] == "ready"
            assert proc_name in data_status["processes"]
            assert data_status["gpu_inference"]["active_count"] == 0
            assert data_status["gpu_inference"]["is_cooling_down"] is False

            # Verify initial process is running
            init_status = await supervisor.status()
            assert init_status.state == ProcessState.RUNNING
            init_pid = init_status.pid
            assert init_pid is not None

            # -------------------------------------------------------------
            # STEP 2B: Verify Read-Only Model Passthrough
            # -------------------------------------------------------------
            # Query /api/v0/models
            resp_v0 = await client.get("/api/v0/models")
            assert resp_v0.status_code == 200
            v0_data = resp_v0.json()
            assert any(m["id"] == model_id for m in v0_data.get("data", []))

            # Query /v1/models
            resp_v1 = await client.get("/v1/models")
            assert resp_v1.status_code == 200
            v1_data = resp_v1.json()
            assert any(m["id"] == model_id for m in v1_data.get("data", []))

            # Ensure passthrough acquired ZERO leases and process remained continuously running
            st_after_models = await supervisor.status()
            assert st_after_models.state == ProcessState.RUNNING
            assert st_after_models.pid == init_pid
            assert telemetry["active_leases"] == 0

            # -------------------------------------------------------------
            # STEP 2C: Verify Real Non-Streaming Inference
            # -------------------------------------------------------------
            infer_payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                "max_tokens": 4,
                "temperature": 0.0,
            }

            resp_infer = await client.post("/v1/chat/completions", json=infer_payload, timeout=30.0)
            assert resp_infer.status_code == 200
            infer_data = resp_infer.json()
            assert "choices" in infer_data
            assert len(infer_data["choices"]) > 0
            assert telemetry["stopped_before_forward"] is True

            # Process should be stopped and cooldown initiated
            assert (await supervisor.status()).state == ProcessState.STOPPED
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            # Wait for cooldown to expire and process to restart
            t_wait_start = time.monotonic()
            restarted = False
            while time.monotonic() - t_wait_start < cooldown_seconds + 5.0:
                st = await supervisor.status()
                if st.state == ProcessState.RUNNING:
                    restarted = True
                    break
                await asyncio.sleep(0.1)

            assert restarted, "Managed process failed to restart after cooldown"
            resumed_pid = (await supervisor.status()).pid
            assert resumed_pid is not None

            # -------------------------------------------------------------
            # STEP 2D: Verify Real Streaming Inference (SSE over real TCP)
            # -------------------------------------------------------------
            stream_payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Count from 1 to 3."}],
                "max_tokens": 8,
                "temperature": 0.0,
                "stream": True,
            }

            received_chunks = 0
            done_marker_seen = False
            async with client.stream("POST", "/v1/chat/completions", json=stream_payload, timeout=30.0) as s_resp:
                assert s_resp.status_code == 200
                async for line in s_resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        received_chunks += 1
                        payload_str = line[6:].strip()
                        if payload_str == "[DONE]":
                            done_marker_seen = True
                        # Process MUST remain stopped while streaming chunks
                        st_stream = await supervisor.status()
                        assert st_stream.state == ProcessState.STOPPED

            assert received_chunks > 1, f"Expected multiple SSE chunks, got {received_chunks}"
            assert done_marker_seen, "Expected terminal [DONE] marker in SSE stream"
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            # Wait for restart after stream cooldown
            t_wait_start = time.monotonic()
            restarted = False
            while time.monotonic() - t_wait_start < cooldown_seconds + 5.0:
                st = await supervisor.status()
                if st.state == ProcessState.RUNNING:
                    restarted = True
                    break
                await asyncio.sleep(0.1)
            assert restarted, "Managed process failed to restart after stream cooldown"

            # -------------------------------------------------------------
            # STEP 2E: Verify Concurrent Overlapping Requests over TCP
            # -------------------------------------------------------------
            telemetry["peak_active_leases"] = 0

            task1 = asyncio.create_task(client.post("/v1/chat/completions", json=infer_payload, timeout=30.0))
            task2 = asyncio.create_task(client.post("/v1/chat/completions", json=infer_payload, timeout=30.0))

            r1, r2 = await asyncio.gather(task1, task2)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert (await supervisor.status()).state == ProcessState.STOPPED
            assert telemetry["peak_active_leases"] >= 2, (
                f"Expected peak_active_leases >= 2, got {telemetry['peak_active_leases']}"
            )
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            # Wait for post-concurrency restart
            t_wait_start = time.monotonic()
            restarted = False
            while time.monotonic() - t_wait_start < cooldown_seconds + 5.0:
                st = await supervisor.status()
                if st.state == ProcessState.RUNNING:
                    restarted = True
                    break
                await asyncio.sleep(0.1)
            assert restarted, "Managed process failed to restart after concurrent requests"

            # -------------------------------------------------------------
            # STEP 3: Verify Model Mutation and Load Protection
            # -------------------------------------------------------------
            # Model unload is prohibited
            resp_unload = await client.post("/api/v0/model/unload")
            assert resp_unload.status_code == 503
            assert resp_unload.json()["error"]["type"] == "uncoordinated_model_mutation"

            # Model load without explicit configured policy is prohibited
            resp_load = await client.post("/api/v0/model/load", json={"model": "non-existent"})
            assert resp_load.status_code == 503
            assert resp_load.json()["error"]["type"] == "uncoordinated_model_mutation"

    finally:
        # Clean server teardown
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

        # Clean supervisor teardown
        await service.stop()

        # Verify no orphan processes
        st_final = await supervisor.status()
        assert st_final.state == ProcessState.STOPPED

        # Wait briefly for OS socket cleanup and verify port 1235 is freed
        await asyncio.sleep(0.5)
        assert not _is_port_in_use(LOOPBACK_PORT), f"Port {LOOPBACK_PORT} was not freed after shutdown"
