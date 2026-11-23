from __future__ import annotations

import builtins
import sys
import tomllib
import types
from argparse import Namespace
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import _open, build_parser, dispatch
from agent_continuity.interactive import filter_items, format_timestamp, select_item
from agent_continuity.service import ContinuityService


class TTYInput(StringIO):
    def isatty(self):
        return True


class TTYOutput(StringIO):
    def isatty(self):
        return True


def test_noninteractive_no_argument_call_shows_help_without_registry_mutation(tmp_path):
    parser = build_parser()
    output = StringIO()
    result = dispatch(parser.parse_args([]), parser, input_stream=StringIO(), output_stream=output)

    assert result == 2
    assert "usage: llmd" in output.getvalue()
    assert not (tmp_path / "index.sqlite").exists()


def test_no_argument_interactive_entry_can_exit_without_mutation(tmp_path):
    parser = build_parser()
    output = StringIO()
    output = TTYOutput()
    result = dispatch(parser.parse_args(["-H", str(tmp_path)]), parser, input_stream=TTYInput("\x03"), output_stream=output)

    assert result == 0
    assert "Select GUI Conversation" in output.getvalue()


def test_selector_filters_case_insensitively_and_keeps_item_order():
    items = [
        {"name": "AgentNew", "activity": "2026-11-19T10:00:00Z"},
        {"name": "AgentOld", "activity": "2026-11-18T10:00:00Z"},
        {"name": "Other", "activity": None},
    ]
    assert [item["name"] for item in filter_items(items, "agent")] == ["AgentNew", "AgentOld"]
    actions = TTYInput("a\r")
    output = StringIO()
    action, selected = select_item(items, title="test", render_line=lambda item: item["name"],
                                   input_stream=actions, output_stream=output)
    assert action == "selected"
    assert selected["name"] == "AgentNew"


def test_timestamp_format_is_consistent_and_unknown_is_not_invented():
    assert format_timestamp(None) == "—"
    assert format_timestamp("bad timestamp") == "—"
    formatted = format_timestamp(datetime(2026, 11, 19, 19, 18, tzinfo=UTC).isoformat())
    assert len(formatted) == 16
    assert formatted[4] == "-" and formatted[10] == " "


def test_console_entry_points_are_aliases_and_flags_work_after_subcommand():
    module_dir = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((module_dir / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = metadata["project"]["scripts"]
    assert scripts["llmd"] == scripts["llm-dispatcher"] == "agent_continuity.dispatcher_cli:main"
    args = build_parser().parse_args(["open", "-g", "AgentImprovement", "-k", "4", "-t", "windows-terminal", "-w", "2", "-j"])
    assert args.json_output is True
    assert args.panes_per_tab == 4
    assert args.window == "2"


def test_open_creates_pane_specs_and_delegates_layout_and_launch(tmp_path, monkeypatch):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider="agy", session_id="a-1", apply=True)

    @dataclass(frozen=True)
    class PaneSpec:
        title: str
        argv: tuple[str, ...]
        cwd: str | None = None

    class Backend:
        def preview(self, plan):
            return {"tab_count": len(plan["tabs"]), "titles": [tab["title"] for tab in plan["tabs"]]}

        def launch(self, plan):
            return {"launched": True}

    def group_panes(panes, *, panes_per_tab, target_window):
        return {"tabs": [{"title": pane.title, "panes": [pane]} for pane in panes],
                "panes_per_tab": panes_per_tab, "target_window": target_window}

    monkeypatch.setitem(sys.modules, "terminal_launcher", types.SimpleNamespace(
        PaneSpec=PaneSpec, WindowsTerminalBackend=Backend, group_panes=group_panes
    ))
    result = _open(dispatcher, Namespace(gui="AgentImprovement", terminal="windows-terminal",
                                         panes_per_tab=2, window="window-2", apply=True))

    assert result["preview"]["tab_count"] == 1
    assert result["preview"]["titles"] == ["AgentPerf"]
    assert result["launch"] == {"launched": True}
    assert result["request"]["panes"][0]["argv"] == ["llmd", "pane-run", "--slot-id", dispatcher.list_slots(gui="AgentImprovement")[0]["slot_id"]]
    assert result["request"]["panes"][0]["provider_argv"] == ["agy", "--conversation", "a-1"]


def test_open_without_terminal_library_returns_pending_integration_preview(tmp_path, monkeypatch):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("Empty", apply=True)
    import_fn = builtins.__import__

    def import_without_terminal(name, *args, **kwargs):
        if name == "terminal_launcher":
            raise ModuleNotFoundError("No module named 'terminal_launcher'", name="terminal_launcher")
        return import_fn(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_terminal)
    result = _open(dispatcher, Namespace(gui="Empty", terminal="windows-terminal", panes_per_tab=2, window=None, apply=False))
    assert result["terminal_launcher_available"] is False
    assert result["request"]["panes"] == []


def test_open_does_not_hide_internal_terminal_library_import_errors(tmp_path, monkeypatch):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("Empty", apply=True)
    import_fn = builtins.__import__

    def import_with_broken_terminal_submodule(name, *args, **kwargs):
        if name == "terminal_launcher":
            raise ModuleNotFoundError("missing terminal_launcher.backend", name="terminal_launcher.backend")
        return import_fn(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_with_broken_terminal_submodule)
    with pytest.raises(ModuleNotFoundError, match="terminal_launcher.backend"):
        _open(dispatcher, Namespace(gui="Empty", terminal="windows-terminal", panes_per_tab=2, window=None, apply=False))
