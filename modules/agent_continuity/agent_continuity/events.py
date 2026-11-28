"""Environment-isolated atomic per-event JSON spool persistence."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .environment import load_config
from .errors import ContinuityError, ErrorCode
from .models import EventEnvelope

MAX_EVENT_FILE_BYTES = 1_048_576
SUPPORTED_EVENT_SCHEMA_VERSIONS = frozenset({1})

_REQUIRED_FIELDS = (
    "event_id",
    "event_schema_version",
    "event_type",
    "environment_id",
    "source_timestamp",
    "observed_timestamp",
    "payload",
)


@dataclass(slots=True)
class SpoolRecord:
    """Validated event loaded from a spool file."""

    envelope: EventEnvelope
    file_path: Path
    checksum: str
    fingerprint: tuple[int, int, int, int, int] | None = None


@dataclass(slots=True)
class SpoolIssue:
    """Corrupt, partial, or unreadable event spool entry."""

    file_path: str
    reason: str


@dataclass(slots=True)
class SpoolScanResult:
    """Result of reading all event spools."""

    records: list[SpoolRecord]
    issues: list[SpoolIssue]
    spool_roots: list[Path]


@dataclass(slots=True)
class IncrementalSpoolScanResult:
    """Result of incremental spool scanning using `(size, mtime_ns, ctime_ns, ino)` fingerprints."""

    records: list[SpoolRecord]
    issues: list[SpoolIssue]
    spool_roots: list[Path]
    unchanged_count: int
    total_files: int
    current_keys: set[str]


def compute_event_checksum(event_dict: dict[str, Any]) -> str:
    """Return canonical SHA-256 hex digest for an event payload."""
    encoded = json.dumps(event_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_ts_prefix(iso_ts: str) -> str:
    # Compact sortable prefix: 20261119T145501123456Z
    cleaned = "".join(ch for ch in iso_ts if ch.isalnum())
    return cleaned or "00000000T000000"


def atomic_write_json(target: Path, data: dict[str, Any]) -> None:
    """Write JSON to target atomically using a same-directory temporary file and os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".tmp.{os.getpid()}.{secrets.token_hex(4)}.json")
    serialized = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(serialized)
            fh.flush()
            with contextlib.suppress(OSError):
                os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise ContinuityError(
            ErrorCode.EVENT_SPOOL_UNAVAILABLE,
            f"Failed to write durable event file {target}: {exc}",
            {"path": str(target)},
        ) from exc


def append_event(home_dir: Path, event: EventEnvelope) -> Path:
    """Persist an immutable EventEnvelope into <home_dir>/events/<environment_id>/."""
    if not event.environment_id:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Event environment_id cannot be empty.")
    env_dir = home_dir / "events" / event.environment_id
    filename = f"{_safe_ts_prefix(event.observed_timestamp)}_{event.event_id}.json"
    target = env_dir / filename
    atomic_write_json(target, event.to_dict())
    return target


def discover_spool_roots(home_dir: Path, extra_roots: list[Path] | None = None) -> list[Path]:
    """Return ordered list of event spool directories configured for ingestion."""
    roots: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            roots.append(path)

    _add(home_dir / "events")
    cfg = load_config(home_dir)
    for raw in cfg.get("extra_spool_dirs", []) or []:
        if isinstance(raw, str) and raw.strip():
            _add(Path(raw).expanduser())
    for p in extra_roots or []:
        _add(p)
    return roots


def _stat_tuple(st: os.stat_result) -> tuple[int, int, int, int, int]:
    # On Windows, os.stat() reports ftCreationTime as st_ctime_ns while os.fstat()
    # reports NTFS ChangeTime as st_ctime_ns; st_birthtime_ns matches across both.
    birth_ns = getattr(st, "st_birthtime_ns", None)
    ctime_ns = (
        int(birth_ns)
        if (os.name == "nt" and birth_ns is not None)
        else int(getattr(st, "st_ctime_ns", 0))
    )
    return (
        int(st.st_size),
        int(st.st_mtime_ns),
        ctime_ns,
        int(getattr(st, "st_ino", 0)),
        int(getattr(st, "st_dev", 0)),
    )


