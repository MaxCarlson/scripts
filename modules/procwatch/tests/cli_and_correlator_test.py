"""Unit tests for CLI argument parsing, correlator, and single-owner mutex."""

from __future__ import annotations

from pathlib import Path
import queue
import time

import pytest

from procwatch.cli import build_parser, main
from procwatch.collectors.wmi_trace import WmiProcessEvent
from procwatch.config import WatchConfig
from procwatch.correlator.ancestry import ProcessTableCache
from procwatch.correlator.engine import LiveCorrelator
from procwatch.guard.window_guard import EVENT_OBJECT_SHOW, RawWindowEvent
from procwatch.models import ConfidenceLevel, LiveIncidentEvent, WindowState
from procwatch.mutex import CollectorAlreadyRunningError, CollectorMutex


def test_cli_parser_has_short_and_long_flags() -> None:
    parser = build_parser()
    args_w = parser.parse_args(["watch", "-p", "-g", "-m", "smart", "-c", "-s", "-f", "python", "-o", "out.jsonl"])
    assert args_w.command == "watch"
    assert args_w.popups_only is True
    assert args_w.guard_windows is True
    assert args_w.guard_mode == "smart"
    assert args_w.collapse_bursts is True
    assert args_w.show_headless is True
    assert args_w.filter_regex == "python"
    assert args_w.output_file == Path("out.jsonl")

    args_g = parser.parse_args(["guard", "-m", "observe", "-n", "-t", "python", "-e", "PowerShell", "-q"])
    assert args_g.command == "guard"
    assert args_g.mode == "observe"
    assert args_g.no_focus_restore is True
    assert args_g.quiet is True


def test_cli_invalid_regex_returns_error_code(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["watch", "-f", "[unclosed"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Configuration error" in err


def test_correlator_distinguishes_windows_terminal_owner_from_initiator() -> None:
    cache = ProcessTableCache(boot_id="boot-test")
    win_q: queue.Queue[RawWindowEvent] = queue.Queue()
    wmi_q: queue.Queue[WmiProcessEvent] = queue.Queue()
    emitted: list[LiveIncidentEvent] = []

    now_ns = time.monotonic_ns()
    # Windows Terminal host process
    cache.record_start(pid=1000, ppid=500, image_name="WindowsTerminal.exe", monotonic_ns=now_ns - 500_000_000, enrich_live=False)
    # Initiating background python process started 20ms before the window
    wmi_q.put(
        WmiProcessEvent(
            kind="start",
            pid=2000,
            ppid=1500,
            process_name="python.exe",
            timestamp_utc="2026-11-15T00:00:00.000Z",
            monotonic_ns=now_ns - 20_000_000,
        )
    )
    win_q.put(
        RawWindowEvent(
            window_instance_id="boot-test:999:1",
            hwnd=999,
            owner_pid=1000,
            owner_tid=1001,
            window_class="CASCADIA_HOSTING_WINDOW_CLASS",
            title=r"C:\repo\.venv\Scripts\python.exe",
            win_event=EVENT_OBJECT_SHOW,
            visible=True,
            is_foreground=True,
            foreground_hwnd=999,
            state=WindowState.ALLOWED,
            timestamp_utc="2026-11-15T00:00:00.020Z",
            monotonic_ns=now_ns,
            callback_arrival_ns=now_ns,
        )
    )

    correlator = LiveCorrelator(
        process_cache=cache,
        win_queue=win_q,
        wmi_queue=wmi_q,
        watch_config=WatchConfig(),
        on_incident=emitted.append,
    )
    correlator.drain_once()

    win_incidents = [e for e in emitted if e.window is not None]
    assert len(win_incidents) == 1
    inc = win_incidents[0]
    assert inc.process is not None
    assert inc.process.image_name == "WindowsTerminal.exe"
    assert len(inc.candidate_initiators) >= 1
    assert inc.candidate_initiators[0].pid == 2000
    assert inc.candidate_initiators[0].confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)


def test_collector_mutex_blocks_duplicate_owner(tmp_path: Path) -> None:
    m1 = CollectorMutex(name=r"Local\ProcWatchTestMutex_Unit", data_dir=tmp_path, mode="observe", command="watch")
    m2 = CollectorMutex(name=r"Local\ProcWatchTestMutex_Unit", data_dir=tmp_path, mode="smart", command="guard")
    m1.acquire()
    try:
        with pytest.raises(CollectorAlreadyRunningError):
            m2.acquire()
    finally:
        m1.release()
    # After release, m2 can acquire cleanly
    m2.acquire()
    m2.release()


def test_cli_help_menus_include_examples(capsys) -> None:
    from procwatch.cli import build_parser

    parser = build_parser()
    main_help = parser.format_help()
    assert "Examples:" in main_help
    assert "procwatch watch -g -m all-consoles" in main_help
    assert "procwatch guard -m all-consoles" in main_help
    assert "subset" in main_help.lower()

    expected_subcommands = (
        "watch",
        "guard",
        "doctor",
        "history",
        "explain",
        "mark",
        "scan",
        "audit",
        "analyze",
        "exec",
    )
    for subcmd in expected_subcommands:
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args([subcmd, "-h"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "Examples:" in out, f"Missing Examples section in `{subcmd} -h`"
        assert f"procwatch {subcmd}" in out, f"Missing command example in `{subcmd} -h`"
