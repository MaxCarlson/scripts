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
