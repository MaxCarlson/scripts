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
from agent_continuity.errors import ContinuityError, ErrorCode
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
    seed = _record(DispatcherService(home_dir=home), terminal_id, "seed-launch")

    def write_record(index: int) -> None:
        service = DispatcherService(home_dir=home)
        record = {**seed, "launch_id": f"launch-{index}"}
        service.record_terminal_launch(record)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write_record, range(2)))

    rows = DispatcherService(home_dir=home).list_terminal_launches(terminal_id, limit=20)
    assert len(rows) == 2
    assert {row["launch_id"] for row in rows} == {f"launch-{index}" for index in range(2)}


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


def test_new_session_history_records_requested_and_native_cwd(tmp_path: Path, monkeypatch) -> None:
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    cwd = tmp_path / "new session worktree"
    cwd.mkdir()
    launch = dispatcher.prepare_start(gui="GUI", name="New Agent", provider="codex", cwd=str(cwd), apply=True)
    terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)

    def fake_run(argv, **kwargs):
        if Path(str(argv[0])).name.casefold() in {"git", "git.exe"}:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "exec" in argv and "--json" in argv:
            stdout = '{"type":"thread.started","thread_id":"captured-exact-id"}\n{"type":"turn.completed"}\n'
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    result = dispatcher_cli._run_pane(
        dispatcher, slot_id=launch["details"]["slot_id"], launch_id=launch["details"]["launch_id"],
        input_stream=io.StringIO("1\n"), output_stream=io.StringIO(), show_summary=False,
    )

    assert result == 0
    [record] = dispatcher.list_terminal_launches(terminal_id)
    assert record["native_session_id"] == "captured-exact-id"
    assert record["requested_cwd"] == str(cwd)
    assert record["effective_cwd"] == str(cwd)
    assert record["native_cwd"] == str(cwd)
    rebuilt = DispatcherService(home_dir=tmp_path / "registry").list_terminal_launches(terminal_id)
    assert rebuilt[0]["native_cwd"] == str(cwd)


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


