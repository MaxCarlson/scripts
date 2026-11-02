"""
Independent Adversarial Review (Argon) regression tests for Miner / Local LLM Coordination.

Covers Findings A through E:
- Finding A: AcceptanceHarness mode validation, refusal of simulated fallback in live mode,
  and real Windows cscript helper execution.
- Finding B: Atomic ordering of durable journal resolution before clearing in-memory
  inhibition in /_coordinator/recover, and distinct OPERATOR_RESOLVED phase.
- Finding C: Watchdog restart race against new reservations after backoff sleep,
  cooldown respect, and no spurious launch of never-started processes.
- Finding D: Runtime journal disappearance detection (no silent empty journal recreation)
  and fail-closed in-memory inhibition when terminal journal persistence fails.
- Finding E: Manual pause (is_manual_override) persistence across inference completion,
  watchdog supervision, and coordinator service restarts.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from resource_coordinator.acceptance_harness import AcceptanceHarness
from resource_coordinator.config import CoordinatorConfig, build_system
from resource_coordinator.core.durable_state import (
    CoordinatorState,
    RequestPhase,
    StateCodec,
)
from resource_coordinator.core.leases import LeaseManager, LeaseType
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessState,
    ProcessSupervisor,
)
from resource_coordinator.core.service import CoordinatorService


def _make_config_dict(state_file: Path, cooldown: float = 0.1) -> dict:
    return {
        "version": "1.0",
        "service": {
            "listen_host": "127.0.0.1",
            "listen_port": 1235,
            "upstream_url": "http://127.0.0.1:1234",
            "state_persistence_path": str(state_file),
        },
        "processes": {
            "krig": {
                "backend": "fake",
                "executable": r"C:\Mining\krig-miner.exe",
            }
        },
        "policies": [
            {
                "name": "stop-miner",
                "trigger_event": "lmstudio.inference_requested",
                "target_process": "krig",
                "resource": "gpu.inference",
                "cooldown_seconds": cooldown,
            }
        ],
    }


def _make_mock_upstream() -> Starlette:
    async def handle_models(request):
        return JSONResponse({"data": [{"id": "qwen2.5-coder-32b"}]})

    async def handle_chat(request):
        return JSONResponse(
            {"id": "chatcmpl-test", "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}
        )

    return Starlette(
        routes=[
            Route("/v1/models", handle_models, methods=["GET"]),
            Route("/v1/chat/completions", handle_chat, methods=["POST"]),
        ]
    )


class TestFindingAAcceptanceHarnessIntegrity:
    """Finding A: AcceptanceHarness must never mislabel simulated runs or ignore mode constraints."""

    @pytest.mark.asyncio
    async def test_finding_a_rejects_invalid_mode_and_refuses_live_simulated_fallback(self):
        with pytest.raises(ValueError, match="Unsupported acceptance harness mode"):
            AcceptanceHarness(mode="invalid_mode")

        harness = AcceptanceHarness(
            mode="live",
            allow_live_lmstudio=True,
            allow_real_miner=True,
        )
        with pytest.raises(RuntimeError, match="Live acceptance mode requires an explicit"):
            await harness.run_all()

    @pytest.mark.skipif(os.name != "nt", reason="Windows cscript helper test requires Windows")
    @pytest.mark.asyncio
    async def test_finding_a_disposable_helper_real_windows_cscript_execution(self):
        harness = AcceptanceHarness(mode="disposable_helper", cooldown_seconds=0.15)
        report = await harness.run_all()

        assert report.mode == "disposable_helper"
        assert report.verification_level == "os_process_contract"
        assert report.process_backend == "windows_cscript"
        assert report.summary.get("all_passed") is True, [
            (r.trial_id, r.error, r.diagnostics) for r in report.trials if r.status != "PASS"
        ]
        assert len(report.trials) == 5


class TestFindingBOperatorRecoveryAtomicityAndPhase:
    """Finding B: /_coordinator/recover must persist journal resolution before clearing in-memory inhibition."""

    @pytest.mark.asyncio
    async def test_finding_b_operator_recovery_journal_failure_preserves_in_memory_inhibition(
        self, tmp_path: Path
    ):
        state_file = tmp_path / "coordinator_state.json"
        StateCodec.initialize(state_file)
        StateCodec.record_request_phase(
            state_file,
            "req-uncertain-1",
            "gpu.inference",
            RequestPhase.POSSIBLY_FORWARDED,
            model="qwen2.5-coder-32b",
            path="/v1/chat/completions",
        )

        config = CoordinatorConfig.from_dict(_make_config_dict(state_file, cooldown=0.05))
        system = build_system(config, use_fake_processes=True)
        system.gateway.recovery_token = "test-secret-token"
        service = CoordinatorService(system=system, start_miner_on_ready=False)
        assert await service.start() is True
        assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True

        app = system.gateway.create_app(service=service)
        transport = httpx.ASGITransport(app=app)
        auth_headers = {"Authorization": "Bearer test-secret-token"}

        # 1. Simulate disk failure during /_coordinator/recover
        with patch.object(StateCodec, "save_atomic", side_effect=OSError("Simulated disk write failure")):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/_coordinator/recover?resource=gpu.inference",
                    headers=auth_headers,
                    json={
                        "override": True,
                        "reason": "Verified LM Studio is idle",
                        "operator": "argon_tester",
                    },
                )
                assert resp.status_code == 500

        # In-memory inhibition MUST still be held and cooldown must NOT have started
        assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True
        assert system.lease_mgr.is_cooling_down("gpu.inference") is False

        # Journal must still hold POSSIBLY_FORWARDED
        loaded_after_fail = StateCodec.load(state_file)
        assert (
            loaded_after_fail.requests["req-uncertain-1"].phase
            == RequestPhase.POSSIBLY_FORWARDED.value
        )

        # 2. Now allow disk persistence to succeed
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/_coordinator/recover?resource=gpu.inference",
                headers=auth_headers,
                json={
                    "override": True,
                    "reason": "Verified LM Studio is idle",
                    "operator": "argon_tester",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "cleared"

        assert system.lease_mgr.is_restart_inhibited("gpu.inference") is False

        # Durable state must record OPERATOR_RESOLVED (not TERMINAL_VERIFIED) and preserve previous_phase
        loaded_after_ok = StateCodec.load(state_file)
        rec = loaded_after_ok.requests["req-uncertain-1"]
        assert rec.phase == RequestPhase.OPERATOR_RESOLVED.value
        assert rec.details.get("previous_phase") == RequestPhase.POSSIBLY_FORWARDED.value
        assert rec.details.get("resolved_by") == "operator_override:argon_tester:Verified LM Studio is idle"
        assert "gpu.inference" not in loaded_after_ok.inhibitions

        await service.stop()

        # 3. Restart coordinator against the same journal: should start cleanly without inhibition
        system2 = build_system(config, use_fake_processes=True)
        service2 = CoordinatorService(system=system2, start_miner_on_ready=False)
        assert await service2.start() is True
        assert system2.lease_mgr.is_restart_inhibited("gpu.inference") is False
        await service2.stop()


class TestFindingCWatchdogRestartRaces:
    """Finding C: Watchdog restart must respect reservations, cooldowns, and never-started state."""

    @pytest.mark.asyncio
    async def test_finding_c_supervision_loop_does_not_start_never_started_process(
        self, tmp_path: Path
    ):
        state_file = tmp_path / "state.json"
        StateCodec.initialize(state_file)
        config = CoordinatorConfig.from_dict(_make_config_dict(state_file, cooldown=0.05))
        system = build_system(config, use_fake_processes=True)
        service = CoordinatorService(
            system=system,
            start_miner_on_ready=False,
            supervision_poll_interval=0.03,
        )
        assert await service.start() is True
        backend: FakeProcessBackend = system.supervisors["krig"].backend  # type: ignore[assignment]
        assert backend.running is False

        await asyncio.sleep(0.12)
        assert backend.running is False
        assert backend.last_started_at is None
        await service.stop()

    @pytest.mark.asyncio
    async def test_finding_c_watchdog_respects_active_cooldown(self):
        lease_mgr = LeaseManager(default_cooldown_seconds=0.5)
        backend = FakeProcessBackend(name="krig", running=False)
        supervisor = ProcessSupervisor(backend=backend)
        await supervisor.start(only_if_stopped_by_coordinator=False)
        assert backend.running is True

        # Acquire and release a lease so gpu.inference enters its 0.5s cooldown window
        async with lease_mgr.reserve("gpu.inference", LeaseType.SHARED, "req-1"):
            await supervisor.stop(origin="coordinator")
        assert lease_mgr.is_cooling_down("gpu.inference") is True

        # Simulate unexpected crash state while cooldown is active
        supervisor.was_stopped_by_coordinator = False
        backend.running = False

        restarted = await supervisor.handle_unexpected_exit_backoff(
            lease_manager=lease_mgr,
            resource="gpu.inference",
            base_backoff_seconds=0.01,
        )
        assert restarted is False
        assert backend.running is False
        lease_mgr.block_restarts("cleanup")

    @pytest.mark.asyncio
    async def test_finding_c_watchdog_race_at_process_start_barrier_after_backoff(self):
        lease_mgr = LeaseManager(default_cooldown_seconds=0.1)
        backend = FakeProcessBackend(name="krig", running=False)
        supervisor = ProcessSupervisor(backend=backend)
        await supervisor.start(only_if_stopped_by_coordinator=False)
        # Simulate crash
        backend.running = False

        # Start watchdog backoff (sleeps 0.04s)
        watchdog_task = asyncio.create_task(
            supervisor.handle_unexpected_exit_backoff(
                lease_manager=lease_mgr,
                resource="gpu.inference",
                base_backoff_seconds=0.04,
            )
        )
        # Wait 0.01s so backoff is sleeping, then acquire a reservation before backoff wakes
        await asyncio.sleep(0.01)
        async with lease_mgr.reserve("gpu.inference", LeaseType.SHARED, "req-race"):
            restarted = await watchdog_task
            assert restarted is False
            assert backend.running is False
            # Pre-empted backoff should not inflate consecutive_unexpected_exits
            assert supervisor.consecutive_unexpected_exits == 0

        lease_mgr.block_restarts("cleanup")

    @pytest.mark.asyncio
    async def test_finding_c_controllable_barrier_serializes_start_with_incoming_reservation(
        self, tmp_path: Path
    ):
        state_file = tmp_path / "barrier_state.json"
        StateCodec.initialize(state_file)
        config = CoordinatorConfig.from_dict(_make_config_dict(state_file, cooldown=0.05))
        system = build_system(config, use_fake_processes=True)
        service = CoordinatorService(
            system=system,
            start_miner_on_ready=True,
            supervision_poll_interval=10.0,
        )
        assert await service.start() is True
        supervisor = system.supervisors["krig"]
        backend: FakeProcessBackend = supervisor.backend  # type: ignore[assignment]
        assert backend.running is True

        # Simulate crash
        backend.running = False
        supervisor.was_stopped_by_coordinator = False

        start_entered = asyncio.Event()
        release_start = asyncio.Event()
        orig_start = backend.start

        async def gated_start() -> bool:
            start_entered.set()
            await release_start.wait()
            return await orig_start()

        backend.start = gated_start  # type: ignore[method-assign]

        watchdog_task = asyncio.create_task(
            supervisor.handle_unexpected_exit_backoff(
                lease_manager=system.lease_mgr,
                resource="gpu.inference",
                base_backoff_seconds=0.01,
            )
        )
        await asyncio.wait_for(start_entered.wait(), timeout=1.0)

        # Now start a reservation while backend.start() is mid-flight inside run_if_idle
        reservation_entered = asyncio.Event()

        async def _inference_caller():
            async with system.lease_mgr.reserve("gpu.inference", LeaseType.SHARED, "req-barrier") as res:
                reservation_entered.set()
                await system.dispatcher.emit_blocking(
                    "lmstudio.inference_requested",
                    {"request_id": "req-barrier", "resource": "gpu.inference"},
                )
                await res.activate()
                # At the moment of activation/forwarding, miner MUST be stopped!
                assert backend.running is False

        caller_task = asyncio.create_task(_inference_caller())
        await asyncio.sleep(0.02)
        # Because run_if_idle holds lease_mgr._condition, reservation cannot enter until start finishes
        assert reservation_entered.is_set() is False

        release_start.set()
        await asyncio.gather(watchdog_task, caller_task)
        await service.stop()


class TestFindingDDurableJournalIntegrityAndTerminalFailure:
    """Finding D: Runtime journal disappearance or terminal write failure must fail closed."""

    @pytest.mark.asyncio
    async def test_finding_d_runtime_journal_disappearance_raises_and_latches_inhibition(
        self, tmp_path: Path
    ):
        state_file = tmp_path / "runtime_state.json"
        StateCodec.initialize(state_file)

        # Direct StateCodec check: deleting initialized journal must NOT silently create empty state
        state_file.unlink()
        with pytest.raises(FileNotFoundError):
            StateCodec.record_request_phase(
                state_file,
                "req-ghost",
                "gpu.inference",
                RequestPhase.RESERVED,
                model="m",
                path="/v1/chat/completions",
            )
        assert not state_file.exists()

        # Full gateway check: journal deleted while request is in flight
        StateCodec.initialize(state_file)
        config = CoordinatorConfig.from_dict(_make_config_dict(state_file, cooldown=0.05))
        system = build_system(config, use_fake_processes=True)

        async def handle_chat_deleting_journal(request):
            # Delete journal while request is executing upstream
            if state_file.exists():
                state_file.unlink()
            return JSONResponse(
                {"id": "chatcmpl-1", "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}
            )

        upstream_app = Starlette(
            routes=[Route("/v1/chat/completions", handle_chat_deleting_journal, methods=["POST"])]
        )
        system.gateway._http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=upstream_app),
            base_url="http://127.0.0.1:1234",
        )
        service = CoordinatorService(system=system, start_miner_on_ready=True)
        assert await service.start() is True
        backend: FakeProcessBackend = system.supervisors["krig"].backend  # type: ignore[assignment]
        assert backend.running is True

        app = system.gateway.create_app(service=service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={"model": "qwen", "messages": [{"role": "user", "content": "hi"}]},
            )
            assert resp.status_code == 200

        # Wait past cooldown: miner MUST NOT restart because terminal journal write failed!
        await asyncio.sleep(0.12)
        assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True
        assert backend.running is False
        # Journal file must NOT have been silently recreated as a clean state
        assert not state_file.exists()

        await service.stop()

    @pytest.mark.asyncio
    async def test_finding_d_terminal_write_oserror_latches_in_memory_inhibition(
        self, tmp_path: Path
    ):
        state_file = tmp_path / "terminal_err_state.json"
        StateCodec.initialize(state_file)
        config = CoordinatorConfig.from_dict(_make_config_dict(state_file, cooldown=0.05))
        system = build_system(config, use_fake_processes=True)
        system.gateway._http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_make_mock_upstream()),
            base_url="http://127.0.0.1:1234",
        )
        service = CoordinatorService(system=system, start_miner_on_ready=True)
        assert await service.start() is True
        backend: FakeProcessBackend = system.supervisors["krig"].backend  # type: ignore[assignment]
        assert backend.running is True

        orig_record = StateCodec.record_request_phase

        def fail_on_terminal(file_path, request_id, resource, phase, **kwargs):
            if phase == RequestPhase.TERMINAL_VERIFIED:
                raise OSError("Simulated disk full on TERMINAL_VERIFIED write")
            return orig_record(file_path, request_id, resource, phase, **kwargs)

        app = system.gateway.create_app(service=service)
        with patch.object(StateCodec, "record_request_phase", side_effect=fail_on_terminal):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/v1/chat/completions",
                    json={"model": "qwen", "messages": [{"role": "user", "content": "hi"}]},
                )
                assert resp.status_code == 200

        await asyncio.sleep(0.12)
        assert system.lease_mgr.is_restart_inhibited("gpu.inference") is True
        assert backend.running is False
        await service.stop()


class TestFindingEManualPausePersistence:
    """Finding E: Manual pause must persist across inference cycles, watchdog, and coordinator restarts."""

    @pytest.mark.asyncio
    async def test_finding_e_manual_pause_persists_across_restarts_and_inference(
        self, tmp_path: Path
    ):
        state_file = tmp_path / "pause_state.json"
        StateCodec.initialize(state_file)
        config = CoordinatorConfig.from_dict(_make_config_dict(state_file, cooldown=0.05))
        system = build_system(config, use_fake_processes=True)
        system.gateway._http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_make_mock_upstream()),
            base_url="http://127.0.0.1:1234",
        )
        service = CoordinatorService(
            system=system,
            start_miner_on_ready=True,
            supervision_poll_interval=0.04,
        )
        assert await service.start() is True
        assert system.miner_adapter is not None
        backend: FakeProcessBackend = system.supervisors["krig"].backend  # type: ignore[assignment]
        assert backend.running is True

        # Operator manually pauses the miner
        system.miner_adapter.set_manual_override(True)
        assert await system.miner_adapter.pause(origin="manual") is True
        assert backend.running is False
        assert system.miner_adapter.is_manual_override is True

        # Run an inference cycle: completion + cooldown must NOT resume manually paused miner
        app = system.gateway.create_app(service=service)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/chat/completions",
                json={"model": "qwen", "messages": [{"role": "user", "content": "hi"}]},
            )
            assert resp.status_code == 200

        await asyncio.sleep(0.12)
        assert backend.running is False

        # Stop service and start a new CoordinatorService with start_miner_on_ready=True
        await service.stop()

        system2 = build_system(config, use_fake_processes=True)
        service2 = CoordinatorService(
            system=system2,
            start_miner_on_ready=True,
            supervision_poll_interval=0.04,
        )
        assert await service2.start() is True
        assert system2.miner_adapter is not None
        backend2: FakeProcessBackend = system2.supervisors["krig"].backend  # type: ignore[assignment]
        assert system2.miner_adapter.is_manual_override is True
        assert backend2.running is False

        # Wait through supervision poll: watchdog must not start manually paused miner
        await asyncio.sleep(0.1)
        assert backend2.running is False

        # Operator explicitly clears manual override and resumes
        system2.miner_adapter.set_manual_override(False)
        assert await system2.miner_adapter.resume(only_if_stopped_by_coordinator=False) is True
        assert backend2.running is True
        await service2.stop()
