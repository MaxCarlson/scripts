from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from runmux.constants import STATUS_FINISHED, STATUS_PAUSED, STATUS_PENDING, STATUS_RUNNING
from runmux.history import save_command
from runmux.ipc import IpcError
from runmux.store import RunStore
from runmux.tui_adapter import RunmuxTuiAdapter


def _create_run(store: RunStore, run_id: str, status: str, *, port: int | None = None) -> None:
    run_dir = store.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"")
    store.create_run(
        run_id=run_id,
        name=None,
        status=status,
        program="python",
        argv_json=json.dumps(["python", "-c", "print('hello')"]),
        cwd=str(Path.cwd()),
        env_overrides_json="{}",
        auth_token="test-token",
        log_path=log_path,
        command_line="python -c print('hello')",
    )
    if port is not None:
        store.update_run(run_id, port=port, supervisor_pid=12345)


def test_list_runs_includes_active_and_terminal_without_pruning(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    _create_run(store, "20261023-010101-active1", STATUS_RUNNING)
    _create_run(store, "20261023-010102-paused1", STATUS_PAUSED)
    _create_run(store, "20261023-010103-done01", STATUS_FINISHED)
    adapter = RunmuxTuiAdapter(store, tmp_path / "history.json")

    before = [(record.id, record.status, record.numeric_id) for record in store.list_runs()]
    records = adapter.list_runs()
    after = [(record.id, record.status, record.numeric_id) for record in store.list_runs()]

    assert {record.status for record in records} == {STATUS_RUNNING, STATUS_PAUSED, STATUS_FINISHED}
    assert before == after
    assert [record.id for record in records] == [record.id for record in store.list_runs()]


def test_full_ids_remain_authoritative_when_numeric_ids_are_reused(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    first_id = "20261023-010101-first1"
    replacement_id = "20261023-010102-next01"
    _create_run(store, first_id, STATUS_FINISHED)
    first_numeric_id = store.get_run(first_id).numeric_id
    store.remove_run(first_id)
    _create_run(store, replacement_id, STATUS_RUNNING)
    adapter = RunmuxTuiAdapter(store, tmp_path / "history.json")

    records = adapter.list_runs()

    assert store.get_run(replacement_id).numeric_id == first_numeric_id
    assert [record.id for record in records] == [replacement_id]
    assert adapter.get_run(replacement_id).id == replacement_id


def test_refresh_display_status_projects_supervisor_state_without_registry_write(
    tmp_path: Path, monkeypatch
) -> None:
    store = RunStore(tmp_path)
    run_id = "20261023-010101-running1"
    _create_run(store, run_id, STATUS_PENDING, port=45678)
    stored = store.get_run(run_id)
    adapter = RunmuxTuiAdapter(store, tmp_path / "history.json")

    monkeypatch.setattr(
        "runmux.tui_adapter.request_json",
        lambda record, *, op, timeout: {"ok": True, "status": STATUS_RUNNING, "pid": 23456},
    )
    displayed = adapter.refresh_display_status(stored)

    assert displayed.status == STATUS_RUNNING
    assert displayed.pid == 23456
    assert store.get_run(run_id) == stored


def test_refresh_display_status_marks_unresponsive_dead_supervisor_lost_transiently(
    tmp_path: Path, monkeypatch
) -> None:
    store = RunStore(tmp_path)
    run_id = "20261023-010101-lost001"
    _create_run(store, run_id, STATUS_RUNNING, port=45678)
    store.update_run(run_id, supervisor_pid=987654)
    stored = store.get_run(run_id)
    adapter = RunmuxTuiAdapter(store, tmp_path / "history.json")

    def unavailable(*args, **kwargs):
        raise IpcError("offline")

    monkeypatch.setattr("runmux.tui_adapter.request_json", unavailable)
    monkeypatch.setattr("runmux.tui_adapter.is_pid_alive", lambda pid: False)
    displayed = adapter.refresh_display_status(stored)

    assert displayed.status == "lost"
    assert store.get_run(run_id) == stored


def test_refresh_display_status_keeps_status_when_unresponsive_supervisor_may_be_alive(
    tmp_path: Path, monkeypatch
) -> None:
    store = RunStore(tmp_path)
    run_id = "20261023-010101-pending1"
    _create_run(store, run_id, STATUS_PENDING, port=45678)
    store.update_run(run_id, supervisor_pid=987654)
    stored = store.get_run(run_id)
    adapter = RunmuxTuiAdapter(store, tmp_path / "history.json")

    def unavailable(*args, **kwargs):
        raise IpcError("offline")

    monkeypatch.setattr("runmux.tui_adapter.request_json", unavailable)
    monkeypatch.setattr("runmux.tui_adapter.is_pid_alive", lambda pid: True)
    displayed = adapter.refresh_display_status(stored)

    assert displayed == stored
    assert store.get_run(run_id) == stored


def test_launch_preserves_argv_order_tokens_and_cwd(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path / "registry")
    existing_id = "20261023-010101-existing1"
    _create_run(store, existing_id, STATUS_RUNNING)
    record = store.get_run(existing_id)
    argv = ["python", "script with spaces.py", "--label", "two words", "--", "--literal"]
    cwd = tmp_path / "working directory"
    captured: dict[str, object] = {}

    def fake_create_managed_run(store_arg, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(record=record)

    monkeypatch.setattr("runmux.tui_adapter.create_managed_run", fake_create_managed_run)
    adapter = RunmuxTuiAdapter(store, tmp_path / "state" / "commands.json")

    assert adapter.launch(argv, cwd=cwd, name="my process") == record
    assert captured["program_args"] == argv
    assert captured["cwd"] == cwd
    assert captured["name"] == "my process"


def test_saved_commands_and_history_use_adapter_custom_state_path(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "registry")
    run_id = "20261023-010101-custom01"
    _create_run(store, run_id, STATUS_RUNNING)
    custom_history = tmp_path / "registry" / "commands.json"
    adapter = RunmuxTuiAdapter(store, custom_history)
    save_command(
        argv=["python", "custom script.py"],
        command_line="python custom script.py",
        cwd=str(tmp_path),
        path=custom_history,
    )

    commands = adapter.saved_commands()

    assert len(commands) == 1
    assert commands[0].argv == ["python", "custom script.py"]
    assert (tmp_path / "commands.json").exists() is False


def test_lifecycle_adapter_calls_keep_full_run_id(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261023-010101-stable01"
    _create_run(store, run_id, STATUS_RUNNING)
    adapter = RunmuxTuiAdapter(store, tmp_path / "history.json")
    observed: list[tuple[str, str, bool | None]] = []

    def fake_action(name: str, *, run_id: str, **kwargs):
        observed.append((name, run_id, kwargs.get("force")))
        record = store.get_run(run_id)
        return SimpleNamespace(record=record) if name in {"restart_run", "duplicate_run"} else record

    for name in ("kill_run", "pause_run", "resume_run", "restart_run", "duplicate_run", "remove_run"):
        def _patch_action(store_arg, *, run_id, _name=name, **kwargs):
            return fake_action(_name, run_id=run_id, **kwargs)

        monkeypatch.setattr(f"runmux.tui_adapter.{name}", _patch_action)

    adapter.kill(run_id, force=True)
    adapter.pause(run_id)
    adapter.resume(run_id)
    adapter.restart(run_id)
    adapter.duplicate(run_id)

    assert [item[1] for item in observed] == [run_id] * 5
    assert observed[0] == ("kill_run", run_id, True)


def test_remove_terminal_rejects_active_record(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path)
    run_id = "20261023-010101-active01"
    _create_run(store, run_id, STATUS_RUNNING)
    adapter = RunmuxTuiAdapter(store, tmp_path / "history.json")
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("runmux.tui_adapter.remove_run", forbidden)

    try:
        adapter.remove_terminal(run_id)
    except ValueError as error:
        assert "not terminal" in str(error)
    else:
        raise AssertionError("active process removal should be rejected")
    assert called is False

