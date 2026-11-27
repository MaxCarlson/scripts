"""Transactional, argument-free records for managed terminal children."""

from __future__ import annotations

import hashlib
import os
import signal
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class LaunchSubmissionState(str, Enum):
    RESERVED = "reserved"
    SUBMITTING = "submitting"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"


class ManagedProcessState(str, Enum):
    UNKNOWN = "unknown"
    RESERVED = "reserved"
    CLAIMED = "claimed"
    STARTED = "started"
    RUNNING = "running"
    EXITED = "exited"
    FAILED = "failed"
    STALE = "stale"


class ProcessLiveness(str, Enum):
    ALIVE = "alive"
    EXITED = "exited"
    UNKNOWN = "unknown"


class InterruptionState(str, Enum):
    NONE = "none"
    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ManagedPaneReservation:
    pane_id: str
    tab_index: int
    pane_index: int
    requested_layout: str


@dataclass(frozen=True, slots=True)
class ManagedProcessRecord:
    launch_id: str
    pane_id: str
    window_id_hash: str
    state: ManagedProcessState
    requested_tab_index: int
    requested_pane_index: int
    requested_layout: str
    submitted_at: float
    pid: int | None = None
    process_created: int | None = None
    relay_pid: int | None = None
    relay_process_created: int | None = None
    spawn_acknowledged: bool = False
    started_at: float | None = None
    exited_at: float | None = None
    exit_code: int | None = None
    failure_code: str | None = None
    readiness: str = "unknown"
    shutdown_requested: bool = False
    shutdown_delivered: bool = False
    submission_state: LaunchSubmissionState = LaunchSubmissionState.AMBIGUOUS
    liveness: ProcessLiveness = ProcessLiveness.UNKNOWN
    owner_liveness: ProcessLiveness = ProcessLiveness.UNKNOWN
    interruption_state: InterruptionState = InterruptionState.NONE


@dataclass(frozen=True, slots=True)
class ShutdownRequestResult:
    accepted: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ShutdownRequest:
    pane_id: str
    pid: int | None = None
    process_created: int | None = None


ProcessIdentity = Callable[[int], tuple[int, int] | None]
ProcessLivenessLookup = Callable[[int], ProcessLiveness]
SignalProcessGroup = Callable[[int], bool]


def process_identity(pid: int) -> tuple[int, int] | None:
    """Return PID plus Windows creation FILETIME; liveness is checked separately."""
    if not sys.platform.startswith("win"):
        return None

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    get_times = kernel32.GetProcessTimes
    get_times.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    get_times.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    try:
        if not get_times(handle, created, exited, kernel, user):
            return None
        creation_value = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return pid, creation_value
    finally:
        close_handle(handle)


