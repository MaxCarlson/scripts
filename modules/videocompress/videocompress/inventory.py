"""
SQLite inventory persistence, incremental caching, and library scanning.
Follows INTEGRATION_CONTRACTS.md §4 and MEDIA_SAFETY_CONTRACT.md §1, §3.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator, Mapping, Sequence

from .contracts import EligibilityDecision, SourceIdentity, VideoAsset, VideoStream
from .discovery import discover_video_files
from .eligibility import evaluate_eligibility
from .events import ProgressEmitter
from .probe import probe_video_file
from .workspace import VideoWorkspace, resolve_workspace

CURRENT_INVENTORY_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class InventoryReport:
    """Summary and details of an inventory scan."""

    target: str
    workspace_root: str
    inventory_depth: str
    total_sources: int
    eligible_sources: int
    excluded_sources: int
    unknown_sources: int
    unsupported_sources: int
    failed_sources: int
    total_bytes: int
    eligible_bytes: int
    cache_hits: int
    cache_misses: int
    pruned_sources: int
    elapsed_seconds: float
    schema_version: int = 1
    per_source_records: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target": self.target,
            "workspace_root": self.workspace_root,
            "inventory_depth": self.inventory_depth,
            "total_sources": self.total_sources,
            "eligible_sources": self.eligible_sources,
            "excluded_sources": self.excluded_sources,
            "unknown_sources": self.unknown_sources,
            "unsupported_sources": self.unsupported_sources,
            "failed_sources": self.failed_sources,
            "total_bytes": self.total_bytes,
            "eligible_bytes": self.eligible_bytes,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "pruned_sources": self.pruned_sources,
            "elapsed_seconds": self.elapsed_seconds,
            "per_source_records": list(self.per_source_records),
        }


class InventoryStore:
    """Manages the versioned SQLite inventory cache."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).resolve()
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    source_id TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL,
                    canonical_path TEXT NOT NULL,
                    file_bytes INTEGER NOT NULL,
                    stat_fingerprint TEXT NOT NULL,
                    container_format TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    primary_video_codec TEXT,
                    primary_video_width INTEGER,
                    primary_video_height INTEGER,
                    primary_video_bitrate INTEGER,
                    primary_bitrate_provenance TEXT,
                    is_hdr INTEGER NOT NULL,
                    video_stream_count INTEGER NOT NULL,
                    audio_stream_count INTEGER NOT NULL,
                    subtitle_stream_count INTEGER NOT NULL,
                    probe_status TEXT NOT NULL,
                    asset_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_canonical ON assets(canonical_path);")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS eligibility (
                    source_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reasons_json TEXT NOT NULL,
                    applied_thresholds_json TEXT NOT NULL,
                    unknowns_json TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES assets(source_id) ON DELETE CASCADE
                );
            """)

            # Schema version check / set
            cur = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'")
            row = cur.fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                    (str(CURRENT_INVENTORY_SCHEMA),),
                )
            elif int(row["value"]) != CURRENT_INVENTORY_SCHEMA:
                raise ValueError(
                    f"Unsupported inventory schema version {row['value']} (expected {CURRENT_INVENTORY_SCHEMA})"
                )

    def get_asset(self, source_id: str) -> tuple[VideoAsset, str] | None:
        """Retrieve cached asset and its recorded stat_fingerprint."""
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT asset_json, stat_fingerprint FROM assets WHERE source_id = ?",
                (source_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            data = json.loads(row["asset_json"])
            return VideoAsset.from_dict(data), row["stat_fingerprint"]

    def find_by_canonical_path(self, canonical_path: str) -> tuple[VideoAsset, str] | None:
        """Find cached asset by its canonical filesystem path."""
        norm_path = canonical_path.lower() if os.name == "nt" else canonical_path
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT asset_json, stat_fingerprint FROM assets WHERE canonical_path = ?",
                (norm_path,),
            )
            row = cur.fetchone()
            if not row:
                return None
            data = json.loads(row["asset_json"])
            return VideoAsset.from_dict(data), row["stat_fingerprint"]

    def save_asset(self, asset: VideoAsset, canonical_path: str, stat_fingerprint: str) -> None:
        """Insert or replace an asset record in SQLite."""
        norm_path = canonical_path.lower() if os.name == "nt" else canonical_path
        pv = asset.primary_video_stream
        video_count = sum(1 for s in asset.streams if s.stream_type == "video")
        audio_count = sum(1 for s in asset.streams if s.stream_type == "audio")
        sub_count = sum(1 for s in asset.streams if s.stream_type == "subtitle")
        is_hdr_int = 1 if pv and pv.is_hdr else 0
        now = datetime.now(timezone.utc).isoformat()
        asset_json_str = json.dumps(asset.to_dict())

        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO assets (
                    source_id, relative_path, canonical_path, file_bytes, stat_fingerprint,
                    container_format, duration_seconds, primary_video_codec,
                    primary_video_width, primary_video_height, primary_video_bitrate,
                    primary_bitrate_provenance, is_hdr, video_stream_count,
                    audio_stream_count, subtitle_stream_count, probe_status,
                    asset_json, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.source_id,
                    asset.relative_path,
                    norm_path,
                    asset.file_bytes,
                    stat_fingerprint,
                    asset.container_format,
                    asset.duration_seconds,
                    pv.codec_name if pv else None,
                    pv.width if pv else None,
                    pv.height if pv else None,
                    pv.bit_rate_bps if pv else None,
                    pv.bitrate_provenance if pv else None,
                    is_hdr_int,
                    video_count,
                    audio_count,
                    sub_count,
                    asset.probe_status,
                    asset_json_str,
                    now,
                ),
            )

    def save_eligibility(self, source_id: str, decision: EligibilityDecision) -> None:
        """Insert or replace eligibility decision in SQLite."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eligibility (
                    source_id, stage, status, reasons_json, applied_thresholds_json,
                    unknowns_json, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    decision.stage,
                    decision.status,
                    json.dumps(decision.reasons),
                    json.dumps(decision.applied_thresholds),
                    json.dumps(decision.unknowns),
                    now,
                ),
            )

    def get_eligibility(self, source_id: str) -> EligibilityDecision | None:
        """Retrieve stored eligibility decision for an asset."""
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT stage, status, reasons_json, applied_thresholds_json, unknowns_json FROM eligibility WHERE source_id = ?",
                (source_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return EligibilityDecision(
                stage=row["stage"],
                status=row["status"],
                reasons=tuple(json.loads(row["reasons_json"])),
                applied_thresholds=json.loads(row["applied_thresholds_json"]),
                unknowns=tuple(json.loads(row["unknowns_json"])),
            )

    def list_assets(self) -> list[VideoAsset]:
        """Return all stored VideoAssets."""
        with self._conn() as conn:
            cur = conn.execute("SELECT asset_json FROM assets ORDER BY relative_path ASC")
            return [VideoAsset.from_dict(json.loads(r["asset_json"])) for r in cur.fetchall()]

    def get_canonical_paths(self) -> dict[str, str]:
        """Return a mapping of source_id -> canonical_path for all stored assets."""
        with self._conn() as conn:
            cur = conn.execute("SELECT source_id, canonical_path FROM assets")
            return {r["source_id"]: r["canonical_path"] for r in cur.fetchall()}

    def prune_stale(self, current_canonical_paths: set[str]) -> int:
        """Delete records for files that no longer exist in the discovered set."""
        norm_current = {p.lower() if os.name == "nt" else p for p in current_canonical_paths}
        with self._conn() as conn:
            cur = conn.execute("SELECT source_id, canonical_path FROM assets")
            rows = cur.fetchall()
            to_delete = [r["source_id"] for r in rows if r["canonical_path"] not in norm_current]
            if to_delete:
                conn.executemany("DELETE FROM assets WHERE source_id = ?", [(sid,) for sid in to_delete])
            return len(to_delete)


def scan_inventory(
    target: Path | str,
    workspace_root: Path | str | None = None,
    min_video_bitrate: int | str | None = None,
    min_resolution: str | tuple[int, int] | None = None,
    min_size: int | str | None = None,
    min_duration: float | str | None = None,
    inventory_depth: str = "probe",
    emitter: ProgressEmitter | None = None,
    force_refresh: bool = False,
) -> InventoryReport:
    """
    Perform an inventory scan of target media, using SQLite caching and eligibility filtering.
    Entirely non-destructive: zero media files modified, zero encodings performed.
    """
    start_time = time.perf_counter()
    target_path = Path(target).expanduser().resolve()
    ws = resolve_workspace(target_path, workspace_root)
    store = InventoryStore(ws.inventory_db)

    # 1. Discovery
    if emitter:
        emitter.emit("discovery_started", phase="discovery", message=f"Discovering media under {target_path}")

    discovered = discover_video_files(target_path, workspace_root=ws.root)
    total_sources = len(discovered)

    if emitter:
        emitter.emit(
            "discovery_completed",
            phase="discovery",
            current=total_sources,
            total=total_sources,
            message=f"Discovered {total_sources} candidate media files",
        )

    cache_hits = 0
    cache_misses = 0
    per_source_records: list[dict[str, Any]] = []

    current_canonical_paths: set[str] = set()
    total_bytes = 0
    eligible_bytes = 0
    eligible_count = 0
    excluded_count = 0
    unknown_count = 0
    unsupported_count = 0
    failed_count = 0

    if emitter:
        emitter.emit("probe_started", phase="probe", total=total_sources)

    # 2. Probe & Filter
    for idx, item in enumerate(discovered, start=1):
        current_canonical_paths.add(item.canonical_path)
        asset: VideoAsset | None = None

        if inventory_depth == "files":
            # Files depth: stat only, no decoder or probe
            try:
                st = Path(item.canonical_path).stat()
                file_size = st.st_size
            except OSError:
                file_size = 0

            norm_canon = item.canonical_path.lower() if os.name == "nt" else item.canonical_path
            source_id = hashlib.sha256(norm_canon.encode("utf-8")).hexdigest()[:16]

            # Check cache
            cached = store.find_by_canonical_path(item.canonical_path)
            if not force_refresh and cached and cached[1] == item.stat_fingerprint:
                asset = cached[0]
                cache_hits += 1
            else:
                asset = VideoAsset(
                    source_id=source_id,
                    relative_path=item.relative_path,
                    file_bytes=file_size,
                    container_format=Path(item.relative_path).suffix.lstrip("."),
                    duration_seconds=0.0,
                    streams=(),
                    probe_status="files_only",
                )
                store.save_asset(asset, item.canonical_path, item.stat_fingerprint)
                cache_misses += 1
        else:
            # Probe depth: check SQLite cache first
            cached = store.find_by_canonical_path(item.canonical_path)
            if not force_refresh and cached and cached[1] == item.stat_fingerprint:
                asset = cached[0]
                cache_hits += 1
            else:
                cache_misses += 1
                asset = probe_video_file(item.canonical_path, relative_path=item.relative_path)
                store.save_asset(asset, item.canonical_path, item.stat_fingerprint)

        # 3. Eligibility evaluation
        decision = evaluate_eligibility(
            asset,
            min_video_bitrate=min_video_bitrate,
            min_resolution=min_resolution,
            min_size=min_size,
            min_duration=min_duration,
        )
        store.save_eligibility(asset.source_id, decision)

        total_bytes += asset.file_bytes
        if decision.status == "eligible":
            eligible_count += 1
            eligible_bytes += asset.file_bytes
        elif decision.status == "excluded":
            excluded_count += 1
        elif decision.status == "unknown":
            unknown_count += 1
        elif decision.status == "unsupported":
            unsupported_count += 1
        else:
            failed_count += 1

        pv = asset.primary_video_stream
        record = {
            "source_id": asset.source_id,
            "relative_path": asset.relative_path,
            "file_bytes": asset.file_bytes,
            "duration_seconds": asset.duration_seconds,
            "container_format": asset.container_format,
            "primary_video": {
                "codec": pv.codec_name if pv else None,
                "width": pv.width if pv else None,
                "height": pv.height if pv else None,
                "bit_rate_bps": pv.bit_rate_bps if pv else None,
                "bitrate_provenance": pv.bitrate_provenance if pv else None,
                "is_hdr": pv.is_hdr if pv else False,
                "rotation": pv.rotation_degrees if pv else 0,
            } if pv else None,
            "streams_summary": {
                "video": sum(1 for s in asset.streams if s.stream_type == "video"),
                "audio": sum(1 for s in asset.streams if s.stream_type == "audio"),
                "subtitle": sum(1 for s in asset.streams if s.stream_type == "subtitle"),
            },
            "eligibility": decision.to_dict(),
        }
        per_source_records.append(record)

        if emitter:
            emitter.emit(
                "probe_item",
                phase="probe",
                current=idx,
                total=total_sources,
                source_id=asset.source_id,
                relative_path=asset.relative_path,
                status=decision.status,
                message=f"[{decision.status.upper()}] {asset.relative_path}",
            )

    # 4. Prune stale cache records for deleted files
    pruned = store.prune_stale(current_canonical_paths)

    if emitter:
        emitter.emit(
            "inventory_summary",
            phase="summary",
            current=total_sources,
            total=total_sources,
            message=f"Inventory complete: {eligible_count} eligible, {excluded_count} excluded, {unknown_count} unknown",
        )

    elapsed = time.perf_counter() - start_time
    return InventoryReport(
        target=str(target_path),
        workspace_root=str(ws.root),
        inventory_depth=inventory_depth,
        total_sources=total_sources,
        eligible_sources=eligible_count,
        excluded_sources=excluded_count,
        unknown_sources=unknown_count,
        unsupported_sources=unsupported_count,
        failed_sources=failed_count,
        total_bytes=total_bytes,
        eligible_bytes=eligible_bytes,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        pruned_sources=pruned,
        elapsed_seconds=elapsed,
        per_source_records=tuple(per_source_records),
    )
