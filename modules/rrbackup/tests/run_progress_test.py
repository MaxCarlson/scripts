from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rrbackup.run_progress import BackupProgress, parse_progress_line


UTC = timezone.utc
NOW = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)


def test_parse_progress_line_normalizes_status_and_estimates_speed() -> None:
    progress = parse_progress_line(
        '{"message_type":"status","seconds_elapsed":20,"percent_done":0.25,'
        '"total_files":400,"files_done":100,"total_bytes":1000,"bytes_done":250,'
        '"current_files":["/C/example.bin"]}',
        now=NOW,
    )

    assert progress is not None
    assert progress.percent_display == pytest.approx(25.0)
    assert progress.bytes_per_second == pytest.approx(12.5)
    assert progress.eta_seconds == pytest.approx(60.0)
    assert progress.current_files == ("/C/example.bin",)
    assert progress.to_dict()["updated_utc"] == NOW.isoformat()


def test_progress_mapping_rejects_non_status_and_invalid_values() -> None:
    assert BackupProgress.from_mapping({"message_type": "summary"}, now=NOW) is None
    assert BackupProgress.from_mapping(
        {"message_type": "status", "seconds_elapsed": "invalid"},
        now=NOW,
    ) is None
    assert parse_progress_line("not-json", now=NOW) is None
    assert parse_progress_line("[]", now=NOW) is None


def test_eta_is_unknown_until_speed_and_total_are_available() -> None:
    progress = BackupProgress(
        seconds_elapsed=0,
        percent_done=0,
        total_files=0,
        files_done=0,
        total_bytes=0,
        bytes_done=0,
        current_files=tuple(),
        updated_utc=NOW,
    )

    assert progress.bytes_per_second == 0
    assert progress.eta_seconds is None
