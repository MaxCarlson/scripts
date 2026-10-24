from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from runmux.constants import STATUS_RUNNING
from runmux.ipc import IpcError
from runmux.runner import kill_run
from runmux.store import RunStore
from runmux.tui import RunmuxTuiApp
from runmux.tui_adapter import RunmuxTuiAdapter
from runmux.workspace_state import WorkspaceState, WorkspaceStateStore


def _create_run(store: RunStore, run_id: str) -> str:
    run_dir = store.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"first line\nsecond line\n")
    store.create_run(
        run_id=run_id,
        name=None,
        status=STATUS_RUNNING,
        program="python",
        argv_json=json.dumps(["python", "-c", "pass"]),
        cwd=str(Path.cwd()),
        env_overrides_json="{}",
        auth_token="test-token",
        log_path=log_path,
        command_line="python -c pass",
    )
    return run_id


def _app(tmp_path: Path) -> tuple[RunmuxTuiApp, RunStore, WorkspaceStateStore]:
    store = RunStore(tmp_path / "registry")
    state_store = WorkspaceStateStore(tmp_path / "registry", tmp_path / "project")
    app = RunmuxTuiApp(RunmuxTuiAdapter(store, tmp_path / "history.json"), state_store)
    return app, store, state_store


def test_historical_runs_are_not_automatically_opened(tmp_path: Path) -> None:
    app, store, _ = _app(tmp_path)
    _create_run(store, "20261023-010101-historic1")

    app.restore_workspace()

    assert app.open_run_ids == []
    app.close()


def test_open_close_and_quit_never_call_process_lifecycle_operations(tmp_path: Path, monkeypatch) -> None:
    app, store, _ = _app(tmp_path)
    run_id = _create_run(store, "20261023-010101-managed1")
    calls: list[str] = []
    lifecycle_names = (
        "create_managed_run", "kill_run", "pause_run", "resume_run", "restart_run", "duplicate_run", "remove_run"
    )
    for name in lifecycle_names:
        monkeypatch.setattr(f"runmux.runner.{name}", lambda *args, _name=name, **kwargs: calls.append(_name))
        monkeypatch.setattr(f"runmux.tui_adapter.{name}", lambda *args, _name=name, **kwargs: calls.append(_name))

    app.open_view(run_id)
    app.close_view(run_id)
    app.open_view(run_id)
    app.close_all_views()
    app.open_view(run_id)
    app.quit(save_layout=False)

    assert calls == []
    assert store.get_run(run_id).status == STATUS_RUNNING


def test_workspace_restart_restores_only_valid_full_ids_and_scroll_offsets(tmp_path: Path) -> None:
    app, store, state_store = _app(tmp_path)
    first = _create_run(store, "20261023-010101-first001")
    second = _create_run(store, "20261023-010102-second01")
    state_store.save(
        WorkspaceState(
            open_run_ids=[first, second, "20261023-010103-removed1"],
            active_run_id=second,
            scroll_offsets={first: 7, second: 0},
        )
    )

    app.restore_workspace()

    assert app.open_run_ids == [first, second]
    assert app.active_run_id == second
    assert app.views[first].viewport.scroll_offset == 7
    app.close()


def test_tabs_keep_independent_viewport_state_and_full_identity(tmp_path: Path) -> None:
    app, store, _ = _app(tmp_path)
    first = _create_run(store, "20261023-010101-view001")
    second = _create_run(store, "20261023-010102-view002")

    app.open_view(first)
    app.open_view(second)
    app.views[first].viewport.scroll_offset = 4
    app.views[second].viewport.scroll_offset = 9
    app.activate_view(first)

    assert app.active_run_id == first
    assert app.views[first].record.id == first
    assert app.views[first].viewport.scroll_offset == 4
    assert app.views[second].viewport.scroll_offset == 9
    app.close()


def test_quit_saves_layout_only_when_requested(tmp_path: Path) -> None:
    app, store, state_store = _app(tmp_path)
    run_id = _create_run(store, "20261023-010101-save001")
    app.open_view(run_id)
    app.quit(save_layout=True)

    assert state_store.load().open_run_ids == [run_id]
    assert store.get_run(run_id).status == STATUS_RUNNING


def test_browser_is_searchable_and_navigable_by_full_record(tmp_path: Path) -> None:
    app, store, _ = _app(tmp_path)
    first = _create_run(store, "20261023-010101-match001")
    _create_run(store, "20261023-010102-other001")
    app.refresh_browser()

    app.set_search("match")

    assert [record.id for record in app.visible_runs] == [first]
    app.open_selected()
    assert app.active_run_id == first
    app.close()


def test_pane_capture_exports_raw_ansi_log_and_follows_new_output(tmp_path: Path) -> None:
    app, store, _ = _app(tmp_path)
    run_id = _create_run(store, "20261023-010101-capture1")
    app.open_view(run_id)
    destination = tmp_path / "exports" / "pane output.ansi"

    app.capture_output(run_id, destination)
    deadline = time.monotonic() + 1
    while (
        not destination.exists()
        or destination.stat().st_size < store.get_run(run_id).log_file.stat().st_size
    ) and time.monotonic() < deadline:
        time.sleep(0.005)
    with store.get_run(run_id).log_file.open("ab") as stream:
        stream.write(b"\x1b[32mnew output\x1b[0m\n")
    deadline = time.monotonic() + 1
    while destination.stat().st_size < store.get_run(run_id).log_file.stat().st_size and time.monotonic() < deadline:
        time.sleep(0.005)

    assert destination.read_bytes() == store.get_run(run_id).log_file.read_bytes()
    app.close()


