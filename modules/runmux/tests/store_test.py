from __future__ import annotations

import json
from pathlib import Path

import pytest

from runmux.store import AmbiguousRunIdError, RunStore


def create_test_run(store: RunStore, run_id: str, command: list[str]) -> None:
    run_dir = store.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"")
    store.create_run(
        run_id=run_id,
        name=None,
        status="pending",
        program=command[0],
        argv_json=json.dumps(command),
        cwd=str(Path.cwd()),
        env_overrides_json=json.dumps({}),
        auth_token="token",
        log_path=log_path,
        command_line=" ".join(command),
    )


def test_store_creates_and_resolves_run_by_full_id(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-abcdef", ["python", "-V"])

    record = store.get_run("20260611-010101-abcdef")

    assert record.id == "20260611-010101-abcdef"
    assert record.status == "pending"
    assert record.program == "python"
    assert record.numeric_id == 0


def test_store_resolves_numeric_id(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-abcdef", ["python", "-V"])

    record = store.get_run("0")

    assert record.id == "20260611-010101-abcdef"


def test_store_reuses_lowest_removed_numeric_id(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-aaaaaa", ["python", "-V"])
    create_test_run(store, "20260611-010102-bbbbbb", ["python", "-V"])
    store.update_run("20260611-010101-aaaaaa", status="finished")

    removed = store.remove_run("0")
    create_test_run(store, "20260611-010103-cccccc", ["python", "-V"])

    assert removed.numeric_id == 0
    assert store.get_run("20260611-010103-cccccc").numeric_id == 0


def test_store_removes_all_terminal_runs_by_default(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-aaaaaa", ["python", "-V"])
    create_test_run(store, "20260611-010102-bbbbbb", ["python", "-V"])
    create_test_run(store, "20260611-010103-cccccc", ["python", "-V"])
    store.update_run("20260611-010101-aaaaaa", status="finished")
    store.update_run("20260611-010102-bbbbbb", status="failed")

    removed = store.remove_finished_runs()

    assert [record.numeric_id for record in removed] == [0, 1]
    assert [record.numeric_id for record in store.list_runs()] == [2]


def test_store_removes_only_clean_finished_runs_when_requested(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-aaaaaa", ["python", "-V"])
    create_test_run(store, "20260611-010102-bbbbbb", ["python", "-V"])
    create_test_run(store, "20260611-010103-cccccc", ["python", "-V"])
    store.update_run("20260611-010101-aaaaaa", status="finished")
    store.update_run("20260611-010102-bbbbbb", status="failed")
    store.update_run("20260611-010103-cccccc", status="running")

    removed = store.remove_finished_runs(clean_only=True)

    assert [record.numeric_id for record in removed] == [0]
    assert sorted(record.numeric_id for record in store.list_runs()) == [1, 2]


def test_store_resolves_unambiguous_prefix(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-abcdef", ["python", "-V"])

    record = store.get_run("20260611-010101")

    assert record.id == "20260611-010101-abcdef"


def test_store_rejects_ambiguous_prefix(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-aaaaaa", ["python", "-V"])
    create_test_run(store, "20260611-010101-bbbbbb", ["python", "-V"])

    with pytest.raises(AmbiguousRunIdError):
        store.get_run("20260611-010101")


def test_store_updates_runtime_status(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-abcdef", ["python", "-V"])

    started = store.mark_started(
        run_id="20260611-010101-abcdef",
        pid=123,
        supervisor_pid=456,
        port=789,
    )
    finished = store.mark_finished(
        run_id="20260611-010101-abcdef",
        status="finished",
        exit_code=0,
    )

    assert started.status == "running"
    assert started.pid == 123
    assert finished.status == "finished"
    assert finished.exit_code == 0
    assert finished.runtime_seconds >= 0


def test_store_tracks_current_and_lifetime_attachments(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-abcdef", ["python", "-V"])

    store.register_attachment(
        run_id="20260611-010101-abcdef",
        session_id="view-1",
        mode="view",
    )
    store.register_attachment(
        run_id="20260611-010101-abcdef",
        session_id="interact-1",
        mode="interact",
    )
    store.set_attachment_lock_state(
        run_id="20260611-010101-abcdef",
        holder_id="interact-1",
        queued_ids=[],
    )

    attached = store.attachment_summary("20260611-010101-abcdef")
    store.disconnect_attachment("view-1")
    detached = store.attachment_summary("20260611-010101-abcdef")

    assert attached.current_viewers == 1
    assert attached.current_interactors == 1
    assert attached.lifetime_connections == 2
    assert attached.lock_held is True
    assert detached.current_viewers == 0
    assert detached.lifetime_viewers == 1


def test_store_does_not_double_count_repeated_session_registration(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    create_test_run(store, "20260611-010101-abcdef", ["python", "-V"])

    for _ in range(2):
        store.register_attachment(
            run_id="20260611-010101-abcdef",
            session_id="view-1",
            mode="view",
        )

    summary = store.attachment_summary("20260611-010101-abcdef")

    assert summary.current_viewers == 1
    assert summary.lifetime_viewers == 1
