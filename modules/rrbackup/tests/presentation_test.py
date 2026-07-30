from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from rrbackup.config import RetentionPolicy, Schedule
from rrbackup.health import HealthReport, HealthSeverity
from rrbackup.inventory import BackupDefinition, BackupInventoryRecord
from rrbackup.models import ExecutionMode, RunRecord, RunState
from rrbackup.presentation import (
    Palette,
    backup_detail_lines,
    browse_backups,
    render_backup_table,
    render_history,
    render_repository_summary,
    render_schedule_table,
    strip_ansi,
)
from rrbackup.profile import BackupProfile
from rrbackup.repository_ops import RepositoryOperation
from rrbackup.repository_summary import RepositorySummary, StorageCache
from rrbackup.restic import ExecutionResult, ResticCommand
from rrbackup.snapshots import SnapshotRecord

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 16, 0, tzinfo=UTC)


def make_profile(tmp_path) -> BackupProfile:
    password_file = tmp_path / "password.txt"
    password_file.write_text("test-password", encoding="utf-8")
    return BackupProfile(
        name="daily-documents",
        repository=str(tmp_path / "repository"),
        password_file=str(password_file),
        sources_file=str(tmp_path / "sources.txt"),
        excludes_file=str(tmp_path / "excludes.txt"),
        status_file=str(tmp_path / "state" / "status.json"),
        log_file=str(tmp_path / "logs" / "daily.log"),
        lock_file=str(tmp_path / "state" / "daily.lock"),
        tag="daily-documents",
        restic_executable="restic",
        restore_root=str(tmp_path / "restore"),
    )


def interrupted_run() -> RunRecord:
    run = RunRecord.create(
        profile="daily-documents",
        backup_set="daily-documents",
        now=NOW - timedelta(minutes=8),
        run_id="attempted-run-id",
    )
    run = run.transition(
        RunState.RUNNING,
        now=NOW - timedelta(minutes=7),
    )
    return run.transition(
        RunState.INTERRUPTED,
        now=NOW - timedelta(minutes=2),
        exit_code=130,
        reason="Backup execution was interrupted.",
    )


def make_record(tmp_path) -> BackupInventoryRecord:
    profile = make_profile(tmp_path)
    snapshot = SnapshotRecord(
        snapshot_id="a" * 64,
        short_id="aaaaaaaa",
        time=datetime(2026, 7, 28, 3, 0, tzinfo=UTC),
        hostname="Xeres",
        paths=(str(tmp_path / "documents"),),
        tags=("daily-documents",),
        summary={"total_bytes_processed": 1024},
    )
    latest_run = interrupted_run()
    definition = BackupDefinition(
        name="daily-documents",
        profile=profile,
        sources=(str(tmp_path / "documents"), str(tmp_path / "pictures")),
        excludes=("**/.cache/**",),
        tags=("daily-documents",),
        schedule=Schedule(type="daily", time="03:00"),
        retention=RetentionPolicy(keep_daily=10, keep_monthly=3),
        source_kind="toml",
    )
    health = HealthReport(
        profile=definition.name,
        severity=HealthSeverity.OK,
        generated_utc=NOW,
        latest_snapshot=snapshot,
        latest_run=latest_run,
        issues=tuple(),
    )
    return BackupInventoryRecord(
        definition=definition,
        latest_snapshot=snapshot,
        latest_run=latest_run,
        scheduler_record=None,
        next_run=datetime(2026, 7, 30, 3, 0, tzinfo=UTC),
        missed_runs=1,
        health=health,
    )


def make_operation(profile: BackupProfile) -> RepositoryOperation:
    command = ResticCommand(argv=("restic", "-r", profile.repository, "cat", "config"))
    result = ExecutionResult(
        command=command,
        mode=ExecutionMode.RUN,
        executed=True,
        return_code=0,
        started_utc=NOW,
        finished_utc=NOW,
        output=tuple(),
    )
    return RepositoryOperation(
        result=result,
        payload={"version": 2, "id": "repository-id"},
    )


def test_palette_and_strip_ansi_are_deterministic() -> None:
    colored = Palette(True).good("healthy")

    assert "\x1b[" in colored
    assert strip_ansi(colored) == "healthy"
    assert Palette(False).bad("failed") == "failed"


