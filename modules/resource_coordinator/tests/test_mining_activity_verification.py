"""
Deterministic offline tests for AcceptanceHarness mining-activity verification,
process-generation log isolation, phase-isolated GPU sampling, and settling state machine.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from resource_coordinator.acceptance_harness import (
    AcceptanceHarness,
    GpuActivitySampler,
    TrialEvidence,
    parse_miner_stdout_log,
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


# ---------------------------------------------------------------------------
# Test 1: Initial mining activity successfully established
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_initial_mining_activity_established(tmp_path: Path):
    """
    Initial miner produces sustained GPU compute and positive hashrate.
    Must verify initial generation and overall trial successfully.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Baseline
            _create_metric(350.0, 99.0),  # Initial warm-up 1
            _create_metric(350.0, 99.0),  # Initial warm-up 2
            _create_metric(350.0, 99.0),  # Initial settling
            _create_metric(350.0, 99.0),  # Restart 1
            _create_metric(350.0, 99.0),  # Restart 2
            _create_metric(350.0, 99.0),  # Restart settling
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=2.0,
        mining_settle_seconds=0.1,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "PASS"
    assert trial.process_contract_verified is True
    assert trial.inference_arbitration_contract_verified is True
    assert trial.mining_activity_contract_verified is True
    assert trial.initial_generation is not None
    assert trial.initial_generation["verified"] is True
    assert trial.initial_generation["peak_power_w"] >= 350.0


# ---------------------------------------------------------------------------
# Test 2: Restarted miner produces new evidence and succeeds
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_restarted_miner_produces_new_evidence_and_succeeds(tmp_path: Path):
    """
    Both initial and restarted miner independently produce fresh GPU samples.
    Evidence must be recorded separately for each generation.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Initial baseline
            _create_metric(320.0, 90.0),  # Initial warm-up
            _create_metric(320.0, 90.0),  # Initial sustained
            _create_metric(320.0, 90.0),  # Initial settling
            _create_metric(40.0, 0.0),    # Cooldown idle
            _create_metric(380.0, 95.0),  # Restart warm-up
            _create_metric(380.0, 95.0),  # Restart sustained
            _create_metric(380.0, 95.0),  # Restart settling
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=2.0,
        mining_settle_seconds=0.05,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "PASS"
    assert trial.initial_generation is not None
    assert trial.restart_generation is not None
    assert trial.initial_generation["generation"] == 1
    assert trial.restart_generation["generation"] == 2
    assert trial.initial_generation["verified"] is True
    assert trial.restart_generation["verified"] is True
    # Peak powers must reflect generation-specific samples
    assert trial.initial_generation["peak_power_w"] == 320.0
    assert trial.restart_generation["peak_power_w"] == 380.0


# ---------------------------------------------------------------------------
# Test 3: Restarted miner idle with old log hashrate — must fail
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_restarted_miner_idle_with_old_log_hashrate_fails(tmp_path: Path):
    """
    Initial miner logs a valid hashrate (at byte offset 0).
    Restarted miner produces no new hashrate and its GPU is idle.
    MUST FAIL: old log hashrate before restart byte offset must NOT satisfy restart.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Initial baseline
            _create_metric(300.0, 95.0),  # Initial warm-up 1
            _create_metric(300.0, 95.0),  # Initial warm-up 2
            # Post-restart: GPU remains at 40W idle
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
        mining_settle_seconds=0.05,
        gpu_monitor=mock_gpu,
    )

    # Hook post-build to write hashrate to the initial log
    def write_initial_log(service, system, backend):
        run_dir = harness._ensure_run_dir()
        log_file = run_dir / "t01" / "miner_stdout.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        # Write hashrate from Gen 1
        log_file.write_text("Total: 324.42 TH/s shares: 1 accepted 0 stale 0 rejected\n", encoding="utf-8")

    await harness._run_trial_1_single_request(_post_build_hook=write_initial_log)

    trial = harness.report.trials[0]
    assert trial.status == "FAIL"
    assert trial.initial_generation is not None
    assert trial.initial_generation["verified"] is True
    assert trial.restart_generation is not None
    assert trial.restart_generation["verified"] is False
    assert trial.mining_activity_contract_verified is False