def _scan_spool_entries(
    spool_roots: list[Path],
    *,
    optional_roots: set[Path] | None = None,
) -> tuple[list[tuple[Path, tuple[int, int, int, int, int]]], list[SpoolIssue]]:
    """Collect `(path, (size, mtime_ns, ctime_ns, ino, dev))` for candidate `*.json` spool files."""
    entries: list[tuple[Path, tuple[int, int, int, int, int]]] = []
    issues: list[SpoolIssue] = []
    optional_keys = {str(p) for p in (optional_roots or set())}

    def _walk_dir(directory: Path) -> None:
        with os.scandir(directory) as it:
            dir_items = sorted(it, key=lambda e: e.name)
        for entry in dir_items:
            if entry.name == "quarantine" and entry.is_dir(follow_symlinks=False):
                continue
            if entry.is_dir(follow_symlinks=False):
                _walk_dir(Path(entry.path))
                continue
            if not entry.name.endswith(".json") or entry.name.startswith(".tmp."):
                continue
            try:
                st = entry.stat(follow_symlinks=False)
                if int(getattr(st, "st_ino", 0)) == 0:
                    st = os.stat(entry.path, follow_symlinks=False)
            except OSError as exc:
                issues.append(SpoolIssue(entry.path, f"Unreadable event file metadata: {exc}"))
                continue
            entries.append((Path(entry.path), _stat_tuple(st)))

    for root in spool_roots:
        try:
            exists = root.exists()
            is_dir = root.is_dir() if exists else False
        except OSError as exc:
            issues.append(SpoolIssue(str(root), f"Spool root is inaccessible: {exc}"))
            continue
        if not exists:
            if str(root) not in optional_keys:
                issues.append(SpoolIssue(str(root), "Configured external spool root does not exist or is inaccessible"))
            continue
        if not is_dir:
            issues.append(SpoolIssue(str(root), "Spool root is not a directory"))
            continue
        try:
            _walk_dir(root)
        except OSError as exc:
            issues.append(SpoolIssue(str(root), f"Failed to list spool root: {exc}"))
            continue

    return entries, issues


def _read_and_validate_spool_file(
    path: Path,
    *,
    max_event_bytes: int,
) -> tuple[SpoolRecord | None, SpoolIssue | None]:
    """Read, validate, and bind exact `os.fstat` fingerprint to the opened file handle's bytes."""
    try:
        with path.open("rb") as fh:
            st1 = os.fstat(fh.fileno())
            if st1.st_size == 0:
                return None, SpoolIssue(str(path), "Zero-byte or whitespace-only event file")
            if st1.st_size > max_event_bytes:
                return None, SpoolIssue(
                    str(path), f"Oversized event file ({st1.st_size} > {max_event_bytes} bytes)"
                )
            raw_bytes = fh.read(max_event_bytes + 1)
            st2 = os.fstat(fh.fileno())
            st_path = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        return None, SpoolIssue(str(path), f"Unreadable event file: {exc}")

    if len(raw_bytes) > max_event_bytes:
        return None, SpoolIssue(str(path), f"Oversized event file ({len(raw_bytes)} > {max_event_bytes} bytes)")

    fd1 = _stat_tuple(st1)
    fd2 = _stat_tuple(st2)
    path_fp = _stat_tuple(st_path)
    if (
        fd1 != fd2
        or int(getattr(st1, "st_ctime_ns", 0)) != int(getattr(st2, "st_ctime_ns", 0))
        or fd1 != path_fp
        or len(raw_bytes) != int(st1.st_size)
    ):
        return None, SpoolIssue(str(path), "Concurrent modification detected while reading event file")
    fp1: tuple[int, int, int, int, int] | None = fd1 if fd1[3] != 0 else None

    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, SpoolIssue(str(path), f"Malformed UTF-8: {exc}")

    if not raw_text.strip():
        return None, SpoolIssue(str(path), "Zero-byte or whitespace-only event file")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, SpoolIssue(str(path), f"Malformed JSON: {exc}")
    if not isinstance(data, dict):
        return None, SpoolIssue(str(path), "Event JSON root is not an object")

    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        return None, SpoolIssue(str(path), f"Missing required event fields: {', '.join(missing)}")
    schema_ver = data.get("event_schema_version")
    if (
        isinstance(schema_ver, bool)
        or not isinstance(schema_ver, int)
        or schema_ver not in SUPPORTED_EVENT_SCHEMA_VERSIONS
    ):
        return None, SpoolIssue(str(path), f"Unsupported event_schema_version: {schema_ver!r}")
    if not all(
        isinstance(data.get(k), str) and data.get(k, "").strip()
        for k in ("event_id", "event_type", "environment_id")
    ):
        return None, SpoolIssue(str(path), "event_id, event_type, and environment_id must be non-empty strings")
    if not isinstance(data.get("payload"), dict):
        return None, SpoolIssue(str(path), "Event payload must be a JSON object")

    try:
        envelope = EventEnvelope.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        return None, SpoolIssue(str(path), f"Invalid event schema values: {exc}")

    return (
        SpoolRecord(
            envelope=envelope,
            file_path=path,
            checksum=compute_event_checksum(envelope.to_dict()),
            fingerprint=fp1,
        ),
        None,
    )