def test_curses_exception_cleanup_leaves_managed_process_running(tmp_path: Path, monkeypatch) -> None:
    app, store, state_store = _app(tmp_path)
    run_id = _create_run(store, "20261023-010101-except01")
    state_store.save(WorkspaceState(open_run_ids=[run_id], active_run_id=run_id))

    def fail_wrapper(callback):
        raise RuntimeError("terminal failed")

    monkeypatch.setattr("runmux.tui.curses.wrapper", fail_wrapper)
    try:
        app.run()
    except RuntimeError as error:
        assert str(error) == "terminal failed"
    else:
        raise AssertionError("expected injected curses failure")

    assert store.get_run(run_id).status == STATUS_RUNNING


def test_kill_hotkey_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    app, store, _ = _app(tmp_path)
    run_id = _create_run(store, "20261023-010101-confirm01")
    app.open_view(run_id)
    submissions: list[tuple[str, bool]] = []
    monkeypatch.setattr(app, "_confirm", lambda screen, prompt: False)
    monkeypatch.setattr(
        app.actions,
        "submit",
        lambda kind, action, *, open_view=False: submissions.append((kind, open_view)),
    )

    app._handle_key(None, "k")

    assert submissions == []
    assert store.get_run(run_id).status == STATUS_RUNNING
    app.close()


def test_kill_hotkey_dispatches_only_after_confirmation(tmp_path: Path, monkeypatch) -> None:
    app, store, _ = _app(tmp_path)
    run_id = _create_run(store, "20261023-010101-killok01")
    app.open_view(run_id)
    submissions: list[tuple[str, bool]] = []
    monkeypatch.setattr(app, "_confirm", lambda screen, prompt: True)
    monkeypatch.setattr(
        app.actions,
        "submit",
        lambda kind, action, *, open_view=False: submissions.append((kind, open_view)),
    )

    app._handle_key(None, "k")

    assert submissions == [("kill", False)]
    assert store.get_run(run_id).status == STATUS_RUNNING
    app.close()


def test_terminal_record_removal_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    app, store, _ = _app(tmp_path)
    run_id = _create_run(store, "20261023-010101-removal1")
    store.update_run(run_id, status="finished")
    app.open_view(run_id)
    submissions: list[str] = []
    monkeypatch.setattr(app, "_confirm", lambda screen, prompt: False)
    monkeypatch.setattr(app.actions, "submit", lambda kind, action, **kwargs: submissions.append(kind))

    app._handle_key(None, "z")

    assert submissions == []
    assert run_id in app.views
    assert store.get_run(run_id).status == "finished"
    app.close()


def test_interactive_attach_handoff_preserves_view_state_and_restores_tui(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path / "registry")
    run_id = _create_run(store, "20261023-010101-attach01")
    root = tmp_path / "project"
    root.mkdir()
    run_states = []
    attached: list[tuple[RunStore, str, int | None]] = []

    def fake_run(app, *, initial_state=None):
        run_states.append(initial_state)
        if len(run_states) == 1:
            app.open_view(run_id)
            app.views[run_id].viewport.scroll_offset = 6
            assert app.request_attach(run_id) is True
            app.handoff_state = app.workspace_snapshot()
            app.close()
            return run_id
        assert initial_state is not None
        assert initial_state.open_run_ids == [run_id]
        assert initial_state.scroll_offsets[run_id] == 6
        app.close()
        return None

    def fake_interact(store_arg, *, run_id: str, tail_lines: int | None):
        attached.append((store_arg, run_id, tail_lines))

    monkeypatch.setattr("runmux.tui.RunmuxTuiApp.run", fake_run)
    monkeypatch.setattr("runmux.tui.interact_run", fake_interact)

    from runmux.tui import run_tui

    assert run_tui(store, history_path=tmp_path / "registry" / "commands.json", root_dir=root) == 0
    assert attached == [(store, run_id, None)]
    assert len(run_states) == 2


def test_interactive_attach_ipc_failure_returns_to_tui(tmp_path: Path, monkeypatch) -> None:
    store = RunStore(tmp_path / "registry")
    run_id = _create_run(store, "20261023-010101-attacherr")
    root = tmp_path / "project"
    root.mkdir()
    statuses: list[str] = []

    def fake_run(app, *, initial_state=None):
        statuses.append(app.status_message)
        if len(statuses) == 1:
            app.open_view(run_id)
            app.request_attach(run_id)
            app.handoff_state = app.workspace_snapshot()
            app.close()
            return run_id
        app.close()
        return None

    def failed_interact(*args, **kwargs):
        raise IpcError("input lock unavailable")

    monkeypatch.setattr("runmux.tui.RunmuxTuiApp.run", fake_run)
    monkeypatch.setattr("runmux.tui.interact_run", failed_interact)
    from runmux.tui import run_tui

    assert run_tui(store, history_path=tmp_path / "registry" / "commands.json", root_dir=root) == 0
    assert "Attach ended: input lock unavailable" in statuses[1]


def test_real_managed_process_survives_view_close_and_tui_quit(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "registry")
    adapter = RunmuxTuiAdapter(store, store.state_dir / "commands.json")
    record = adapter.launch([sys.executable, "-c", "import time; time.sleep(20)"], cwd=tmp_path)
    state_store = WorkspaceStateStore(store.state_dir, tmp_path)
    app = RunmuxTuiApp(adapter, state_store)
    try:
        app.open_view(record.id)
        app.close_view(record.id)
        app.open_view(record.id)
        app.quit(save_layout=False)

        current = store.get_run(record.id)
        assert current.status in {"pending", "running", "paused"}
        assert current.pid is not None
    finally:
        current = store.get_run(record.id)
        if current.status not in {"finished", "failed", "killed", "lost"}:
            kill_run(store, run_id=record.id, force=True)
