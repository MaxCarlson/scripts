from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rrbackup.audit import collect_audit
from rrbackup.models import ExecutionMode
from rrbackup.profile import BackupProfile
from rrbackup.repository_ops import RepositoryOperation
from rrbackup.restic import ExecutionResult, ResticCommand
from rrbackup.schedule_discovery import ScheduleDiscovery
from rrbackup.snapshots import SnapshotRecord


UTC = timezone.utc
NOW = datetime(2026, 7, 29, tzinfo=UTC)


def make_profile(tmp_path: Path) -> BackupProfile:
    password = tmp_path / "password.txt"
    sources = tmp_path / "sources.txt"
    excludes = tmp_path / "excludes.txt"
    password.write_text("super-secret-password", encoding="utf-8")
    sources.write_text("C:\\\nD:\\Pictures\n", encoding="utf-8")
    excludes.write_text("C:\\pagefile.sys\n", encoding="utf-8")
    return BackupProfile(
        name="local-main",
        repository=str(tmp_path / "repo"),
        password_file=str(password),
        sources_file=str(sources),
        excludes_file=str(excludes),
        status_file=str(tmp_path / "status.json"),
        log_file=str(tmp_path / "backup.log"),
        lock_file=str(tmp_path / "backup.lock"),
        tag="local-main",
        restic_executable="restic",
        restore_root=str(tmp_path / "restore"),
    )


def execution(arguments: tuple[str, ...] = ("snapshots",)) -> ExecutionResult:
    command = ResticCommand(argv=("restic", "-r", "repo") + arguments)
    return ExecutionResult(
        command=command,
        mode=ExecutionMode.RUN,
        executed=True,
        return_code=0,
        started_utc=NOW,
        finished_utc=NOW,
        output=tuple(),
    )


class FakeRepositoryClient:
    def __init__(self) -> None:
        self.snapshot = SnapshotRecord(
            snapshot_id="a" * 64,
            short_id="aaaaaaaa",
            time=NOW,
            hostname="Xeres",
            username="mcarls",
            paths=("C:\\",),
            tags=("local-main",),
            program_version="restic 0.19.1",
        )

    def snapshots(self, **kwargs: object):
        return [self.snapshot], execution(("snapshots", "--json"))

    def status(self) -> RepositoryOperation:
        return RepositoryOperation(execution(("cat", "config")), {"version": 2})

    def keys(self) -> RepositoryOperation:
        return RepositoryOperation(execution(("key", "list")), {"lines": ["* abc123"]})


def test_audit_redacts_secret_environment_and_never_reads_password_contents(
    tmp_path: Path,
) -> None:
    profile = make_profile(tmp_path)
    report = collect_audit(
        profile,
        selected_sections=("configuration", "environment", "paths", "inputs"),
        environment={
            "RESTIC_PASSWORD": "environment-secret",
            "RESTIC_PASSWORD_FILE": profile.password_file,
        },
        repository_client=FakeRepositoryClient(),
        schedule_discovery=ScheduleDiscovery(
            backend="test",
            available=True,
            records=tuple(),
        ),
    )

    payload_text = json.dumps(report.to_dict())
    assert "environment-secret" not in payload_text
    assert "super-secret-password" not in payload_text
    assert report.sections["environment"]["RESTIC_PASSWORD"]["value"] == "<redacted>"
    assert report.sections["inputs"]["sources"] == ["C:\\", "D:\\Pictures"]
    assert report.sections["paths"]["password_file"]["sensitive"] is True


def test_audit_collects_snapshot_health_and_provenance(tmp_path: Path) -> None:
    profile = make_profile(tmp_path)
    report = collect_audit(
        profile,
        selected_sections=(
            "repository",
            "keys",
            "snapshots",
            "runs",
            "health",
            "provenance",
            "recommendations",
        ),
        environment={},
        repository_client=FakeRepositoryClient(),
        schedule_discovery=ScheduleDiscovery(
            backend="test",
            available=True,
            records=tuple(),
        ),
    )

    assert report.sections["repository"]["payload"]["version"] == 2
    assert report.sections["snapshots"]["count"] == 1
    assert report.sections["health"]["latest_snapshot"]["short_id"] == "aaaaaaaa"
    assert report.sections["provenance"]["latest_snapshot_id"] == "a" * 64
    assert report.sections["provenance"]["structured_run_history_present"] is False


def test_audit_markdown_contains_selected_sections(tmp_path: Path) -> None:
    report = collect_audit(
        make_profile(tmp_path),
        selected_sections=("runtime", "configuration"),
        environment={},
        repository_client=FakeRepositoryClient(),
        schedule_discovery=ScheduleDiscovery(
            backend="test",
            available=True,
            records=tuple(),
        ),
    )

    markdown = report.to_markdown()
    assert "# Backup Audit" in markdown
    assert "## Runtime" in markdown
    assert "## Configuration" in markdown
    assert "## Snapshots" not in markdown


def test_unknown_audit_section_is_rejected(tmp_path: Path) -> None:
    try:
        collect_audit(
            make_profile(tmp_path),
            selected_sections=("not-a-section",),
            environment={},
            repository_client=FakeRepositoryClient(),
            schedule_discovery=ScheduleDiscovery(
                backend="test",
                available=True,
                records=tuple(),
            ),
        )
    except ValueError as exc:
        assert "Unsupported audit section" in str(exc)
    else:
        raise AssertionError("Expected unknown audit section to fail.")
