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
