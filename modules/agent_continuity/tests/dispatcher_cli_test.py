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
from uuid import UUID, uuid4

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
    output = TTYOutput()
    service = DispatcherService(ContinuityService(tmp_path))
    before_guis = service.list_guis()
    before_events = service._rows("SELECT event_id, event_type FROM activity_events ORDER BY sequence")
    result = dispatch(parser.parse_args(["-H", str(tmp_path)]), parser, input_stream=TTYInput("\x03"), output_stream=output)

    assert result == 0
    assert "Select GUI Conversation" in output.getvalue()
    assert service.list_guis() == before_guis == []
    assert service._rows("SELECT event_id, event_type FROM activity_events ORDER BY sequence") == before_events == []


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


def test_public_help_hides_internal_pane_run_but_parser_keeps_it_callable():
    parser = build_parser()
    help_text = parser.format_help()
    assert "pane-run" not in help_text
    assert "Primary: start, continue, switch, review, return, list, open, history." in help_text
    assert "Recovery and diagnostics" in help_text
    args = parser.parse_args(["pane-run", "-s", "slot-example"])
    assert args.command == "pane-run"
    assert args.slot_id == "slot-example"
    assert "--history-count" in parser._subparsers._group_actions[0].choices["list"].format_help()
    assert "--new" in parser._subparsers._group_actions[0].choices["start"].format_help()


