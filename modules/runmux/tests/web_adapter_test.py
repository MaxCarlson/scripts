import json
import sqlite3
from pathlib import Path

import pytest

from runmux.models import RunRecord
from runmux.store import RunNotFoundError, RunStore
from runmux.web_adapter import ReadOnlyRunmux, read_output_chunk, serialize_run


def create_record(store: RunStore, state_dir: Path, run_id: str, *, status: str = "finished") -> RunRecord:
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"")
    return store.create_run(
        run_id=run_id,
        name="private label",
        status=status,
        program=r"C:\tools\worker.exe",
        argv_json=json.dumps([r"C:\tools\worker.exe", "--password", "do-not-disclose"]),
        cwd=r"C:\private\working-directory",
        env_overrides_json=json.dumps({"TOKEN": "env-secret"}),
        auth_token="ipc-secret",
        log_path=log_path,
        command_line=r"C:\tools\worker.exe --password do-not-disclose",
    )


def test_read_only_registry_lists_and_resolves_full_ids_without_disclosing_secrets(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    active_id = "20261023-123456-a1b2c3"
    finished_id = "20261022-123456-d4e5f6"
    create_record(store, state_dir, active_id, status="running")
    create_record(store, state_dir, finished_id)
    before_files = sorted(path.name for path in state_dir.iterdir())
    before_values = sqlite3.connect(state_dir / "registry.sqlite3").execute(
        "SELECT id, status, updated_at FROM runs ORDER BY id"
    ).fetchall()

    browser = ReadOnlyRunmux(state_dir)
    records = browser.list_runs()
    record = browser.get_run(active_id)
    payload = serialize_run(record)

    after_values = sqlite3.connect(state_dir / "registry.sqlite3").execute(
        "SELECT id, status, updated_at FROM runs ORDER BY id"
    ).fetchall()
    assert [item.id for item in records] == [active_id, finished_id]
    assert record.id == active_id
    assert payload["command"] == "worker.exe"
    assert payload["status"] == "running"
    assert payload["name"] == "private label"
    sensitive_fields = {"argv_json", "cwd", "env_overrides_json", "auth_token", "log_path", "command_line", "port"}
    assert not sensitive_fields & payload.keys()
    assert before_values == after_values
    assert before_files == sorted(path.name for path in state_dir.iterdir())


def test_browser_requires_stable_full_run_id(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    full_id = "20261023-123456-a1b2c3"
    create_record(store, state_dir, full_id)
    browser = ReadOnlyRunmux(state_dir)

    with pytest.raises(RunNotFoundError):
        browser.get_run(full_id[:12])
    with pytest.raises(RunNotFoundError):
        browser.get_run("0")


def test_missing_registry_is_reported_as_empty_without_initializing_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "not-created"
    assert ReadOnlyRunmux(state_dir).list_runs() == []
    assert not state_dir.exists()


def test_status_refresh_is_transient_and_uses_status_ipc_only(tmp_path: Path, monkeypatch) -> None:
    import runmux.web_adapter as web_adapter

    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    run_id = "20261023-123456-a1b2c3"
    create_record(store, state_dir, run_id, status="running")
    store.update_run(run_id, port=43123, pid=9001, supervisor_pid=9002)
    before = store.get_run(run_id)
    operations: list[str] = []

    def request_json(_record, *, op: str, timeout: float):
        operations.append(op)
        return {"status": "finished", "exit_code": 7, "pid": None}

    monkeypatch.setattr(web_adapter, "request_json", request_json)
    refreshed, connection = ReadOnlyRunmux(state_dir).refresh_display_status(store.get_run(run_id))

    assert refreshed.status == "finished"
    assert refreshed.exit_code == 7
    assert connection == "connected"
    assert operations == ["status"]
    assert store.get_run(run_id) == before


def test_log_chunks_preserve_split_utf8_and_detect_truncation_and_rotation(tmp_path: Path) -> None:
    run_id = "20261023-123456-a1b2c3"
    state_dir = tmp_path / "state"
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"prefix\xe2")
    first = read_output_chunk(log_path, state_dir=state_dir, run_id=run_id, max_bytes=32)
    assert first.text == "prefix"
    assert first.reset is True
    log_path.write_bytes(b"prefix\xe2\x82\xac plus\n")
    second = read_output_chunk(
        log_path,
        state_dir=state_dir,
        run_id=run_id,
        cursor=first.cursor,
        max_bytes=32,
    )
    assert second.text.encode("utf-8").hex() == "e282ac20706c75730a"
    assert second.reset is False

    log_path.write_bytes(b"short again\n")
    reset = read_output_chunk(log_path, state_dir=state_dir, run_id=run_id, cursor=second.cursor, max_bytes=32)
    assert reset.reset is True
    assert reset.text == "short again\n"
    assert len(reset.text.encode("utf-8")) <= 32

    replacement = run_dir / "replacement.tmp"
    replacement.write_bytes(b"rotated output\n")
    replacement.replace(log_path)
    rotated = read_output_chunk(log_path, state_dir=state_dir, run_id=run_id, cursor=reset.cursor, max_bytes=32)
    assert rotated.reset is True
    assert rotated.text == "rotated output\n"


def test_completed_log_defers_utf8_finalization_until_eof(tmp_path: Path) -> None:
    run_id = "20261023-123456-a1b2c3"
    state_dir = tmp_path / "state"
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"A")
    initial = read_output_chunk(log_path, state_dir=state_dir, run_id=run_id, max_bytes=4)
    log_path.write_bytes(b"ABC\xe2\x82\xacDEFG")

    first = read_output_chunk(
        log_path,
        state_dir=state_dir,
        run_id=run_id,
        cursor=initial.cursor,
        max_bytes=4,
        finished=True,
    )
    second = read_output_chunk(
        log_path,
        state_dir=state_dir,
        run_id=run_id,
        cursor=first.cursor,
        max_bytes=4,
        finished=True,
    )
    final = read_output_chunk(
        log_path,
        state_dir=state_dir,
        run_id=run_id,
        cursor=second.cursor,
        max_bytes=4,
        finished=True,
    )

    assert first.text == "BC"
    assert first.at_end is False
    assert second.text == "€D"
    assert second.at_end is False
    assert final.text == "EFG"
    assert final.at_end is True


def test_log_reader_enforces_owned_path_and_reports_missing_files(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = RunStore(state_dir)
    run_id = "20261023-123456-a1b2c3"
    record = create_record(store, state_dir, run_id)
    assert read_output_chunk(Path(record.log_path), state_dir=state_dir, run_id=run_id).state == "available"
    assert read_output_chunk(
        Path("runs") / run_id / "output.ansi",
        state_dir=state_dir,
        run_id=run_id,
    ).state == "available"

    with pytest.raises(ValueError, match="selected run"):
        read_output_chunk(tmp_path / "outside.log", state_dir=state_dir, run_id=run_id)

    Path(record.log_path).unlink()
    missing = read_output_chunk(Path(record.log_path), state_dir=state_dir, run_id=run_id)
    assert missing.state == "missing"
    assert "output.ansi" not in missing.message


def test_log_reader_resolves_paths_stored_from_relative_state_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    state_dir = Path("relative-state")
    store = RunStore(state_dir)
    run_id = "20261023-123456-a1b2c3"
    record = create_record(store, state_dir, run_id)

    chunk = read_output_chunk(
        Path(record.log_path),
        state_dir=state_dir.resolve(),
        run_id=run_id,
    )

    assert chunk.state == "available"
