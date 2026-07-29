from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rrbackup.models import (
    InvalidRunTransition,
    RunRecord,
    RunState,
    datetime_from_text,
    datetime_to_text,
    ensure_utc,
)

UTC = timezone.utc
FIXED = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_ensure_utc_handles_naive_and_aware_values():
    naive = datetime(2026, 7, 29, 12, 0)
    assert ensure_utc(naive) == FIXED
    assert ensure_utc(FIXED) == FIXED


def test_datetime_text_round_trip():
    encoded = datetime_to_text(FIXED)
    assert encoded == "2026-07-29T12:00:00+00:00"
    assert datetime_from_text(encoded) == FIXED
    assert datetime_from_text(None) is None


def test_create_run_record_uses_supplied_identity():
    record = RunRecord.create(
        profile="local",
        backup_set="local-main",
        now=FIXED,
        run_id="run-1",
    )

    assert record.run_id == "run-1"
    assert record.state == RunState.QUEUED
    assert record.created_utc == FIXED
    assert not record.is_terminal


def test_transition_sets_start_and_finish_times():
    queued = RunRecord.create(
        profile="local",
        backup_set="local-main",
        now=FIXED,
        run_id="run-1",
    )
    running = queued.transition(
        RunState.RUNNING,
        now=datetime(2026, 7, 29, 12, 1, tzinfo=UTC),
        metadata={"cpu": 12.5},
    )
    success = running.transition(
        RunState.SUCCESS,
        now=datetime(2026, 7, 29, 12, 2, tzinfo=UTC),
        exit_code=0,
        snapshot_id="abcdef12",
    )

    assert running.started_utc == datetime(2026, 7, 29, 12, 1, tzinfo=UTC)
    assert running.metadata == {"cpu": 12.5}
    assert success.started_utc == running.started_utc
    assert success.finished_utc == datetime(2026, 7, 29, 12, 2, tzinfo=UTC)
    assert success.snapshot_id == "abcdef12"
    assert success.is_terminal


def test_invalid_transition_is_rejected():
    record = RunRecord.create(
        profile="local",
        backup_set="local-main",
        now=FIXED,
    )

    with pytest.raises(InvalidRunTransition):
        record.transition(RunState.SUCCESS, now=FIXED)

    running = record.transition(RunState.RUNNING, now=FIXED)
    with pytest.raises(InvalidRunTransition):
        running.transition(RunState.RUNNING, now=FIXED)


def test_terminal_state_cannot_transition_again():
    record = RunRecord.create(
        profile="local",
        backup_set="local-main",
        now=FIXED,
    )
    skipped = record.transition(RunState.SKIPPED, now=FIXED)

    with pytest.raises(InvalidRunTransition):
        skipped.transition(RunState.RUNNING, now=FIXED)


def test_run_record_json_round_trip_is_independent():
    record = RunRecord.create(
        profile="local",
        backup_set="local-main",
        now=FIXED,
        run_id="run-1",
    )
    record.command.extend(["restic", "backup"])
    record.metadata["nested"] = {"value": 1}

    payload = record.to_dict()
    restored = RunRecord.from_dict(payload)
    payload["metadata"]["nested"]["value"] = 2

    assert restored == record
    assert restored.metadata["nested"]["value"] == 1


def test_run_record_requires_created_time():
    with pytest.raises(ValueError, match="created_utc"):
        RunRecord.from_dict(
            {
                "run_id": "run-1",
                "state": "queued",
            }
        )
