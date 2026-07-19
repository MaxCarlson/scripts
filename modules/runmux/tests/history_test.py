from __future__ import annotations

import json
from pathlib import Path

from runmux.history import (
    command_stats,
    filter_history_entries,
    history_entry_by_id,
    history_path_for_state_dir,
    history_entries,
    indexed_history_entries,
    most_common_history_entries,
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
    record_run_finished(record.id, status="finished", runtime_seconds=12.5, exit_code=0, path=path)

    entries = history_entries(path)
    assert entries[0]["base"] == "ytaedl"
    assert entries[0]["runtime_seconds"] == 12.5
    assert entries[0]["status"] == "finished"
    assert entries[0]["exit_code"] == 0


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


def test_indexed_history_is_newest_first_and_filter_preserves_ids(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    data = {
        "history": [
            {"command_line": "python old.py", "argv": ["python", "old.py"]},
            {"command_line": "ytaedl run first", "argv": ["ytaedl", "run", "first"]},
            {"command_line": "python newest.py", "argv": ["python", "newest.py"]},
        ],
        "saved_commands": [],
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    entries = indexed_history_entries(path)
    filtered = filter_history_entries(entries, starts_with="YTAEDL")

    assert [entry["history_id"] for entry in entries] == [0, 1, 2]
    assert entries[0]["command_line"] == "python newest.py"
    assert filtered[0]["history_id"] == 1
    assert history_entry_by_id(1, path)["command_line"] == "ytaedl run first"


def test_contains_and_most_common_use_latest_global_replay_id(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    data = {
        "history": [
            {"command_line": "ytaedl run", "argv": ["ytaedl", "run"]},
            {"command_line": "python task.py", "argv": ["python", "task.py"]},
            {"command_line": "YTAEDL RUN", "argv": ["YTAEDL", "RUN"]},
            {"command_line": "python task.py", "argv": ["python", "task.py"]},
        ],
        "saved_commands": [],
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    matching = filter_history_entries(indexed_history_entries(path), contains="task")
    common = most_common_history_entries(indexed_history_entries(path), count=2)

    assert [entry["history_id"] for entry in matching] == [0, 2]
    assert common[0]["command_line"] == "python task.py"
    assert common[0]["history_id"] == 0
    assert common[0]["occurrence_count"] == 2
    assert common[1]["history_id"] == 1


def test_prefix_and_contains_filters_can_be_combined(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    path.write_text(
        json.dumps(
            {
                "history": [
                    {"command_line": "ytaedl run one", "argv": ["ytaedl", "run", "one"]},
                    {"command_line": "ytaedl archive", "argv": ["ytaedl", "archive"]},
                    {"command_line": "other run", "argv": ["other", "run"]},
                ],
                "saved_commands": [],
            }
        ),
        encoding="utf-8",
    )

    entries = filter_history_entries(indexed_history_entries(path), starts_with="ytaedl", contains="run")

    assert [entry["command_line"] for entry in entries] == ["ytaedl run one"]


def test_internal_probe_entries_are_removed_before_global_ids_are_assigned(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"
    data = {
        "history": [
            {"command_line": "ytaedl run", "cwd": "D:\\work"},
            {"command_line": "python -V", "cwd": str(tmp_path)},
        ],
        "saved_commands": [],
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    entries = indexed_history_entries(path)

    assert len(entries) == 1
    assert entries[0]["history_id"] == 0
    assert entries[0]["command_line"] == "ytaedl run"


def test_custom_state_directory_uses_isolated_history(tmp_path: Path) -> None:
    assert history_path_for_state_dir(tmp_path) == tmp_path.resolve() / "commands.json"


def test_finish_does_not_create_history_for_unrecorded_clone(tmp_path: Path) -> None:
    path = tmp_path / "commands.json"

    record_run_finished("clone-run", status="finished", runtime_seconds=1.0, path=path)

    assert not path.exists()
