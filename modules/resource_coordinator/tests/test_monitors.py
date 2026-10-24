import pytest

from resource_coordinator.monitors.cpu import CpuMonitor
from resource_coordinator.monitors.gpu import MockGpuMonitor


def test_cpu_monitor():
    monitor = CpuMonitor(sample_history_seconds=10.0)
    pct = monitor.sample()
    assert isinstance(pct, float)
    assert pct >= 0.0
    latest = monitor.get_latest()
    assert latest == pct
    avg = monitor.get_average(window_seconds=5.0)
    assert avg >= 0.0


@pytest.mark.asyncio
async def test_gpu_monitor():
    monitor = MockGpuMonitor(default_utilization=25.0)
    metrics = await monitor.get_metrics()
    assert len(metrics) == 1
    assert metrics[0].device_id == "gpu-0"
    assert metrics[0].utilization_pct == 25.0

    max_util = await monitor.get_max_utilization()
    assert max_util == 25.0

    monitor.set_utilization("gpu-0", 85.5)
    assert await monitor.get_max_utilization() == 85.5


@pytest.mark.asyncio
async def test_nvidia_monitor_uses_shared_gpu_metrics(monkeypatch):
    import resource_coordinator.monitors.gpu as gpu_module

    monkeypatch.setattr(gpu_module, "nvidia_gpus", lambda **kwargs: [{
        "id": 2, "load": 40.0, "mem_used": 2 * 1024**2,
        "mem_total": 8 * 1024**2, "power_w": 150.0,
    }])
    metrics = await gpu_module.NvidiaGpuMonitor().get_metrics()
    assert metrics == [gpu_module.GpuDeviceMetrics(
        device_id="gpu-2", utilization_pct=40.0, memory_used_mb=2.0,
        memory_total_mb=8.0, power_draw_w=150.0,
    )]
