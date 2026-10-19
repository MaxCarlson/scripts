from __future__ import annotations

import time

from sysmon.sampler import HardwareSampler, SystemStats, TelemetryDisplayMode


def test_sampler_lifecycle_and_system_metrics():
    assert TelemetryDisplayMode.FULL.value == "full"
    sampler = HardwareSampler(interval=0.1)
    sampler.start()
    try:
        time.sleep(0.25)
        sys_stats, proc_stats = sampler.get_snapshots()
        assert isinstance(sys_stats, SystemStats)
        assert 0.0 <= sys_stats.cpu_pct <= 100.0
        assert sys_stats.ram_used_bytes > 0
        assert sys_stats.ram_total_bytes > 0
        assert 0.0 <= sys_stats.ram_pct <= 100.0
        assert proc_stats is None
    finally:
        sampler.stop()


def test_sampler_graceful_gpu_fallback(monkeypatch):
    import sysmon.sampler as sm

    monkeypatch.setattr(sm, "_gpu_info_safe", lambda: ([], "GPU query failed"))
    sampler = HardwareSampler(interval=0.1)
    sampler._sample_tick()
    sys_stats, _ = sampler.get_snapshots()
    assert sys_stats is not None
    assert sys_stats.gpu_load_pct is None
    assert sys_stats.gpu_mem_used_bytes is None


def test_process_tree_attribution_and_normalization():
    import subprocess
    import sys

    from sysmon.sampler import ProcessStats

    # Spawn child python process executing busy CPU loop for 0.8s
    code = "import time; t0 = time.time()\nwhile time.time() - t0 < 0.8: pass"
    proc = subprocess.Popen([sys.executable, "-c", code])
    sampler = HardwareSampler(interval=0.05)
    sampler.set_target_pid(proc.pid)
    try:
        # Tick 1 establishes baseline
        sampler._sample_tick()
        time.sleep(0.1)
        # Tick 2 computes non-zero delta
        sampler._sample_tick()
        _, proc_stats = sampler.get_snapshots()
        assert isinstance(proc_stats, ProcessStats)
        assert proc_stats.pid == proc.pid
        assert proc_stats.is_active is True
        assert proc_stats.cpu_pct > 0.0
        assert proc_stats.cpu_pct <= 100.0
        assert proc_stats.cpu_raw_pct > 0.0
        assert proc_stats.cpu_raw_pct >= proc_stats.cpu_pct
        assert proc_stats.memory_rss_bytes > 0
    finally:
        proc.terminate()
        proc.wait()
        sampler.stop()


def test_process_exit_and_nosuchprocess_handling():
    sampler = HardwareSampler(interval=0.05)
    # Set non-existent PID
    sampler.set_target_pid(9999999)
    sampler._sample_tick()
    _, proc_stats = sampler.get_snapshots()
    assert proc_stats is None or proc_stats.is_active is False