def test_action_default_flags_resolve_and_reject_contradictions_before_registry_io(tmp_path):
    parser = build_parser()
    args = parser.parse_args(["-H", str(tmp_path), "gui", "add", "-n", "G"])
    assert args.apply is False
    output = StringIO()
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=output) == 0
    assert DispatcherService(home_dir=tmp_path).list_guis()[0]["alias"] == "G"
    args = parser.parse_args(["-H", str(tmp_path), "slot", "create", "-g", "G", "-n", "A"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert DispatcherService(home_dir=tmp_path).get_slot(gui="G", name="A")["name"] == "A"

    second = tmp_path / "second"
    args = parser.parse_args(["-H", str(second), "gui", "add", "-n", "G", "-d"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert DispatcherService(home_dir=second).list_guis() == []

    third = tmp_path / "third"
    args = parser.parse_args(["-H", str(third), "gui", "add", "-n", "G", "-a", "-d"])
    with pytest.raises(Exception, match="Choose either --dry-run or --apply"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
    assert not third.exists()


def test_continue_executes_by_default_and_dry_run_is_pure(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "A", provider="codex", session_id="native")
    calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: calls.append("run") or 0)
    parser = build_parser()
    assert dispatch(parser.parse_args(["-H", str(home), "continue", "-g", "G", "-n", "A"]), parser,
                    input_stream=StringIO(), output_stream=StringIO()) == 0
    assert calls == ["run"]
    calls.clear()
    assert dispatch(parser.parse_args(["-H", str(home), "continue", "-g", "G", "-n", "A", "-d"]), parser,
                    input_stream=StringIO(), output_stream=StringIO()) == 0
    assert calls == []


def test_default_launch_emits_early_redacted_progress_to_stderr_only(tmp_path, monkeypatch, capsys):
    import time

    home = tmp_path / "registry"
    DispatcherService(home_dir=home).register("G", "A", provider="codex", session_id="native")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)
    parser = build_parser()
    started = time.monotonic()
    assert dispatch(parser.parse_args(["-H", str(home), "continue", "-g", "G", "-n", "A"]), parser,
                    input_stream=StringIO(), output_stream=StringIO()) == 0
    elapsed = time.monotonic() - started
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("LLMD startup +")
    assert "registry synchronization" in captured.err
    assert "password" not in captured.err.casefold()
    assert elapsed < 1.0


def test_blocking_provider_progress_is_periodic_and_does_not_echo_argv(monkeypatch, capsys):
    import subprocess
    import time

    from agent_continuity import dispatcher_cli

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (time.sleep(0.035) or subprocess.CompletedProcess(a[0], 0)))
    enabled = dispatcher_cli._STARTUP_PROGRESS.set(True)
    started = dispatcher_cli._STARTUP_STARTED.set(time.monotonic())
    try:
        result = dispatcher_cli._run_provider_with_progress(
            ["codex", "--token", "private-value"], label="fake bootstrap", progress_interval=0.005
        )
    finally:
        dispatcher_cli._STARTUP_STARTED.reset(started)
        dispatcher_cli._STARTUP_PROGRESS.reset(enabled)
    assert result.returncode == 0
    captured = capsys.readouterr()
    assert "fake bootstrap still running" in captured.err
    assert "private-value" not in captured.err


def test_new_conversation_dry_run_never_bootstraps(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    parser = build_parser()
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: pytest.fail("bootstrap must not run"))
    args = parser.parse_args(["-H", str(home), "start", "G", "A", "-p", "codex", "-N", "-d"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert DispatcherService(home_dir=home).list_guis() == []


def test_new_provider_switch_keeps_explicit_authorization_while_reuse_executes_by_default(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "A", provider="codex", session_id="codex-id")
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "switch", "-g", "G", "-n", "A", "-p", "agy", "-d"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert service.get_slot(gui="G", name="A")["history"][-1]["native_session_id"] == "codex-id"
    assert service.list_pending_launches(gui="G") == []

    calls = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: calls.append(k) or 0)
    args = parser.parse_args(["-H", str(home), "switch", "-g", "G", "-n", "A", "-p", "codex", "-r"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    assert calls


def test_provider_switch_executes_by_default_and_preserves_prior_association(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "A", provider="codex", session_id="codex-original")
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)
    parser = build_parser()

    args = parser.parse_args(["-H", str(home), "switch", "-g", "G", "-n", "A", "-p", "agy"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    slot = service.get_slot(gui="G", name="A")
    pending = service.list_pending_launches(gui="G")
    assert [row["native_session_id"] for row in slot["history"]] == ["codex-original"]
    assert len(pending) == 1 and pending[0]["provider"] == "agy"
    assert launches == [pending[0]["launch_id"]]


def test_first_reviewer_session_initializes_by_default(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "Implementer", provider="codex", session_id="implementation")
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)
    parser = build_parser()

    args = parser.parse_args([
        "-H", str(home), "review", "-g", "G", "-n", "Implementer", "-R", "Review",
        "-p", "agy",
    ])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    original = service.get_slot(gui="G", name="Implementer")
    reviewer = service.get_slot(gui="G", name="Review")
    pending = service.list_pending_launches(gui="G")
    assert original["state"] == "active" and original["current"]["native_session_id"] == "implementation"
    assert reviewer["current"] is None and reviewer["state"] == "active"
    assert len(pending) == 1 and launches == [pending[0]["launch_id"]]
    assert service.open_review_cycle(slot_id=original["slot_id"])["status"] == "pending"


def test_review_new_flag_replaces_selected_reviewer_without_apply(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("G", "Implementer", provider="codex", session_id="implementation")
    service.register("G", "Review", provider="agy", session_id="review-original")
    launches = []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)
    parser = build_parser()

    args = parser.parse_args([
        "-H", str(home), "review", "-g", "G", "-n", "Implementer", "-R", "Review",
        "-p", "agy", "-N",
    ])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    reviewer = service.get_slot(gui="G", name="Review")
    pending = service.list_pending_launches(gui="G")
    assert [row["native_session_id"] for row in reviewer["history"]] == ["review-original"]
    assert len(pending) == 1 and pending[0]["provider"] == "agy"
    assert launches == [pending[0]["launch_id"]]


def test_start_first_session_concurrency_reserves_only_one_pending_launch(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from agent_continuity.errors import ContinuityError

    home = tmp_path / "registry"
    parser = build_parser()
    barrier = Barrier(2)
    launches = []

    def synchronized_preview(*args, **kwargs):
        barrier.wait(timeout=3)
        return {"environment": {"id": "local"}}

    monkeypatch.setattr("agent_continuity.dispatcher_cli._new_launch_preview", synchronized_preview)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda dispatcher, **kwargs: launches.append(kwargs["launch_id"]) or 0)

    def start_once():
        args = parser.parse_args(["-H", str(home), "start", "G", "A", "-p", "codex"])
        try:
            return dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
        except ContinuityError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: start_once(), range(2)))

    pending = DispatcherService(home_dir=home).list_pending_launches(gui="G")
    assert results.count(0) == 1 and results.count("rejected") == 1
    assert len(pending) == 1 and launches == [pending[0]["launch_id"]]


def test_last_resume_aliases_are_compatible_and_read_only_by_default():
    parser = build_parser()
    default = parser.parse_args(["last"])
    dry = parser.parse_args(["last", "-a"])
    resume = parser.parse_args(["last", "-r"])
    from agent_continuity.dispatcher_cli import _resolve_execution_mode
    _resolve_execution_mode(default)
    _resolve_execution_mode(dry)
    _resolve_execution_mode(resume)
    assert default.apply is False
    assert dry.apply is resume.apply is True


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
    pane_argv = result["request"]["panes"][0]["argv"]
    assert pane_argv[:4] == ["llmd", "pane-run", "--slot-id", dispatcher.list_slots(gui="AgentImprovement")[0]["slot_id"]]
    assert pane_argv[4] == "-T"
    assert UUID(pane_argv[5])
    assert result["request"]["panes"][0]["provider_argv"] == ["agy", "--conversation", "a-1"]


def test_open_assigns_distinct_launcher_contexts_without_reusing_profile_terminal_id(tmp_path, monkeypatch):
    dispatcher = DispatcherService(ContinuityService(tmp_path / "registry"))
    dispatcher.create_gui("GUI", apply=True)
    for name, session in (("One", "session-one"), ("Two", "session-two")):
        dispatcher.create_slot(gui="GUI", name=name, apply=True)
        dispatcher.attach_session(gui="GUI", name=name, provider="codex", session_id=session, apply=True)
    parent_terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", parent_terminal_id)

    @dataclass(frozen=True)
    class PaneSpec:
        title: str
        argv: tuple[str, ...]
        cwd: str | None = None

    class Backend:
        def preview(self, plan):
            return {"tab_count": len(plan["tabs"])}

        def launch(self, plan):
            return {"launched": True}

    def group_panes(panes, *, panes_per_tab, target_window):
        return {"tabs": [{"title": pane.title, "panes": [pane]} for pane in panes]}

    monkeypatch.setitem(sys.modules, "terminal_launcher", types.SimpleNamespace(
        PaneSpec=PaneSpec, WindowsTerminalBackend=Backend, group_panes=group_panes
    ))
    result = _open(dispatcher, Namespace(gui="GUI", terminal="windows-terminal", panes_per_tab=2,
                                         window=None, apply=True))

    pane_argv = [pane["argv"] for pane in result["request"]["panes"]]
    context_ids = [argv[argv.index("-T") + 1] for argv in pane_argv]
    assert len(context_ids) == 2
    assert len(set(context_ids)) == 2
    assert parent_terminal_id not in context_ids
    assert all(UUID(context_id) for context_id in context_ids)


def test_pane_run_accepts_launcher_owned_terminal_context():
    context_id = str(uuid4())
    args = build_parser().parse_args(["pane-run", "-s", "slot-example", "-T", context_id])

    assert args.launcher_terminal_context == context_id


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
