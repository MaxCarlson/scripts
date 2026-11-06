"""File-identity-bound cache for AEBN media verified under the current contract."""

from __future__ import annotations

import math
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit


AEBN_VALIDATION_CONTRACT = 3
_NAME = "aebn-verified-media.sqlite3"


def is_aebn_url(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower().endswith(".aebn.com")
    except ValueError:
        return False


def validated_aebn_event(event: dict) -> bool:
    """Accept only the current AEBN A/V and full packet-scan validation contract."""
    if event.get("event") not in {"complete", "already"} or not event.get("path"):
        return False
    try:
        identity = _identity(Path(event["path"]))
    except (TypeError, ValueError):
        return False
    if identity is None:
        return False
    if event["event"] == "complete" and (
        isinstance(event.get("file_size"), bool) or event.get("file_size") != identity[3]
    ):
        return False
    validation = event.get("validation")
    if not isinstance(validation, dict) or validation.get("valid") is not True:
        return False
    if validation.get("validation_contract") != AEBN_VALIDATION_CONTRACT:
        return False
    evidence = validation.get("evidence")
    if not isinstance(evidence, dict):
        return False
    try:
        duration = float(evidence["expected_duration_s"])
        streams = evidence["streams"]
        continuity = evidence["video_continuity"]
        required = {"packet_count", "invalid_packets", "dts_regressions", "max_pts_gap_s", "max_dts_gap_s",
                    "longest_tiny_duration_run", "longest_tiny_dts_run"}
        if not (math.isfinite(duration) and duration > 0 and isinstance(streams, dict)
                and {"video", "audio"}.issubset(streams) and isinstance(continuity, dict)
                and required.issubset(continuity)):
            return False
        tolerance = min(max(8.0, duration * 0.05), duration * 0.2)
        for kind in ("video", "audio"):
            stream_duration = float(streams[kind]["duration_s"])
            span = float(streams[kind]["packet_span_s"])
            packet_count = int(streams[kind]["packet_count"])
            if (not math.isfinite(stream_duration) or not math.isfinite(span) or packet_count <= 0
                    or abs(stream_duration - duration) > tolerance or span < duration - tolerance):
                return False
        if not all(math.isfinite(float(continuity[key])) for key in required):
            return False
        limit = max(10.0, duration * 0.05)
        return (continuity["packet_count"] > 0 and continuity["invalid_packets"] == 0
                and (duration < 60 or continuity["packet_count"] / duration >= 0.2)
                and continuity["dts_regressions"] == 0 and continuity["max_pts_gap_s"] <= limit
                and continuity["max_dts_gap_s"] <= limit and continuity["longest_tiny_duration_run"] < 100
                and continuity["longest_tiny_dts_run"] < 100)
    except (KeyError, TypeError, ValueError):
        return False


def _identity(path: Path) -> tuple[str, str, str, int, int, int] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
        return (str(resolved), str(stat.st_dev), str(stat.st_ino), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except OSError:
        return None


def record_verified_output(archive_dir: Path, url: str, event: dict) -> bool:
    if not is_aebn_url(url) or not validated_aebn_event(event):
        return False
    identity = _identity(Path(event["path"]))
    if identity is None:
        return False
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for attempt in range(5):
            try:
                with sqlite3.connect(str(archive_dir / _NAME), timeout=5) as db:
                    db.execute("PRAGMA busy_timeout=5000")
                    db.execute("PRAGMA journal_mode=WAL")
                    db.execute("CREATE TABLE IF NOT EXISTS verified (url TEXT PRIMARY KEY, path TEXT NOT NULL, "
                               "device TEXT NOT NULL, inode TEXT NOT NULL, size INTEGER NOT NULL, "
                               "mtime_ns INTEGER NOT NULL, ctime_ns INTEGER NOT NULL, contract INTEGER NOT NULL)")
                    db.execute("INSERT OR REPLACE INTO verified VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (url, *identity, AEBN_VALIDATION_CONTRACT))
                return True
            except sqlite3.OperationalError as exc:
                if attempt == 4 or not any(word in str(exc).lower() for word in ("locked", "busy")):
                    raise
                time.sleep(0.05 * (attempt + 1))
    except (OSError, sqlite3.Error, OverflowError):
        return False


def current_verified_urls(archive_dir: Path | None) -> set[str]:
    if archive_dir is None:
        return set()
    path = archive_dir / _NAME
    if not path.is_file():
        return set()
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
            rows = db.execute("SELECT url, path, device, inode, size, mtime_ns, ctime_ns, contract FROM verified")
            return {url for url, file_path, device, inode, size, mtime, ctime, contract in rows
                    if contract == AEBN_VALIDATION_CONTRACT and is_aebn_url(url)
                    and _identity(Path(file_path)) == (file_path, device, inode, size, mtime, ctime)}
    except (OSError, sqlite3.Error, ValueError, OverflowError):
        return set()
