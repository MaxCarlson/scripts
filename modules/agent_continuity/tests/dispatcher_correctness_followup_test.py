from __future__ import annotations

import json
from io import StringIO

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import build_parser, dispatch
from agent_continuity.errors import ContinuityError
from agent_continuity.models import EnvironmentInfo, EventEnvelope, EventType


class TTYInput(StringIO):
    def isatty(self):
        return True


class TTYOutput(StringIO):
    def isatty(self):
        return True


def _register_environment(dispatcher: DispatcherService, environment: EnvironmentInfo) -> None:
    event = EventEnvelope(
        event_id=f"evt-{environment.environment_id}", event_schema_version=1,
        event_type=EventType.ENVIRONMENT_REGISTERED.value, provider=None, environment_id=environment.environment_id,
        native_session_id=None, source_timestamp=environment.created_at,
        observed_timestamp=environment.created_at, source_adapter_version="test",
        payload=environment.to_dict(),
    )
    dispatcher.continuity._emit_and_materialize([event])


@pytest.mark.parametrize("runtime_kind,distro,selector", [
    ("windows", None, "win-test"),
    ("wsl", "Ubuntu", "wsl-test"),
])
@pytest.mark.parametrize("command", ["start", "switch"])
@pytest.mark.parametrize("explicit_environment", [False, True])
def test_new_launch_preview_and_pending_launch_share_resolved_environment(
    tmp_path, monkeypatch, runtime_kind, distro, selector, command, explicit_environment,
):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    environment = EnvironmentInfo(
        environment_id=selector, runtime_kind=runtime_kind, distro=distro, hostname="test",
        label=selector, created_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T00:00:00Z",
    )
    _register_environment(service, environment)
    service.create_gui("GUI", apply=True)
    service.create_slot(gui="GUI", name="Agent", apply=True)
    service.attach_session(gui="GUI", name="Agent", provider="codex", session_id="codex-current",
                           environment_selector=selector, apply=True)

    previews = []
    actual_preview = __import__("agent_continuity.dispatcher_cli", fromlist=["_new_launch_preview"])._new_launch_preview
    monkeypatch.setattr(
        "agent_continuity.dispatcher_cli._new_launch_preview",
        lambda *args, **kwargs: previews.append(actual_preview(*args, **kwargs)) or previews[-1],
    )
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *args, **kwargs: 0)
    argv = ["-H", str(home), command]
    if command == "start":
        argv.extend(["GUI", "Agent", "-p", "agy", "-N", "-a"])
    else:
        argv.extend(["-g", "GUI", "-n", "Agent", "-p", "agy", "-a"])
    if explicit_environment:
        argv.extend(["-e", selector])
    parser = build_parser()
    args = parser.parse_args(argv)
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0

    pending = service.list_pending_launches(gui="GUI")
    assert len(pending) == 1
    assert previews[0]["environment"]["id"] == selector
    assert pending[0]["environment_id"] == previews[0]["environment"]["id"]


@pytest.mark.parametrize("command", ["start", "switch"])
@pytest.mark.parametrize("explicit_environment", [False, True])
def test_new_launch_dry_run_json_reports_resolved_environment(tmp_path, command, explicit_environment):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    environment = EnvironmentInfo(
        environment_id="wsl-test", runtime_kind="wsl", distro="Ubuntu", hostname="test",
        label="Ubuntu", created_at="2026-01-01T00:00:00Z", last_seen_at="2026-01-01T00:00:00Z",
    )
    _register_environment(service, environment)
    service.create_gui("GUI", apply=True)
    service.create_slot(gui="GUI", name="Agent", apply=True)
    service.attach_session(gui="GUI", name="Agent", provider="codex", session_id="codex-current",
                           environment_selector=environment.environment_id, apply=True)
    argv = ["-H", str(home), command]
    if command == "start":
        argv.extend(["GUI", "Agent", "-p", "agy", "-N", "-j"])
    else:
        argv.extend(["-g", "GUI", "-n", "Agent", "-p", "agy", "-j"])
    if explicit_environment:
        argv.extend(["-e", environment.environment_id])
    parser = build_parser()
    args = parser.parse_args(argv)
    output = StringIO()
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=output) == 0
    result = json.loads(output.getvalue())
    assert result["launch_preview"]["environment"]["id"] == environment.environment_id
    assert service.list_pending_launches(gui="GUI") == []


