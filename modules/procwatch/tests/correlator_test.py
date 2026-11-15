"""Unit tests for Phase 2 collectors (XML parsing) and causal correlator modules."""

from __future__ import annotations

import queue
import sys
from pathlib import Path

from procwatch.collectors.sysmon_evt import parse_sysmon_event_xml
from procwatch.collectors.task_events import parse_task_event_xml
from procwatch.correlator.agent_context import infer_agent_context_from_env, parse_procwatch_context
from procwatch.correlator.ancestry import ProcessTableCache
from procwatch.correlator.engine import LiveCorrelator
from procwatch.correlator.peb_git import read_pe_subsystem, resolve_git_context
from procwatch.correlator.scorer import score_window_attribution
from procwatch.guard.window_guard import RawWindowEvent
from procwatch.models import (
    CollectorStats,
    ConfidenceLevel,
    MissingMetadataReason,
    ProcessIdentity,
    ProcessObservation,
    WindowObservation,
    WindowState,
)
from procwatch.storage import FlightRecorderStorage


def test_parse_sysmon_event_1_and_5() -> None:
    xml_create = """
    <Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
      <System>
        <EventID>1</EventID>
        <EventRecordID>5501</EventRecordID>
        <TimeCreated SystemTime="2026-11-15T12:00:00.123Z"/>
        <Computer>WORKSTATION</Computer>
      </System>
      <EventData>
        <Data Name="ProcessGuid">{AAA-111}</Data>
        <Data Name="ProcessId">1234</Data>
        <Data Name="Image">C:\\Python312\\python.exe</Data>
        <Data Name="CommandLine">python.exe -m pytest</Data>
        <Data Name="CurrentDirectory">C:\\Users\\mcarls\\src\\scripts</Data>
        <Data Name="User">WORKSTATION\\mcarls</Data>
        <Data Name="IntegrityLevel">Medium</Data>
        <Data Name="ParentProcessGuid">{AAA-000}</Data>
        <Data Name="ParentProcessId">900</Data>
        <Data Name="ParentImage">C:\\Windows\\System32\\cmd.exe</Data>
      </EventData>
    </Event>
    """
    parsed = parse_sysmon_event_xml(xml_create)
    assert parsed is not None
    assert parsed.event_id == 1
    assert parsed.record_id == "5501"
    assert parsed.pid == 1234
    assert parsed.ppid == 900
    assert parsed.process_guid == "{AAA-111}"
    assert parsed.parent_guid == "{AAA-000}"
    assert parsed.current_directory == r"C:\Users\mcarls\src\scripts"

    xml_stop = """
    <Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
      <System><EventID>5</EventID><EventRecordID>5502</EventRecordID></System>
      <EventData>
        <Data Name="ProcessGuid">{AAA-111}</Data>
        <Data Name="ProcessId">1234</Data>
        <Data Name="Image">C:\\Python312\\python.exe</Data>
      </EventData>
    </Event>
    """
    stopped = parse_sysmon_event_xml(xml_stop)
    assert stopped is not None
    assert stopped.event_id == 5
    assert stopped.pid == 1234


def test_parse_task_scheduler_events() -> None:
    xml_129 = """
    <Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
      <System>
        <EventID>129</EventID>
        <EventRecordID>77</EventRecordID>
        <TimeCreated SystemTime="2026-11-15T12:05:00.000Z"/>
      </System>
      <EventData>
        <Data Name="TaskName">\\Microsoft\\Windows\\UpdateCheck</Data>
        <Data Name="Path">C:\\Windows\\System32\\cmd.exe</Data>
        <Data Name="ProcessID">4455</Data>
        <Data Name="EnginePID">888</Data>
      </EventData>
    </Event>
    """
    info = parse_task_event_xml(xml_129)
    assert info is not None
    assert info.event_id == 129
    assert info.task_path == r"\Microsoft\Windows\UpdateCheck"
    assert info.process_id == 4455
    assert info.engine_pid == 888


def test_pe_subsystem_and_git_worktree_resolution() -> None:
    sub = read_pe_subsystem(sys.executable)
    if sys.platform == "win32":
        assert sub == "CUI"
    assert read_pe_subsystem(Path(__file__)) is None

    git_ctx = resolve_git_context(Path(__file__).resolve())
    assert git_ctx is not None
    assert git_ctx.repo_root is not None
    assert git_ctx.worktree_path is not None
    assert git_ctx.branch is not None and "procwatch" in git_ctx.branch


def test_agent_context_instrumented_vs_heuristic() -> None:
    explicit = parse_procwatch_context(
        '{"agent_kind": "codex", "agent_session": "t-99", "correlation_id": "corr-1", "phase": "test"}'
    )
    assert explicit is not None
    assert explicit.trust_level == "instrumented"
    assert explicit.agent_kind == "codex"
    assert explicit.correlation_id == "corr-1"

    heuristic = infer_agent_context_from_env({"CODEX_THREAD_ID": "thr-123"})
    assert heuristic is not None
    assert heuristic.trust_level == "heuristic"
    assert heuristic.agent_kind == "codex"

    assert parse_procwatch_context("{not-json") is None


def test_scorer_confidence_and_missing_reasons() -> None:
    win = WindowObservation(
        window_instance_id="w1",
        hwnd=100,
        owner_pid=2222,
        owner_tid=1,
        window_class="ConsoleWindowClass",
        initial_title="cmd",
        current_title="cmd",
        first_seen_monotonic_ns=1_000_000_000,
    )
    empty_res = score_window_attribution(win, [])
    assert empty_res.confidence == ConfidenceLevel.UNKNOWN
    assert MissingMetadataReason.NOT_EMITTED in empty_res.missing_reasons

    proc = ProcessObservation(
        identity=ProcessIdentity.canonical_kernel("b1", 2222, 12345),
        image_name="python.exe",
        start_monotonic_ns=990_000_000,
    )
    high_res = score_window_attribution(
        win,
        [proc],
        agent_context=parse_procwatch_context('{"agent_kind": "codex", "correlation_id": "c1"}'),
    )
    assert high_res.confidence == ConfidenceLevel.HIGH
    assert len(high_res.edges) == 1


def test_live_correlator_persists_to_storage(tmp_path: Path) -> None:
    db_path = tmp_path / "live.db"
    storage = FlightRecorderStorage(db_path=db_path)
    try:
        cache = ProcessTableCache()
        cache.record_start(
            pid=9191,
            ppid=100,
            image_name="cmd.exe",
            command_line="cmd.exe /c echo hi",
            source="wmi_trace",
            monotonic_ns=1_000_000_000,
        )
        win_q: queue.Queue[RawWindowEvent] = queue.Queue()
        wmi_q = queue.Queue()
        correlator = LiveCorrelator(
            process_cache=cache,
            win_queue=win_q,
            wmi_queue=wmi_q,
            stats=CollectorStats(),
            storage=storage,
        )
        correlator.process_window_event(
            RawWindowEvent(
                window_instance_id="win-9191",
                hwnd=0x9191,
                owner_pid=9191,
                owner_tid=1,
                window_class="ConsoleWindowClass",
                title="cmd.exe",
                win_event=0x8002,
                visible=True,
                is_foreground=False,
                foreground_hwnd=0,
                state=WindowState.FIRST_SEEN,
                timestamp_utc="2099-01-01T00:00:00.000Z",
                monotonic_ns=1_050_000_000,
                callback_arrival_ns=1_050_000_000,
            )
        )
        rows = storage.query_history(popups_only=True)
        assert len(rows) == 1
        assert "cmd.exe" in rows[0]["summary_text"]
    finally:
        storage.close()
