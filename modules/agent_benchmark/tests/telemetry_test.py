from __future__ import annotations

import threading
from types import SimpleNamespace

from agent_benchmark import telemetry


def test_nvidia_smi_row_parser_reports_gpu_and_memory_utilization() -> None:
    snapshot = telemetry.parse_nvidia_smi_row(
        "NVIDIA GeForce RTX 5090, 0, 81, 37, 20480, 24576"
    )

    assert snapshot.gpu_name == "NVIDIA GeForce RTX 5090"
    assert snapshot.gpu_utilization_pct == 81.0
    assert snapshot.gpu_memory_utilization_pct == 37.0
    assert snapshot.gpu_memory_used_bytes == 20 * 1024**3
    assert snapshot.gpu_memory_total_bytes == 24 * 1024**3


def test_nvidia_smi_row_parser_keeps_unavailable_metrics_unavailable() -> None:
    snapshot = telemetry.parse_nvidia_smi_row("NVIDIA GPU, 0, N/A, N/A, N/A, N/A")

    assert snapshot.gpu_name == "NVIDIA GPU"
    assert snapshot.gpu_utilization_pct is None
    assert snapshot.gpu_memory_utilization_pct is None
    assert snapshot.gpu_memory_used_bytes is None
    assert snapshot.gpu_memory_total_bytes is None


def test_utilization_percentages_use_requested_color_bands() -> None:
    cases = [
        (49.9, "32", "49%"),
        (50.0, "33", "50%"),
        (69.9, "33", "69%"),
        (70.0, "38;5;208", "70%"),
        (84.9, "38;5;208", "84%"),
        (85.0, "31", "85%"),
        (100.0, "31", "100%"),
    ]

    for value, color, visible in cases:
        line = telemetry.format_resource_line(telemetry.ResourceSnapshot(gpu_utilization_pct=value))
        assert f"\033[{color}m{visible}\033[0m" in line

    unavailable = telemetry.format_resource_line(telemetry.ResourceSnapshot())
    assert "GPU --" in unavailable
    assert "\033[" not in unavailable


def test_resource_snapshot_reads_host_ram_and_gpu_metrics(monkeypatch) -> None:
    import resource_metrics.system as resource_system

    monkeypatch.setattr(
        resource_system.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(used=16 * 1024**3, total=32 * 1024**3, percent=50.0,
                                available=16 * 1024**3),
    )
    monkeypatch.setattr(
        telemetry,
        "_read_gpu",
        lambda: telemetry.parse_nvidia_smi_row("RTX 5090, 0, 81, 37, 20480, 24576"),
    )

    snapshot = telemetry.collect_resource_snapshot()

    assert snapshot.ram_used_bytes == 16 * 1024**3
    assert snapshot.ram_total_bytes == 32 * 1024**3
    assert snapshot.ram_pct == 50.0
    assert snapshot.ram_available_bytes == 16 * 1024**3
    assert snapshot.gpu_utilization_pct == 81.0
    assert snapshot.gpu_memory_utilization_pct == 37.0


def test_resource_sampler_publishes_snapshot_and_stops(monkeypatch) -> None:
    sampled = threading.Event()
    expected = telemetry.ResourceSnapshot(ram_used_bytes=10, ram_total_bytes=20, ram_pct=50.0)

    def collect():
        sampled.set()
        return expected

    monkeypatch.setattr(telemetry, "collect_resource_snapshot", collect)
    sampler = telemetry.ResourceSampler(interval=0.2)
    sampler.start()
    thread = sampler._thread

    try:
        assert sampled.wait(2.0)
        assert sampler.snapshot() == expected
    finally:
        sampler.stop()

    assert thread is not None and not thread.is_alive()


def test_resource_sampler_calls_sample_observer(monkeypatch) -> None:
    sampled = threading.Event()
    expected = telemetry.ResourceSnapshot(ram_pct=77.0)
    received = []
    monkeypatch.setattr(telemetry, "collect_resource_snapshot", lambda: expected)

    sampler = telemetry.ResourceSampler(interval=0.2, on_sample=lambda item: (received.append(item), sampled.set()))
    sampler.start()
    try:
        assert sampled.wait(2.0)
    finally:
        sampler.stop()

    assert received == [expected]


def test_runtime_memory_guard_stops_before_host_exhaustion(monkeypatch):
    import pytest

    monkeypatch.setattr("resource_metrics.system.psutil.virtual_memory", lambda: SimpleNamespace(
        percent=87.5, available=7 * 1024**3))
    monkeypatch.setattr(telemetry, "process_memory_snapshot", lambda: [{"pid": 42, "name": "llama-server", "rss_bytes": 30}])
    with pytest.raises(telemetry.ResourceLimitExceeded, match="87.5%"):
        telemetry.RuntimeMemoryGuard(max_ram_pct=85.0)()


def test_runtime_memory_guard_logs_process_attribution_without_stopping_healthy_host(monkeypatch, caplog):
    import logging

    monkeypatch.setattr("resource_metrics.system.psutil.virtual_memory", lambda: SimpleNamespace(
        percent=55.0, available=28 * 1024**3))
    monkeypatch.setattr(telemetry, "process_memory_snapshot", lambda: [{"pid": 42, "name": "llama-server", "rss_bytes": 30}])
    monkeypatch.setattr(logging.getLogger("agent_benchmark"), "propagate", True)
    with caplog.at_level(logging.INFO):
        telemetry.RuntimeMemoryGuard()()
    assert "llama-server" in caplog.text


def test_runtime_memory_guard_checks_available_ram_even_below_percentage_limit(monkeypatch):
    import pytest

    monkeypatch.setattr("resource_metrics.system.psutil.virtual_memory", lambda: SimpleNamespace(
        percent=70.0, available=3 * 1024**3))
    monkeypatch.setattr(telemetry, "process_memory_snapshot", lambda: [])
    with pytest.raises(telemetry.ResourceLimitExceeded):
        telemetry.RuntimeMemoryGuard()()


def test_process_memory_snapshot_sorts_and_omits_unavailable_process_memory(monkeypatch):
    requested = []

    def process_iter(fields, **kwargs):
        requested.extend(fields)
        return [SimpleNamespace(info={"pid": 1, "name": "small", "memory_info": SimpleNamespace(rss=10)}),
                SimpleNamespace(info={"pid": 2, "name": "large", "memory_info": SimpleNamespace(rss=100)}),
                SimpleNamespace(info={"pid": 3, "name": "unavailable", "memory_info": None})]

    import resource_metrics.process as resource_process

    monkeypatch.setattr(resource_process.psutil, "process_iter", process_iter)
    assert telemetry.process_memory_snapshot(1) == [{"pid": 2, "name": "large", "rss_bytes": 100}]
    assert requested == ["pid", "name", "memory_info"]
