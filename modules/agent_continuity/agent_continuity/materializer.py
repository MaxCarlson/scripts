"""SQLite materializer, idempotent event ingestion, and atomic index rebuild."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .environment import assert_sqlite_writer_allowed
from .errors import ContinuityError, ErrorCode
from .events import SpoolIssue, discover_spool_roots, read_spool_events
from .identifiers import normalize_path_canonical, normalize_repo_identity, now_utc_iso
from .models import (
    AssociationRecord,
    AssociationStatus,
    EnvironmentInfo,
    EventEnvelope,
    EventType,
    GuiConversation,
    SessionRecord,
    Workflow,
)
from .schema import SCHEMA_VERSION, configure_connection, ensure_schema, get_schema_version


@dataclass(slots=True)
class SyncResult:
    """Summary of an event materialization or rebuild operation."""

    ingested_count: int
    skipped_duplicates: int
    total_spool_events: int
    issues: list[SpoolIssue] = field(default_factory=list)
    db_path: str = ""
    rebuilt: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingested_count": self.ingested_count,
            "skipped_duplicates": self.skipped_duplicates,
            "total_spool_events": self.total_spool_events,
            "issues": [{"file_path": i.file_path, "reason": i.reason} for i in self.issues],
            "db_path": self.db_path,
            "rebuilt": self.rebuilt,
        }


class SQLiteMaterializer:
    """Manages the derived SQLite query index from durable environment-isolated events."""

    def __init__(self, home_dir: Path, *, allow_unsafe_cross_os: bool = False) -> None:
        self.home_dir = home_dir
        self.db_path = home_dir / "index.sqlite"
        self.allow_unsafe_cross_os = allow_unsafe_cross_os

    def _connect_rw(self, path: Path | None = None) -> sqlite3.Connection:
        target = path or self.db_path
        assert_sqlite_writer_allowed(target, allow_unsafe_cross_os=self.allow_unsafe_cross_os)
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), timeout=5.0)
        ensure_schema(conn)
        return conn

    def _connect_ro(self) -> sqlite3.Connection | None:
        if not self.db_path.exists():
            return None
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5.0)
        configure_connection(conn, read_only=True)
        return conn

    def ingest_event(self, event: EventEnvelope, *, spool_file: str | None = None, checksum: str = "") -> bool:
        """Ingest a single event transactionally and idempotently. Returns True if newly applied."""
        return self.ingest_events([(event, spool_file, checksum)]) > 0

    def ingest_events(self, items: list[tuple[EventEnvelope, str | None, str]]) -> int:
        """Ingest a batch of events in one SQLite transaction. Returns newly applied count."""
        if not items:
            return 0
        applied_count = 0
        with closing(self._connect_rw()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                for event, spool_file, checksum in items:
                    if self._apply_event_in_tx(conn, event, spool_file=spool_file, checksum=checksum):
                        applied_count += 1
                conn.commit()
                return applied_count
            except Exception as exc:
                conn.rollback()
                if isinstance(exc, ContinuityError):
                    raise
                last_ev = items[-1][0]
                raise ContinuityError(
                    ErrorCode.MATERIALIZER_FAILED,
                    f"Failed to materialize event {last_ev.event_id} ({last_ev.event_type}): {exc}",
                    {"event_id": last_ev.event_id, "event_type": last_ev.event_type},
                ) from exc

    def sync_from_spools(self, extra_roots: list[Path] | None = None) -> SyncResult:
        """Ingest any unmaterialized events from configured spool roots."""
        roots = discover_spool_roots(self.home_dir, extra_roots=extra_roots)
        scan = read_spool_events(roots, optional_roots={self.home_dir / "events"})
        ingested = 0
        skipped = 0

        if not scan.records and not self.db_path.exists():
            # Avoid creating empty SQLite if there are zero events yet unless writer wants schema
            return SyncResult(
                ingested_count=0,
                skipped_duplicates=0,
                total_spool_events=0,
                issues=scan.issues,
                db_path=str(self.db_path),
                rebuilt=False,
            )

        if self.db_path.exists():
            ro_conn = self._connect_ro()
            if ro_conn is not None:
                try:
                    with closing(ro_conn):
                        from .schema import SCHEMA_VERSION, get_schema_version

                        if get_schema_version(ro_conn) == SCHEMA_VERSION:
                            if not scan.records:
                                return SyncResult(
                                    ingested_count=0,
                                    skipped_duplicates=0,
                                    total_spool_events=0,
                                    issues=scan.issues,
                                    db_path=str(self.db_path),
                                    rebuilt=False,
                                )
                            ingested_ids = {
                                row[0] for row in ro_conn.execute("SELECT event_id FROM ingested_events").fetchall()
                            }
                            if all(rec.envelope.event_id in ingested_ids for rec in scan.records):
                                return SyncResult(
                                    ingested_count=0,
                                    skipped_duplicates=len(scan.records),
                                    total_spool_events=len(scan.records),
                                    issues=scan.issues,
                                    db_path=str(self.db_path),
                                    rebuilt=False,
                                )
                except sqlite3.Error:
                    pass

        with closing(self._connect_rw()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                for rec in scan.records:
                    if self._apply_event_in_tx(
                        conn,
                        rec.envelope,
                        spool_file=str(rec.file_path),
                        checksum=rec.checksum,
                    ):
                        ingested += 1
                    else:
                        skipped += 1
                conn.execute(
                    "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES ('last_sync_at', ?)",
                    (now_utc_iso(),),
                )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                if isinstance(exc, ContinuityError):
                    raise
                raise ContinuityError(
                    ErrorCode.MATERIALIZER_FAILED,
                    f"Spool synchronization failed: {exc}",
                    {"db_path": str(self.db_path)},
                ) from exc

        return SyncResult(
            ingested_count=ingested,
            skipped_duplicates=skipped,
            total_spool_events=len(scan.records),
            issues=scan.issues,
            db_path=str(self.db_path),
            rebuilt=False,
        )

    def rebuild_from_spools(self, extra_roots: list[Path] | None = None) -> SyncResult:
        """Rebuild index.sqlite atomically from scratch by replaying all durable spool events."""
        assert_sqlite_writer_allowed(self.db_path, allow_unsafe_cross_os=self.allow_unsafe_cross_os)
        roots = discover_spool_roots(self.home_dir, extra_roots=extra_roots)
        scan = read_spool_events(roots, optional_roots={self.home_dir / "events"})

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.db_path.with_name(f".index.sqlite.rebuild.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        ingested = 0
        skipped = 0

        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(staging), timeout=5.0)
            ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            for rec in scan.records:
                if self._apply_event_in_tx(
                    conn,
                    rec.envelope,
                    spool_file=str(rec.file_path),
                    checksum=rec.checksum,
                ):
                    ingested += 1
                else:
                    skipped += 1
            now = now_utc_iso()
            conn.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES ('last_rebuild_at', ?)",
                (now,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES ('last_sync_at', ?)",
                (now,),
            )
            conn.commit()
            # Switch staging DB out of WAL before replacing target so no orphan -wal/-shm are needed
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.execute("PRAGMA journal_mode = DELETE;")
            integrity = conn.execute("PRAGMA integrity_check;").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ContinuityError(
                    ErrorCode.MATERIALIZER_FAILED,
                    f"Rebuilt database failed integrity_check: {integrity}",
                )
            conn.close()
            conn = None

            # Clean stale WAL/SHM sidecars for target before atomic replacement
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{self.db_path}{suffix}")
                sidecar.unlink(missing_ok=True)
            os.replace(staging, self.db_path)

            # Re-open briefly to restore WAL mode on the live index
            with closing(self._connect_rw(self.db_path)) as live:
                live.execute("PRAGMA journal_mode = WAL;")
        except Exception as exc:
            if conn is not None:
                try:
                    conn.rollback()
                    conn.close()
                except sqlite3.Error:
                    pass
            try:
                staging.unlink(missing_ok=True)
                for suffix in ("-wal", "-shm"):
                    Path(f"{staging}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, ContinuityError):
                raise
            raise ContinuityError(
                ErrorCode.MATERIALIZER_FAILED,
                f"Atomic rebuild failed: {exc}",
                {"db_path": str(self.db_path)},
            ) from exc

        return SyncResult(
            ingested_count=ingested,
            skipped_duplicates=skipped,
            total_spool_events=len(scan.records),
            issues=scan.issues,
            db_path=str(self.db_path),
            rebuilt=True,
        )

    def _apply_event_in_tx(
        self,
        conn: sqlite3.Connection,
        event: EventEnvelope,
        *,
        spool_file: str | None = None,
        checksum: str = "",
    ) -> bool:
        existing = conn.execute(
            "SELECT checksum FROM ingested_events WHERE event_id = ?",
            (event.event_id,),
        ).fetchone()
        if existing is not None:
            return False

        p = event.payload
        ts = event.source_timestamp or event.observed_timestamp
        etype = event.event_type

        if etype == EventType.ENVIRONMENT_REGISTERED.value:
            self._upsert_environment(
                conn,
                environment_id=event.environment_id,
                runtime_kind=p.get("runtime_kind", "unknown"),
                distro=p.get("distro"),
                hostname=p.get("hostname"),
                label=p.get("label") or event.environment_id,
                created_at=p.get("created_at") or ts,
                last_seen_at=ts,
            )

        elif etype == EventType.WORKFLOW_REGISTERED.value:
            wf_id = str(p["workflow_id"])
            repos = [r for r in (p.get("repo_paths") or []) if r]
            conn.execute(
                """
                INSERT INTO workflows(workflow_id, slug, title, repo_paths_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    slug = excluded.slug,
                    title = excluded.title,
                    repo_paths_json = excluded.repo_paths_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    wf_id,
                    str(p["slug"]),
                    str(p["title"]),
                    json.dumps(repos),
                    str(p.get("status", "active")),
                    str(p.get("created_at") or ts),
                    ts,
                ),
            )
            for gui in p.get("gui_conversations") or []:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO gui_conversations(
                        gui_ref_id, workflow_id, url, canonical_url, title, relationship, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(gui["gui_ref_id"]),
                        wf_id,
                        str(gui["url"]),
                        str(gui["canonical_url"]),
                        gui.get("title"),
                        str(gui.get("relationship", "primary")),
                        str(gui.get("status", "active")),
                        str(gui.get("created_at") or ts),
                        ts,
                    ),
                )

        elif etype == EventType.WORKFLOW_UPDATED.value:
            wf_id = str(p["workflow_id"])
            row = conn.execute("SELECT title, repo_paths_json, status FROM workflows WHERE workflow_id = ?", (wf_id,)).fetchone()
            if row is not None:
                title = str(p.get("title") or row["title"])
                repos = p.get("repo_paths")
                repos_json = json.dumps(repos) if repos is not None else row["repo_paths_json"]
                conn.execute(
                    "UPDATE workflows SET title = ?, repo_paths_json = ?, updated_at = ? WHERE workflow_id = ?",
                    (title, repos_json, ts, wf_id),
                )

        elif etype == EventType.WORKFLOW_ARCHIVED.value:
            conn.execute(
                "UPDATE workflows SET status = 'archived', updated_at = ? WHERE workflow_id = ?",
                (ts, str(p["workflow_id"])),
            )

        elif etype == EventType.WORKFLOW_UNARCHIVED.value:
            conn.execute(
                "UPDATE workflows SET status = 'active', updated_at = ? WHERE workflow_id = ?",
                (ts, str(p["workflow_id"])),
            )

        elif etype == EventType.WORKFLOW_GUI_LINKED.value:
            conn.execute(
                """
                INSERT OR REPLACE INTO gui_conversations(
                    gui_ref_id, workflow_id, url, canonical_url, title, relationship, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    str(p["gui_ref_id"]),
                    str(p["workflow_id"]),
                    str(p["url"]),
                    str(p["canonical_url"]),
                    p.get("title"),
                    str(p.get("relationship", "continuation")),
                    str(p.get("created_at") or ts),
                    ts,
                ),
            )
            conn.execute("UPDATE workflows SET updated_at = ? WHERE workflow_id = ?", (ts, str(p["workflow_id"])))

        elif etype == EventType.WORKFLOW_GUI_UNLINKED.value:
            conn.execute(
                "UPDATE gui_conversations SET status = 'unlinked', updated_at = ? WHERE gui_ref_id = ?",
                (ts, str(p["gui_ref_id"])),
            )

        elif etype in (EventType.SESSION_REGISTERED.value, EventType.SESSION_OBSERVED.value):
            self._ensure_env_placeholder(conn, event.environment_id, p.get("environment"), ts)
            self._upsert_session(conn, event, ts)

        elif etype == EventType.SESSION_STATUS_CHANGED.value:
            if event.provider and event.native_session_id:
                conn.execute(
                    """
                    UPDATE sessions
                    SET lifecycle_status = ?, updated_at = ?
                    WHERE provider = ? AND environment_id = ? AND native_session_id = ?
                    """,
                    (
                        str(p["lifecycle_status"]),
                        ts,
                        event.provider,
                        event.environment_id,
                        event.native_session_id,
                    ),
                )

        elif etype == EventType.ASSOCIATION_CREATED.value:
            self._ensure_env_placeholder(conn, event.environment_id, p.get("environment"), ts)
            self._ensure_session_placeholder(conn, event, ts)
            for sup_id in p.get("supersede_association_ids") or []:
                conn.execute(
                    "UPDATE associations SET status = ?, updated_at = ? WHERE association_id = ?",
                    (AssociationStatus.SUPERSEDED.value, ts, str(sup_id)),
                )
            assoc_id = str(p["association_id"])
            evidence_level = str(p["evidence_level"])
            status = str(p.get("status", AssociationStatus.ACTIVE.value))
            confirmed_at = p.get("confirmed_at") or (ts if evidence_level == "confirmed" else None)
            conn.execute(
                """
                INSERT INTO associations(
                    association_id, workflow_id, provider, environment_id, native_session_id,
                    evidence_level, association_method, evidence_summary, evidence_reference,
                    status, first_turn_id, last_turn_id, confirmed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(association_id) DO UPDATE SET
                    evidence_level = excluded.evidence_level,
                    evidence_summary = excluded.evidence_summary,
                    status = excluded.status,
                    confirmed_at = COALESCE(excluded.confirmed_at, associations.confirmed_at),
                    updated_at = excluded.updated_at
                """,
                (
                    assoc_id,
                    str(p["workflow_id"]),
                    str(event.provider),
                    event.environment_id,
                    str(event.native_session_id),
                    evidence_level,
                    str(p.get("association_method", "manual")),
                    p.get("evidence_summary"),
                    p.get("evidence_reference"),
                    status,
                    p.get("first_turn_id"),
                    p.get("last_turn_id"),
                    confirmed_at,
                    str(p.get("created_at") or ts),
                    ts,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO association_evidence(
                    evidence_id, association_id, event_id, evidence_level, evidence_type, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(p.get("evidence_id") or f"evd_{event.event_id}"),
                    assoc_id,
                    event.event_id,
                    evidence_level,
                    str(p.get("association_method", "manual")),
                    json.dumps(p.get("detail") or {}),
                    ts,
                ),
            )

        elif etype == EventType.ASSOCIATION_SUPERSEDED.value:
            conn.execute(
                "UPDATE associations SET status = ?, updated_at = ? WHERE association_id = ?",
                (AssociationStatus.SUPERSEDED.value, ts, str(p["association_id"])),
            )

        elif etype == EventType.ASSOCIATION_UNLINKED.value:
            assoc_id = str(p["association_id"])
            conn.execute(
                "UPDATE associations SET status = ?, updated_at = ? WHERE association_id = ?",
                (AssociationStatus.UNLINKED.value, ts, assoc_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO association_evidence(
                    evidence_id, association_id, event_id, evidence_level, evidence_type, detail_json, created_at
                ) VALUES (?, ?, ?, 'unknown', 'manual_unlink', ?, ?)
                """,
                (f"evd_{event.event_id}", assoc_id, event.event_id, json.dumps({"note": p.get("note")}), ts),
            )

        elif etype == EventType.ASSOCIATION_CANDIDATE_REJECTED.value:
            assoc_id = str(p["association_id"])
            conn.execute(
                "UPDATE associations SET evidence_level = 'rejected', status = ?, updated_at = ? WHERE association_id = ?",
                (AssociationStatus.REJECTED.value, ts, assoc_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO association_evidence(
                    evidence_id, association_id, event_id, evidence_level, evidence_type, detail_json, created_at
                ) VALUES (?, ?, ?, 'rejected', 'manual_reject', ?, ?)
                """,
                (f"evd_{event.event_id}", assoc_id, event.event_id, json.dumps({"note": p.get("note")}), ts),
            )

        elif etype == EventType.ASSOCIATION_CONFLICT_FLAGGED.value:
            assoc_id = str(p["association_id"])
            conn.execute(
                "UPDATE associations SET status = ?, updated_at = ? WHERE association_id = ?",
                (AssociationStatus.CONFLICT.value, ts, assoc_id),
            )

        elif etype == EventType.HOOK_EVENT.value:
            self._apply_hook_event_in_tx(conn, event, ts)
            self._select_slot_from_user_prompt_in_tx(conn, event, ts)

        elif etype == EventType.DISPATCHER_GUI_REGISTERED.value:
            conn.execute(
                """
                INSERT OR IGNORE INTO dispatcher_gui_conversations(
                    gui_id, alias, alias_key, status, created_at, updated_at, last_activity_at
                ) VALUES (?, ?, ?, 'active', ?, ?, NULL)
                """,
                (str(p["gui_id"]), str(p["alias"]), str(p["alias_key"]), ts, ts),
            )

        elif etype == EventType.DISPATCHER_GUI_RENAMED.value:
            conn.execute(
                "UPDATE dispatcher_gui_conversations SET alias = ?, alias_key = ?, updated_at = ? WHERE gui_id = ?",
                (str(p["alias"]), str(p["alias_key"]), ts, str(p["gui_id"])),
            )

        elif etype == EventType.DISPATCHER_SLOT_CREATED.value:
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_slots(
                    slot_id, gui_id, name, name_key, state, created_at, updated_at, last_activity_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)
                """,
                (str(p["slot_id"]), str(p["gui_id"]), str(p["name"]), str(p["name_key"]), ts, ts),
            )

        elif etype == EventType.DISPATCHER_SLOT_STATE_CHANGED.value:
            conn.execute(
                "UPDATE agent_slots SET state = ?, updated_at = ? WHERE slot_id = ?",
                (str(p["state"]), ts, str(p["slot_id"])),
            )

        elif etype == EventType.DISPATCHER_SLOTS_TRANSITIONED.value:
            for change in p["slot_changes"]:
                conn.execute(
                    "UPDATE agent_slots SET state = ?, updated_at = ? WHERE slot_id = ?",
                    (str(change["state"]), ts, str(change["slot_id"])),
                )
            cycle = p.get("review_cycle")
            if cycle:
                conn.execute(
                    """INSERT INTO dispatcher_review_cycles(
                           cycle_id, original_slot_id, reviewer_slot_id, original_provider,
                           original_environment_id, original_session_id, original_state,
                           reviewer_provider, reviewer_environment_id, reviewer_session_id,
                           status, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(cycle_id) DO UPDATE SET
                           reviewer_provider=excluded.reviewer_provider,
                           reviewer_environment_id=excluded.reviewer_environment_id,
                           reviewer_session_id=excluded.reviewer_session_id,
                           status=excluded.status, updated_at=excluded.updated_at""",
                    (str(cycle["cycle_id"]), str(cycle["original_slot_id"]), str(cycle["reviewer_slot_id"]),
                     str(cycle["original_provider"]), str(cycle["original_environment_id"]),
                     str(cycle["original_session_id"]), str(cycle["original_state"]),
                     cycle.get("reviewer_provider"), cycle.get("reviewer_environment_id"),
                     cycle.get("reviewer_session_id"), str(cycle["status"]),
                     str(cycle.get("created_at") or ts), ts),
                )

        elif etype == EventType.DISPATCHER_AGENT_TRANSITION_COMPLETED.value:
            provider = str(event.provider)
            session_id = str(event.native_session_id)
            session = p.get("session", {})
            conn.execute(
                """INSERT OR IGNORE INTO sessions(
                       provider, environment_id, native_session_id, cwd_native, cwd_canonical,
                       repository_identity, first_observed_at, last_seen_at, metadata_source, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (provider, event.environment_id, session_id, session.get("cwd_native"),
                 session.get("cwd_canonical"), session.get("repository_identity"), ts, ts,
                 str(session.get("metadata_source") or "dispatcher_transition"), ts),
            )
            activation = p["activation"]
            conn.execute(
                """INSERT OR IGNORE INTO agent_slot_activations(
                       activation_id, slot_id, sequence, provider, environment_id,
                       native_session_id, provenance, activated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(activation["activation_id"]), str(activation["slot_id"]), int(activation["sequence"]),
                 provider, event.environment_id, session_id, str(activation["provenance"]), ts),
            )
            conn.execute("UPDATE agent_slots SET updated_at=?, last_activity_at=? WHERE slot_id=?",
                         (ts, ts, str(activation["slot_id"])))
            conn.execute(
                """UPDATE dispatcher_gui_conversations SET updated_at=?, last_activity_at=
                       CASE WHEN last_activity_at IS NULL OR last_activity_at < ? THEN ? ELSE last_activity_at END
                   WHERE gui_id=(SELECT gui_id FROM agent_slots WHERE slot_id=?)""",
                (ts, ts, ts, str(activation["slot_id"])),
            )
            for change in p["slot_changes"]:
                conn.execute("UPDATE agent_slots SET state=?, updated_at=? WHERE slot_id=?",
                             (str(change["state"]), ts, str(change["slot_id"])))
            if p.get("launch_id"):
                conn.execute(
                    """UPDATE dispatcher_pending_launches SET status='resolved', resolved_at=?,
                           resolved_session_id=?, failure_detail=NULL
                       WHERE launch_id=? AND status='pending'""",
                    (ts, session_id, str(p["launch_id"])),
                )
            cycle = p.get("review_cycle")
            if cycle:
                conn.execute(
                    """INSERT INTO dispatcher_review_cycles(
                           cycle_id, original_slot_id, reviewer_slot_id, original_provider,
                           original_environment_id, original_session_id, original_state,
                           reviewer_provider, reviewer_environment_id, reviewer_session_id,
                           status, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(cycle_id) DO UPDATE SET
                           reviewer_provider=excluded.reviewer_provider,
                           reviewer_environment_id=excluded.reviewer_environment_id,
                           reviewer_session_id=excluded.reviewer_session_id,
                           status=excluded.status, updated_at=excluded.updated_at""",
                    (str(cycle["cycle_id"]), str(cycle["original_slot_id"]), str(cycle["reviewer_slot_id"]),
                     str(cycle["original_provider"]), str(cycle["original_environment_id"]),
                     str(cycle["original_session_id"]), str(cycle["original_state"]),
                     cycle.get("reviewer_provider"), cycle.get("reviewer_environment_id"),
                     cycle.get("reviewer_session_id"), str(cycle["status"]),
                     str(cycle.get("created_at") or ts), ts),
                )
        elif etype == EventType.DISPATCHER_SESSION_ACTIVATED.value:
            slot_id = str(p["slot_id"])
            sequence = int(p["sequence"])
            activation_id = str(p["activation_id"])
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_slot_activations(
                    activation_id, slot_id, sequence, provider, environment_id,
                    native_session_id, provenance, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    activation_id,
                    slot_id,
                    sequence,
                    str(event.provider),
                    event.environment_id,
                    str(event.native_session_id),
                    str(p["provenance"]),
                    ts,
                ),
            )
            conn.execute(
                "UPDATE agent_slots SET updated_at = ?, last_activity_at = ? WHERE slot_id = ?",
                (ts, ts, slot_id),
            )
            conn.execute(
                """
                UPDATE dispatcher_gui_conversations SET updated_at = ?, last_activity_at =
                    CASE WHEN last_activity_at IS NULL OR last_activity_at < ? THEN ? ELSE last_activity_at END
                WHERE gui_id = (SELECT gui_id FROM agent_slots WHERE slot_id = ?)
                """,
                (ts, ts, ts, slot_id),
            )

        elif etype == EventType.DISPATCHER_LAUNCH_REQUESTED.value:
            conn.execute(
                """
                INSERT OR IGNORE INTO dispatcher_pending_launches(
                    launch_id, slot_id, provider, environment_id, cwd, status, requested_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    str(p["launch_id"]),
                    str(p["slot_id"]),
                    str(event.provider),
                    event.environment_id,
                    p.get("cwd"),
                    ts,
                ),
            )

        elif etype == EventType.DISPATCHER_LAUNCH_RESOLVED.value:
            conn.execute(
                """
                UPDATE dispatcher_pending_launches
                SET status = 'resolved', resolved_at = ?, resolved_session_id = ?, failure_detail = NULL
                WHERE launch_id = ? AND status = 'pending'
                """,
                (ts, str(p["native_session_id"]), str(p["launch_id"])),
            )

        elif etype == EventType.DISPATCHER_LAUNCH_FAILED.value:
            conn.execute(
                """
                UPDATE dispatcher_pending_launches
                SET status = 'failed', resolved_at = ?, failure_detail = ?
                WHERE launch_id = ? AND status = 'pending'
                """,
                (ts, str(p.get("detail") or "launch failed"), str(p["launch_id"])),
            )

        elif etype == EventType.DISPATCHER_PROCESS_OBSERVED.value:
            launch_id = p.get("launch_id")
            outcome = str(p.get("outcome") or "")
            if launch_id and outcome in {
                "bootstrap_attempt_started", "bootstrap_id_captured", "bootstrap_capture_failed"
            }:
                conn.execute(
                    """UPDATE dispatcher_pending_launches SET failure_detail = ?
                       WHERE launch_id = ? AND status = 'pending'""",
                    (
                        str(p.get("detail") or "A provider bootstrap was attempted; automatic retry is disabled."),
                        str(launch_id),
                    ),
                )

        elif etype == EventType.DISPATCHER_TERMINAL_LAUNCH_RECORDED.value:
            conn.execute(
                """
                INSERT INTO dispatcher_terminal_launches(
                    launch_id, terminal_session_id, terminal_session_owner_pid,
                    gui_id, gui_alias, slot_id, slot_name, provider, native_session_id,
                    environment_id, launch_started_at, launch_exited_at, status, exit_code,
                    requested_cwd, effective_cwd, native_cwd,
                    git_repository, git_worktree, git_branch, git_commit, settings_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(launch_id) DO UPDATE SET
                    terminal_session_owner_pid = excluded.terminal_session_owner_pid,
                    native_session_id = COALESCE(excluded.native_session_id, dispatcher_terminal_launches.native_session_id),
                    native_cwd = COALESCE(dispatcher_terminal_launches.native_cwd, excluded.native_cwd),
                    launch_exited_at = COALESCE(excluded.launch_exited_at, dispatcher_terminal_launches.launch_exited_at),
                    status = excluded.status,
                    exit_code = COALESCE(excluded.exit_code, dispatcher_terminal_launches.exit_code),
                    settings_json = excluded.settings_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(p["launch_id"]), str(p["terminal_session_id"]), p.get("terminal_session_owner_pid"),
                    p.get("gui_id"), p.get("gui_alias"), p.get("slot_id"), p.get("slot_name"),
                    event.provider, event.native_session_id, event.environment_id,
                    str(p["launch_started_at"]), p.get("launch_exited_at"), str(p["status"]),
                    p.get("exit_code"), p.get("requested_cwd"), p.get("effective_cwd"), p.get("native_cwd"),
                    p.get("git_repository"), p.get("git_worktree"), p.get("git_branch"), p.get("git_commit"),
                    json.dumps(p.get("settings") or {}, sort_keys=True, ensure_ascii=False), ts,
                ),
            )

        elif etype == EventType.CHECKPOINT_RECORDED.value:
            conn.execute(
                """
                INSERT OR IGNORE INTO checkpoints(
                    checkpoint_id, workflow_id, provider, environment_id, native_session_id,
                    repository_identity, commit_sha, branch_name, validation_command, exit_code,
                    evidence_source, user_accepted, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(p["checkpoint_id"]),
                    p.get("workflow_id"),
                    event.provider,
                    event.environment_id,
                    event.native_session_id,
                    p.get("repository_identity"),
                    p.get("commit_sha"),
                    p.get("branch_name"),
                    p.get("validation_command"),
                    p.get("exit_code"),
                    str(p.get("evidence_source", "user_reported")),
                    1 if p.get("user_accepted") else 0,
                    ts,
                ),
            )

        conn.execute(
            """
            INSERT INTO activity_events(
                event_id, event_type, provider, environment_id, native_session_id,
                workflow_id, source_timestamp, observed_timestamp, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                event.provider,
                event.environment_id,
                event.native_session_id,
                p.get("workflow_id"),
                event.source_timestamp,
                event.observed_timestamp,
                json.dumps(p),
            ),
        )
        conn.execute(
            """
            INSERT INTO ingested_events(
                event_id, event_type, source_timestamp, observed_timestamp, spool_file, checksum, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                event.source_timestamp,
                event.observed_timestamp,
                spool_file,
                checksum,
                now_utc_iso(),
            ),
        )
        return True

    def _resolve_workflow_id_in_tx(self, conn: sqlite3.Connection, marker: str | None) -> str | None:
        if not marker:
            return None
        row = conn.execute(
            "SELECT workflow_id FROM workflows WHERE (workflow_id = ? OR slug = ?) AND status = 'active'",
            (marker.strip(), marker.strip().lower()),
        ).fetchone()
        return str(row["workflow_id"]) if row else None

    def _apply_hook_event_in_tx(self, conn: sqlite3.Connection, event: EventEnvelope, ts: str) -> None:
        if not event.provider or not event.native_session_id:
            return
        p = event.payload
        self._ensure_env_placeholder(conn, event.environment_id, p.get("environment"), ts)

        norm_type = str(p.get("normalized_event_type") or "session.observed")
        turn_id = p.get("turn_id")
        marker = p.get("workflow_marker")
        conflict_markers = p.get("workflow_markers_conflict") or []

        session_payload = dict(p)
        session_payload.setdefault("first_observed_at", ts)
        session_payload.setdefault("last_seen_at", ts)
        session_payload.setdefault("metadata_source", "hook")
        if norm_type == "session.created":
            session_payload["native_created_at"] = ts
        elif norm_type == "turn.submitted":
            session_payload["last_turn_at"] = ts
        elif norm_type == "turn.completed":
            session_payload["last_completed_turn_at"] = ts

        hook_session_event = EventEnvelope(
            event_id=event.event_id,
            event_schema_version=event.event_schema_version,
            event_type=EventType.SESSION_OBSERVED.value,
            provider=event.provider,
            environment_id=event.environment_id,
            native_session_id=event.native_session_id,
            source_timestamp=event.source_timestamp,
            observed_timestamp=event.observed_timestamp,
            source_adapter_version=event.source_adapter_version,
            payload=session_payload,
        )
        self._upsert_session(conn, hook_session_event, ts)

        resolved_wf_id: str | None = None
        turn_evidence = "unknown"

        existing_rows = conn.execute(
            """
            SELECT association_id, workflow_id, evidence_level, status
            FROM associations
            WHERE provider = ? AND environment_id = ? AND native_session_id = ?
            """,
            (event.provider, event.environment_id, event.native_session_id),
        ).fetchall()

        active_rows = [r for r in existing_rows if r["status"] == AssociationStatus.ACTIVE.value]
        conflict_rows = [r for r in existing_rows if r["status"] == AssociationStatus.CONFLICT.value]

        if conflict_markers:
            # Multiple conflicting markers in one prompt: flag conflicts without picking a winner
            for cand_marker in conflict_markers:
                wf_id = self._resolve_workflow_id_in_tx(conn, str(cand_marker))
                if not wf_id:
                    continue
                assoc_id = f"assoc_{event.event_id}_{wf_id}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO associations(
                        association_id, workflow_id, provider, environment_id, native_session_id,
                        evidence_level, association_method, evidence_summary, evidence_reference,
                        status, first_turn_id, last_turn_id, confirmed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'candidate', 'hook_marker_conflict', ?, ?, 'conflict', ?, ?, NULL, ?, ?)
                    """,
                    (
                        assoc_id,
                        wf_id,
                        event.provider,
                        event.environment_id,
                        event.native_session_id,
                        f"Conflicting workflow markers in prompt: {', '.join(str(m) for m in conflict_markers)}",
                        turn_id,
                        turn_id,
                        turn_id,
                        ts,
                        ts,
                    ),
                )
        elif marker:
            wf_id = self._resolve_workflow_id_in_tx(conn, str(marker))
            if wf_id is not None:
                resolved_wf_id = wf_id
                turn_evidence = "strong"
                same_active = [r for r in active_rows if r["workflow_id"] == wf_id]
                other_confirmed = [
                    r for r in active_rows if r["workflow_id"] != wf_id and r["evidence_level"] == "confirmed"
                ]
                other_strong = [
                    r for r in active_rows if r["workflow_id"] != wf_id and r["evidence_level"] == "strong"
                ]

                if same_active:
                    target_assoc_id = same_active[0]["association_id"]
                    conn.execute(
                        "UPDATE associations SET last_turn_id = COALESCE(?, last_turn_id), updated_at = ? WHERE association_id = ?",
                        (turn_id, ts, target_assoc_id),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO association_evidence(
                            evidence_id, association_id, event_id, evidence_level, evidence_type, detail_json, created_at
                        ) VALUES (?, ?, ?, 'strong', 'workflow_marker', ?, ?)
                        """,
                        (f"evd_{event.event_id}", target_assoc_id, event.event_id, json.dumps({"marker": marker, "turn_id": turn_id}), ts),
                    )
                elif other_confirmed:
                    # Preserve manual confirmation; surface conflict for review (deduplicated)
                    existing_conflict = [r for r in conflict_rows if r["workflow_id"] == wf_id]
                    if existing_conflict:
                        conflict_assoc_id = str(existing_conflict[0]["association_id"])
                        conn.execute(
                            "UPDATE associations SET last_turn_id = COALESCE(?, last_turn_id), updated_at = ? WHERE association_id = ?",
                            (turn_id, ts, conflict_assoc_id),
                        )
                    else:
                        conflict_assoc_id = f"assoc_{event.event_id}"
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO associations(
                                association_id, workflow_id, provider, environment_id, native_session_id,
                                evidence_level, association_method, evidence_summary, evidence_reference,
                                status, first_turn_id, last_turn_id, confirmed_at, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, 'strong', 'workflow_marker_conflict', ?, ?, 'conflict', ?, ?, NULL, ?, ?)
                            """,
                            (
                                conflict_assoc_id,
                                wf_id,
                                event.provider,
                                event.environment_id,
                                event.native_session_id,
                                f"Hook marker {marker!r} conflicts with manual confirmation for {other_confirmed[0]['workflow_id']}",
                                turn_id,
                                turn_id,
                                turn_id,
                                ts,
                                ts,
                            ),
                        )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO association_evidence(
                            evidence_id, association_id, event_id, evidence_level, evidence_type, detail_json, created_at
                        ) VALUES (?, ?, ?, 'strong', 'workflow_marker_conflict', ?, ?)
                        """,
                        (f"evd_{event.event_id}", conflict_assoc_id, event.event_id, json.dumps({"marker": marker, "turn_id": turn_id}), ts),
                    )
                else:
                    # Session repurposing (or first association): supersede prior strong links, create new strong link
                    for old_r in other_strong:
                        conn.execute(
                            "UPDATE associations SET status = ?, updated_at = ? WHERE association_id = ?",
                            (AssociationStatus.SUPERSEDED.value, ts, old_r["association_id"]),
                        )
                    new_assoc_id = f"assoc_{event.event_id}"
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO associations(
                            association_id, workflow_id, provider, environment_id, native_session_id,
                            evidence_level, association_method, evidence_summary, evidence_reference,
                            status, first_turn_id, last_turn_id, confirmed_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'strong', 'workflow_marker', ?, ?, 'active', ?, ?, NULL, ?, ?)
                        """,
                        (
                            new_assoc_id,
                            wf_id,
                            event.provider,
                            event.environment_id,
                            event.native_session_id,
                            f"Automatic association via Workflow-ID marker ({marker})",
                            turn_id,
                            turn_id,
                            turn_id,
                            ts,
                            ts,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO association_evidence(
                            evidence_id, association_id, event_id, evidence_level, evidence_type, detail_json, created_at
                        ) VALUES (?, ?, ?, 'strong', 'workflow_marker', ?, ?)
                        """,
                        (f"evd_{event.event_id}", new_assoc_id, event.event_id, json.dumps({"marker": marker, "turn_id": turn_id}), ts),
                    )
        else:
            # Untagged turn or resume: inherit only when unambiguous active association exists and no conflicts
            unambiguous = [r for r in active_rows if r["evidence_level"] in ("confirmed", "strong")]
            if not conflict_rows and len(unambiguous) == 1:
                resolved_wf_id = str(unambiguous[0]["workflow_id"])
                turn_evidence = str(unambiguous[0]["evidence_level"])
                if turn_id:
                    conn.execute(
                        "UPDATE associations SET last_turn_id = ?, updated_at = ? WHERE association_id = ?",
                        (turn_id, ts, unambiguous[0]["association_id"]),
                    )

        if norm_type == "turn.submitted":
            t_id = str(turn_id or f"turn_{event.event_id}")
            conn.execute(
                """
                INSERT OR REPLACE INTO turns(
                    turn_id, provider, environment_id, native_session_id, workflow_id,
                    evidence_level, marker_text, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    t_id,
                    event.provider,
                    event.environment_id,
                    event.native_session_id,
                    resolved_wf_id,
                    turn_evidence,
                    str(marker) if marker else None,
                    ts,
                ),
            )
        elif norm_type == "turn.completed":
            if turn_id:
                cur = conn.execute(
                    "UPDATE turns SET completed_at = ? WHERE turn_id = ?",
                    (ts, str(turn_id)),
                )
                if cur.rowcount == 0:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO turns(
                            turn_id, provider, environment_id, native_session_id, workflow_id,
                            evidence_level, marker_text, started_at, completed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                        """,
                        (
                            str(turn_id),
                            event.provider,
                            event.environment_id,
                            event.native_session_id,
                            resolved_wf_id,
                            turn_evidence,
                            ts,
                        ),
                    )
            else:
                latest_open = conn.execute(
                    """
                    SELECT turn_id FROM turns
                    WHERE provider = ? AND environment_id = ? AND native_session_id = ? AND completed_at IS NULL
                    ORDER BY started_at DESC LIMIT 1
                    """,
                    (event.provider, event.environment_id, event.native_session_id),
                ).fetchone()
                if latest_open is not None:
                    conn.execute(
                        "UPDATE turns SET completed_at = ? WHERE turn_id = ?",
                        (ts, latest_open["turn_id"]),
                    )

    def _select_slot_from_user_prompt_in_tx(self, conn: sqlite3.Connection, event: EventEnvelope, ts: str) -> None:
        """A verified user-prompt hook can reactivate a session already bound to a slot."""
        if (
            event.payload.get("normalized_event_type") != "turn.submitted"
            or not event.provider
            or not event.native_session_id
        ):
            return
        rows = conn.execute(
            """
            SELECT s.slot_id,
                   (SELECT MAX(all_a.sequence) FROM agent_slot_activations all_a WHERE all_a.slot_id = s.slot_id) AS last_sequence,
                   current.provider AS current_provider,
                   current.environment_id AS current_environment_id,
                   current.native_session_id AS current_session_id
            FROM agent_slot_activations a
            JOIN agent_slots s ON s.slot_id = a.slot_id
            LEFT JOIN agent_slot_activations current
              ON current.activation_id = (
                 SELECT cur.activation_id FROM agent_slot_activations cur
                 WHERE cur.slot_id = s.slot_id ORDER BY cur.sequence DESC LIMIT 1
              )
            WHERE a.provider = ? AND a.environment_id = ? AND a.native_session_id = ?
            GROUP BY s.slot_id
            """,
            (event.provider, event.environment_id, event.native_session_id),
        ).fetchall()
        if len(rows) != 1:
            return
        for row in rows:
            if (
                row["current_provider"], row["current_environment_id"], row["current_session_id"]
            ) == (event.provider, event.environment_id, event.native_session_id):
                conn.execute(
                    "UPDATE agent_slots SET updated_at = ?, last_activity_at = ? WHERE slot_id = ?",
                    (ts, ts, str(row["slot_id"])),
                )
                conn.execute(
                    "UPDATE dispatcher_gui_conversations SET updated_at = ?, last_activity_at = ? "
                    "WHERE gui_id = (SELECT gui_id FROM agent_slots WHERE slot_id = ?)",
                    (ts, ts, str(row["slot_id"])),
                )
                continue
            sequence = int(row["last_sequence"]) + 1
            activation_id = f"act_{event.event_id}_{row['slot_id']}"
            inserted = conn.execute(
                """
                INSERT OR IGNORE INTO agent_slot_activations(
                    activation_id, slot_id, sequence, provider, environment_id,
                    native_session_id, provenance, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'verified_user_prompt', ?)
                """,
                (
                    activation_id,
                    str(row["slot_id"]),
                    sequence,
                    event.provider,
                    event.environment_id,
                    event.native_session_id,
                    ts,
                ),
            )
            if inserted.rowcount == 0:
                continue
            conn.execute(
                "UPDATE agent_slots SET updated_at = ?, last_activity_at = ? WHERE slot_id = ?",
                (ts, ts, str(row["slot_id"])),
            )
            conn.execute(
                """
                UPDATE dispatcher_gui_conversations SET updated_at = ?, last_activity_at = ?
                WHERE gui_id = (SELECT gui_id FROM agent_slots WHERE slot_id = ?)
                """,
                (ts, ts, str(row["slot_id"])),
            )

    def _upsert_environment(
        self,
        conn: sqlite3.Connection,
        *,
        environment_id: str,
        runtime_kind: str,
        distro: str | None,
        hostname: str | None,
        label: str | None,
        created_at: str,
        last_seen_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO environments(environment_id, runtime_kind, distro, hostname, label, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(environment_id) DO UPDATE SET
                runtime_kind = CASE WHEN excluded.runtime_kind != 'unknown' THEN excluded.runtime_kind ELSE environments.runtime_kind END,
                distro = COALESCE(excluded.distro, environments.distro),
                hostname = CASE WHEN excluded.hostname != '' THEN excluded.hostname ELSE environments.hostname END,
                label = COALESCE(excluded.label, environments.label),
                last_seen_at = MAX(environments.last_seen_at, excluded.last_seen_at)
            """,
            (environment_id, runtime_kind, distro, hostname or "", label or environment_id, created_at, last_seen_at),
        )

    def _ensure_env_placeholder(
        self,
        conn: sqlite3.Connection,
        environment_id: str,
        env_payload: dict[str, Any] | None,
        ts: str,
    ) -> None:
        if isinstance(env_payload, dict) and env_payload:
            self._upsert_environment(
                conn,
                environment_id=environment_id,
                runtime_kind=str(env_payload.get("runtime_kind", "unknown")),
                distro=env_payload.get("distro"),
                hostname=env_payload.get("hostname"),
                label=env_payload.get("label") or environment_id,
                created_at=str(env_payload.get("created_at") or ts),
                last_seen_at=ts,
            )
            return
        row = conn.execute("SELECT 1 FROM environments WHERE environment_id = ?", (environment_id,)).fetchone()
        if row is None:
            self._upsert_environment(
                conn,
                environment_id=environment_id,
                runtime_kind="unknown",
                distro=None,
                hostname="",
                label=environment_id,
                created_at=ts,
                last_seen_at=ts,
            )

    def _ensure_session_placeholder(self, conn: sqlite3.Connection, event: EventEnvelope, ts: str) -> None:
        if not event.provider or not event.native_session_id:
            return
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE provider = ? AND environment_id = ? AND native_session_id = ?",
            (event.provider, event.environment_id, event.native_session_id),
        ).fetchone()
        if row is None:
            self._upsert_session(conn, event, ts)

    def _upsert_session(self, conn: sqlite3.Connection, event: EventEnvelope, ts: str) -> None:
        if not event.provider or not event.native_session_id:
            return
        p = event.payload
        cwd_native = p.get("cwd_native")
        cwd_canonical = p.get("cwd_canonical") or normalize_path_canonical(cwd_native)
        repo_id = p.get("repository_identity") or normalize_repo_identity(p.get("repository_path") or cwd_native)
        conn.execute(
            """
            INSERT INTO sessions(
                provider, environment_id, native_session_id, native_root_id, parent_session_id,
                surface, native_version, cwd_native, cwd_canonical, repository_identity,
                native_title, transcript_reference, created_at, first_observed_at,
                last_seen_at, last_turn_at, last_completed_turn_at, lifecycle_status,
                metadata_source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, environment_id, native_session_id) DO UPDATE SET
                native_root_id = COALESCE(excluded.native_root_id, sessions.native_root_id),
                parent_session_id = COALESCE(excluded.parent_session_id, sessions.parent_session_id),
                surface = COALESCE(excluded.surface, sessions.surface),
                native_version = COALESCE(excluded.native_version, sessions.native_version),
                cwd_native = COALESCE(excluded.cwd_native, sessions.cwd_native),
                cwd_canonical = COALESCE(excluded.cwd_canonical, sessions.cwd_canonical),
                repository_identity = COALESCE(excluded.repository_identity, sessions.repository_identity),
                native_title = COALESCE(excluded.native_title, sessions.native_title),
                transcript_reference = COALESCE(excluded.transcript_reference, sessions.transcript_reference),
                created_at = COALESCE(sessions.created_at, excluded.created_at),
                last_seen_at = COALESCE(
                    CASE
                        WHEN excluded.last_seen_at IS NULL THEN sessions.last_seen_at
                        WHEN sessions.last_seen_at IS NULL THEN excluded.last_seen_at
                        ELSE MAX(sessions.last_seen_at, excluded.last_seen_at)
                    END,
                    sessions.last_seen_at
                ),
                last_turn_at = COALESCE(
                    CASE
                        WHEN excluded.last_turn_at IS NULL THEN sessions.last_turn_at
                        WHEN sessions.last_turn_at IS NULL THEN excluded.last_turn_at
                        ELSE MAX(sessions.last_turn_at, excluded.last_turn_at)
                    END,
                    sessions.last_turn_at
                ),
                last_completed_turn_at = COALESCE(
                    CASE
                        WHEN excluded.last_completed_turn_at IS NULL THEN sessions.last_completed_turn_at
                        WHEN sessions.last_completed_turn_at IS NULL THEN excluded.last_completed_turn_at
                        ELSE MAX(sessions.last_completed_turn_at, excluded.last_completed_turn_at)
                    END,
                    sessions.last_completed_turn_at
                ),
                lifecycle_status = COALESCE(excluded.lifecycle_status, sessions.lifecycle_status),
                updated_at = excluded.updated_at
            """,
            (
                event.provider,
                event.environment_id,
                event.native_session_id,
                p.get("native_root_id"),
                p.get("parent_session_id"),
                p.get("surface"),
                p.get("native_version"),
                cwd_native,
                cwd_canonical,
                repo_id,
                p.get("native_title"),
                p.get("transcript_reference"),
                p.get("native_created_at"),
                str(p.get("first_observed_at") or ts),
                p.get("last_seen_at") or ts,
                p.get("last_turn_at"),
                p.get("last_completed_turn_at"),
                str(p.get("lifecycle_status") or "active"),
                str(p.get("metadata_source") or "manual"),
                ts,
            ),
        )

    # ------------------------------------------------------------------
    # Read-only query helpers
    # ------------------------------------------------------------------

    def list_workflows(self, *, status: str | None = "active") -> list[Workflow]:
        conn = self._connect_ro()
        if conn is None:
            return []
        try:
            if status and status != "all":
                rows = conn.execute(
                    "SELECT * FROM workflows WHERE status = ? ORDER BY updated_at DESC, workflow_id ASC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workflows ORDER BY updated_at DESC, workflow_id ASC"
                ).fetchall()
            return [self._row_to_workflow(conn, row) for row in rows]
        finally:
            conn.close()

    def get_workflow(self, identifier: str) -> Workflow | None:
        conn = self._connect_ro()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM workflows WHERE workflow_id = ? OR slug = ?",
                (identifier.strip(), identifier.strip().lower()),
            ).fetchone()
            return self._row_to_workflow(conn, row) if row else None
        finally:
            conn.close()

    def _row_to_workflow(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Workflow:
        gui_rows = conn.execute(
            "SELECT * FROM gui_conversations WHERE workflow_id = ? AND status = 'active' ORDER BY created_at ASC",
            (row["workflow_id"],),
        ).fetchall()
        guis = [
            GuiConversation(
                gui_ref_id=g["gui_ref_id"],
                workflow_id=g["workflow_id"],
                url=g["url"],
                canonical_url=g["canonical_url"],
                title=g["title"],
                relationship=g["relationship"],
                status=g["status"],
                created_at=g["created_at"],
                updated_at=g["updated_at"],
            )
            for g in gui_rows
        ]
        try:
            repos = json.loads(row["repo_paths_json"])
        except json.JSONDecodeError:
            repos = []
        return Workflow(
            workflow_id=row["workflow_id"],
            slug=row["slug"],
            title=row["title"],
            repo_paths=repos,
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            gui_conversations=guis,
        )

    def list_environments(self) -> list[EnvironmentInfo]:
        conn = self._connect_ro()
        if conn is None:
            return []
        try:
            rows = conn.execute("SELECT * FROM environments ORDER BY environment_id ASC").fetchall()
            return [
                EnvironmentInfo(
                    environment_id=r["environment_id"],
                    runtime_kind=r["runtime_kind"],
                    distro=r["distro"],
                    hostname=r["hostname"] or "",
                    label=r["label"] or r["environment_id"],
                    created_at=r["created_at"],
                    last_seen_at=r["last_seen_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def list_sessions(
        self,
        *,
        provider: str | None = None,
        environment_id: str | None = None,
        native_session_id: str | None = None,
    ) -> list[SessionRecord]:
        conn = self._connect_ro()
        if conn is None:
            return []
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if provider:
                clauses.append("provider = ?")
                params.append(provider)
            if environment_id:
                clauses.append("environment_id = ?")
                params.append(environment_id)
            if native_session_id:
                clauses.append("native_session_id = ?")
                params.append(native_session_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM sessions {where} ORDER BY COALESCE(last_turn_at, last_seen_at, first_observed_at) DESC",
                params,
            ).fetchall()
            return [self._row_to_session(r) for r in rows]
        finally:
            conn.close()

    def get_session(self, provider: str, environment_id: str, native_session_id: str) -> SessionRecord | None:
        sessions = self.list_sessions(
            provider=provider,
            environment_id=environment_id,
            native_session_id=native_session_id,
        )
        return sessions[0] if sessions else None

    def _row_to_session(self, r: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            provider=r["provider"],
            environment_id=r["environment_id"],
            native_session_id=r["native_session_id"],
            native_root_id=r["native_root_id"],
            parent_session_id=r["parent_session_id"],
            surface=r["surface"],
            native_version=r["native_version"],
            cwd_native=r["cwd_native"],
            cwd_canonical=r["cwd_canonical"],
            repository_identity=r["repository_identity"],
            native_title=r["native_title"],
            transcript_reference=r["transcript_reference"],
            created_at=r["created_at"],
            first_observed_at=r["first_observed_at"],
            last_seen_at=r["last_seen_at"],
            last_turn_at=r["last_turn_at"],
            last_completed_turn_at=r["last_completed_turn_at"],
            lifecycle_status=r["lifecycle_status"],
            metadata_source=r["metadata_source"],
            updated_at=r["updated_at"],
        )

    def list_associations(
        self,
        *,
        workflow_id: str | None = None,
        provider: str | None = None,
        environment_id: str | None = None,
        native_session_id: str | None = None,
        status: str | None = None,
    ) -> list[AssociationRecord]:
        conn = self._connect_ro()
        if conn is None:
            return []
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if workflow_id:
                clauses.append("workflow_id = ?")
                params.append(workflow_id)
            if provider:
                clauses.append("provider = ?")
                params.append(provider)
            if environment_id:
                clauses.append("environment_id = ?")
                params.append(environment_id)
            if native_session_id:
                clauses.append("native_session_id = ?")
                params.append(native_session_id)
            if status:
                clauses.append("status = ?")
                params.append(status)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM associations {where} ORDER BY updated_at DESC, association_id ASC",
                params,
            ).fetchall()
            return [
                AssociationRecord(
                    association_id=r["association_id"],
                    workflow_id=r["workflow_id"],
                    provider=r["provider"],
                    environment_id=r["environment_id"],
                    native_session_id=r["native_session_id"],
                    evidence_level=r["evidence_level"],
                    association_method=r["association_method"],
                    evidence_summary=r["evidence_summary"],
                    evidence_reference=r["evidence_reference"],
                    status=r["status"],
                    first_turn_id=r["first_turn_id"],
                    last_turn_id=r["last_turn_id"],
                    confirmed_at=r["confirmed_at"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        """Return read-only SQLite metadata, schema version, and row counts."""
        if not self.db_path.exists():
            return {
                "db_exists": False,
                "db_path": str(self.db_path),
                "schema_version": None,
                "supported_schema_version": SCHEMA_VERSION,
                "integrity": "not_initialized",
                "counts": {},
                "last_sync_at": None,
                "last_rebuild_at": None,
            }
        conn = self._connect_ro()
        assert conn is not None
        try:
            ver = get_schema_version(conn)
            integrity_row = conn.execute("PRAGMA quick_check;").fetchone()
            meta = {
                r["key"]: r["value"]
                for r in conn.execute("SELECT key, value FROM schema_metadata").fetchall()
            }
            counts = {}
            for table in ("workflows", "gui_conversations", "environments", "sessions", "associations", "ingested_events"):
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            return {
                "db_exists": True,
                "db_path": str(self.db_path),
                "schema_version": ver,
                "supported_schema_version": SCHEMA_VERSION,
                "integrity": integrity_row[0] if integrity_row else "unknown",
                "counts": counts,
                "last_sync_at": meta.get("last_sync_at"),
                "last_rebuild_at": meta.get("last_rebuild_at"),
            }
        finally:
            conn.close()
