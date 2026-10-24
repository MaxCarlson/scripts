from types import SimpleNamespace

from resource_metrics import gpu


def test_nvidia_gpu_query_parses_mib_and_unavailable(monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda _: "nvidia-smi")
    monkeypatch.setattr(gpu.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="RTX, 0, 70, N/A, 1024, 4096, 55\n"))
    row = gpu.nvidia_gpus()[0]
    assert row["name"] == "RTX"
    assert row["load"] == 70.0
    assert row["memory_utilization"] is None
    assert row["mem_used"] == 1024**3


def test_nvidia_gpu_query_unavailable(monkeypatch):
    monkeypatch.setattr(gpu.shutil, "which", lambda _: None)
    assert gpu.nvidia_gpus() == []
    assert gpu.gpu_process_memory() == []
