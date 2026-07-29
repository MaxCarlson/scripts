"""Parsers and models for Restic snapshot and backup JSON output."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .models import datetime_from_text


@dataclass(frozen=True)
class SnapshotRecord:
    """Normalized Restic snapshot metadata."""

    snapshot_id: str
    short_id: str
    time: datetime
    hostname: Optional[str] = None
    username: Optional[str] = None
    paths: Sequence[str] = field(default_factory=tuple)
    tags: Sequence[str] = field(default_factory=tuple)
    parent: Optional[str] = None
    program_version: Optional[str] = None
    summary: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SnapshotRecord":
        """Create a normalized snapshot from Restic JSON."""

        snapshot_id = str(payload.get("id") or payload.get("short_id") or "")
        if not snapshot_id:
            raise ValueError("Snapshot payload is missing id.")

        parsed_time = datetime_from_text(
            None if payload.get("time") is None else str(payload.get("time"))
        )
        if parsed_time is None:
            raise ValueError("Snapshot payload is missing time.")

        short_id = str(payload.get("short_id") or snapshot_id[:8])
        raw_summary = payload.get("summary")
        summary = dict(raw_summary) if isinstance(raw_summary, Mapping) else {}

        return cls(
            snapshot_id=snapshot_id,
            short_id=short_id,
            time=parsed_time,
            hostname=(
                None
                if payload.get("hostname") is None
                else str(payload.get("hostname"))
            ),
            username=(
                None
                if payload.get("username") is None
                else str(payload.get("username"))
            ),
            paths=tuple(str(value) for value in payload.get("paths", [])),
            tags=tuple(str(value) for value in payload.get("tags", [])),
            parent=(
                None if payload.get("parent") is None else str(payload.get("parent"))
            ),
            program_version=(
                None
                if payload.get("program_version") is None
                else str(payload.get("program_version"))
            ),
            summary=summary,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize normalized snapshot metadata."""

        return {
            "id": self.snapshot_id,
            "short_id": self.short_id,
            "time": self.time.isoformat(),
            "hostname": self.hostname,
            "username": self.username,
            "paths": list(self.paths),
            "tags": list(self.tags),
            "parent": self.parent,
            "program_version": self.program_version,
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class BackupSummary:
    """Normalized final summary from `restic backup --json`."""

    snapshot_id: Optional[str]
    files_new: int
    files_changed: int
    files_unmodified: int
    dirs_new: int
    dirs_changed: int
    dirs_unmodified: int
    data_blobs: int
    tree_blobs: int
    data_added: int
    data_added_packed: int
    total_files_processed: int
    total_bytes_processed: int
    total_duration_seconds: float
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BackupSummary":
        """Create a normalized summary from one Restic JSON message."""

        message_type = payload.get("message_type")
        if message_type not in (None, "summary"):
            raise ValueError("Expected a Restic summary message.")

        return cls(
            snapshot_id=(
                None
                if payload.get("snapshot_id") is None
                else str(payload.get("snapshot_id"))
            ),
            files_new=int(payload.get("files_new", 0)),
            files_changed=int(payload.get("files_changed", 0)),
            files_unmodified=int(payload.get("files_unmodified", 0)),
            dirs_new=int(payload.get("dirs_new", 0)),
            dirs_changed=int(payload.get("dirs_changed", 0)),
            dirs_unmodified=int(payload.get("dirs_unmodified", 0)),
            data_blobs=int(payload.get("data_blobs", 0)),
            tree_blobs=int(payload.get("tree_blobs", 0)),
            data_added=int(payload.get("data_added", 0)),
            data_added_packed=int(payload.get("data_added_packed", 0)),
            total_files_processed=int(payload.get("total_files_processed", 0)),
            total_bytes_processed=int(payload.get("total_bytes_processed", 0)),
            total_duration_seconds=float(payload.get("total_duration", 0.0)),
            raw=dict(payload),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the normalized backup summary."""

        return {
            "snapshot_id": self.snapshot_id,
            "files_new": self.files_new,
            "files_changed": self.files_changed,
            "files_unmodified": self.files_unmodified,
            "dirs_new": self.dirs_new,
            "dirs_changed": self.dirs_changed,
            "dirs_unmodified": self.dirs_unmodified,
            "data_blobs": self.data_blobs,
            "tree_blobs": self.tree_blobs,
            "data_added": self.data_added,
            "data_added_packed": self.data_added_packed,
            "total_files_processed": self.total_files_processed,
            "total_bytes_processed": self.total_bytes_processed,
            "total_duration_seconds": self.total_duration_seconds,
        }


def _load_json_value(value: Any) -> Any:
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


def parse_snapshots_json(value: Any) -> List[SnapshotRecord]:
    """Parse `restic snapshots --json` output."""

    payload = _load_json_value(value)
    if not isinstance(payload, list):
        raise ValueError("Restic snapshots JSON must be an array.")

    records = [SnapshotRecord.from_dict(item) for item in payload]
    return sorted(records, key=lambda record: record.time)


def parse_backup_json_lines(
    lines: Iterable[str],
    *,
    strict: bool = False,
) -> Optional[BackupSummary]:
    """Extract the final summary from JSON-lines backup output.

    Non-JSON console lines are ignored unless `strict` is enabled. When several
    summary messages are present, the last one is authoritative.
    """

    summary: Optional[BackupSummary] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            if strict:
                raise
            continue

        if not isinstance(payload, Mapping):
            if strict:
                raise ValueError("Restic JSON-lines entry must be an object.")
            continue

        if payload.get("message_type") == "summary":
            summary = BackupSummary.from_dict(payload)

    return summary


def latest_snapshot(
    snapshots: Sequence[SnapshotRecord],
    *,
    tag: Optional[str] = None,
    hostname: Optional[str] = None,
) -> Optional[SnapshotRecord]:
    """Return the latest snapshot matching optional tag and host filters."""

    candidates = [
        snapshot
        for snapshot in snapshots
        if (tag is None or tag in snapshot.tags)
        and (hostname is None or snapshot.hostname == hostname)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda snapshot: snapshot.time)