def test_start_existing_session_json_is_one_document(tmp_path):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("GUI", "Agent", provider="codex", session_id="exact")
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "GUI", "Agent", "-p", "codex", "-j"])
    output = StringIO()
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=output) == 0
    result = json.loads(output.getvalue())
    assert result["action"] == "start"
    assert result["launch_preview"]["selected_session"]["native_session_id"] == "exact"
    assert service.get_slot(gui="GUI", name="Agent")["history"][-1]["native_session_id"] == "exact"


def test_start_existing_session_text_preview_keeps_human_output(tmp_path):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("GUI", "Agent", provider="codex", session_id="exact")
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "start", "GUI", "Agent", "-p", "codex"])
    output = StringIO()
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=output) == 0
    assert output.getvalue().startswith("Launch preview")
    assert '"native_session_id": "exact"' in output.getvalue()


@pytest.mark.parametrize("choice", ["y", ""])
def test_exit_option_four_uses_destination_environment_cwd_and_defaults_for_incompatible_options(
    tmp_path, monkeypatch, choice,
):
    from agent_continuity.dispatcher_cli import _switch_after_exit

    home = tmp_path / "registry"
    source_cwd = tmp_path / "source tree"
    destination_cwd = tmp_path / "destination tree"
    source_cwd.mkdir()
    destination_cwd.mkdir()
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="codex", session_id="codex-current",
                              cwd=str(source_cwd), apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="agy", session_id="agy-prior",
                              cwd=str(destination_cwd), apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="codex", session_id="codex-current",
                              cwd=str(source_cwd), apply=True)
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    previews, launches = [], []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._launch_preview",
                        lambda *args, **kwargs: previews.append((args, kwargs)) or {})
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda _dispatcher, **kwargs: launches.append(kwargs) or 0)

    result = _switch_after_exit(
        dispatcher, slot, "agy", input_stream=StringIO(f"r\n{choice}\n"), output_stream=StringIO(),
        native_args=["--ask-for-approval", "never"], cwd_override=str(source_cwd),
    )

    if choice == "":
        assert result is None
        assert dispatcher.get_slot(gui="GUI", name="Agent")["current"]["native_session_id"] == "codex-current"
        assert launches == []
        return
    assert result == 0
    assert previews[0][0][1:3] == ("agy", "agy-prior")
    assert previews[0][0][4] == str(destination_cwd)
    assert previews[0][0][5] == []
    assert launches[0]["native_args"] == []
    assert launches[0]["cwd_override"] is None
    assert dispatcher.get_slot(gui="GUI", name="Agent")["current"]["environment_id"] == slot["current"]["environment_id"]