# ---------------------------------------------------------------------------
# Test 4: Restarted miner idle with earlier high GPU samples — must fail
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_restarted_miner_idle_with_earlier_high_gpu_samples_fails(tmp_path: Path):
    """
    Initial phase takes high GPU samples (350W).
    Restarted phase only takes idle samples (40W).
    MUST FAIL: initial phase GPU samples must not leak into restart evaluation.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Initial baseline
            _create_metric(350.0, 99.0),  # Initial warm-up 1
            _create_metric(350.0, 99.0),  # Initial warm-up 2
            _create_metric(350.0, 99.0),  # Initial settling
            # Post-restart: only idle samples
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
        mining_settle_seconds=0.05,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "FAIL"
    assert trial.restart_generation is not None
    assert trial.restart_generation["verified"] is False
    assert trial.mining_activity_contract_verified is False


# ---------------------------------------------------------------------------
# Test 5: Miner produces transient activity spike but becomes idle during settling — must fail
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_transient_activity_spike_drops_idle_during_settling_fails(tmp_path: Path):
    """
    GPU spikes to 300W for 2 samples, but drops back to 40W idle during settling.
    State machine must reject the spike because activity did not remain sustained throughout settling.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Baseline
            _create_metric(300.0, 95.0),  # Spike sample 1
            _create_metric(300.0, 95.0),  # Spike sample 2 (triggers sustained state)
            # Settling begins: power immediately drops back to 40W idle
            _create_metric(40.0, 0.0),
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
        mining_warmup_timeout_seconds=0.4,
        mining_settle_seconds=0.2,  # Settling required
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "FAIL"
    assert trial.mining_activity_contract_verified is False
    assert trial.initial_generation is not None
    assert trial.initial_generation["settling_verified"] is False


# ---------------------------------------------------------------------------
# Test 6: Log contains only Stratum URL without actual connection confirmation
# ---------------------------------------------------------------------------
def test_stratum_url_alone_without_connection_confirmation(tmp_path: Path):
    """
    Log contains command-line arguments echoing '--url stratum+ssl://...'
    Must NOT claim pool_connected=True because no connection confirmation message exists.
    """
    log_file = tmp_path / "args_echo.log"
    log_file.write_text(
        "krig-miner --coin pearl --url stratum+ssl://prl-us.kryptex.network:8048 --user 0x123/worker\n"
        "Initializing device 0...\n",
        encoding="utf-8",
    )

    parsed = parse_miner_stdout_log(log_file, start_offset=0)
    assert parsed["pool_connected"] is False
    assert parsed["connected_pool_url"] is None
    assert parsed["hashrate"] is None

    # Now append real connection confirmation
    with log_file.open("a", encoding="utf-8") as f:
        f.write("connected: stratum+ssl://prl-us.kryptex.network:8048\n")
        f.write("stratum: new job 2c5d2bba height 127357\n")

    parsed_connected = parse_miner_stdout_log(log_file, start_offset=0)
    assert parsed_connected["pool_connected"] is True
    assert parsed_connected["connected_pool_url"] == "stratum+ssl://prl-us.kryptex.network:8048"
    assert parsed_connected["pool_job_received"] is True


# ---------------------------------------------------------------------------
# Test 7: Hashrate before start offset is ignored for current generation
# ---------------------------------------------------------------------------
def test_hashrate_before_start_offset_ignored(tmp_path: Path):
    """
    Log file contains Gen 1 output with hashrate.
    Gen 2 starts at offset 200. Bytes after offset 200 have no hashrate.
    parse_miner_stdout_log with start_offset=200 must return hashrate=None.
    """
    log_file = tmp_path / "multi_gen.log"
    # Write Gen 1 output (bytes 0..~150)
    gen1_content = (
        "connected: stratum+ssl://prl-us.kryptex.network:8048\n"
        "Total: 324.42 TH/s shares: 1 accepted 0 stale 0 rejected\n"
    )
    log_file.write_text(gen1_content, encoding="utf-8")
    offset_gen2 = log_file.stat().st_size

    # Write Gen 2 output (no hashrate)
    with log_file.open("a", encoding="utf-8") as f:
        f.write("connected: stratum+ssl://prl-us.kryptex.network:8048\n")
        f.write("GPU0 01:00.0 RTX 5090 initializing\n")

    # Read from offset 0: sees hashrate
    parsed_gen1 = parse_miner_stdout_log(log_file, start_offset=0)
    assert parsed_gen1["hashrate"] == "324.42 TH/s"

    # Read from offset_gen2: does NOT see Gen 1 hashrate
    parsed_gen2 = parse_miner_stdout_log(log_file, start_offset=offset_gen2)
    assert parsed_gen2["hashrate"] is None
    assert parsed_gen2["pool_connected"] is True


