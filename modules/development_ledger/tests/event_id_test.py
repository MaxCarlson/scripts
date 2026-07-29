from __future__ import annotations

from development_ledger.cli import _event_id


def test_automatic_event_ids_are_unique_for_same_timestamp_and_commit():
    timestamp = "2026-07-29T17:00:00.123456+00:00"
    commit = "abcdef0123456789"

    first = _event_id("run", timestamp, commit)
    second = _event_id("run", timestamp, commit)

    assert first != second
    assert "20260729T170000123456Z" in first
    assert "abcdef01" in first