def test_provider_launch_records_launcher_owned_terminal_context(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "registry"
    dispatcher = DispatcherService(home_dir=home)
    dispatcher.register(gui="Launch GUI", name="Agent", provider="codex", session_id="exact-session", apply=True)
    slot = dispatcher.get_slot(gui="Launch GUI", name="Agent")
    profile_terminal_id = str(uuid4())
    launcher_terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", profile_terminal_id)
    commands = []

    def fake_run(argv, **kwargs):
        commands.append(list(argv))
        if Path(str(argv[0])).name.casefold() == "git.exe" or str(argv[0]).casefold() == "git":
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    from agent_continuity.dispatcher_cli import _run_pane

    result = _run_pane(
        dispatcher, slot_id=slot["slot_id"], launch_id=None, input_stream=io.StringIO("1\n"),
        output_stream=io.StringIO(), show_summary=False, launcher_terminal_context=launcher_terminal_id,
    )
    assert result == 0
    assert dispatcher.list_terminal_launches(profile_terminal_id) == []
    assert dispatcher.list_terminal_launches(launcher_terminal_id)[0]["native_session_id"] == "exact-session"


def test_launcher_context_survives_provider_switch_and_reviewer_return(tmp_path: Path, monkeypatch) -> None:
    class TTY(io.StringIO):
        def isatty(self) -> bool:
            return True

    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.create_gui("GUI", apply=True)
    dispatcher.create_slot(gui="GUI", name="Original", apply=True)
    dispatcher.create_slot(gui="GUI", name="Reviewer", apply=True)
    dispatcher.attach_session(gui="GUI", name="Original", provider="agy", session_id="original-agy", apply=True)
    dispatcher.attach_session(gui="GUI", name="Original", provider="codex", session_id="original-exact", apply=True)
    dispatcher.attach_session(gui="GUI", name="Reviewer", provider="codex", session_id="reviewer-codex", apply=True)
    dispatcher.attach_session(gui="GUI", name="Reviewer", provider="agy", session_id="reviewer-agy", apply=True)
    dispatcher.set_slot_state(gui="GUI", name="Reviewer", state="inactive", apply=True)
    original = dispatcher.get_slot(gui="GUI", name="Original")
    reviewer = dispatcher.get_slot(gui="GUI", name="Reviewer")
    cycle = dispatcher_cli._review_cycle_payload(original, reviewer["slot_id"], reviewer["current"])
    dispatcher.complete_agent_transition(
        gui="GUI", source_slot_id=original["slot_id"], destination_slot_id=reviewer["slot_id"],
        provider="agy", environment_id=reviewer["current"]["environment_id"], session_id="reviewer-agy",
        source_state="inactive", destination_state="active",
        expected_source=("codex", original["current"]["environment_id"], "original-exact"),
        expected_destination=("agy", reviewer["current"]["environment_id"], "reviewer-agy"),
        review_cycle=cycle, apply=True,
    )

    shell_terminal_id = str(uuid4())
    pane_terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", shell_terminal_id)
    monkeypatch.setattr(
        dispatcher_cli, "_native_argv",
        lambda _dispatcher, provider, session_id, **_kwargs: [provider, "resume", session_id],
    )

    def fake_run(argv, **_kwargs):
        if Path(str(argv[0])).name.casefold() in {"git", "git.exe"}:
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(
        "agent_continuity.interactive.select_item",
        lambda items, **_kwargs: ("selected", next(row for row in items if row["name"] == "Original")),
    )

    result = dispatcher_cli._run_pane(
        dispatcher, slot_id=reviewer["slot_id"], launch_id=None,
        input_stream=TTY("5\n4\nr\n1\n"), output_stream=TTY(), show_summary=False,
        launcher_terminal_context=pane_terminal_id,
    )

    assert result == 0
    assert dispatcher.list_terminal_launches(shell_terminal_id) == []
    launches = dispatcher.list_terminal_launches(pane_terminal_id, limit=10)
    assert len(launches) == 3
    assert {launch["native_session_id"] for launch in launches} == {
        "original-exact", "original-agy", "reviewer-agy",
    }
    assert dispatcher.get_slot(gui="GUI", name="Original")["state"] == "active"
    assert dispatcher.get_slot(gui="GUI", name="Reviewer")["state"] == "inactive"
    assert dispatcher._rows("SELECT status FROM dispatcher_review_cycles") == [{"status": "returned"}]


def test_failed_command_preflight_does_not_replace_terminal_history(tmp_path: Path, monkeypatch) -> None:
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register(gui="Launch GUI", name="Agent", provider="codex", session_id="exact-session", apply=True)
    slot = dispatcher.get_slot(gui="Launch GUI", name="Agent")
    terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)
    prior = _record(dispatcher, terminal_id, "prior-success", status="exited")
    prior["native_session_id"] = "prior-session"
    prior["launch_exited_at"] = "2026-11-23T12:01:00+00:00"
    prior["exit_code"] = 0
    dispatcher.record_terminal_launch(prior)

    def fail_preflight(*_args, **_kwargs):
        raise ContinuityError(ErrorCode.PROVIDER_UNAVAILABLE, "fake executable unavailable")

    monkeypatch.setattr(dispatcher_cli, "_native_argv", fail_preflight)
    with pytest.raises(ContinuityError, match="fake executable unavailable"):
        dispatcher_cli._run_pane(
            dispatcher, slot_id=slot["slot_id"], launch_id=None,
            input_stream=io.StringIO(), output_stream=io.StringIO(), show_summary=False,
        )

    rows = dispatcher.list_terminal_launches(terminal_id)
    assert len(rows) == 1
    assert rows[0]["launch_id"] == "prior-success"


def test_failed_bootstrap_preflight_keeps_pending_launch_retryable(tmp_path: Path, monkeypatch) -> None:
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    launch = dispatcher.prepare_start(gui="GUI", name="Pending", provider="codex", apply=True)
    terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)

    def fail_preflight(*_args, **_kwargs):
        raise ContinuityError(ErrorCode.PROVIDER_UNAVAILABLE, "fake bootstrap executable missing")

    monkeypatch.setattr(dispatcher_cli, "_bootstrap_native_argv", fail_preflight)
    with pytest.raises(ContinuityError, match="fake bootstrap executable missing"):
        dispatcher_cli._run_pane(
            dispatcher, slot_id=launch["details"]["slot_id"], launch_id=launch["details"]["launch_id"],
            input_stream=io.StringIO(), output_stream=io.StringIO(), show_summary=False,
        )

    pending = dispatcher.get_pending_launch(launch["details"]["launch_id"])
    assert pending["failure_detail"] is None
    assert dispatcher.list_terminal_launches(terminal_id) == []


@pytest.mark.parametrize(("outcome", "expected_status", "expected_code"), [
    ("abnormal", "abnormal_exit", 7), ("spawn", "spawn_failed", 1),
])
def test_provider_failure_outcomes_are_recorded_distinctly(tmp_path: Path, monkeypatch, outcome, expected_status, expected_code) -> None:
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register(gui="GUI", name="Agent", provider="codex", session_id="exact-session", apply=True)
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)
    monkeypatch.setattr(dispatcher_cli, "_native_argv", lambda *_args, **_kwargs: ["fake-codex", "resume"])

    def fake_run(argv, **_kwargs):
        if Path(str(argv[0])).name.casefold() in {"git", "git.exe"}:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if outcome == "spawn":
            raise FileNotFoundError("fake provider missing")
        return subprocess.CompletedProcess(argv, expected_code)

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    if outcome == "spawn":
        with pytest.raises(ContinuityError, match="Failed to launch"):
            dispatcher_cli._run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                                     input_stream=io.StringIO(), output_stream=io.StringIO(), show_summary=False)
    else:
        result = dispatcher_cli._run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                                          input_stream=io.StringIO(), output_stream=io.StringIO(), show_summary=False)
        assert result == expected_code

    [record] = dispatcher.list_terminal_launches(terminal_id)
    assert record["status"] == expected_status
    assert record["exit_code"] == expected_code


