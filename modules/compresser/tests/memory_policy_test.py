"""Available RAM is explicit telemetry, never a substitute for safe defaults."""

import pytest

import compresser.memory_policy as memory_policy_module


def test_available_memory_bytes_uses_shared_memory_measurement(monkeypatch):
    monkeypatch.setattr(memory_policy_module, "memory_stats", lambda: {"available": 123456})

    assert memory_policy_module.available_memory_bytes() == 123456


def test_available_memory_bytes_keeps_native_fallback_when_shared_sample_is_unavailable(monkeypatch):
    from pathlib import Path
    from cross_platform import system_utils

    class LinuxSystemUtils:
        @staticmethod
        def is_windows():
            return False

        @staticmethod
        def is_linux():
            return True

    monkeypatch.setattr(memory_policy_module, "memory_stats", lambda: None)
    monkeypatch.setattr(system_utils, "SystemUtils", LinuxSystemUtils)
    monkeypatch.setattr(Path, "read_text", lambda self: "MemAvailable: 123 kB\n")

    assert memory_policy_module.available_memory_bytes() == 123 * 1024


def test_fixed_default_and_explicit_budgets_never_query_ram():
    from compresser.memory_policy import resolve_memory_policy

    def forbidden():
        pytest.fail("Fixed budget queried system RAM")

    assert resolve_memory_policy(512, provider=forbidden).budget_mib == 512
    assert resolve_memory_policy(64, provider=forbidden).budget_mib == 64


@pytest.mark.parametrize("available,expected", [(320 * 1024**2, 64), (1024 * 1024**2, 204), (100 * 1024**3, 20480)])
def test_auto_uses_available_fraction_floor_and_cap(available, expected):
    from compresser.memory_policy import resolve_memory_policy

    policy = resolve_memory_policy("auto", provider=lambda: available)
    assert policy.budget_mib == expected
    assert policy.diagnostics()["available_bytes_at_start"] == available
    assert policy.diagnostics()["requested"] == "auto"


def test_human_units_and_percentages_parsing():
    from compresser.memory_policy import parse_memory_budget, resolve_memory_policy

    assert parse_memory_budget("16G") == 16384
    assert parse_memory_budget("8GB") == 8192
    assert parse_memory_budget("2048M") == 2048
    assert parse_memory_budget("50%") == "50%"
    assert parse_memory_budget(8192) == 8192

    # Percentage resolves against available RAM
    policy = resolve_memory_policy("50%", provider=lambda: 16384 * 1024**2)
    assert policy.budget_mib == 8192


@pytest.mark.parametrize("available", [None, 0, 319 * 1024**2, float("nan"), float("inf")])
def test_auto_unknown_or_low_ram_fails_without_total_fallback(available):
    from compresser.memory_policy import resolve_memory_policy

    with pytest.raises(ValueError, match="-B"):
        resolve_memory_policy("auto", provider=lambda: available)


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "63", "0%", "101%", "-5G", "1.5"])
def test_bad_memory_policy_values_reject(value):
    import argparse
    from compresser.memory_policy import parse_memory_budget

    with pytest.raises(argparse.ArgumentTypeError):
        parse_memory_budget(value)


def test_pressure_allowance_stops_new_reservations_and_recovers():
    from compresser.memory_policy import resolve_memory_policy

    available = [1024 * 1024**2]
    policy = resolve_memory_policy("auto", provider=lambda: available[0])
    policy.poll_interval = 0
    available[0] = 1
    assert policy.admission_allowance() == 0
    available[0] = 1024 * 1024**2
    assert policy.admission_allowance() == policy.budget_mib * 1024**2


def test_memory_scheduler_pressure_limit_does_not_reserve_or_reject_jobs():
    from compresser.scheduler import MemoryScheduler

    scheduler = MemoryScheduler([("large", 100), ("small", 10)], 200, 2)
    assert scheduler.next_job(available_limit=0) is None
    assert scheduler.reserved_bytes == 0
    assert scheduler.next_job(available_limit=15) == ("small", 10)
    scheduler.release(10)
    assert scheduler.next_job(available_limit=200) == ("large", 100)


@pytest.mark.parametrize("cancel", [False, True])
def test_engine_pressure_wait_recovers_or_cancels_without_starting_owners(tmp_path, cancel, monkeypatch):
    from PIL import Image
    from compresser import CompressionEngine, CompressionStrategy, scan_directory
    from compresser.memory_policy import resolve_memory_policy

    path = tmp_path / "01.png"
    Image.new("RGB", (40, 40)).save(path)
    _, images = scan_directory(tmp_path)
    available = [1024 * 1024**2]
    policy = resolve_memory_policy("auto", provider=lambda: available[0])
    policy.poll_interval = 0
    engine = CompressionEngine(memory_budget_bytes=policy.budget_mib * 1024**2, memory_policy=policy)
    available[0] = 0
    waiting = []

    def observe(state):
        if state["waiting_reason"] == "system memory pressure":
            waiting.append(state)
            assert state["active_workers"] == 0 and state["reserved_bytes"] == 0
            if cancel:
                raise KeyboardInterrupt()
            available[0] = 1024 * 1024**2

    try:
        if cancel:
            with pytest.raises(KeyboardInterrupt):
                engine.compress_batch(
                    images, CompressionStrategy("png", format="png", method=0), activity_callback=observe
                )
        else:
            result = engine.compress_batch(
                images, CompressionStrategy("png", format="png", method=0), activity_callback=observe
            )
            assert result.failed_count == 0 and result.processed_images == 1
        assert waiting
    finally:
        engine.cache.close()


def test_cli_auto_resolves_once_and_reports_policy(tmp_path, monkeypatch, capsys):
    import json
    from PIL import Image
    from cli_test_support import main
    import compresser.memory_policy as module

    Image.new("RGB", (40, 40)).save(tmp_path / "01.png")
    monkeypatch.setattr(module, "available_memory_bytes", lambda: 1024 * 1024**2)
    assert main(["-i", str(tmp_path), "-B", "auto", "-f", "png", "-e", "0", "-J"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["worker_diagnostics"]["memory_policy"]["requested"] == "auto"
    assert report["worker_diagnostics"]["memory_policy"]["resolved_mib"] == 204