def test_exit_option_five_uses_selected_same_provider_worktree_unless_overrides_are_authorized(
    tmp_path, monkeypatch,
):
    from agent_continuity.dispatcher_cli import _switch_to_existing_agent

    source_cwd, destination_cwd = tmp_path / "source", tmp_path / "destination"
    source_cwd.mkdir()
    destination_cwd.mkdir()
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Source", apply=True)
    dispatcher.create_slot(gui="GUI", name="Target", apply=True)
    dispatcher.attach_session(gui="GUI", name="Source", provider="codex", session_id="source",
                              cwd=str(source_cwd), apply=True)
    dispatcher.attach_session(gui="GUI", name="Target", provider="codex", session_id="target",
                              cwd=str(destination_cwd), apply=True)
    dispatcher.set_slot_state(gui="GUI", name="Target", state="inactive", apply=True)
    source = dispatcher.get_slot(gui="GUI", name="Source")
    monkeypatch.setattr("agent_continuity.interactive.select_item", lambda items, **kwargs: ("selected", items[0]))
    previews, launches = [], []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._launch_preview",
                        lambda *args, **kwargs: previews.append((args, kwargs)) or {})
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda _dispatcher, **kwargs: launches.append(kwargs) or 0)

    result = _switch_to_existing_agent(
        dispatcher, source, input_stream=TTYInput("d\n"), output_stream=TTYOutput(),
        native_args=["--sandbox", "workspace-write"], cwd_override=str(source_cwd),
    )

    assert result == 0
    assert previews[0][0][4] == str(destination_cwd)
    assert previews[0][0][5] == []
    assert launches[0]["native_args"] == []
    assert launches[0]["cwd_override"] is None
    assert dispatcher.get_slot(gui="GUI", name="Target")["state"] == "active"


def test_exit_option_four_rejects_authorized_invalid_destination_cwd_before_mutation(tmp_path, monkeypatch):
    from agent_continuity.dispatcher_cli import _switch_after_exit

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Agent", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="codex", session_id="current", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="agy", session_id="prior", apply=True)
    dispatcher.attach_session(gui="GUI", name="Agent", provider="codex", session_id="current", apply=True)
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    monkeypatch.setattr("agent_continuity.dispatcher_cli._launch_preview", lambda *a, **k: {})
    with pytest.raises(ContinuityError, match="does not exist"):
        _switch_after_exit(dispatcher, slot, "codex", input_stream=StringIO("r\no\n"),
                           output_stream=StringIO(), native_args=["--model", "model"],
                           cwd_override=str(tmp_path / "missing"))
    assert dispatcher.get_slot(gui="GUI", name="Agent")["current"]["native_session_id"] == "current"


@pytest.mark.parametrize(
    "provider,choice,expected_args",
    [
        ("agy", "y", []),
        ("codex", "o", ["--sandbox", "workspace-write"]),
    ],
)
def test_exit_option_six_never_inherits_provider_options_without_authorization(
    tmp_path, monkeypatch, provider, choice, expected_args,
):
    from agent_continuity.dispatcher_cli import _create_agent_after_exit

    cwd = tmp_path / "new agent worktree"
    cwd.mkdir()
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI", "Source", provider="codex", session_id="source-exact")
    source = dispatcher.get_slot(gui="GUI", name="Source")
    previews, launches = [], []
    monkeypatch.setattr("agent_continuity.dispatcher_cli._new_launch_preview",
                        lambda *args, **kwargs: previews.append((args, kwargs)) or {})
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane",
                        lambda _dispatcher, **kwargs: launches.append(kwargs) or 0)
    provider_choice = "2" if provider == "agy" else "1"
    supplied = ["--ask-for-approval", "never"] if provider == "agy" else ["--sandbox", "workspace-write"]
    response = f"New\n{provider_choice}\n{cwd}\n{choice}\ny\n"
    output = TTYOutput()
    result = _create_agent_after_exit(
        dispatcher, source, input_stream=TTYInput(response), output_stream=output,
        native_args=supplied, cwd_override=str(tmp_path / "departing override"),
    )
    target = dispatcher.get_slot(gui="GUI", name="New")
    pending = dispatcher.list_pending_launches(gui="GUI")

    assert result == 0
    assert len(pending) == 1 and pending[0]["slot_id"] == target["slot_id"]
    assert pending[0]["cwd"] == str(cwd)
    assert previews[0][0][3] == str(cwd)
    assert launches[0]["native_args"] == expected_args
    assert "departing override" in output.getvalue()


