from __future__ import annotations

from datetime import datetime, timedelta, timezone

from saved_game_archiver.models import SnapshotManifest
from saved_game_archiver.retention import parse_interval, parse_retention, retained_snapshot_ids, select_gfs_snapshot_ids


def snap(index: int, when: datetime, reason: str = "scheduled", session: str | None = None) -> SnapshotManifest:
    return SnapshotManifest(f"s{index}", "g", when.isoformat(), reason, 0, session, [])


def test_parse_requested_gfs_syntax() -> None:
    policy = parse_retention("24h 7d 4w 12m")
    assert (policy.hourly, policy.daily, policy.weekly, policy.monthly) == (24, 7, 4, 12)


def test_running_interval_minutes_are_distinct_context() -> None:
    assert parse_interval("15m") == 900
    assert parse_interval("2h") == 7200


def test_gfs_keeps_bucket_representatives_not_every_check() -> None:
    now = datetime(2026, 8, 25, 20, tzinfo=timezone.utc)
    manifests = [snap(i, now - timedelta(minutes=10 * i)) for i in range(30)]
    keep = select_gfs_snapshot_ids(manifests, parse_retention("2h 1d 1w 1m"))
    assert len(keep) <= 5
    assert "s0" in keep


def test_in_session_cycles_and_exit_pins_are_preserved() -> None:
    now = datetime(2026, 8, 25, 20, tzinfo=timezone.utc)
    manifests = [
        snap(0, now - timedelta(days=3), "in_session", "session0"),
        snap(1, now - timedelta(days=2), "in_session", "session1"),
        snap(2, now - timedelta(days=1), "in_session", "session2"),
        snap(3, now, "session_exit", "session2"),
    ]
    keep = retained_snapshot_ids(
        manifests,
        policy=parse_retention("1h"),
        in_session_keep_cycles=2,
        exit_snapshot_ids={"s0"},
    )
    assert "s0" in keep
    assert "s1" in keep and "s2" in keep
    assert "s3" in keep
