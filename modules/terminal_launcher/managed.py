"""Durable, argument-free records for explicitly managed terminal children."""

from __future__ import annotations

import hashlib
import os
import signal
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ManagedProcessState(str, Enum):
    UNKNOWN = "unknown"
    STARTED = "started"
    RUNNING = "running"
    EXITED = "exited"
    FAILED = "failed"
    STALE = "stale"


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


@dataclass(frozen=True, slots=True)
class ShutdownRequestResult:
    accepted: bool
    reason: str


@dataclass(frozen=True, slots=True)
class _ShutdownRequest:
    pane_id: str
    pid: int
    process_created: int


ProcessIdentity = Callable[[int], tuple[int, int] | None]
SignalProcessGroup = Callable[[int], bool]


def process_identity(pid: int) -> tuple[int, int] | None:
    """Return ``(pid, creation FILETIME)`` only when Windows confirms identity."""
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


def _default_database_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "terminal-launcher" / "managed-processes.sqlite3"


class ManagedProcessStore:
    """Persist managed process receipts without storing argv, cwd, or titles.

    The submitted window identifier is SHA-256 hashed before persistence. Runtime
    records contain requested topology only; they never claim to observe WT pane
    geometry or application readiness.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        process_identity_lookup: ProcessIdentity | None = None,
    ) -> None:
        selected_path = Path(path).expanduser() if path is not None else _default_database_path()
        self.path = selected_path.resolve()
        self._identity = process_identity_lookup or process_identity
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _lookup_identity(self, pid: int) -> tuple[int, int] | None:
        return (self._identity or process_identity)(pid)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
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
                    started_at REAL,
                    exited_at REAL,
                    exit_code INTEGER,
                    failure_code TEXT,
                    shutdown_requested INTEGER NOT NULL DEFAULT 0,
                    shutdown_delivered INTEGER NOT NULL DEFAULT 0
                )"""
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(managed_panes)")}
            for name in ("relay_pid", "relay_process_created"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE managed_panes ADD COLUMN {name} INTEGER")
            connection.execute("CREATE INDEX IF NOT EXISTS managed_launch_id ON managed_panes(launch_id)")

    @staticmethod
    def _require_id(value: str, name: str) -> str:
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError(f"{name} must be a non-empty string without NUL")
        if len(value) > 256:
            raise ValueError(f"{name} must be at most 256 characters")
        return value

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
        launch_id = self._require_id(launch_id, "launch_id")
        pane_id = self._require_id(pane_id, "pane_id")
        if not isinstance(window_id, str) or not window_id:
            raise ValueError("window_id must be a non-empty string")
        if tab_index < 0 or pane_index < 0:
            raise ValueError("tab and pane indexes must be non-negative")
        if not isinstance(requested_layout, str) or not requested_layout:
            raise ValueError("requested_layout must be a non-empty string")
        window_hash = hashlib.sha256(window_id.encode("utf-8")).hexdigest()
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO managed_panes (
                        launch_id, pane_id, window_id_hash, requested_tab_index,
                        requested_pane_index, requested_layout, submitted_at, state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        launch_id,
                        pane_id,
                        window_hash,
                        tab_index,
                        pane_index,
                        requested_layout,
                        time.time(),
                        ManagedProcessState.UNKNOWN.value,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"managed pane identity already exists: {pane_id}") from exc

    def record_started(
        self,
        pane_id: str,
        *,
        pid: int,
        process_created: int | None,
        relay_pid: int | None = None,
        relay_process_created: int | None = None,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE managed_panes SET state = ?, pid = ?, process_created = ?,
                   relay_pid = ?, relay_process_created = ?, started_at = ?
                   WHERE pane_id = ? AND state = ?""",
                (
                    "started",
                    pid,
                    process_created,
                    relay_pid,
                    relay_process_created,
                    time.time(),
                    pane_id,
                    ManagedProcessState.UNKNOWN.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"managed pane has no pending submission: {pane_id}")

    def record_exit(self, pane_id: str, *, exit_code: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE managed_panes SET state = ?, exited_at = ?, exit_code = ?
                   WHERE pane_id = ? AND state = 'started'""",
                (ManagedProcessState.EXITED.value, time.time(), exit_code, pane_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"managed pane has no start receipt: {pane_id}")

    def record_failure(self, pane_id: str, *, failure_code: str) -> None:
        if not failure_code or len(failure_code) > 80 or not failure_code.replace("_", "").isalnum():
            raise ValueError("failure_code must be a short identifier")
        with self._connect() as connection:
            connection.execute(
                "UPDATE managed_panes SET state = ?, failure_code = ? WHERE pane_id = ?",
                (ManagedProcessState.FAILED.value, failure_code, pane_id),
            )

    @staticmethod
    def _record(row: sqlite3.Row, state: ManagedProcessState | None = None) -> ManagedProcessRecord:
        return ManagedProcessRecord(
            launch_id=row["launch_id"],
            pane_id=row["pane_id"],
            window_id_hash=row["window_id_hash"],
            state=state or ManagedProcessState(row["state"]),
            requested_tab_index=row["requested_tab_index"],
            requested_pane_index=row["requested_pane_index"],
            requested_layout=row["requested_layout"],
            submitted_at=row["submitted_at"],
            pid=row["pid"],
            process_created=row["process_created"],
            relay_pid=row["relay_pid"],
            relay_process_created=row["relay_process_created"],
            started_at=row["started_at"],
            exited_at=row["exited_at"],
            exit_code=row["exit_code"],
            failure_code=row["failure_code"],
            spawn_acknowledged=row["pid"] is not None,
            readiness="unknown",
            shutdown_requested=bool(row["shutdown_requested"]),
            shutdown_delivered=bool(row["shutdown_delivered"]),
        )

    def enumerate_processes(self, *, launch_id: str | None = None) -> tuple[ManagedProcessRecord, ...]:
        query = "SELECT * FROM managed_panes"
        values: tuple[str, ...] = ()
        if launch_id is not None:
            query += " WHERE launch_id = ?"
            values = (launch_id,)
        query += " ORDER BY submitted_at, pane_id"
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()

        records = []
        for row in rows:
            state = ManagedProcessState(row["state"])
            if row["state"] == ManagedProcessState.STARTED.value:
                identity = self._lookup_identity(row["pid"]) if row["pid"] is not None else None
                if identity is not None:
                    state = (
                        ManagedProcessState.RUNNING
                        if identity == (row["pid"], row["process_created"])
                        else ManagedProcessState.STALE
                    )
                else:
                    state = ManagedProcessState.UNKNOWN
            records.append(self._record(row, state))
        return tuple(records)

    def request_graceful_shutdown(self, pane_id: str) -> ShutdownRequestResult:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM managed_panes WHERE pane_id = ?", (pane_id,)).fetchone()
            if row is None:
                return ShutdownRequestResult(False, "unknown_pane")
            if row["state"] != "started" or row["pid"] is None or row["process_created"] is None:
                return ShutdownRequestResult(False, "process_not_running")
            identity = self._lookup_identity(row["pid"])
            if identity is None:
                return ShutdownRequestResult(False, "process_identity_unavailable")
            if identity != (row["pid"], row["process_created"]):
                return ShutdownRequestResult(False, "stale_process_identity")
            relay_identity = (
                self._lookup_identity(row["relay_pid"]) if row["relay_pid"] is not None else None
            )
            if relay_identity is None:
                return ShutdownRequestResult(False, "owning_relay_unavailable")
            if relay_identity != (row["relay_pid"], row["relay_process_created"]):
                return ShutdownRequestResult(False, "stale_relay_identity")
            connection.execute(
                "UPDATE managed_panes SET shutdown_requested = 1 WHERE pane_id = ? AND state = 'started'",
                (pane_id,),
            )
        return ShutdownRequestResult(True, "queued_for_owned_relay")

    def pending_shutdown_requests(self) -> tuple[_ShutdownRequest, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT pane_id, pid, process_created FROM managed_panes
                   WHERE state = 'started' AND shutdown_requested = 1 AND shutdown_delivered = 0"""
            ).fetchall()
        return tuple(_ShutdownRequest(row["pane_id"], row["pid"], row["process_created"]) for row in rows)

    def deliver_shutdown_request(self, pane_id: str, *, signal_process_group: SignalProcessGroup) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM managed_panes WHERE pane_id = ?", (pane_id,)).fetchone()
            if row is None or row["state"] != "started" or not row["shutdown_requested"]:
                return False
            expected = (row["pid"], row["process_created"])
            if self._lookup_identity(row["pid"]) != expected or not signal_process_group(row["pid"]):
                return False
            cursor = connection.execute(
                """UPDATE managed_panes SET shutdown_delivered = 1
                   WHERE pane_id = ? AND state = 'started' AND shutdown_requested = 1""",
                (pane_id,),
            )
            return cursor.rowcount == 1


def signal_owned_process_group(pid: int) -> bool:
    """Send Ctrl+Break; callers must be the relay sharing the pane console."""
    if not sys.platform.startswith("win"):
        return False
    try:
        os.kill(pid, signal.CTRL_BREAK_EVENT)
        return True
    except (OSError, ValueError):
        return False