def test_interrupted_interactive_provider_is_recorded_as_interrupted(tmp_path: Path, monkeypatch) -> None:
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register(gui="GUI", name="Agent", provider="codex", session_id="exact-session", apply=True)
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)
    monkeypatch.setattr(dispatcher_cli, "_native_argv", lambda *_args, **_kwargs: ["fake-codex", "resume"])

    def fake_run(argv, **_kwargs):
        if Path(str(argv[0])).name.casefold() in {"git", "git.exe"}:
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise KeyboardInterrupt

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", fake_run)
    with pytest.raises(KeyboardInterrupt):
        dispatcher_cli._run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                                 input_stream=io.StringIO(), output_stream=io.StringIO(), show_summary=False)

    [record] = dispatcher.list_terminal_launches(terminal_id)
    assert record["status"] == "interrupted"
    assert record["exit_code"] == 130


@pytest.mark.parametrize("conflict", ["lock", "stale-selection"])
def test_lock_or_stale_selection_preflight_does_not_record_launch(tmp_path: Path, monkeypatch, conflict) -> None:
    dispatcher = DispatcherService(home_dir=tmp_path / "registry")
    dispatcher.register(gui="GUI", name="Agent", provider="codex", session_id="selected-session", apply=True)
    slot = dispatcher.get_slot(gui="GUI", name="Agent")
    terminal_id = str(uuid4())
    monkeypatch.setenv("TERMINAL_SESSION_ID", terminal_id)

    def prepare_argv(*_args, **_kwargs):
        if conflict == "stale-selection":
            dispatcher.attach_session(gui="GUI", name="Agent", provider="codex",
                                      session_id="competing-session", apply=True)
        return ["fake-codex", "resume"]

    monkeypatch.setattr(dispatcher_cli, "_native_argv", prepare_argv)
    if conflict == "lock":
        class ConflictingLock:
            def __enter__(self):
                raise ContinuityError(ErrorCode.INVALID_INPUT, "fake runtime lock conflict")

            def __exit__(self, *_args):
                return False

        monkeypatch.setattr(dispatcher_cli, "_session_runtime_lock", lambda *_args, **_kwargs: ConflictingLock())
    with pytest.raises(ContinuityError):
        dispatcher_cli._run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                                 input_stream=io.StringIO(), output_stream=io.StringIO(), show_summary=False)

    assert dispatcher.list_terminal_launches(terminal_id) == []


def test_last_text_output_shows_exact_session_git_and_cwd_provenance() -> None:
    output = io.StringIO()
    dispatcher_cli._render_terminal_launches([{
        "launch_started_at": "2026-11-24T12:00:00Z", "status": "exited",
        "gui_alias": "Requested GUI", "slot_name": "Requested agent", "provider": "agy",
        "native_session_id": "exact-session-123", "environment_id": "wsl:Ubuntu",
        "requested_cwd": "/requested/tree", "effective_cwd": "/effective/tree",
        "native_cwd": "/native/tree", "git_repository": "/repo",
        "git_worktree": "/repo/worktree-review", "git_branch": "review-branch",
        "git_commit": "a" * 40,
    }], output, show_terminal_id=False)

    rendered = output.getvalue()
    for expected in (
        "Requested GUI", "Requested agent", "AGY", "exact-session-123", "wsl:Ubuntu",
        "/requested/tree", "/effective/tree", "/native/tree", "/repo/worktree-review",
        "review-branch", "a" * 40,
    ):
        assert expected in rendered


def test_last_text_output_marks_unavailable_provenance_explicitly() -> None:
    output = io.StringIO()
    dispatcher_cli._render_terminal_launches([{
        "launch_started_at": "2026-11-24T12:00:00Z", "status": "launching",
        "gui_alias": "GUI", "slot_name": "Agent", "provider": "codex",
        "native_session_id": None, "environment_id": "windows", "requested_cwd": None,
        "effective_cwd": None, "native_cwd": None, "git_repository": None,
        "git_worktree": None, "git_branch": None, "git_commit": None,
    }], output, show_terminal_id=False)

    rendered = output.getvalue()
    assert "session ID not captured" not in rendered
    assert "unavailable" in rendered.casefold()
