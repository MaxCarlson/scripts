import sys
from types import SimpleNamespace

from resource_metrics import gpu


def test_nvidia_gpu_query_parses_mib_and_unavailable(monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda _: "nvidia-smi")
    monkeypatch.setattr(
        gpu.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="RTX, 0, 70, N/A, 1024, 3072, 4096, 55\n"),
    )
    row = gpu.nvidia_gpus()[0]
    assert row["name"] == "RTX"
    assert row["load"] == 70.0
    assert row["memory_utilization"] is None
    assert row["mem_used"] == 1024**3
    assert row["mem_free"] == 3 * 1024**3
    assert row["mem_total"] == 4 * 1024**3


def test_nvidia_gpu_query_unavailable(monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda _: None)
    assert gpu.nvidia_gpus() == []
    assert gpu.gpu_process_memory() == []
    assert gpu.gpu_process_attribution([123]) == {"total_memory_bytes": 0, "process_memory": {}}


def test_gpu_devices_preserves_optional_gputil_fallback(monkeypatch):
    monkeypatch.setattr(gpu, "nvidia_gpus", lambda **kwargs: [])
    monkeypatch.setitem(
        sys.modules,
        "GPUtil",
        SimpleNamespace(
            getGPUs=lambda: [
                SimpleNamespace(
                    name="legacy",
                    id=1,
                    load=0.5,
                    memoryUsed=512,
                    memoryTotal=1024,
                    temperature=60,
                )
            ]
        ),
    )
    row = gpu.gpu_devices()[0]
    assert row["name"] == "legacy"
    assert row["load"] == 50.0
    assert row["mem_used"] == 512 * 1024**2


def test_gpu_process_attribution_matches_tree_pids(monkeypatch):
    fake_apps = [
        {"pid": 100, "name": "python", "memory_bytes": 500 * 1024**2},
        {"pid": 101, "name": "worker", "memory_bytes": 200 * 1024**2},
        {"pid": 999, "name": "unrelated", "memory_bytes": 800 * 1024**2},
    ]
    monkeypatch.setattr(gpu, "gpu_process_memory", lambda **k: fake_apps)

    attribution = gpu.gpu_process_attribution({100, 101})
    assert attribution["total_memory_bytes"] == 700 * 1024**2
    assert attribution["process_memory"] == {
        100: 500 * 1024**2,
        101: 200 * 1024**2,
    }
    assert 999 not in attribution["process_memory"]


def test_cached_gpu_monitor_throttles_and_falls_back_to_nvidia_smi(monkeypatch):
    calls = {"gpus": 0, "apps": 0}
    now = [100.0]

    def fake_gpus(**kwargs):
        calls["gpus"] += 1
        return [{"name": "RTX 4090", "id": 0, "load": 25.0, "mem_used": 1024, "mem_total": 4096}]

    def fake_apps(**kwargs):
        calls["apps"] += 1
        return [{"pid": 4242, "name": "python.exe", "memory_bytes": 512 * 1024**2}]

    monkeypatch.setattr(gpu, "_sample_nvml", lambda: None)
    monkeypatch.setattr(gpu, "nvidia_gpus", fake_gpus)
    monkeypatch.setattr(gpu, "gpu_process_memory", fake_apps)

    monitor = gpu.CachedGpuMonitor(ttl_seconds=4.0, clock=lambda: now[0])
    snap1 = monitor.snapshot()
    assert snap1["backend"] == "nvidia-smi"
    assert snap1["available"] is True
    assert snap1["process_memory"][4242]["memory_bytes"] == 512 * 1024**2
    assert calls == {"gpus": 1, "apps": 1}

    now[0] = 102.0
    snap2 = monitor.snapshot()
    assert snap2["age_seconds"] == 2.0
    assert calls == {"gpus": 1, "apps": 1}

    now[0] = 105.0
    snap3 = monitor.snapshot()
    assert snap3["age_seconds"] == 0.0
    assert calls == {"gpus": 2, "apps": 2}


def test_cached_gpu_monitor_unavailable(monkeypatch):
    monkeypatch.setattr(gpu, "_sample_nvml", lambda: None)
    monkeypatch.setattr(gpu, "nvidia_gpus", lambda **k: [])
    monkeypatch.setattr(gpu.shutil, "which", lambda _: None)

    monitor = gpu.CachedGpuMonitor(ttl_seconds=4.0)
    snap = monitor.snapshot()
    assert snap["backend"] == "unavailable"
    assert snap["available"] is False
    assert snap["devices"] == []
    assert snap["process_memory"] == {}


def test_sample_nvml_handles_wddm_not_available(monkeypatch):
    not_avail = 0xFFFFFFFFFFFFFFFF
    fake_pynvml = SimpleNamespace(
        NVML_TEMPERATURE_GPU=0,
        NVML_VALUE_NOT_AVAILABLE=not_avail,
        nvmlInit=lambda: None,
        nvmlShutdown=lambda: None,
        nvmlDeviceGetCount=lambda: 1,
        nvmlDeviceGetHandleByIndex=lambda idx: "h0",
        nvmlDeviceGetName=lambda h: b"RTX WDDM",
        nvmlDeviceGetMemoryInfo=lambda h: SimpleNamespace(used=2000, free=6000, total=8000),
        nvmlDeviceGetUtilizationRates=lambda h: SimpleNamespace(gpu=15, memory=20),
        nvmlDeviceGetTemperature=lambda h, s: 52,
        nvmlDeviceGetPowerUsage=lambda h: 45000,
        nvmlDeviceGetComputeRunningProcesses=lambda h: [SimpleNamespace(pid=111, usedGpuMemory=not_avail)],
        nvmlDeviceGetGraphicsRunningProcesses=lambda h: [SimpleNamespace(pid=222, usedGpuMemory=1024)],
    )
    monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)

    res = gpu._sample_nvml()
    assert res is not None
    assert res["backend"] == "nvml"
    assert res["process_memory"][111]["memory_bytes"] is None
    assert res["process_memory"][222]["memory_bytes"] == 1024
    assert "WDDM" in (res["limitations"] or "")
