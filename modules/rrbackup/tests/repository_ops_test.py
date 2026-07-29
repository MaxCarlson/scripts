from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest

from rrbackup.models import ExecutionMode
from rrbackup.profile import BackupProfile
from rrbackup.repository_ops import RepositoryClient, operation_to_dict
from rrbackup.restic import ExecutionResult, ResticCommand


UTC = timezone.utc
NOW = datetime(2026, 7, 29, tzinfo=UTC)


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
    )


def result(command: ResticCommand, output: Sequence[str], return_code: int = 0) -> ExecutionResult:
    return ExecutionResult(
        command=command,
        mode=ExecutionMode.RUN,
        executed=True,
        return_code=return_code,
        started_utc=NOW,
        finished_utc=NOW,
        output=tuple(output),
    )


def test_snapshots_are_parsed_and_returned_newest_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RepositoryClient(make_profile(tmp_path))
    payload = [
        {
            "id": "a" * 64,
            "short_id": "aaaaaaaa",
            "time": "2026-04-11T22:09:38-07:00",
            "tags": ["local-main"],
        },
        {
            "id": "b" * 64,
            "short_id": "bbbbbbbb",
            "time": "2026-04-14T21:41:15-07:00",
            "tags": ["local-main"],
        },
    ]

    def fake_execute(command: ResticCommand, **kwargs: object) -> ExecutionResult:
        return result(command, [json.dumps(payload)])

    monkeypatch.setattr("rrbackup.repository_ops.execute_restic", fake_execute)

    snapshots, execution = client.snapshots(tags=("local-main",))

    assert execution.succeeded
    assert [value.short_id for value in snapshots] == ["bbbbbbbb", "aaaaaaaa"]
    assert "--tag" in execution.command.argv


def test_status_and_stats_parse_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RepositoryClient(make_profile(tmp_path))
    outputs = iter(
        [
            [json.dumps({"version": 2, "id": "repo-id"})],
            [json.dumps({"total_size": 123, "total_file_count": 9})],
        ]
    )

    def fake_execute(command: ResticCommand, **kwargs: object) -> ExecutionResult:
        return result(command, next(outputs))

    monkeypatch.setattr("rrbackup.repository_ops.execute_restic", fake_execute)

    status = client.status()
    stats = client.stats()

    assert status.payload["version"] == 2
    assert stats.payload["total_size"] == 123
    assert operation_to_dict(stats)["succeeded"] is True


def test_keys_locks_and_cache_preserve_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RepositoryClient(make_profile(tmp_path))

    def fake_execute(command: ResticCommand, **kwargs: object) -> ExecutionResult:
        return result(command, ["line one\n", "line two\r\n"])

    monkeypatch.setattr("rrbackup.repository_ops.execute_restic", fake_execute)

    assert client.keys().payload["lines"] == ["line one", "line two"]
    assert client.locks().payload["lines"] == ["line one", "line two"]
    assert client.cache_status().payload["lines"] == ["line one", "line two"]


def test_nonzero_snapshot_result_does_not_parse_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RepositoryClient(make_profile(tmp_path))

    def fake_execute(command: ResticCommand, **kwargs: object) -> ExecutionResult:
        return result(command, ["not-json"], return_code=1)

    monkeypatch.setattr("rrbackup.repository_ops.execute_restic", fake_execute)

    snapshots, execution = client.snapshots()

    assert snapshots == []
    assert execution.return_code == 1
