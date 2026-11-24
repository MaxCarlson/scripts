"""Terminal-scoped launch history persistence and query contracts."""

from __future__ import annotations

import io
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_continuity import dispatcher_cli
from agent_continuity.dispatcher import DispatcherService
from agent_continuity.errors import ContinuityError
from agent_continuity.service import ContinuityService


def _record(dispatcher: DispatcherService, terminal_id: str, launch_id: str, *, status: str = "running") -> dict:
    gui = dispatcher.create_gui("Terminal history", apply=True)["details"]["gui_id"]
    slot = dispatcher.create_slot(gui="Terminal history", name=f"agent-{launch_id}", apply=True)["details"]["slot_id"]
    environment_id = dispatcher.materializer.list_environments()[0].environment_id
    return {
        "launch_id": launch_id,
        "terminal_session_id": terminal_id,
        "terminal_session_owner_pid": "4242",
        "gui_id": gui,
        "gui_alias": "Terminal history",
        "slot_id": slot,
        "slot_name": f"agent-{launch_id}",
        "provider": "codex",
        "native_session_id": f"session-{launch_id}",
        "environment_id": environment_id,
        "launch_started_at": "2026-11-23T12:00:00+00:00",
        "launch_exited_at": None,
        "status": status,
        "exit_code": None,
        "requested_cwd": None,
        "effective_cwd": r"C:\work\repo",
        "native_cwd": r"C:\work\repo",
        "git_repository": r"C:\work\repo",
        "git_worktree": None,
        "git_branch": "main",
        "git_commit": "a" * 40,
        "settings": {"sandbox": "workspace-write"},
    }


def test_terminal_launch_updates_are_immutable_and_rebuildable(tmp_path: Path) -> None:
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    terminal_id = str(uuid4())
    record = _record(dispatcher, terminal_id, "launch-1")

    dispatcher.record_terminal_launch(record)
    completed = {**record, "status": "exited", "exit_code": 0,
                 "launch_exited_at": "2026-11-23T12:01:00+00:00"}
    dispatcher.record_terminal_launch(completed)

    rows = dispatcher.list_terminal_launches(terminal_id, limit=10)
    assert len(rows) == 1
    assert rows[0]["status"] == "exited"
    assert rows[0]["native_session_id"] == "session-launch-1"
    assert rows[0]["settings"] == {"sandbox": "workspace-write"}

    ContinuityService(home).rebuild_index(apply=True)
    rebuilt = DispatcherService(home_dir=home).list_terminal_launches(terminal_id, limit=10)
    assert rebuilt == rows
    event_files = list((home / "events").rglob("*.json"))
    assert len(event_files) >= 2


def test_concurrent_terminal_launches_keep_distinct_history_records(tmp_path: Path) -> None:
    home = tmp_path / "registry"
    terminal_id = str(uuid4())
    DispatcherService(home_dir=home).create_gui("Terminal history", apply=True)

    def write_record(index: int) -> None:
        service = DispatcherService(home_dir=home)
        record = _record(service, terminal_id, f"launch-{index}")
        service.record_terminal_launch(record)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(write_record, range(12)))

    rows = DispatcherService(home_dir=home).list_terminal_launches(terminal_id, limit=20)
    assert len(rows) == 12
    assert {row["launch_id"] for row in rows} == {f"launch-{index}" for index in range(12)}


@pytest.mark.parametrize("value", ["", "not-a-uuid", "1234"])
def test_terminal_history_rejects_missing_or_malformed_scope(tmp_path: Path, value: str) -> None:
    service = DispatcherService(home_dir=tmp_path / "registry")
    with pytest.raises(ContinuityError):
        service.list_terminal_launches(value, limit=10)


