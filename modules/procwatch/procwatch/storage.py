"""SQLite WAL flight recorder, atomic Event Log checkpoints, migrations, and retention."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import socket
import sqlite3
import threading
import time
from typing import Any, Iterator

from procwatch.config import StorageConfig, get_data_dir
from procwatch.models import (
    EdgeRelation,
    EvidenceEdge,
    IncidentRecord,
    IngestGap,
    ProcessObservation,
    RawEventRecord,
    RunResult,
    UserBookmark,
    WindowObservation,
    utc_now_iso,
)
from procwatch.redactor import redact_dict, redact_text

SCHEMA_VERSION = 2


class UnsupportedSchemaVersionError(RuntimeError):
    """Raised when the SQLite database has a newer schema version than this code supports."""


def _machine_id() -> str:
    return socket.gethostname() or "unknown-host"


class FlightRecorderStorage:
    """Thread-safe SQLite WAL storage for ProcWatch Phase 2."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        config: StorageConfig | None = None,
        read_only: bool = False,
    ) -> None:
        self.config = config or StorageConfig()
        if db_path is not None:
            self.db_path = Path(db_path).expanduser().resolve()
        else:
            self.db_path = self.config.resolved_db_path(get_data_dir())
        self.read_only = read_only
        self.machine_id = _machine_id()
        self._lock = threading.RLock()

        if not self.read_only:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_and_migrate()

    def close(self) -> None:
        """Close any held resources (connections are short-lived per operation)."""
        return None

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            if not self.db_path.exists():
                raise FileNotFoundError(f"ProcWatch database does not exist: {self.db_path}")
            uri = self.db_path.as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=self.config.busy_timeout_ms / 1000.0)
        else:
            conn = sqlite3.connect(str(self.db_path), timeout=self.config.busy_timeout_ms / 1000.0)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {int(self.config.busy_timeout_ms)}")
        conn.execute("PRAGMA foreign_keys = ON")
        if not self.read_only:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def _write_tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def _read_conn(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _init_and_migrate(self) -> None:
        with self._write_tx() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    version INTEGER PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                )
                """
            )
            row = conn.execute("SELECT MAX(version) AS v FROM schema_meta").fetchone()
            current = int(row["v"]) if row and row["v"] is not None else 0
            if current > SCHEMA_VERSION:
                raise UnsupportedSchemaVersionError(
                    f"Database schema version {current} is newer than supported version {SCHEMA_VERSION}."
                )
            if current < 1:
                self._apply_v1(conn)
                conn.execute(
                    "INSERT INTO schema_meta (version, applied_at_utc) VALUES (?, ?)",
                    (1, utc_now_iso()),
                )
            if current < 2:
                self._apply_v2(conn)
                conn.execute(
                    "INSERT INTO schema_meta (version, applied_at_utc) VALUES (?, ?)",
                    (2, utc_now_iso()),
                )

    @staticmethod
    def _apply_v2(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS supervised_runs (
                execution_id TEXT PRIMARY KEY,
                start_ts_utc TEXT NOT NULL,
                end_ts_utc TEXT,
                duration_ms REAL NOT NULL DEFAULT 0.0,
                executable TEXT NOT NULL,
                argv_redacted_json TEXT NOT NULL,
                cwd TEXT NOT NULL,
                profile TEXT NOT NULL,
                exit_code INTEGER,
                status TEXT NOT NULL,
                pid INTEGER,
                proc_key TEXT,
                job_assigned INTEGER NOT NULL DEFAULT 0,
                job_status TEXT NOT NULL DEFAULT 'unknown',
                job_cleanup_outcome TEXT NOT NULL DEFAULT 'unknown',
                stdout_bytes INTEGER NOT NULL DEFAULT 0,
                stderr_bytes INTEGER NOT NULL DEFAULT 0,
                stdout_truncated INTEGER NOT NULL DEFAULT 0,
                stderr_truncated INTEGER NOT NULL DEFAULT 0,
                dropped_bytes INTEGER NOT NULL DEFAULT 0,
                stdout_redacted TEXT NOT NULL DEFAULT '',
                stderr_redacted TEXT NOT NULL DEFAULT '',
                agent_context_json TEXT,
                error_detail TEXT,
                incomplete INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_supervised_runs_start ON supervised_runs(start_ts_utc);
            """
        )

    @staticmethod
    def _apply_v1(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS collector_state (
                source TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                evt_bookmark_xml TEXT,
                events_ingested INTEGER NOT NULL DEFAULT 0,
                events_dropped INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                coverage_state TEXT NOT NULL DEFAULT 'unknown',
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS raw_events (
                raw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id TEXT NOT NULL,
                boot_id TEXT NOT NULL,
                source TEXT NOT NULL,
                provider_event_id INTEGER NOT NULL,
                source_record_id TEXT NOT NULL,
                event_ts_utc TEXT NOT NULL,
                ingestion_ts_utc TEXT NOT NULL,
                monotonic_ns INTEGER,
                payload_redacted_json TEXT NOT NULL,
                UNIQUE(boot_id, source, source_record_id)
            );
            CREATE INDEX IF NOT EXISTS idx_raw_events_ts ON raw_events(event_ts_utc);

            CREATE TABLE IF NOT EXISTS processes (
                proc_key TEXT PRIMARY KEY,
                boot_id TEXT NOT NULL,
                pid INTEGER NOT NULL,
                ppid INTEGER,
                sysmon_guid TEXT,
                kernel_create_100ns INTEGER,
                is_provisional INTEGER NOT NULL DEFAULT 1,
                image_name TEXT,
                image_path TEXT,
                cmdline_redacted TEXT,
                decoded_payload TEXT,
                cwd TEXT,
                git_repo TEXT,
                git_worktree TEXT,
                git_branch TEXT,
                pe_subsystem TEXT,
                startup_flags INTEGER,
                agent_context_json TEXT,
                start_ts_utc TEXT,
                exit_ts_utc TEXT,
                duration_ms REAL,
                exit_code INTEGER,
                process_created INTEGER NOT NULL DEFAULT 0,
                process_terminated INTEGER NOT NULL DEFAULT 0,
                exit_code_known INTEGER NOT NULL DEFAULT 0,
                window_observed INTEGER NOT NULL DEFAULT 0,
                command_line_captured INTEGER NOT NULL DEFAULT 0,
                ancestry_complete INTEGER NOT NULL DEFAULT 0,
                missing_reasons_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_processes_pid ON processes(pid);

            CREATE TABLE IF NOT EXISTS windows (
                window_instance_id TEXT PRIMARY KEY,
                hwnd INTEGER NOT NULL,
                owner_pid INTEGER NOT NULL,
                owner_proc_key TEXT,
                window_class TEXT NOT NULL,
                initial_title TEXT NOT NULL,
                title_history_json TEXT NOT NULL DEFAULT '[]',
                became_visible INTEGER NOT NULL DEFAULT 0,
                stole_foreground INTEGER NOT NULL DEFAULT 0,
                guard_action TEXT,
                create_ts_utc TEXT NOT NULL,
                destroy_ts_utc TEXT
            );

            CREATE TABLE IF NOT EXISTS evidence_edges (
                edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_node_id TEXT NOT NULL,
                to_node_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                source TEXT NOT NULL,
                method TEXT NOT NULL,
                confidence TEXT NOT NULL,
                supporting_raw_ids_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_edges_from ON evidence_edges(from_node_id);
            CREATE INDEX IF NOT EXISTS idx_edges_to ON evidence_edges(to_node_id);

            CREATE TABLE IF NOT EXISTS incidents (
                incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_ts_utc TEXT NOT NULL,
                category TEXT NOT NULL,
                primary_proc_key TEXT,
                collapsed_shim_key TEXT,
                root_initiator_key TEXT,
                window_instance_id TEXT,
                confidence TEXT NOT NULL,
                summary_text TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                scorer_version TEXT NOT NULL DEFAULT '0.2.0'
            );
            CREATE INDEX IF NOT EXISTS idx_incidents_ts ON incidents(created_ts_utc);

            CREATE TABLE IF NOT EXISTS incident_windows (
                incident_id INTEGER NOT NULL,
                window_instance_id TEXT NOT NULL,
                PRIMARY KEY (incident_id, window_instance_id)
            );

            CREATE TABLE IF NOT EXISTS bookmarks (
                bookmark_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                monotonic_ns INTEGER NOT NULL,
                label TEXT NOT NULL,
                matched_incident_ids_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS ingest_gaps (
                gap_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                start_ts_utc TEXT,
                end_ts_utc TEXT,
                reason TEXT NOT NULL,
                remediation_status TEXT NOT NULL DEFAULT 'unrecovered',
                created_at_utc TEXT NOT NULL
            );
            """
        )

    def get_schema_version(self) -> int:
        with self._read_conn() as conn:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_meta").fetchone()
            return int(row["v"]) if row and row["v"] is not None else 0

    def get_collector_state(self, source: str | None = None) -> list[dict[str, Any]]:
        with self._read_conn() as conn:
            if source is not None:
                rows = conn.execute("SELECT * FROM collector_state WHERE source = ?", (source,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM collector_state ORDER BY source").fetchall()
            return [dict(r) for r in rows]

    def update_collector_state(
        self,
        *,
        source: str,
        status: str,
        coverage_state: str = "unknown",
        last_error: str | None = None,
        events_dropped_delta: int = 0,
    ) -> None:
        red_err = redact_text(last_error, escape_controls=True) if last_error else None
        with self._write_tx() as conn:
            conn.execute(
                """
                INSERT INTO collector_state (
                    source, status, evt_bookmark_xml, events_ingested, events_dropped,
                    last_error, coverage_state, updated_at_utc
                ) VALUES (?, ?, NULL, 0, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    status = excluded.status,
                    events_dropped = collector_state.events_dropped + excluded.events_dropped,
                    last_error = excluded.last_error,
                    coverage_state = excluded.coverage_state,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (source, status, events_dropped_delta, red_err, coverage_state, utc_now_iso()),
            )

    def ingest_event_batch(
        self,
        *,
        source: str,
        events: list[RawEventRecord],
        new_bookmark_xml: str | None = None,
        status: str = "active",
        coverage_state: str = "live",
        last_error: str | None = None,
    ) -> tuple[int, list[int]]:
        """Atomically persist raw events and advance the source Event Log bookmark.

        Returns (inserted_count, inserted_raw_ids).
        """
        inserted = 0
        raw_ids: list[int] = []
        red_err = redact_text(last_error, escape_controls=True) if last_error else None
        with self._write_tx() as conn:
            for ev in events:
                redacted_payload = redact_dict(ev.payload_redacted)
                payload_json = json.dumps(redacted_payload, ensure_ascii=False, default=str)
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO raw_events (
                        machine_id, boot_id, source, provider_event_id, source_record_id,
                        event_ts_utc, ingestion_ts_utc, monotonic_ns, payload_redacted_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev.machine_id or self.machine_id,
                        ev.boot_id,
                        ev.source,
                        ev.provider_event_id,
                        ev.source_record_id,
                        ev.event_ts_utc,
                        ev.ingestion_ts_utc,
                        ev.monotonic_ns,
                        payload_json,
                    ),
                )
                if cur.rowcount > 0:
                    inserted += 1
                    if cur.lastrowid is not None:
                        raw_ids.append(int(cur.lastrowid))

            conn.execute(
                """
                INSERT INTO collector_state (
                    source, status, evt_bookmark_xml, events_ingested, events_dropped,
                    last_error, coverage_state, updated_at_utc
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    status = excluded.status,
                    evt_bookmark_xml = COALESCE(excluded.evt_bookmark_xml, collector_state.evt_bookmark_xml),
                    events_ingested = collector_state.events_ingested + excluded.events_ingested,
                    last_error = excluded.last_error,
                    coverage_state = excluded.coverage_state,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (source, status, new_bookmark_xml, inserted, red_err, coverage_state, utc_now_iso()),
            )
        return inserted, raw_ids

    def record_ingest_gap(self, gap: IngestGap) -> int:
        with self._write_tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO ingest_gaps (
                    source, start_ts_utc, end_ts_utc, reason, remediation_status, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    gap.source,
                    gap.start_ts_utc,
                    gap.end_ts_utc,
                    gap.reason,
                    gap.remediation_status,
                    gap.created_at_utc,
                ),
            )
            return int(cur.lastrowid or 0)

    def get_ingest_gaps(self, source: str | None = None) -> list[dict[str, Any]]:
        with self._read_conn() as conn:
            if source is not None:
                rows = conn.execute("SELECT * FROM ingest_gaps WHERE source = ? ORDER BY gap_id DESC", (source,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM ingest_gaps ORDER BY gap_id DESC").fetchall()
            return [dict(r) for r in rows]

    def upsert_process(
        self,
        obs: ProcessObservation,
        *,
        cwd: str | None = None,
        git_repo: str | None = None,
        git_worktree: str | None = None,
        git_branch: str | None = None,
        pe_subsystem: str | None = None,
        agent_context: Any | None = None,
    ) -> None:
        from dataclasses import asdict, is_dataclass

        red_cmd = redact_text(obs.command_line_redacted, escape_controls=True) if obs.command_line_redacted else None
        red_dec = redact_text(obs.decoded_payload_redacted, escape_controls=True) if obs.decoded_payload_redacted else None
        ctx_dict = asdict(agent_context) if is_dataclass(agent_context) else agent_context
        red_ctx = json.dumps(redact_dict(ctx_dict), default=str) if ctx_dict else None
        missing_json = json.dumps([m.value for m in obs.missing_reasons])
        duration_ms: float | None = None
        if obs.start_monotonic_ns is not None and obs.exit_monotonic_ns is not None:
            duration_ms = round((obs.exit_monotonic_ns - obs.start_monotonic_ns) / 1_000_000.0, 3)

        with self._write_tx() as conn:
            conn.execute(
                """
                INSERT INTO processes (
                    proc_key, boot_id, pid, ppid, sysmon_guid, kernel_create_100ns, is_provisional,
                    image_name, image_path, cmdline_redacted, decoded_payload, cwd,
                    git_repo, git_worktree, git_branch, pe_subsystem, agent_context_json,
                    start_ts_utc, exit_ts_utc, duration_ms, exit_code,
                    process_created, process_terminated, exit_code_known,
                    window_observed, command_line_captured, ancestry_complete, missing_reasons_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proc_key) DO UPDATE SET
                    ppid = COALESCE(excluded.ppid, processes.ppid),
                    sysmon_guid = COALESCE(excluded.sysmon_guid, processes.sysmon_guid),
                    kernel_create_100ns = COALESCE(excluded.kernel_create_100ns, processes.kernel_create_100ns),
                    is_provisional = MIN(processes.is_provisional, excluded.is_provisional),
                    image_name = COALESCE(NULLIF(excluded.image_name, ''), processes.image_name),
                    image_path = COALESCE(excluded.image_path, processes.image_path),
                    cmdline_redacted = COALESCE(excluded.cmdline_redacted, processes.cmdline_redacted),
                    decoded_payload = COALESCE(excluded.decoded_payload, processes.decoded_payload),
                    cwd = COALESCE(excluded.cwd, processes.cwd),
                    git_repo = COALESCE(excluded.git_repo, processes.git_repo),
                    git_worktree = COALESCE(excluded.git_worktree, processes.git_worktree),
                    git_branch = COALESCE(excluded.git_branch, processes.git_branch),
                    pe_subsystem = COALESCE(excluded.pe_subsystem, processes.pe_subsystem),
                    agent_context_json = COALESCE(excluded.agent_context_json, processes.agent_context_json),
                    exit_ts_utc = COALESCE(excluded.exit_ts_utc, processes.exit_ts_utc),
                    duration_ms = COALESCE(excluded.duration_ms, processes.duration_ms),
                    exit_code = COALESCE(excluded.exit_code, processes.exit_code),
                    process_created = MAX(processes.process_created, excluded.process_created),
                    process_terminated = MAX(processes.process_terminated, excluded.process_terminated),
                    exit_code_known = MAX(processes.exit_code_known, excluded.exit_code_known),
                    window_observed = MAX(processes.window_observed, excluded.window_observed),
                    command_line_captured = MAX(processes.command_line_captured, excluded.command_line_captured),
                    ancestry_complete = MAX(processes.ancestry_complete, excluded.ancestry_complete),
                    missing_reasons_json = excluded.missing_reasons_json
                """,
                (
                    obs.identity.proc_key,
                    obs.identity.boot_id,
                    obs.identity.pid,
                    obs.ppid,
                    obs.identity.sysmon_guid,
                    obs.identity.kernel_create_100ns,
                    1 if obs.identity.is_provisional else 0,
                    obs.image_name,
                    obs.image_path,
                    red_cmd,
                    red_dec,
                    cwd,
                    git_repo,
                    git_worktree,
                    git_branch,
                    pe_subsystem,
                    red_ctx,
                    obs.start_ts_utc,
                    obs.exit_ts_utc,
                    duration_ms,
                    obs.exit_code,
                    1 if obs.capabilities.process_created else 0,
                    1 if obs.capabilities.process_terminated else 0,
                    1 if obs.capabilities.exit_code_known else 0,
                    1 if obs.capabilities.window_observed else 0,
                    1 if obs.capabilities.command_line_captured else 0,
                    1 if obs.capabilities.ancestry_complete else 0,
                    missing_json,
                ),
            )

    def promote_process_identity(self, provisional_key: str, canonical: ProcessObservation) -> None:
        """Promote a provisional process key to canonical identity and record `supersedes` edge."""
        canon_key = canonical.identity.proc_key
        if provisional_key == canon_key:
            self.upsert_process(canonical)
            return

        self.upsert_process(canonical)
        with self._write_tx() as conn:
            prov_row = conn.execute(
                """
                SELECT cwd, git_repo, git_worktree, git_branch, pe_subsystem, agent_context_json
                FROM processes WHERE proc_key = ?
                """,
                (provisional_key,),
            ).fetchone()
            if prov_row is not None:
                conn.execute(
                    """
                    UPDATE processes
                    SET cwd = COALESCE(cwd, ?),
                        git_repo = COALESCE(git_repo, ?),
                        git_worktree = COALESCE(git_worktree, ?),
                        git_branch = COALESCE(git_branch, ?),
                        pe_subsystem = COALESCE(pe_subsystem, ?),
                        agent_context_json = COALESCE(agent_context_json, ?)
                    WHERE proc_key = ?
                    """,
                    (
                        prov_row["cwd"],
                        prov_row["git_repo"],
                        prov_row["git_worktree"],
                        prov_row["git_branch"],
                        prov_row["pe_subsystem"],
                        prov_row["agent_context_json"],
                        canon_key,
                    ),
                )
            conn.execute("UPDATE windows SET owner_proc_key = ? WHERE owner_proc_key = ?", (canon_key, provisional_key))
            conn.execute(
                "UPDATE incidents SET primary_proc_key = ? WHERE primary_proc_key = ?",
                (canon_key, provisional_key),
            )
            conn.execute(
                "UPDATE incidents SET root_initiator_key = ? WHERE root_initiator_key = ?",
                (canon_key, provisional_key),
            )
            conn.execute(
                """
                INSERT INTO evidence_edges (
                    from_node_id, to_node_id, relation, source, method, confidence, supporting_raw_ids_json, notes
                )
                SELECT ?, ?, ?, 'reconciler', 'identity_promotion', 'high', '[]', 'canonical supersedes provisional'
                WHERE NOT EXISTS (
                    SELECT 1 FROM evidence_edges
                    WHERE from_node_id = ? AND to_node_id = ? AND relation = ?
                )
                """,
                (
                    canon_key,
                    provisional_key,
                    EdgeRelation.SUPERSEDES.value,
                    canon_key,
                    provisional_key,
                    EdgeRelation.SUPERSEDES.value,
                ),
            )

    def upsert_window(
        self,
        win: WindowObservation,
        *,
        owner_proc_key: str | None = None,
        guard_action: str | None = None,
    ) -> None:
        red_init = redact_text(win.initial_title, escape_controls=True) or ""
        red_hist = json.dumps([redact_text(t, escape_controls=True) or "" for t in win.title_history])
        with self._write_tx() as conn:
            conn.execute(
                """
                INSERT INTO windows (
                    window_instance_id, hwnd, owner_pid, owner_proc_key, window_class,
                    initial_title, title_history_json, became_visible, stole_foreground,
                    guard_action, create_ts_utc, destroy_ts_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(window_instance_id) DO UPDATE SET
                    owner_proc_key = COALESCE(excluded.owner_proc_key, windows.owner_proc_key),
                    title_history_json = excluded.title_history_json,
                    became_visible = MAX(windows.became_visible, excluded.became_visible),
                    stole_foreground = MAX(windows.stole_foreground, excluded.stole_foreground),
                    guard_action = COALESCE(excluded.guard_action, windows.guard_action),
                    destroy_ts_utc = COALESCE(excluded.destroy_ts_utc, windows.destroy_ts_utc)
                """,
                (
                    win.window_instance_id,
                    win.hwnd,
                    win.owner_pid,
                    owner_proc_key,
                    win.window_class,
                    red_init,
                    red_hist,
                    1 if win.became_visible else 0,
                    1 if win.stole_foreground else 0,
                    guard_action,
                    win.first_seen_ts_utc,
                    win.destroy_ts_utc,
                ),
            )

    def insert_edge(self, edge: EvidenceEdge) -> int:
        with self._write_tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO evidence_edges (
                    from_node_id, to_node_id, relation, source, method, confidence,
                    supporting_raw_ids_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.from_node_id,
                    edge.to_node_id,
                    edge.relation.value,
                    edge.source,
                    edge.method,
                    edge.confidence.value if hasattr(edge.confidence, "value") else str(edge.confidence),
                    json.dumps(edge.supporting_raw_ids),
                    redact_text(edge.notes, escape_controls=True) or "",
                ),
            )
            return int(cur.lastrowid or 0)

    def insert_incident(
        self,
        inc: IncidentRecord,
        *,
        window_ids: list[str] | None = None,
        extra_details: dict[str, Any] | None = None,
    ) -> int:
        red_summary = redact_text(inc.summary_text, escape_controls=True) or ""
        details = redact_dict(
            {
                "alternative_candidates": [
                    c.to_dict() if hasattr(c, "to_dict") else c for c in inc.alternative_candidates
                ],
                "missing_reasons": [
                    m.value if hasattr(m, "value") else str(m) for m in inc.missing_reasons
                ],
                **(extra_details or {}),
            }
        )
        with self._write_tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO incidents (
                    created_ts_utc, category, primary_proc_key, collapsed_shim_key,
                    root_initiator_key, window_instance_id, confidence, summary_text,
                    details_json, scorer_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inc.created_ts_utc,
                    inc.category,
                    inc.primary_proc_key,
                    inc.collapsed_shim_key,
                    inc.root_initiator_key,
                    inc.window_instance_id,
                    inc.confidence.value,
                    red_summary,
                    json.dumps(details, default=str),
                    inc.scorer_version,
                ),
            )
            inc_id = int(cur.lastrowid or 0)
            all_wids = list(window_ids or [])
            if inc.window_instance_id and inc.window_instance_id not in all_wids:
                all_wids.append(inc.window_instance_id)
            for wid in all_wids:
                conn.execute(
                    "INSERT OR IGNORE INTO incident_windows (incident_id, window_instance_id) VALUES (?, ?)",
                    (inc_id, wid),
                )
            return inc_id

    def add_user_mark(self, label: str, *, window_seconds: float = 3.0) -> UserBookmark:
        now_dt = datetime.now(UTC)
        now_iso = now_dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        start_iso = (now_dt - timedelta(seconds=window_seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        end_iso = (now_dt + timedelta(seconds=window_seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        red_label = redact_text(label, escape_controls=True) or ""
        now_ns = time.monotonic_ns()

        with self._write_tx() as conn:
            rows = conn.execute(
                "SELECT incident_id FROM incidents WHERE created_ts_utc BETWEEN ? AND ? ORDER BY incident_id DESC",
                (start_iso, end_iso),
            ).fetchall()
            matched_ids = [int(r["incident_id"]) for r in rows]
            cur = conn.execute(
                """
                INSERT INTO bookmarks (ts_utc, monotonic_ns, label, matched_incident_ids_json)
                VALUES (?, ?, ?, ?)
                """,
                (now_iso, now_ns, red_label, json.dumps(matched_ids)),
            )
            return UserBookmark(
                bookmark_id=int(cur.lastrowid or 0),
                ts_utc=now_iso,
                monotonic_ns=now_ns,
                label=red_label,
                matched_incident_ids=matched_ids,
            )

    def query_history(
        self,
        *,
        since_utc: str | None = None,
        popups_only: bool = False,
        agent_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if since_utc:
            clauses.append("i.created_ts_utc >= ?")
            params.append(since_utc)
        if popups_only:
            clauses.append(
                "i.category IN ('visible_popup', 'suppressed_popup', 'console_popup', 'guard_action')"
            )
        if agent_filter:
            clauses.append("(LOWER(i.summary_text) LIKE ? OR LOWER(COALESCE(p.agent_context_json, '')) LIKE ?)")
            pat = f"%{agent_filter.lower()}%"
            params.extend([pat, pat])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT i.*, p.image_name, p.pid, p.cmdline_redacted, p.cwd, p.git_branch,
                   w.hwnd, w.window_class, w.initial_title, w.guard_action
            FROM incidents i
            LEFT JOIN processes p ON i.primary_proc_key = p.proc_key
            LEFT JOIN windows w ON i.window_instance_id = w.window_instance_id
            {where_sql}
            ORDER BY i.created_ts_utc DESC, i.incident_id DESC
            LIMIT ?
        """
        params.append(limit)
        with self._read_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_incident_detail(self, incident_id: int) -> dict[str, Any] | None:
        with self._read_conn() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
            if row is None:
                return None
            inc = dict(row)
            proc = None
            if inc.get("primary_proc_key"):
                prow = conn.execute("SELECT * FROM processes WHERE proc_key = ?", (inc["primary_proc_key"],)).fetchone()
                proc = dict(prow) if prow else None
            win = None
            if inc.get("window_instance_id"):
                wrow = conn.execute(
                    "SELECT * FROM windows WHERE window_instance_id = ?", (inc["window_instance_id"],)
                ).fetchone()
                win = dict(wrow) if wrow else None

            node_ids = [n for n in (inc.get("primary_proc_key"), inc.get("window_instance_id"), inc.get("root_initiator_key")) if n]
            edges: list[dict[str, Any]] = []
            if node_ids:
                placeholders = ",".join("?" for _ in node_ids)
                erows = conn.execute(
                    f"SELECT * FROM evidence_edges WHERE from_node_id IN ({placeholders}) OR to_node_id IN ({placeholders})",
                    node_ids + node_ids,
                ).fetchall()
                edges = [dict(e) for e in erows]

            return {
                "incident": inc,
                "process": proc,
                "window": win,
                "edges": edges,
            }

    def get_process_by_pid(self, pid: int) -> dict[str, Any] | None:
        with self._read_conn() as conn:
            row = conn.execute(
                "SELECT * FROM processes WHERE pid = ? ORDER BY start_ts_utc DESC LIMIT 1", (pid,)
            ).fetchone()
            return dict(row) if row else None

    def export_bundle(
        self,
        *,
        since_utc: str | None = None,
        popups_only: bool = False,
        agent_filter: str | None = None,
    ) -> dict[str, Any]:
        incidents = self.query_history(
            since_utc=since_utc,
            popups_only=popups_only,
            agent_filter=agent_filter,
            limit=500,
        )
        bundle = {
            "schema_version": SCHEMA_VERSION,
            "exported_at_utc": utc_now_iso(),
            "incidents": incidents,
            "collector_state": self.get_collector_state(),
            "ingest_gaps": self.get_ingest_gaps(),
        }
        return redact_dict(bundle)

    def prune_retention(self, *, max_age_days: int | None = None, max_size_mb: int | None = None) -> dict[str, int]:
        age_days = max_age_days if max_age_days is not None else self.config.max_age_days
        size_mb = max_size_mb if max_size_mb is not None else self.config.max_size_mb
        cutoff_iso = (datetime.now(UTC) - timedelta(days=age_days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        deleted_raw = 0
        deleted_inc = 0

        with self._write_tx() as conn:
            c1 = conn.execute("DELETE FROM raw_events WHERE event_ts_utc < ?", (cutoff_iso,))
            deleted_raw += c1.rowcount
            c2 = conn.execute("DELETE FROM incidents WHERE created_ts_utc < ?", (cutoff_iso,))
            deleted_inc += c2.rowcount
            conn.execute("DELETE FROM supervised_runs WHERE start_ts_utc < ?", (cutoff_iso,))

            # Enforce size cap by deleting oldest raw_events in batches if DB exceeds max_size_mb
            max_bytes = size_mb * 1024 * 1024
            if self.db_path.exists() and self.db_path.stat().st_size > max_bytes:
                c3 = conn.execute(
                    "DELETE FROM raw_events WHERE raw_id IN (SELECT raw_id FROM raw_events ORDER BY raw_id ASC LIMIT 1000)"
                )
                deleted_raw += c3.rowcount

        return {"deleted_raw_events": deleted_raw, "deleted_incidents": deleted_inc}

    def record_supervised_run_start(
        self,
        *,
        execution_id: str,
        executable: str,
        argv: list[str],
        cwd: str,
        profile: str,
        start_ts_utc: str,
        agent_context: dict[str, Any] | None = None,
    ) -> None:
        red_argv = [redact_text(a, escape_controls=True) or "" for a in argv]
        red_ctx = json.dumps(redact_dict(agent_context), default=str) if agent_context else None
        with self._write_tx() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO supervised_runs (
                    execution_id, start_ts_utc, executable, argv_redacted_json,
                    cwd, profile, status, agent_context_json, incomplete
                ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, 1)
                """,
                (execution_id, start_ts_utc, executable, json.dumps(red_argv), cwd, profile, red_ctx),
            )

    def record_supervised_run(self, result: RunResult) -> None:
        red_argv = [redact_text(a, escape_controls=True) or "" for a in result.argv_redacted]
        red_stdout = redact_text(result.stdout_redacted, escape_controls=False) or ""
        red_stderr = redact_text(result.stderr_redacted, escape_controls=False) or ""
        red_err = redact_text(result.error_detail, escape_controls=True) if result.error_detail else None
        red_ctx = json.dumps(redact_dict(result.agent_context), default=str) if result.agent_context else None
        with self._write_tx() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO supervised_runs (
                    execution_id, start_ts_utc, end_ts_utc, duration_ms, executable,
                    argv_redacted_json, cwd, profile, exit_code, status, pid, proc_key,
                    job_assigned, job_status, job_cleanup_outcome, stdout_bytes, stderr_bytes,
                    stdout_truncated, stderr_truncated, dropped_bytes,
                    stdout_redacted, stderr_redacted, agent_context_json, error_detail, incomplete
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    result.execution_id,
                    result.start_ts_utc,
                    result.end_ts_utc,
                    result.duration_ms,
                    result.executable,
                    json.dumps(red_argv),
                    result.cwd,
                    result.profile.value,
                    result.exit_code,
                    result.status.value,
                    result.pid,
                    result.proc_key,
                    1 if result.job_assigned else 0,
                    result.job_status,
                    result.job_cleanup_outcome,
                    result.stdout_bytes,
                    result.stderr_bytes,
                    1 if result.stdout_truncated else 0,
                    1 if result.stderr_truncated else 0,
                    result.dropped_bytes,
                    red_stdout,
                    red_stderr,
                    red_ctx,
                    red_err,
                ),
            )

    def query_supervised_runs(
        self,
        *,
        execution_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._read_conn() as conn:
            if execution_id:
                rows = conn.execute(
                    "SELECT * FROM supervised_runs WHERE execution_id = ? LIMIT ?",
                    (execution_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM supervised_runs ORDER BY start_ts_utc DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def db_stats(self) -> dict[str, Any]:
        with self._read_conn() as conn:
            raw_cnt = int(conn.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0])
            proc_cnt = int(conn.execute("SELECT COUNT(*) FROM processes").fetchone()[0])
            win_cnt = int(conn.execute("SELECT COUNT(*) FROM windows").fetchone()[0])
            inc_cnt = int(conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0])
            gap_cnt = int(conn.execute("SELECT COUNT(*) FROM ingest_gaps").fetchone()[0])
            runs_cnt = int(conn.execute("SELECT COUNT(*) FROM supervised_runs").fetchone()[0])
        size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "db_path": str(self.db_path),
            "schema_version": self.get_schema_version(),
            "size_bytes": size_bytes,
            "raw_events": raw_cnt,
            "processes": proc_cnt,
            "windows": win_cnt,
            "incidents": inc_cnt,
            "ingest_gaps": gap_cnt,
            "supervised_runs": runs_cnt,
        }
