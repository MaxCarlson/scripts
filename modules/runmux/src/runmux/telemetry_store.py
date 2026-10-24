"""Persistent SQLite storage, rollups, and bounded querying for Runmux historical telemetry."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator

from runmux.constants import TERMINAL_STATUSES
from runmux.models import RunRecord, parse_iso_datetime, utc_now_iso
from runmux.platform_paths import ensure_state_tree, get_state_dir
from runmux.stats import HostTelemetry, ProcessStats

logger = logging.getLogger(__name__)

# Nominal thresholds
DEFAULT_RAW_RETENTION_SECONDS = 3600.0        # 1 hour
DEFAULT_ROLLUP_1M_RETENTION_SECONDS = 86400.0  # 24 hours
DEFAULT_ROLLUP_5M_RETENTION_SECONDS = 604800.0 # 7 days
DEFAULT_STORAGE_BUDGET_BYTES = 50 * 1024 * 1024 # 50 MB target storage budget
MAX_RETURNED_POINTS = 1000
DEFAULT_RETURNED_POINTS = 300


@dataclass(frozen=True)
class TelemetryQueryPoint:
    timestamp: str
    epoch: float
    sample_interval_seconds: float | None
    cpu_percent: float | None
    cpu_percent_normalized: float | None
    rss_bytes: int | None
    read_bytes_per_second: float | None
    write_bytes_per_second: float | None
    process_count: int
    thread_count: int
    gpu_memory_bytes: int | None
    is_gap: bool = False
    gap_reason: str | None = None
    cpu_percent_min: float | None = None
    cpu_percent_max: float | None = None
    rss_bytes_max: int | None = None
    run_id: str | None = None


class TelemetryStore:
    """Manages separate SQLite-backed time-series history for Runmux processes and host."""

    def __init__(
        self,
        state_dir: Path | str | None = None,
        *,
        raw_retention_seconds: float = DEFAULT_RAW_RETENTION_SECONDS,
        rollup_1m_retention_seconds: float = DEFAULT_ROLLUP_1M_RETENTION_SECONDS,
        rollup_5m_retention_seconds: float = DEFAULT_ROLLUP_5M_RETENTION_SECONDS,
        max_budget_bytes: int = DEFAULT_STORAGE_BUDGET_BYTES,
        auto_init: bool = True,
    ) -> None:
        raw_dir = Path(state_dir) if state_dir else get_state_dir()
        self.state_dir = ensure_state_tree(raw_dir) if auto_init else raw_dir.expanduser().resolve()
        self.db_path = self.state_dir / "telemetry.sqlite3"
        self.wal_path = self.state_dir / "telemetry.sqlite3-wal"
        self.raw_retention_seconds = raw_retention_seconds
        self.rollup_1m_retention_seconds = rollup_1m_retention_seconds
        self.rollup_5m_retention_seconds = rollup_5m_retention_seconds
        self.max_budget_bytes = max_budget_bytes
        self.auto_init = auto_init
        if auto_init:
            self.init_db()

    def connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with Runmux telemetry performance settings."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA page_size = 4096")
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def session(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that ensures the SQLite connection is strictly closed on exit."""
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        ensure_state_tree(self.state_dir)
        with self.session() as conn:
            av = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
            if av != 2:
                conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
                conn.execute("VACUUM")

            conn.executescript("""
                CREATE TABLE IF NOT EXISTS telemetry_raw (
                    run_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    sampled_at TEXT NOT NULL,
                    cpu_percent REAL,
                    cpu_percent_normalized REAL,
                    rss_bytes INTEGER,
                    read_bytes_per_sec REAL,
                    write_bytes_per_sec REAL,
                    process_count INTEGER NOT NULL,
                    thread_count INTEGER NOT NULL,
                    gpu_memory_bytes INTEGER,
                    PRIMARY KEY (run_id, timestamp)
                ) WITHOUT ROWID;

                CREATE INDEX IF NOT EXISTS idx_telemetry_raw_timestamp ON telemetry_raw(timestamp);

                CREATE TABLE IF NOT EXISTS telemetry_rollup_1m (
                    run_id TEXT NOT NULL,
                    bucket_epoch INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL,
                    cpu_avg REAL,
                    cpu_min REAL,
                    cpu_max REAL,
                    rss_avg INTEGER,
                    rss_max INTEGER,
                    read_bytes_sec_avg REAL,
                    write_bytes_sec_avg REAL,
                    gpu_memory_bytes_max INTEGER,
                    PRIMARY KEY (run_id, bucket_epoch)
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS telemetry_rollup_5m (
                    run_id TEXT NOT NULL,
                    bucket_epoch INTEGER NOT NULL,
                    sample_count INTEGER NOT NULL,
                    cpu_avg REAL,
                    cpu_min REAL,
                    cpu_max REAL,
                    rss_avg INTEGER,
                    rss_max INTEGER,
                    read_bytes_sec_avg REAL,
                    write_bytes_sec_avg REAL,
                    gpu_memory_bytes_max INTEGER,
                    PRIMARY KEY (run_id, bucket_epoch)
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS host_telemetry_raw (
                    timestamp REAL PRIMARY KEY,
                    sampled_at TEXT NOT NULL,
                    cpu_percent REAL,
                    memory_used_bytes INTEGER,
                    memory_available_bytes INTEGER,
                    net_read_bytes_sec REAL,
                    net_write_bytes_sec REAL
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS host_telemetry_rollup_1m (
                    bucket_epoch INTEGER PRIMARY KEY,
                    sample_count INTEGER NOT NULL,
                    cpu_avg REAL,
                    cpu_min REAL,
                    cpu_max REAL,
                    memory_used_avg INTEGER,
                    memory_used_max INTEGER,
                    net_read_sec_avg REAL,
                    net_write_sec_avg REAL
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS host_telemetry_rollup_5m (
                    bucket_epoch INTEGER PRIMARY KEY,
                    sample_count INTEGER NOT NULL,
                    cpu_avg REAL,
                    cpu_min REAL,
                    cpu_max REAL,
                    memory_used_avg INTEGER,
                    memory_used_max INTEGER,
                    net_read_sec_avg REAL,
                    net_write_sec_avg REAL
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS telemetry_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    reason TEXT,
                    details_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_telemetry_events_run ON telemetry_events(run_id, timestamp);
            """)

            # Ensure cpu_min exists on pre-existing 5m rollup tables if opened from older schema
            try:
                conn.execute("ALTER TABLE telemetry_rollup_5m ADD COLUMN cpu_min REAL")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE host_telemetry_rollup_5m ADD COLUMN cpu_min REAL")
            except sqlite3.OperationalError:
                pass

    def insert_process_samples(self, samples: list[ProcessStats]) -> None:
        """Batch insert process metric samples into telemetry_raw."""
        if not samples:
            return
        if not self.db_path.exists():
            ensure_state_tree(self.state_dir)
            self.init_db()
        rows = []
        for s in samples:
            t = getattr(s, "sampled_epoch", None)
            if t is None:
                try:
                    t = parse_iso_datetime(s.sampled_at).timestamp() if s.sampled_at else time.time()
                except (ValueError, TypeError):
                    t = time.time()
            rows.append((
                s.record.id,
                t,
                s.sampled_at or utc_now_iso(),
                s.cpu_percent,
                s.cpu_percent_normalized,
                s.rss_bytes,
                s.read_bytes_per_second,
                s.write_bytes_per_second,
                s.process_count,
                s.thread_count,
                s.gpu_memory_bytes,
            ))

        try:
            with self.session() as conn:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO telemetry_raw (
                        run_id, timestamp, sampled_at, cpu_percent, cpu_percent_normalized,
                        rss_bytes, read_bytes_per_sec, write_bytes_per_sec,
                        process_count, thread_count, gpu_memory_bytes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        except sqlite3.OperationalError as error:
            logger.warning("Failed to insert process samples, attempting storage budget recovery: %s", error)
            self.enforce_storage_budget()

    def insert_host_sample(self, host: HostTelemetry) -> None:
        """Insert host-level metrics into host_telemetry_raw."""
        if not self.db_path.exists():
            ensure_state_tree(self.state_dir)
            self.init_db()
        t = getattr(host, "sampled_epoch", None)
        if t is None:
            try:
                t = parse_iso_datetime(host.sampled_at).timestamp() if host.sampled_at else time.time()
            except (ValueError, TypeError):
                t = time.time()

        try:
            with self.session() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO host_telemetry_raw (
                        timestamp, sampled_at, cpu_percent, memory_used_bytes,
                        memory_available_bytes, net_read_bytes_sec, net_write_bytes_sec
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t,
                        host.sampled_at or utc_now_iso(),
                        host.cpu_percent,
                        host.memory_used_bytes,
                        host.memory_available_bytes,
                        host.net_read_bytes_per_second,
                        host.net_write_bytes_per_second,
                    ),
                )
        except sqlite3.OperationalError as error:
            logger.warning("Failed to insert host sample, attempting storage budget recovery: %s", error)
            self.enforce_storage_budget()

    def record_event(
        self,
        run_id: str,
        event_type: str,
        *,
        timestamp: float | None = None,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a discrete run lifecycle event (pause, resume, restart, exit)."""
        t = timestamp if timestamp is not None else time.time()
        details_str = json.dumps(details) if details else None
        try:
            with self.session() as conn:
                conn.execute(
                    "INSERT INTO telemetry_events (run_id, timestamp, event_type, reason, details_json) VALUES (?, ?, ?, ?, ?)",
                    (run_id, t, event_type, reason, details_str),
                )
        except sqlite3.OperationalError as error:
            logger.warning("Failed to record event: %s", error)

    def generate_rollups(self, now: float | None = None) -> None:
        """Aggregate raw data into 1-minute rollups and 1-minute into 5-minute rollups using sample-weighted averages."""
        ref_time = now if now is not None else time.time()
        completed_1m_boundary = int(ref_time // 60) * 60
        completed_5m_boundary = int(ref_time // 300) * 300

        with self.session() as conn:
            # 1. Process 1-minute rollup from raw samples
            conn.execute(
                """
                INSERT OR REPLACE INTO telemetry_rollup_1m
                SELECT
                    run_id,
                    CAST(timestamp / 60 AS INTEGER) * 60 AS bucket_epoch,
                    COUNT(*) AS sample_count,
                    AVG(cpu_percent) AS cpu_avg,
                    MIN(cpu_percent) AS cpu_min,
                    MAX(cpu_percent) AS cpu_max,
                    CAST(ROUND(AVG(rss_bytes)) AS INTEGER) AS rss_avg,
                    MAX(rss_bytes) AS rss_max,
                    AVG(read_bytes_per_sec) AS read_bytes_sec_avg,
                    AVG(write_bytes_per_sec) AS write_bytes_sec_avg,
                    MAX(gpu_memory_bytes) AS gpu_memory_bytes_max
                FROM telemetry_raw
                WHERE timestamp < ?
                GROUP BY run_id, CAST(timestamp / 60 AS INTEGER) * 60
                """,
                (completed_1m_boundary,),
            )

            # 2. Process 5-minute rollup with sample-count-weighted averages and strict null preservation
            conn.execute(
                """
                INSERT OR REPLACE INTO telemetry_rollup_5m
                SELECT
                    run_id,
                    CAST(bucket_epoch / 300 AS INTEGER) * 300 AS bucket_epoch,
                    SUM(sample_count) AS sample_count,
                    SUM(CASE WHEN cpu_avg IS NOT NULL THEN cpu_avg * sample_count END) * 1.0 / NULLIF(SUM(CASE WHEN cpu_avg IS NOT NULL THEN sample_count ELSE 0 END), 0) AS cpu_avg,
                    MIN(cpu_min) AS cpu_min,
                    MAX(cpu_max) AS cpu_max,
                    CAST(ROUND(SUM(CASE WHEN rss_avg IS NOT NULL THEN rss_avg * sample_count END) * 1.0 / NULLIF(SUM(CASE WHEN rss_avg IS NOT NULL THEN sample_count ELSE 0 END), 0)) AS INTEGER) AS rss_avg,
                    MAX(rss_max) AS rss_max,
                    SUM(CASE WHEN read_bytes_sec_avg IS NOT NULL THEN read_bytes_sec_avg * sample_count END) * 1.0 / NULLIF(SUM(CASE WHEN read_bytes_sec_avg IS NOT NULL THEN sample_count ELSE 0 END), 0) AS read_bytes_sec_avg,
                    SUM(CASE WHEN write_bytes_sec_avg IS NOT NULL THEN write_bytes_sec_avg * sample_count END) * 1.0 / NULLIF(SUM(CASE WHEN write_bytes_sec_avg IS NOT NULL THEN sample_count ELSE 0 END), 0) AS write_bytes_sec_avg,
                    MAX(gpu_memory_bytes_max) AS gpu_memory_bytes_max
                FROM telemetry_rollup_1m
                WHERE bucket_epoch < ?
                GROUP BY run_id, CAST(bucket_epoch / 300 AS INTEGER) * 300
                """,
                (completed_5m_boundary,),
            )

            # 3. Host 1-minute rollup
            conn.execute(
                """
                INSERT OR REPLACE INTO host_telemetry_rollup_1m
                SELECT
                    CAST(timestamp / 60 AS INTEGER) * 60 AS bucket_epoch,
                    COUNT(*) AS sample_count,
                    AVG(cpu_percent) AS cpu_avg,
                    MIN(cpu_percent) AS cpu_min,
                    MAX(cpu_percent) AS cpu_max,
                    CAST(ROUND(AVG(memory_used_bytes)) AS INTEGER) AS memory_used_avg,
                    MAX(memory_used_bytes) AS memory_used_max,
                    AVG(net_read_bytes_sec) AS net_read_sec_avg,
                    AVG(net_write_bytes_sec) AS net_write_sec_avg
                FROM host_telemetry_raw
                WHERE timestamp < ?
                GROUP BY CAST(timestamp / 60 AS INTEGER) * 60
                """,
                (completed_1m_boundary,),
            )

            # 4. Host 5-minute rollup with sample-count-weighted averages
            conn.execute(
                """
                INSERT OR REPLACE INTO host_telemetry_rollup_5m
                SELECT
                    CAST(bucket_epoch / 300 AS INTEGER) * 300 AS bucket_epoch,
                    SUM(sample_count) AS sample_count,
                    SUM(CASE WHEN cpu_avg IS NOT NULL THEN cpu_avg * sample_count END) * 1.0 / NULLIF(SUM(CASE WHEN cpu_avg IS NOT NULL THEN sample_count ELSE 0 END), 0) AS cpu_avg,
                    MIN(cpu_min) AS cpu_min,
                    MAX(cpu_max) AS cpu_max,
                    CAST(ROUND(SUM(CASE WHEN memory_used_avg IS NOT NULL THEN memory_used_avg * sample_count END) * 1.0 / NULLIF(SUM(CASE WHEN memory_used_avg IS NOT NULL THEN sample_count ELSE 0 END), 0)) AS INTEGER) AS memory_used_avg,
                    MAX(memory_used_max) AS memory_used_max,
                    SUM(CASE WHEN net_read_sec_avg IS NOT NULL THEN net_read_sec_avg * sample_count END) * 1.0 / NULLIF(SUM(CASE WHEN net_read_sec_avg IS NOT NULL THEN sample_count ELSE 0 END), 0) AS net_read_sec_avg,
                    SUM(CASE WHEN net_write_sec_avg IS NOT NULL THEN net_write_sec_avg * sample_count END) * 1.0 / NULLIF(SUM(CASE WHEN net_write_sec_avg IS NOT NULL THEN sample_count ELSE 0 END), 0) AS net_write_sec_avg
                FROM host_telemetry_rollup_1m
                WHERE bucket_epoch < ?
                GROUP BY CAST(bucket_epoch / 300 AS INTEGER) * 300
                """,
                (completed_5m_boundary,),
            )

    def prune_retention(self, now: float | None = None) -> None:
        """Prune samples exceeding retention horizons."""
        ref_time = now if now is not None else time.time()
        raw_cutoff = ref_time - self.raw_retention_seconds
        rollup_1m_cutoff = ref_time - self.rollup_1m_retention_seconds
        rollup_5m_cutoff = ref_time - self.rollup_5m_retention_seconds

        with self.session() as conn:
            conn.execute("DELETE FROM telemetry_raw WHERE timestamp < ?", (raw_cutoff,))
            conn.execute("DELETE FROM telemetry_rollup_1m WHERE bucket_epoch < ?", (int(rollup_1m_cutoff),))
            conn.execute("DELETE FROM telemetry_rollup_5m WHERE bucket_epoch < ?", (int(rollup_5m_cutoff),))

            conn.execute("DELETE FROM host_telemetry_raw WHERE timestamp < ?", (raw_cutoff,))
            conn.execute("DELETE FROM host_telemetry_rollup_1m WHERE bucket_epoch < ?", (int(rollup_1m_cutoff),))
            conn.execute("DELETE FROM host_telemetry_rollup_5m WHERE bucket_epoch < ?", (int(rollup_5m_cutoff),))

            conn.execute("DELETE FROM telemetry_events WHERE timestamp < ?", (rollup_5m_cutoff,))

    def checkpoint_wal(self) -> tuple[int, int, int]:
        """Checkpoint and truncate the WAL file. Returns (busy, log_pages, checkpointed_pages)."""
        if not self.db_path.exists():
            return 0, 0, 0
        try:
            with self.session() as conn:
                row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                return int(row[0]), int(row[1]), int(row[2])
        except sqlite3.OperationalError as error:
            logger.warning("WAL checkpoint deferred: %s", error)
            return 1, 0, 0

    def vacuum(self) -> None:
        """Run full VACUUM outside of a transaction to reclaim all freed pages."""
        if not self.db_path.exists():
            return
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError as error:
            logger.warning("VACUUM deferred: %s", error)
        finally:
            conn.close()

    def incremental_vacuum(self, max_pages: int = 500) -> None:
        """Reclaim unused pages from the SQLite freelist."""
        if not self.db_path.exists():
            return
        try:
            with self.session() as conn:
                freelist_count = conn.execute("PRAGMA freelist_count").fetchone()[0]
                if freelist_count > 0:
                    conn.execute(f"PRAGMA incremental_vacuum({min(freelist_count, max_pages)})")
        except sqlite3.OperationalError as error:
            logger.warning("Incremental vacuum deferred: %s", error)

    def total_disk_bytes(self) -> int:
        """Return combined physical size of main database and WAL file."""
        total = 0
        if self.db_path.exists():
            total += self.db_path.stat().st_size
        if self.wal_path.exists():
            total += self.wal_path.stat().st_size
        return total

    def enforce_storage_budget(self, max_bytes: int | None = None) -> bool:
        """Enforce target disk budget with multi-stage emergency pruning and graceful degradation."""
        budget = max_bytes if max_bytes is not None else self.max_budget_bytes
        self.checkpoint_wal()
        self.incremental_vacuum(1000)

        current_size = self.total_disk_bytes()
        if current_size <= budget:
            return True

        now = time.time()
        # Stage 1: Prune oldest half of 5-minute rollups (> 3.5 days)
        try:
            with self.session() as conn:
                conn.execute(
                    "DELETE FROM telemetry_rollup_5m WHERE bucket_epoch < ?",
                    (int(now - (self.rollup_5m_retention_seconds / 2)),),
                )
                conn.execute(
                    "DELETE FROM host_telemetry_rollup_5m WHERE bucket_epoch < ?",
                    (int(now - (self.rollup_5m_retention_seconds / 2)),),
                )
            self.checkpoint_wal()
            self.incremental_vacuum(2000)
        except sqlite3.OperationalError as error:
            logger.warning("Budget pruning Stage 1 deferred: %s", error)

        if self.total_disk_bytes() <= budget:
            return True

        # Stage 2: Prune all 5m rollups older than 24h, and raw retention down to 30 minutes
        try:
            with self.session() as conn:
                conn.execute("DELETE FROM telemetry_rollup_5m WHERE bucket_epoch < ?", (int(now - 86400.0),))
                conn.execute("DELETE FROM host_telemetry_rollup_5m WHERE bucket_epoch < ?", (int(now - 86400.0),))
                conn.execute("DELETE FROM telemetry_raw WHERE timestamp < ?", (now - 1800.0,))
                conn.execute("DELETE FROM host_telemetry_raw WHERE timestamp < ?", (now - 1800.0,))
            self.checkpoint_wal()
            self.incremental_vacuum(2000)
        except sqlite3.OperationalError as error:
            logger.warning("Budget pruning Stage 2 deferred: %s", error)

        if self.total_disk_bytes() <= budget:
            return True

        # Stage 3: Emergency raw down to 15m, 1m rollups down to 6h, full VACUUM
        try:
            with self.session() as conn:
                conn.execute("DELETE FROM telemetry_raw WHERE timestamp < ?", (now - 900.0,))
                conn.execute("DELETE FROM host_telemetry_raw WHERE timestamp < ?", (now - 900.0,))
                conn.execute("DELETE FROM telemetry_rollup_1m WHERE bucket_epoch < ?", (int(now - 21600.0),))
                conn.execute("DELETE FROM host_telemetry_rollup_1m WHERE bucket_epoch < ?", (int(now - 21600.0),))
            self.vacuum()
            self.checkpoint_wal()
        except sqlite3.OperationalError as error:
            logger.warning("Budget pruning Stage 3 deferred: %s", error)

        if self.total_disk_bytes() <= budget:
            return True

        # Stage 4: Critical overflow protection: shed oldest down to 1h rollups
        try:
            with self.session() as conn:
                conn.execute("DELETE FROM telemetry_rollup_5m")
                conn.execute("DELETE FROM host_telemetry_rollup_5m")
                conn.execute("DELETE FROM telemetry_rollup_1m WHERE bucket_epoch < ?", (int(now - 3600.0),))
                conn.execute("DELETE FROM host_telemetry_rollup_1m WHERE bucket_epoch < ?", (int(now - 3600.0),))
                conn.execute("DELETE FROM telemetry_raw WHERE timestamp < ?", (now - 300.0,))
                conn.execute("DELETE FROM host_telemetry_raw WHERE timestamp < ?", (now - 300.0,))
            self.vacuum()
            self.checkpoint_wal()
        except sqlite3.OperationalError as error:
            logger.warning("Budget pruning Stage 4 deferred: %s", error)

        return self.total_disk_bytes() <= budget

    def check_integrity(self) -> bool:
        """Run SQLite integrity check."""
        if not self.db_path.exists():
            return True
        try:
            with open(self.db_path, "rb") as f:
                header = f.read(16)
                if header != b"SQLite format 3\x00":
                    return False
            conn = self.connect()
            try:
                rows = conn.execute("PRAGMA integrity_check").fetchall()
                return len(rows) == 1 and rows[0][0] == "ok"
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            return False

    def quarantine_and_reset(self) -> Path | None:
        """Move corrupted database AND accompanying WAL/SHM files to quarantine, preserving recoverable WAL data."""
        if not self.db_path.exists():
            self.init_db()
            return None

        quarantine_ts = int(time.time())
        quarantine_path = self.state_dir / f"telemetry.sqlite3.corrupt.{quarantine_ts}"
        try:
            if self.db_path.exists():
                self.db_path.rename(quarantine_path)
            if self.wal_path.exists():
                self.wal_path.rename(self.state_dir / f"telemetry.sqlite3-wal.corrupt.{quarantine_ts}")
            shm_path = self.state_dir / "telemetry.sqlite3-shm"
            if shm_path.exists():
                shm_path.rename(self.state_dir / f"telemetry.sqlite3-shm.corrupt.{quarantine_ts}")
        except OSError as error:
            logger.error("Failed to quarantine database: %s", error)

        self.init_db()
        return quarantine_path

    def query_process_history(
        self,
        run_id: str,
        since: float,
        until: float,
        *,
        max_points: int = DEFAULT_RETURNED_POINTS,
        nominal_interval: float = 5.0,
    ) -> list[TelemetryQueryPoint]:
        """Query process metrics across 5m rollups, 1m rollups, and raw boundaries with zero dropped samples."""
        if not self.db_path.exists() or since >= until:
            return []

        capped_points = max(10, min(max_points, MAX_RETURNED_POINTS))
        window_duration = until - since

        # Find earliest timestamp currently present in telemetry_raw and 1m rollups
        with self.session() as conn:
            row_raw = conn.execute(
                "SELECT MIN(timestamp) FROM telemetry_raw WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            earliest_raw = float(row_raw[0]) if (row_raw and row_raw[0] is not None) else until

            row_1m = conn.execute(
                "SELECT MIN(bucket_epoch), MAX(bucket_epoch) FROM telemetry_rollup_1m WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            earliest_1m = int(row_1m[0]) if (row_1m and row_1m[0] is not None) else None
            latest_1m = int(row_1m[1]) if (row_1m and row_1m[1] is not None) else None

        points: list[TelemetryQueryPoint] = []

        if window_duration <= self.raw_retention_seconds and since >= (earliest_raw - 10.0):
            # Window falls within raw retention: query raw table directly
            with self.session() as conn:
                rows = conn.execute(
                    """
                    SELECT timestamp, sampled_at, cpu_percent, cpu_percent_normalized,
                           rss_bytes, read_bytes_per_sec, write_bytes_per_sec,
                           process_count, thread_count, gpu_memory_bytes
                    FROM telemetry_raw
                    WHERE run_id = ? AND timestamp >= ? AND timestamp <= ?
                    ORDER BY timestamp ASC
                    """,
                    (run_id, since, until),
                ).fetchall()

            last_t: float | None = None
            for r in rows:
                t = float(r["timestamp"])
                interval = (t - last_t) if last_t is not None else nominal_interval
                # Check for gap
                if last_t is not None and (t - last_t) > (3.0 * nominal_interval):
                    gap_epoch = last_t + nominal_interval
                    points.append(
                        TelemetryQueryPoint(
                            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(gap_epoch)),
                            epoch=gap_epoch,
                            sample_interval_seconds=t - last_t,
                            cpu_percent=None,
                            cpu_percent_normalized=None,
                            rss_bytes=None,
                            read_bytes_per_second=None,
                            write_bytes_per_second=None,
                            process_count=int(r["process_count"]),
                            thread_count=int(r["thread_count"]),
                            gpu_memory_bytes=None,
                            is_gap=True,
                            gap_reason="sampling interval missed or process paused",
                            run_id=run_id,
                        )
                    )
                points.append(
                    TelemetryQueryPoint(
                        timestamp=str(r["sampled_at"]),
                        epoch=t,
                        sample_interval_seconds=interval,
                        cpu_percent=r["cpu_percent"],
                        cpu_percent_normalized=r["cpu_percent_normalized"],
                        rss_bytes=r["rss_bytes"],
                        read_bytes_per_second=r["read_bytes_per_sec"],
                        write_bytes_per_second=r["write_bytes_per_sec"],
                        process_count=int(r["process_count"]),
                        thread_count=int(r["thread_count"]),
                        gpu_memory_bytes=r["gpu_memory_bytes"],
                        run_id=run_id,
                    )
                )
                last_t = t
        else:
            # Window spans beyond raw retention: 3-tier seamless UNION ALL across 5m, 1m, and raw
            if latest_1m is not None:
                raw_boundary = max(float(latest_1m + 60), earliest_raw)
            else:
                raw_boundary = earliest_raw

            nominal_1m_cutoff = until - self.rollup_1m_retention_seconds
            if earliest_1m is not None:
                b_5m_1m = max(float(earliest_1m), float(int(nominal_1m_cutoff // 300) * 300))
            else:
                b_5m_1m = raw_boundary
            b_5m_1m = max(since, min(b_5m_1m, raw_boundary))
            b_5m_1m = float(int(b_5m_1m // 300) * 300)

            with self.session() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        bucket_epoch,
                        sample_count,
                        cpu_avg,
                        cpu_min,
                        cpu_max,
                        rss_avg,
                        rss_max,
                        read_bytes_sec_avg,
                        write_bytes_sec_avg,
                        gpu_memory_bytes_max,
                        300.0 AS interval_sec
                    FROM telemetry_rollup_5m
                    WHERE run_id = :run_id AND bucket_epoch >= :since AND bucket_epoch < :b_5m_1m
                    UNION ALL
                    SELECT
                        bucket_epoch,
                        sample_count,
                        cpu_avg,
                        cpu_min,
                        cpu_max,
                        rss_avg,
                        rss_max,
                        read_bytes_sec_avg,
                        write_bytes_sec_avg,
                        gpu_memory_bytes_max,
                        60.0 AS interval_sec
                    FROM telemetry_rollup_1m
                    WHERE run_id = :run_id AND bucket_epoch >= :b_5m_1m AND bucket_epoch < :raw_boundary
                    UNION ALL
                    SELECT
                        CAST(timestamp / 60 AS INTEGER) * 60 AS bucket_epoch,
                        COUNT(*) AS sample_count,
                        AVG(cpu_percent) AS cpu_avg,
                        MIN(cpu_percent) AS cpu_min,
                        MAX(cpu_percent) AS cpu_max,
                        CAST(ROUND(AVG(rss_bytes)) AS INTEGER) AS rss_avg,
                        MAX(rss_bytes) AS rss_max,
                        AVG(read_bytes_per_sec) AS read_bytes_sec_avg,
                        AVG(write_bytes_per_sec) AS write_bytes_sec_avg,
                        MAX(gpu_memory_bytes) AS gpu_memory_bytes_max,
                        60.0 AS interval_sec
                    FROM telemetry_raw
                    WHERE run_id = :run_id AND timestamp >= :raw_boundary AND timestamp <= :until
                    GROUP BY CAST(timestamp / 60 AS INTEGER) * 60
                    ORDER BY bucket_epoch ASC
                    """,
                    {
                        "run_id": run_id,
                        "since": int(since),
                        "b_5m_1m": int(b_5m_1m),
                        "raw_boundary": raw_boundary,
                        "until": until,
                    },
                ).fetchall()

            last_epoch: float | None = None
            last_interval: float = 60.0
            for r in rows:
                epoch = float(r["bucket_epoch"])
                interval = float(r["interval_sec"])
                if last_epoch is not None and epoch > (last_epoch + last_interval + 1.0):
                    gap_duration = epoch - (last_epoch + last_interval)
                    gap_epoch = last_epoch + last_interval
                    points.append(
                        TelemetryQueryPoint(
                            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(gap_epoch)),
                            epoch=gap_epoch,
                            sample_interval_seconds=gap_duration,
                            cpu_percent=None,
                            cpu_percent_normalized=None,
                            rss_bytes=None,
                            read_bytes_per_second=None,
                            write_bytes_per_second=None,
                            process_count=1,
                            thread_count=1,
                            gpu_memory_bytes=None,
                            is_gap=True,
                            gap_reason="sampling interval gap",
                            run_id=run_id,
                        )
                    )
                iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
                points.append(
                    TelemetryQueryPoint(
                        timestamp=iso,
                        epoch=epoch,
                        sample_interval_seconds=interval,
                        cpu_percent=r["cpu_avg"],
                        cpu_percent_normalized=None,
                        cpu_percent_min=r["cpu_min"],
                        cpu_percent_max=r["cpu_max"],
                        rss_bytes=r["rss_avg"],
                        rss_bytes_max=r["rss_max"],
                        read_bytes_per_second=r["read_bytes_sec_avg"],
                        write_bytes_per_second=r["write_bytes_sec_avg"],
                        process_count=1,
                        thread_count=1,
                        gpu_memory_bytes=r["gpu_memory_bytes_max"],
                        run_id=run_id,
                    )
                )
                last_epoch = epoch
                last_interval = interval

        # Downsample if point count exceeds budget
        if len(points) > capped_points:
            return self._downsample_points(points, capped_points)
        return points

    def query_host_history(
        self,
        since: float,
        until: float,
        *,
        max_points: int = DEFAULT_RETURNED_POINTS,
        nominal_interval: float = 5.0,
    ) -> list[dict[str, Any]]:
        """Query host-level metrics across 5m rollups, 1m rollups, and raw boundaries."""
        if not self.db_path.exists() or since >= until:
            return []

        capped_points = max(10, min(max_points, MAX_RETURNED_POINTS))
        window_duration = until - since

        with self.session() as conn:
            row_raw = conn.execute("SELECT MIN(timestamp) FROM host_telemetry_raw").fetchone()
            earliest_raw = float(row_raw[0]) if (row_raw and row_raw[0] is not None) else until

            row_1m = conn.execute(
                "SELECT MIN(bucket_epoch), MAX(bucket_epoch) FROM host_telemetry_rollup_1m"
            ).fetchone()
            earliest_1m = int(row_1m[0]) if (row_1m and row_1m[0] is not None) else None
            latest_1m = int(row_1m[1]) if (row_1m and row_1m[1] is not None) else None

        points: list[dict[str, Any]] = []

        if window_duration <= self.raw_retention_seconds and since >= (earliest_raw - 10.0):
            # Window falls within raw retention: query raw host table directly
            with self.session() as conn:
                rows = conn.execute(
                    """
                    SELECT timestamp, sampled_at, cpu_percent, memory_used_bytes,
                           memory_available_bytes, net_read_bytes_sec, net_write_bytes_sec
                    FROM host_telemetry_raw
                    WHERE timestamp >= ? AND timestamp <= ?
                    ORDER BY timestamp ASC
                    """,
                    (since, until),
                ).fetchall()

            last_t: float | None = None
            for r in rows:
                t = float(r["timestamp"])
                interval = (t - last_t) if last_t is not None else nominal_interval
                if last_t is not None and (t - last_t) > (3.0 * nominal_interval):
                    gap_epoch = last_t + nominal_interval
                    points.append({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(gap_epoch)),
                        "epoch": gap_epoch,
                        "sample_interval_seconds": t - last_t,
                        "sample_count": 0,
                        "cpu_percent": None,
                        "cpu_percent_min": None,
                        "cpu_percent_max": None,
                        "memory_used_bytes": None,
                        "memory_used_max": None,
                        "memory_available_bytes": None,
                        "net_read_bytes_per_second": None,
                        "net_write_bytes_per_second": None,
                        "is_gap": True,
                        "gap_reason": "host sampling gap",
                    })
                points.append({
                    "timestamp": str(r["sampled_at"]),
                    "epoch": t,
                    "sample_interval_seconds": interval,
                    "sample_count": 1,
                    "cpu_percent": r["cpu_percent"],
                    "cpu_percent_min": r["cpu_percent"],
                    "cpu_percent_max": r["cpu_percent"],
                    "memory_used_bytes": r["memory_used_bytes"],
                    "memory_used_max": r["memory_used_bytes"],
                    "memory_available_bytes": r["memory_available_bytes"],
                    "net_read_bytes_per_second": r["net_read_bytes_sec"],
                    "net_write_bytes_per_second": r["net_write_sec_avg"] if "net_write_sec_avg" in r.keys() else r["net_write_bytes_sec"],
                    "is_gap": False,
                })
                last_t = t
        else:
            # 3-tier host query across 5m, 1m, and raw
            if latest_1m is not None:
                raw_boundary = max(float(latest_1m + 60), earliest_raw)
            else:
                raw_boundary = earliest_raw

            nominal_1m_cutoff = until - self.rollup_1m_retention_seconds
            if earliest_1m is not None:
                b_5m_1m = max(float(earliest_1m), float(int(nominal_1m_cutoff // 300) * 300))
            else:
                b_5m_1m = raw_boundary
            b_5m_1m = max(since, min(b_5m_1m, raw_boundary))
            b_5m_1m = float(int(b_5m_1m // 300) * 300)

            with self.session() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        bucket_epoch,
                        sample_count,
                        cpu_avg,
                        cpu_min,
                        cpu_max,
                        memory_used_avg,
                        memory_used_max,
                        net_read_sec_avg,
                        net_write_sec_avg,
                        300.0 AS interval_sec
                    FROM host_telemetry_rollup_5m
                    WHERE bucket_epoch >= :since AND bucket_epoch < :b_5m_1m
                    UNION ALL
                    SELECT
                        bucket_epoch,
                        sample_count,
                        cpu_avg,
                        cpu_min,
                        cpu_max,
                        memory_used_avg,
                        memory_used_max,
                        net_read_sec_avg,
                        net_write_sec_avg,
                        60.0 AS interval_sec
                    FROM host_telemetry_rollup_1m
                    WHERE bucket_epoch >= :b_5m_1m AND bucket_epoch < :raw_boundary
                    UNION ALL
                    SELECT
                        CAST(timestamp / 60 AS INTEGER) * 60 AS bucket_epoch,
                        COUNT(*) AS sample_count,
                        AVG(cpu_percent) AS cpu_avg,
                        MIN(cpu_percent) AS cpu_min,
                        MAX(cpu_percent) AS cpu_max,
                        CAST(ROUND(AVG(memory_used_bytes)) AS INTEGER) AS memory_used_avg,
                        MAX(memory_used_bytes) AS memory_used_max,
                        AVG(net_read_bytes_sec) AS net_read_sec_avg,
                        AVG(net_write_bytes_sec) AS net_write_sec_avg,
                        60.0 AS interval_sec
                    FROM host_telemetry_raw
                    WHERE timestamp >= :raw_boundary AND timestamp <= :until
                    GROUP BY CAST(timestamp / 60 AS INTEGER) * 60
                    ORDER BY bucket_epoch ASC
                    """,
                    {
                        "since": int(since),
                        "b_5m_1m": int(b_5m_1m),
                        "raw_boundary": raw_boundary,
                        "until": until,
                    },
                ).fetchall()

            last_epoch: float | None = None
            last_interval: float = 60.0
            for r in rows:
                epoch = float(r["bucket_epoch"])
                interval = float(r["interval_sec"])
                if last_epoch is not None and epoch > (last_epoch + last_interval + 1.0):
                    gap_duration = epoch - (last_epoch + last_interval)
                    gap_epoch = last_epoch + last_interval
                    points.append({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(gap_epoch)),
                        "epoch": gap_epoch,
                        "sample_interval_seconds": gap_duration,
                        "sample_count": 0,
                        "cpu_percent": None,
                        "cpu_percent_min": None,
                        "cpu_percent_max": None,
                        "memory_used_bytes": None,
                        "memory_used_max": None,
                        "memory_available_bytes": None,
                        "net_read_bytes_per_second": None,
                        "net_write_bytes_per_second": None,
                        "is_gap": True,
                        "gap_reason": "sampling interval gap",
                    })
                iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
                points.append({
                    "timestamp": iso,
                    "epoch": epoch,
                    "sample_interval_seconds": interval,
                    "sample_count": int(r["sample_count"]),
                    "cpu_percent": r["cpu_avg"],
                    "cpu_percent_min": r["cpu_min"],
                    "cpu_percent_max": r["cpu_max"],
                    "memory_used_bytes": r["memory_used_avg"],
                    "memory_used_max": r["memory_used_max"],
                    "memory_available_bytes": None,
                    "net_read_bytes_per_second": r["net_read_sec_avg"],
                    "net_write_bytes_per_second": r["net_write_sec_avg"],
                    "is_gap": False,
                })
                last_epoch = epoch
                last_interval = interval

        if len(points) > capped_points:
            return self._downsample_host_points(points, capped_points)
        return points

    def query_events(self, run_id: str, since: float, until: float) -> list[dict[str, Any]]:
        """Return discrete lifecycle events for a run."""
        if not self.db_path.exists():
            return []
        with self.session() as conn:
            rows = conn.execute(
                "SELECT timestamp, event_type, reason, details_json FROM telemetry_events WHERE run_id = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC",
                (run_id, since, until),
            ).fetchall()
        events = []
        for r in rows:
            events.append({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(r["timestamp"]))),
                "epoch": float(r["timestamp"]),
                "event": str(r["event_type"]),
                "reason": r["reason"],
                "details": json.loads(r["details_json"]) if r["details_json"] else None,
            })
        return events

    def _downsample_points(self, points: list[TelemetryQueryPoint], target_count: int) -> list[TelemetryQueryPoint]:
        """Downsample points using bucketed averages and peak conservation, strictly preserving gap markers."""
        if len(points) <= target_count:
            return points

        bucket_size = len(points) / target_count
        downsampled: list[TelemetryQueryPoint] = []

        for b in range(target_count):
            start_idx = int(b * bucket_size)
            end_idx = min(len(points), int((b + 1) * bucket_size))
            sub = points[start_idx:end_idx]
            if not sub:
                continue

            gap_items = [p for p in sub if p.is_gap]
            valid_items = [p for p in sub if not p.is_gap]

            agg_point: TelemetryQueryPoint | None = None
            if valid_items:
                valid_cpus = [p.cpu_percent for p in valid_items if p.cpu_percent is not None]
                valid_rss = [p.rss_bytes for p in valid_items if p.rss_bytes is not None]
                valid_read = [p.read_bytes_per_second for p in valid_items if p.read_bytes_per_second is not None]
                valid_write = [p.write_bytes_per_second for p in valid_items if p.write_bytes_per_second is not None]
                valid_gpu = [p.gpu_memory_bytes for p in valid_items if p.gpu_memory_bytes is not None]

                mid_item = valid_items[len(valid_items) // 2]
                agg_point = TelemetryQueryPoint(
                    timestamp=mid_item.timestamp,
                    epoch=mid_item.epoch,
                    sample_interval_seconds=mid_item.sample_interval_seconds,
                    cpu_percent=(sum(valid_cpus) / len(valid_cpus)) if valid_cpus else None,
                    cpu_percent_normalized=mid_item.cpu_percent_normalized,
                    cpu_percent_min=min(valid_cpus) if valid_cpus else None,
                    cpu_percent_max=max(valid_cpus) if valid_cpus else None,
                    rss_bytes=int(sum(valid_rss) / len(valid_rss)) if valid_rss else None,
                    rss_bytes_max=max(valid_rss) if valid_rss else None,
                    read_bytes_per_second=(sum(valid_read) / len(valid_read)) if valid_read else None,
                    write_bytes_per_second=(sum(valid_write) / len(valid_write)) if valid_write else None,
                    process_count=mid_item.process_count,
                    thread_count=mid_item.thread_count,
                    gpu_memory_bytes=max(valid_gpu) if valid_gpu else None,
                    run_id=mid_item.run_id,
                )

            bucket_out: list[TelemetryQueryPoint] = []
            if agg_point:
                bucket_out.append(agg_point)
            if gap_items:
                bucket_out.extend(gap_items)

            bucket_out.sort(key=lambda p: p.epoch)
            downsampled.extend(bucket_out)

        return downsampled

    def _downsample_host_points(self, points: list[dict[str, Any]], target_count: int) -> list[dict[str, Any]]:
        """Downsample host points using bucketed averages, strictly preserving gap markers."""
        if len(points) <= target_count:
            return points

        bucket_size = len(points) / target_count
        downsampled: list[dict[str, Any]] = []

        for b in range(target_count):
            start_idx = int(b * bucket_size)
            end_idx = min(len(points), int((b + 1) * bucket_size))
            sub = points[start_idx:end_idx]
            if not sub:
                continue

            gap_items = [p for p in sub if p.get("is_gap")]
            valid_items = [p for p in sub if not p.get("is_gap")]

            agg_point: dict[str, Any] | None = None
            if valid_items:
                valid_cpus = [p["cpu_percent"] for p in valid_items if p.get("cpu_percent") is not None]
                valid_mem = [p["memory_used_bytes"] for p in valid_items if p.get("memory_used_bytes") is not None]
                valid_read = [p["net_read_bytes_per_second"] for p in valid_items if p.get("net_read_bytes_per_second") is not None]
                valid_write = [p["net_write_bytes_per_second"] for p in valid_items if p.get("net_write_bytes_per_second") is not None]

                mid_item = valid_items[len(valid_items) // 2]
                agg_point = {
                    "timestamp": mid_item["timestamp"],
                    "epoch": mid_item["epoch"],
                    "sample_interval_seconds": mid_item.get("sample_interval_seconds", 60.0),
                    "sample_count": sum(int(p.get("sample_count", 1)) for p in valid_items),
                    "cpu_percent": (sum(valid_cpus) / len(valid_cpus)) if valid_cpus else None,
                    "cpu_percent_min": min(valid_cpus) if valid_cpus else None,
                    "cpu_percent_max": max(valid_cpus) if valid_cpus else None,
                    "memory_used_bytes": int(sum(valid_mem) / len(valid_mem)) if valid_mem else None,
                    "memory_used_max": max(valid_mem) if valid_mem else None,
                    "memory_available_bytes": mid_item.get("memory_available_bytes"),
                    "net_read_bytes_per_second": (sum(valid_read) / len(valid_read)) if valid_read else None,
                    "net_write_bytes_per_second": (sum(valid_write) / len(valid_write)) if valid_write else None,
                    "is_gap": False,
                }

            bucket_out: list[dict[str, Any]] = []
            if agg_point:
                bucket_out.append(agg_point)
            if gap_items:
                bucket_out.extend(gap_items)

            bucket_out.sort(key=lambda p: float(p["epoch"]))
            downsampled.extend(bucket_out)

        return downsampled

    def count_raw_samples(self, run_id: str, since: float, until: float) -> int:
        """Count raw samples for a run within a time range."""
        if not self.db_path.exists():
            return 0
        with self.session() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM telemetry_raw WHERE run_id = ? AND timestamp >= ? AND timestamp <= ?",
                (run_id, since, until),
            ).fetchone()
            return int(row[0]) if row else 0
