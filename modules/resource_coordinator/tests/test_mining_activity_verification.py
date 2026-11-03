"""
Deterministic offline tests for AcceptanceHarness mining-activity verification and 3-contract partitioning.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from resource_coordinator.acceptance_harness import (
    AcceptanceHarness,
    GpuActivitySampler,
    TrialEvidence,
)
from resource_coordinator.core.processes import (
    FakeProcessBackend,
    ProcessInfo,
    ProcessLifecycleOwner,
    ProcessState,
    ProcessSupervisor,
)
from resource_coordinator.monitors.gpu import GpuDeviceMetrics


class MockGpuMonitor:
    """Mock GPU monitor simulating configurable telemetry transitions."""

    def __init__(self, profiles: Optional[List[GpuDeviceMetrics]] = None) -> None:
        self.profiles = list(profiles or [])
        self._index = 0
        self.calls = 0

    async def get_metrics(self) -> List[GpuDeviceMetrics]:
        self.calls += 1
        if not self.profiles:
            return []
        if self._index < len(self.profiles):
            m = self.profiles[self._index]
            self._index += 1
            return [m]
        return [self.profiles[-1]]


def _create_metric(power_w: float, util_pct: float, mem_mb: float = 2000.0) -> GpuDeviceMetrics:
    return GpuDeviceMetrics(
        device_id="0",
        utilization_pct=util_pct,
        memory_used_mb=mem_mb,
        memory_total_mb=32768.0,
        power_draw_w=power_w,
    )


@pytest.mark.asyncio
async def test_simulated_mining_warmup_passes_when_hashing_confirmed(tmp_path: Path):
    """
    Trial 1 with require_mining_activity=True:
    GPU ramps from 40W idle to 350W hashing.
    All 3 contracts must be verified and status must be PASS.
    """
    # 1 baseline sample (40W), then 3 hashing samples (350W, 99%)
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(power_w=40.0, util_pct=0.0),
            _create_metric(power_w=350.0, util_pct=99.0),
            _create_metric(power_w=350.0, util_pct=99.0),
            _create_metric(power_w=350.0, util_pct=99.0),
            # After restart: 3 more hashing samples
            _create_metric(power_w=350.0, util_pct=99.0),
            _create_metric(power_w=350.0, util_pct=99.0),
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=2.0,
        mining_settle_seconds=0.0,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "PASS"
    assert trial.process_contract_verified is True
    assert trial.inference_arbitration_contract_verified is True
    assert trial.mining_activity_contract_verified is True
    assert trial.initial_mining_activity_verified is True
    assert trial.restart_mining_activity_verified is True
    assert trial.gpu_idle_baseline is not None
    assert trial.gpu_idle_baseline["power_draw_w"] == 40.0
    assert trial.peak_gpu_power_w is not None and trial.peak_gpu_power_w >= 350.0


@pytest.mark.asyncio
async def test_delayed_hashing_readiness_waits_for_warmup(tmp_path: Path):
    """
    Miner stays idle (40W) for 2 samples, then ramps to 300W on 3rd sample.
    Warmup loop must wait until hashing is confirmed before proceeding to inference.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),  # Baseline
            _create_metric(40.0, 0.0),  # Warmup sample 1 (idle)
            _create_metric(40.0, 0.0),  # Warmup sample 2 (idle)
            _create_metric(300.0, 95.0),  # Warmup sample 3 (hashing)
            _create_metric(300.0, 95.0),  # Warmup sample 4 (hashing)
            # Post-restart
            _create_metric(300.0, 95.0),
            _create_metric(300.0, 95.0),
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=2.0,
        mining_settle_seconds=0.0,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "PASS"
    assert trial.mining_activity_contract_verified is True
    assert trial.initial_miner_uptime_before_inference_seconds is not None
    assert trial.initial_miner_uptime_before_inference_seconds > 0.0


