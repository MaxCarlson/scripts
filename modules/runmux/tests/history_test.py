from __future__ import annotations

import json
from pathlib import Path

from runmux.history import (
    command_stats,
    history_entries,
    record_run_finished,
    record_run_started,
    save_command,
    saved_bases,
)
from runmux.models import RunRecord


def make_record(tmp_path: Path) -> RunRecord:
    return RunRecord(
        id="20260611-010101-abcdef",
        numeric_id=0,
        name=None,
        status="running",
        created_at="2026-06-11T00:00:00+00:00",
        updated_at="2026-06-11T00:00:00+00:00",
        started_at="2026-06-11T00:00:00+00:00",
        ended_at=None,
        exit_code=None,
        pid=123,
        supervisor_pid=456,
        program="ytaedl",
        argv_json=json.dumps(["ytaedl", "run", "urls.txt"]),
        cwd=str(tmp_path),
        env_overrides_json="{}",
        port=999,
        auth_token="token",
        log_path=str(tmp_path / "output.ansi"),
        command_line="ytaedl run urls.txt",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )


def test_history_records_start_and_finish(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    record = make_record(tmp_path)

    record_run_started(record, path=path)
    record_run_finished(record.id, status="finished", runtime_seconds=12.5, path=path)

    entries = history_entries(path)
    assert entries[0]["base"] == "ytaedl"
    assert entries[0]["runtime_seconds"] == 12.5
    assert entries[0]["status"] == "finished"


def test_saved_bases_and_command_stats(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    record = make_record(tmp_path)
    record_run_started(record, path=path)
    record_run_finished(record.id, status="finished", runtime_seconds=10.0, path=path)
    saved = save_command(
        argv=["ytaedl", "run", "urls.txt"],
        command_line="ytaedl run urls.txt",
        cwd=str(tmp_path),
        path=path,
    )

    stats = command_stats(path)

    assert saved.id == 0
    assert saved_bases(path) == ["ytaedl"]
    assert stats["base_counts"] == {"ytaedl": 1}
    assert stats["saved"][0]["run_count"] == 1
    assert stats["saved"][0]["average_runtime_seconds"] == 10.0
