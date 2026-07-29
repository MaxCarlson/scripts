"""Combined repository summary with explicit, cached expensive statistics."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .profile import BackupProfile
from .repository_ops import RepositoryClient, RepositoryOperation, operation_to_dict
from .snapshots import SnapshotRecord


@dataclass(frozen=True)
class StorageCache:
    generated_utc: datetime
    command: str
    payload: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_utc": self.generated_utc.isoformat(),
            "command": self.command,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class RepositorySummary:
    repository: str
    available: bool
    format_version: Optional[int]
    repository_id: Optional[str]
    key_lines: Tuple[str, ...]
    lock_lines: Tuple[str, ...]
    snapshot_count: int
    latest_snapshot: Optional[SnapshotRecord]
    status_operation: RepositoryOperation
    storage: Optional[StorageCache]
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repository": self.repository,
            "available": self.available,
            "format_version": self.format_version,
            "repository_id": self.repository_id,
            "keys": list(self.key_lines),
            "locks": list(self.lock_lines),
            "snapshot_count": self.snapshot_count,
            "latest_snapshot": (
                None if self.latest_snapshot is None else self.latest_snapshot.to_dict()
            ),
            "status": operation_to_dict(self.status_operation),
            "storage": None if self.storage is None else self.storage.to_dict(),
            "warnings": list(self.warnings),
        }


def storage_cache_path(profile: BackupProfile) -> Path:
    state_root = Path(profile.status_file).parent / "rrbackup-state"
    return state_root / "repository-storage.json"


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".{0}.".format(path.name),
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_storage_cache(profile: BackupProfile) -> Optional[StorageCache]:
    path = storage_cache_path(profile)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        generated = datetime.fromisoformat(str(raw["generated_utc"]))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        payload = raw.get("payload", {})
        if not isinstance(payload, Mapping):
            return None
        return StorageCache(
            generated_utc=generated,
            command=str(raw.get("command") or ""),
            payload=dict(payload),
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def refresh_storage_cache(
    profile: BackupProfile,
    *,
    client_factory: Callable[[BackupProfile], RepositoryClient] = RepositoryClient,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> Tuple[Optional[StorageCache], RepositoryOperation]:
    """Run the expensive restore-size statistics command and persist its result."""

    operation = client_factory(profile).stats(mode="restore-size")
    cache: Optional[StorageCache] = None
    if operation.result.succeeded and isinstance(operation.payload, Mapping):
        cache = StorageCache(
            generated_utc=clock().astimezone(timezone.utc),
            command=operation.result.command.render(redacted=True),
            payload=dict(operation.payload),
        )
        _atomic_json_write(storage_cache_path(profile), cache.to_dict())
    return cache, operation


def _payload_lines(operation: RepositoryOperation) -> Tuple[str, ...]:
    payload = operation.payload
    if isinstance(payload, Mapping):
        values = payload.get("lines", [])
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            return tuple(str(value) for value in values if str(value).strip())
    return tuple()


def collect_repository_summary(
    profile: BackupProfile,
    *,
    refresh_storage: bool = False,
    client_factory: Callable[[BackupProfile], RepositoryClient] = RepositoryClient,
) -> RepositorySummary:
    """Collect the default fast summary.

    The expensive Restic restore-size statistics command is called only when
    ``refresh_storage`` is true. Otherwise a previously cached result is used.
    """

    client = client_factory(profile)
    status = client.status()
    keys = client.keys()
    locks = client.locks()
    snapshots, snapshot_result = client.snapshots(
        tags=(() if not profile.tag else (profile.tag,))
    )
    warnings: List[str] = []
    if not status.result.succeeded:
        warnings.append("Repository configuration could not be read.")
    if not keys.result.succeeded:
        warnings.append("Repository key metadata could not be read.")
    if not locks.result.succeeded:
        warnings.append("Repository locks could not be read.")
    if not snapshot_result.succeeded:
        warnings.append("Repository snapshots could not be read.")

    storage = load_storage_cache(profile)
    if refresh_storage:
        storage, storage_operation = refresh_storage_cache(
            profile,
            client_factory=client_factory,
        )
        if not storage_operation.result.succeeded:
            warnings.append("Repository storage statistics refresh failed.")

    payload = status.payload if isinstance(status.payload, Mapping) else {}
    format_version = payload.get("version")
    return RepositorySummary(
        repository=profile.repository,
        available=status.result.succeeded,
        format_version=(None if format_version is None else int(format_version)),
        repository_id=(None if payload.get("id") is None else str(payload.get("id"))),
        key_lines=_payload_lines(keys),
        lock_lines=_payload_lines(locks),
        snapshot_count=len(snapshots),
        latest_snapshot=(snapshots[0] if snapshots else None),
        status_operation=status,
        storage=storage,
        warnings=tuple(warnings),
    )
