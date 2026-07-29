from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from rrbackup.health import HealthSeverity, evaluate_health
from rrbackup.locking import LockInspection
from rrbackup.models import RunRecord, RunState
from rrbackup.policy import CpuPolicy
from rrbackup.profile import BackupProfile
from rrbackup.snapshots import SnapshotRecord


UTC = timezone.utc
NOW = datetime(2026, 7, 29, 16, 0, tzinfo=UTC)


def make_profile(tmp_path: Path) -> BackupProfile:
    password = tmp_path / "password.txt"
    sources = tmp_path / "sources.txt"
    password.write_text("secret", encoding="utf-8")
    sources.write_text("C:\\", encoding="utf-8")
    return BackupProfile(
        name="local-main",
        repository=str(tmp_path / "repo"),
        password_file=str(password),
        sources_file=str(sources),
        excludes_file=None,
        status_file=str(tmp_path / "status.json"),
        log_file=str(tmp_path / "backup.log"),
        lock_file=str(tmp_path / "backup.lock"),
        tag="local-main",
        restic_executable="restic",
        restore_root=str(tmp_path / "restore"),
        cpu_policy=CpuPolicy(overdue_after=timedelta(days=3)),
    )


def missing_lock() -> LockInspection:
    return LockInspection(
        exists=False,
        active=False,
        stale=False,
        valid=True,
        identity=None,
        token=None,
        reason="Lock file does not exist.",
    )


def snapshot(age_days: float) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id="a" * 64,
        short_id="aaaaaaaa",
        time=NOW - timedelta(days=age_days),
        hostname="Xeres",
        tags=("local-main",),
    )


def test_recent_snapshot_with_valid_inputs_is_healthy(tmp_path: Path) -> None:
    report = evaluate_health(
        make_profile(tmp_path),
        snapshots=[snapshot(1)],
        latest_run=None,
        lock=missing_lock(),
        now=NOW,
    )

    assert report.healthy
    assert report.severity == HealthSeverity.OK
    assert report.latest_snapshot is not None


def test_overdue_snapshot_is_critical(tmp_path: Path) -> None:
    report = evaluate_health(
        make_profile(tmp_path),
        snapshots=[snapshot(4)],
        latest_run=None,
        lock=missing_lock(),
        now=NOW,
    )

    assert not report.healthy
    assert report.severity == HealthSeverity.CRITICAL
    issue = next(value for value in report.issues if value.code == "backup-overdue")
    assert issue.details["threshold_seconds"] == 3 * 86400


def test_missing_snapshot_and_input_files_are_critical(tmp_path: Path) -> None:
    profile = make_profile(tmp_path)
    Path(profile.password_file).unlink()
    Path(profile.sources_file).unlink()

    report = evaluate_health(
        profile,
        snapshots=[],
        latest_run=None,
        lock=missing_lock(),
        now=NOW,
    )

    codes = {issue.code for issue in report.issues}
    assert {"missing-password-file", "missing-sources-file", "no-snapshots"} <= codes
    assert report.severity == HealthSeverity.CRITICAL


def test_failed_run_and_stale_lock_are_reported(tmp_path: Path) -> None:
    record = RunRecord.create(profile="local-main", backup_set="local-main", now=NOW)
    record = record.transition(RunState.RUNNING, now=NOW)
    record = record.transition(RunState.FAILURE, now=NOW, reason="restic failed")
    stale_lock = LockInspection(
        exists=True,
        active=False,
        stale=True,
        valid=True,
        identity=None,
        token="token",
        reason="Recorded process is gone.",
    )

    report = evaluate_health(
        make_profile(tmp_path),
        snapshots=[snapshot(1)],
        latest_run=record,
        lock=stale_lock,
        now=NOW,
    )

    codes = {issue.code for issue in report.issues}
    assert "latest-run-failure" in codes
    assert "stale-lock" in codes
    assert report.severity == HealthSeverity.CRITICAL


def test_skipped_run_is_warning(tmp_path: Path) -> None:
    record = RunRecord.create(profile="local-main", backup_set="local-main", now=NOW)
    record = record.transition(RunState.SKIPPED, now=NOW, reason="CPU busy")

    report = evaluate_health(
        make_profile(tmp_path),
        snapshots=[snapshot(1)],
        latest_run=record,
        lock=missing_lock(),
        now=NOW,
    )

    assert report.severity == HealthSeverity.WARNING
    assert any(issue.code == "latest-run-skipped" for issue in report.issues)