def process_liveness(pid: int) -> ProcessLiveness:
    """Check whether the PID's process handle is signaled, independently of identity."""
    if not sys.platform.startswith("win"):
        return ProcessLiveness.UNKNOWN

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    wait = kernel32.WaitForSingleObject
    wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = open_process(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return ProcessLiveness.UNKNOWN
    try:
        result = wait(handle, 0)
        if result == 0:
            return ProcessLiveness.EXITED
        if result == 0x102:
            return ProcessLiveness.ALIVE
        return ProcessLiveness.UNKNOWN
    finally:
        close_handle(handle)


def _default_database_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "terminal-launcher" / "managed-processes.sqlite3"


class ManagedProcessStore:
    """Durable launch reservations and receipts without argv, cwd, or titles."""

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        process_identity_lookup: ProcessIdentity | None = None,
        process_liveness_lookup: ProcessLivenessLookup | None = None,
    ) -> None:
        selected_path = Path(path).expanduser() if path is not None else _default_database_path()
        self.path = selected_path.resolve()
        self._identity = process_identity_lookup or process_identity
        self._liveness = process_liveness_lookup or process_liveness
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS managed_launches (
                    launch_id TEXT PRIMARY KEY,
                    window_id_hash TEXT NOT NULL,
                    submission_state TEXT NOT NULL,
                    submitted_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    failure_code TEXT
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS managed_panes (
                    launch_id TEXT NOT NULL,
                    pane_id TEXT PRIMARY KEY,
                    window_id_hash TEXT NOT NULL,
                    requested_tab_index INTEGER NOT NULL,
                    requested_pane_index INTEGER NOT NULL,
                    requested_layout TEXT NOT NULL,
                    submitted_at REAL NOT NULL,
                    state TEXT NOT NULL,
                    pid INTEGER,
                    process_created INTEGER,
                    relay_pid INTEGER,
                    relay_process_created INTEGER,
                    claim_token TEXT,
                    started_at REAL,
                    exited_at REAL,
                    exit_code INTEGER,
                    failure_code TEXT,
                    shutdown_requested INTEGER NOT NULL DEFAULT 0,
                    shutdown_delivered INTEGER NOT NULL DEFAULT 0,
                    interruption_state TEXT NOT NULL DEFAULT 'none'
                )"""
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(managed_panes)")}
            additions = {
                "claim_token": "TEXT",
                "interruption_state": "TEXT NOT NULL DEFAULT 'none'",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE managed_panes ADD COLUMN {name} {definition}")

            # Old receipts cannot prove whether a previously unknown relay had spawned.
            # Keep them queryable and permanently non-claimable after migration.
            connection.execute(
                """INSERT OR IGNORE INTO managed_launches
                   (launch_id, window_id_hash, submission_state, submitted_at, updated_at)
                   SELECT launch_id, MIN(window_id_hash), 'ambiguous', MIN(submitted_at), ?
                   FROM managed_panes GROUP BY launch_id""",
                (time.time(),),
            )
            connection.execute(
                """UPDATE managed_panes SET interruption_state = CASE
                       WHEN shutdown_delivered = 1 THEN 'delivered'
                       WHEN shutdown_requested = 1 THEN 'unknown'
                       ELSE 'none' END
                   WHERE interruption_state = 'none' AND (shutdown_requested = 1 OR shutdown_delivered = 1)"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS managed_panes_launch ON managed_panes(launch_id)")

    @staticmethod
    def _require_id(value: str, name: str) -> str:
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError(f"{name} must be a non-empty string without NUL")
        if len(value) > 256:
            raise ValueError(f"{name} must be at most 256 characters")
        return value

    @staticmethod
    def _validate_reservations(panes: Sequence[ManagedPaneReservation]) -> None:
        if not panes:
            raise ValueError("a managed launch must reserve at least one pane")
        pane_ids = set()
        for pane in panes:
            if not isinstance(pane, ManagedPaneReservation):
                raise ValueError("panes must contain ManagedPaneReservation values")
            if pane.pane_id in pane_ids:
                raise ValueError(f"duplicate pane identity in launch: {pane.pane_id}")
            pane_ids.add(pane.pane_id)
            if pane.tab_index < 0 or pane.pane_index < 0:
                raise ValueError("tab and pane indexes must be non-negative")
            if not pane.requested_layout:
                raise ValueError("requested_layout must be a non-empty string")

    def reserve_launch(
        self,
        launch_id: str,
        window_id: str,
        panes: Sequence[ManagedPaneReservation],
    ) -> None:
        """Atomically reserve the complete launch and every pane before submission."""
        launch_id = self._require_id(launch_id, "launch_id")
        if not isinstance(window_id, str) or not window_id:
            raise ValueError("window_id must be a non-empty string")
        reservations = tuple(panes)
        self._validate_reservations(reservations)
        window_hash = hashlib.sha256(window_id.encode("utf-8")).hexdigest()
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO managed_launches
                   (launch_id, window_id_hash, submission_state, submitted_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (launch_id, window_hash, LaunchSubmissionState.RESERVED.value, now, now),
            )
            connection.executemany(
                """INSERT INTO managed_panes (
                    launch_id, pane_id, window_id_hash, requested_tab_index, requested_pane_index,
                    requested_layout, submitted_at, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        launch_id,
                        self._require_id(pane.pane_id, "pane_id"),
                        window_hash,
                        pane.tab_index,
                        pane.pane_index,
                        pane.requested_layout,
                        now,
                        ManagedProcessState.RESERVED.value,
                    )
                    for pane in reservations
                ],
            )

    def register_submission(
        self,
        *,
        launch_id: str,
        pane_id: str,
        window_id: str,
        tab_index: int,
        pane_index: int,
        requested_layout: str,
    ) -> None:
        """Deprecated one-pane compatibility API; new code reserves full launches."""
        launch_id = self._require_id(launch_id, "launch_id")
        pane_id = self._require_id(pane_id, "pane_id")
        if not isinstance(window_id, str) or not window_id:
            raise ValueError("window_id must be a non-empty string")
        if tab_index < 0 or pane_index < 0:
            raise ValueError("tab and pane indexes must be non-negative")
        if not isinstance(requested_layout, str) or not requested_layout:
            raise ValueError("requested_layout must be a non-empty string")
        window_hash = hashlib.sha256(window_id.encode("utf-8")).hexdigest()
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO managed_launches
                   (launch_id, window_id_hash, submission_state, submitted_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (launch_id, window_hash, LaunchSubmissionState.ACCEPTED.value, now, now),
            )
            connection.execute(
                """INSERT INTO managed_panes (
                    launch_id, pane_id, window_id_hash, requested_tab_index, requested_pane_index,
                    requested_layout, submitted_at, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (launch_id, pane_id, window_hash, tab_index, pane_index, requested_layout, now,
                 ManagedProcessState.RESERVED.value),
            )

    def get_submission_state(self, launch_id: str) -> LaunchSubmissionState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT submission_state FROM managed_launches WHERE launch_id = ?", (launch_id,)
            ).fetchone()
        return LaunchSubmissionState(row[0]) if row else None

    def mark_submission_started(self, launch_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE managed_launches SET submission_state = ?, updated_at = ?
                   WHERE launch_id = ? AND submission_state = ?""",
                (
                    LaunchSubmissionState.SUBMITTING.value,
                    time.time(),
                    launch_id,
                    LaunchSubmissionState.RESERVED.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"managed launch has no unsubmitted reservation: {launch_id}")

    def mark_submission_outcome(
        self,
        launch_id: str,
        outcome: LaunchSubmissionState,
        *,
        failure_code: str | None = None,
    ) -> None:
        if outcome not in {
            LaunchSubmissionState.ACCEPTED,
            LaunchSubmissionState.REJECTED,
            LaunchSubmissionState.AMBIGUOUS,
        }:
            raise ValueError("submission outcome must be accepted, rejected, or ambiguous")
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE managed_launches SET submission_state = ?, updated_at = ?, failure_code = ?
                   WHERE launch_id = ? AND submission_state = ?""",
                (outcome.value, time.time(), failure_code, launch_id, LaunchSubmissionState.SUBMITTING.value),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"managed launch is not submitting: {launch_id}")
            if outcome is LaunchSubmissionState.REJECTED:
                connection.execute(
                    """UPDATE managed_panes SET state = ?, failure_code = ?
                       WHERE launch_id = ? AND state = ?""",
                    (
                        ManagedProcessState.FAILED.value,
                        failure_code or "terminal_rejected",
                        launch_id,
                        ManagedProcessState.RESERVED.value,
                    ),
                )

    def claim_pane(
        self,
        launch_id: str,
        pane_id: str,
        *,
        relay_pid: int,
        relay_process_created: int,
    ) -> str | None:
        """CAS a reserved pane to one relay before any child process can be spawned."""
        token = uuid.uuid4().hex
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE managed_panes SET state = ?, claim_token = ?, relay_pid = ?,
                       relay_process_created = ?
                   WHERE launch_id = ? AND pane_id = ? AND state = ?
                     AND EXISTS (SELECT 1 FROM managed_launches l WHERE l.launch_id = ?
                       AND l.submission_state IN (?, ?, ?))""",
                (
                    ManagedProcessState.CLAIMED.value,
                    token,
                    relay_pid,
                    relay_process_created,
                    launch_id,
                    pane_id,
                    ManagedProcessState.RESERVED.value,
                    launch_id,
                    LaunchSubmissionState.SUBMITTING.value,
                    LaunchSubmissionState.ACCEPTED.value,
                    LaunchSubmissionState.AMBIGUOUS.value,
                ),
            )
        return token if cursor.rowcount == 1 else None

    def record_started(
        self,
        launch_id: str | None = None,
        pane_id: str | None = None,
        *,
        claim_token: str | None = None,
        pid: int,
        process_created: int | None,
        relay_pid: int | None = None,
        relay_process_created: int | None = None,
    ) -> None:
        # Compatibility with the former record_started(pane_id, ...) API. The
        # compatibility path still binds its receipt to a pre-spawn claim.
        legacy_call = launch_id is None or pane_id is None
        if pane_id is None:
            pane_id = launch_id
        if pane_id is None:
            raise ValueError("pane_id is required")
        if launch_id is None or legacy_call:
            with self._connect() as connection:
                row = self._load_pane(connection, pane_id)
            if row is None:
                raise ValueError(f"managed pane is not registered: {pane_id}")
            launch_id = row["launch_id"]
            if claim_token is None:
                relay_pid = os.getpid() if relay_pid is None else relay_pid
                relay_identity = self._lookup_identity(relay_pid)
                if relay_process_created is None:
                    if relay_identity is None or relay_identity[0] != relay_pid:
                        raise ValueError("cannot prove the owning relay identity")
                    relay_process_created = relay_identity[1]
                claim_token = self.claim_pane(
                    launch_id,
                    pane_id,
                    relay_pid=relay_pid,
                    relay_process_created=relay_process_created,
                )
                if claim_token is None:
                    raise ValueError(f"managed pane cannot be claimed: {pane_id}")
        if claim_token is None or relay_pid is None or relay_process_created is None:
            raise ValueError("start receipts require a pane claim and owning relay identity")
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE managed_panes SET state = ?, pid = ?, process_created = ?, started_at = ?
                   WHERE launch_id = ? AND pane_id = ? AND state = ? AND claim_token = ?
                     AND relay_pid = ? AND relay_process_created = ?""",
                (
                    ManagedProcessState.STARTED.value,
                    pid,
                    process_created,
                    time.time(),
                    launch_id,
                    pane_id,
                    ManagedProcessState.CLAIMED.value,
                    claim_token,
                    relay_pid,
                    relay_process_created,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"managed pane claim is stale or does not belong to this relay: {pane_id}")

    def record_spawn_failure(self, launch_id: str, pane_id: str, *, claim_token: str, failure_code: str) -> None:
        self._validate_failure_code(failure_code)
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE managed_panes SET state = ?, failure_code = ?
                   WHERE launch_id = ? AND pane_id = ? AND state = ? AND claim_token = ?""",
                (
                    ManagedProcessState.FAILED.value,
                    failure_code,
                    launch_id,
                    pane_id,
                    ManagedProcessState.CLAIMED.value,
                    claim_token,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"managed pane has no matching pre-spawn claim: {pane_id}")

    @staticmethod
    def _validate_failure_code(failure_code: str) -> None:
        if not failure_code or len(failure_code) > 80 or not failure_code.replace("_", "").isalnum():
            raise ValueError("failure_code must be a short identifier")

    def record_exit(
        self,
        launch_id: str | None = None,
        pane_id: str | None = None,
        *,
        claim_token: str | None = None,
        exit_code: int,
    ) -> None:
        if pane_id is None:
            pane_id = launch_id
        if pane_id is None:
            raise ValueError("pane_id is required")
        if launch_id is None or launch_id == pane_id:
            with self._connect() as connection:
                row = self._load_pane(connection, pane_id)
            if row is None:
                raise ValueError(f"managed pane is not registered: {pane_id}")
            launch_id = row["launch_id"]
            if claim_token is None:
                claim_token = row["claim_token"]
        if claim_token is None:
            raise ValueError("exit receipts require the pane claim token")
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE managed_panes SET state = ?, exited_at = ?, exit_code = ?,
                       interruption_state = CASE WHEN interruption_state = ? THEN ? ELSE interruption_state END
                   WHERE launch_id = ? AND pane_id = ? AND state = ? AND claim_token = ?""",
                (
                    ManagedProcessState.EXITED.value,
                    time.time(),
                    exit_code,
                    InterruptionState.PENDING.value,
                    InterruptionState.CANCELLED.value,
                    launch_id,
                    pane_id,
                    ManagedProcessState.STARTED.value,
                    claim_token,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"managed pane has no matching start receipt: {pane_id}")

    def record_failure(self, pane_id: str, *, failure_code: str) -> None:
        """Deprecated compatibility API for pre-spawn failures."""
        self._validate_failure_code(failure_code)
        with self._connect() as connection:
            row = self._load_pane(connection, pane_id)
            if row is None:
                raise ValueError(f"managed pane is not registered: {pane_id}")
            if row["state"] == ManagedProcessState.CLAIMED.value:
                claim_token = row["claim_token"]
                if claim_token is None:
                    raise ValueError(f"managed pane has no pre-spawn claim: {pane_id}")
                cursor = connection.execute(
                    """UPDATE managed_panes SET state = ?, failure_code = ?
                       WHERE pane_id = ? AND state = ? AND claim_token = ?""",
                    (ManagedProcessState.FAILED.value, failure_code, pane_id,
                     ManagedProcessState.CLAIMED.value, claim_token),
                )
            elif row["state"] == ManagedProcessState.RESERVED.value:
                cursor = connection.execute(
                    """UPDATE managed_panes SET state = ?, failure_code = ?
                       WHERE pane_id = ? AND state = ?""",
                    (ManagedProcessState.FAILED.value, failure_code, pane_id, ManagedProcessState.RESERVED.value),
                )
            else:
                raise ValueError(f"managed pane cannot be failed from state {row['state']}: {pane_id}")
            if cursor.rowcount != 1:
                raise ValueError(f"managed pane failure raced with another receipt: {pane_id}")

    def _lookup_identity(self, pid: int) -> tuple[int, int] | None:
        return self._identity(pid)

    def _lookup_liveness(self, pid: int) -> ProcessLiveness:
        return self._liveness(pid)

    def _load_pane(self, connection: sqlite3.Connection, pane_id: str) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM managed_panes WHERE pane_id = ?", (pane_id,)).fetchone()

    def request_interrupt(self, pane_id: str) -> ShutdownRequestResult:
        """Queue a Ctrl+Break interruption request for one exact live owned child."""
        with self._connect() as connection:
            row = self._load_pane(connection, pane_id)
            if row is None:
                return ShutdownRequestResult(False, "unknown_pane")
            if row["state"] != ManagedProcessState.STARTED.value or row["pid"] is None:
                return ShutdownRequestResult(False, "process_not_running")
            if row["process_created"] is None:
                return ShutdownRequestResult(False, "process_identity_unavailable")
            if self._lookup_identity(row["pid"]) != (row["pid"], row["process_created"]):
                return ShutdownRequestResult(False, "stale_process_identity")
            child_liveness = self._lookup_liveness(row["pid"])
            if child_liveness is ProcessLiveness.EXITED:
                return ShutdownRequestResult(False, "process_not_live")
            if child_liveness is ProcessLiveness.UNKNOWN:
                return ShutdownRequestResult(False, "process_liveness_unknown")
            if row["relay_pid"] is None or row["relay_process_created"] is None:
                return ShutdownRequestResult(False, "owning_relay_unavailable")
            if self._lookup_identity(row["relay_pid"]) != (row["relay_pid"], row["relay_process_created"]):
                return ShutdownRequestResult(False, "stale_relay_identity")
            relay_liveness = self._lookup_liveness(row["relay_pid"])
            if relay_liveness is ProcessLiveness.EXITED:
                return ShutdownRequestResult(False, "owning_relay_not_live")
            if relay_liveness is ProcessLiveness.UNKNOWN:
                return ShutdownRequestResult(False, "owning_relay_liveness_unknown")
            state = InterruptionState(row["interruption_state"])
            if state is InterruptionState.NONE:
                cursor = connection.execute(
                    """UPDATE managed_panes SET interruption_state = ?, shutdown_requested = 1
                       WHERE pane_id = ? AND state = ? AND interruption_state = ?""",
                    (
                        InterruptionState.PENDING.value,
                        pane_id,
                        ManagedProcessState.STARTED.value,
                        InterruptionState.NONE.value,
                    ),
                )
                if cursor.rowcount != 1:
                    return ShutdownRequestResult(False, "state_changed")
                return ShutdownRequestResult(True, "interruption_queued")
            if state is InterruptionState.PENDING:
                return ShutdownRequestResult(True, "already_queued")
            return ShutdownRequestResult(False, f"interruption_{state.value}")

    def request_graceful_shutdown(self, pane_id: str) -> ShutdownRequestResult:
        """Deprecated compatibility alias; queues interruption only, not shutdown."""
        return self.request_interrupt(pane_id)

    def get_interruption_state(self, pane_id: str) -> InterruptionState:
        """Query only this relay's pane; relays never scan the global table."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT interruption_state FROM managed_panes WHERE pane_id = ?", (pane_id,)
            ).fetchone()
        return InterruptionState(row[0]) if row else InterruptionState.NONE

    def pending_shutdown_requests(self) -> tuple[ShutdownRequest, ...]:
        """Deprecated compatibility query; managed relays query only their pane."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT pane_id, pid, process_created FROM managed_panes
                   WHERE interruption_state = ? ORDER BY pane_id""",
                (InterruptionState.PENDING.value,),
            ).fetchall()
        return tuple(ShutdownRequest(row["pane_id"], row["pid"], row["process_created"]) for row in rows)

    def deliver_shutdown_request(
        self,
        pane_id: str,
        *,
        signal_process_group: SignalProcessGroup,
    ) -> bool:
        """Deprecated wrapper retaining owning-relay and at-most-once checks."""
        with self._connect() as connection:
            row = self._load_pane(connection, pane_id)
        if row is None or row["relay_pid"] is None or row["relay_process_created"] is None:
            return False
        return self.deliver_interruption(
            pane_id,
            relay_pid=row["relay_pid"],
            relay_process_created=row["relay_process_created"],
            signal_process_group=signal_process_group,
        )

    def deliver_interruption(
        self,
        pane_id: str,
        *,
        relay_pid: int,
        relay_process_created: int,
        signal_process_group: SignalProcessGroup,
    ) -> bool:
        """Atomically claim one Ctrl+Break attempt before calling the OS signal API.

        If the relay is interrupted after the claim, state remains ``delivering``;
        subsequent calls never send a second control event.
        """
        with self._connect() as connection:
            row = self._load_pane(connection, pane_id)
            if row is None or row["state"] != ManagedProcessState.STARTED.value:
                return False
            if row["interruption_state"] != InterruptionState.PENDING.value:
                return False
            if (row["relay_pid"], row["relay_process_created"]) != (relay_pid, relay_process_created):
                return False
            if self._lookup_identity(relay_pid) != (relay_pid, relay_process_created):
                return False
            relay_liveness = self._lookup_liveness(relay_pid)
            if relay_liveness is not ProcessLiveness.ALIVE:
                return False
            if row["pid"] is None or row["process_created"] is None:
                return False
            if self._lookup_identity(row["pid"]) != (row["pid"], row["process_created"]):
                connection.execute(
                    "UPDATE managed_panes SET interruption_state = ? WHERE pane_id = ? AND interruption_state = ?",
                    (InterruptionState.UNKNOWN.value, pane_id, InterruptionState.PENDING.value),
                )
                return False
            child_liveness = self._lookup_liveness(row["pid"])
            if child_liveness is ProcessLiveness.UNKNOWN:
                connection.execute(
                    "UPDATE managed_panes SET interruption_state = ? WHERE pane_id = ? AND interruption_state = ?",
                    (InterruptionState.UNKNOWN.value, pane_id, InterruptionState.PENDING.value),
                )
                return False
            if child_liveness is ProcessLiveness.EXITED:
                connection.execute(
                    "UPDATE managed_panes SET interruption_state = ? WHERE pane_id = ? AND interruption_state = ?",
                    (InterruptionState.CANCELLED.value, pane_id, InterruptionState.PENDING.value),
                )
                return False
            cursor = connection.execute(
                """UPDATE managed_panes SET interruption_state = ?
                   WHERE pane_id = ? AND state = ? AND interruption_state = ?
                     AND relay_pid = ? AND relay_process_created = ?""",
                (
                    InterruptionState.DELIVERING.value,
                    pane_id,
                    ManagedProcessState.STARTED.value,
                    InterruptionState.PENDING.value,
                    relay_pid,
                    relay_process_created,
                ),
            )
            if cursor.rowcount != 1:
                return False
            child_pid = row["pid"]

        try:
            sent = signal_process_group(child_pid)
        except Exception:
            self.finish_interruption_delivery(
                pane_id,
                relay_pid=relay_pid,
                relay_process_created=relay_process_created,
                outcome=InterruptionState.UNKNOWN,
            )
            return False
        outcome = InterruptionState.DELIVERED if sent else InterruptionState.UNKNOWN
        self.finish_interruption_delivery(
            pane_id,
            relay_pid=relay_pid,
            relay_process_created=relay_process_created,
            outcome=outcome,
        )
        return sent

    def finish_interruption_delivery(
        self,
        pane_id: str,
        *,
        relay_pid: int,
        relay_process_created: int,
        outcome: InterruptionState,
    ) -> None:
        if outcome not in {InterruptionState.DELIVERED, InterruptionState.UNKNOWN}:
            raise ValueError("delivery outcome must be delivered or unknown")
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE managed_panes SET interruption_state = ?,
                       shutdown_delivered = CASE WHEN ? = ? THEN 1 ELSE shutdown_delivered END
                   WHERE pane_id = ? AND state = ? AND interruption_state = ?
                     AND relay_pid = ? AND relay_process_created = ?""",
                (
                    outcome.value,
                    outcome.value,
                    InterruptionState.DELIVERED.value,
                    pane_id,
                    ManagedProcessState.STARTED.value,
                    InterruptionState.DELIVERING.value,
                    relay_pid,
                    relay_process_created,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"interruption delivery is no longer owned by this relay: {pane_id}")

    @staticmethod
    def _record(
        row: sqlite3.Row,
        state: ManagedProcessState,
        submission_state: LaunchSubmissionState,
        *,
        liveness: ProcessLiveness = ProcessLiveness.UNKNOWN,
        owner_liveness: ProcessLiveness = ProcessLiveness.UNKNOWN,
    ) -> ManagedProcessRecord:
        return ManagedProcessRecord(
            launch_id=row["launch_id"],
            pane_id=row["pane_id"],
            window_id_hash=row["window_id_hash"],
            state=state,
            requested_tab_index=row["requested_tab_index"],
            requested_pane_index=row["requested_pane_index"],
            requested_layout=row["requested_layout"],
            submitted_at=row["submitted_at"],
            pid=row["pid"],
            process_created=row["process_created"],
            relay_pid=row["relay_pid"],
            relay_process_created=row["relay_process_created"],
            spawn_acknowledged=row["pid"] is not None,
            started_at=row["started_at"],
            exited_at=row["exited_at"],
            exit_code=row["exit_code"],
            failure_code=row["failure_code"],
            readiness="unknown",
            shutdown_requested=bool(row["shutdown_requested"])
            or InterruptionState(row["interruption_state"]) is not InterruptionState.NONE,
            shutdown_delivered=bool(row["shutdown_delivered"])
            or InterruptionState(row["interruption_state"]) is InterruptionState.DELIVERED,
            submission_state=submission_state,
            liveness=liveness,
            owner_liveness=owner_liveness,
            interruption_state=InterruptionState(row["interruption_state"]),
        )

    def enumerate_processes(self, *, launch_id: str | None = None) -> tuple[ManagedProcessRecord, ...]:
        query = """SELECT p.*, COALESCE(l.submission_state, 'ambiguous') AS submission_state
                   FROM managed_panes p LEFT JOIN managed_launches l ON l.launch_id = p.launch_id"""
        values: tuple[str, ...] = ()
        if launch_id is not None:
            query += " WHERE p.launch_id = ?"
            values = (launch_id,)
        query += " ORDER BY p.submitted_at, p.pane_id"
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()

        records = []
        for row in rows:
            state = ManagedProcessState(row["state"])
            liveness = ProcessLiveness.UNKNOWN
            owner_liveness = ProcessLiveness.UNKNOWN
            owner_identity = None
            if row["relay_pid"] is not None and row["relay_process_created"] is not None:
                owner_identity = self._lookup_identity(row["relay_pid"])
                owner_liveness = self._lookup_liveness(row["relay_pid"])
            if (
                state is ManagedProcessState.CLAIMED
                and row["relay_pid"] is not None
                and (
                    owner_identity != (row["relay_pid"], row["relay_process_created"])
                    or owner_liveness is not ProcessLiveness.ALIVE
                )
            ):
                state = ManagedProcessState.UNKNOWN
            if state is ManagedProcessState.STARTED and row["pid"] is not None:
                identity = self._lookup_identity(row["pid"])
                liveness = self._lookup_liveness(row["pid"])
                if identity is None or row["process_created"] is None:
                    state = ManagedProcessState.UNKNOWN
                elif identity != (row["pid"], row["process_created"]):
                    state = ManagedProcessState.STALE
                else:
                    state = (
                        ManagedProcessState.RUNNING
                        if liveness is ProcessLiveness.ALIVE
                        else ManagedProcessState.UNKNOWN
                    )
            records.append(
                self._record(
                    row,
                    state,
                    LaunchSubmissionState(row["submission_state"]),
                    liveness=liveness,
                    owner_liveness=owner_liveness,
                )
            )
        return tuple(records)


def signal_owned_process_group(pid: int) -> bool:
    """Send Ctrl+Break as an interruption request to the owned process group."""
    if not sys.platform.startswith("win"):
        return False
    try:
        os.kill(pid, signal.CTRL_BREAK_EVENT)
        return True
    except (OSError, ValueError):
        return False
