from __future__ import annotations

import subprocess
from io import StringIO
from types import SimpleNamespace

import pytest

from agent_continuity.dispatcher import DispatcherService
from agent_continuity.dispatcher_cli import _native_argv, _run_pane
from agent_continuity.errors import ContinuityError
from agent_continuity.models import EnvironmentInfo, EventEnvelope, EventType
from agent_continuity.service import ContinuityService


class FakeAdapter:
    def __init__(self, executable="codex.exe"):
        self.executable = executable

    def detect_installation(self):
        return SimpleNamespace(installed=True, runnable=True, executable_path=self.executable, detail="")

    def resolve_resume_command(self, session_id, *, cwd, environment_id, runtime_kind):
        argv = ["codex", "resume"]
        if cwd:
            argv.extend(["-C", cwd])
        argv.append(session_id)
        return SimpleNamespace(argv=argv)


def _dispatcher_with_session(tmp_path, *, provider="codex", session_id="session-1", cwd=r"C:\Project With Spaces"):
    continuity = ContinuityService(tmp_path / "registry")
    dispatcher = DispatcherService(continuity)
    dispatcher.create_gui("AgentImprovement", apply=True)
    dispatcher.create_slot(gui="AgentImprovement", name="AgentPerf", apply=True)
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider=provider,
                              session_id=session_id, cwd=cwd, apply=True)
    return dispatcher, dispatcher.list_slots(gui="AgentImprovement")[0]


def test_windows_resume_uses_provider_adapter_arguments_and_executable(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path)
    dispatcher.continuity.adapters["codex"] = FakeAdapter(r"C:\Program Files\Codex\codex.exe")
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")

    argv = _native_argv(dispatcher, "codex", "session-1", environment_id=slot["current_environment_id"],
                        cwd=r"C:\Project With Spaces")

    assert argv == [r"C:\Program Files\Codex\codex.exe", "resume", "-C", r"C:\Project With Spaces", "session-1"]


def test_codex_cmd_wrapper_is_invoked_as_argument_safe_powershell_file(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path)
    install_dir = tmp_path / "Codex Tools"
    install_dir.mkdir()
    command_wrapper = install_dir / "codex.CMD"
    powershell_wrapper = install_dir / "codex.ps1"
    powershell_wrapper.write_text("# fixture", encoding="utf-8")
    dispatcher.continuity.adapters["codex"] = FakeAdapter(str(command_wrapper))
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr("agent_continuity.dispatcher_cli.shutil.which", lambda name: r"C:\Program Files\PowerShell\7\pwsh.exe" if name == "pwsh" else None)

    argv = _native_argv(dispatcher, "codex", "session-1", environment_id=slot["current_environment_id"],
                        cwd=r"C:\Project & $Data")

    assert argv == [r"C:\Program Files\PowerShell\7\pwsh.exe", "-NoLogo", "-NoProfile", "-File",
                    str(powershell_wrapper), "resume", "-C", r"C:\Project & $Data", "session-1"]


def test_windows_launcher_uses_wsl_distribution_and_native_working_directory(tmp_path, monkeypatch):
    dispatcher, _ = _dispatcher_with_session(tmp_path, provider="codex", session_id="wsl-session")
    env = EnvironmentInfo(
        environment_id="wsl_ubuntu_test", runtime_kind="wsl", distro="Ubuntu", hostname="test",
        label="Ubuntu", created_at="2026-11-19T00:00:00Z", last_seen_at="2026-11-19T00:00:00Z",
    )
    event = EventEnvelope(
        event_id="evt_wsl_environment", event_schema_version=1, event_type=EventType.ENVIRONMENT_REGISTERED.value,
        provider=None, environment_id=env.environment_id, native_session_id=None,
        source_timestamp=env.created_at, observed_timestamp=env.created_at, source_adapter_version="test",
        payload=env.to_dict(),
    )
    dispatcher.continuity._emit_and_materialize([event])
    dispatcher.attach_session(gui="AgentImprovement", name="AgentPerf", provider="codex", session_id="wsl-session",
                              environment_selector=env.environment_id, cwd="/home/user/project", apply=True)
    dispatcher.continuity.adapters["codex"] = FakeAdapter()
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr("agent_continuity.dispatcher_cli.shutil.which", lambda name: r"C:\Windows\System32\wsl.exe")

    argv = _native_argv(dispatcher, "codex", "wsl-session", environment_id=env.environment_id,
                        cwd="/home/user/project")

    assert argv == [r"C:\Windows\System32\wsl.exe", "--distribution", "Ubuntu", "--cd",
                    "/home/user/project", "--exec", "codex", "resume", "wsl-session"]


def test_windows_session_is_not_launched_from_wsl(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path)
    monkeypatch.setattr("agent_continuity.dispatcher_cli.detect_runtime_kind", lambda: "wsl")
    with pytest.raises(ContinuityError, match="Cannot launch windows session from runtime"):
        _native_argv(dispatcher, "codex", "session-1", environment_id=slot["current_environment_id"], cwd=None)


def test_normal_exit_prompts_and_unexpected_nonzero_exit_preserves_active_state(tmp_path, monkeypatch):
    dispatcher, slot = _dispatcher_with_session(tmp_path)
    monkeypatch.setattr("agent_continuity.dispatcher_cli._native_argv", lambda *a, **k: ["fake-provider"])
    codes = iter((0, 17))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=next(codes)))

    result = _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                       input_stream=StringIO("2\n"), output_stream=StringIO())
    assert result == 0
    assert dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["state"] == "completed"

    dispatcher.set_slot_state(gui="AgentImprovement", name="AgentPerf", state="active", apply=True)
    result = _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                       input_stream=StringIO("3\n"), output_stream=StringIO())
    assert result == 17
    assert dispatcher.get_slot(gui="AgentImprovement", name="AgentPerf")["state"] == "active"
