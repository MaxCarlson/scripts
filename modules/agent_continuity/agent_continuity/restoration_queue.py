"""Crash-consistent shared manual restoration queue (LLMD-43)."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .errors import ContinuityError, ErrorCode
from .identifiers import generate_id, now_utc_iso
from .workspace_checkpoint import (
    CheckpointSessionEntry,
    WorkspaceCheckpoint,
    WorkspaceSlotMetadata,
    WorkspaceTopologyRequest,
    WorkspaceWorktreeEvidence,
    _checkpoint_lock,
    sanitize_launch_settings,
)

QUEUE_SCHEMA_VERSION = 2


class QueueEntryStatus(StrEnum):
    """Durable lifecycle state of one restoration queue entry."""

    PENDING = "pending"
    CLAIMED = "claimed"
    LAUNCHING = "launching"
    AMBIGUOUS = "ambiguous"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


UNRESOLVED_QUEUE_STATUSES = frozenset(
    {
        QueueEntryStatus.PENDING.value,
        QueueEntryStatus.CLAIMED.value,
        QueueEntryStatus.LAUNCHING.value,
        QueueEntryStatus.AMBIGUOUS.value,
        QueueEntryStatus.FAILED.value,
    }
)

ACTIVE_SLOT_EXCLUSION_STATUSES = frozenset(
    {
        QueueEntryStatus.CLAIMED.value,
        QueueEntryStatus.LAUNCHING.value,
        QueueEntryStatus.AMBIGUOUS.value,
    }
)


@dataclass(frozen=True, slots=True)
class QueueEntry:
    """One deduplicated restoration queue item keyed by (checkpoint_id, slot_id)."""

    queue_entry_id: str
    checkpoint_id: str
    slot_id: str
    gui_id: str
    provider: str
    native_session_id: str
    environment_id: str
    runtime_kind: str
    status: QueueEntryStatus
    created_at: str
    updated_at: str
    attempts: int = 0
    claimed_by: str | None = None
    claim_token: str | None = None
    claimed_at: str | None = None
    completed_at: str | None = None
    launch_id: str | None = None
    launch_submission_state: str = "not_started"
    spawn_confirmed: bool = False
    partial: bool = False
    recovery_note: str | None = None
    gui_alias: str | None = None
    slot_name: str | None = None
    worktree: WorkspaceWorktreeEvidence | None = None
    launch_settings: dict[str, Any] | None = None
    requested_topology: WorkspaceTopologyRequest | None = None
    metadata: WorkspaceSlotMetadata | None = None

    @property
    def is_unresolved(self) -> bool:
        return self.status.value in UNRESOLVED_QUEUE_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_entry_id": self.queue_entry_id,
            "checkpoint_id": self.checkpoint_id,
            "slot_id": self.slot_id,
            "gui_id": self.gui_id,
            "provider": self.provider,
            "native_session_id": self.native_session_id,
            "environment_id": self.environment_id,
            "runtime_kind": self.runtime_kind,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "attempts": self.attempts,
            "claimed_by": self.claimed_by,
            "claim_token": self.claim_token,
            "claimed_at": self.claimed_at,
            "completed_at": self.completed_at,
            "launch_id": self.launch_id,
            "launch_submission_state": self.launch_submission_state,
            "spawn_confirmed": self.spawn_confirmed,
            "partial": self.partial,
            "recovery_note": self.recovery_note,
            "gui_alias": self.gui_alias,
            "slot_name": self.slot_name,
            "worktree": self.worktree.to_dict() if self.worktree else None,
            "launch_settings": dict(self.launch_settings) if self.launch_settings else {},
            "requested_topology": self.requested_topology.to_dict() if self.requested_topology else None,
            "metadata": self.metadata.to_dict() if self.metadata else None,
        }


@dataclass(frozen=True, slots=True)
class ClaimRecoveryEvidence:
    """Explicit guarded evidence required before recovering an abandoned claim."""

    verified_abandoned: bool
    reason: str
    expected_claimed_by: str | None = None
    expected_claim_token: str | None = None
    min_claim_age_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    """Result of enqueuing one checkpoint into the shared restoration queue."""

    checkpoint_id: str
    enqueued: tuple[QueueEntry, ...]
    deduplicated: tuple[QueueEntry, ...]


@dataclass(frozen=True, slots=True)
class ClaimResult:
    """Atomic claim outcome for a queue entry."""

    acquired: bool
    reason: str
    entry: QueueEntry | None = None
    claim_token: str | None = None


_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS queue_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS queue_entries (
    queue_entry_id TEXT PRIMARY KEY,
    checkpoint_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    gui_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    runtime_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    claimed_by TEXT,
    claim_token TEXT,
    claimed_at TEXT,
    completed_at TEXT,
    launch_id TEXT,
    launch_submission_state TEXT NOT NULL DEFAULT 'not_started',
    spawn_confirmed INTEGER NOT NULL DEFAULT 0,
    partial INTEGER NOT NULL DEFAULT 0,
    recovery_note TEXT,
    gui_alias TEXT,
    slot_name TEXT,
    worktree_json TEXT,
    launch_settings_json TEXT,
    requested_topology_json TEXT,
    metadata_json TEXT,
    UNIQUE(checkpoint_id, slot_id)
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON queue_entries(status, created_at, queue_entry_id);
CREATE INDEX IF NOT EXISTS idx_queue_checkpoint ON queue_entries(checkpoint_id, slot_id);
CREATE INDEX IF NOT EXISTS idx_queue_slot ON queue_entries(slot_id, status);
"""


