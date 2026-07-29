from __future__ import annotations

from datetime import datetime, timezone

from rrbackup.models import ExecutionMode
from rrbackup.profile import BackupProfile
from rrbackup.repository_ops import RepositoryOperation
from rrbackup.repository_summary import (
    collect_repository_summary,
    load_storage_cache,
    storage_cache_path,
)
from rrbackup.restic import ExecutionResult, ResticCommand
from rrbackup.snapshots import SnapshotRecord

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 16, 0, tzinfo=UTC)


def make_profile(temp_dir) -> BackupProfile:
    password = temp_dir / "password.txt"
    password.write_text("test-password", encoding="utf-8")
    return BackupProfile(
        name="local-main",
        repository=str(temp_dir / "repository"),
        password_file=str(password),
        sources_file=str(temp_dir / "sources.txt"),
        excludes_file=str(temp_dir / "excludes.txt"),
        status_file=str(temp_dir / "state" / "status.json"),
        log_file=str(temp_dir / "logs" / "backup.log"),
        lock_file=str(temp_dir / "state" / "backup.lock"),
        tag="local-main",
        restic_executable="restic",
        restore_root=str(temp_dir / "restore"),
    )


def operation(profile: BackupProfile, arguments, payload, return_code: int = 0):
    command = ResticCommand(
        argv=tuple(["restic", "-r", profile.repository] + list(arguments))
    )
    result = ExecutionResult(
        command=command,
        mode=ExecutionMode.RUN,
        executed=True,
        return_code=return_code,
        started_utc=NOW,
        finished_utc=NOW,
        output=tuple(),
    )
    return RepositoryOperation(result=result, payload=payload)


class FakeRepositoryClient:
    def __init__(self, profile: BackupProfile) -> None:
        self.profile = profile
        self.calls = []
        self.snapshot = SnapshotRecord(
            snapshot_id="a" * 64,
            short_id="aaaaaaaa",
            time=NOW,
            paths=("C:\\",),
            tags=("local-main",),
        )

    def status(self):
        self.calls.append("status")
        return operation(
            self.profile,
            ["cat", "config"],
            {"version": 2, "id": "repository-id"},
        )

    def keys(self):
        self.calls.append("keys")
        return operation(
            self.profile,
            ["key", "list"],
            {"lines": ["*deadbeef  user  host  2026-07-01"]},
        )

    def locks(self):
        self.calls.append("locks")
        return operation(self.profile, ["list", "locks"], {"lines": []})

    def snapshots(self, *, tags=()):
        self.calls.append(("snapshots", tuple(tags)))
        result = operation(self.profile, ["snapshots", "--json"], []).result
        return [self.snapshot], result

    def stats(self, *, mode="restore-size"):
        self.calls.append(("stats", mode))
        return operation(
            self.profile,
            ["stats", "--mode", mode, "--json"],
            {
                "snapshots_count": 1,
                "total_file_count": 250,
                "total_size": 4096,
            },
        )


def test_default_repository_summary_never_runs_expensive_stats(temp_dir) -> None:
    profile = make_profile(temp_dir)
    client = FakeRepositoryClient(profile)

    summary = collect_repository_summary(
        profile,
        client_factory=lambda unused: client,
    )

    assert summary.available
    assert summary.format_version == 2
    assert summary.snapshot_count == 1
    assert summary.storage is None
    assert ("stats", "restore-size") not in client.calls
    assert not storage_cache_path(profile).exists()


def test_explicit_storage_refresh_runs_once_and_writes_cache(temp_dir) -> None:
    profile = make_profile(temp_dir)
    client = FakeRepositoryClient(profile)

    summary = collect_repository_summary(
        profile,
        refresh_storage=True,
        client_factory=lambda unused: client,
    )

    assert client.calls.count(("stats", "restore-size")) == 1
    assert summary.storage is not None
    assert summary.storage.payload["total_size"] == 4096
    assert storage_cache_path(profile).exists()
    cached = load_storage_cache(profile)
    assert cached is not None
    assert cached.payload["total_file_count"] == 250


def test_default_summary_reuses_cache_without_refreshing(temp_dir) -> None:
    profile = make_profile(temp_dir)
    first_client = FakeRepositoryClient(profile)
    collect_repository_summary(
        profile,
        refresh_storage=True,
        client_factory=lambda unused: first_client,
    )

    second_client = FakeRepositoryClient(profile)
    summary = collect_repository_summary(
        profile,
        client_factory=lambda unused: second_client,
    )

    assert summary.storage is not None
    assert summary.storage.payload["total_size"] == 4096
    assert ("stats", "restore-size") not in second_client.calls
