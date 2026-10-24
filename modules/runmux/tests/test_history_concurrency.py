from __future__ import annotations

import json
import multiprocessing
from pathlib import Path


def _write_history_entry(history_path: str, index: int, barrier) -> None:
    from runmux.history import record_run_finished, record_run_started, save_command
    from runmux.models import RunRecord

    run_id = f"20261023-0101{index:02d}-history{index:02d}"
    created_at = "2026-10-23T00:00:00+00:00"
    record = RunRecord(
        id=run_id,
        numeric_id=index,
        name=None,
        status="running",
        created_at=created_at,
        updated_at=created_at,
        started_at=created_at,
        ended_at=None,
        exit_code=None,
        pid=10000 + index,
        supervisor_pid=20000 + index,
        program="python",
        argv_json=json.dumps(["python", "-c", "print('same command')"]),
        cwd="C:/isolated/project",
        env_overrides_json="{}",
        port=30000 + index,
        auth_token="test-token",
        log_path=f"C:/isolated/{run_id}/output.ansi",
        command_line="python -c print('same command')",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )
    barrier.wait(timeout=20)
    path = Path(history_path)
    record_run_started(record, path=path)
    record_run_finished(run_id, status="finished", runtime_seconds=1.0, exit_code=0, path=path)
    save_command(
        argv=["python", "-c", "print('same command')"],
        command_line=record.command_line,
        cwd=record.cwd,
        path=path,
    )


def test_concurrent_supervisors_preserve_history_ledger_and_saved_command_updates(tmp_path: Path) -> None:
    from runmux.history import load_data, load_unique_commands

    history_path = tmp_path / "custom" / "commands.json"
    worker_count = 6
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(worker_count)
    processes = [
        context.Process(target=_write_history_entry, args=(str(history_path), index, barrier))
        for index in range(worker_count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join()
        assert process.exitcode == 0

    history = load_data(history_path)
    unique = load_unique_commands(history_path)

    assert len(history["history"]) == worker_count
    assert {item["status"] for item in history["history"]} == {"finished"}
    assert len(history["saved_commands"]) == 1
    assert history["saved_commands"][0]["id"] == 0
    assert len(unique["commands"]) == 1
    assert unique["commands"][0]["run_count"] == worker_count
    assert len(unique["commands"][0]["runs"]) == worker_count
    assert {item["status"] for item in unique["commands"][0]["runs"]} == {"finished"}
