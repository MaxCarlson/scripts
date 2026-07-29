from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import tomli_w

from rrbackup.inventory import build_inventory, load_definitions, settings_from_definitions
from rrbackup.schedule_discovery import ScheduleDiscovery, ScheduleRecord
from rrbackup.snapshots import SnapshotRecord

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def write_config(temp_dir):
    password_file = temp_dir / "password.txt"
    password_file.write_text("test-password", encoding="utf-8")
    config_path = temp_dir / "config.toml"
    config_path.write_text(
        tomli_w.dumps(
            {
                "repository": {
                    "url": str(temp_dir / "repository"),
                    "password_file": str(password_file),
                },
                "restic": {"bin": "restic"},
                "state": {"dir": str(temp_dir / "state")},
                "log": {"dir": str(temp_dir / "logs")},
                "backup_sets": [
                    {
                        "name": "daily-documents",
                        "include": [str(temp_dir / "documents")],
                        "exclude": ["**/.cache/**"],
                        "tags": ["daily-documents"],
                        "schedule": {"type": "daily", "time": "03:00"},
                        "retention": {"keep_daily": 10},
                        "use_fs_snapshot": True,
                        "exclude_caches": True,
                        "extra_backup_args": ["--exclude-if-present", ".nobackup"],
                    },
                    {
                        "name": "monthly-pictures",
                        "include": [str(temp_dir / "pictures")],
                        "tags": ["monthly-pictures"],
                        "schedule": {
                            "type": "monthly",
                            "time": "04:00",
                            "day_of_month": 1,
                        },
                        "retention": {"keep_monthly": 3},
                        "use_fs_snapshot": False,
                        "exclude_caches": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_load_definitions_is_read_only_and_preserves_engine_options(
    temp_dir,
    mocker,
) -> None:
    config_path = write_config(temp_dir)
    mocker.patch("rrbackup.config.shutil.which", return_value="tool")

    definitions, warnings = load_definitions(str(config_path))

    assert warnings == []
    assert [definition.name for definition in definitions] == [
        "daily-documents",
        "monthly-pictures",
    ]
    assert not (temp_dir / "state").exists()
    assert not (temp_dir / "logs").exists()

    daily = definitions[0]
    monthly = definitions[1]
    assert daily.profile.use_fs_snapshot is True
    assert daily.profile.exclude_caches is True
    assert daily.profile.extra_backup_args == [
        "--exclude-if-present",
        ".nobackup",
    ]
    assert monthly.profile.use_fs_snapshot is False
    assert monthly.profile.exclude_caches is False

    settings = settings_from_definitions(definitions)
    assert settings.sets[0].use_fs_snapshot is True
    assert settings.sets[0].extra_backup_args == [
        "--exclude-if-present",
        ".nobackup",
    ]
    assert settings.sets[1].exclude_caches is False


def test_build_inventory_caches_repository_and_enriches_each_backup(
    temp_dir,
    mocker,
) -> None:
    config_path = write_config(temp_dir)
    mocker.patch("rrbackup.config.shutil.which", return_value="tool")
    calls = []
    snapshots = [
        SnapshotRecord(
            snapshot_id="d" * 64,
            short_id="dddddddd",
            time=datetime(2026, 7, 28, 3, 0, tzinfo=UTC),
            paths=(str(temp_dir / "documents"),),
            tags=("daily-documents",),
        ),
        SnapshotRecord(
            snapshot_id="m" * 64,
            short_id="mmmmmmmm",
            time=datetime(2026, 7, 1, 4, 0, tzinfo=UTC),
            paths=(str(temp_dir / "pictures"),),
            tags=("monthly-pictures",),
        ),
    ]

    class FakeRepositoryClient:
        def __init__(self, profile) -> None:
            calls.append(profile.repository)

        def snapshots(self):
            return snapshots, SimpleNamespace(return_code=0, succeeded=True)

    discovery = ScheduleDiscovery(
        backend="windows-task-scheduler",
        available=True,
        records=(
            ScheduleRecord(
                backend="windows-task-scheduler",
                identifier="\\RRBackup::daily-documents",
                enabled=True,
                state="Ready",
                executable="backup.exe",
                arguments=("run", "daily-documents"),
                last_run="2026-07-28T03:00:00-07:00",
                next_run="2026-07-30T03:00:00-07:00",
                missed_runs=1,
            ),
        ),
    )

    inventory = build_inventory(
        str(config_path),
        now=NOW,
        schedule_discovery=discovery,
        repository_factory=FakeRepositoryClient,
    )

    assert calls == [str(temp_dir / "repository")]
    assert [record.definition.name for record in inventory.records] == [
        "daily-documents",
        "monthly-pictures",
    ]

    daily = inventory.by_name("DAILY-DOCUMENTS")
    monthly = inventory.by_name("monthly-pictures")
    assert daily.latest_snapshot is not None
    assert daily.latest_snapshot.short_id == "dddddddd"
    assert daily.scheduler_record is discovery.records[0]
    assert daily.missed_runs == 1
    assert daily.next_run == datetime(2026, 7, 30, 3, 0, tzinfo=UTC)
    assert monthly.latest_snapshot is not None
    assert monthly.latest_snapshot.short_id == "mmmmmmmm"
    assert monthly.scheduler_record is None
    assert monthly.next_run == datetime(2026, 8, 1, 4, 0, tzinfo=UTC)
    assert monthly.missed_runs == 0


def test_inventory_by_name_requires_one_exact_case_insensitive_match(
    temp_dir,
    mocker,
) -> None:
    config_path = write_config(temp_dir)
    mocker.patch("rrbackup.config.shutil.which", return_value="tool")

    class EmptyRepositoryClient:
        def __init__(self, profile) -> None:
            self.profile = profile

        def snapshots(self):
            return [], SimpleNamespace(return_code=0, succeeded=True)

    inventory = build_inventory(
        str(config_path),
        now=NOW,
        schedule_discovery=ScheduleDiscovery(
            backend="test",
            available=True,
            records=tuple(),
        ),
        repository_factory=EmptyRepositoryClient,
    )

    assert inventory.by_name("daily-documents").definition.name == "daily-documents"
    with pytest.raises(ValueError, match="matched 0 definitions"):
        inventory.by_name("missing")
