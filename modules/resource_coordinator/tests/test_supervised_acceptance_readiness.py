"""
Supervised Hardware Acceptance Readiness & Fault-Injection Tests.

Covers the 6 focused requirements for live KRig + LM Studio readiness:
1. Guaranteed cleanup in `finally` with miner & descendant termination verification;
   failed stop forces FAIL and never produces PASS.
2. Realistic live testing: read-only model discovery (/api/v0/models -> /v1/models),
   separation of mock-only trials from live trials, monotonic stop-before-forward
   and cooldown verification.
3. Durable safety: isolated initialized journal and SingleInstanceLock ownership.
4. Correct failure behavior: rich PID/create_time/exit/inference/cooldown metrics
   and guaranteed non-PASS on incomplete/failed trials.
5. Operational compatibility: Mining repo launcher/manifest fidelity and read-only
   live acceptance preflight (external miner check, lock check, LM Studio loaded
   model check, GPU VRAM headroom check).
6. Evidence integrity: `verification_level = "live_hardware"` is only set after
   actual live execution and verification.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx
import psutil
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from resource_coordinator.acceptance_harness import (
    AcceptanceHarness,
    discover_live_model,
    run_live_acceptance_preflight,
)
from resource_coordinator.adapters.miners.manifest import MinerManifest
from resource_coordinator.config import CoordinatorConfig, PolicyConfig, ProcessConfig, ServiceConfig
from resource_coordinator.core.lock import SingleInstanceLock
from resource_coordinator.core.processes import ProcessState
from resource_coordinator.monitors.gpu import GpuDeviceMetrics


def test_evidence_integrity_verification_level_not_premature():
    """
    Focused Correction #6:
    A report must NOT be labeled `verification_level = "live_hardware"` merely upon
    instantiating `AcceptanceHarness(mode="live", ...)`. It must start in a pending/unverified
    state and only transition after actual live execution and verification.
    """
    live_harness = AcceptanceHarness(
        mode="live",
        allow_live_lmstudio=True,
        allow_real_miner=True,
    )
    assert live_harness.report.verification_level != "live_hardware"
    assert live_harness.report.verification_level == "pending_live_verification"
    assert live_harness.report.process_backend == "windows_miner"
    assert live_harness.report.upstream_type == "live_lmstudio"


def test_live_mode_enforces_full_10s_cooldown_by_default():
    """
    Focused Correction #2:
    Live acceptance mode must enforce a >= 10.0s cooldown unless explicitly overridden
    by the internal test flag `_allow_short_cooldown_for_test`.
    """
    with pytest.raises(ValueError, match="10.0 seconds"):
        AcceptanceHarness(
            mode="live",
            cooldown_seconds=0.5,
            allow_live_lmstudio=True,
            allow_real_miner=True,
        )


@pytest.mark.asyncio
async def test_discover_live_model_prefers_loaded_v0_and_falls_back_to_v1():
    """
    Focused Correction #2:
    Model discovery queries LM Studio read-only `/api/v0/models` first to pick an
    already-loaded LLM/VLM (preventing unintended model swaps), and falls back to
    `/v1/models` if `/api/v0/models` is 404. Fails closed if no model is loaded.
    """
    # Case 1: /api/v0/models has both unloaded and loaded models + embedding model
    app_v0_loaded = Starlette(
        routes=[
            Route(
                "/api/v0/models",
                lambda r: JSONResponse(
                    {
                        "data": [
                            {"id": "text-embedding-nomic", "type": "embeddings", "state": "loaded"},
                            {"id": "qwen/qwen3.6-27b", "type": "vlm", "state": "not-loaded"},
                            {"id": "qwen38_23GB", "type": "llm", "state": "loaded", "loaded_context_length": 98304},
                        ]
                    }
                ),
                methods=["GET"],
            )
        ]
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_v0_loaded), base_url="http://lms") as client:
        info = await discover_live_model(client)
        assert info["model_id"] == "qwen38_23GB"
        assert info["source"] == "/api/v0/models"
        assert info["state"] == "loaded"
        assert info["loaded_context_length"] == 98304

    # Case 2: /api/v0/models returns 200 OK but NO LLM/VLM is in state == "loaded" -> fails closed!
    app_v0_none_loaded = Starlette(
        routes=[
            Route(
                "/api/v0/models",
                lambda r: JSONResponse(
                    {
                        "data": [
                            {"id": "qwen38_23GB", "type": "llm", "state": "not-loaded"},
                        ]
                    }
                ),
                methods=["GET"],
            )
        ]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_v0_none_loaded), base_url="http://lms"
    ) as client:
        with pytest.raises(RuntimeError, match="No loaded LLM/VLM model found"):
            await discover_live_model(client)

    # Case 3: /api/v0/models returns 404 -> falls back to /v1/models
    app_v1_fallback = Starlette(
        routes=[
            Route(
                "/v1/models",
                lambda r: JSONResponse(
                    {
                        "data": [
                            {"id": "text-embedding-nomic-embed-text-v1.5"},
                            {"id": "qwen38-local-v1"},
                        ]
                    }
                ),
                methods=["GET"],
            )
        ]
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_v1_fallback), base_url="http://lms") as client:
        info = await discover_live_model(client)
        assert info["model_id"] == "qwen38-local-v1"
        assert info["source"] == "/v1/models"


@pytest.mark.asyncio
async def test_cleanup_runs_in_finally_on_mid_trial_exception(tmp_path: Path):
    """
    Focused Correction #1 & #4:
    If an assertion or upstream exception occurs mid-trial, `finally` MUST still run
    supervised cleanup, stop the miner, release the SingleInstanceLock, verify termination,
    and record FAIL with PID/create_time/cleanup telemetry.
    """
    harness = AcceptanceHarness(mode="simulated", cooldown_seconds=0.05, work_dir=tmp_path)

    async def exploding_handler(request: Request):
        raise RuntimeError("Injected upstream failure mid-trial")

    await harness._run_trial_1_single_request(mock_handler=exploding_handler)

    assert len(harness.report.trials) == 1
    t = harness.report.trials[0]
    assert t.status == "FAIL"
    assert t.metrics.get("cleanup_verified_stopped") is True
    assert t.metrics.get("initial_pid") is not None
    assert t.metrics.get("initial_create_time") is not None

    # SingleInstanceLock must have been released by finally cleanup
    lock = SingleInstanceLock(tmp_path / "coordinator.lock")
    assert lock.acquire() is True
    lock.release()


@pytest.mark.asyncio
async def test_failed_stop_during_cleanup_forces_fail_and_never_passes(tmp_path: Path):
    """
    Focused Correction #1:
    Even if the trial body (request + stop-before-forward + cooldown + restart) succeeds,
    if stopping the miner during `finally` cleanup fails or remains unverified, the trial
    MUST be marked FAIL and must NEVER produce a PASS result.
    """
    harness = AcceptanceHarness(mode="simulated", cooldown_seconds=0.05, work_dir=tmp_path)

    def inject_cleanup_stop_failure(service, system, backend):
        # Allow the first stop (for inference) to succeed, then fail the shutdown stop!
        original_stop = backend.stop
        stop_calls = 0

        async def faulty_stop(timeout: float = 10.0) -> bool:
            nonlocal stop_calls
            stop_calls += 1
            if stop_calls >= 2:
                backend.fail_stop = True
                return False
            return await original_stop(timeout=timeout)

        backend.stop = faulty_stop

    await harness._run_trial_1_single_request(_post_build_hook=inject_cleanup_stop_failure)

    assert len(harness.report.trials) == 1
    t = harness.report.trials[0]
    assert t.status == "FAIL"
    assert t.metrics.get("cleanup_verified_stopped") is False
    assert "Supervised cleanup failed" in (t.error or "")


@pytest.mark.asyncio
async def test_acceptance_harness_durable_journal_and_lock_contention(tmp_path: Path):
    """
    Focused Correction #3:
    Trials use an isolated, explicitly initialized durable journal and SingleInstanceLock.
    If another coordinator holds the lock, the trial fails closed without starting a miner.
    """
    lock_file = tmp_path / "coordinator.lock"
    external_lock = SingleInstanceLock(lock_file)
    assert external_lock.acquire() is True
    try:
        harness = AcceptanceHarness(
            mode="simulated",
            cooldown_seconds=0.05,
            work_dir=tmp_path,
            lock_path=lock_file,
        )
        await harness._run_trial_1_single_request()
        t = harness.report.trials[0]
        assert t.status == "FAIL"
        assert "lock" in (t.error or "").lower() or "start" in (t.error or "").lower()
    finally:
        external_lock.release()

    # Once the external lock is released, running the full sequence succeeds and writes per-trial journals
    harness_ok = AcceptanceHarness(
        mode="simulated",
        cooldown_seconds=0.05,
        work_dir=tmp_path / "clean_run",
    )
    report = await harness_ok.run_all()
    assert report.summary["all_passed"] is True
    assert report.verification_level == "unit_simulation"
    for trial in report.trials:
        journal_path = trial.metrics.get("journal_path")
        assert journal_path is not None
        assert Path(journal_path).is_file()
        assert trial.metrics.get("cleanup_verified_stopped") is True
        assert trial.metrics.get("model_id") == "test-model"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows disposable process test")
async def test_disposable_windows_helper_fault_injection_guarantees_process_termination(tmp_path: Path):
    """
    Focused Correction #1 & #4 (Real Windows OS Process):
    In `disposable_helper` mode (`cscript.exe`), inject a mid-trial fault after `cscript.exe`
    has been launched (and/or restarted). Verify `finally` terminates the real OS process
    and records `cleanup_verified_stopped = True` and `status = "FAIL"`.
    """
    harness = AcceptanceHarness(
        mode="disposable_helper",
        cooldown_seconds=0.1,
        work_dir=tmp_path,
    )
    observed_pids: List[Dict[str, Any]] = []

    def capture_and_fail_after_restart(service, system, backend):
        orig_wait = harness._wait_for_restart

        async def wrapped_wait(sup, b, cd):
            await orig_wait(sup, b, cd)
            info = await b.status()
            if info.pid and info.create_time:
                observed_pids.append({"pid": info.pid, "create_time": info.create_time})
            raise RuntimeError("Injected fault after real Windows helper process restarted")

        harness._wait_for_restart = wrapped_wait  # type: ignore[method-assign]

    await harness._run_trial_1_single_request(_post_build_hook=capture_and_fail_after_restart)

    t = harness.report.trials[0]
    assert t.status == "FAIL"
    assert "Injected fault after real Windows helper process restarted" in (t.error or "")
    assert t.metrics.get("cleanup_verified_stopped") is True
    assert t.metrics.get("descendants_verified_stopped") is True
    assert len(observed_pids) == 1

    # Verify the real OS process is no longer alive
    pid_info = observed_pids[0]
    try:
        proc = psutil.Process(pid_info["pid"])
        assert proc.create_time() != pid_info["create_time"] or not proc.is_running()
    except psutil.NoSuchProcess:
        pass


def test_manifest_resolves_krig_core_clock_and_mining_repo_compatibility():
    """
    Focused Correction #5:
    Verify `MinerManifest.resolve_from_mining_repo` supports `krig_core_clock_mhz` in both
    preview and static modes and matches `C:\\Users\\mcarls\\src\\Mining\\start-prl.ps1`.
    """
    mining_repo = Path(r"C:\Users\mcarls\src\Mining")
    if not (mining_repo / "start-prl.ps1").exists():
        pytest.skip("Mining repo not present")

    manifest_preview = MinerManifest.resolve_from_mining_repo(
        mining_repo=mining_repo,
        miner_type="krig",
        power_limit_watts=0,
        krig_core_clock_mhz=2400,
        use_preview_invocation=True,
    )
    assert manifest_preview.executable.endswith("krig-miner.exe")
    assert Path(manifest_preview.executable).is_file()
    assert "--gpu-cclock" in manifest_preview.arguments
    assert "2400" in manifest_preview.arguments
    assert "--gpu-plimit" not in manifest_preview.arguments
    assert manifest_preview.core_clock_mhz == 2400

    manifest_static = MinerManifest.resolve_from_mining_repo(
        mining_repo=mining_repo,
        miner_type="krig",
        power_limit_watts=0,
        krig_core_clock_mhz=2400,
        use_preview_invocation=False,
    )
    assert manifest_static.arguments == manifest_preview.arguments
    assert manifest_static.core_clock_mhz == 2400


@pytest.mark.asyncio
async def test_read_only_live_acceptance_preflight_checks_conflicts_and_vram(tmp_path: Path):
    """
    Focused Correction #5:
    `run_live_acceptance_preflight` performs strictly read-only checks for:
    - external miner processes
    - coordinator instance lock contention
    - LM Studio reachability and loaded model discovery
    - GPU VRAM headroom warning/blocking when free VRAM is below threshold
    """
    exe_file = tmp_path / "krig-miner.exe"
    exe_file.write_text("dummy", encoding="utf-8")
    lock_file = tmp_path / "coordinator.lock"

    cfg = CoordinatorConfig(
        service=ServiceConfig(
            listen_host="127.0.0.1",
            listen_port=19876,
            upstream_url="http://lms-preflight",
            state_persistence_path=str(tmp_path / "state.json"),
        ),
        processes={
            "krig_miner": ProcessConfig(
                name="krig_miner",
                backend="windows",
                executable=str(exe_file),
                working_directory=str(tmp_path),
                arguments=["--coin", "pearl"],
                new_console=False,
                allow_external_stop=False,
                allow_external_restart=False,
                adopt_external=False,
                allow_force_termination=True,
            )
        },
        policies=[
            PolicyConfig(
                name="stop-krig",
                trigger_event="lmstudio.inference_requested",
                target_process="krig_miner",
                stop_process=True,
                restart_process=True,
                resource="gpu.inference",
                lease_type="shared",
                cooldown_seconds=10.0,
                only_if_stopped_by_coordinator=True,
            )
        ],
    )

    mock_lms = Starlette(
        routes=[
            Route(
                "/api/v0/models",
                lambda r: JSONResponse(
                    {
                        "data": [
                            {
                                "id": "qwen38_23GB",
                                "type": "llm",
                                "state": "loaded",
                                "loaded_context_length": 98304,
                            }
                        ]
                    }
                ),
                methods=["GET"],
            )
        ]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_lms), base_url="http://lms-preflight"
    ) as client:
        # Case 1: Sufficient free VRAM (e.g. 4096 MB free), no external miners, lock free
        result_ok = await run_live_acceptance_preflight(
            cfg,
            http_client=client,
            lock_path=lock_file,
            external_miners_override=[],
            gpu_metrics_override=[
                GpuDeviceMetrics(
                    device_id="gpu-0",
                    utilization_pct=2.0,
                    memory_used_mb=28000.0,
                    memory_total_mb=32607.0,
                    power_draw_w=45.0,
                )
            ],
            min_free_vram_mb=2048.0,
        )
        assert result_ok["ready_for_supervised_live"] is True, result_ok["blocking_reasons"]
        assert result_ok["loaded_model"]["model_id"] == "qwen38_23GB"
        assert result_ok["vram_headroom"]["free_mb"] == pytest.approx(4607.0)

        # Case 2: Tight VRAM (e.g. 30690 MB used / 32607 MB total -> 1917 MB free < 2048 MB threshold)
        result_low_vram = await run_live_acceptance_preflight(
            cfg,
            http_client=client,
            lock_path=lock_file,
            external_miners_override=[],
            gpu_metrics_override=[
                GpuDeviceMetrics(
                    device_id="gpu-0",
                    utilization_pct=5.0,
                    memory_used_mb=30690.0,
                    memory_total_mb=32607.0,
                    power_draw_w=60.0,
                )
            ],
            min_free_vram_mb=2048.0,
        )
        assert result_low_vram["ready_for_supervised_live"] is False
        assert any("VRAM" in err for err in result_low_vram["blocking_reasons"])

        # Case 3: External miner running
        result_ext_miner = await run_live_acceptance_preflight(
            cfg,
            http_client=client,
            lock_path=lock_file,
            external_miners_override=[{"pid": 69988, "name": "krig-miner.exe", "exe": str(exe_file)}],
            gpu_metrics_override=[
                GpuDeviceMetrics(
                    device_id="gpu-0",
                    utilization_pct=99.0,
                    memory_used_mb=30690.0,
                    memory_total_mb=32607.0,
                    power_draw_w=550.0,
                )
            ],
            min_free_vram_mb=1024.0,
        )
        assert result_ext_miner["ready_for_supervised_live"] is False
        assert any("External miner" in err for err in result_ext_miner["blocking_reasons"])

        # Case 4: Held SingleInstanceLock
        held_lock = SingleInstanceLock(lock_file)
        assert held_lock.acquire() is True
        try:
            result_locked = await run_live_acceptance_preflight(
                cfg,
                http_client=client,
                lock_path=lock_file,
                external_miners_override=[],
                gpu_metrics_override=[
                    GpuDeviceMetrics(
                        device_id="gpu-0",
                        utilization_pct=2.0,
                        memory_used_mb=28000.0,
                        memory_total_mb=32607.0,
                        power_draw_w=45.0,
                    )
                ],
                min_free_vram_mb=1024.0,
            )
            assert result_locked["ready_for_supervised_live"] is False
            assert any("SingleInstanceLock" in err for err in result_locked["blocking_reasons"])
        finally:
            held_lock.release()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows process test")
async def test_live_mode_separates_mock_trials_and_records_full_telemetry(tmp_path: Path):
    """
    Focused Correction #2, #4, #6:
    In `live` mode:
    - Discovers loaded model via `/api/v0/models` (`qwen38_23GB`) rather than fabricated IDs.
    - Executes only realistic live-compatible trials (T01..T04) and skips mock-only T05.
    - Records PID, create_time, stopped_before_forward_verified, observed_exit_during_inference,
      inference_result, cooldown_elapsed_seconds, restarted_pid, and cleanup_verified_stopped.
    - Never labels `verification_level = "live_hardware"` when test overrides are used or when a trial fails.
    """
    from starlette.responses import StreamingResponse

    observed_models: List[str] = []

    async def fake_lmstudio_chat(request: Request):
        body = await request.json()
        observed_models.append(body.get("model", ""))
        if body.get("stream"):
            async def sse():
                yield b'data: {"choices": [{"delta": {"content": "OK"}}]}\n\n'
                yield b"data: [DONE]\n\n"
            return StreamingResponse(sse(), media_type="text/event-stream")
        return JSONResponse({"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]})

    fake_lms_app = Starlette(
        routes=[
            Route(
                "/api/v0/models",
                lambda r: JSONResponse(
                    {
                        "data": [
                            {
                                "id": "qwen38_23GB",
                                "type": "llm",
                                "state": "loaded",
                                "loaded_context_length": 98304,
                            }
                        ]
                    }
                ),
                methods=["GET"],
            ),
            Route("/v1/chat/completions", fake_lmstudio_chat, methods=["POST"]),
        ]
    )

    vbs_path = (
        Path(__file__).parent.parent
        / "resource_coordinator"
        / "adapters"
        / "miners"
        / "windows_miner_helper.vbs"
    )
    cscript_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cscript.exe")
    proc_cfg = ProcessConfig(
        name="krig_miner",
        backend="windows",
        executable=cscript_exe,
        arguments=["//B", "//NoLogo", str(vbs_path), "live_rehearsal"],
        working_directory=str(tmp_path),
        stop_timeout_seconds=5.0,
        allow_force_termination=True,
    )

    harness = AcceptanceHarness(
        mode="live",
        cooldown_seconds=0.15,
        allow_live_lmstudio=True,
        allow_real_miner=True,
        miner_process_config=proc_cfg,
        work_dir=tmp_path,
        _allow_short_cooldown_for_test=True,
        _upstream_app_override_for_test=fake_lms_app,
    )
    assert harness.report.verification_level == "pending_live_verification"

    report = await harness.run_all()
    assert report.summary["all_passed"] is True
    assert report.summary["total_trials"] == 4
    assert report.summary["mock_only_trials_skipped"] == 1
    assert [t.trial_id for t in report.trials] == ["T01", "T02", "T03", "T04"]
    # Because test overrides were used, verification_level is "live_contract_rehearsal", not "live_hardware"
    assert report.verification_level == "live_contract_rehearsal"
    assert all(m == "qwen38_23GB" for m in observed_models)

    for t in report.trials:
        assert t.status == "PASS"
        assert t.metrics["model_id"] == "qwen38_23GB"
        assert t.metrics["initial_pid"] is not None
        assert t.metrics["initial_create_time"] is not None
        assert t.metrics["stopped_before_forward_verified"] is True
        assert t.metrics["observed_exit_during_inference"] is True
        assert t.metrics["restarted_pid"] is not None
        assert t.metrics["cleanup_verified_stopped"] is True