def test_last_is_strictly_terminal_scoped_and_json_is_one_document(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    first = _record(service, str(uuid4()), "launch-first")
    second = _record(service, str(uuid4()), "launch-second")
    service.record_terminal_launch(first)
    service.record_terminal_launch(second)

    monkeypatch.setenv("TERMINAL_SESSION_ID", first["terminal_session_id"])
    assert dispatcher_cli.main(["-H", str(home), "last", "-j"]) == 0
    output = capsys.readouterr().out
    import json

    parsed = json.loads(output)
    assert parsed["launches"][0]["launch_id"] == "launch-first"
    assert parsed["launches"][0]["terminal_session_id"] == first["terminal_session_id"]

    monkeypatch.delenv("TERMINAL_SESSION_ID")
    assert dispatcher_cli.main(["-H", str(home), "last", "-j"]) == 1
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_recent_is_read_only_cross_terminal_history(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    first = _record(service, str(uuid4()), "launch-first")
    second = _record(service, str(uuid4()), "launch-second")
    service.record_terminal_launch(first)
    service.record_terminal_launch(second)

    assert dispatcher_cli.main(["-H", str(home), "recent", "-N", "10", "-j"]) == 0
    import json

    output = capsys.readouterr().out
    parsed = json.loads(output)
    assert len(parsed["launches"]) == 2
    assert {row["terminal_session_id"] for row in parsed["launches"]} == {
        first["terminal_session_id"], second["terminal_session_id"]
    }


def test_last_count_selects_only_requested_terminal_history(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    terminal_id = str(uuid4())
    rows = [_record(service, terminal_id, f"launch-{index}") for index in range(3)]
    for row in rows:
        service.record_terminal_launch(row)
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)

    assert dispatcher_cli.main(["-H", str(home), "last", "-N", "2", "-j"]) == 0
    import json

    parsed = json.loads(capsys.readouterr().out)
    assert len(parsed["launches"]) == 2
    assert {row["terminal_session_id"] for row in parsed["launches"]} == {terminal_id}


def test_last_requires_explicit_reactivation_for_inactive_slot(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register(gui="GUI", name="Agent", provider="codex", session_id="exact", apply=True)
    slot = service.get_slot(gui="GUI", name="Agent")
    current = slot["current"]
    terminal_id = str(uuid4())
    record = {
        "launch_id": "inactive-launch", "terminal_session_id": terminal_id,
        "gui_id": slot["gui_id"], "gui_alias": "GUI", "slot_id": slot["slot_id"], "slot_name": "Agent",
        "provider": "codex", "native_session_id": "exact", "environment_id": current["environment_id"],
        "launch_started_at": "2026-11-23T12:00:00+00:00", "launch_exited_at": "2026-11-23T12:01:00+00:00",
        "status": "exited", "exit_code": 0, "requested_cwd": None, "effective_cwd": r"C:\stale",
        "native_cwd": None, "git_repository": None, "git_worktree": None, "git_branch": None,
        "git_commit": None, "settings": {"sandbox": "workspace-write"},
    }
    service.record_terminal_launch(record)
    service.set_slot_state(gui="GUI", name="Agent", state="inactive", apply=True)
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)
    monkeypatch.setattr(dispatcher_cli, "_run_pane", lambda *a, **kw: 0)

    assert dispatcher_cli.main(["-H", str(home), "last", "-a"]) == 1
    assert DispatcherService(home_dir=home).get_slot(gui="GUI", name="Agent")["state"] == "inactive"
    assert dispatcher_cli.main(["-H", str(home), "last", "-R", "-a"]) == 0
    assert DispatcherService(home_dir=home).get_slot(gui="GUI", name="Agent")["state"] == "active"


def test_wsl_git_context_uses_recorded_distribution_and_argv_paths(monkeypatch) -> None:
    from agent_continuity.dispatcher_cli import _git_launch_context

    calls = []
    monkeypatch.setattr(dispatcher_cli, "_resolve_environment", lambda *_a, **_k: SimpleNamespace(
        environment_id="wsl:Ubuntu", runtime_kind="wsl", distro="Ubuntu"
    ))
    monkeypatch.setattr(dispatcher_cli, "detect_runtime_kind", lambda: "windows")
    monkeypatch.setattr(dispatcher_cli.shutil, "which", lambda name: "C:/Windows/wsl.exe" if name == "wsl.exe" else None)

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "/work/repo\n/work/repo/.git\n/work/repo/.git\nmain\n" + "c" * 40 + "\n", "")

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    context = _git_launch_context(DispatcherService(home_dir="unused"), "wsl:Ubuntu", "/work/repo with spaces")
    assert calls[0][:7] == ["C:/Windows/wsl.exe", "--distribution", "Ubuntu", "--exec", "git", "-C", "/work/repo with spaces"]
    assert context == {"git_repository": "/work/repo", "git_worktree": "/work/repo", "git_branch": "main", "git_commit": "c" * 40}


def test_interrupted_bootstrap_is_recorded_without_guessing_session_id(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    launch = dispatcher.prepare_start(gui="GUI", name="Agent", provider="codex", apply=True)
    terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)

    def fake_run(argv, **kwargs):
        if Path(str(argv[0])).name.casefold() == "git.exe" or str(argv[0]).casefold() == "git":
            repo = str(tmp_path)
            return subprocess.CompletedProcess(argv, 0, f"{repo}\n{repo}/.git\n{repo}/.git\nmain\n{'d' * 40}\n", "")
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    from agent_continuity.dispatcher_cli import _run_pane

    result = _run_pane(
        dispatcher, slot_id=launch["details"]["slot_id"], launch_id=launch["details"]["launch_id"],
        input_stream=io.StringIO(), output_stream=io.StringIO(),
    )
    assert result == 124
    rows = dispatcher.list_terminal_launches(terminal_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "interrupted"
    assert rows[0]["native_session_id"] is None


def test_last_apply_resumes_exact_session_without_replaying_cwd(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "registry"
    service = DispatcherService(home_dir=home)
    service.register(gui="Original GUI", name="Agent", provider="codex", session_id="exact-session", apply=True)
    slot = service.get_slot(gui="Original GUI", name="Agent")
    current = slot["current"]
    record = {
        "launch_id": "launch-exact", "terminal_session_id": str(uuid4()),
        "terminal_session_owner_pid": "4242", "gui_id": slot["gui_id"],
        "gui_alias": "Original GUI", "slot_id": slot["slot_id"], "slot_name": "Agent",
        "provider": "codex", "native_session_id": "exact-session",
        "environment_id": current["environment_id"], "launch_started_at": "2026-11-23T12:00:00+00:00",
        "launch_exited_at": "2026-11-23T12:01:00+00:00", "status": "exited", "exit_code": 0,
        "requested_cwd": r"C:\stale\launch", "effective_cwd": r"C:\stale\launch",
        "native_cwd": current.get("cwd_native"), "git_repository": None, "git_worktree": None,
        "git_branch": None, "git_commit": None, "settings": {"sandbox": "workspace-write"},
    }
    service.record_terminal_launch(record)
    monkeypatch.setenv("TERMINAL_SESSION_ID", record["terminal_session_id"])
    calls = []
    monkeypatch.setattr(dispatcher_cli, "_run_pane", lambda *a, **kw: calls.append(kw) or 0)
    requested_cwd = tmp_path / "explicit worktree"
    requested_cwd.mkdir()

    assert dispatcher_cli.main([
        "-H", str(home), "last", "-C", str(requested_cwd), "-U", "-a", "--", "--future-option", "two words",
    ]) == 0
    assert calls[0]["expected_session_identity"] == (
        "codex", current["environment_id"], "exact-session"
    )
    assert calls[0]["native_args"] == ["--future-option", "two words"]
    assert calls[0]["cwd_override"] == str(requested_cwd)
    assert calls[0]["allow_native_unknown"] is True


def test_provider_launch_records_start_exact_session_git_context_and_exit(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register(gui="Launch GUI", name="Agent", provider="codex", session_id="exact-session", apply=True)
    slot = dispatcher.get_slot(gui="Launch GUI", name="Agent")
    terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)
    monkeypatch.setenv("TERMINAL_SESSION_OWNER_PID", "4567")
    commands = []

    def fake_run(argv, **kwargs):
        commands.append(list(argv))
        if Path(str(argv[0])).name.casefold() == "git.exe" or str(argv[0]).casefold() == "git":
            repo = str(tmp_path / "repo")
            return subprocess.CompletedProcess(argv, 0, f"{repo}\n{repo}\\.git\n{repo}\\.git\nmain\n{'b' * 40}\n", "")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    from agent_continuity.dispatcher_cli import _run_pane

    result = _run_pane(
        dispatcher, slot_id=slot["slot_id"], launch_id=None, input_stream=io.StringIO("1\n"),
        output_stream=io.StringIO(), show_summary=False,
    )

    assert result == 0
    assert len(commands) == 2
    rows = dispatcher.list_terminal_launches(terminal_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "exited"
    assert rows[0]["exit_code"] == 0
    assert rows[0]["native_session_id"] == "exact-session"
    assert rows[0]["terminal_session_owner_pid"] == "4567"
    assert rows[0]["git_branch"] == "main"
    assert rows[0]["git_commit"] == "b" * 40
