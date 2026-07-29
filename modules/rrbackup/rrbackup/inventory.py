"""Unified inventory of configured backups and their runtime status."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import (
    BackupSet,
    RetentionPolicy,
    Schedule,
    Settings,
    load_config,
    resolve_config_path,
)
from .health import HealthReport, evaluate_health
from .locking import ProcessLock
from .models import RunRecord, utc_now
from .profile import (
    BackupProfile,
    SourceAttribution,
    ValueSource,
    load_legacy_profile,
    read_path_list,
)
from .repository_ops import RepositoryClient
from .schedule_discovery import ScheduleDiscovery, ScheduleRecord, discover_schedules
from .schedule_math import (
    count_missed_runs,
    describe_retention,
    describe_schedule,
    next_scheduled_run,
)
from .snapshots import SnapshotRecord
from .state import RunStateStore


@dataclass
class BackupDefinition:
    """One user-facing backup definition regardless of its source format."""

    name: str
    profile: BackupProfile
    sources: Tuple[str, ...]
    excludes: Tuple[str, ...]
    tags: Tuple[str, ...]
    schedule: Schedule
    retention: Optional[RetentionPolicy]
    source_kind: str
    config_path: Optional[Path] = None
    settings: Optional[Settings] = None
    backup_set: Optional[BackupSet] = None

    @property
    def task_name(self) -> str:
        """Return the stable scheduler identifier for this backup."""

        normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", self.name).strip("-")
        return f"RRBackup::{normalized or 'backup'}"

    @property
    def schedule_text(self) -> str:
        return describe_schedule(self.schedule)

    @property
    def retention_text(self) -> str:
        return describe_retention(self.retention)

    @property
    def source_summary(self) -> str:
        if not self.sources:
            return "No sources"
        if len(self.sources) == 1:
            return self.sources[0]
        return f"{self.sources[0]} +{len(self.sources) - 1} more"

    def materialize_inputs(self) -> None:
        """Write canonical set inputs immediately before execution."""

        if self.source_kind != "toml":
            return
        _atomic_write_lines(Path(self.profile.sources_file or ""), self.sources)
        if self.profile.excludes_file:
            _atomic_write_lines(Path(self.profile.excludes_file), self.excludes)


@dataclass(frozen=True)
class BackupInventoryRecord:
    """Backup definition enriched with snapshots, runs, schedule, and health."""

    definition: BackupDefinition
    latest_snapshot: Optional[SnapshotRecord]
    latest_run: Optional[RunRecord]
    scheduler_record: Optional[ScheduleRecord]
    next_run: Optional[datetime]
    missed_runs: Optional[int]
    health: HealthReport
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.definition.name,
            "source_kind": self.definition.source_kind,
            "sources": list(self.definition.sources),
            "source_summary": self.definition.source_summary,
            "excludes": list(self.definition.excludes),
            "tags": list(self.definition.tags),
            "repository": self.definition.profile.repository,
            "schedule": self.definition.schedule.to_dict(),
            "schedule_text": self.definition.schedule_text,
            "retention": (
                None
                if self.definition.retention is None
                else self.definition.retention.to_dict()
            ),
            "retention_text": self.definition.retention_text,
            "task_name": self.definition.task_name,
            "latest_snapshot": (
                None if self.latest_snapshot is None else self.latest_snapshot.to_dict()
            ),
            "latest_run": None if self.latest_run is None else self.latest_run.to_dict(),
            "scheduler": (
                None if self.scheduler_record is None else self.scheduler_record.to_dict()
            ),
            "next_run": None if self.next_run is None else self.next_run.isoformat(),
            "missed_runs": self.missed_runs,
            "health": self.health.to_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class BackupInventory:
    records: Tuple[BackupInventoryRecord, ...]
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def by_name(self, name: str) -> BackupInventoryRecord:
        normalized = name.strip().lower()
        matches = [
            record
            for record in self.records
            if record.definition.name.lower() == normalized
        ]
        if len(matches) != 1:
            raise ValueError(
                "Backup name matched {0} definitions; exactly one is required: {1!r}".format(
                    len(matches),
                    name,
                )
            )
        return matches[0]

    def to_dict(self) -> Dict[str, object]:
        return {
            "backups": [record.to_dict() for record in self.records],
            "warnings": list(self.warnings),
        }


def _atomic_write_lines(path: Path, values: Iterable[str]) -> None:
    if not str(path):
        raise ValueError("Cannot materialize an empty input path.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for value in values:
                handle.write(str(value).rstrip("\r\n") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _profile_state_root(settings: Settings, name: str) -> Path:
    state_root = Path(settings.state_dir or Path.home() / ".cache" / "rrbackup")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "backup"
    return state_root / "profiles" / safe_name


def _profile_from_set(
    settings: Settings,
    backup_set: BackupSet,
    *,
    config_path: Path,
) -> BackupDefinition:
    if settings.repo is None:
        raise ValueError("Canonical configuration has no repository section.")
    password_file = settings.repo.password_file or os.environ.get("RESTIC_PASSWORD_FILE")
    if not password_file:
        if settings.repo.password_env:
            raise ValueError(
                "Canonical password_env credentials are not yet supported by the shared "
                "engine; configure repository.password_file instead."
            )
        raise ValueError("Canonical repository has no password file.")

    profile_root = _profile_state_root(settings, backup_set.name)
    tags = tuple(backup_set.tags or [backup_set.name])
    extra_arguments: List[str] = []
    if backup_set.one_fs:
        extra_arguments.append("--one-file-system")

    attribution = {
        "repository": SourceAttribution(ValueSource.CONFIG_FILE, str(config_path)),
        "password_file": SourceAttribution(ValueSource.CONFIG_FILE, str(config_path)),
        "sources_file": SourceAttribution(ValueSource.CONFIG_FILE, str(config_path)),
        "excludes_file": SourceAttribution(ValueSource.CONFIG_FILE, str(config_path)),
        "tag": SourceAttribution(ValueSource.CONFIG_FILE, str(config_path)),
    }
    profile = BackupProfile(
        name=backup_set.name,
        repository=settings.repo.url,
        password_file=password_file,
        sources_file=str(profile_root / "sources.txt"),
        excludes_file=str(profile_root / "excludes.txt"),
        status_file=str(profile_root / "status.json"),
        log_file=str(Path(settings.log_dir or profile_root / "logs") / f"{backup_set.name}.log"),
        lock_file=str(profile_root / "backup.lock"),
        tag=tags[0] if tags else backup_set.name,
        restic_executable=settings.restic_bin,
        restore_root=str(profile_root / "restore"),
        use_fs_snapshot=True,
        exclude_caches=True,
        dry_run=backup_set.dry_run_default,
        extra_backup_args=extra_arguments,
        attribution=attribution,
    )
    profile.validate()
    return BackupDefinition(
        name=backup_set.name,
        profile=profile,
        sources=tuple(backup_set.include),
        excludes=tuple(backup_set.exclude),
        tags=tags,
        schedule=backup_set.schedule,
        retention=backup_set.retention or settings.retention_defaults,
        source_kind="toml",
        config_path=config_path,
        settings=settings,
        backup_set=backup_set,
    )


def load_definitions(
    config_path: Optional[str] = None,
) -> Tuple[List[BackupDefinition], List[str]]:
    """Load canonical TOML sets when available, otherwise legacy defaults."""

    warnings: List[str] = []
    candidate = resolve_config_path(config_path)
    definitions: List[BackupDefinition] = []
    if candidate.exists():
        settings = load_config(candidate)
        for backup_set in settings.sets:
            try:
                definitions.append(
                    _profile_from_set(settings, backup_set, config_path=candidate)
                )
            except (OSError, ValueError) as exc:
                warnings.append(f"{backup_set.name}: {exc}")
        if definitions:
            return definitions, warnings
        warnings.append(f"No usable backup sets were found in {candidate}.")

    legacy_config = (
        config_path
        if config_path and candidate.suffix.lower() == ".json"
        else None
    )
    legacy_profile, legacy_path = load_legacy_profile(legacy_config)
    sources = tuple(read_path_list(legacy_profile.sources_file))
    excludes = tuple(read_path_list(legacy_profile.excludes_file))
    definitions.append(
        BackupDefinition(
            name=legacy_profile.name,
            profile=legacy_profile,
            sources=sources,
            excludes=excludes,
            tags=tuple([legacy_profile.tag] if legacy_profile.tag else []),
            schedule=Schedule(type="manual", description="No schedule configured"),
            retention=None,
            source_kind="legacy-json" if legacy_path else "legacy-default",
            config_path=legacy_path,
        )
    )
    return definitions, warnings


def _match_schedule(
    definition: BackupDefinition,
    discovery: ScheduleDiscovery,
) -> Optional[ScheduleRecord]:
    expected_name = definition.task_name.lower()
    name = definition.name.lower()
    matches = []
    for record in discovery.records:
        identifier = record.identifier.lower()
        command_text = " ".join(
            [record.executable or ""] + [str(value) for value in record.arguments]
        ).lower()
        if expected_name in identifier or (
            "backup" in command_text
            and " run " in f" {command_text} "
            and name in command_text
        ):
            matches.append(record)
    return matches[0] if len(matches) == 1 else None


def _record_store(definition: BackupDefinition) -> RunStateStore:
    return RunStateStore(
        Path(definition.profile.status_file).parent / "rrbackup-state"
    )


def _filter_snapshots(
    snapshots: Sequence[SnapshotRecord],
    definition: BackupDefinition,
) -> List[SnapshotRecord]:
    if definition.tags:
        tagged = [
            snapshot
            for snapshot in snapshots
            if any(tag in snapshot.tags for tag in definition.tags)
        ]
        if tagged:
            return tagged
    if definition.sources:
        expected = set(definition.sources)
        matched = [
            snapshot
            for snapshot in snapshots
            if expected.issubset(set(snapshot.paths))
        ]
        if matched:
            return matched
    return list(snapshots)


def build_inventory(
    config_path: Optional[str] = None,
    *,
    now: Optional[datetime] = None,
    schedule_discovery: Optional[ScheduleDiscovery] = None,
    repository_factory: Callable[[BackupProfile], RepositoryClient] = RepositoryClient,
) -> BackupInventory:
    """Build the authoritative inventory used by view, run, and schedule."""

    current = now or utc_now()
    definitions, warnings = load_definitions(config_path)
    discovery = schedule_discovery or discover_schedules()
    warnings.extend(discovery.warnings)

    snapshot_cache: Dict[
        Tuple[str, str, str],
        Tuple[List[SnapshotRecord], Optional[str]],
    ] = {}
    records: List[BackupInventoryRecord] = []
    for definition in definitions:
        profile = definition.profile
        cache_key = (
            profile.repository,
            profile.password_file,
            profile.restic_executable,
        )
        if cache_key not in snapshot_cache:
            snapshots, result = repository_factory(profile).snapshots()
            error = (
                None
                if result.return_code == 0
                else "Restic snapshot listing failed."
            )
            snapshot_cache[cache_key] = (snapshots, error)
        snapshots, snapshot_error = snapshot_cache[cache_key]
        relevant = _filter_snapshots(snapshots, definition)
        latest_snapshot = relevant[0] if relevant else None
        latest_run = _record_store(definition).load_latest()
        scheduler_record = _match_schedule(definition, discovery)

        next_run = None
        missed_runs: Optional[int] = None
        try:
            next_run = next_scheduled_run(definition.schedule, current)
            if scheduler_record and scheduler_record.missed_runs is not None:
                missed_runs = scheduler_record.missed_runs
            else:
                missed_runs = count_missed_runs(
                    definition.schedule,
                    since=(
                        None
                        if latest_snapshot is None
                        else latest_snapshot.time
                    ),
                    until=current,
                )
        except ValueError as exc:
            warnings.append(f"{definition.name}: invalid schedule: {exc}")

        health = evaluate_health(
            profile,
            snapshots=relevant,
            latest_run=latest_run,
            lock=ProcessLock(profile.lock_file).inspect(),
            now=current,
        )
        record_warnings = tuple([snapshot_error] if snapshot_error else [])
        records.append(
            BackupInventoryRecord(
                definition=definition,
                latest_snapshot=latest_snapshot,
                latest_run=latest_run,
                scheduler_record=scheduler_record,
                next_run=next_run,
                missed_runs=missed_runs,
                health=health,
                warnings=record_warnings,
            )
        )

    return BackupInventory(
        records=tuple(records),
        warnings=tuple(dict.fromkeys(warnings)),
    )
