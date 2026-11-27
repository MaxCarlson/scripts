from __future__ import annotations

import base64
import io
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from terminal_launcher.backend import LaunchStatus
from terminal_launcher.backends import windows_terminal

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import main
from agent_continuity.interactive import run_interactive
from agent_continuity.service import ContinuityService


class CaptureRunner:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, self.returncode, stdout="", stderr="")


def _dispatcher(home: Path, active_count: int) -> DispatcherService:
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.create_gui("AgentImprovement", apply=True)
    for index in range(1, 5):
        name = f"Agent{index}"
        dispatcher.create_slot(gui="AgentImprovement", name=name, apply=True)
        dispatcher.attach_session(
            gui="AgentImprovement",
            name=name,
            provider="codex",
            session_id=f"native-session-{index}",
            cwd=rf"C:\Workspace Area;雪\{name}",
            apply=True,
        )
        if index > active_count:
            dispatcher.set_slot_state(gui="AgentImprovement", name=name, state="inactive", apply=True)
    return dispatcher


def _expected_activity_order(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    named = sorted(slots, key=lambda slot: slot["name"].casefold())
    return sorted(named, key=lambda slot: slot.get("last_activity_at") or "", reverse=True)


def _capture_terminal(monkeypatch, *, returncode: int = 0) -> CaptureRunner:
    runner = CaptureRunner(returncode)
    monkeypatch.setattr(windows_terminal.shutil, "which", lambda _: r"C:\Program Files\Windows Terminal\wt.exe")
    monkeypatch.setattr(windows_terminal.subprocess, "run", runner)
    return runner


def _child_payloads(command: list[str]) -> list[tuple[list[str], str | None]]:
    result = []
    for index, value in enumerate(command[:-1]):
        if Path(value).name == "_pane_runner.py":
            encoded = command[index + 1]
            encoded += "=" * (-len(encoded) % 4)
            argv, cwd = json.loads(base64.urlsafe_b64decode(encoded))
            result.append((argv, cwd))
    return result


@pytest.mark.parametrize(
    ("pane_count", "split_directions", "layout"),
    [
        (2, ["-V"], "two-column"),
        (3, ["-V", "-H"], "three-left"),
        (4, ["-V", "-H", "-H"], "grid"),
    ],
)
def test_noninteractive_open_previews_then_submits_grouped_active_slots(
    tmp_path, monkeypatch, capsys, pane_count, split_directions, layout
):
    home = tmp_path / "registry"
    dispatcher = _dispatcher(home, active_count=pane_count)
    active_slots = _expected_activity_order(dispatcher.list_slots(gui="AgentImprovement"))
    runner = _capture_terminal(monkeypatch)

    dry_code = main(["-H", str(home), "open", "-g", "AgentImprovement", "-k", str(pane_count), "-w", "llmd-test-window", "-j", "-d"])
    dry_output = json.loads(capsys.readouterr().out)

    assert dry_code == 0
    assert dry_output["applied"] is False
    assert dry_output["preview"]["operations"][0]["layout"] == layout
    assert runner.calls == []

    apply_code = main(["-H", str(home), "open", "-g", "AgentImprovement", "-k", str(pane_count), "-w", "llmd-test-window", "-a", "-j"])
    applied = json.loads(capsys.readouterr().out)

    assert apply_code == 0
    assert applied["launch"]["status"] == LaunchStatus.SUBMITTED.value
    assert applied["launch"]["process_state"] == "unknown"
    assert applied["preview"]["operations"][0]["layout"] == layout
    expected_names = [slot["name"] for slot in active_slots]
    assert applied["preview"]["operations"][0]["tab_title"] == " | ".join(expected_names)
    assert len(runner.calls) == 1
    command, options = runner.calls[0]
    assert command[:3] == [r"C:\Program Files\Windows Terminal\wt.exe", "--window", "llmd-test-window"]
    assert options["shell"] is False
    assert [command[index + 1] for index, token in enumerate(command) if token == "split-pane"] == split_directions
    child_payloads = _child_payloads(command)
    child_argvs = [argv for argv, _ in child_payloads]
    assert [argv[:4] for argv in child_argvs] == [
        ["llmd", "pane-run", "--slot-id", slot["slot_id"]]
        for slot in active_slots[:pane_count]
    ]
    contexts = [argv[5] for argv in child_argvs]
    assert all(argv[4] == "-T" and UUID(context) for argv, context in zip(child_argvs, contexts, strict=True))
    assert len(set(contexts)) == pane_count
    assert [cwd for _, cwd in child_payloads] == [rf"C:\Workspace Area;雪\{slot['name']}" for slot in active_slots]


def test_interactive_open_all_uses_the_same_preview_and_submission_path(tmp_path, monkeypatch, capsys):
    dispatcher = _dispatcher(tmp_path / "registry", active_count=2)
    active_slots = _expected_activity_order(dispatcher.list_slots(gui="AgentImprovement"))
    runner = _capture_terminal(monkeypatch)
    from agent_continuity import interactive

    home = dispatcher.home_dir
    cli_status = main(["-H", str(home), "open", "-g", "AgentImprovement", "-j", "-d"])
    assert cli_status == 0
    cli_preview = json.loads(capsys.readouterr().out)

    selections = iter((
        ("selected", dispatcher.list_guis()[0]),
        ("open_all", None),
        ("back", None),
        ("exit", None),
    ))
    monkeypatch.setattr(interactive, "select_item", lambda *args, **kwargs: next(selections))

    output = io.StringIO()
    status = run_interactive(dispatcher, input_stream=io.StringIO("y\n"), output_stream=output)

    assert status == 0
    assert "Open All preview:" in output.getvalue()
    preview_text = output.getvalue().split("Open All preview:\n", 1)[1]
    preview_result, _ = json.JSONDecoder().raw_decode(preview_text)
    assert preview_result["preview"] == cli_preview["preview"]
    assert preview_result["preview"]["operations"][0]["tab_title"] == " | ".join(slot["name"] for slot in active_slots)
    assert len(runner.calls) == 1
    command, _ = runner.calls[0]
    assert len(_child_payloads(command)) == 2
    assert "Launch request submitted; pane process state is unknown." in output.getvalue()


def test_interactive_open_all_reports_backend_rejection(tmp_path, monkeypatch):
    dispatcher = _dispatcher(tmp_path / "registry", active_count=1)
    runner = _capture_terminal(monkeypatch, returncode=17)
    from agent_continuity import interactive

    selections = iter((
        ("selected", dispatcher.list_guis()[0]),
        ("open_all", None),
        ("back", None),
        ("exit", None),
    ))
    monkeypatch.setattr(interactive, "select_item", lambda *args, **kwargs: next(selections))

    output = io.StringIO()
    status = run_interactive(dispatcher, input_stream=io.StringIO("y\n"), output_stream=output)

    assert status == 0
    assert len(runner.calls) == 1
    assert "Open All launch failed: Windows Terminal rejected the launch request" in output.getvalue()
    assert "Launch request submitted; pane process state is unknown." not in output.getvalue()


@pytest.mark.parametrize(("active_count", "panes_per_tab", "expected_tab_count"), [(2, 2, 1), (4, 2, 2)])
def test_default_open_uses_two_panes_per_tab(tmp_path, monkeypatch, capsys, active_count, panes_per_tab, expected_tab_count):
    home = tmp_path / "registry"
    dispatcher = _dispatcher(home, active_count=active_count)
    active_slots = dispatcher.list_slots(gui="AgentImprovement")
    runner = _capture_terminal(monkeypatch)

    status = main(["-H", str(home), "open", "-g", "AgentImprovement", "-j", "-d"])
    result = json.loads(capsys.readouterr().out)

    assert status == 0
    assert result["panes_per_tab"] == panes_per_tab
    operations = result["preview"]["operations"]
    tab_indices = {operation["tab_index"] for operation in operations}
    assert tab_indices == set(range(expected_tab_count))
    assert runner.calls == []
    if active_count == 2:
        assert len(operations) == 2
        assert {operation["layout"] for operation in operations} == {"two-column"}
        assert {operation["tab_title"] for operation in operations} == {" | ".join(slot["name"] for slot in active_slots)}
    else:
        assert len(operations) == 4
        assert [operation["tab_title"] for operation in operations if operation["action"] == "create_tab"] == [
            " | ".join(slot["name"] for slot in active_slots[:2]),
            " | ".join(slot["name"] for slot in active_slots[2:]),
        ]


def test_open_all_excludes_completed_slots_and_retains_history(tmp_path, monkeypatch, capsys):
    home = tmp_path / "registry"
    dispatcher = _dispatcher(home, active_count=3)
    slots = _expected_activity_order(dispatcher.list_slots(gui="AgentImprovement"))
    completed = slots[0]
    dispatcher.set_slot_state(gui="AgentImprovement", name=completed["name"], state="completed", apply=True)
    history = dispatcher.get_slot(gui="AgentImprovement", name=completed["name"])["history"]
    _capture_terminal(monkeypatch)

    status = main(["-H", str(home), "open", "-g", "AgentImprovement", "-j"])
    result = json.loads(capsys.readouterr().out)

    assert status == 0
    assert [pane["slot_id"] for pane in result["request"]["panes"]] == [slot["slot_id"] for slot in slots[1:]]
    assert dispatcher.get_slot(gui="AgentImprovement", name=completed["name"])["history"] == history


def test_open_all_reports_unresolved_pending_slots_without_starting_a_session(tmp_path, monkeypatch, capsys):
    home = tmp_path / "registry"
    dispatcher = DispatcherService(ContinuityService(home))
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    pending = dispatcher.begin_launch(gui="AgentImprovement", name="AgentPerf", provider="codex", apply=True)
    monkeypatch.setattr(windows_terminal.shutil, "which", lambda _: None)

    status = main(["-H", str(home), "open", "-g", "AgentImprovement", "-j"])
    result = json.loads(capsys.readouterr().out)

    assert status == 0
    assert result["request"]["panes"] == []
    assert result["request"]["unresolved"] == [
        {
            "slot_id": pending["details"]["slot_id"],
            "agent_name": "AgentPerf",
            "reason": "native codex session identity pending",
        }
    ]


def test_noninteractive_open_reports_failed_terminal_submission(tmp_path, monkeypatch, capsys):
    home = tmp_path / "registry"
    dispatcher = _dispatcher(home, active_count=1)
    before = dispatcher.get_slot(gui="AgentImprovement", name="Agent1")
    _capture_terminal(monkeypatch, returncode=17)

    status = main(["-H", str(home), "open", "-g", "AgentImprovement", "-a", "-j"])
    result = json.loads(capsys.readouterr().out)

    assert status == 1
    assert result["launch"]["status"] == LaunchStatus.FAILED.value
    assert result["launch"]["returncode"] == 17
    after = dispatcher.get_slot(gui="AgentImprovement", name="Agent1")
    assert after["current"] == before["current"]
    assert after["history"] == before["history"]