# ---------------------------------------------------------------------------
# Test 8: Missing GPU telemetry handles conservatively
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_gpu_telemetry_handles_conservatively(tmp_path: Path):
    """
    When GPU monitor returns empty metrics (e.g. nvidia-smi missing),
    harness does not crash; if no log evidence either, verification fails closed.
    """
    empty_gpu = MockGpuMonitor(profiles=[])
    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=0.2,
        mining_settle_seconds=0.0,
        gpu_monitor=empty_gpu,
    )

    await harness._run_trial_1_single_request()

    trial = harness.report.trials[0]
    assert trial.status == "FAIL"
    assert trial.mining_activity_contract_verified is False
    assert trial.initial_generation is not None
    assert trial.initial_generation["evidence_classification"] == "verification_inconclusive"


# ---------------------------------------------------------------------------
# Test 9: Miner terminates during settling — aborts immediately and cleans up
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_miner_termination_during_settling_aborts_immediately(tmp_path: Path):
    """
    Miner enters settling window, but abruptly exits before settling finishes.
    Harness must fail fast immediately and verify supervisor cleanup.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Baseline
            _create_metric(350.0, 99.0),  # Warm-up 1
            _create_metric(350.0, 99.0),  # Warm-up 2 (enters settling)
            _create_metric(350.0, 99.0),
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=5.0,  # Long timeout
        mining_settle_seconds=2.0,          # Long settling
        gpu_monitor=mock_gpu,
    )

    def crash_backend_during_settling(service, system, backend):
        async def kill_soon():
            await asyncio.sleep(0.1)
            backend.running = False

        asyncio.create_task(kill_soon())

    t_start = asyncio.get_event_loop().time()
    await harness._run_trial_1_single_request(_post_build_hook=crash_backend_during_settling)
    t_elapsed = asyncio.get_event_loop().time() - t_start

    trial = harness.report.trials[0]
    assert trial.status == "FAIL"
    assert "prematurely" in (trial.error or "").lower() or "stopped" in (trial.error or "").lower()
    # Must have aborted well before the 5.0s timeout
    assert t_elapsed < 2.0


# ---------------------------------------------------------------------------
# Test 10: Restart warm-up timeout — fails and verifies cleanup
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_restart_warmup_timeout_fails_and_cleans_up(tmp_path: Path):
    """
    Initial phase succeeds, inference passes, cooldown passes,
    but restarted miner never produces activity and hits timeout.
    Harness must fail trial and verify final process termination.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Initial baseline
            _create_metric(300.0, 95.0),  # Initial warm-up 1
            _create_metric(300.0, 95.0),  # Initial warm-up 2
            # Post-restart: stuck at idle
            _create_metric(40.0, 0.0),
            _create_metric(40.0, 0.0),
        ]
    )

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
    assert trial.initial_generation is not None
    assert trial.initial_generation["verified"] is True
    assert trial.restart_generation is not None
    assert trial.restart_generation["verified"] is False
    assert trial.mining_activity_contract_verified is False