def read_spool_events(
    spool_roots: list[Path],
    *,
    optional_roots: set[Path] | None = None,
    max_event_bytes: int = MAX_EVENT_FILE_BYTES,
) -> SpoolScanResult:
    """
    Scan all event files across spool roots without mutating spool files.

    Malformed, truncated, oversized, or schema-invalid JSON files are recorded as
    SpoolIssue entries rather than aborting valid event ingestion.
    """
    entries, issues = _scan_spool_entries(spool_roots, optional_roots=optional_roots)
    records: list[SpoolRecord] = []
    for path, _fp in entries:
        rec, issue = _read_and_validate_spool_file(path, max_event_bytes=max_event_bytes)
        if issue is not None:
            issues.append(issue)
        elif rec is not None:
            records.append(rec)

    records.sort(key=lambda r: (r.envelope.observed_timestamp, r.envelope.event_id))
    return SpoolScanResult(records=records, issues=issues, spool_roots=spool_roots)


def read_spool_events_incremental(
    spool_roots: list[Path],
    *,
    known_fingerprints: Mapping[str, tuple[int, int, int, int, int]] | None = None,
    optional_roots: set[Path] | None = None,
    max_event_bytes: int = MAX_EVENT_FILE_BYTES,
    verify_checksums: bool = False,
) -> IncrementalSpoolScanResult:
    """Read only new or modified spool files whose `(size, mtime_ns, ctime_ns, ino, dev)` is not in `known_fingerprints`."""
    entries, issues = _scan_spool_entries(spool_roots, optional_roots=optional_roots)
    known = known_fingerprints or {}
    records: list[SpoolRecord] = []
    unchanged = 0
    current_keys: set[str] = set()

    for path, fp in entries:
        key = str(path)
        if not verify_checksums and fp[3] != 0 and known.get(key) == fp:
            unchanged += 1
            current_keys.add(key)
            continue
        rec, issue = _read_and_validate_spool_file(path, max_event_bytes=max_event_bytes)
        if issue is not None:
            issues.append(issue)
        elif rec is not None:
            records.append(rec)
            current_keys.add(key)

    records.sort(key=lambda r: (r.envelope.observed_timestamp, r.envelope.event_id))
    return IncrementalSpoolScanResult(
        records=records,
        issues=issues,
        spool_roots=spool_roots,
        unchanged_count=unchanged,
        total_files=len(entries),
        current_keys=current_keys,
    )
