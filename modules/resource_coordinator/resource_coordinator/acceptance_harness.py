"""
Supervised Acceptance Test Harness for Miner / Local LLM Inference Coordination.

Executes and benchmarks the canonical test sequence:
1. Idle baseline and read-only model discovery (/api/v0/models -> /v1/models)
2. Single request stop-before-forward and 10.0s cooldown resumption (T01)
3. Cooldown interruption and cancellation / debounce (T02)
4. Concurrent overlapping request arbitration (T03)
5. Streaming SSE verification with [DONE] terminal detection (T04)
6. Error handling, truncated streams, and restart inhibition latching (T05, mock-only)
7. Guaranteed supervised cleanup in `finally` with miner & descendant stop verification

Outputs machine-readable evidence log (acceptance_evidence_<timestamp>.json)
with high-resolution monotonic timestamps, duration metrics, PID/create_time records,
and status snapshots.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx
import psutil
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from resource_coordinator.config import (
    CoordinatorConfig,
    CoordinatorSystem,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
    build_system,
)
from resource_coordinator.core.durable_state import StateCodec
from resource_coordinator.core.lock import SingleInstanceLock
from resource_coordinator.core.processes import (
    ProcessInfo,
    ProcessLifecycleOwner,
    ProcessState,
    WindowsProcessBackend,
)
from resource_coordinator.core.service import CoordinatorService, ServiceState
from resource_coordinator.monitors.gpu import GpuDeviceMetrics, NvidiaGpuMonitor

logger = logging.getLogger(__name__)

KNOWN_MINER_EXECUTABLES = {
    "krig-miner.exe",
    "srbminer-multi.exe",
    "srbminer.exe",
    "xmrig.exe",
    "lolminer.exe",
    "nbminer.exe",
    "t-rex.exe",
    "gminer.exe",
}


async def discover_live_model(client: httpx.AsyncClient) -> Dict[str, Any]:
    """
    Discover an active, loaded LLM/VLM model via read-only LM Studio endpoints.

    1. Queries `GET /api/v0/models` first. If supported (200 OK), selects a model
       with `state == "loaded"` and `type not in ("embeddings", "embedding")`.
       If `/api/v0/models` returns 200 OK with models but none are in `state == "loaded"`,
       fails closed rather than risking an unintended automatic model load in LM Studio.
    2. If `/api/v0/models` returns 404 (e.g. standard OpenAI-compatible mock server),
       falls back to `GET /v1/models` and selects the first non-embedding model.
    """
    try:
        resp_v0 = await client.get("/api/v0/models")
    except Exception as exc:
        raise RuntimeError(f"Failed to query upstream /api/v0/models: {exc}") from exc

    if resp_v0.status_code == 200:
        payload = resp_v0.json()
        models = payload.get("data", []) if isinstance(payload, dict) else []
        loaded_candidates = [
            m
            for m in models
            if isinstance(m, dict)
            and m.get("id")
            and m.get("state") == "loaded"
            and str(m.get("type", "llm")).lower() not in {"embeddings", "embedding"}
        ]
        if loaded_candidates:
            chosen = loaded_candidates[0]
            return {
                "model_id": str(chosen["id"]),
                "source": "/api/v0/models",
                "state": str(chosen.get("state", "loaded")),
                "type": str(chosen.get("type", "llm")),
                "loaded_context_length": chosen.get("loaded_context_length"),
                "max_context_length": chosen.get("max_context_length"),
            }
        raise RuntimeError(
            "No loaded LLM/VLM model found in LM Studio (/api/v0/models returned no model with state='loaded'; "
            "refusing to send inference request that could trigger an unintended model load)"
        )

    if resp_v0.status_code != 404:
        raise RuntimeError(f"Unexpected status {resp_v0.status_code} from /api/v0/models")

    try:
        resp_v1 = await client.get("/v1/models")
    except Exception as exc:
        raise RuntimeError(f"Failed to query upstream /v1/models: {exc}") from exc

    if resp_v1.status_code != 200:
        raise RuntimeError(f"Upstream /v1/models returned HTTP {resp_v1.status_code}")

    payload_v1 = resp_v1.json()
    models_v1 = payload_v1.get("data", []) if isinstance(payload_v1, dict) else []
    v1_candidates = [
        m
        for m in models_v1
        if isinstance(m, dict)
        and m.get("id")
        and not str(m.get("id", "")).lower().startswith("text-embedding")
        and str(m.get("type", "llm")).lower() not in {"embeddings", "embedding"}
    ]
    if not v1_candidates:
        raise RuntimeError("No usable LLM/VLM model found in /v1/models response")

    chosen_v1 = v1_candidates[0]
    return {
        "model_id": str(chosen_v1["id"]),
        "source": "/v1/models",
        "state": "assumed_loaded",
        "type": str(chosen_v1.get("type", "llm")),
        "loaded_context_length": chosen_v1.get("loaded_context_length"),
        "max_context_length": chosen_v1.get("max_context_length"),
    }


async def run_live_acceptance_preflight(
    config: CoordinatorConfig,
    http_client: Optional[httpx.AsyncClient] = None,
    lock_path: Optional[str | Path] = None,
    gpu_metrics_override: Optional[List[GpuDeviceMetrics]] = None,
    external_miners_override: Optional[List[Dict[str, Any]]] = None,
    min_free_vram_mb: float = 1024.0,
) -> Dict[str, Any]:
    """
    Strictly read-only preflight check for supervised live hardware acceptance.

    Does NOT launch miners, alter GPU clocks/power limits, or interrupt active services.
    Checks:
    1. External miner processes in OS process table (`psutil.process_iter`).
    2. Coordinator `SingleInstanceLock` availability.
    3. `CoordinatorService.preflight_check()` and process ownership flags (`adopt_external == False`).
    4. LM Studio upstream reachability and currently loaded LLM/VLM model (`/api/v0/models`).
    5. GPU VRAM headroom (`free_mb >= min_free_vram_mb`).
    """
    blocking_reasons: List[str] = []
    warnings: List[str] = []

    # 1. Inspect OS process table for any running miner processes
    if external_miners_override is not None:
        external_miners = list(external_miners_override)
    else:
        configured_exe_names = {
            Path(p.executable).name.casefold() for p in config.processes.values() if p.executable
        }
        miner_names = KNOWN_MINER_EXECUTABLES | configured_exe_names
        external_miners = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pname = (proc.info.get("name") or "").strip()
                pexe = (proc.info.get("exe") or "").strip()
                if pname.casefold() in miner_names or (pexe and Path(pexe).name.casefold() in miner_names):
                    external_miners.append(
                        {
                            "pid": proc.info.get("pid"),
                            "name": pname,
                            "exe": pexe,
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    if external_miners:
        blocking_reasons.append(
            f"External miner process(es) currently running: {external_miners}. "
            "Stop external miners manually before starting supervised acceptance."
        )

    # 2. Probe SingleInstanceLock availability without holding it
    resolved_lock_path = lock_path
    if not resolved_lock_path and getattr(config.service, "state_persistence_path", ""):
        resolved_lock_path = Path(config.service.state_persistence_path).with_suffix(".lock")
    lock_available = True
    if resolved_lock_path:
        probe_lock = SingleInstanceLock(resolved_lock_path)
        if probe_lock.acquire():
            probe_lock.release()
        else:
            lock_available = False
            blocking_reasons.append(
                f"Coordinator SingleInstanceLock at '{resolved_lock_path}' is already held by another process."
            )

    # 3. Validate coordinator configuration and ownership flags
    system = build_system(config, use_fake_processes=False)
    try:
        service = CoordinatorService(system=system)
        config_passed, config_messages = service.preflight_check()
    finally:
        await system.gateway.close()
    if not config_passed:
        for msg in config_messages:
            if msg.startswith("ERROR"):
                blocking_reasons.append(msg)

    for pname, pcfg in config.processes.items():
        if pcfg.adopt_external or pcfg.allow_external_stop or pcfg.allow_external_restart:
            blocking_reasons.append(
                f"Process '{pname}' enables external adoption/stop/restart, which is forbidden for supervised acceptance."
            )
        gpu_mutating_flags = {"--gpu-plimit", "--gpu-cclock", "--gpu-coffset", "--gpu-mclock"}
        present_mutating = [arg for arg in pcfg.arguments if arg in gpu_mutating_flags]
        if present_mutating:
            warnings.append(
                f"Process '{pname}' arguments include GPU clock/power flags {present_mutating}; "
                "verify explicit operator authorization before live execution."
            )

    # 4. Read-only LM Studio loaded model discovery
    loaded_model: Optional[Dict[str, Any]] = None
    close_client = False
    client = http_client
    if client is None:
        client = httpx.AsyncClient(base_url=config.service.upstream_url, timeout=5.0)
        close_client = True
    try:
        loaded_model = await discover_live_model(client)
    except Exception as exc:
        blocking_reasons.append(f"LM Studio upstream model discovery failed: {exc}")
    finally:
        if close_client and client is not None:
            await client.aclose()

    # 5. Read-only GPU telemetry & VRAM headroom assessment
    gpus = gpu_metrics_override if gpu_metrics_override is not None else await NvidiaGpuMonitor().get_metrics()
    vram_headroom: Optional[Dict[str, Any]] = None
    if gpus:
        primary = gpus[0]
        free_mb = max(0.0, primary.memory_total_mb - primary.memory_used_mb)
        vram_headroom = {
            "device_id": primary.device_id,
            "memory_used_mb": primary.memory_used_mb,
            "memory_total_mb": primary.memory_total_mb,
            "free_mb": free_mb,
            "min_required_free_mb": min_free_vram_mb,
            "sufficient": free_mb >= min_free_vram_mb,
        }
        if free_mb < min_free_vram_mb:
            blocking_reasons.append(
                f"Insufficient free GPU VRAM for safe concurrent resident LLM + KRig launch: "
                f"{free_mb:.0f} MiB free < {min_free_vram_mb:.0f} MiB minimum threshold "
                f"({primary.memory_used_mb:.0f}/{primary.memory_total_mb:.0f} MiB used). "
                "Reduce LM Studio loaded_context_length or KV cache allocation before launching KRig."
            )
    else:
        warnings.append("No NVIDIA GPU metrics returned by nvidia-smi during preflight.")

    return {
        "timestamp": time.time(),
        "ready_for_supervised_live": len(blocking_reasons) == 0,
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "external_miners": external_miners,
        "lock_available": lock_available,
        "config_preflight_passed": config_passed,
        "config_messages": config_messages,
        "loaded_model": loaded_model,
        "vram_headroom": vram_headroom,
        "gpus": [
            {
                "device_id": g.device_id,
                "utilization_pct": g.utilization_pct,
                "memory_used_mb": g.memory_used_mb,
                "memory_total_mb": g.memory_total_mb,
                "power_draw_w": g.power_draw_w,
            }
            for g in gpus
        ],
    }


@dataclass
class TrialEvidence:
    trial_id: str
    name: str
    status: str = "PENDING"  # PASS, FAIL, NOT_RUN
    start_monotonic: float = 0.0
    end_monotonic: float = 0.0
    duration_seconds: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    diagnostics: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class AcceptanceReport:
    timestamp: float = field(default_factory=time.time)
    mode: str = "simulated"  # "simulated", "disposable_helper", "live"
    process_backend: str = "fake"  # "fake", "windows_cscript", "windows_miner"
    upstream_type: str = "mock"  # "mock", "live_lmstudio"
    verification_level: str = "unit_simulation"
    trials: List[TrialEvidence] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mode": self.mode,
            "process_backend": self.process_backend,
            "upstream_type": self.upstream_type,
            "verification_level": self.verification_level,
            "trials": [asdict(t) for t in self.trials],
            "summary": self.summary,
        }

    def save(self, output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


class AcceptanceHarness:
    """
    Automated execution runner for the supervised coordination test sequence.
    """

    def __init__(
        self,
        mode: str = "simulated",
        cooldown_seconds: Optional[float] = None,
        allow_live_lmstudio: bool = False,
        allow_real_miner: bool = False,
        lmstudio_url: str = "http://127.0.0.1:1234",
        miner_process_config: Optional[ProcessConfig] = None,
        work_dir: Optional[str | Path] = None,
        lock_path: Optional[str | Path] = None,
        _allow_short_cooldown_for_test: bool = False,
        _upstream_app_override_for_test: Any = None,
    ) -> None:
        if mode not in {"simulated", "disposable_helper", "live"}:
            raise ValueError(f"Unsupported acceptance harness mode: {mode!r}")

        self.mode = mode
        self.allow_live_lmstudio = allow_live_lmstudio
        self.allow_real_miner = allow_real_miner
        self.lmstudio_url = lmstudio_url
        self.miner_process_config = miner_process_config
        self._allow_short_cooldown_for_test = _allow_short_cooldown_for_test
        self._upstream_app_override_for_test = _upstream_app_override_for_test

        if work_dir is not None:
            self._base_work_dir = Path(work_dir)
            self._base_work_dir.mkdir(parents=True, exist_ok=True)
            self._temp_dir_obj = None
        else:
            self._temp_dir_obj = tempfile.TemporaryDirectory(prefix="rc_acceptance_")
            self._base_work_dir = Path(self._temp_dir_obj.name)

        self.lock_path = Path(lock_path) if lock_path is not None else (self._base_work_dir / "coordinator.lock")

        if mode == "live":
            if not allow_live_lmstudio or not allow_real_miner:
                raise ValueError(
                    "Live acceptance mode requires both allow_live_lmstudio=True and allow_real_miner=True"
                )
            effective_cooldown = 10.0 if cooldown_seconds is None else float(cooldown_seconds)
            if effective_cooldown < 10.0 and not _allow_short_cooldown_for_test:
                raise ValueError("Live acceptance mode requires cooldown_seconds >= 10.0 seconds")
            process_backend = "windows_miner"
            upstream_type = "live_lmstudio"
            # Focused Correction #6: Never label a report "live_hardware" before actual live execution
            verification_level = "pending_live_verification"
        elif mode == "disposable_helper":
            if os.name != "nt":
                raise RuntimeError("Disposable helper acceptance mode requires Windows (os.name == 'nt')")
            effective_cooldown = 0.2 if cooldown_seconds is None else float(cooldown_seconds)
            process_backend = "windows_cscript"
            upstream_type = "mock"
            verification_level = "os_process_contract"
        else:
            effective_cooldown = 0.1 if cooldown_seconds is None else float(cooldown_seconds)
            process_backend = "fake"
            upstream_type = "mock"
            verification_level = "unit_simulation"

        self.cooldown_seconds = effective_cooldown
        self.report = AcceptanceReport(
            mode=mode,
            process_backend=process_backend,
            upstream_type=upstream_type,
            verification_level=verification_level,
        )

    async def run_all(self, output_file: Optional[str | Path] = None) -> AcceptanceReport:
        """Run all applicable test sequence trials and return the structured acceptance report."""
        logger.info("Starting Acceptance Test Sequence in mode: %s", self.mode)
        if self.mode == "live" and (
            self.miner_process_config is None or self.miner_process_config.backend != "windows"
        ):
            raise RuntimeError(
                "Live acceptance mode requires an explicit Windows miner_process_config; "
                "refusing to fall back to simulated backend"
            )

        await self._run_trial_1_single_request()
        await self._run_trial_2_cooldown_interruption()
        await self._run_trial_3_concurrent_requests()
        await self._run_trial_4_streaming_sse()

        mock_only_skipped = 0
        if self.mode != "live":
            await self._run_trial_5_error_inhibition()
        else:
            mock_only_skipped = 1

        total = len(self.report.trials)
        passed = sum(1 for t in self.report.trials if t.status == "PASS")
        failed = sum(1 for t in self.report.trials if t.status == "FAIL")
        all_passed = passed == total and total > 0

        # Focused Correction #6: Promote verification_level to "live_hardware" ONLY after
        # actual live execution and verification of all live trials against real hardware & upstream.
        if self.mode == "live":
            is_test_override = (
                self._allow_short_cooldown_for_test or self._upstream_app_override_for_test is not None
            )
            if all_passed and total >= 4 and not is_test_override:
                self.report.verification_level = "live_hardware"
            elif all_passed and is_test_override:
                self.report.verification_level = "live_contract_rehearsal"
            else:
                self.report.verification_level = "failed_live_verification"

        self.report.summary = {
            "total_trials": total,
            "passed": passed,
            "failed": failed,
            "mock_only_trials_skipped": mock_only_skipped,
            "all_passed": all_passed,
            "verification_level": self.report.verification_level,
        }

        if output_file:
            self.report.save(output_file)
            logger.info("Saved acceptance report to %s", output_file)

        return self.report

    def _build_test_harness(
        self,
        trial_id: str,
        cooldown_seconds: float,
        mock_handler: Optional[Callable] = None,
    ):
        """Build isolated per-trial environment with durable journal, single-instance lock, and telemetry."""
        trial_dir = self._base_work_dir / trial_id.lower()
        trial_dir.mkdir(parents=True, exist_ok=True)
        journal_path = trial_dir / f"journal_{trial_id.lower()}.json"
        StateCodec.initialize(journal_path)

        telemetry: Dict[str, Any] = {
            "journal_path": str(journal_path),
            "lock_path": str(self.lock_path),
            "stop_verified_monotonic": None,
            "first_forward_monotonic": None,
            "stopped_before_forward_verified": False,
            "observed_running_during_inference": False,
            "cooldown_started_monotonic": None,
            "restarted_monotonic": None,
            "observed_pids": [],
        }

        async def default_upstream_handler(request):
            body = await request.json()
            is_stream = body.get("stream", False)
            if is_stream:

                async def event_generator():
                    yield b'data: {"choices": [{"delta": {"content": "OK"}}]}\n\n'
                    await asyncio.sleep(0.01)
                    yield b"data: [DONE]\n\n"

                return StreamingResponse(event_generator(), media_type="text/event-stream")
            return JSONResponse({"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]})

        raw_handler = mock_handler or default_upstream_handler

        async def instrumented_mock_handler(request):
            now_mono = time.monotonic()
            if telemetry["first_forward_monotonic"] is None:
                telemetry["first_forward_monotonic"] = now_mono
            info = await supervisor.status()
            if info.state != ProcessState.STOPPED:
                telemetry["observed_running_during_inference"] = True
            elif (
                telemetry["stop_verified_monotonic"] is not None
                and telemetry["stop_verified_monotonic"] <= now_mono
            ):
                telemetry["stopped_before_forward_verified"] = True
            return await raw_handler(request)

        mock_upstream_app = Starlette(
            routes=[
                Route("/v1/chat/completions", instrumented_mock_handler, methods=["POST"]),
                Route(
                    "/api/v0/models",
                    lambda r: JSONResponse(
                        {
                            "data": [
                                {
                                    "id": "test-model",
                                    "type": "llm",
                                    "state": "loaded",
                                    "loaded_context_length": 8192,
                                }
                            ]
                        }
                    ),
                    methods=["GET"],
                ),
                Route("/v1/models", lambda r: JSONResponse({"data": [{"id": "test-model"}]}), methods=["GET"]),
            ]
        )

        upstream_client: Optional[httpx.AsyncClient] = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_upstream_app),
            base_url="http://mock-upstream",
        )

        if self.mode == "live":
            if self.miner_process_config is None or self.miner_process_config.backend != "windows":
                raise RuntimeError(
                    "Live acceptance mode requires an explicit Windows miner_process_config; "
                    "refusing to fall back to simulated backend"
                )
            target_proc_name = self.miner_process_config.name
            cfg = CoordinatorConfig(
                service=ServiceConfig(
                    upstream_url=self.lmstudio_url,
                    state_persistence_path=str(journal_path),
                ),
                processes={target_proc_name: self.miner_process_config},
                policies=[
                    PolicyConfig(
                        name="stop-miner-live",
                        trigger_event="lmstudio.inference_requested",
                        target_process=target_proc_name,
                        stop_process=True,
                        restart_process=True,
                        resource="gpu.inference",
                        lease_type="shared",
                        cooldown_seconds=cooldown_seconds,
                        only_if_stopped_by_coordinator=True,
                    )
                ],
            )
            system = build_system(cfg, use_fake_processes=False)
            if self._upstream_app_override_for_test is not None:
                await_close = upstream_client
                asyncio.create_task(await_close.aclose())
                upstream_client = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self._upstream_app_override_for_test),
                    base_url=self.lmstudio_url,
                )
                system.gateway._http_client = upstream_client
            elif mock_handler is not None:
                system.gateway._http_client = upstream_client
            else:
                await_close = upstream_client
                upstream_client = None
                # Close unused mock client asynchronously when loop runs
                asyncio.create_task(await_close.aclose())
            service = CoordinatorService(
                system,
                start_process_on_ready=target_proc_name,
                stop_process_on_shutdown=target_proc_name,
                lock_path=self.lock_path,
            )
            supervisor = system.supervisors[target_proc_name]
            backend = supervisor.backend
        elif self.mode == "disposable_helper":
            if os.name != "nt":
                raise RuntimeError("Disposable helper acceptance mode requires Windows (os.name == 'nt')")
            vbs_path = Path(__file__).parent / "adapters" / "miners" / "windows_miner_helper.vbs"
            cscript_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cscript.exe")
            proc_cfg = ProcessConfig(
                name="krig",
                backend="windows",
                executable=cscript_exe,
                arguments=["//B", "//NoLogo", str(vbs_path), f"rc_{trial_id}"],
                working_directory=str(trial_dir),
                stop_timeout_seconds=5.0,
                allow_force_termination=True,
            )
            cfg = CoordinatorConfig(
                service=ServiceConfig(
                    upstream_url="http://mock-upstream",
                    state_persistence_path=str(journal_path),
                ),
                processes={"krig": proc_cfg},
                policies=[
                    PolicyConfig(
                        name="stop-krig",
                        trigger_event="lmstudio.inference_requested",
                        target_process="krig",
                        stop_process=True,
                        restart_process=True,
                        resource="gpu.inference",
                        lease_type="shared",
                        cooldown_seconds=cooldown_seconds,
                        only_if_stopped_by_coordinator=True,
                    )
                ],
            )
            system = build_system(cfg, use_fake_processes=False)
            system.gateway._http_client = upstream_client
            service = CoordinatorService(
                system,
                start_process_on_ready="krig",
                stop_process_on_shutdown="krig",
                lock_path=self.lock_path,
            )
            supervisor = system.supervisors["krig"]
            backend = supervisor.backend
        else:
            cfg = CoordinatorConfig(
                service=ServiceConfig(
                    upstream_url="http://mock-upstream",
                    state_persistence_path=str(journal_path),
                ),
                processes={"krig": ProcessConfig(name="krig", backend="fake")},
                policies=[
                    PolicyConfig(
                        name="stop-krig",
                        trigger_event="lmstudio.inference_requested",
                        target_process="krig",
                        stop_process=True,
                        restart_process=True,
                        resource="gpu.inference",
                        lease_type="shared",
                        cooldown_seconds=cooldown_seconds,
                        only_if_stopped_by_coordinator=True,
                    )
                ],
            )
            system = build_system(cfg, use_fake_processes=True)
            system.gateway._http_client = upstream_client
            service = CoordinatorService(
                system,
                start_process_on_ready="krig",
                stop_process_on_shutdown="krig",
                lock_path=self.lock_path,
            )
            supervisor = system.supervisors["krig"]
            backend = supervisor.backend

        # Attach dispatcher listeners for monotonic timing and PID tracking
        async def on_process_started(event: Any) -> None:
            now_mono = time.monotonic()
            info = await supervisor.status()
            if info.pid is not None and info.create_time is not None:
                telemetry["observed_pids"].append({"pid": info.pid, "create_time": info.create_time})
            if telemetry["cooldown_started_monotonic"] is not None:
                telemetry["restarted_monotonic"] = now_mono
                telemetry["restarted_pid"] = info.pid
                telemetry["restarted_create_time"] = info.create_time

        async def on_process_stopped(event: Any) -> None:
            if telemetry["stop_verified_monotonic"] is None:
                telemetry["stop_verified_monotonic"] = time.monotonic()

        async def on_resource_acquired(event: Any) -> None:
            now_mono = time.monotonic()
            if telemetry["first_forward_monotonic"] is None:
                telemetry["first_forward_monotonic"] = now_mono
            info = await supervisor.status()
            if info.state != ProcessState.STOPPED:
                telemetry["observed_running_during_inference"] = True
            elif (
                telemetry["stop_verified_monotonic"] is not None
                and telemetry["stop_verified_monotonic"] <= now_mono
            ):
                telemetry["stopped_before_forward_verified"] = True

        async def on_cooldown_started(event: Any) -> None:
            telemetry["cooldown_started_monotonic"] = time.monotonic()

        system.dispatcher.on("process.started", on_process_started)
        system.dispatcher.on("process.stopped", on_process_stopped)
        system.dispatcher.on("resource.acquired", on_resource_acquired)
        system.dispatcher.on("resource.cooldown_started", on_cooldown_started)

        gateway_app = system.gateway.create_app(service)
        coordinator_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway_app),
            base_url="http://coordinator",
        )

        return service, system, coordinator_client, upstream_client, supervisor, backend, telemetry

    async def _cleanup_trial_harness(
        self,
        t: TrialEvidence,
        service: Optional[CoordinatorService],
        system: Optional[CoordinatorSystem],
        client: Optional[httpx.AsyncClient],
        upstream_client: Optional[httpx.AsyncClient],
        supervisor: Any,
        backend: Any,
        telemetry: Optional[Dict[str, Any]],
    ) -> None:
        """
        Focused Correction #1 & #4:
        Guaranteed supervised cleanup executed in `finally` of every trial.
        Verifies miner and descendant termination. Overrides trial status to FAIL
        if process stop cannot be verified.
        """
        if telemetry:
            t.metrics.setdefault("journal_path", telemetry.get("journal_path"))
            t.metrics.setdefault("lock_path", telemetry.get("lock_path"))

        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:
                t.diagnostics.append(f"Error closing coordinator client: {exc}")

        if upstream_client is not None:
            try:
                await upstream_client.aclose()
            except Exception as exc:
                t.diagnostics.append(f"Error closing mock upstream client: {exc}")

        cleanup_errors: List[str] = []
        if service is not None:
            try:
                await service.stop(reason=f"trial_{t.trial_id}_cleanup")
                if (
                    service.state == ServiceState.RECONCILIATION_REQUIRED
                    and service.failure_reason
                    and "unverified process stop" in service.failure_reason
                ):
                    cleanup_errors.append(f"Service shutdown reported: {service.failure_reason}")
            except Exception as exc:
                cleanup_errors.append(f"Exception in service.stop(): {exc}")

        backend_stopped = True
        if backend is not None:
            try:
                info: ProcessInfo = await backend.status()
                if info.state != ProcessState.STOPPED:
                    stopped_ok = await backend.stop(timeout=5.0)
                    info = await backend.status()
                    if not stopped_ok or info.state != ProcessState.STOPPED:
                        backend_stopped = False
                        cleanup_errors.append(
                            f"Backend process '{info.name}' remained in state '{info.state.value}' (PID {info.pid}) after stop"
                        )
            except Exception as exc:
                backend_stopped = False
                cleanup_errors.append(f"Exception verifying backend stop: {exc}")

        descendants_stopped = True
        observed_pids = (telemetry or {}).get("observed_pids", [])
        if os.name == "nt" and isinstance(backend, WindowsProcessBackend):
            for ident in observed_pids:
                pid = ident.get("pid")
                ct = ident.get("create_time")
                if not pid or not ct:
                    continue
                try:
                    proc = psutil.Process(pid)
                    if proc.create_time() == ct:
                        children = proc.children(recursive=True)
                        if proc.is_running():
                            proc.terminate()
                            try:
                                proc.wait(timeout=3.0)
                            except psutil.TimeoutExpired:
                                proc.kill()
                                proc.wait(timeout=2.0)
                        for child in children:
                            try:
                                if child.is_running():
                                    child.terminate()
                                    child.wait(timeout=2.0)
                            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                                pass
                        if proc.is_running() or any(c.is_running() for c in children):
                            descendants_stopped = False
                            cleanup_errors.append(f"Owned Windows PID {pid} or its descendants remained running")
                except psutil.NoSuchProcess:
                    continue
                except Exception as exc:
                    descendants_stopped = False
                    cleanup_errors.append(f"Error verifying Windows PID {pid} cleanup: {exc}")

        cleanup_verified = bool(backend_stopped and descendants_stopped and not cleanup_errors)
        t.metrics["cleanup_verified_stopped"] = cleanup_verified
        t.metrics["descendants_verified_stopped"] = descendants_stopped

        if not cleanup_verified:
            t.status = "FAIL"
            err_detail = "; ".join(cleanup_errors) or "unverified miner stop"
            cleanup_msg = f"Supervised cleanup failed: {err_detail}"
            t.error = f"{t.error} | {cleanup_msg}" if t.error else cleanup_msg

    async def _wait_for_restart(self, supervisor: Any, backend: Any, cooldown: float) -> ProcessInfo:
        deadline = time.monotonic() + cooldown + 3.0
        while time.monotonic() < deadline:
            info = await supervisor.status()
            if info.state == ProcessState.RUNNING:
                return info
            await asyncio.sleep(0.05)
        return await supervisor.status()

    def _record_trial_telemetry(self, t: TrialEvidence, telemetry: Dict[str, Any], cooldown: float) -> None:
        t.metrics["stopped_before_forward_verified"] = bool(telemetry.get("stopped_before_forward_verified"))
        t.metrics["observed_exit_during_inference"] = not bool(telemetry.get("observed_running_during_inference"))
        t.metrics["cooldown_target_seconds"] = cooldown
        cd_start = telemetry.get("cooldown_started_monotonic")
        restarted_at = telemetry.get("restarted_monotonic")
        if cd_start is not None and restarted_at is not None:
            t.metrics["cooldown_elapsed_seconds"] = restarted_at - cd_start
        if telemetry.get("restarted_pid") is not None:
            t.metrics["restarted_pid"] = telemetry.get("restarted_pid")
            t.metrics["restarted_create_time"] = telemetry.get("restarted_create_time")

    async def _run_trial_1_single_request(
        self,
        mock_handler: Optional[Callable] = None,
        _post_build_hook: Optional[Callable] = None,
    ) -> None:
        """Trial 1: Single request stop-before-forward and exact idle cooldown restart."""
        t = TrialEvidence(trial_id="T01", name="Single Request Stop Before Forward and Cooldown")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = None
        try:
            cooldown = self.cooldown_seconds
            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T01",
                cooldown_seconds=cooldown,
                mock_handler=mock_handler,
            )
            if _post_build_hook is not None:
                _post_build_hook(service, system, backend)

            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            # Miner must still be running after read-only model discovery
            assert (await supervisor.status()).state == ProcessState.RUNNING

            t_req_start = time.monotonic()
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                    "max_tokens": 8,
                    "temperature": 0.0,
                },
            )
            t_req_end = time.monotonic()
            t.metrics["inference_result"] = {"status_code": resp.status_code}
            t.metrics["request_duration_ms"] = (t_req_end - t_req_start) * 1000.0

            assert resp.status_code == 200
            assert (await supervisor.status()).state == ProcessState.STOPPED
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True
            assert telemetry["stopped_before_forward_verified"] is True
            assert telemetry["observed_running_during_inference"] is False

            resumed_info = await self._wait_for_restart(supervisor, backend, cooldown)
            assert resumed_info.state == ProcessState.RUNNING
            t.metrics["miner_restarted"] = True
            t.metrics["restarted_pid"] = resumed_info.pid
            t.metrics["restarted_create_time"] = resumed_info.create_time
            self._record_trial_telemetry(t, telemetry, cooldown)
            if t.metrics.get("cooldown_elapsed_seconds") is not None:
                assert t.metrics["cooldown_elapsed_seconds"] >= cooldown - 0.15
            t.status = "PASS"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 1 failed: %s", exc)
        finally:
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_2_cooldown_interruption(self) -> None:
        """Trial 2: Request arriving during cooldown cancels restart immediately."""
        t = TrialEvidence(trial_id="T02", name="Cooldown Interruption and Debounce")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = None
        try:
            cooldown = self.cooldown_seconds
            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T02",
                cooldown_seconds=cooldown,
            )
            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                "max_tokens": 8,
                "temperature": 0.0,
            }

            resp1 = await client.post("/v1/chat/completions", json=payload)
            assert resp1.status_code == 200
            assert (await supervisor.status()).state == ProcessState.STOPPED
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            # Send Request 2 at 50% of cooldown duration
            await asyncio.sleep(cooldown * 0.5)
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True
            assert (await supervisor.status()).state == ProcessState.STOPPED

            resp2 = await client.post("/v1/chat/completions", json=payload)
            t.metrics["inference_result"] = {
                "first_status_code": resp1.status_code,
                "second_status_code": resp2.status_code,
            }
            assert resp2.status_code == 200

            # Cooldown was reset; miner must STILL be stopped immediately after second completion
            assert (await supervisor.status()).state == ProcessState.STOPPED
            t.metrics["cooldown_cancelled_on_arrival"] = True

            resumed_info = await self._wait_for_restart(supervisor, backend, cooldown)
            assert resumed_info.state == ProcessState.RUNNING
            t.metrics["restarted_pid"] = resumed_info.pid
            t.metrics["restarted_create_time"] = resumed_info.create_time
            self._record_trial_telemetry(t, telemetry, cooldown)
            t.status = "PASS"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 2 failed: %s", exc)
        finally:
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_3_concurrent_requests(self) -> None:
        """Trial 3: Overlapping concurrent requests: miner stays stopped until last completion + cooldown."""
        t = TrialEvidence(trial_id="T03", name="Concurrent Overlapping Requests")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = None
        try:
            cooldown = self.cooldown_seconds

            # In simulated/disposable_helper modes, use a deterministic staggered handler
            req_counter = 0

            async def staggered_mock_handler(request):
                nonlocal req_counter
                req_counter += 1
                delay = 0.05 if req_counter == 1 else 0.14
                await asyncio.sleep(delay)
                return JSONResponse({"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]})

            mock_h = staggered_mock_handler if self.mode != "live" else None
            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T03",
                cooldown_seconds=cooldown,
                mock_handler=mock_h,
            )
            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                "max_tokens": 8,
                "temperature": 0.0,
            }

            task1 = asyncio.create_task(client.post("/v1/chat/completions", json=payload))
            task2 = asyncio.create_task(client.post("/v1/chat/completions", json=payload))

            if self.mode != "live":
                resp1 = await task1
                assert resp1.status_code == 200
                # Task 2 is still running: miner MUST be stopped and cooldown NOT active
                assert (await supervisor.status()).state == ProcessState.STOPPED
                assert system.lease_mgr.active_count("gpu.inference") == 1
                assert system.lease_mgr.is_cooling_down("gpu.inference") is False
                resp2 = await task2
                assert resp2.status_code == 200
            else:
                resp1, resp2 = await asyncio.gather(task1, task2)
                assert resp1.status_code == 200
                assert resp2.status_code == 200
                assert (await supervisor.status()).state == ProcessState.STOPPED

            t.metrics["inference_result"] = {
                "resp1_status": resp1.status_code,
                "resp2_status": resp2.status_code,
            }
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            resumed_info = await self._wait_for_restart(supervisor, backend, cooldown)
            assert resumed_info.state == ProcessState.RUNNING
            t.metrics["restarted_pid"] = resumed_info.pid
            t.metrics["restarted_create_time"] = resumed_info.create_time
            self._record_trial_telemetry(t, telemetry, cooldown)
            t.status = "PASS"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 3 failed: %s", exc)
        finally:
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_4_streaming_sse(self) -> None:
        """Trial 4: Streaming SSE request with verified [DONE] marker."""
        t = TrialEvidence(trial_id="T04", name="Streaming SSE Terminal Detection")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = None
        try:
            cooldown = self.cooldown_seconds
            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T04",
                cooldown_seconds=cooldown,
            )
            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                    "max_tokens": 8,
                    "temperature": 0.0,
                    "stream": True,
                },
            )
            t.metrics["inference_result"] = {
                "status_code": resp.status_code,
                "done_marker_observed": "[DONE]" in resp.text,
            }
            assert resp.status_code == 200
            assert "[DONE]" in resp.text

            assert system.lease_mgr.is_cooling_down("gpu.inference") is True
            resumed_info = await self._wait_for_restart(supervisor, backend, cooldown)
            assert resumed_info.state == ProcessState.RUNNING
            t.metrics["restarted_pid"] = resumed_info.pid
            t.metrics["restarted_create_time"] = resumed_info.create_time
            self._record_trial_telemetry(t, telemetry, cooldown)
            t.status = "PASS"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 4 failed: %s", exc)
        finally:
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_5_error_inhibition(self) -> None:
        """Trial 5 (Mock-only fault injection): Truncated stream latches restart inhibition."""
        t = TrialEvidence(trial_id="T05", name="Error and Truncated Stream Restart Inhibition")
        t.start_monotonic = time.monotonic()
        service = system = client = upstream_client = supervisor = backend = telemetry = None
        try:
            if self.mode == "live":
                raise RuntimeError("Trial 5 uses a synthetic truncated stream handler and is mock-only")

            cooldown = self.cooldown_seconds

            async def truncated_stream_handler(request):
                async def gen():
                    yield b'data: {"choices": [{"delta": {"content": "part"}}]}\n\n'
                    # Abrupt close without [DONE]

                return StreamingResponse(gen(), media_type="text/event-stream")

            service, system, client, upstream_client, supervisor, backend, telemetry = self._build_test_harness(
                trial_id="T05",
                cooldown_seconds=cooldown,
                mock_handler=truncated_stream_handler,
            )
            if not await service.start():
                raise RuntimeError(f"Service failed to start: {service.failure_reason}")

            initial_info = await supervisor.status()
            assert initial_info.state == ProcessState.RUNNING
            t.metrics["initial_pid"] = initial_info.pid
            t.metrics["initial_create_time"] = initial_info.create_time

            model_info = await discover_live_model(client)
            model_id = model_info["model_id"]
            t.metrics["model_id"] = model_id

            resp = await client.post(
                "/v1/chat/completions",
                json={"model": model_id, "messages": [], "stream": True},
            )
            t.metrics["inference_result"] = {
                "status_code": resp.status_code,
                "truncated": "[DONE]" not in resp.text,
            }
            assert resp.status_code == 200
            assert "part" in resp.text

            # Restart MUST be inhibited
            assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True

            # Wait past cooldown duration: miner MUST NOT restart
            await asyncio.sleep(cooldown + 0.05)
            assert (await supervisor.status()).state == ProcessState.STOPPED

            t.metrics["restart_inhibited"] = True
            self._record_trial_telemetry(t, telemetry, cooldown)
            t.status = "PASS"
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 5 failed: %s", exc)
        finally:
            await self._cleanup_trial_harness(
                t, service, system, client, upstream_client, supervisor, backend, telemetry
            )
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)