# ---------------------------------------------------------------------------
# Test 11: Trial 2 (Cooldown Interruption) with verified mining warm-up
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_trial_2_cooldown_interruption_with_mining_verification(tmp_path: Path):
    """
    Trial 2: Initial miner warms up and hashes. Request 1 stops miner.
    Request 2 arrives mid-cooldown, resetting cooldown.
    Restarted miner warms up and hashes. All 3 contracts must PASS.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Baseline
            _create_metric(350.0, 99.0),  # Initial warm-up 1
            _create_metric(350.0, 99.0),  # Initial warm-up 2
            _create_metric(350.0, 99.0),  # Initial settling
            _create_metric(40.0, 0.0),    # Idle during Request 1 & cooldown
            _create_metric(350.0, 99.0),  # Restart warm-up 1
            _create_metric(350.0, 99.0),  # Restart warm-up 2
            _create_metric(350.0, 99.0),  # Restart settling
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=2.0,
        mining_settle_seconds=0.05,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_2_cooldown_interruption()

    trial = harness.report.trials[0]
    assert trial.status == "PASS"
    assert trial.process_contract_verified is True
    assert trial.inference_arbitration_contract_verified is True
    assert trial.mining_activity_contract_verified is True
    assert trial.initial_generation is not None
    assert trial.restart_generation is not None
    assert trial.initial_generation["verified"] is True
    assert trial.restart_generation["verified"] is True
    assert trial.metrics.get("cooldown_cancelled_on_arrival") is True
    assert trial.peak_gpu_power_w >= 350.0


# ---------------------------------------------------------------------------
# Test 12: Trial 3 (Concurrent Overlapping Requests) with verified mining warm-up
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_trial_3_concurrent_requests_with_mining_verification(tmp_path: Path):
    """
    Trial 3: Initial miner warms up. Two overlapping requests arrive.
    Miner remains stopped while either is active.
    Restarted miner warms up. All 3 contracts must PASS.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Baseline
            _create_metric(350.0, 99.0),  # Initial warm-up 1
            _create_metric(350.0, 99.0),  # Initial warm-up 2
            _create_metric(350.0, 99.0),  # Initial settling
            _create_metric(40.0, 0.0),    # Idle during requests
            _create_metric(350.0, 99.0),  # Restart warm-up 1
            _create_metric(350.0, 99.0),  # Restart warm-up 2
            _create_metric(350.0, 99.0),  # Restart settling
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=2.0,
        mining_settle_seconds=0.05,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_3_concurrent_requests()

    trial = harness.report.trials[0]
    assert trial.status == "PASS"
    assert trial.process_contract_verified is True
    assert trial.inference_arbitration_contract_verified is True
    assert trial.mining_activity_contract_verified is True
    assert trial.initial_generation is not None
    assert trial.restart_generation is not None
    assert trial.initial_generation["verified"] is True
    assert trial.restart_generation["verified"] is True
    assert trial.peak_gpu_power_w >= 350.0


# ---------------------------------------------------------------------------
# Test 13: Trial 4 (Streaming SSE Terminal Detection) with verified mining warm-up
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_trial_4_streaming_sse_with_mining_verification(tmp_path: Path):
    """
    Trial 4: Initial miner warms up. SSE stream consumed incrementally until [DONE].
    Miner remains stopped throughout stream.
    Restarted miner warms up. All 3 contracts must PASS.
    """
    mock_gpu = MockGpuMonitor(
        profiles=[
            _create_metric(40.0, 0.0),    # Baseline
            _create_metric(350.0, 99.0),  # Initial warm-up 1
            _create_metric(350.0, 99.0),  # Initial warm-up 2
            _create_metric(350.0, 99.0),  # Initial settling
            _create_metric(40.0, 0.0),    # Idle during stream
            _create_metric(350.0, 99.0),  # Restart warm-up 1
            _create_metric(350.0, 99.0),  # Restart warm-up 2
            _create_metric(350.0, 99.0),  # Restart settling
        ]
    )

    harness = AcceptanceHarness(
        work_dir=tmp_path / "work",
        mode="simulated",
        cooldown_seconds=0.2,
        require_mining_activity=True,
        mining_warmup_timeout_seconds=2.0,
        mining_settle_seconds=0.05,
        gpu_monitor=mock_gpu,
    )

    await harness._run_trial_4_streaming_sse()

    trial = harness.report.trials[0]
    assert trial.status == "PASS"
    assert trial.process_contract_verified is True
    assert trial.inference_arbitration_contract_verified is True
    assert trial.mining_activity_contract_verified is True
    assert trial.initial_generation is not None
    assert trial.restart_generation is not None
    assert trial.initial_generation["verified"] is True
    assert trial.restart_generation["verified"] is True
    assert trial.metrics["inference_result"]["done_marker_observed"] is True
    assert trial.peak_gpu_power_w >= 350.0