def test_failed_historical_resume_keeps_exact_session_history_and_no_pending_launch(tmp_path, monkeypatch):
    import subprocess

    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("GUI", "Agent", provider="agy", session_id="historical")
    service.register("GUI", "Agent", provider="codex", session_id="current", select=True)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv",
                        lambda _dispatcher, provider, session_id, **kwargs: [provider, "resume", session_id])
    calls = []

    def failed_provider(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 23)

    monkeypatch.setattr("agent_continuity.dispatcher_cli.subprocess.run", failed_provider)
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "continue", "GUI", "Agent", "-p", "agy", "-a"])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 23
    after = service.get_slot(gui="GUI", name="Agent")
    assert after["current"]["provider"] == "agy"
    assert after["current"]["native_session_id"] == "historical"
    assert [row["native_session_id"] for row in after["history"]] == ["historical", "current", "historical"]
    assert service.list_pending_launches(gui="GUI") == []
    assert calls[0][0] == ["agy", "resume", "historical"]


def test_picker_invalid_cwd_is_rejected_before_inactive_reactivation(tmp_path, monkeypatch):
    from argparse import Namespace

    from agent_continuity.dispatcher_cli import _run_picker

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI", "Agent", provider="codex", session_id="exact")
    dispatcher.set_slot_state(gui="GUI", name="Agent", state="inactive", apply=True)
    before = dispatcher.get_slot(gui="GUI", name="Agent")
    item = {**before, "gui_alias": "GUI", "provider": "codex", "runtime_status": "NOT OBSERVED",
            "current_session_id": "exact", "search_text": "GUI Agent codex exact"}
    monkeypatch.setattr("agent_continuity.interactive.select_item", lambda *a, **k: ("selected", item))
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: pytest.fail("provider launch must not be reached"))
    with pytest.raises(ContinuityError, match="Working directory does not exist"):
        _run_picker(dispatcher, Namespace(gui=None, all=False, apply=True, cwd=str(tmp_path / "missing")),
                    TTYInput("y\n"), TTYOutput())
    after = dispatcher.get_slot(gui="GUI", name="Agent")
    assert after["state"] == "inactive"
    assert after["history"] == before["history"]


def test_picker_rejects_current_session_changed_while_picker_open(tmp_path, monkeypatch):
    from argparse import Namespace

    from agent_continuity.dispatcher_cli import _run_picker

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register("GUI", "Agent", provider="codex", session_id="old")
    snapshot = dispatcher.get_slot(gui="GUI", name="Agent")
    item = {**snapshot, "gui_alias": "GUI", "provider": "codex", "runtime_status": "NOT OBSERVED",
            "current_session_id": "old", "search_text": "GUI Agent codex old"}

    def concurrent_selection(_items, **kwargs):
        dispatcher.attach_session(gui="GUI", name="Agent", provider="agy", session_id="concurrent", apply=True)
        return "selected", item

    monkeypatch.setattr("agent_continuity.interactive.select_item", concurrent_selection)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: pytest.fail("stale session launched"))
    with pytest.raises(ContinuityError, match="changed while|selection changed"):
        _run_picker(dispatcher, Namespace(gui=None, all=False, apply=True, cwd=None), TTYInput(""), TTYOutput())
    assert dispatcher.get_slot(gui="GUI", name="Agent")["current"]["native_session_id"] == "concurrent"