def test_backup_and_schedule_tables_show_complete_and_attempted_runs(tmp_path) -> None:
    record = make_record(tmp_path)

    backup_text = render_backup_table(
        [record],
        colors=Palette(False),
        include_repository=True,
    )
    schedule_text = render_schedule_table([record], colors=Palette(False))

    assert "Backup" in backup_text
    assert "daily-documents" in backup_text
    assert "+1 more" in backup_text
    assert "Last complete" in backup_text
    assert "Last attempt" in backup_text
    assert "INTERRUPTED" in backup_text
    assert "Every day at 03:00" in backup_text
    assert record.definition.profile.repository in backup_text
    assert "Last complete" in schedule_text
    assert "Last attempt" in schedule_text
    assert "INTERRUPTED" in schedule_text
    assert "daily-documents" in schedule_text
    assert "RRBackup::daily-documents" in schedule_text
    assert "10 daily" in schedule_text


def test_backup_detail_contains_complete_and_attempted_run_information(tmp_path) -> None:
    lines = backup_detail_lines(make_record(tmp_path))
    text = "\n".join(lines)

    assert "Name: daily-documents" in text
    assert "Sources:" in text
    assert "Schedule: Every day at 03:00" in text
    assert "Retention:" in text
    assert "Missed runs: 1" in text
    assert "Last complete backup: snapshot aaaaaaaa" in text
    assert "Last attempted run: INTERRUPTED" in text
    assert "Run ID: attempted-run-id" in text
    assert "Exit code: 130" in text
    assert "Reason: Backup execution was interrupted." in text


def test_history_distinguishes_completed_snapshot_and_attempted_run(tmp_path) -> None:
    text = render_history([make_record(tmp_path)], colors=Palette(False))

    assert "completed snapshot aaaaaaaa" in text
    assert "attempted run attempte (interrupted)" in text


def test_repository_summary_is_labeled_human_output(tmp_path) -> None:
    profile = make_profile(tmp_path)
    snapshot = SnapshotRecord(
        snapshot_id="b" * 64,
        short_id="bbbbbbbb",
        time=NOW,
        tags=(profile.tag or "",),
        summary={"total_bytes_processed": 2048},
    )
    summary = RepositorySummary(
        repository=profile.repository,
        available=True,
        format_version=2,
        repository_id="repository-id",
        key_lines=("*deadbeef  user  host  2026-07-01",),
        lock_lines=tuple(),
        snapshot_count=2,
        latest_snapshot=snapshot,
        status_operation=make_operation(profile),
        storage=StorageCache(
            generated_utc=NOW,
            command="restic stats --mode restore-size --json",
            payload={
                "snapshots_count": 2,
                "total_file_count": 100,
                "total_size": 2048,
            },
        ),
    )

    text = render_repository_summary(summary, colors=Palette(False))

    assert text.startswith("Repository")
    assert "Status:         AVAILABLE" in text
    assert "Format:         2" in text
    assert "Keys" in text
    assert "No repository locks" in text
    assert "Restore size:   2.00 KiB" in text
    assert not text.lstrip().startswith("{")


def test_browse_backups_uses_shared_termdash_selection_adapter(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termdash.interactive_list as interactive_list
    import rrbackup.presentation as presentation

    record = make_record(tmp_path)
    captured = {}

    class FakeInteractiveList:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.items = kwargs["items"]

        def get_selected_items(self):
            return list(self.items)

        def run(self) -> None:
            captured["key_handler"](ord("r"), self.items[0], SimpleNamespace())

    monkeypatch.setattr(presentation, "interactive_available", lambda: True)
    monkeypatch.setattr(interactive_list, "InteractiveList", FakeInteractiveList)

    selected = browse_backups(
        [record],
        title="Select backups",
        multi_select=True,
        action_key="r",
        action_label="run selected backups",
    )

    assert selected == [record]
    assert captured["multi_select"] is True
    assert captured["detail_formatter"] is backup_detail_lines
    assert "LAST COMPLETE" in captured["columns_line"]
    assert "LAST ATTEMPT" in captured["columns_line"]
    assert "PgUp/PgDn" in " ".join(captured["footer_lines"])