class RestorationQueue:
    """Crash-consistent durable restoration queue backed by an authoritative event log."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.db_path = self.root_dir / "restoration_queue.sqlite3"
        self.events_path = self.root_dir / "restoration_queue.events.jsonl"
        self.lock_path = self.root_dir / ".restoration_queue.lock"

    @contextlib.contextmanager
    def _open_conn(self, db_path: Path | None = None):
        target = db_path or self.db_path
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_initialized_locked(self) -> None:
        with self._open_conn() as conn:
            conn.executescript(_QUEUE_DDL)
        self._sync_from_log_locked()

    def _read_valid_events(self) -> tuple[list[dict[str, Any]], bool]:
        """Read complete JSONL events; validate sequence continuity and reject corrupt complete records."""
        if not self.events_path.exists():
            return [], False
        raw_bytes = self.events_path.read_bytes()
        if not raw_bytes:
            return [], False
        text = raw_bytes.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        events: list[dict[str, Any]] = []
        had_partial_tail = False
        for idx, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            if not stripped:
                continue
            is_last = idx == len(lines) - 1
            if is_last and not raw_line.endswith("\n"):
                had_partial_tail = True
                break
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ContinuityError(
                    ErrorCode.EVENT_SPOOL_UNAVAILABLE,
                    f"Corrupt JSON record at line {idx + 1} in restoration queue log {self.events_path}: {exc}",
                ) from exc
            if not isinstance(parsed, dict) or "event_type" not in parsed or "payload" not in parsed:
                raise ContinuityError(
                    ErrorCode.EVENT_SPOOL_UNAVAILABLE,
                    f"Invalid event envelope at line {idx + 1} in restoration queue log {self.events_path}.",
                )
            expected_seq = len(events) + 1
            raw_seq = parsed.get("event_seq")
            if raw_seq is None or int(raw_seq) != expected_seq:
                raise ContinuityError(
                    ErrorCode.EVENT_SPOOL_UNAVAILABLE,
                    f"Event sequence discontinuity at line {idx + 1}: expected {expected_seq}, got {raw_seq!r}.",
                    {"expected_seq": expected_seq, "actual_seq": raw_seq},
                )
            events.append(parsed)
        return events, had_partial_tail

    def _truncate_partial_tail_locked(self, events: Sequence[dict[str, Any]]) -> None:
        tmp = self.events_path.with_name(f".tmp.{os.getpid()}.events.jsonl")
        content = "".join(json.dumps(ev, sort_keys=True, ensure_ascii=False) + "\n" for ev in events)
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.events_path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise ContinuityError(
                ErrorCode.EVENT_SPOOL_UNAVAILABLE,
                f"Failed to fsync/replace truncated restoration queue log {self.events_path}: {exc}",
            ) from exc

    def _sync_from_log_locked(self) -> int:
        """Apply any committed log events not yet reflected in SQLite."""
        events, had_partial_tail = self._read_valid_events()
        if had_partial_tail:
            self._truncate_partial_tail_locked(events)
        if not events:
            return 0
        with self._open_conn() as conn:
            conn.executescript(_QUEUE_DDL)
            row = conn.execute("SELECT value FROM queue_meta WHERE key = 'applied_seq'").fetchone()
            applied_seq = int(row["value"]) if row is not None else 0
            pending = [(idx + 1, ev) for idx, ev in enumerate(events) if (idx + 1) > applied_seq]
            if not pending:
                return 0
            conn.execute("BEGIN IMMEDIATE")
            try:
                for seq, ev in pending:
                    self._apply_event(conn, ev["event_type"], ev["payload"])
                    applied_seq = seq
                conn.execute(
                    "INSERT OR REPLACE INTO queue_meta(key, value) VALUES ('applied_seq', ?)",
                    (str(applied_seq),),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return len(pending)

    def _commit_event_locked(self, event_type: str, payload: Mapping[str, Any]) -> None:
        """Append event to authoritative log (fsync) first, then apply to SQLite projection."""
        events, had_partial_tail = self._read_valid_events()
        if had_partial_tail:
            self._truncate_partial_tail_locked(events)
        seq = len(events) + 1
        record = {
            "schema_version": QUEUE_SCHEMA_VERSION,
            "event_seq": seq,
            "event_id": generate_id("qev"),
            "event_type": event_type,
            "recorded_at": now_utc_iso(),
            "payload": dict(payload),
        }
        line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        prev_size = self.events_path.stat().st_size if self.events_path.exists() else 0
        try:
            with self.events_path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            with contextlib.suppress(OSError), self.events_path.open("r+b") as fh_rollback:
                fh_rollback.truncate(prev_size)
            raise ContinuityError(
                ErrorCode.EVENT_SPOOL_UNAVAILABLE,
                f"Failed to append and fsync restoration queue event {self.events_path}: {exc}",
            ) from exc

        with self._open_conn() as conn:
            conn.executescript(_QUEUE_DDL)
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._apply_event(conn, event_type, payload)
                conn.execute(
                    "INSERT OR REPLACE INTO queue_meta(key, value) VALUES ('applied_seq', ?)",
                    (str(seq),),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def enqueue_checkpoint(
        self,
        checkpoint: WorkspaceCheckpoint,
        *,
        slot_ids: Sequence[str] | None = None,
    ) -> EnqueueResult:
        """Enqueue checkpoint entries deduplicated by immutable (checkpoint_id, slot_id)."""
        selected = set(slot_ids) if slot_ids is not None else None
        enqueued: list[QueueEntry] = []
        deduplicated: list[QueueEntry] = []

        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            for item in checkpoint.sessions:
                if selected is not None and item.slot_id not in selected:
                    continue
                entry, created = self._enqueue_one_locked(checkpoint.checkpoint_id, item)
                if created:
                    enqueued.append(entry)
                else:
                    deduplicated.append(entry)

        return EnqueueResult(
            checkpoint_id=checkpoint.checkpoint_id,
            enqueued=tuple(enqueued),
            deduplicated=tuple(deduplicated),
        )

    def _enqueue_one_locked(self, checkpoint_id: str, item: CheckpointSessionEntry) -> tuple[QueueEntry, bool]:
        with self._open_conn() as conn:
            existing = conn.execute(
                "SELECT * FROM queue_entries WHERE checkpoint_id = ? AND slot_id = ?",
                (checkpoint_id, item.slot_id),
            ).fetchone()
            if existing is not None:
                return self._row_to_entry(existing), False

        now = now_utc_iso()
        entry = QueueEntry(
            queue_entry_id=generate_id("rq"),
            checkpoint_id=checkpoint_id,
            slot_id=item.slot_id,
            gui_id=item.gui_id,
            provider=item.provider,
            native_session_id=item.native_session_id,
            environment_id=item.environment_id,
            runtime_kind=item.runtime_kind,
            status=QueueEntryStatus.PENDING,
            created_at=now,
            updated_at=now,
            attempts=0,
            gui_alias=item.gui_alias,
            slot_name=item.slot_name,
            worktree=item.worktree,
            launch_settings=sanitize_launch_settings(item.launch_settings),
            requested_topology=item.requested_topology,
            metadata=item.metadata,
        )
        self._commit_event_locked("queue.enqueued", entry.to_dict())
        return entry, True

    def claim(self, queue_entry_id: str, *, operator_id: str) -> ClaimResult:
        """Atomically claim a pending or failed entry while enforcing slot-wide exclusion."""
        if not operator_id or not operator_id.strip():
            raise ContinuityError(ErrorCode.INVALID_INPUT, "operator_id cannot be empty.")

        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            with self._open_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM queue_entries WHERE queue_entry_id = ?",
                    (queue_entry_id,),
                ).fetchone()
                if row is None:
                    return ClaimResult(acquired=False, reason="not_found")
                status = row["status"]
                if status == QueueEntryStatus.AMBIGUOUS.value:
                    return ClaimResult(
                        acquired=False,
                        reason="ambiguous_launch_requires_resolution",
                        entry=self._row_to_entry(row),
                    )
                if status not in {QueueEntryStatus.PENDING.value, QueueEntryStatus.FAILED.value}:
                    return ClaimResult(
                        acquired=False,
                        reason=f"already_{status}",
                        entry=self._row_to_entry(row),
                    )
                busy = conn.execute(
                    """SELECT queue_entry_id, checkpoint_id, status FROM queue_entries
                       WHERE slot_id = ? AND queue_entry_id != ? AND status IN (?, ?, ?)""",
                    (
                        row["slot_id"],
                        queue_entry_id,
                        QueueEntryStatus.CLAIMED.value,
                        QueueEntryStatus.LAUNCHING.value,
                        QueueEntryStatus.AMBIGUOUS.value,
                    ),
                ).fetchone()
                if busy is not None:
                    reason = (
                        "slot_ambiguous_requires_resolution"
                        if busy["status"] == QueueEntryStatus.AMBIGUOUS.value
                        else "slot_busy_other_checkpoint"
                    )
                    return ClaimResult(
                        acquired=False,
                        reason=reason,
                        entry=self._row_to_entry(row),
                    )

            claim_token = generate_id("clm")
            now = now_utc_iso()
            attempts = int(row["attempts"]) + 1
            self._commit_event_locked(
                "queue.claimed",
                {
                    "queue_entry_id": queue_entry_id,
                    "claimed_by": operator_id,
                    "claim_token": claim_token,
                    "claimed_at": now,
                    "attempts": attempts,
                },
            )
            with self._open_conn() as conn:
                updated = conn.execute(
                    "SELECT * FROM queue_entries WHERE queue_entry_id = ?",
                    (queue_entry_id,),
                ).fetchone()
            return ClaimResult(
                acquired=True,
                reason="claimed",
                entry=self._row_to_entry(updated),
                claim_token=claim_token,
            )

    def claim_next(self, *, operator_id: str, checkpoint_id: str | None = None) -> ClaimResult | None:
        """Atomically claim the oldest pending/failed entry (optionally filtered by checkpoint)."""
        entries = self.list_entries(checkpoint_id=checkpoint_id, unresolved_only=True)
        for entry in entries:
            if entry.status in {QueueEntryStatus.PENDING, QueueEntryStatus.FAILED}:
                result = self.claim(entry.queue_entry_id, operator_id=operator_id)
                if result.acquired:
                    return result
        return None

    def mark_launching(
        self,
        queue_entry_id: str,
        *,
        claim_token: str,
    ) -> QueueEntry:
        """Record durably before spawning that a claimed entry has entered launch submission."""
        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            row = self._require_claimed_row_locked(
                queue_entry_id,
                claim_token=claim_token,
                allowed_statuses={QueueEntryStatus.CLAIMED.value},
            )
            now = now_utc_iso()
            self._commit_event_locked(
                "queue.launching",
                {
                    "queue_entry_id": str(row["queue_entry_id"]),
                    "claim_token": claim_token,
                    "updated_at": now,
                    "launch_submission_state": "submitting",
                },
            )
            return self._load_entry_locked(queue_entry_id)

    def mark_ambiguous(
        self,
        queue_entry_id: str,
        *,
        claim_token: str,
        reason: str,
        launch_id: str | None = None,
        launch_submission_state: str = "ambiguous",
    ) -> QueueEntry:
        """Transition a claimed/launching entry to AMBIGUOUS so it is never blindly retried."""
        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            self._require_claimed_row_locked(
                queue_entry_id,
                claim_token=claim_token,
                allowed_statuses={QueueEntryStatus.CLAIMED.value, QueueEntryStatus.LAUNCHING.value},
            )
            now = now_utc_iso()
            self._commit_event_locked(
                "queue.ambiguous",
                {
                    "queue_entry_id": queue_entry_id,
                    "claim_token": claim_token,
                    "updated_at": now,
                    "launch_id": launch_id,
                    "launch_submission_state": launch_submission_state,
                    "recovery_note": reason,
                },
            )
            return self._load_entry_locked(queue_entry_id)

    def resolve_ambiguous(
        self,
        queue_entry_id: str,
        *,
        operator_id: str,
        outcome: str,
        reason: str,
        launch_id: str | None = None,
    ) -> QueueEntry:
        """Explicitly resolve an AMBIGUOUS entry to completed, failed, or cancelled."""
        if outcome not in {"completed", "failed", "cancelled"}:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                f"Invalid ambiguous resolution outcome {outcome!r}; expected completed, failed, or cancelled.",
            )
        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            with self._open_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM queue_entries WHERE queue_entry_id = ?",
                    (queue_entry_id,),
                ).fetchone()
                if row is None:
                    raise ContinuityError(ErrorCode.SESSION_NOT_FOUND, f"Queue entry {queue_entry_id!r} was not found.")
                if row["status"] != QueueEntryStatus.AMBIGUOUS.value:
                    raise ContinuityError(
                        ErrorCode.ASSOCIATION_CONFLICT,
                        f"Queue entry {queue_entry_id!r} is {row['status']}, not ambiguous.",
                    )
            now = now_utc_iso()
            self._commit_event_locked(
                "queue.ambiguous_resolved",
                {
                    "queue_entry_id": queue_entry_id,
                    "operator_id": operator_id,
                    "outcome": outcome,
                    "updated_at": now,
                    "launch_id": launch_id,
                    "recovery_note": f"{operator_id}: {reason}",
                },
            )
            return self._load_entry_locked(queue_entry_id)

    def recover_abandoned_claim(
        self,
        queue_entry_id: str,
        *,
        operator_id: str,
        reason: str,
        recovery_evidence: ClaimRecoveryEvidence | None = None,
        live_claim_checker: Any = None,
    ) -> QueueEntry:
        """Recover an abandoned claim only with explicit guarded evidence; never release live claims."""
        if recovery_evidence is None or not recovery_evidence.verified_abandoned:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                "Abandoned-claim recovery requires explicit ClaimRecoveryEvidence(verified_abandoned=True).",
            )
        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            with self._open_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM queue_entries WHERE queue_entry_id = ?",
                    (queue_entry_id,),
                ).fetchone()
                if row is None:
                    raise ContinuityError(ErrorCode.SESSION_NOT_FOUND, f"Queue entry {queue_entry_id!r} was not found.")
                status = row["status"]
                if status not in {QueueEntryStatus.CLAIMED.value, QueueEntryStatus.LAUNCHING.value}:
                    raise ContinuityError(
                        ErrorCode.ASSOCIATION_CONFLICT,
                        f"Queue entry {queue_entry_id!r} is {status}; only claimed or launching entries can be recovered.",
                    )
                if (
                    recovery_evidence.expected_claimed_by is not None
                    and row["claimed_by"] != recovery_evidence.expected_claimed_by
                ):
                    raise ContinuityError(
                        ErrorCode.ASSOCIATION_CONFLICT,
                        f"Claimed operator mismatch on {queue_entry_id!r}: expected {recovery_evidence.expected_claimed_by!r}, got {row['claimed_by']!r}.",
                    )
                if (
                    recovery_evidence.expected_claim_token is not None
                    and row["claim_token"] != recovery_evidence.expected_claim_token
                ):
                    raise ContinuityError(
                        ErrorCode.ASSOCIATION_CONFLICT,
                        f"Claim token mismatch on {queue_entry_id!r}.",
                    )
                entry = self._row_to_entry(row)
                if live_claim_checker is not None and live_claim_checker(entry):
                    raise ContinuityError(
                        ErrorCode.ASSOCIATION_CONFLICT,
                        f"Cannot recover live operator claim on {queue_entry_id!r} (claimed_by={entry.claimed_by!r}).",
                    )
                if recovery_evidence.min_claim_age_seconds is not None and entry.claimed_at is not None:
                    from datetime import UTC, datetime

                    claimed_dt = datetime.fromisoformat(entry.claimed_at.replace("Z", "+00:00"))
                    age = (datetime.now(UTC) - claimed_dt).total_seconds()
                    if age < recovery_evidence.min_claim_age_seconds:
                        raise ContinuityError(
                            ErrorCode.ASSOCIATION_CONFLICT,
                            f"Claim on {queue_entry_id!r} is only {age:.2f}s old (< {recovery_evidence.min_claim_age_seconds:.2f}s).",
                        )
            now = now_utc_iso()
            target_status = (
                QueueEntryStatus.AMBIGUOUS.value
                if status == QueueEntryStatus.LAUNCHING.value
                else QueueEntryStatus.PENDING.value
            )
            self._commit_event_locked(
                "queue.abandoned_recovered",
                {
                    "queue_entry_id": queue_entry_id,
                    "operator_id": operator_id,
                    "target_status": target_status,
                    "updated_at": now,
                    "recovery_note": f"{operator_id}: {reason} ({recovery_evidence.reason})",
                },
            )
            return self._load_entry_locked(queue_entry_id)

    def complete(
        self,
        queue_entry_id: str,
        *,
        claim_token: str,
        launch_id: str | None = None,
        note: str | None = None,
        spawn_confirmed: bool = False,
    ) -> QueueEntry:
        """Mark a claimed/launching queue entry completed only with explicit positive spawn_confirmed=True."""
        if not spawn_confirmed:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                "Cannot mark queue entry completed without positive spawn_confirmed=True; use mark_ambiguous instead.",
            )
        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            self._require_claimed_row_locked(
                queue_entry_id,
                claim_token=claim_token,
                allowed_statuses={QueueEntryStatus.CLAIMED.value, QueueEntryStatus.LAUNCHING.value},
            )
            now = now_utc_iso()
            self._commit_event_locked(
                "queue.completed",
                {
                    "queue_entry_id": queue_entry_id,
                    "claim_token": claim_token,
                    "completed_at": now,
                    "launch_id": launch_id,
                    "spawn_confirmed": True,
                    "recovery_note": note,
                },
            )
            return self._load_entry_locked(queue_entry_id)

    def record_failure(
        self,
        queue_entry_id: str,
        *,
        claim_token: str,
        reason: str,
        partial: bool = False,
    ) -> QueueEntry:
        """Transition a claimed/launching entry to failed (unresolved) while preserving recovery context."""
        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            self._require_claimed_row_locked(
                queue_entry_id,
                claim_token=claim_token,
                allowed_statuses={QueueEntryStatus.CLAIMED.value, QueueEntryStatus.LAUNCHING.value},
            )
            now = now_utc_iso()
            self._commit_event_locked(
                "queue.failed",
                {
                    "queue_entry_id": queue_entry_id,
                    "claim_token": claim_token,
                    "updated_at": now,
                    "partial": partial,
                    "recovery_note": reason,
                },
            )
            return self._load_entry_locked(queue_entry_id)

    def release(
        self,
        queue_entry_id: str,
        *,
        claim_token: str,
        reason: str | None = None,
    ) -> QueueEntry:
        """Release a claimed (not yet launching) entry back to pending."""
        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            self._require_claimed_row_locked(
                queue_entry_id,
                claim_token=claim_token,
                allowed_statuses={QueueEntryStatus.CLAIMED.value},
            )
            now = now_utc_iso()
            self._commit_event_locked(
                "queue.released",
                {
                    "queue_entry_id": queue_entry_id,
                    "claim_token": claim_token,
                    "updated_at": now,
                    "recovery_note": reason,
                },
            )
            return self._load_entry_locked(queue_entry_id)

    def cancel(
        self,
        queue_entry_id: str,
        *,
        operator_id: str,
        reason: str,
        claim_token: str | None = None,
    ) -> QueueEntry:
        """Cancel a pending, failed, or matching-token claimed entry."""
        with _checkpoint_lock(self.lock_path):
            self._ensure_initialized_locked()
            with self._open_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM queue_entries WHERE queue_entry_id = ?",
                    (queue_entry_id,),
                ).fetchone()
                if row is None:
                    raise ContinuityError(ErrorCode.SESSION_NOT_FOUND, f"Queue entry {queue_entry_id!r} was not found.")
                status = row["status"]
                if status in {QueueEntryStatus.COMPLETED.value, QueueEntryStatus.CANCELLED.value}:
                    raise ContinuityError(
                        ErrorCode.ASSOCIATION_CONFLICT,
                        f"Queue entry {queue_entry_id!r} is already {status}.",
                    )
                if status in {QueueEntryStatus.CLAIMED.value, QueueEntryStatus.LAUNCHING.value} and (
                    row["claim_token"] != claim_token
                ):
                    raise ContinuityError(
                        ErrorCode.ASSOCIATION_CONFLICT,
                        f"Queue entry {queue_entry_id!r} is claimed by another operator.",
                    )
            now = now_utc_iso()
            self._commit_event_locked(
                "queue.cancelled",
                {
                    "queue_entry_id": queue_entry_id,
                    "operator_id": operator_id,
                    "updated_at": now,
                    "recovery_note": f"{operator_id}: {reason}",
                },
            )
            return self._load_entry_locked(queue_entry_id)

    def _read_entries_readonly(
        self,
        *,
        status: QueueEntryStatus | str | None = None,
        checkpoint_id: str | None = None,
        unresolved_only: bool = False,
    ) -> tuple[QueueEntry, ...]:
        """Pure read-only query using in-memory replay of valid log events (no disk mutations)."""
        if self.events_path.exists():
            events, _had_partial = self._read_valid_events()
            if not events:
                return ()
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            try:
                conn.executescript(_QUEUE_DDL)
                for ev in events:
                    self._apply_event(conn, ev["event_type"], ev["payload"])
                return self._query_entries_from_conn(
                    conn,
                    status=status,
                    checkpoint_id=checkpoint_id,
                    unresolved_only=unresolved_only,
                )
            finally:
                conn.close()
        if not self.db_path.exists():
            return ()
        conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return self._query_entries_from_conn(
                conn,
                status=status,
                checkpoint_id=checkpoint_id,
                unresolved_only=unresolved_only,
            )
        finally:
            conn.close()

    def _query_entries_from_conn(
        self,
        conn: sqlite3.Connection,
        *,
        status: QueueEntryStatus | str | None = None,
        checkpoint_id: str | None = None,
        unresolved_only: bool = False,
    ) -> tuple[QueueEntry, ...]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value if isinstance(status, QueueEntryStatus) else str(status))
        if checkpoint_id is not None:
            clauses.append("checkpoint_id = ?")
            params.append(checkpoint_id)
        if unresolved_only:
            placeholders = ", ".join("?" for _ in UNRESOLVED_QUEUE_STATUSES)
            clauses.append(f"status IN ({placeholders})")
            params.extend(sorted(UNRESOLVED_QUEUE_STATUSES))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM queue_entries {where} ORDER BY created_at, queue_entry_id"
        rows = conn.execute(query, tuple(params)).fetchall()
        return tuple(self._row_to_entry(row) for row in rows)

    def get_entry(self, queue_entry_id: str) -> QueueEntry:
        for entry in self._read_entries_readonly():
            if entry.queue_entry_id == queue_entry_id:
                return entry
        raise ContinuityError(ErrorCode.SESSION_NOT_FOUND, f"Queue entry {queue_entry_id!r} was not found.")

    def list_entries(
        self,
        *,
        status: QueueEntryStatus | str | None = None,
        checkpoint_id: str | None = None,
        unresolved_only: bool = False,
    ) -> tuple[QueueEntry, ...]:
        return self._read_entries_readonly(
            status=status,
            checkpoint_id=checkpoint_id,
            unresolved_only=unresolved_only,
        )

    def rebuild_index(self) -> int:
        """Rebuild the SQLite projection deterministically from the authoritative log under lock."""
        with _checkpoint_lock(self.lock_path):
            events, had_partial_tail = self._read_valid_events()
            if had_partial_tail:
                self._truncate_partial_tail_locked(events)
            staging = self.root_dir / f".restoration_queue.{os.getpid()}.staging.sqlite3"
            with contextlib.suppress(OSError):
                staging.unlink(missing_ok=True)
            replayed = 0
            with self._open_conn(staging) as conn:
                conn.executescript(_QUEUE_DDL)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for ev in events:
                        self._apply_event(conn, ev["event_type"], ev["payload"])
                        replayed += 1
                    conn.execute(
                        "INSERT OR REPLACE INTO queue_meta(key, value) VALUES ('applied_seq', ?)",
                        (str(replayed),),
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            os.replace(staging, self.db_path)
            for suffix in ("-wal", "-shm"):
                with contextlib.suppress(OSError):
                    Path(f"{self.db_path}{suffix}").unlink(missing_ok=True)
            return replayed

    def _require_claimed_row_locked(
        self,
        queue_entry_id: str,
        *,
        claim_token: str,
        allowed_statuses: set[str],
    ) -> sqlite3.Row:
        with self._open_conn() as conn:
            row = conn.execute(
                "SELECT * FROM queue_entries WHERE queue_entry_id = ?",
                (queue_entry_id,),
            ).fetchone()
        if row is None:
            raise ContinuityError(ErrorCode.SESSION_NOT_FOUND, f"Queue entry {queue_entry_id!r} was not found.")
        if row["status"] not in allowed_statuses or row["claim_token"] != claim_token:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Queue entry {queue_entry_id!r} cannot transition from {row['status']} with supplied claim token.",
                {"status": row["status"]},
            )
        return row

    def _load_entry_locked(self, queue_entry_id: str) -> QueueEntry:
        with self._open_conn() as conn:
            row = conn.execute(
                "SELECT * FROM queue_entries WHERE queue_entry_id = ?",
                (queue_entry_id,),
            ).fetchone()
        if row is None:
            raise ContinuityError(ErrorCode.SESSION_NOT_FOUND, f"Queue entry {queue_entry_id!r} was not found.")
        return self._row_to_entry(row)

    def _apply_event(self, conn: sqlite3.Connection, event_type: str, payload: Mapping[str, Any]) -> None:
        if event_type == "queue.enqueued":
            conn.execute(
                """INSERT OR IGNORE INTO queue_entries (
                    queue_entry_id, checkpoint_id, slot_id, gui_id, provider,
                    native_session_id, environment_id, runtime_kind, status,
                    created_at, updated_at, attempts, launch_submission_state, spawn_confirmed,
                    partial, gui_alias, slot_name,
                    worktree_json, launch_settings_json, requested_topology_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["queue_entry_id"],
                    payload["checkpoint_id"],
                    payload["slot_id"],
                    payload["gui_id"],
                    payload["provider"],
                    payload["native_session_id"],
                    payload["environment_id"],
                    payload["runtime_kind"],
                    payload["status"],
                    payload["created_at"],
                    payload["updated_at"],
                    int(payload.get("attempts", 0)),
                    payload.get("launch_submission_state", "not_started"),
                    1 if payload.get("spawn_confirmed") else 0,
                    1 if payload.get("partial") else 0,
                    payload.get("gui_alias"),
                    payload.get("slot_name"),
                    json.dumps(payload.get("worktree") or {}, sort_keys=True),
                    json.dumps(payload.get("launch_settings") or {}, sort_keys=True),
                    (
                        json.dumps(payload["requested_topology"], sort_keys=True)
                        if payload.get("requested_topology")
                        else None
                    ),
                    json.dumps(payload.get("metadata") or {}, sort_keys=True),
                ),
            )
        elif event_type == "queue.claimed":
            conn.execute(
                """UPDATE queue_entries
                   SET status = ?, claimed_by = ?, claim_token = ?, claimed_at = ?,
                       updated_at = ?, attempts = ?, launch_submission_state = 'not_started'
                   WHERE queue_entry_id = ?""",
                (
                    QueueEntryStatus.CLAIMED.value,
                    payload["claimed_by"],
                    payload["claim_token"],
                    payload["claimed_at"],
                    payload["claimed_at"],
                    int(payload["attempts"]),
                    payload["queue_entry_id"],
                ),
            )
        elif event_type == "queue.launching":
            conn.execute(
                """UPDATE queue_entries
                   SET status = ?, updated_at = ?, launch_submission_state = ?
                   WHERE queue_entry_id = ?""",
                (
                    QueueEntryStatus.LAUNCHING.value,
                    payload["updated_at"],
                    payload.get("launch_submission_state", "submitting"),
                    payload["queue_entry_id"],
                ),
            )
        elif event_type == "queue.ambiguous":
            conn.execute(
                """UPDATE queue_entries
                   SET status = ?, updated_at = ?, launch_id = COALESCE(?, launch_id),
                       launch_submission_state = ?, spawn_confirmed = 0,
                       partial = 1, recovery_note = ?,
                       claimed_by = NULL, claim_token = NULL, claimed_at = NULL
                   WHERE queue_entry_id = ?""",
                (
                    QueueEntryStatus.AMBIGUOUS.value,
                    payload["updated_at"],
                    payload.get("launch_id"),
                    payload.get("launch_submission_state", "ambiguous"),
                    payload.get("recovery_note"),
                    payload["queue_entry_id"],
                ),
            )
        elif event_type == "queue.ambiguous_resolved":
            outcome = payload["outcome"]
            status_val = {
                "completed": QueueEntryStatus.COMPLETED.value,
                "failed": QueueEntryStatus.FAILED.value,
                "cancelled": QueueEntryStatus.CANCELLED.value,
            }[outcome]
            completed_at = payload["updated_at"] if outcome == "completed" else None
            conn.execute(
                """UPDATE queue_entries
                   SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at),
                       launch_id = COALESCE(?, launch_id),
                       spawn_confirmed = CASE WHEN ? = 'completed' THEN 1 ELSE 0 END,
                       partial = CASE WHEN ? = 'completed' THEN 0 ELSE partial END,
                       recovery_note = ?
                   WHERE queue_entry_id = ?""",
                (
                    status_val,
                    payload["updated_at"],
                    completed_at,
                    payload.get("launch_id"),
                    outcome,
                    outcome,
                    payload.get("recovery_note"),
                    payload["queue_entry_id"],
                ),
            )
        elif event_type == "queue.abandoned_recovered":
            conn.execute(
                """UPDATE queue_entries
                   SET status = ?, updated_at = ?, recovery_note = ?,
                       launch_submission_state = CASE WHEN ? = 'ambiguous' THEN 'ambiguous' ELSE 'not_started' END,
                       claimed_by = NULL, claim_token = NULL, claimed_at = NULL
                   WHERE queue_entry_id = ?""",
                (
                    payload["target_status"],
                    payload["updated_at"],
                    payload.get("recovery_note"),
                    payload["target_status"],
                    payload["queue_entry_id"],
                ),
            )
        elif event_type == "queue.completed":
            conn.execute(
                """UPDATE queue_entries
                   SET status = ?, completed_at = ?, updated_at = ?,
                       launch_id = COALESCE(?, launch_id),
                       launch_submission_state = 'accepted',
                       spawn_confirmed = ?,
                       partial = 0,
                       recovery_note = COALESCE(?, recovery_note)
                   WHERE queue_entry_id = ?""",
                (
                    QueueEntryStatus.COMPLETED.value,
                    payload["completed_at"],
                    payload["completed_at"],
                    payload.get("launch_id"),
                    1 if payload.get("spawn_confirmed", True) else 0,
                    payload.get("recovery_note"),
                    payload["queue_entry_id"],
                ),
            )
        elif event_type == "queue.failed":
            conn.execute(
                """UPDATE queue_entries
                   SET status = ?, updated_at = ?, partial = ?, recovery_note = ?,
                       launch_submission_state = 'rejected',
                       claimed_by = NULL, claim_token = NULL, claimed_at = NULL
                   WHERE queue_entry_id = ?""",
                (
                    QueueEntryStatus.FAILED.value,
                    payload["updated_at"],
                    1 if payload.get("partial") else 0,
                    payload.get("recovery_note"),
                    payload["queue_entry_id"],
                ),
            )
        elif event_type == "queue.released":
            conn.execute(
                """UPDATE queue_entries
                   SET status = ?, updated_at = ?, recovery_note = COALESCE(?, recovery_note),
                       launch_submission_state = 'not_started',
                       claimed_by = NULL, claim_token = NULL, claimed_at = NULL
                   WHERE queue_entry_id = ?""",
                (
                    QueueEntryStatus.PENDING.value,
                    payload["updated_at"],
                    payload.get("recovery_note"),
                    payload["queue_entry_id"],
                ),
            )
        elif event_type == "queue.cancelled":
            conn.execute(
                """UPDATE queue_entries
                   SET status = ?, updated_at = ?, recovery_note = ?,
                       claimed_by = NULL, claim_token = NULL, claimed_at = NULL
                   WHERE queue_entry_id = ?""",
                (
                    QueueEntryStatus.CANCELLED.value,
                    payload["updated_at"],
                    payload.get("recovery_note"),
                    payload["queue_entry_id"],
                ),
            )

    def _row_to_entry(self, row: sqlite3.Row) -> QueueEntry:
        worktree_raw = json.loads(row["worktree_json"]) if row["worktree_json"] else None
        settings_raw = json.loads(row["launch_settings_json"]) if row["launch_settings_json"] else {}
        topology_raw = json.loads(row["requested_topology_json"]) if row["requested_topology_json"] else None
        metadata_raw = json.loads(row["metadata_json"]) if row["metadata_json"] else None
        return QueueEntry(
            queue_entry_id=str(row["queue_entry_id"]),
            checkpoint_id=str(row["checkpoint_id"]),
            slot_id=str(row["slot_id"]),
            gui_id=str(row["gui_id"]),
            provider=str(row["provider"]),
            native_session_id=str(row["native_session_id"]),
            environment_id=str(row["environment_id"]),
            runtime_kind=str(row["runtime_kind"]),
            status=QueueEntryStatus(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            attempts=int(row["attempts"]),
            claimed_by=str(row["claimed_by"]) if row["claimed_by"] is not None else None,
            claim_token=str(row["claim_token"]) if row["claim_token"] is not None else None,
            claimed_at=str(row["claimed_at"]) if row["claimed_at"] is not None else None,
            completed_at=str(row["completed_at"]) if row["completed_at"] is not None else None,
            launch_id=str(row["launch_id"]) if row["launch_id"] is not None else None,
            launch_submission_state=str(row["launch_submission_state"]),
            spawn_confirmed=bool(row["spawn_confirmed"]),
            partial=bool(row["partial"]),
            recovery_note=str(row["recovery_note"]) if row["recovery_note"] is not None else None,
            gui_alias=str(row["gui_alias"]) if row["gui_alias"] is not None else None,
            slot_name=str(row["slot_name"]) if row["slot_name"] is not None else None,
            worktree=WorkspaceWorktreeEvidence.from_dict(worktree_raw) if worktree_raw else None,
            launch_settings=dict(settings_raw),
            requested_topology=WorkspaceTopologyRequest.from_dict(topology_raw),
            metadata=WorkspaceSlotMetadata.from_dict(metadata_raw) if metadata_raw else None,
        )