def test_historical_continue_rejects_competing_activation_after_preview(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("GUI", "Agent", provider="agy", session_id="historical")
    service.register("GUI", "Agent", provider="codex", session_id="selected", select=True)

    def concurrent_activation(dispatcher, *args, **kwargs):
        service.attach_session(gui="GUI", name="Agent", provider="codex", session_id="competing",
                               apply=True, provenance="concurrent-test")
        return {}

    monkeypatch.setattr("agent_continuity.dispatcher_cli._launch_preview", concurrent_activation)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: pytest.fail("stale history launched"))
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "continue", "GUI", "Agent", "-p", "agy", "-a"])
    with pytest.raises(ContinuityError, match="selection changed"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
    assert service.get_slot(gui="GUI", name="Agent")["current"]["native_session_id"] == "competing"


@pytest.mark.parametrize("state,reactivate", [("inactive", False), ("completed", True)])
def test_switch_reuse_requires_reactivation_and_rejects_completed_slots(tmp_path, state, reactivate):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("GUI", "Agent", provider="agy", session_id="previous")
    service.register("GUI", "Agent", provider="codex", session_id="current", select=True)
    service.set_slot_state(gui="GUI", name="Agent", state=state, apply=True)
    before = service.get_slot(gui="GUI", name="Agent")
    parser = build_parser()
    argv = ["-H", str(home), "switch", "-g", "GUI", "-n", "Agent", "-p", "agy", "-r", "-a"]
    if reactivate:
        argv.append("-R")
    args = parser.parse_args(argv)
    with pytest.raises(ContinuityError, match="inactive.*reactivate|[Cc]ompleted"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
    after = service.get_slot(gui="GUI", name="Agent")
    assert after["state"] == before["state"]
    assert after["current"] == before["current"]
    assert after["history"] == before["history"]


def test_switch_reuse_rejects_stale_current_session_after_preview(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("GUI", "Agent", provider="agy", session_id="previous")
    service.register("GUI", "Agent", provider="codex", session_id="current", select=True)

    def concurrent_activation(*args, **kwargs):
        service.attach_session(gui="GUI", name="Agent", provider="codex", session_id="competing",
                               apply=True, provenance="concurrent-test")
        return {}

    monkeypatch.setattr("agent_continuity.dispatcher_cli._launch_preview", concurrent_activation)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: pytest.fail("stale session launched"))
    parser = build_parser()
    args = parser.parse_args(["-H", str(home), "switch", "-g", "GUI", "-n", "Agent", "-p", "agy", "-r", "-a"])
    with pytest.raises(ContinuityError, match="selection changed"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
    assert service.get_slot(gui="GUI", name="Agent")["current"]["native_session_id"] == "competing"


def test_switch_reuse_invalid_cwd_does_not_reactivate_inactive_slot(tmp_path):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("GUI", "Agent", provider="agy", session_id="previous")
    service.register("GUI", "Agent", provider="codex", session_id="current", select=True)
    service.set_slot_state(gui="GUI", name="Agent", state="inactive", apply=True)
    before = service.get_slot(gui="GUI", name="Agent")
    parser = build_parser()
    args = parser.parse_args([
        "-H", str(home), "switch", "-g", "GUI", "-n", "Agent", "-p", "agy", "-r", "-R", "-a",
        "-C", str(tmp_path / "missing"),
    ])
    with pytest.raises(ContinuityError, match="Working directory does not exist"):
        dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO())
    after = service.get_slot(gui="GUI", name="Agent")
    assert after["state"] == "inactive"
    assert after["current"] == before["current"]
    assert after["history"] == before["history"]


def test_switch_reuse_with_reactivation_selects_exact_history_atomically(tmp_path, monkeypatch):
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register("GUI", "Agent", provider="agy", session_id="previous")
    service.register("GUI", "Agent", provider="codex", session_id="current", select=True)
    service.set_slot_state(gui="GUI", name="Agent", state="inactive", apply=True)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._launch_preview", lambda *a, **k: {})
    monkeypatch.setattr("agent_continuity.dispatcher_cli._run_pane", lambda *a, **k: 0)
    parser = build_parser()
    args = parser.parse_args([
        "-H", str(home), "switch", "-g", "GUI", "-n", "Agent", "-p", "agy", "-r", "-R", "-a",
    ])
    assert dispatch(args, parser, input_stream=StringIO(), output_stream=StringIO()) == 0
    after = service.get_slot(gui="GUI", name="Agent")
    assert after["state"] == "active"
    assert after["current"]["provider"] == "agy"
    assert after["current"]["native_session_id"] == "previous"
    assert [row["native_session_id"] for row in after["history"]] == ["previous", "current", "previous"]
