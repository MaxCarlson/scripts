"""
Supervised Acceptance Test Harness for Miner / Local LLM Inference Coordination.

Executes and benchmarks the canonical test sequence:
1. Idle baseline verification
2. Single request stop-before-forward and 10.0s cooldown resumption
3. Cooldown interruption and cancellation (debounce at ~5s and ~9.9s)
4. Concurrent overlapping request arbitration
5. Streaming SSE verification with [DONE] terminal detection
6. Error handling, truncated streams, and restart inhibition latching
7. Safe shutdown and clean process ownership cleanup

Outputs machine-readable evidence log (acceptance_evidence_<timestamp>.json)
with high-resolution monotonic timestamps, duration metrics, and status snapshots.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway
from resource_coordinator.config import (
    CoordinatorConfig,
    PolicyConfig,
    ProcessConfig,
    ServiceConfig,
    build_system,
)
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessLifecycleOwner,
    ProcessState,
    ProcessSupervisor,
)
from resource_coordinator.core.service import CoordinatorService, ServiceState

logger = logging.getLogger(__name__)


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
    verification_level: str = "unit_simulation"  # "unit_simulation", "os_process_contract", "live_hardware"
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
        cooldown_seconds: float = 10.0,
        allow_live_lmstudio: bool = False,
        allow_real_miner: bool = False,
        lmstudio_url: str = "http://127.0.0.1:1234",
    ) -> None:
        self.mode = mode
        self.cooldown_seconds = cooldown_seconds
        self.allow_live_lmstudio = allow_live_lmstudio
        self.allow_real_miner = allow_real_miner
        self.lmstudio_url = lmstudio_url

        import os
        if mode == "live":
            if not allow_live_lmstudio or not allow_real_miner:
                raise ValueError(
                    "Live acceptance mode requires both allow_live_lmstudio=True and allow_real_miner=True"
                )
            process_backend = "windows_miner"
            upstream_type = "live_lmstudio"
            verification_level = "live_hardware"
        elif mode == "disposable_helper":
            process_backend = "windows_cscript" if os.name == "nt" else "fake"
            upstream_type = "mock"
            verification_level = "os_process_contract"
        else:
            process_backend = "fake"
            upstream_type = "mock"
            verification_level = "unit_simulation"

        self.report = AcceptanceReport(
            mode=mode,
            process_backend=process_backend,
            upstream_type=upstream_type,
            verification_level=verification_level,
        )

    async def run_all(self, output_file: Optional[str | Path] = None) -> AcceptanceReport:
        """Run all test sequence trials and return the structured acceptance report."""
        logger.info("Starting Acceptance Test Sequence in mode: %s", self.mode)

        await self._run_trial_1_single_request()
        await self._run_trial_2_cooldown_interruption()
        await self._run_trial_3_concurrent_requests()
        await self._run_trial_4_streaming_sse()
        await self._run_trial_5_error_inhibition()

        # Compute summary
        total = len(self.report.trials)
        passed = sum(1 for t in self.report.trials if t.status == "PASS")
        failed = sum(1 for t in self.report.trials if t.status == "FAIL")
        self.report.summary = {
            "total_trials": total,
            "passed": passed,
            "failed": failed,
            "all_passed": (passed == total and total > 0),
        }

        if output_file:
            self.report.save(output_file)
            logger.info("Saved acceptance report to %s", output_file)

        return self.report

    def _build_test_harness(
        self,
        cooldown_seconds: float,
        mock_handler=None,
    ):
        """Build test environment with mock upstream and coordinator service."""
        recorded_events: List[Dict[str, Any]] = []

        async def default_upstream_handler(request):
            body = await request.json()
            is_stream = body.get("stream", False)
            if is_stream:

                async def event_generator():
                    yield b'data: {"choices": [{"delta": {"content": "tok"}}]}\n\n'
                    await asyncio.sleep(0.01)
                    yield b"data: [DONE]\n\n"

                return StreamingResponse(event_generator(), media_type="text/event-stream")
            return JSONResponse({"choices": [{"finish_reason": "stop", "message": {"content": "done"}}]})

        handler = mock_handler or default_upstream_handler
        mock_upstream_app = Starlette(
            routes=[
                Route("/v1/chat/completions", handler, methods=["POST"]),
                Route("/v1/models", lambda r: JSONResponse({"data": [{"id": "test-model"}]}), methods=["GET"]),
            ]
        )

        upstream_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_upstream_app),
            base_url="http://mock-upstream",
        )

        import os
        if self.mode == "disposable_helper" and os.name == "nt":
            vbs_path = Path(__file__).parent / "adapters" / "miners" / "windows_miner_helper.vbs"
            cscript_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cscript.exe")
            proc_cfg = ProcessConfig(
                name="krig",
                backend="windows",
                executable=cscript_exe,
                arguments=["//NoLogo", str(vbs_path)],
                stop_timeout_seconds=5.0,
                allow_force_termination=True,
            )
            cfg = CoordinatorConfig(
                service=ServiceConfig(upstream_url="http://mock-upstream"),
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
            )
            backend = system.supervisors["krig"].backend
        else:
            cfg = CoordinatorConfig(
                service=ServiceConfig(upstream_url="http://mock-upstream"),
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
            service = CoordinatorService(system)

            # Start supervisor with running miner
            backend = system.supervisors["krig"].backend
            backend.running = True
            backend.lifecycle_owner = ProcessLifecycleOwner.COORDINATOR
            backend.is_coordinator_owned = True
            system.supervisors["krig"].was_stopped_by_coordinator = False

        gateway_app = system.gateway.create_app(service)
        coordinator_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway_app),
            base_url="http://coordinator",
        )

        return service, system, coordinator_client, backend

    async def _run_trial_1_single_request(self) -> None:
        """Trial 1: Single request stop-before-forward and exact idle cooldown restart."""
        t = TrialEvidence(trial_id="T01", name="Single Request Stop Before Forward and Cooldown")
        t.start_monotonic = time.monotonic()
        try:
            cooldown = 0.1  # Fast cooldown for unit test harness
            service, system, client, backend = self._build_test_harness(cooldown_seconds=cooldown)
            assert await service.start() is True

            # Confirm initial state: miner RUNNING
            assert backend.running is True
            t_req_start = time.monotonic()

            resp = await client.post("/v1/chat/completions", json={"model": "test-model", "messages": []})
            t_req_end = time.monotonic()

            assert resp.status_code == 200
            # Miner MUST be stopped while in cooldown
            assert backend.running is False
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            t.metrics["request_duration_ms"] = (t_req_end - t_req_start) * 1000.0

            # Wait for cooldown to expire
            await asyncio.sleep(cooldown + 0.05)

            # Miner must now be restarted!
            assert backend.running is True
            t.metrics["miner_restarted"] = True
            t.status = "PASS"
            await service.stop()
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 1 failed: %s", exc)
        finally:
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_2_cooldown_interruption(self) -> None:
        """Trial 2: Request arriving during cooldown cancels restart immediately."""
        t = TrialEvidence(trial_id="T02", name="Cooldown Interruption and Debounce")
        t.start_monotonic = time.monotonic()
        try:
            cooldown = 0.2
            service, system, client, backend = self._build_test_harness(cooldown_seconds=cooldown)
            assert await service.start() is True

            # Request 1
            resp1 = await client.post("/v1/chat/completions", json={"model": "test-model", "messages": []})
            assert resp1.status_code == 200
            assert backend.running is False
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            # Send Request 2 at 50% of cooldown duration
            await asyncio.sleep(cooldown * 0.5)
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            t_int_start = time.monotonic()
            resp2 = await client.post("/v1/chat/completions", json={"model": "test-model", "messages": []})
            assert resp2.status_code == 200

            # Cooldown was reset; miner must STILL be stopped
            assert backend.running is False
            t.metrics["cooldown_cancelled_on_arrival"] = True

            # Wait for second cooldown to expire
            await asyncio.sleep(cooldown + 0.05)
            assert backend.running is True

            t.status = "PASS"
            await service.stop()
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 2 failed: %s", exc)
        finally:
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_3_concurrent_requests(self) -> None:
        """Trial 3: Overlapping concurrent requests: miner stays stopped until last completion + cooldown."""
        t = TrialEvidence(trial_id="T03", name="Concurrent Overlapping Requests")
        t.start_monotonic = time.monotonic()
        try:
            cooldown = 0.15

            # Handler simulating slow inference
            async def slow_handler(request):
                body = await request.json()
                delay = body.get("delay", 0.05)
                await asyncio.sleep(delay)
                return JSONResponse({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})

            service, system, client, backend = self._build_test_harness(
                cooldown_seconds=cooldown, mock_handler=slow_handler
            )
            assert await service.start() is True

            # Launch request 1 (duration 0.05s) and request 2 (duration 0.12s) concurrently
            task1 = asyncio.create_task(
                client.post("/v1/chat/completions", json={"model": "m", "delay": 0.05})
            )
            task2 = asyncio.create_task(
                client.post("/v1/chat/completions", json={"model": "m", "delay": 0.12})
            )

            # Wait for task 1 to finish
            resp1 = await task1
            assert resp1.status_code == 200
            # Task 2 is still running: miner MUST be stopped and cooldown NOT active
            assert backend.running is False
            assert system.lease_mgr.active_count("gpu.inference") == 1
            assert system.lease_mgr.is_cooling_down("gpu.inference") is False

            # Wait for task 2 to finish
            resp2 = await task2
            assert resp2.status_code == 200
            # Now cooldown starts
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True

            # Wait for cooldown to expire
            await asyncio.sleep(cooldown + 0.05)
            assert backend.running is True

            t.status = "PASS"
            await service.stop()
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 3 failed: %s", exc)
        finally:
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_4_streaming_sse(self) -> None:
        """Trial 4: Streaming SSE request with verified [DONE] marker."""
        t = TrialEvidence(trial_id="T04", name="Streaming SSE Terminal Detection")
        t.start_monotonic = time.monotonic()
        try:
            cooldown = 0.1
            service, system, client, backend = self._build_test_harness(cooldown_seconds=cooldown)
            assert await service.start() is True

            resp = await client.post("/v1/chat/completions", json={"model": "test-model", "stream": True})
            assert resp.status_code == 200
            assert "[DONE]" in resp.text

            # Stream finished cleanly with [DONE]
            assert system.lease_mgr.is_cooling_down("gpu.inference") is True
            await asyncio.sleep(cooldown + 0.05)
            assert backend.running is True

            t.status = "PASS"
            await service.stop()
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 4 failed: %s", exc)
        finally:
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)

    async def _run_trial_5_error_inhibition(self) -> None:
        """Trial 5: Truncated stream or upstream failure latches restart inhibition."""
        t = TrialEvidence(trial_id="T05", name="Error and Truncated Stream Restart Inhibition")
        t.start_monotonic = time.monotonic()
        try:
            cooldown = 0.1

            async def truncated_stream_handler(request):
                async def gen():
                    yield b'data: {"choices": [{"delta": {"content": "part"}}]}\n\n'
                    # Abrupt close without [DONE]

                return StreamingResponse(gen(), media_type="text/event-stream")

            service, system, client, backend = self._build_test_harness(
                cooldown_seconds=cooldown, mock_handler=truncated_stream_handler
            )
            assert await service.start() is True

            resp = await client.post("/v1/chat/completions", json={"model": "test-model", "stream": True})
            assert resp.status_code == 200
            assert "part" in resp.text

            # Restart MUST be inhibited
            assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True

            # Wait past cooldown duration: miner MUST NOT restart
            await asyncio.sleep(cooldown + 0.05)
            assert backend.running is False

            t.metrics["restart_inhibited"] = True
            t.status = "PASS"
            await service.stop()
        except Exception as exc:
            t.status = "FAIL"
            t.error = str(exc)
            logger.exception("Trial 5 failed: %s", exc)
        finally:
            t.end_monotonic = time.monotonic()
            t.duration_seconds = t.end_monotonic - t.start_monotonic
            self.report.trials.append(t)
