from datetime import datetime, timezone
from dataclasses import replace
from io import StringIO
from contextlib import nullcontext

import pytest

from llm_monitor.observability import Freshness, ProviderStatus, SessionSummary, SystemSnapshot, SystemSummary
from llm_monitor.tui import TuiState, render_dashboard


def make_snapshot():
    summary = SessionSummary("http://localhost:4096", "session-123456", None, "model-a", "build", 65536,
        "inference_running", "inference_running", "observed", "opencode_poll", "2026-01-01T00:00:00+00:00",
        Freshness("fresh", "2026-01-01T00:00:00+00:00", 0, "opencode"), {"status": "partial"},
        {"tokens": {"input": 9000, "output": 200}}, {"input": 10000, "output": 500}, 2,
        {"tool_name": "read"}, {"permissions": 0, "questions": 0}, {"warning": 1}, True, [], [], [])
    return SystemSnapshot(1, datetime.now(timezone.utc).isoformat(),
        ProviderStatus("http://localhost:4096", "connected", "2026-01-01T00:00:00+00:00"),
        SystemSummary(1, 1, 0, 0, 0, ["model-a"], "not_started_by_dashboard"), [summary],
        {"scope": "device_snapshot", "utilization": 70}, None)


def test_tui_state_navigation_filter_pause_refresh_and_exit():
    state = TuiState()
    state.handle_key("DOWN", session_count=3)
    assert state.selected_index == 1
    state.handle_key("ENTER", session_count=3)
    assert state.section == "detail"
    state.handle_key("ESC", session_count=3)
    assert state.section == "overview"
    state.handle_key("p", session_count=3)
    assert state.paused
    state.handle_key("r", session_count=3)
    assert state.refresh_requested
    state.handle_key("/", session_count=3)
    state.handle_key("x", session_count=3)
    assert state.query == "x"
    state.handle_key("ESC", session_count=3)
    assert not state.searching
    state.handle_key("q", session_count=3)
    assert state.quit_requested
    state.handle_key("s", session_count=3)
    assert state.sort_by == "state"


def test_tui_render_is_width_bounded_and_distinguishes_unknown_and_stale():
    state = TuiState()
    output = render_dashboard(make_snapshot(), state, width=52, height=12)
    assert all(len(line) <= 52 for line in output.splitlines())
    assert "inference_running" in output or "inference" in output
    assert "Context" in output or "ctx" in output.casefold()
    assert "cumulative" in output.casefold() or "session tokens" in output.casefold()


def test_tui_detail_render_handles_missing_data_and_html_like_text():
    summary = make_snapshot().sessions[0]
    detail = {"summary": summary.to_dict(), "recent_events": [], "diagnostics": [],
              "coverage": {"status": "unavailable"}, "completion": {"task_acceptance": "unverified"}}
    state = TuiState(section="detail")
    output = render_dashboard(make_snapshot(), state, detail=detail, width=44, height=14)
    assert "unknown" in output.casefold() or "unavailable" in output.casefold()
    assert all(len(line) <= 44 for line in output.splitlines())


def test_history_section_selects_historical_sessions_only():
    from llm_monitor.tui import _visible_sessions

    snapshot = make_snapshot()
    active = snapshot.sessions[0]
    historical = replace(active, session_id="historical-session", is_live=False)
    snapshot = replace(snapshot, sessions=[active, historical])
    state = TuiState(section="history")

    assert [item.session_id for item in _visible_sessions(snapshot, state)] == ["historical-session"]


def test_tui_requires_interactive_terminal(tmp_path):
    from llm_monitor.tui import run_dashboard

    with pytest.raises(RuntimeError, match="interactive terminal"):
        run_dashboard(None, interval=1, input_stream=StringIO(), output_stream=StringIO())


def test_tui_respects_refresh_interval_and_exits_cleanly(monkeypatch):
    from llm_monitor import tui

    class Tty(StringIO):
        def isatty(self):
            return True

    class Service:
        calls = 0

        def refresh(self):
            self.calls += 1
            return make_snapshot()

        def get_detail(self, *_args):
            return None

    keys = iter([None, "q"])
    monkeypatch.setattr(tui, "_terminal_mode", lambda _stream: nullcontext())
    monkeypatch.setattr(tui, "_read_key", lambda *_args: next(keys))
    service = Service()

    assert tui.run_dashboard(service, interval=30, input_stream=Tty(), output_stream=Tty()) == 0
    assert service.calls == 1
