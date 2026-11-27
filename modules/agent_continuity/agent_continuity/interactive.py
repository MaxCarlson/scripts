"""Small, dependency-free interactive selector for llmd."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from typing import Any, TextIO

from .dispatcher import DispatcherService
from .terminal_format import (
    clip_display,
    color_enabled,
    display_width,
    format_timestamp,
    pad_semantic,
    provider_semantic,
    runtime_semantic,
    semantic_color,
)


def _gui_selector_line(row: dict[str, Any], width: int, *, header: bool = False, enabled: bool = False) -> str:
    if width < 62:
        name_width = max(0, width - 40)
        gui = 'GUI Conversation' if header else row['alias']
        date = 'Last Activity' if header else format_timestamp(row.get('last_activity_at'))
        return f"{pad_semantic(gui, name_width, 'label' if header else 'gui', enabled=enabled)}  " \
               f"{pad_semantic(date, 16, 'label' if header else 'timestamp', enabled=enabled)}"
    name_width = max(12, min(36, width - 25))
    date = 'Last Activity' if header else format_timestamp(row.get('last_activity_at'))
    gui = 'GUI Conversation' if header else row['alias']
    return f"{pad_semantic(date, 16, 'label' if header else 'timestamp', enabled=enabled)}  " \
           f"{pad_semantic(gui, name_width, 'label' if header else 'gui', enabled=enabled)}"


def _agent_selector_line(row: dict[str, Any], width: int, *, header: bool = False, enabled: bool = False) -> str:
    provider = "Provider" if header else str(row.get("current_provider") or row.get("pending_provider") or "—").upper()
    provider_semantic_name = {"CODEX": "provider_codex", "AGY": "provider_agy"}.get(provider, "label" if header else "")
    lifecycle = "Lifecycle" if header else str(row.get("state") or "unknown")
    lifecycle_style = "label" if header else lifecycle.casefold() if lifecycle.casefold() in {"active", "inactive", "completed"} else "unknown"
    runtime = "Runtime" if header else row.get("runtime_status")
    runtime_text = runtime_semantic(str(runtime), enabled=enabled) if runtime else ""
    if width < 70:
        name_width = max(8, min(24, width - 22))
        session = "Current Session" if header else row.get("current_session_id") or (
            "pending" if row.get("pending_launch_id") else "unresolved"
        )
        date = "Last Activity" if header else format_timestamp(row.get("last_activity_at"))
        name = pad_semantic('Agent' if header else row['name'], name_width,
                            'label' if header else 'agent', enabled=enabled)
        first = f"{name}  {pad_semantic(provider, 7, provider_semantic_name, enabled=enabled)}  " \
                f"{pad_semantic(lifecycle, 9, lifecycle_style, enabled=enabled)}"
        runtime_cells = display_width(str(runtime or "")) + (2 if runtime else 0)
        session_text = semantic_color(clip_display(session, max(1, width - 22 - runtime_cells)),
                                      'session' if session not in {'pending', 'unresolved'} else session,
                                      enabled=enabled)
        details = (f"    {pad_semantic(date, 16, 'label' if header else 'timestamp', enabled=enabled)}  "
                   f"{runtime_text + '  ' if runtime else ''}{session_text}")
        return first + "\n" + details
    name_width = max(12, min(32, (width - 72) // 2))
    session_width = max(1, width - name_width - 41 - (14 if runtime else 0))
    date = "Last Activity" if header else format_timestamp(row.get("last_activity_at"))
    name = "Agent" if header else row["name"]
    session = "Current Session" if header else row.get("current_session_id") or (
        "pending" if row.get("pending_launch_id") else "unresolved"
    )
    session_text = semantic_color(clip_display(session, session_width),
                                  'session' if session not in {'pending', 'unresolved'} else session,
                                  enabled=enabled)
    return f"{pad_semantic(date, 16, 'label' if header else 'timestamp', enabled=enabled)}  " \
           f"{pad_semantic(name, name_width, 'label' if header else 'agent', enabled=enabled)}  " \
           f"{pad_semantic(provider, 8, provider_semantic_name, enabled=enabled)}  " \
           f"{pad_semantic(lifecycle, 9, lifecycle_style, enabled=enabled)}  " \
           f"{pad_semantic(str(runtime), 12, { 'IN USE': 'runtime_in_use', 'NOT OBSERVED': 'runtime_not_observed', 'PENDING': 'pending', 'UNKNOWN': 'unknown'}.get(str(runtime).upper(), ''), enabled=enabled) + '  ' if runtime else ''}" \
           f"{session_text}"


def filter_items(items: list[dict[str, Any]], query: str, *, key: str = "name") -> list[dict[str, Any]]:
    """Filter names by case-insensitive substring while preserving activity order."""
    needle = query.casefold()
    return [item for item in items if needle in str(item.get(key) or "").casefold()]


def _read_key(stream: TextIO) -> str:
    if stream is sys.stdin and stream.isatty():
        if sys.platform == "win32":
            import msvcrt

            value = msvcrt.getwch()
            if value in ("\x00", "\xe0"):
                return "DOWN" if msvcrt.getwch() == "P" else "UP"
            return {"\r": "ENTER", "\x1b": "ESC", "\x08": "BACKSPACE", "\x03": "CTRL_C", "\x0e": "CTRL_N", "\x01": "CTRL_A"}.get(value, value)
        import select
        import termios
        import tty

        fd = stream.fileno()
        previous = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            value = stream.read(1)
            if value == "\x1b" and select.select([stream], [], [], 0.04)[0]:
                second = stream.read(1)
                if second == "[" and select.select([stream], [], [], 0.04)[0]:
                    return {"A": "UP", "B": "DOWN"}.get(stream.read(1), "ESC")
                return "ESC"
            return {"\r": "ENTER", "\n": "ENTER", "\x7f": "BACKSPACE", "\x08": "BACKSPACE", "\x03": "CTRL_C", "\x0e": "CTRL_N", "\x01": "CTRL_A"}.get(value, value)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)
    value = stream.read(1)
    if value == "\x1b":
        second = stream.read(1)
        if second == "[":
            third = stream.read(1)
            return {"A": "UP", "B": "DOWN"}.get(third, "ESC")
        return "ESC"
    return {"\n": "ENTER", "\r": "ENTER", "\x7f": "BACKSPACE", "\x08": "BACKSPACE", "\x03": "CTRL_C", "\x0e": "CTRL_N", "\x01": "CTRL_A"}.get(value, value)


def select_item(
    items: list[dict[str, Any]],
    *,
    title: str,
    render_line,
    header: str | Callable[[], str] = "",
    input_stream: TextIO,
    output_stream: TextIO,
    allow_new: bool = False,
    allow_open_all: bool = False,
    filter_key: str = "name",
    color_mode: str = "auto",
) -> tuple[str, dict[str, Any] | None]:
    """Read arrow keys, enter, incremental text filtering, and explicit Ctrl shortcuts."""
    query = ""
    selected = 0
    while True:
        matches = filter_items(items, query, key=filter_key)
        selected = min(selected, max(0, len(matches) - 1))
        output_stream.write("\x1b[2J\x1b[H")
        enabled = color_enabled(color_mode, is_tty=output_stream.isatty())
        output_stream.write(f"{semantic_color(title, 'gui', enabled=enabled)}\n\nSearch: {query}\n\n")
        header_text = header() if callable(header) else header
        if header_text:
            output_stream.write(header_text + "\n")
        for index, item in enumerate(matches):
            marker = semantic_color(">", "success", enabled=enabled) if index == selected else " "
            output_stream.write(marker + " " + render_line(item) + "\n")
        if not matches:
            output_stream.write("  No matching items.\n")
        shortcuts = ["↑/↓ Navigate", "Enter Select", "Esc Back", "Typing Filter", "Backspace Edit", "Ctrl+C Exit"]
        if allow_new:
            shortcuts.append("Ctrl+N New")
        if allow_open_all:
            shortcuts.append("Ctrl+A Open All")
        output_stream.write("\n" + "   ".join(shortcuts) + "\n")
        output_stream.flush()
        key = _read_key(input_stream)
        if key == "CTRL_C":
            return "exit", None
        if key == "ESC":
            return "back", None
        if key == "CTRL_N" and allow_new:
            return "new", None
        if key == "CTRL_A" and allow_open_all:
            return "open_all", None
        if key == "UP" and matches:
            selected = (selected - 1) % len(matches)
        elif key == "DOWN" and matches:
            selected = (selected + 1) % len(matches)
        elif key == "ENTER":
            if matches:
                return "selected", matches[selected]
        elif key == "BACKSPACE":
            query = query[:-1]
            selected = 0
        elif len(key) == 1 and key.isprintable():
            query += key
            selected = 0


def _ask(output_stream: TextIO, input_stream: TextIO, prompt: str) -> str:
    output_stream.write(prompt)
    output_stream.flush()
    if input_stream is sys.stdin and input_stream.isatty():
        try:
            return input()
        except EOFError:
            return ""
    return input_stream.readline().strip()


def _confirm(output_stream: TextIO, input_stream: TextIO, summary: str) -> bool:
    return _ask(output_stream, input_stream, f"\n{summary}\nApply? [y/N] ").strip().casefold() in {"y", "yes"}


def _provider_choice(input_stream: TextIO, output_stream: TextIO) -> str | None:
    action, item = select_item(
        [{"name": "AGY", "provider": "agy"}, {"name": "Codex", "provider": "codex"}],
        title="Choose Provider", render_line=lambda row: row["name"],
        input_stream=input_stream, output_stream=output_stream,
    )
    return item["provider"] if action == "selected" and item else None


def run_interactive(dispatcher: DispatcherService, *, input_stream: TextIO, output_stream: TextIO) -> int:
    """Run the four-step menu using the same durable service operations as CLI commands."""
    from argparse import Namespace

    from .dispatcher_cli import _json_default, _open, _run_pane

    def terminal_width() -> int:
        return shutil.get_terminal_size((100, 24)).columns

    selector_color = color_enabled("auto", is_tty=output_stream.isatty())

    while True:
        action, gui = select_item(
            dispatcher.list_guis(), title="LLM Dispatcher — Select GUI Conversation",
            render_line=lambda row: _gui_selector_line(row, terminal_width(), enabled=selector_color),
            header=lambda: _gui_selector_line({}, terminal_width(), header=True, enabled=selector_color),
            input_stream=input_stream, output_stream=output_stream, allow_new=True,
            filter_key="alias",
        )
        if action == "exit":
            return 0
        if action == "back":
            continue
        if action == "new":
            alias = _ask(output_stream, input_stream, "New local GUI conversation alias: ")
            if alias and _confirm(output_stream, input_stream, f"Register local alias {alias!r}?"):
                dispatcher.create_gui(alias, apply=True)
            continue
        if gui is None:
            continue
        gui_name = gui["alias"]
        while True:
            action, slot = select_item(
                dispatcher.list_slots(gui=gui_name), title=f"GUI: {gui_name}",
                render_line=lambda row: _agent_selector_line(row, terminal_width(), enabled=selector_color),
                header=lambda: _agent_selector_line({}, terminal_width(), header=True, enabled=selector_color),
                input_stream=input_stream, output_stream=output_stream,
                allow_new=True, allow_open_all=True,
            )
            if action == "exit":
                return 0
            if action == "back":
                break
            if action == "new":
                name = _ask(output_stream, input_stream, "New local agent name: ")
                if name and _confirm(output_stream, input_stream, f"Create agent slot {name!r} under {gui_name!r}?"):
                    dispatcher.create_slot(gui=gui_name, name=name, apply=True)
                continue
            if action == "open_all":
                namespace = Namespace(terminal="windows-terminal", panes_per_tab=2, window=None, gui=gui_name, apply=False)
                preview = _open(dispatcher, namespace)
                import json

                output_stream.write(f"\nOpen All preview:\n{json.dumps(preview, indent=2, ensure_ascii=False, default=_json_default)}\n")
                if preview.get("terminal_launcher_available") is False:
                    output_stream.write("terminal_launcher is not installed or integrated; request was not launched.\n")
                elif _confirm(output_stream, input_stream, "Launch the active selected sessions?"):
                    namespace.apply = True
                    result = _open(dispatcher, namespace)
                    launch = result.get("launch")
                    status = getattr(getattr(launch, "status", None), "value", None)
                    if status == "failed":
                        output_stream.write(f"Open All launch failed: {launch.diagnostic or 'unknown terminal error'}\n")
                    elif status == "submitted":
                        output_stream.write("Launch request submitted; pane process state is unknown.\n")
                continue
            if action != "selected" or slot is None:
                continue
            while True:
                current = dispatcher.get_slot(gui=gui_name, name=slot["name"])
                options = []
                if current["current"]:
                    options.append({"name": "Continue current session", "action": "continue"})
                options.extend([
                    {"name": "Start new native conversation", "action": "new"},
                    {"name": "Switch provider — new conversation", "action": "switch"},
                    {"name": "Switch provider — reuse previous conversation", "action": "reuse"},
                    {"name": "View activation history", "action": "history"},
                    {"name": "Mark inactive / completed", "action": "state"},
                    {"name": "Back", "action": "back"},
                ])
                if current["current"]:
                    output_stream.write(
                        f"\n{semantic_color('GUI:', 'label', enabled=selector_color)} {semantic_color(gui_name, 'gui', enabled=selector_color)}\n"
                        f"{semantic_color('Agent:', 'label', enabled=selector_color)} {semantic_color(slot['name'], 'agent', enabled=selector_color)}\n"
                        f"{semantic_color('Current:', 'label', enabled=selector_color)} "
                        f"{provider_semantic(current['current']['provider'], enabled=selector_color)} "
                        f"{semantic_color(current['current']['native_session_id'], 'session', enabled=selector_color)}\n"
                    )
                action, choice = select_item(
                    options, title="Choose Session Action", render_line=lambda row: row["name"],
                    input_stream=input_stream, output_stream=output_stream,
                )
                if action == "exit":
                    return 0
                if action == "back" or not choice or choice["action"] == "back":
                    break
                if choice["action"] == "history":
                    for index, row in enumerate(current["history"], 1):
                        output_stream.write(f"{index}. {provider_semantic(row['provider'], enabled=selector_color)} "
                                            f"{semantic_color(row['native_session_id'], 'session', enabled=selector_color)} "
                                            f"[{row['environment_id']}] — {row['provenance']}\n")
                    _ask(output_stream, input_stream, "Press Enter to return.")
                    continue
                if choice["action"] == "state":
                    state_name = _ask(output_stream, input_stream, "Type inactive or completed (blank cancels): ").strip().lower()
                    if state_name in {"inactive", "completed"} and _confirm(output_stream, input_stream, f"Mark {slot['name']} {state_name}?"):
                        dispatcher.set_slot_state(gui=gui_name, name=slot["name"], state=state_name, apply=True)
                    break
                provider = current["current"]["provider"] if choice["action"] == "continue" else _provider_choice(input_stream, output_stream)
                if provider is None:
                    continue
                if choice["action"] == "reuse":
                    previous_sessions = dispatcher.sessions_for_provider(gui=gui_name, name=slot["name"], provider=provider)
                    if not previous_sessions:
                        output_stream.write(f"No previous {provider} session exists for this agent.\n")
                        continue
                    session_action, previous = select_item(
                        previous_sessions,
                        title=f"Reuse previous {provider.upper()} session",
                        render_line=lambda row: (
                            f"{provider_semantic(row['provider'], enabled=selector_color)}  "
                            f"{semantic_color(row['native_session_id'], 'session', enabled=selector_color)}  "
                            f"[{row['environment_id']}]  {format_timestamp(row['activated_at'])}"
                        ),
                        input_stream=input_stream,
                        output_stream=output_stream,
                    )
                    if session_action == "exit":
                        return 0
                    if session_action != "selected" or previous is None:
                        continue
                    if not _confirm(output_stream, input_stream, f"Select {provider} session {previous['native_session_id']}?"):
                        continue
                    dispatcher.attach_session(gui=gui_name, name=slot["name"], provider=provider,
                                              session_id=previous["native_session_id"],
                                              environment_selector=previous["environment_id"],
                                              apply=True, provenance="dispatcher_reuse")
                    _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                              input_stream=input_stream, output_stream=output_stream)
                    continue
                if choice["action"] in {"new", "switch"}:
                    preview = dispatcher.begin_launch(gui=gui_name, name=slot["name"], provider=provider, apply=False)
                    if not _confirm(output_stream, input_stream, preview["summary"]):
                        continue
                    pending = dispatcher.begin_launch(gui=gui_name, name=slot["name"], provider=provider, apply=True)
                    _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=pending["details"]["launch_id"],
                              input_stream=input_stream, output_stream=output_stream)
                    continue
                if choice["action"] == "continue":
                    if _confirm(output_stream, input_stream, f"Resume {provider} session {current['current']['native_session_id']}?"):
                        _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                                  input_stream=input_stream, output_stream=output_stream)
                    continue