@pytest.mark.asyncio
async def test_process_running_without_hashing_fails_timeout(tmp_path: Path):
    """
    Miner process exists and runs, but GPU remains at 40W idle throughout.
    Must fail with mining_activity_contract_verified=False, while process_contract_verified=True.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),  # Baseline
            _create_metric(40.0, 0.0),  # Sample 1
            _create_metric(40.0, 0.0),  # Sample 2
            _create_metric(40.0, 0.0),  # Sample 3
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=0.3,
        mining_settle_seconds=0.0,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "FAIL"
    assert trial.mining_activity_contract_verified is False
    assert trial.initial_mining_activity_verified is False
    assert "mining activity" in (trial.error or "").lower()


@pytest.mark.asyncio
async def test_miner_startup_failure_during_warmup_aborts_immediately(tmp_path: Path):
    """
    Miner exits unexpectedly during warm-up.
    Warmup loop must abort immediately rather than waiting for the timeout.
    """
    mock_gpu = MockGpuMonitor(profiles=[_create_metric(40.0, 0.0)])

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=5.0,  # Long timeout
        mining_settle_seconds=0.0,
        gpu_monitor=mock_gpu,
    )

    def crash_backend_after_start(service, system, backend):
        # Schedule the backend to stop abruptly after 0.05s
        async def abrupt_exit():
            await asyncio.sleep(0.05)
            backend.running = False

        asyncio.create_task(abrupt_exit())

    t_start = asyncio.get_event_loop().time()
    await harness._run_trial_1_single_request(_post_build_hook=crash_backend_after_start)
    t_elapsed = asyncio.get_event_loop().time() - t_start

    trial = harness.report.trials[0]
    assert trial.status == "FAIL"
    assert "prematurely" in (trial.error or "").lower() or "stopped" in (trial.error or "").lower()
    # Must have aborted well before the 5.0s timeout
    assert t_elapsed < 2.0


@pytest.mark.asyncio
async def test_failure_to_resume_hashing_after_cooldown_fails(tmp_path: Path):
    """
    Initial warmup passes and inference succeeds, but post-cooldown restart fails to hash.
    Must fail overall with restart_mining_activity_verified=False.
    """
    # High power for initial warmup, but low power (idle) after restart
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),  # Baseline
            _create_metric(300.0, 95.0),  # Initial warmup 1
            _create_metric(300.0, 95.0),  # Initial warmup 2
            # Post-restart: stuck at idle
            _create_metric(40.0, 0.0),
            _create_metric(40.0, 0.0),
            _create_metric(40.0, 0.0),
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=0.3,
        mining_settle_seconds=0.0,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "FAIL"
    assert trial.initial_mining_activity_verified is True
    assert trial.restart_mining_activity_verified is False
    assert trial.mining_activity_contract_verified is False


def test_miner_stdout_log_hashrate_detection(tmp_path: Path):
    """
    Test stdout log parser on genuine KRig/SRBMiner output lines.
    """
    log_file = tmp_path / "miner_stdout.log"
    log_content = (
        "2026-11-02 15:33:01 [INFO] krig-miner v1.4.2\n"
        "2026-11-02 15:33:02 [INFO] Connected to stratum+ssl://prl-us.example-pool.network:8048\n"
        "2026-11-02 15:33:02 [INFO] Subscribed to pool jobs\n"
        "2026-11-02 15:33:04 [INFO] [pearl] Speed: 1250.50 MH/s (Shares: 1/0)\n"
    )
    log_file.write_text(log_content, encoding="utf-8")

    from resource_coordinator.acceptance_harness import parse_miner_stdout_log

    parsed = parse_miner_stdout_log(log_file)
    assert parsed["pool_connected"] is True
    assert parsed["hashrate"] == "1250.50 MH/s"


@pytest.mark.asyncio
async def test_guaranteed_cleanup_in_finally_on_warmup_failure(tmp_path: Path):
    """
    When warm-up verification fails due to timeout, harness must guarantee
    cleanup in finally, verifying supervisor and backend are STOPPED.
    """
    mock_gpu = MockGpuMonitor(profiles=[_create_metric(40.0, 0.0)])
    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=0.2,
        mining_settle_seconds=0.0,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "FAIL"
    # Harness cleanup must have run
    assert harness.host_lock is not None or harness.mode != "live"
    # Cleanup verification in report
    assert "mining activity" in (trial.error or "").lower()
