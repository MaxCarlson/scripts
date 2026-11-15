"""Controlled Windows 11 integration tests separating detection, attribution, and targeted suppression."""

from __future__ import annotations

import ctypes
from pathlib import Path
import queue
import re
import subprocess
import sys
import time

import pytest

from procwatch.collectors.win_event import WinEventCollector
from procwatch.collectors.wmi_trace import WmiProcessEvent, WmiProcessTraceCollector
from procwatch.config import GuardConfig, GuardMode, WatchConfig
from procwatch.correlator.ancestry import ProcessTableCache
from procwatch.correlator.engine import LiveCorrelator
from procwatch.guard.window_guard import RawWindowEvent
from procwatch.models import CollectorStats, LiveIncidentEvent, MissingMetadataReason, WindowState
from procwatch.mutex import CollectorAlreadyRunningError, CollectorMutex

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 11 Win32 integration tests")


def _has_interactive_desktop() -> bool:
    """Return True only when running on an interactive desktop with visible windows (e.g., WinSta0\\Default)."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if not user32.GetForegroundWindow():
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    desk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    buf = ctypes.create_unicode_buffer(256)
    user32.GetUserObjectInformationW(desk, 2, buf, 512, None)
    return buf.value.lower() == "default"


def _pump_until(correlator: LiveCorrelator, predicate: object, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        correlator.drain_once()
        if callable(predicate) and predicate():
            return
        time.sleep(0.02)


def test_win32_toolhelp32_snapshot_and_mutex_lifecycle(tmp_path: Path) -> None:
    """Verify real CreateToolhelp32Snapshot seeding and CreateMutexW single-owner enforcement."""
    cache = ProcessTableCache()
    seeded = cache.seed_from_snapshot()
    assert seeded > 5

    m1 = CollectorMutex(name=r"Local\ProcWatchWin32IntegMutex", data_dir=tmp_path, mode="observe", command="watch")
    m2 = CollectorMutex(name=r"Local\ProcWatchWin32IntegMutex", data_dir=tmp_path, mode="smart", command="guard")
    m1.acquire()
    try:
        with pytest.raises(CollectorAlreadyRunningError):
            m2.acquire()
    finally:
        m1.release()
    m2.acquire()
    m2.release()


def test_win32_hook_registration_and_clean_shutdown() -> None:
    """Verify real SetWinEventHook registration and clean WM_QUIT/UnhookWinEvent shutdown."""
    win = WinEventCollector(GuardConfig(mode=GuardMode.OBSERVE))
    win.start(timeout=2.0)
    time.sleep(0.1)
    win.stop(timeout=2.0)


def test_win32_wmi_trace_degrades_gracefully_when_unprivileged() -> None:
    """Verify WmiProcessTraceCollector either activates (if elevated) or reports access_denied cleanly."""
    stats = CollectorStats()
    wmi = WmiProcessTraceCollector(stats=stats)
    status = wmi.start(timeout=2.0)
    try:
        assert status in ("active", "access_denied")
        if status == "access_denied":
            assert wmi.missing_reason == MissingMetadataReason.ACCESS_DENIED
            assert wmi.last_error is not None
    finally:
        wmi.stop(timeout=2.0)


def test_win32_observe_detects_new_console_window() -> None:
    """Independent ground-truth test for WinEvent window detection (read-only observe mode)."""
    if not _has_interactive_desktop():
        pytest.skip("Requires interactive WinSta0\\Default desktop.")

    stats = CollectorStats()
    win_q: queue.Queue[RawWindowEvent] = queue.Queue(maxsize=1024)
    wmi_q: queue.Queue[WmiProcessEvent] = queue.Queue(maxsize=1024)
    events: list[LiveIncidentEvent] = []

    cache = ProcessTableCache()
    cache.seed_from_snapshot()
    win = WinEventCollector(GuardConfig(mode=GuardMode.OBSERVE), event_queue=win_q, stats=stats)
    correlator = LiveCorrelator(
        process_cache=cache,
        win_queue=win_q,
        wmi_queue=wmi_q,
        watch_config=WatchConfig(),
        stats=stats,
        on_incident=events.append,
    )

    win.start(timeout=2.0)
    title_marker = "PROCWATCH_DETECT_TEST"
    proc: subprocess.Popen[bytes] | None = None
    try:
        CREATE_NEW_CONSOLE = 0x00000010
        proc = subprocess.Popen(
            ["conhost.exe", "cmd.exe", "/c", f"title {title_marker} & ping -n 2 127.0.0.1 >nul"],
            creationflags=CREATE_NEW_CONSOLE,
        )
        _pump_until(
            correlator,
            lambda: any(
                e.window is not None and title_marker in e.window.current_title
                for e in events
            ),
            timeout=5.0,
        )
        detected = [e for e in events if e.window is not None and title_marker in e.window.current_title]
        assert len(detected) >= 1, f"Expected window detection for {title_marker}; stats={stats}"
        assert stats.guard_suppressed_count == 0
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=3.0)
        win.stop(timeout=2.0)


def test_win32_attributes_client_process_to_console_window() -> None:
    """Verify client-process attribution even when top-level terminal title does not mirror client title."""
    if not _has_interactive_desktop():
        pytest.skip("Requires interactive WinSta0\\Default desktop.")

    stats = CollectorStats()
    win_q: queue.Queue[RawWindowEvent] = queue.Queue(maxsize=1024)
    wmi_q: queue.Queue[WmiProcessEvent] = queue.Queue(maxsize=1024)
    events: list[LiveIncidentEvent] = []

    cache = ProcessTableCache()
    cache.seed_from_snapshot()

    wmi = WmiProcessTraceCollector(event_queue=wmi_q, stats=stats)
    wmi.start(timeout=2.0)

    win = WinEventCollector(GuardConfig(mode=GuardMode.OBSERVE), event_queue=win_q, stats=stats)
    correlator = LiveCorrelator(
        process_cache=cache,
        win_queue=win_q,
        wmi_queue=wmi_q,
        watch_config=WatchConfig(),
        stats=stats,
        on_incident=events.append,
        wmi_missing_reason=wmi.missing_reason or MissingMetadataReason.ACCESS_DENIED,
    )

    win.start(timeout=2.0)
    proc: subprocess.Popen[bytes] | None = None
    try:
        CREATE_NEW_CONSOLE = 0x00000010
        proc = subprocess.Popen(
            ["cmd.exe", "/c", "ping -n 3 127.0.0.1 >nul"],
            creationflags=CREATE_NEW_CONSOLE,
        )
        _pump_until(
            correlator,
            lambda: any(
                e.window is not None
                and (e.window.owner_pid == proc.pid or any(c.pid == proc.pid for c in e.candidate_initiators))
                for e in events
            ),
            timeout=5.0,
        )
        attributed = [
            e
            for e in events
            if e.window is not None
            and (e.window.owner_pid == proc.pid or any(c.pid == proc.pid for c in e.candidate_initiators))
        ]
        assert len(attributed) >= 1, (
            f"Expected attribution of client pid={proc.pid}; stats={stats}, "
            f"windows={[(e.window.window_class, e.window.owner_pid, [c.pid for c in e.candidate_initiators]) for e in events if e.window]}"
        )
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=3.0)
        win.stop(timeout=2.0)
        wmi.stop(timeout=2.0)


def test_win32_smart_mode_does_not_suppress_interactive_powershell() -> None:
    """Deliberately opened interactive PowerShell window must NOT be suppressed in smart mode."""
    if not _has_interactive_desktop():
        pytest.skip("Requires interactive WinSta0\\Default desktop.")

    stats = CollectorStats()
    win_q: queue.Queue[RawWindowEvent] = queue.Queue(maxsize=1024)
    wmi_q: queue.Queue[WmiProcessEvent] = queue.Queue(maxsize=1024)
    events: list[LiveIncidentEvent] = []

    cache = ProcessTableCache()
    cache.seed_from_snapshot()
    win = WinEventCollector(GuardConfig(mode=GuardMode.SMART), event_queue=win_q, stats=stats)
    correlator = LiveCorrelator(
        process_cache=cache,
        win_queue=win_q,
        wmi_queue=wmi_q,
        watch_config=WatchConfig(),
        stats=stats,
        on_incident=events.append,
    )

    win.start(timeout=2.0)
    proc: subprocess.Popen[bytes] | None = None
    try:
        CREATE_NEW_CONSOLE = 0x00000010
        proc = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "$Host.UI.RawUI.WindowTitle = 'Windows PowerShell'; Start-Sleep -Milliseconds 700",
            ],
            creationflags=CREATE_NEW_CONSOLE,
        )
        proc.wait(timeout=5.0)
        _pump_until(correlator, lambda: False, timeout=0.3)

        suppressed_for_ps = [
            e
            for e in events
            if e.window is not None
            and (e.window.owner_pid == proc.pid or any(c.pid == proc.pid for c in e.candidate_initiators))
            and e.window.state == WindowState.SUPPRESSED
        ]
        assert len(suppressed_for_ps) == 0
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
        win.stop(timeout=2.0)


def test_win32_smart_suppresses_targeted_console_and_restores() -> None:
    """Verify narrowly targeted smart-mode suppression and full cleanup without affecting other windows."""
    if not _has_interactive_desktop():
        pytest.skip("Requires interactive WinSta0\\Default desktop.")

    stats = CollectorStats()
    win_q: queue.Queue[RawWindowEvent] = queue.Queue(maxsize=1024)
    wmi_q: queue.Queue[WmiProcessEvent] = queue.Queue(maxsize=1024)
    events: list[LiveIncidentEvent] = []

    target_marker = "PROCWATCH_SUPPRESS_TARGET"
    guard_cfg = GuardConfig(
        mode=GuardMode.SMART,
        restore_focus=False,
        title_pattern=re.compile(target_marker),
    )
    cache = ProcessTableCache()
    cache.seed_from_snapshot()
    win = WinEventCollector(guard_cfg, event_queue=win_q, stats=stats)
    correlator = LiveCorrelator(
        process_cache=cache,
        win_queue=win_q,
        wmi_queue=wmi_q,
        watch_config=WatchConfig(),
        stats=stats,
        on_incident=events.append,
    )

    win.start(timeout=2.0)
    proc: subprocess.Popen[bytes] | None = None
    try:
        CREATE_NEW_CONSOLE = 0x00000010
        proc = subprocess.Popen(
            ["conhost.exe", "cmd.exe", "/c", f"title {target_marker} & ping -n 2 127.0.0.1 >nul"],
            creationflags=CREATE_NEW_CONSOLE,
        )
        _pump_until(
            correlator,
            lambda: any(
                e.window is not None
                and e.window.state == WindowState.SUPPRESSED
                and target_marker in e.window.current_title
                for e in events
            ),
            timeout=5.0,
        )
        suppressed = [
            e
            for e in events
            if e.window is not None
            and e.window.state == WindowState.SUPPRESSED
            and target_marker in e.window.current_title
        ]
        assert len(suppressed) >= 1, f"Expected targeted suppression of {target_marker}; stats={stats}"
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=3.0)
        win.stop(timeout=2.0)
        assert all(not inst.modified_by_guard for inst in win.engine.active_instances.values())
