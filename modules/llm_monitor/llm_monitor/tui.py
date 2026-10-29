"""Small dependency-free interactive terminal dashboard backed by shared snapshots."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import select
import shutil
import sys
import time
from typing import Any, TextIO

from .alerts import AlertEngine
from .observability import SystemSnapshot


SECTIONS = ("overview", "detail", "timeline", "history", "hardware", "alerts", "help")
SORTS = ("session", "state", "context", "activity")


@dataclass
class TuiState:
    section: str = "overview"
    selected_index: int = 0
    query: str = ""
    searching: bool = False
    paused: bool = False
    refresh_requested: bool = False
    quit_requested: bool = False
    scroll_offset: int = 0
    sort_by: str = "session"

    def handle_key(self, key: str, *, session_count: int) -> None:
        count = max(0, session_count)
        if self.searching:
            if key in {"ESC", "ENTER", "\r", "\n"}:
                self.searching = False
            elif key in {"BACKSPACE", "\x7f", "\b"}:
                self.query = self.query[:-1]
            elif len(key) == 1 and key.isprintable():
                self.query += key
            if self.selected_index >= count:
                self.selected_index = max(0, count - 1)
            return
        if key in {"q", "Q"}:
            self.quit_requested = True
        elif key in {"UP", "k"} and count:
            self.selected_index = max(0, self.selected_index - 1)
        elif key in {"DOWN", "j"} and count:
            self.selected_index = min(count - 1, self.selected_index + 1)
        elif key in {"ENTER", "\r", "\n"}:
            self.section = "detail"
        elif key in {"ESC", "BACKSPACE"}:
            self.section = "overview"
        elif key == "TAB":
            self.section = SECTIONS[(SECTIONS.index(self.section) + 1) % len(SECTIONS)]
        elif key == "SHIFT_TAB":
            self.section = SECTIONS[(SECTIONS.index(self.section) - 1) % len(SECTIONS)]
        elif key == "/":
            self.searching = True
        elif key in {"p", "P"}:
            self.paused = not self.paused
        elif key in {"r", "R"}:
            self.refresh_requested = True
        elif key in {"PAGEUP", "["}:
            self.scroll_offset = max(0, self.scroll_offset - 10)
        elif key in {"PAGEDOWN", "]"}:
            self.scroll_offset += 10
        elif key == "?":
            self.section = "help"
        elif key in {"s", "S"}:
            self.sort_by = SORTS[(SORTS.index(self.sort_by) + 1) % len(SORTS)]
        if self.selected_index >= count:
            self.selected_index = max(0, count - 1)


def render_dashboard(snapshot: SystemSnapshot, state: TuiState, *, detail: Any = None,
                     alerts: list[Any] | None = None, width: int | None = None,
                     height: int | None = None, verbose: bool = False) -> str:
    terminal = shutil.get_terminal_size(fallback=(100, 30))
    width = max(1, width if width is not None else terminal.columns)
    height = max(1, height if height is not None else terminal.lines)
    if width < 30 or height < 8:
        return _clip("Terminal too small for llm-monitor dashboard", width)
    sessions = _visible_sessions(snapshot, state)
    state.selected_index = min(state.selected_index, max(0, len(sessions) - 1))
    current = sessions[state.selected_index] if sessions else None
    header = f"LLM Monitor  [{snapshot.provider.status}]  refreshed {snapshot.refreshed_at}"
    lines = [_clip(header, width), " ".join(
        f"[{name}]" if state.section == name else name for name in SECTIONS
    ) + f"  sort={state.sort_by}"]
    if verbose:
        lines.append(f"Provider instance: {_safe_text(snapshot.provider.provider_instance_id)}; "
                     f"database: {_safe_text(snapshot.database_path or 'unavailable')}")
    if snapshot.provider.error:
        lines.append(f"Provider note: {_safe_text(snapshot.provider.error)}")
    if state.searching or state.query:
        lines.append(f"Filter: /{_safe_text(state.query)}{'_' if state.searching else ''}")
    available = max(0, height - 4)
    if state.section in {"overview", "history"}:
        rows = sessions if state.section == "overview" else [item for item in sessions if not item.is_live]
        lines.extend(_render_sessions(rows, width, state.selected_index, offset=state.scroll_offset)[:available])
        if current:
            latest = current.latest_inference or {}
            latest_tokens = latest.get("tokens") or {}
            cumulative = current.cumulative_tokens or {}
            lines.append(_clip(
                f"Latest inference I/O: {latest_tokens.get('input', 'unknown')}/{latest_tokens.get('output', 'unknown')}  "
                f"Session tokens (bounded window): {cumulative.get('input', 'unknown')}/{cumulative.get('output', 'unknown')}", width))
    elif state.section in {"detail", "timeline"}:
        lines.extend(_render_detail(detail, current, timeline=state.section == "timeline", offset=state.scroll_offset)[:available])
    elif state.section == "hardware":
        lines.extend(_render_hardware(snapshot.hardware)[:available])
    elif state.section == "alerts":
        lines.extend(_render_alerts(alerts or [])[:available])
    else:
        lines.extend([
            "Up/Down or j/k: select session   Enter: detail   Esc: overview",
            "Tab / Shift+Tab: sections   /: filter   r: refresh   p: pause updates",
            "s: cycle sort   [ / ]: scroll   ?: help   q: exit",
            "All dashboard collection is live-only; it does not start persistent recording.",
        ])
    footer = ("PAUSED" if state.paused else "LIVE") + " | q quit  Tab section  Enter inspect  / filter  r refresh  p pause"
    lines.append(_clip(footer, width))
    clipped = [_clip(_safe_text(line), width) for line in lines[:height]]
    return "\n".join(clipped)


def _filtered_sessions(snapshot: SystemSnapshot, query: str):
    if not query:
        return snapshot.sessions
    needle = query.casefold()
    return [item for item in snapshot.sessions if needle in " ".join(
        (item.session_id, item.model or "", item.agent or "", item.state, item.provider_instance_id)
    ).casefold()]


def _visible_sessions(snapshot: SystemSnapshot, state: TuiState):
    sessions = _filtered_sessions(snapshot, state.query)
    if state.section == "history":
        sessions = [item for item in sessions if not item.is_live]
    if state.sort_by == "state":
        return sorted(sessions, key=lambda item: (item.state.casefold(), item.session_id.casefold()))
    if state.sort_by == "context":
        return sorted(sessions, key=lambda item: (item.context_capacity is None,
                                                   -(item.context_capacity or 0), item.session_id.casefold()))
    if state.sort_by == "activity":
        return sorted(sessions, key=lambda item: (item.last_activity_at is not None,
                                                   item.last_activity_at or "", item.session_id.casefold()), reverse=True)
    return sorted(sessions, key=lambda item: (not item.is_live, item.session_id.casefold()))


def _render_sessions(sessions, width: int, selected: int, *, offset: int) -> list[str]:
    if not sessions:
        return ["No sessions match this view. Historical sessions appear when a telemetry database is available."]
    if width >= 100:
        headers = ["Session", "Model", "Agent", "State", "Context", "Latest I/O", "Session I/O", "Comp", "Activity", "Age", "Alerts"]
        rows = []
        for item in sessions:
            latest = item.latest_inference or {}
            latest_tokens = latest.get("tokens") or {}
            cumulative = item.cumulative_tokens or {}
            rows.append([item.session_id[-14:], item.model or "?", item.agent or "?", item.state,
                         f"{_capacity(item.context_capacity)}", f"{latest_tokens.get('input', '?')}/{latest_tokens.get('output', '?')}",
                         f"{cumulative.get('input', '?')}/{cumulative.get('output', '?')}",
                         item.compaction_count if item.compaction_count is not None else "?",
                         _activity(item), _age(item), sum(item.diagnostic_severity.values())])
        try:
            from termdash.table import Table
            table = Table(headers=headers, style="compact", padding=1, border=False)
            table.add_rows(rows)
            rendered = table.render(max_width=width)
        except (ImportError, ValueError):
            rendered = _simple_table(headers, rows, width)
        return [f"{'>' if index == selected else ' '} {_safe_text(line)}" for index, line in
                enumerate(rendered.splitlines()[offset:])]
    headers = ["Session", "State", "Ctx", "Age"]
    rows = [[item.session_id[-15:], item.state, _capacity(item.context_capacity), _age(item)] for item in sessions]
    try:
        from termdash.table import Table
        table = Table(headers=headers, style="compact", padding=1, border=False)
        table.add_rows(rows)
        rendered = table.render(max_width=width)
    except (ImportError, ValueError):
        rendered = _simple_table(headers, rows, width)
    visible = rendered.splitlines()[offset:]
    return [f"{'>' if index == selected else ' '} {_safe_text(line)}" for index, line in enumerate(visible)]


def _simple_table(headers, rows, width):
    result = ["  ".join(headers)]
    result.extend("  ".join(str(cell) for cell in row) for row in rows)
    return "\n".join(_clip(line, width - 2) for line in result)


def _render_detail(detail: Any, summary: Any, *, timeline: bool, offset: int) -> list[str]:
    if detail is None:
        if summary is None:
            return ["Select a session to inspect its observations."]
        return [f"{summary.session_id}  state={summary.state}  model={summary.model or 'unknown'}",
                f"Freshness: {summary.freshness.status} ({_age(summary)}); coverage={summary.coverage.get('status', 'unknown')}",
                "Detailed event history is unavailable until the next snapshot."]
    if hasattr(detail, "to_dict"):
        detail = detail.to_dict()
    if not isinstance(detail, dict):
        return ["Session detail is unavailable."]
    summary_data = detail.get("summary")
    if hasattr(summary_data, "to_dict"):
        summary_data = summary_data.to_dict()
    summary_data = summary_data if isinstance(summary_data, dict) else {}
    if timeline:
        events = detail.get("recent_events", [])
        lines = ["Recent observed event timeline:"]
        for event in events[-200:]:
            lines.append(f"{event.get('timestamp') or 'time unknown'}  {event.get('category', 'event')} "
                         f"{event.get('subtype') or ''}  {event.get('outcome') or ''}")
        if not events:
            lines.append("No detailed events are available in the current observation window.")
        return lines[offset:]
    blockers = summary_data.get("blockers") or {}
    lines = [f"Session {summary_data.get('session_id', 'unknown')}  state={summary_data.get('state', 'unknown')}",
             f"Provider/model/agent: {summary_data.get('provider_instance_id', 'unknown')} / "
             f"{summary_data.get('model') or 'unknown'} / {summary_data.get('agent') or 'unknown'}",
             f"Freshness={((summary_data.get('freshness') or {}).get('status', 'unknown'))}; "
             f"coverage={(detail.get('coverage') or {}).get('status', 'unknown')}; "
             f"permissions={blockers.get('permissions', 'unknown')}; questions={blockers.get('questions', 'unknown')}",
             f"Completion: inference={detail.get('completion', {}).get('inference_completion', 'unknown')}; "
             f"session={detail.get('completion', {}).get('session_completion', 'unknown')}; "
             f"acceptance={detail.get('completion', {}).get('task_acceptance', 'unverified')}",
             "Context trend:"]
    for item in detail.get("context_utilization", [])[-10:]:
        lines.append(f"  {item.get('timestamp') or '?'} input={((item.get('tokens') or {}).get('input', 'unknown'))} "
                     f"utilization={item.get('utilization_percent') if item.get('utilization_percent') is not None else 'unknown'}%")
    lines.append(f"Compactions: {len(detail.get('compactions', []))}; recent tool={_safe_text(str(summary_data.get('current_tool') or 'unknown'))}")
    lines.append("Diagnostics:")
    for finding in detail.get("diagnostics", [])[:12]:
        lines.append(f"  [{finding.get('classification', 'unknown')}/{finding.get('severity', 'info')}] "
                     f"{finding.get('code', 'finding')}: {finding.get('summary', '')}")
    if not detail.get("diagnostics"):
        lines.append("  No supported diagnostic findings.")
    return lines[offset:]


def _render_hardware(hardware: dict[str, Any] | None) -> list[str]:
    if not hardware:
        return ["Hardware telemetry is unavailable.", "Device readings are not attributed to an individual session."]
    lines = [f"Hardware scope: {hardware.get('scope', 'unknown')}  source: {hardware.get('source', 'unknown')}"]
    for key, value in hardware.items():
        if key not in {"scope", "source", "error"}:
            lines.append(f"{key}: {value}")
    if hardware.get("error"):
        lines.append(f"Unavailable: {hardware['error']}")
    lines.append("GPU activity shown here is device-level unless process attribution is explicitly reported.")
    return lines


def _render_alerts(alerts: list[Any]) -> list[str]:
    lines = ["Active evidence-backed alerts:"]
    if not alerts:
        return lines + ["No active alert conditions."]
    for item in alerts[:100]:
        value = item.to_dict() if hasattr(item, "to_dict") else item
        lines.append(f"[{value.get('status', 'active')}/{value.get('severity', 'info')}/"
                     f"{value.get('classification', 'unknown')}] {value.get('session_id', 'system')} "
                     f"{value.get('rule_id')}: {value.get('summary')}")
    return lines


def _activity(summary) -> str:
    tool = summary.current_tool
    return f"tool:{tool.get('tool_name', 'active')}" if tool and tool.get("outcome") == "running" else "inference/event"


def _capacity(value):
    return f"{value / 1024:.0f}K" if isinstance(value, (int, float)) else "?"


def _age(summary):
    value = summary.freshness.age_seconds
    return f"{value:.0f}s" if value is not None else "?"


def _safe_text(value: str) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    return "".join(char if ord(char) >= 32 and ord(char) != 127 else "?" for char in text)


def _clip(value: str, width: int) -> str:
    text = _safe_text(value)
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def run_dashboard(service, *, interval: float = 2.0, initial_session: str | None = None,
                  input_stream: TextIO | None = None, output_stream: TextIO | None = None,
                  alert_store=None, verbose: bool = False) -> int:
    if interval <= 0:
        raise ValueError("--interval must be greater than zero")
    source = input_stream or sys.stdin
    output = output_stream or sys.stdout
    if not source.isatty() or not output.isatty():
        raise RuntimeError("tui requires an interactive terminal; use status, watch, or report for non-interactive output")
    state = TuiState()
    snapshot = None
    previous_frame = None
    next_refresh_at = 0.0
    engine = AlertEngine()
    alerts = []
    with _terminal_mode(source):
        while not state.quit_requested:
            now = time.monotonic()
            refresh_due = snapshot is None or state.refresh_requested or (not state.paused and now >= next_refresh_at)
            if refresh_due:
                snapshot = service.refresh()
                if initial_session:
                    match = next((index for index, item in enumerate(snapshot.sessions)
                                  if item.session_id == initial_session), None)
                    if match is not None:
                        state.selected_index = match
                        state.section = "detail"
                    initial_session = None
                old = alert_store.list_alert_states(limit=10000) if alert_store else []
                batch = engine.evaluate(snapshot, previous=old)
                alerts = batch.active
                if alert_store:
                    for transition in batch.transitions:
                        alert_store.save_alert_state(transition.alert.to_dict())
                state.refresh_requested = False
                next_refresh_at = time.monotonic() + interval
            visible_sessions = _visible_sessions(snapshot, state)
            current = visible_sessions[state.selected_index] if visible_sessions else None
            detail = service.get_detail(current.provider_instance_id, current.session_id) if current else None
            width, height = shutil.get_terminal_size(fallback=(80, 24))
            frame = render_dashboard(snapshot, state, detail=detail, alerts=alerts, width=width, height=height,
                                     verbose=verbose)
            if frame != previous_frame:
                output.write("\x1b[H\x1b[2J" + frame)
                output.flush()
                previous_frame = frame
            key = _read_key(source, min(interval, 0.15))
            if key is not None:
                state.handle_key(key, session_count=len(_visible_sessions(snapshot, state)))
            if state.paused and key is None:
                time.sleep(min(interval, 0.1))
    return 0


@contextmanager
def _terminal_mode(stream: TextIO):
    if os.name == "nt":
        yield
        return
    import termios
    import tty
    descriptor = stream.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor)
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def _read_key(stream: TextIO, timeout: float) -> str | None:
    if os.name == "nt":
        import msvcrt
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                char = msvcrt.getwch()
                if char in {"\x00", "\xe0"}:
                    return {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT", "I": "PAGEUP", "Q": "PAGEDOWN"}.get(msvcrt.getwch())
                return {"\x03": "q", "\x1b": "ESC", "\r": "ENTER", "\b": "BACKSPACE"}.get(char, char)
            time.sleep(0.01)
        return None
    try:
        ready, _, _ = select.select([stream], [], [], max(0.0, timeout))
    except (OSError, ValueError):
        return None
    if not ready:
        return None
    char = stream.read(1)
    if char == "\x1b":
        ready, _, _ = select.select([stream], [], [], 0.02)
        if ready and stream.read(1) == "[":
            tail = stream.read(1)
            return {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT", "Z": "SHIFT_TAB"}.get(tail, "ESC")
        return "ESC"
    return {"\x03": "q", "\r": "ENTER", "\n": "ENTER", "\t": "TAB", "\x7f": "BACKSPACE"}.get(char, char)
