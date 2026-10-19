from __future__ import annotations

import argparse

from cli_tui.app import CliTuiApp
from sysmon.sampler import ProcessStats, SystemStats, TelemetryDisplayMode


def test_telemetry_header_rendering_modes():
    parser = argparse.ArgumentParser(prog="testapp")
    app = CliTuiApp(parser=parser)
    # Mock sample data
    mock_sys = SystemStats(
        cpu_pct=25.0,
        ram_used_bytes=8 * 1024**3,
        ram_total_bytes=16 * 1024**3,
        ram_pct=50.0,
        gpu_name="RTX",
        gpu_load_pct=30.0,
        gpu_mem_used_bytes=4 * 1024**3,
        gpu_mem_total_bytes=8 * 1024**3,
        gpu_temp_c=45.0,
    )
    mock_proc = ProcessStats(
        pid=1234,
        name="worker",
        cpu_pct=15.0,
        memory_rss_bytes=1024**3,
        memory_pct=6.25,
        gpu_load_pct=None,
        gpu_mem_used_bytes=None,
        num_threads=4,
        num_children=0,
        is_active=True,
    )
    app._last_sys_stats = mock_sys
    app._last_proc_stats = mock_proc

    # 1. Full Mode (Option A: 2 lines)
    app.telemetry_mode = TelemetryDisplayMode.FULL
    screen_full = app.render_virtual_screen(height=20, width=80)
    assert any("System: CPU 25%" in line and "RAM" in line for line in screen_full[:3])
    assert any("Active: CPU 15%" in line and "worker" in line for line in screen_full[:3])

    # 2. Compact Mode (Option C: 1 line)
    app.telemetry_mode = TelemetryDisplayMode.COMPACT
    screen_compact = app.render_virtual_screen(height=20, width=80)
    assert any("CPU: 25% (proc 15%)" in line for line in screen_compact[:2])

    # 3. Hidden Mode (0 lines)
    app.telemetry_mode = TelemetryDisplayMode.HIDDEN
    screen_hidden = app.render_virtual_screen(height=20, width=80)
    assert not any("System: CPU" in line or "CPU: 25%" in line for line in screen_hidden[:3])
