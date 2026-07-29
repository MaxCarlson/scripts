from __future__ import annotations

import json

import pytest

from rrbackup.snapshots import (
    BackupSummary,
    latest_snapshot,
    parse_backup_json_lines,
    parse_snapshots_json,
)


def snapshot_payload(snapshot_id, time, *, tags=None, hostname="Xeres"):
    return {
        "id": snapshot_id,
        "short_id": snapshot_id[:8],
        "time": time,
        "hostname": hostname,
        "username": "XERES\\mcarls",
        "paths": ["C:\\", "D:\\Pictures"],
        "tags": tags or [],
        "parent": None,
        "program_version": "restic 0.18.1",
    }


def test_parse_snapshots_json_sorts_and_normalizes():
    payload = [
        snapshot_payload("bbbbbbbb2222", "2026-04-14T21:41:15-07:00", tags=["local-main"]),
        snapshot_payload("aaaaaaaa1111", "2026-04-11T22:09:38-07:00"),
    ]

    records = parse_snapshots_json(json.dumps(payload))

    assert [record.short_id for record in records] == ["aaaaaaaa", "bbbbbbbb"]
    assert records[-1].tags == ("local-main",)
    assert records[-1].paths == ("C:\\", "D:\\Pictures")
    assert records[-1].to_dict()["program_version"] == "restic 0.18.1"


def test_parse_snapshots_requires_array_and_required_fields():
    with pytest.raises(ValueError, match="array"):
        parse_snapshots_json("{}")
    with pytest.raises(ValueError, match="id"):
        parse_snapshots_json([{"time": "2026-01-01T00:00:00Z"}])
    with pytest.raises(ValueError, match="time"):
        parse_snapshots_json([{"id": "abc"}])


def test_parse_backup_json_lines_returns_last_summary():
    lines = [
        "not json\n",
        json.dumps({"message_type": "status", "seconds_elapsed": 1}) + "\n",
        json.dumps(
            {
                "message_type": "summary",
                "snapshot_id": "first",
                "files_new": 1,
            }
        )
        + "\n",
        json.dumps(
            {
                "message_type": "summary",
                "snapshot_id": "second",
                "files_new": 20,
                "files_changed": 4,
                "data_added": 100,
                "data_added_packed": 50,
                "total_files_processed": 24,
                "total_bytes_processed": 500,
                "total_duration": 12.5,
            }
        )
        + "\n",
    ]

    summary = parse_backup_json_lines(lines)

    assert summary is not None
    assert summary.snapshot_id == "second"
    assert summary.files_new == 20
    assert summary.files_changed == 4
    assert summary.data_added_packed == 50
    assert summary.total_duration_seconds == 12.5
    assert summary.to_dict()["total_files_processed"] == 24


def test_parse_backup_json_lines_can_be_strict():
    with pytest.raises(json.JSONDecodeError):
        parse_backup_json_lines(["not json"], strict=True)

    with pytest.raises(ValueError, match="object"):
        parse_backup_json_lines(["[]"], strict=True)


def test_parse_backup_json_lines_returns_none_without_summary():
    assert parse_backup_json_lines([json.dumps({"message_type": "status"})]) is None


def test_backup_summary_rejects_wrong_message_type():
    with pytest.raises(ValueError, match="summary"):
        BackupSummary.from_dict({"message_type": "status"})


def test_latest_snapshot_filters_by_tag_and_hostname():
    records = parse_snapshots_json(
        [
            snapshot_payload("a" * 16, "2026-04-11T22:09:38Z", tags=["cloud"]),
            snapshot_payload("b" * 16, "2026-04-14T21:41:15Z", tags=["local-main"]),
            snapshot_payload(
                "c" * 16,
                "2026-04-15T21:41:15Z",
                tags=["local-main"],
                hostname="Other",
            ),
        ]
    )

    assert latest_snapshot(records).short_id == "cccccccc"
    assert latest_snapshot(records, tag="local-main", hostname="Xeres").short_id == "bbbbbbbb"
    assert latest_snapshot(records, tag="missing") is None
