"""Named GUI-conversation and agent-slot registry built on continuity events."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .environment import environment_is_locally_owned, load_or_create_environment, resolve_environment_selector
from .errors import ContinuityError, ErrorCode
from .identifiers import generate_id, normalize_path_canonical, normalize_repo_identity, now_utc_iso
from .models import EventEnvelope, EventType
from .service import ADAPTER_VERSION, SCHEMA_EVENT_VERSION, ContinuityService

_VALID_STATES = {"active", "inactive", "completed"}
_PROFILE_SETTING_KEYS = {
    "codex": {"model", "sandbox", "approval_policy", "reasoning_effort", "provider_profile",
              "additional_directories", "enabled_features", "disabled_features", "search",
              "no_alt_screen", "no_daemon", "strict_config"},
    "agy": {"model", "sandbox", "reasoning_effort", "provider_profile", "additional_directories"},
    "claude": {"model", "reasoning_effort", "permission_mode", "provider_profile", "additional_directories"},
}
_PROFILE_RUNTIMES = {"windows", "wsl", "linux", "macos"}
_HELD_MUTATION_LOCKS: ContextVar[frozenset[str]] = ContextVar("llmd_mutation_locks", default=frozenset())
_LOCAL_MUTATION_LOCKS: dict[str, threading.RLock] = {}
_LOCAL_MUTATION_LOCKS_GUARD = threading.Lock()
_HELD_SLOT_LOCKS: ContextVar[frozenset[tuple[str, str]]] = ContextVar("_held_slot_locks", default=frozenset())
_HELD_SESSION_LOCKS: ContextVar[frozenset[tuple[str, str]]] = ContextVar("_held_session_locks", default=frozenset())


def _session_lock_name(provider: str, environment_id: str, session_id: str) -> str:
    key = hashlib.sha256(f"{provider}\0{environment_id}\0{session_id}".encode()).hexdigest()[:24]
    return f"session-{key}.lock"


def _slot_lock_name(slot_id: str) -> str:
    return f"slot-{slot_id}.lock"


def _probe_existing_lock_file(path: Path) -> str:
    """Inspect an existing lock file without creating files or directories."""
    if not path.exists():
        return "not_present"
    try:
        stream = path.open("r+b")
    except OSError:
        return "inaccessible"
    try:
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return "available"
        except OSError:
            return "contended"
    finally:
        stream.close()


@contextlib.contextmanager
def _slot_runtime_lock(home_dir: Path, slot_id: str, *, blocking: bool = False) -> Iterator[None]:
    """Acquire exclusive runtime ownership of one slot for the current launch/resume."""
    lock_name = _slot_lock_name(slot_id)
    try:
        with _mutation_lock(home_dir, lock_name=lock_name, blocking=blocking):
            key = (str(home_dir.resolve()), slot_id)
            token = _HELD_SLOT_LOCKS.set(_HELD_SLOT_LOCKS.get() | {key})
            try:
                yield
            finally:
                _HELD_SLOT_LOCKS.reset(token)
    except ContinuityError as exc:
        if not blocking and "already in use" in exc.message:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                f"Agent slot {slot_id} already has an active or launching session.",
            ) from exc
        raise


@contextlib.contextmanager
def _mutation_lock(home_dir: Path, lock_name: str = "dispatcher.lock", *, blocking: bool = True) -> Iterator[None]:
    """Serialize sequence allocation and spool appends across threads and processes."""
    lock_path = home_dir / lock_name
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_key = str(lock_path.resolve())
    with _LOCAL_MUTATION_LOCKS_GUARD:
        local_lock = _LOCAL_MUTATION_LOCKS.setdefault(lock_key, threading.RLock())
    if not local_lock.acquire(blocking=blocking):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Session is already in use.")
    try:
        held = _HELD_MUTATION_LOCKS.get()
        if lock_key in held:
            yield
            return
        with lock_path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            if os.name == "nt":
                import msvcrt

                deadline = time.monotonic() + (10.0 if blocking else 0.0)
                while True:
                    try:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if not blocking or time.monotonic() >= deadline:
                            raise ContinuityError(
                                ErrorCode.METADATA_INACCESSIBLE,
                                "Session is already in use." if not blocking else "Timed out waiting for dispatcher registry lock.",
                            ) from None
                        time.sleep(0.02)
                token = _HELD_MUTATION_LOCKS.set(held | {lock_key})
                try:
                    yield
                finally:
                    _HELD_MUTATION_LOCKS.reset(token)
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                except BlockingIOError as exc:
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Session is already in use.") from exc
                token = _HELD_MUTATION_LOCKS.set(held | {lock_key})
                try:
                    yield
                finally:
                    _HELD_MUTATION_LOCKS.reset(token)
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        local_lock.release()


@contextlib.contextmanager
def _session_runtime_lock_ctx(
    home_dir: Path, provider: str, environment_id: str, session_id: str, *, blocking: bool = False
) -> Iterator[None]:
    """Acquire exclusive runtime ownership of one exact session."""
    lock_name = _session_lock_name(provider, environment_id, session_id)
    with _mutation_lock(home_dir, lock_name=lock_name, blocking=blocking):
        key = (str(home_dir.resolve()), lock_name)
        token = _HELD_SESSION_LOCKS.set(_HELD_SESSION_LOCKS.get() | {key})
        try:
            yield
        finally:
            _HELD_SESSION_LOCKS.reset(token)


class DispatcherService:
    """Durable dispatcher operations sharing the existing continuity spool and index."""

    def __init__(
        self,
        continuity: ContinuityService | None = None,
        home_dir: Path | str | None = None,
        workflow_bridge: Any = None,
    ) -> None:
        if continuity is not None and home_dir is not None:
            raise ValueError("Pass either a ContinuityService or home_dir, not both.")
        from .workflows import LocalAgentBridgeWorkflowAdapter

        self.continuity = continuity or ContinuityService(home_dir)
        self.materializer = self.continuity.materializer
        self.home_dir = self.continuity.home_dir
        self.workflow_bridge = workflow_bridge or LocalAgentBridgeWorkflowAdapter()

    def _sync(self) -> None:
        if self.continuity._can_write_sqlite():
            # The reconciliation helper owns the registry lock and performs
            # spool synchronization before inspecting or assigning numbers.
            # Synchronizing here as well doubled every normal read's locked
            # SQLite work, including the hot continuation path.
            self._record_legacy_agent_number_assignments()

    def _record_legacy_agent_number_assignments(self) -> None:
        """Preserve existing numbers, then assign deterministic numbers to legacy slots."""
        with _mutation_lock(self.home_dir):
            self.materializer.sync_from_spools()
            duplicate = self._row(
                "SELECT gui_id, agent_number FROM agent_slots WHERE agent_number IS NOT NULL "
                "GROUP BY gui_id, agent_number HAVING COUNT(*) > 1 LIMIT 1"
            )
            if duplicate:
                raise ContinuityError(ErrorCode.ASSOCIATION_CONFLICT,
                                      f"GUI {duplicate['gui_id']} has duplicate existing agent number {duplicate['agent_number']}.")
            preserved = self._rows(
                """SELECT s.slot_id, s.gui_id, s.agent_number FROM agent_slots s
                   LEFT JOIN dispatcher_agent_number_reservations r
                     ON r.gui_id = s.gui_id AND r.agent_number = s.agent_number
                   WHERE s.agent_number IS NOT NULL AND r.slot_id IS NULL
                   ORDER BY s.gui_id, s.agent_number, s.slot_id"""
            )
            legacy = self._rows(
                """SELECT s.slot_id, s.gui_id FROM agent_slots s
                   LEFT JOIN activity_events e ON e.event_type = ?
                     AND json_extract(e.payload_json, '$.slot_id') = s.slot_id
                   WHERE s.agent_number IS NULL
                   GROUP BY s.slot_id, s.gui_id, s.created_at
                   ORDER BY s.gui_id, MIN(e.rowid), s.created_at, s.slot_id""",
                (EventType.DISPATCHER_SLOT_CREATED.value,),
            )
            if not preserved and not legacy:
                return
            env = load_or_create_environment(self.home_dir, persist=True)
            events: list[EventEnvelope] = []
            for row in preserved:
                conflicting = self._row(
                    "SELECT slot_id FROM dispatcher_agent_number_reservations WHERE gui_id = ? AND agent_number = ?",
                    (row["gui_id"], row["agent_number"]),
                )
                if conflicting:
                    raise ContinuityError(ErrorCode.ASSOCIATION_CONFLICT,
                                          "An existing agent number conflicts with a permanent reservation.")
                events.append(self._event(
                    EventType.DISPATCHER_AGENT_NUMBER_ASSIGNED,
                    environment_id=env.environment_id,
                    payload={"slot_id": str(row["slot_id"]), "gui_id": str(row["gui_id"]),
                             "agent_number": int(row["agent_number"]), "source": "preserved_existing_registry_number"},
                ))
            next_numbers: dict[str, int] = {}
            for row in legacy:
                gui_id = str(row["gui_id"])
                if gui_id not in next_numbers:
                    reservation = self._row(
                        """SELECT MAX(value) + 1 AS value FROM (
                               SELECT COALESCE(MAX(agent_number), 0) AS value
                                 FROM dispatcher_agent_number_reservations WHERE gui_id = ?
                               UNION ALL
                               SELECT COALESCE(MAX(agent_number), 0) AS value
                                 FROM agent_slots WHERE gui_id = ?
                           )""", (gui_id, gui_id),
                    )
                    next_numbers[gui_id] = int((reservation or {}).get("value") or 1)
                number = next_numbers[gui_id]
                events.append(self._event(
                    EventType.DISPATCHER_AGENT_NUMBER_ASSIGNED,
                    environment_id=env.environment_id,
                    payload={"slot_id": str(row["slot_id"]), "gui_id": gui_id,
                             "agent_number": number, "source": "legacy_event_ingest_order"},
                ))
                next_numbers[gui_id] = number + 1
            self.continuity._emit_and_materialize(events)

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = self.materializer._connect_ro()
        if conn is None:
            return []
        try:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def _row(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def _next_agent_number(self, gui_id: str) -> int:
        row = self._row(
            "SELECT COALESCE(MAX(agent_number), 0) + 1 AS value "
            "FROM dispatcher_agent_number_reservations WHERE gui_id = ?",
            (gui_id,),
        )
        return int((row or {}).get("value", 1))

    def _event(
        self,
        event_type: EventType,
        *,
        environment_id: str,
        payload: dict[str, Any],
        provider: str | None = None,
        session_id: str | None = None,
        timestamp: str | None = None,
    ) -> EventEnvelope:
        ts = timestamp or now_utc_iso()
        return EventEnvelope(
            event_id=generate_id("evt"),
            event_schema_version=SCHEMA_EVENT_VERSION,
            event_type=event_type.value,
            provider=provider,
            environment_id=environment_id,
            native_session_id=session_id,
            source_timestamp=ts,
            observed_timestamp=ts,
            source_adapter_version=ADAPTER_VERSION,
            payload=payload,
        )

    @staticmethod
    def _terminal_uuid(value: str) -> str:
        try:
            return str(uuid.UUID(str(value).strip()))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                "TERMINAL_SESSION_ID must contain a valid UUID for terminal-scoped launch history.",
            ) from exc

    def record_terminal_launch(self, record: dict[str, Any]) -> dict[str, Any]:
        """Append one immutable event for a terminal-scoped launch-state snapshot."""
        terminal_id = self._terminal_uuid(record.get("terminal_session_id"))
        launch_id = str(record.get("launch_id") or "").strip()
        environment_id = str(record.get("environment_id") or "").strip()
        status = str(record.get("status") or "").strip()
        started_at = str(record.get("launch_started_at") or "").strip()
        if not launch_id or not environment_id or not started_at:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Terminal launch records require launch, environment, and start identities.")
        if status not in {"launching", "running", "exited", "failed", "spawn_failed", "abnormal_exit", "interrupted"}:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported terminal launch status {status!r}.")
        settings = record.get("settings") or {}
        if not isinstance(settings, dict):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Terminal launch settings summary must be an object.")
        try:
            json.dumps(settings, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Terminal launch settings summary must be JSON-safe.") from exc
        payload = {
            **{key: record.get(key) for key in (
                "terminal_session_owner_pid", "gui_id", "gui_alias", "slot_id", "slot_name",
                "provider", "native_session_id", "launch_exited_at", "exit_code", "requested_cwd",
                "effective_cwd", "native_cwd", "git_repository", "git_worktree", "git_branch", "git_commit",
            )},
            "launch_id": launch_id,
            "terminal_session_id": terminal_id,
            "launch_started_at": started_at,
            "status": status,
            "settings": settings,
        }
        provider = str(record.get("provider") or "").strip() or None
        session_id = str(record.get("native_session_id") or "").strip() or None
        event = self._event(
            EventType.DISPATCHER_TERMINAL_LAUNCH_RECORDED,
            environment_id=environment_id,
            provider=provider,
            session_id=session_id,
            payload=payload,
            timestamp=now_utc_iso(),
        )
        with _mutation_lock(self.home_dir):
            self._sync()
            existing = self._row(
                "SELECT * FROM dispatcher_terminal_launches WHERE launch_id = ?", (launch_id,)
            )
            if existing:
                expected = (existing["terminal_session_id"], existing["slot_id"], existing["provider"], existing["environment_id"])
                actual = (terminal_id, payload.get("slot_id"), provider, environment_id)
                if actual != expected:
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Terminal launch update conflicts with its recorded identity.")
                if existing["native_session_id"] and session_id != existing["native_session_id"]:
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Terminal launch update cannot replace its captured native session ID.")
            self.continuity._emit_and_materialize([event])
        return {**payload, "environment_id": environment_id, "event_id": event.event_id}

    def list_terminal_launches(self, terminal_session_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return history only for the validated calling terminal UUID."""
        terminal_id = self._terminal_uuid(terminal_session_id)
        if limit < 1 or limit > 1000:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Terminal history count must be between 1 and 1000.")
        self._sync()
        rows = self._rows(
            """SELECT * FROM dispatcher_terminal_launches WHERE terminal_session_id = ?
               ORDER BY launch_started_at DESC, launch_id DESC LIMIT ?""",
            (terminal_id, limit),
        )
        for row in rows:
            row["settings"] = json.loads(row.pop("settings_json") or "{}")
        return rows

    def list_recent_terminal_launches(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return cross-terminal launch history for read-only diagnostics."""
        if limit < 1 or limit > 1000:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Recent history count must be between 1 and 1000.")
        self._sync()
        rows = self._rows(
            """SELECT * FROM dispatcher_terminal_launches
               ORDER BY launch_started_at DESC, launch_id DESC LIMIT ?""",
            (limit,),
        )
        for row in rows:
            row["settings"] = json.loads(row.pop("settings_json") or "{}")
        return rows

    def latest_terminal_launch_for_identity(
        self, *, slot_id: str, provider: str, environment_id: str, native_session_id: str,
    ) -> dict[str, Any] | None:
        """Return the newest launch for one exact slot/provider/environment/session identity."""
        if not all(value.strip() for value in (slot_id, provider, environment_id, native_session_id)):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Exact terminal-launch identity fields must be non-empty.")
        self._sync()
        row = self._row(
            """SELECT * FROM dispatcher_terminal_launches
               WHERE slot_id = ? AND provider = ? AND environment_id = ? AND native_session_id = ?
               ORDER BY launch_started_at DESC, launch_id DESC LIMIT 1""",
            (slot_id, provider, environment_id, native_session_id),
        )
        if row is None:
            return None
        row["settings"] = json.loads(row.pop("settings_json") or "{}")
        return row

    def list_terminal_launches_for_session_identity(
        self, *, provider: str, environment_id: str, native_session_id: str,
    ) -> list[dict[str, Any]]:
        """Return all exact-session launch associations without a global history cap."""
        if not all(value.strip() for value in (provider, environment_id, native_session_id)):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Exact terminal-session identity fields must be non-empty.")
        self._sync()
        rows = self._rows(
            """SELECT * FROM dispatcher_terminal_launches
               WHERE provider = ? AND environment_id = ? AND native_session_id = ?
               ORDER BY launch_started_at DESC, launch_id DESC""",
            (provider, environment_id, native_session_id),
        )
        for row in rows:
            row["settings"] = json.loads(row.pop("settings_json") or "{}")
        return rows

    def _gui(self, identifier: str) -> dict[str, Any]:
        self._sync()
        raw = identifier.strip()
        gui = self._row(
            "SELECT * FROM dispatcher_gui_conversations WHERE gui_id = ? OR alias_key = ?",
            (raw, raw.casefold()),
        )
        if gui is None:
            raise ContinuityError(ErrorCode.WORKFLOW_NOT_FOUND, f"GUI conversation not found: {identifier!r}.")
        return gui

    def _slot(self, gui_id: str, name_or_id: str) -> dict[str, Any]:
        raw = name_or_id.strip()
        slot = self._row(
            "SELECT * FROM agent_slots WHERE gui_id = ? AND (slot_id = ? OR name_key = ?)",
            (gui_id, raw, raw.casefold()),
        )
        if slot is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Agent slot not found: {name_or_id!r}.")
        return slot

    def _history(self, slot_id: str) -> list[dict[str, Any]]:
        return self._rows(
            """SELECT activation_id, sequence, provider, environment_id, native_session_id,
                      provenance, activated_at
               FROM agent_slot_activations WHERE slot_id = ? ORDER BY sequence""",
            (slot_id,),
        )

    def create_gui(self, alias: str, *, apply: bool = False) -> dict[str, Any]:
        clean = alias.strip()
        if not clean or len(clean) > 120:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "GUI alias must contain 1–120 characters.")
        self._sync()
        existing = self._row(
            "SELECT gui_id, alias FROM dispatcher_gui_conversations WHERE alias_key = ?",
            (clean.casefold(),),
        )
        if existing:
            return {
                "action": "gui-register",
                "applied": False,
                "summary": f"GUI conversation {existing['alias']!r} is already registered.",
                "details": {"gui_id": existing["gui_id"], "existing_alias": existing["alias"]},
                "events": [],
            }
        gui_id = generate_id("gui")
        env = load_or_create_environment(self.home_dir, persist=apply)
        event = self._event(
            EventType.DISPATCHER_GUI_REGISTERED,
            environment_id=env.environment_id,
            payload={"gui_id": gui_id, "alias": clean, "alias_key": clean.casefold()},
        )
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                if self._row("SELECT 1 FROM dispatcher_gui_conversations WHERE alias_key = ?", (clean.casefold(),)):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, f"GUI alias {clean!r} was registered concurrently.")
                events = self.continuity._ensure_environment_event(env, self.materializer.list_environments(), event.observed_timestamp)
                self.continuity._emit_and_materialize([*events, event])
        return {
            "action": "gui-register",
            "applied": apply,
            "summary": f"{'Registered' if apply else 'Dry-run: would register'} GUI conversation {clean!r}.",
            "details": {"gui_id": gui_id, "alias": clean},
            "events": [event.to_dict()],
        }

    def register(self, gui: str, name: str | None = None, *, provider: str | None = None,
                 session_id: str | None = None, apply: bool = True, select: bool = False) -> dict[str, Any]:
        """Register identities and an optional session under one dispatcher mutation lock."""
        gui = gui.strip()
        name = name.strip() if name is not None else None
        if not gui or len(gui) > 120 or (name is not None and (not name or len(name) > 120)):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "GUI and agent names must contain 1 to 120 characters.")
        if bool(provider) != bool(session_id) or (session_id is not None and not session_id.strip()):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Provider and nonempty session ID must be supplied together.")
        if provider and not name:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "A session requires an agent name.")
        provider = self.continuity._validate_provider(provider) if provider else None
        session_id = session_id.strip() if session_id else None
        events: list[EventEnvelope] = []
        with _mutation_lock(self.home_dir) if apply else contextlib.nullcontext():
            self._sync()
            conversation = self._row("SELECT * FROM dispatcher_gui_conversations WHERE alias_key = ?", (gui.casefold(),))
            slot = (self._row("SELECT * FROM agent_slots WHERE gui_id = ? AND name_key = ?",
                              (conversation['gui_id'], name.casefold())) if conversation and name else None)
            env = load_or_create_environment(self.home_dir, persist=False)
            history = self._history(slot['slot_id']) if slot else []
            if history and provider:
                current = history[-1]
                same_current = (current['provider'], current['environment_id'], current['native_session_id']) == (
                    provider, env.environment_id, session_id
                )
                if not same_current and not select:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "A different session is selected; pass --select to change it.")
                if not same_current:
                    lock_key = __import__('hashlib').sha256(
                        f"{current['provider']}\0{current['environment_id']}\0{current['native_session_id']}".encode()
                    ).hexdigest()[:24]
                    try:
                        with _mutation_lock(self.home_dir, f"session-{lock_key}.lock", blocking=False):
                            pass
                    except ContinuityError as exc:
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                            "Cannot change selection while the current session is in use.") from exc
            if apply:
                env = load_or_create_environment(self.home_dir, persist=True)
            gui_id = conversation['gui_id'] if conversation else generate_id('gui')
            slot_id = slot['slot_id'] if slot else generate_id('slot') if name else None
            timestamp = now_utc_iso()
            if not conversation:
                events.append(self._event(EventType.DISPATCHER_GUI_REGISTERED, environment_id=env.environment_id,
                    payload={'gui_id': gui_id, 'alias': gui, 'alias_key': gui.casefold()}, timestamp=timestamp))
            if name and not slot:
                slot_payload = {'slot_id': slot_id, 'gui_id': gui_id, 'name': name, 'name_key': name.casefold()}
                if apply:
                    slot_payload['agent_number'] = self._next_agent_number(gui_id)
                events.append(self._event(EventType.DISPATCHER_SLOT_CREATED, environment_id=env.environment_id,
                    payload=slot_payload, timestamp=timestamp))
            same = history and provider and (history[-1]['provider'], history[-1]['environment_id'],
                    history[-1]['native_session_id']) == (provider, env.environment_id, session_id)
            if provider and not same:
                if not self.materializer.get_session(provider, env.environment_id, session_id):
                    events.append(self._event(EventType.SESSION_REGISTERED, environment_id=env.environment_id,
                        provider=provider, session_id=session_id, timestamp=timestamp,
                        payload={'environment': env.to_dict(), 'cwd_native': None, 'cwd_canonical': None,
                                 'repository_identity': None, 'first_observed_at': timestamp,
                                 'last_seen_at': timestamp, 'metadata_source': 'dispatcher_attach'}))
                activation_time = (datetime.now(UTC) + timedelta(microseconds=2)).isoformat(timespec='microseconds').replace('+00:00', 'Z')
                events.append(self._event(EventType.DISPATCHER_SESSION_ACTIVATED, environment_id=env.environment_id,
                    provider=provider, session_id=session_id, timestamp=activation_time,
                    payload={'slot_id': slot_id, 'activation_id': generate_id('act'),
                             'sequence': (history[-1]['sequence'] if history else 0) + 1,
                             'provenance': 'explicit_attach'}))
            if events:
                base_time = datetime.now(UTC)
                events = [replace(event, source_timestamp=(base_time + timedelta(microseconds=i + 1)).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                                  observed_timestamp=(base_time + timedelta(microseconds=i + 1)).isoformat(timespec="microseconds").replace("+00:00", "Z"))
                          for i, event in enumerate(events)]
            if apply and events:
                env_events = self.continuity._ensure_environment_event(env, self.materializer.list_environments(),
                    base_time.isoformat(timespec="microseconds").replace("+00:00", "Z"))
                self.continuity._emit_and_materialize([*env_events, *events])
        return {'action': 'register', 'applied': bool(apply and events), 'events': [e.to_dict() for e in events],
                'details': {'gui_id': gui_id, 'slot_id': slot_id, 'agent_number': (self._row('SELECT agent_number FROM agent_slots WHERE slot_id = ?', (slot_id,)) or {}).get('agent_number') if apply and slot_id else None},
                'summary': ('Registered' if apply and events else 'Dry-run: would register' if events else 'Already registered') + f' {gui!r}' + (f' / {name!r}' if name else '') + '.'}

    @staticmethod
    def _normalize_profile_settings(provider: str, settings: dict[str, Any] | None) -> dict[str, Any]:
        if settings is None:
            settings = {}
        if not isinstance(settings, dict):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Profile settings must be an object.")
        normalized: dict[str, Any] = {}
        for raw_key, value in settings.items():
            key = str(raw_key).strip().casefold().replace("-", "_")
            if key == "effort":
                key = "reasoning_effort"
            if key not in _PROFILE_SETTING_KEYS[provider]:
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    f"Unsupported profile setting {raw_key!r}; profiles accept only provider-managed non-secret settings.",
                )
            if key in normalized:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Duplicate profile setting {key!r}.")
            if key in {"additional_directories", "enabled_features", "disabled_features"}:
                if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, f"Profile setting {key!r} must be a list of nonempty strings.")
                clean = [item.strip() for item in value]
                if key == "additional_directories" and any(
                    not (PureWindowsPath(item).is_absolute() if provider == "codex" and "\\" in item
                         else PurePosixPath(item).is_absolute() if item.startswith("/")
                         else Path(item).is_absolute())
                    for item in clean
                ):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Profile additional directories must be absolute paths.")
                normalized[key] = clean
                continue
            if key in {"search", "no_alt_screen", "no_daemon", "strict_config", "auto_approval"} or (
                provider == "agy" and key == "sandbox"
            ):
                if not isinstance(value, bool):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, f"Profile setting {key!r} must be boolean.")
                normalized[key] = value
                continue
            if not isinstance(value, str) or not value.strip() or len(value) > 4096:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Profile setting {key!r} must be a nonempty string of at most 4096 characters.")
            clean = value.strip()
            if any(marker in clean.casefold() for marker in ("api_key=", "api-key=", "token=", "password=", "sk-ant-")):
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Profile values cannot contain credentials or secret assignments.")
            choices = {
                "sandbox": {"read-only", "workspace-write", "danger-full-access"},
                "approval_policy": {"on-request", "never"},
                "reasoning_effort": {"low", "medium", "high", "xhigh", "max"},
                "permission_mode": {"default", "manual", "acceptEdits", "plan", "auto", "dontAsk"},
            }
            if key in choices and clean not in choices[key]:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Invalid profile setting value for {key!r}.")
            if (key == "approval_policy" and clean == "never") or (
                key == "permission_mode" and clean in {"auto", "dontAsk"}
            ):
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      "Profiles cannot persist approval bypass or unattended authorization settings.")
            normalized[key] = clean
        return {key: normalized[key] for key in sorted(normalized)}

    @staticmethod
    def _profile_path(runtime_kind: str | None, cwd: str | None) -> str | None:
        clean = str(cwd).strip() if cwd is not None else None
        if not clean:
            return None
        if runtime_kind is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "A profile working directory requires an explicit runtime kind.")
        absolute = PureWindowsPath(clean).is_absolute() if runtime_kind == "windows" else PurePosixPath(clean).is_absolute()
        if not absolute:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Profile working directory must be absolute for its runtime.")
        return clean

    def _profile_row(self, identifier: str) -> dict[str, Any] | None:
        value = identifier.strip()
        if not value:
            return None
        return self._row("SELECT * FROM dispatcher_launch_profiles WHERE profile_id = ?", (value,)) or self._row(
            "SELECT * FROM dispatcher_launch_profiles WHERE name_key = ?", (value.casefold(),)
        )

    @staticmethod
    def _profile_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "settings": json.loads(row.pop("settings_json"))}

    def create_profile(
        self, *, name: str, provider: str, runtime_kind: str | None = None, cwd: str | None = None,
        settings: dict[str, Any] | None = None, apply: bool = True,
    ) -> dict[str, Any]:
        clean = name.strip()
        if not clean or len(clean) > 120:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Profile name must contain 1 to 120 characters.")
        provider_name = self.continuity._validate_provider(provider)
        runtime = runtime_kind.casefold().strip() if runtime_kind else None
        if runtime is not None and runtime not in _PROFILE_RUNTIMES:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported profile runtime {runtime!r}.")
        profile_cwd = self._profile_path(runtime, cwd)
        normalized = self._normalize_profile_settings(provider_name, settings)
        profile_id = generate_id("profile")
        env = load_or_create_environment(self.home_dir, persist=apply)
        timestamp = now_utc_iso()
        payload = {"profile_id": profile_id, "name": clean, "name_key": clean.casefold(),
                   "provider": provider_name, "runtime_kind": runtime, "cwd": profile_cwd,
                   "settings": normalized, "revision": 1, "created_at": timestamp}
        event = self._event(EventType.DISPATCHER_LAUNCH_PROFILE_CREATED, environment_id=env.environment_id,
                            payload=payload, timestamp=timestamp)
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                if self._profile_row(clean):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, f"Launch profile {clean!r} already exists.")
                self.continuity._emit_and_materialize([event])
        return {"action": "profile-create", "applied": apply,
                "summary": f"{'Created' if apply else 'Dry-run: would create'} launch profile {clean!r}.",
                "details": {"profile_id": profile_id, "name": clean, "provider": provider_name,
                            "runtime_kind": runtime, "revision": 1}, "events": [event.to_dict()]}

    def get_profile(self, identifier: str) -> dict[str, Any]:
        self._sync()
        row = self._profile_row(identifier)
        if row is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Launch profile not found: {identifier!r}.")
        return self._profile_dict(row)

    def list_profiles(self, *, provider: str | None = None, include_retired: bool = False) -> list[dict[str, Any]]:
        self._sync()
        clauses: list[str] = []
        params: list[Any] = []
        if provider:
            clauses.append("provider = ?")
            params.append(self.continuity._validate_provider(provider))
        if not include_retired:
            clauses.append("status = 'active'")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self._rows(f"SELECT * FROM dispatcher_launch_profiles {where} ORDER BY name_key", tuple(params))
        return [self._profile_dict(row) for row in rows]

    def update_profile(
        self, identifier: str, *, name: str | None = None, provider: str | None = None,
        runtime_kind: str | None = None, cwd: str | None = None, clear_cwd: bool = False,
        settings: dict[str, Any] | None = None, clear_settings: list[str] | None = None,
        apply: bool = True,
    ) -> dict[str, Any]:
        profile = self.get_profile(identifier)
        if profile["status"] != "active":
            raise ContinuityError(ErrorCode.INVALID_INPUT, "A retired profile cannot be updated; create a new profile.")
        clean = name.strip() if name is not None else profile["name"]
        if not clean or len(clean) > 120:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Profile name must contain 1 to 120 characters.")
        provider_name = self.continuity._validate_provider(provider or profile["provider"])
        runtime = runtime_kind.casefold().strip() if runtime_kind else profile["runtime_kind"]
        if runtime is not None and runtime not in _PROFILE_RUNTIMES:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported profile runtime {runtime!r}.")
        profile_cwd = None if clear_cwd else self._profile_path(runtime, cwd if cwd is not None else profile["cwd"])
        merged = dict(profile["settings"])
        for key in clear_settings or []:
            normalized_key = str(key).strip().casefold().replace("-", "_")
            if normalized_key == "effort":
                normalized_key = "reasoning_effort"
            merged.pop(normalized_key, None)
        merged.update(settings or {})
        normalized = self._normalize_profile_settings(provider_name, merged)
        timestamp = now_utc_iso()
        payload = {"profile_id": profile["profile_id"], "name": clean, "name_key": clean.casefold(),
                   "provider": provider_name, "runtime_kind": runtime, "cwd": profile_cwd,
                   "settings": normalized, "revision": int(profile["revision"]) + 1}
        env = load_or_create_environment(self.home_dir, persist=apply)
        event = self._event(EventType.DISPATCHER_LAUNCH_PROFILE_UPDATED, environment_id=env.environment_id,
                            payload=payload, timestamp=timestamp)
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                current = self._profile_row(profile["profile_id"])
                if current is None or int(current["revision"]) != int(profile["revision"]):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Profile changed concurrently; reload it before updating.")
                conflict = self._row("SELECT profile_id FROM dispatcher_launch_profiles WHERE name_key = ? AND profile_id != ?",
                                     (clean.casefold(), profile["profile_id"]))
                if conflict:
                    raise ContinuityError(ErrorCode.INVALID_INPUT, f"Launch profile {clean!r} already exists.")
                self.continuity._emit_and_materialize([event])
        return {"action": "profile-update", "applied": apply,
                "summary": f"{'Updated' if apply else 'Dry-run: would update'} launch profile {clean!r}.",
                "details": {"profile_id": profile["profile_id"], "name": clean, "revision": payload["revision"]},
                "events": [event.to_dict()]}

    def retire_profile(self, identifier: str, *, apply: bool = True) -> dict[str, Any]:
        profile = self.get_profile(identifier)
        if profile["status"] == "retired":
            return {"action": "profile-retire", "applied": False, "summary": "Launch profile is already retired.",
                    "details": {"profile_id": profile["profile_id"]}, "events": []}
        env = load_or_create_environment(self.home_dir, persist=apply)
        event = self._event(EventType.DISPATCHER_LAUNCH_PROFILE_RETIRED, environment_id=env.environment_id,
                            payload={"profile_id": profile["profile_id"]})
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                current = self._profile_row(profile["profile_id"])
                if current is None or current["status"] != "active":
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Profile changed concurrently; reload it before retiring.")
                self.continuity._emit_and_materialize([event])
        return {"action": "profile-retire", "applied": apply,
                "summary": f"{'Retired' if apply else 'Dry-run: would retire'} launch profile {profile['name']!r}.",
                "details": {"profile_id": profile["profile_id"]}, "events": [event.to_dict()]}

    def assign_profile(self, *, gui: str, agent: str, profile: str, apply: bool = True) -> dict[str, Any]:
        conversation = self._gui(gui)
        slot = self._slot(conversation["gui_id"], agent)
        selected = self.get_profile(profile)
        if selected["status"] != "active":
            raise ContinuityError(ErrorCode.INVALID_INPUT, "A retired profile cannot be assigned.")
        history = self._history(slot["slot_id"])
        if history and history[-1]["provider"] != selected["provider"]:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  f"Profile provider {selected['provider']} is incompatible with selected session provider {history[-1]['provider']}.")
        if history and selected["runtime_kind"]:
            env = self._row("SELECT runtime_kind FROM environments WHERE environment_id = ?", (history[-1]["environment_id"],))
            if env and env["runtime_kind"] not in {"unknown", selected["runtime_kind"]}:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      f"Profile runtime {selected['runtime_kind']} is incompatible with selected session runtime {env['runtime_kind']}.")
        if slot.get("profile_id") == selected["profile_id"]:
            return {"action": "profile-assign", "applied": False, "summary": "Profile is already assigned.",
                    "details": {"slot_id": slot["slot_id"], "profile_id": selected["profile_id"]}, "events": []}
        env = load_or_create_environment(self.home_dir, persist=apply)
        event = self._event(EventType.DISPATCHER_SLOT_PROFILE_ASSIGNED, environment_id=env.environment_id,
                            payload={"slot_id": slot["slot_id"], "profile_id": selected["profile_id"]})
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                latest = self._slot(conversation["gui_id"], slot["slot_id"])
                if latest.get("profile_id") != slot.get("profile_id"):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Slot profile changed concurrently; reload before assigning.")
                latest_profile = self._profile_row(selected["profile_id"])
                if (latest_profile is None or latest_profile["status"] != "active"
                        or int(latest_profile["revision"]) != int(selected["revision"])):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Profile changed or retired concurrently; reload before assigning.")
                latest_history = self._history(slot["slot_id"])
                if latest_history and latest_history[-1]["provider"] != selected["provider"]:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "Profile provider no longer matches the selected session provider.")
                if latest_history and selected["runtime_kind"]:
                    latest_environment = self._row("SELECT runtime_kind FROM environments WHERE environment_id = ?",
                                                   (latest_history[-1]["environment_id"],))
                    if latest_environment and latest_environment["runtime_kind"] not in {"unknown", selected["runtime_kind"]}:
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Profile runtime no longer matches the selected session runtime.")
                self.continuity._emit_and_materialize([event])
        return {"action": "profile-assign", "applied": apply,
                "summary": f"{'Assigned' if apply else 'Dry-run: would assign'} profile {selected['name']!r} to {slot['name']!r}.",
                "details": {"slot_id": slot["slot_id"], "profile_id": selected["profile_id"]},
                "events": [event.to_dict()]}

    def clear_profile(self, *, gui: str, agent: str, apply: bool = True) -> dict[str, Any]:
        conversation = self._gui(gui)
        slot = self._slot(conversation["gui_id"], agent)
        if not slot.get("profile_id"):
            return {"action": "profile-clear", "applied": False, "summary": "Agent has no assigned profile.",
                    "details": {"slot_id": slot["slot_id"]}, "events": []}
        env = load_or_create_environment(self.home_dir, persist=apply)
        event = self._event(EventType.DISPATCHER_SLOT_PROFILE_ASSIGNED, environment_id=env.environment_id,
                            payload={"slot_id": slot["slot_id"], "profile_id": None})
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                latest = self._slot(conversation["gui_id"], slot["slot_id"])
                if latest.get("profile_id") != slot["profile_id"]:
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Slot profile changed concurrently; reload before clearing.")
                self.continuity._emit_and_materialize([event])
        return {"action": "profile-clear", "applied": apply,
                "summary": f"{'Cleared' if apply else 'Dry-run: would clear'} profile from {slot['name']!r}.",
                "details": {"slot_id": slot["slot_id"]}, "events": [event.to_dict()]}

    def list_guis(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        self._sync()
        where = "WHERE status = 'active'" if active_only else ""
        return self._rows(
            f"SELECT * FROM dispatcher_gui_conversations {where} ORDER BY last_activity_at IS NULL, last_activity_at DESC, alias_key"
        )

    def rename_gui(self, *, gui: str, alias: str, apply: bool = False) -> dict[str, Any]:
        clean = alias.strip()
        if not clean or len(clean) > 120:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "GUI alias must contain 1–120 characters.")
        conversation = self._gui(gui)
        if conversation["alias_key"] == clean.casefold():
            return {"action": "gui-rename", "applied": False, "summary": "GUI alias is unchanged.",
                    "details": {"gui_id": conversation["gui_id"], "alias": conversation["alias"]}, "events": []}
        conflict = self._row(
            "SELECT alias FROM dispatcher_gui_conversations WHERE alias_key = ? AND gui_id != ?",
            (clean.casefold(), conversation["gui_id"]),
        )
        if conflict:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"GUI alias {clean!r} is already in use.")
        env = load_or_create_environment(self.home_dir, persist=apply)
        event = self._event(
            EventType.DISPATCHER_GUI_RENAMED,
            environment_id=env.environment_id,
            payload={"gui_id": conversation["gui_id"], "alias": clean, "alias_key": clean.casefold()},
        )
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                if self._row("SELECT 1 FROM dispatcher_gui_conversations WHERE alias_key = ? AND gui_id != ?",
                              (clean.casefold(), conversation["gui_id"])):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, f"GUI alias {clean!r} was registered concurrently.")
                self.continuity._emit_and_materialize([event])
        return {"action": "gui-rename", "applied": apply,
                "summary": f"{'Renamed' if apply else 'Dry-run: would rename'} GUI alias {conversation['alias']!r} to {clean!r}.",
                "details": {"gui_id": conversation["gui_id"], "old_alias": conversation["alias"], "alias": clean},
                "events": [event.to_dict()]}

    def create_slot(self, *, gui: str, name: str, apply: bool = False) -> dict[str, Any]:
        clean = name.strip()
        if not clean or len(clean) > 120:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Agent name must contain 1–120 characters.")
        conversation = self._gui(gui)
        existing = self._row(
            "SELECT slot_id, name, agent_number FROM agent_slots WHERE gui_id = ? AND name_key = ?",
            (conversation["gui_id"], clean.casefold()),
        )
        if existing:
            return {"action": "slot-create", "applied": False, "summary": "Agent slot already exists.",
                    "details": {"slot_id": existing["slot_id"], "existing_name": existing["name"],
                                "agent_number": existing["agent_number"]}, "events": []}
        slot_id = generate_id("slot")
        env = load_or_create_environment(self.home_dir, persist=apply)
        number = None
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                if self._row("SELECT 1 FROM agent_slots WHERE gui_id = ? AND name_key = ?",
                             (conversation["gui_id"], clean.casefold())):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, f"Agent name {clean!r} was registered concurrently.")
                number = self._next_agent_number(conversation["gui_id"])
                event = self._event(
                    EventType.DISPATCHER_SLOT_CREATED, environment_id=env.environment_id,
                    payload={"slot_id": slot_id, "gui_id": conversation["gui_id"], "name": clean,
                             "name_key": clean.casefold(), "agent_number": number},
                )
                self.continuity._emit_and_materialize([event])
        else:
            event = self._event(
                EventType.DISPATCHER_SLOT_CREATED, environment_id=env.environment_id,
                payload={"slot_id": slot_id, "gui_id": conversation["gui_id"], "name": clean,
                         "name_key": clean.casefold()},
            )
            number = self._next_agent_number(conversation["gui_id"])
        return {"action": "slot-create", "applied": apply,
                "summary": f"{'Created' if apply else 'Dry-run: would create'} agent slot {clean!r}" +
                           (f" as #{number}." if number else "."),
                "details": {"slot_id": slot_id, "gui_id": conversation["gui_id"], "name": clean,
                            "agent_number": number},
                "events": [event.to_dict()]}

    def set_workflow_type(self, *, gui: str, agent: str, workflow_type: str | None,
                          apply: bool = True) -> dict[str, Any]:
        allowed = {"standard", "handoff", "goal"}
        selected = workflow_type.strip().casefold() if workflow_type is not None else None
        if selected is not None and selected not in allowed:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "Invalid workflow type; choose standard, handoff, goal, or null to clear it.")
        conversation = self._gui(gui)
        slot = self._slot(conversation["gui_id"], agent)
        if slot.get("workflow_type") == selected:
            return {"action": "workflow-type", "applied": False,
                    "summary": "Workflow type is unchanged.",
                    "details": {"gui_id": conversation["gui_id"], "slot_id": slot["slot_id"],
                                "workflow_type": selected}, "events": []}
        env = load_or_create_environment(self.home_dir, persist=apply)
        event = self._event(EventType.DISPATCHER_SLOT_WORKFLOW_TYPE_CHANGED,
                            environment_id=env.environment_id,
                            payload={"gui_id": conversation["gui_id"], "slot_id": slot["slot_id"],
                                     "workflow_type": selected})
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                current = self._slot(conversation["gui_id"], slot["slot_id"])
                if current.get("workflow_type") != slot.get("workflow_type"):
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "Workflow type changed concurrently; reload before updating.")
                self.continuity._emit_and_materialize([event])
        return {"action": "workflow-type", "applied": apply,
                "summary": f"{'Set' if apply and selected else 'Cleared' if apply else 'Dry-run: would set'} "
                           f"workflow type for {slot['name']!r}" + (f" to {selected}." if selected else "."),
                "details": {"gui_id": conversation["gui_id"], "slot_id": slot["slot_id"],
                            "workflow_type": selected}, "events": [event.to_dict()]}

    def reconcile_agent_number(self, *, gui: str, agent: str, agent_number: int,
                               source: str, apply: bool = True) -> dict[str, Any]:
        evidence = source.strip()
        if not evidence or len(evidence) > 500:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "Verified legacy number reconciliation requires a concise source reference.")
        if not isinstance(agent_number, int) or isinstance(agent_number, bool) or agent_number < 1:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Agent number must be a positive integer.")
        with _mutation_lock(self.home_dir) if apply else contextlib.nullcontext():
            # Do not invoke _sync here: the explicit verified import must get the
            # first chance to assign an old slot before deterministic fallback.
            self.materializer.sync_from_spools()
            conversation = self._row(
                "SELECT * FROM dispatcher_gui_conversations WHERE alias_key = ?", (gui.strip().casefold(),)
            )
            if conversation is None:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"GUI conversation not found: {gui!r}.")
            slot = self._row(
                "SELECT * FROM agent_slots WHERE gui_id = ? AND name_key = ?",
                (conversation["gui_id"], agent.strip().casefold()),
            )
            if slot is None:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Agent slot not found: {agent!r}.")
            if slot.get("agent_number") is not None:
                if int(slot["agent_number"]) == agent_number:
                    return {"action": "agent-number-reconcile", "applied": False,
                            "summary": "Agent number already matches verified evidence.",
                            "details": {"slot_id": slot["slot_id"], "agent_number": agent_number}, "events": []}
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      "An assigned agent number is permanent and cannot be replaced.")
            if self._row("SELECT 1 FROM dispatcher_agent_number_reservations WHERE gui_id = ? AND agent_number = ?",
                         (conversation["gui_id"], agent_number)):
                raise ContinuityError(ErrorCode.INVALID_INPUT, "That agent number is already reserved in this GUI.")
            env = load_or_create_environment(self.home_dir, persist=apply)
            event = self._event(EventType.DISPATCHER_AGENT_NUMBER_ASSIGNED,
                                environment_id=env.environment_id,
                                payload={"gui_id": conversation["gui_id"], "slot_id": slot["slot_id"],
                                         "agent_number": agent_number, "source": evidence})
            if apply:
                self.continuity._emit_and_materialize([event])
        return {"action": "agent-number-reconcile", "applied": apply,
                "summary": f"{'Reconciled' if apply else 'Dry-run: would reconcile'} {slot['name']!r} as #{agent_number}.",
                "details": {"slot_id": slot["slot_id"], "agent_number": agent_number, "source": evidence},
                "events": [event.to_dict()]}

    def list_slots(self, *, gui: str, active_only: bool = True) -> list[dict[str, Any]]:
        conversation = self._gui(gui)
        state_filter = "AND s.state = 'active'" if active_only else ""
        rows = self._rows(
            f"""SELECT s.*, a.provider AS current_provider, a.environment_id AS current_environment_id,
                       a.native_session_id AS current_session_id, a.provenance AS current_provenance,
                       p.launch_id AS pending_launch_id, p.provider AS pending_provider,
                       lp.name AS profile_name, lp.revision AS profile_revision,
                       lp.settings_json AS _profile_settings_json
                FROM agent_slots s
                LEFT JOIN dispatcher_launch_profiles lp ON lp.profile_id = s.profile_id
                LEFT JOIN agent_slot_activations a ON a.activation_id = (
                    SELECT cur.activation_id FROM agent_slot_activations cur
                    WHERE cur.slot_id = s.slot_id ORDER BY cur.sequence DESC LIMIT 1
                )
                LEFT JOIN dispatcher_pending_launches p ON p.launch_id = (
                    SELECT pending.launch_id FROM dispatcher_pending_launches pending
                    WHERE pending.slot_id = s.slot_id AND pending.status = 'pending'
                    ORDER BY pending.requested_at DESC, pending.launch_id DESC LIMIT 1
                )
                WHERE s.gui_id = ? {state_filter}
                ORDER BY s.last_activity_at IS NULL, s.last_activity_at DESC, s.name_key""",
            (conversation["gui_id"],),
        )
        for row in rows:
            raw_settings = row.pop("_profile_settings_json", None)
            row["profile_settings_digest"] = (
                "sha256:" + hashlib.sha256(json.dumps(json.loads(raw_settings or "{}"), sort_keys=True,
                    ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
                if row.get("profile_id") else None
            )
        return rows

    def slot_lock_path(self, slot_id: str) -> Path:
        """Canonical slot ownership lock path shared with workspace restoration."""
        return self.home_dir / _slot_lock_name(slot_id)

    def accept_managed_restoration(
        self,
        *,
        slot_id: str,
        provider: str,
        environment_id: str,
        session_id: str,
        stage: str,
        relay_id: str | None = None,
    ) -> dict[str, Any]:
        """Record distinct relay_spawned / dispatcher_accepted / provider_associated handoff stages."""
        valid_stages = {"relay_spawned", "dispatcher_accepted", "provider_associated"}
        if stage not in valid_stages:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Invalid restoration handoff stage {stage!r}.")
        with _mutation_lock(self.home_dir):
            self._sync()
            slot = self.get_slot_by_id(slot_id)
            if slot["state"] == "completed":
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Completed slots cannot accept restoration handoffs.")
            if self._row(
                "SELECT 1 FROM dispatcher_pending_launches WHERE slot_id = ? AND status = 'pending' LIMIT 1",
                (slot_id,),
            ):
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    "Slot has an unresolved pending launch; fail closed before restoration handoff.",
                )
            current = slot["current"]
            if not current or (
                current["provider"], current["environment_id"], current["native_session_id"]
            ) != (provider, environment_id, session_id):
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    "Slot selection is stale or ambiguous; restoration handoff refused.",
                )
            event = self._event(
                EventType.DISPATCHER_PROCESS_OBSERVED,
                environment_id=environment_id,
                provider=provider,
                session_id=session_id,
                payload={
                    "slot_id": slot_id,
                    "launch_id": relay_id,
                    "return_code": 0,
                    "outcome": f"restoration_{stage}",
                    "detail": f"Managed restoration stage: {stage}",
                    "native_session_id": session_id,
                    "restoration_stage": stage,
                },
            )
            self.continuity._emit_and_materialize([event])
        return {"slot_id": slot_id, "stage": stage, "provider": provider,
                "environment_id": environment_id, "native_session_id": session_id}

    def prepare_new_session_workflow(
        self,
        *,
        slot_id: str,
        launch_id: str,
        provider: str,
        environment_id: str,
        bridge: Any = None,
        workflow_selection: str | None = None,
        expected_digests: Mapping[str, str] | None = None,
        custom_instruction_path: str | None = None,
    ) -> dict[str, Any]:
        """LLMD-50/51: Discover resources and record prepared workflow provenance once for a new launch."""
        from .workflows import discover_workflow_resources, prepare_additive_workflow_init

        self._sync()
        slot = self.get_slot_by_id(slot_id)
        selection = workflow_selection if workflow_selection is not None else slot.get("workflow_type")
        env = next((e for e in self.materializer.list_environments() if e.environment_id == environment_id), None)
        runtime_kind = env.runtime_kind if env else "unknown"
        if selection is None and not custom_instruction_path:
            return prepare_additive_workflow_init(
                provider=provider,
                runtime=runtime_kind,
                is_new_session=True,
                resources=(),
                selection=None,
                custom_instruction_path=None,
            )
        active_bridge = bridge if bridge is not None else self.workflow_bridge
        resources = discover_workflow_resources(
            active_bridge,
            provider=provider,
            runtime=runtime_kind,
            selection=selection or "standard",
            expected_digests=expected_digests,
        )
        prepared = prepare_additive_workflow_init(
            provider=provider,
            runtime=runtime_kind,
            is_new_session=True,
            resources=resources,
            selection=selection,
            custom_instruction_path=custom_instruction_path,
            expected_digests=expected_digests,
        )
        with _mutation_lock(self.home_dir):
            self._sync()
            event = self._event(
                EventType.DISPATCHER_PROCESS_OBSERVED,
                environment_id=environment_id,
                provider=provider,
                payload={
                    "slot_id": slot_id,
                    "launch_id": launch_id,
                    "return_code": 0,
                    "outcome": "workflow_init_prepared" if prepared.get("applied") else "workflow_init_unsupported",
                    "delivery_state": "prepared",
                    "selection": prepared.get("selection"),
                    "provider_qualified": prepared.get("provider_qualified", False),
                    "provider_behavior_observed": prepared.get("provider_behavior_observed", False),
                    "provider_snapshot_status": prepared.get("provider_snapshot_status", "not_observable"),
                    "prompt_submitted": False,
                    "delivery_confirmed": False,
                    "provenance": prepared.get("provenance", []),
                    "resource_snapshot": prepared.get("resource_snapshot"),
                    "limitations": prepared.get("limitations", []),
                },
            )
            self.continuity._emit_and_materialize([event])
        return prepared

    def confirm_workflow_init_delivered(
        self,
        *,
        slot_id: str,
        launch_id: str,
        provider: str,
        environment_id: str,
        session_id: str | None,
        provenance: Sequence[Mapping[str, Any]],
        resource_snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        """Record confirmed delivery separately from preparation once provider launch succeeds with evidence."""
        with _mutation_lock(self.home_dir):
            self._sync()
            event = self._event(
                EventType.DISPATCHER_PROCESS_OBSERVED,
                environment_id=environment_id,
                provider=provider,
                session_id=session_id,
                payload={
                    "slot_id": slot_id,
                    "launch_id": launch_id,
                    "return_code": 0,
                    "outcome": "workflow_init_delivered",
                    "delivery_state": "delivered",
                    "prompt_submitted": True,
                    "delivery_confirmed": True,
                    "provider_qualified": False,
                    "provider_behavior_observed": False,
                    "provider_snapshot_status": "prompt submitted; effective loaded context and resume persistence unverified",
                    "provenance": list(provenance),
                    "resource_snapshot": dict(resource_snapshot or {}),
                    "native_session_id": session_id,
                },
            )
            self.continuity._emit_and_materialize([event])

    def _slot_snapshot_ro(self, *, slot_id: str | None = None, gui: str | None = None, name: str | None = None) -> dict[str, Any] | None:
        if slot_id:
            row = self._row(
                "SELECT s.*, g.alias AS gui_alias FROM agent_slots s JOIN dispatcher_gui_conversations g USING(gui_id) WHERE s.slot_id = ?",
                (slot_id,),
            )
            if row:
                history = self._history(row["slot_id"])
                return {**row, "history": history, "current": history[-1] if history else None}
        elif gui and name:
            gui_row = self._row(
                "SELECT * FROM dispatcher_gui_conversations WHERE gui_id = ? OR alias_key = ?",
                (gui, gui.strip().casefold()),
            )
            if gui_row:
                slot_row = self._row(
                    "SELECT * FROM agent_slots WHERE gui_id = ? AND (slot_id = ? OR name_key = ?)",
                    (gui_row["gui_id"], name, name.strip().casefold()),
                )
                if slot_row:
                    history = self._history(slot_row["slot_id"])
                    return {**slot_row, "gui_alias": gui_row["alias"], "history": history, "current": history[-1] if history else None}
        return None

    def resolve_runtime_identity(
        self,
        *,
        slot_id: str | None = None,
        gui: str | None = None,
        name: str | None = None,
        invoking_pid: int | None = None,
        trusted_observation: Mapping[str, Any] | None = None,
        runtime_snapshot: Any = None,
    ) -> dict[str, Any]:
        """LLMD-52: Resolve authoritative runtime identity read-only using trusted slot + runtime evidence."""
        from .runtime_discovery import ManagementState, MatchStatus, ProcessLiveness
        from .workflows import resolve_authoritative_runtime_identity

        slot = self._slot_snapshot_ro(slot_id=slot_id, gui=gui, name=name)
        observation = trusted_observation

        if observation is None and invoking_pid is not None:
            candidate_rows = self._rows(
                """SELECT s.slot_id FROM agent_slots s
                   WHERE EXISTS (SELECT 1 FROM agent_slot_activations a WHERE a.slot_id = s.slot_id)"""
            )
            candidates = [self._slot_snapshot_ro(slot_id=r["slot_id"]) for r in candidate_rows]
            candidates = [c for c in candidates if c and c.get("current")]
            keys = [
                (c["current"]["provider"], c["current"]["environment_id"], c["current"]["native_session_id"])
                for c in candidates
            ]
            obs_map = self.observe_runtime_sessions(keys) if keys else {}
            matched_slots: list[tuple[dict[str, Any], Any]] = []
            for cand in candidates:
                cur = cand["current"]
                obs = obs_map.get((cur["provider"], cur["environment_id"], cur["native_session_id"]))
                if obs is None:
                    continue
                pids = set(getattr(obs, "pids", ()) or ())
                if invoking_pid in pids:
                    matched_slots.append((cand, obs))
            if len(matched_slots) > 1:
                observation = {"conflict": True, "management": "conflict"}
                if slot is None:
                    slot = matched_slots[0][0]
            elif len(matched_slots) == 1:
                matched_slot, matched_obs = matched_slots[0]
                if slot is not None and slot["slot_id"] != matched_slot["slot_id"]:
                    observation = {"conflict": True, "slot_id": matched_slot["slot_id"], "management": "conflict"}
                else:
                    slot = matched_slot
                    observation = self._observation_from_runtime(slot, matched_obs)

        if observation is None and slot and slot.get("current"):
            current = slot["current"]
            obs = self.observe_runtime_session(
                current["provider"],
                current["environment_id"],
                current["native_session_id"],
            )
            if obs is not None:
                if (
                    obs.management == ManagementState.CONFLICT
                    or obs.process_session_match == MatchStatus.AMBIGUOUS
                    or obs.process_liveness == ProcessLiveness.AMBIGUOUS
                ):
                    observation = {"conflict": True, "slot_id": slot["slot_id"], "management": "conflict"}
                elif obs.management == ManagementState.UNMANAGED:
                    observation = {"slot_id": slot["slot_id"], "management": "unmanaged"}
                elif self._is_observed_runtime(obs):
                    observation = self._observation_from_runtime(slot, obs)
        return resolve_authoritative_runtime_identity(trusted_slot=slot, trusted_observation=observation)

    @staticmethod
    def _observation_from_runtime(slot: Mapping[str, Any], obs: Any) -> dict[str, Any]:
        current = slot.get("current") or {}
        mgmt = getattr(getattr(obs, "management", None), "value", getattr(obs, "management", "managed"))
        return {
            "slot_id": slot["slot_id"],
            "agent_number": slot.get("agent_number"),
            "agent_name": slot["name"],
            "gui_alias": slot.get("gui_alias"),
            "native_session_id": current.get("native_session_id"),
            "management": str(mgmt),
            "status": "observed",
        }

    @staticmethod
    def _is_observed_runtime(obs: Any) -> bool:
        from .runtime_discovery import ManagementState, MatchStatus, ProcessLiveness

        if obs is None:
            return False
        liveness = getattr(obs, "process_liveness", None)
        match = getattr(obs, "process_session_match", None)
        management = getattr(obs, "management", None)
        return (
            liveness == ProcessLiveness.RUNNING
            and match == MatchStatus.EXACT
            and management == ManagementState.MANAGED
        )

    def validate_handoff(
        self,
        *,
        text: str,
        slot_id: str | None = None,
        gui: str | None = None,
        name: str | None = None,
        invoking_pid: int | None = None,
        trusted_observation: Mapping[str, Any] | None = None,
        runtime_snapshot: Any = None,
    ) -> dict[str, Any]:
        """LLMD-53: Validate addressed handoff text read-only against authoritative runtime identity."""
        from .workflows import validate_addressed_handoff

        identity = self.resolve_runtime_identity(
            slot_id=slot_id,
            gui=gui,
            name=name,
            invoking_pid=invoking_pid,
            trusted_observation=trusted_observation,
            runtime_snapshot=runtime_snapshot,
        )
        validation = validate_addressed_handoff(text, authoritative_identity=identity)
        return {"identity": identity, "validation": validation}

    def reconcile_late_activity(
        self,
        *,
        slot_id: str,
        observed_events: Sequence[Mapping[str, Any]] = (),
        provider_evidence: Mapping[tuple[str, str, str], Mapping[str, Any]] | None = None,
        runtime_snapshot: Any = None,
    ) -> dict[str, Any]:
        """LLMD-54: Reconcile persisted + observed activity without letting late observations overwrite selection."""
        from .workflows import reconcile_activity_and_associations

        self._sync()
        slot = self.get_slot_by_id(slot_id)
        current = slot["current"]
        persisted_rows = self._rows(
            """SELECT event_id, event_type, provider, environment_id, native_session_id,
                      source_timestamp, observed_timestamp, payload_json, rowid
               FROM activity_events
               WHERE json_extract(payload_json, '$.slot_id') = ?
                  OR (
                      provider IS NOT NULL AND environment_id IS NOT NULL AND native_session_id IS NOT NULL
                      AND EXISTS (
                          SELECT 1 FROM agent_slot_activations a
                          WHERE a.slot_id = ?
                            AND a.provider = activity_events.provider
                            AND a.environment_id = activity_events.environment_id
                            AND a.native_session_id = activity_events.native_session_id
                      )
                  )
               ORDER BY rowid""",
            (slot_id, slot_id),
        )
        replay_events: list[dict[str, Any]] = []
        for row in persisted_rows:
            replay_events.append(
                {
                    "event_id": row["event_id"],
                    "slot_id": slot_id,
                    "provider": row["provider"],
                    "environment_id": row["environment_id"],
                    "native_session_id": row["native_session_id"],
                    "source_timestamp": row["source_timestamp"],
                    "observed_timestamp": row["observed_timestamp"],
                    "sequence": row["rowid"],
                }
            )
        replay_events.extend(dict(ev) for ev in observed_events)

        evidence = dict(provider_evidence) if provider_evidence is not None else None
        if evidence is None and current is not None:
            try:
                obs = self.observe_runtime_session(
                    current["provider"],
                    current["environment_id"],
                    current["native_session_id"],
                )
                if self._is_observed_runtime(obs):
                    evidence = {
                        (current["provider"], current["environment_id"], current["native_session_id"]): {
                            "status": "observed",
                            "pids": getattr(obs, "pids", ()),
                        }
                    }
            except Exception:
                evidence = None

        result = reconcile_activity_and_associations(replay_events, provider_evidence=evidence)
        reconciled = result["selections"].get(slot_id)
        activation_sequences = [row["sequence"] for row in slot.get("history", ())]
        if current and reconciled:
            current_identity = (current["provider"], current["environment_id"], current["native_session_id"])
            rec_identity = (reconciled["provider"], reconciled["environment_id"], reconciled["native_session_id"])
            if rec_identity != current_identity:
                return {
                    "action": "reconcile",
                    "replaced": False,
                    "selected_session_preserved": True,
                    "authoritative_activation_sequences": activation_sequences,
                    "reason": "newer_selection_preserved",
                    "current": current_identity,
                    "reconciled": reconciled,
                    "duplicates_skipped": result["duplicates_skipped"],
                    "fingerprint": result["fingerprint"],
                }
        return {
            "action": "reconcile",
            "replaced": False,
            "selected_session_preserved": True,
            "authoritative_activation_sequences": activation_sequences,
            "reconciled": reconciled,
            "duplicates_skipped": result["duplicates_skipped"],
            "fingerprint": result["fingerprint"],
        }

    def check_or_consume_restoration_reservation(
        self,
        *,
        slot_id: str,
        provider: str | None = None,
        environment_id: str | None = None,
        session_id: str | None = None,
        reservation_id: str | None = None,
        reservation_token: str | None = None,
        checkpoint_id: str | None = None,
        queue_entry_id: str | None = None,
        attempt: int | None = None,
        launch_id: str | None = None,
        pane_id: str | None = None,
        consume: bool = True,
    ) -> Any:
        """Consume Agent #3's restoration reservation when provided, or fail closed if one is active."""
        try:
            from .workspace_ownership import RestorationReservationStore
        except ImportError:
            return None
        store = RestorationReservationStore(self.home_dir)
        lease_path = store._lease_path(slot_id)
        if lease_path.exists():
            lease = store.get_active_lease(slot_id)
            owns_lease = bool(
                reservation_id
                and lease
                and lease.get("checkpoint_id") == checkpoint_id
                and lease.get("queue_entry_id") == queue_entry_id
            )
            if not owns_lease:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Slot {slot_id!r} has an active workspace preparation lease; competing operation refused.",
                    {"slot_id": slot_id},
                )
        if reservation_id:
            if not reservation_token:
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Restoration reservation token is required.")
            if not all((provider, environment_id, session_id, checkpoint_id, attempt, launch_id, pane_id)):
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    "Exact checkpoint, attempt, provider, environment, session, launch, and pane identity are required to consume a restoration reservation.",
                )
            reservation = store.get_active_for_slot(slot_id)
            if reservation is None or reservation.reservation_id != reservation_id:
                raise ContinuityError(ErrorCode.ASSOCIATION_CONFLICT, "Active restoration reservation identity changed.")
            if (
                reservation.reservation_token != reservation_token
                or reservation.checkpoint_id != checkpoint_id
                or reservation.queue_entry_id != queue_entry_id
                or reservation.attempt != attempt
                or reservation.provider != provider
                or reservation.environment_id != environment_id
                or reservation.native_session_id != session_id
                or reservation.launch_id not in {None, launch_id}
                or reservation.pane_id not in {None, pane_id}
            ):
                raise ContinuityError(ErrorCode.ASSOCIATION_CONFLICT, "Restoration reservation correlation mismatch.")
            if not consume:
                return reservation
            return store.consume_reservation_locked(
                reservation_id,
                reservation_token=reservation_token,
                checkpoint_id=checkpoint_id,
                queue_entry_id=queue_entry_id,
                attempt=attempt,
                slot_id=slot_id,
                provider=provider,
                native_session_id=session_id,
                environment_id=environment_id,
                launch_id=launch_id,
                pane_id=pane_id,
            )
        active = store.get_active_for_slot(slot_id)
        if active is not None:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Slot {slot_id!r} has an active restoration reservation ({active.reservation_id}); competing launch refused.",
            )
        return None

    def transfer_slot(
        self,
        *,
        gui: str,
        name: str,
        destination_gui: str,
        apply: bool = False,
    ) -> dict[str, Any]:
        """LLMD-55: Atomically transfer an immutable slot between GUI memberships."""
        source_gui = self._gui(gui)
        dest_gui = self._gui(destination_gui)
        if source_gui["gui_id"] == dest_gui["gui_id"]:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Source and destination GUIs must be distinct.")
        slot = self._slot(source_gui["gui_id"], name)
        if self._row(
            "SELECT 1 FROM dispatcher_pending_launches WHERE slot_id = ? AND status = 'pending' LIMIT 1",
            (slot["slot_id"],),
        ):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Cannot transfer a slot with an unresolved pending launch.")
        if self._row(
            "SELECT 1 FROM agent_slots WHERE gui_id = ? AND name_key = ? LIMIT 1",
            (dest_gui["gui_id"], slot["name"].casefold()),
        ):
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                f"Destination GUI {dest_gui['alias']!r} already has an agent named {slot['name']!r}.",
            )
        env = load_or_create_environment(self.home_dir, persist=apply)
        dest_number = self._next_agent_number(dest_gui["gui_id"])
        event = self._event(
            EventType.DISPATCHER_SLOT_TRANSFERRED,
            environment_id=env.environment_id,
            payload={
                "slot_id": slot["slot_id"],
                "source_gui_id": source_gui["gui_id"],
                "destination_gui_id": dest_gui["gui_id"],
                "destination_agent_number": dest_number,
                "source_reserved_number": slot.get("agent_number"),
            },
        )
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                latest_slot = self._slot(source_gui["gui_id"], slot["slot_id"])
                if self._row(
                    "SELECT 1 FROM dispatcher_pending_launches WHERE slot_id = ? AND status = 'pending' LIMIT 1",
                    (latest_slot["slot_id"],),
                ):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Cannot transfer a slot with an unresolved pending launch.")
                if self._row(
                    "SELECT 1 FROM agent_slots WHERE gui_id = ? AND name_key = ? LIMIT 1",
                    (dest_gui["gui_id"], latest_slot["name"].casefold()),
                ):
                    raise ContinuityError(
                        ErrorCode.INVALID_INPUT,
                        f"Destination GUI {dest_gui['alias']!r} already has an agent named {latest_slot['name']!r}.",
                    )
                dest_number = self._next_agent_number(dest_gui["gui_id"])
                event.payload["destination_agent_number"] = dest_number
                history = self._history(latest_slot["slot_id"])
                current = history[-1] if history else None
                with contextlib.ExitStack() as held_locks:
                    held_locks.enter_context(self._hold_slot_lock(latest_slot["slot_id"]))
                    if current:
                        held_locks.enter_context(self._hold_session_lock(
                            current["provider"], current["environment_id"], current["native_session_id"]
                        ))
                    self.continuity._emit_and_materialize([event])
        return {
            "action": "slot-transfer",
            "applied": apply,
            "summary": f"{'Transferred' if apply else 'Dry-run: would transfer'} {slot['name']!r} from {source_gui['alias']!r} to {dest_gui['alias']!r} as #{dest_number}.",
            "details": {
                "slot_id": slot["slot_id"],
                "source_gui_id": source_gui["gui_id"],
                "destination_gui_id": dest_gui["gui_id"],
                "destination_agent_number": dest_number,
                "source_reserved_number": slot.get("agent_number"),
            },
            "events": [event.to_dict()],
        }

    def _hold_slot_lock(self, slot_id: str, *, wait_for_metadata_contention: bool = False):
        key = (str(self.home_dir.resolve()), slot_id)
        if key in _HELD_SLOT_LOCKS.get():
            return contextlib.nullcontext()

        @contextlib.contextmanager
        def _guarded_slot_operation():
            lock_context = _slot_runtime_lock(self.home_dir, slot_id, blocking=False)
            try:
                lock_context.__enter__()
            except ContinuityError:
                if not wait_for_metadata_contention:
                    raise
                snapshot = self._slot_snapshot_ro(slot_id=slot_id)
                current = snapshot.get("current") if snapshot else None
                if current:
                    observed = self.observe_runtime_session(
                        current["provider"], current["environment_id"], current["native_session_id"]
                    )
                    if self._is_observed_runtime(observed):
                        raise ContinuityError(
                            ErrorCode.INVALID_INPUT,
                            f"Agent slot {slot_id} has an exactly observed active provider session.",
                        ) from None
                lock_context = _slot_runtime_lock(self.home_dir, slot_id, blocking=True)
                lock_context.__enter__()
            try:
                try:
                    from .workspace_ownership import RestorationReservationStore

                    reservations = RestorationReservationStore(self.home_dir)
                    active = reservations.get_active_for_slot(slot_id)
                    if active is not None:
                        raise ContinuityError(
                            ErrorCode.ASSOCIATION_CONFLICT,
                            f"Slot {slot_id!r} has an active restoration reservation; competing operation refused.",
                            {"slot_id": slot_id},
                        )
                    if reservations._lease_path(slot_id).exists():
                        raise ContinuityError(
                            ErrorCode.ASSOCIATION_CONFLICT,
                            f"Slot {slot_id!r} has an active workspace preparation lease; competing operation refused.",
                            {"slot_id": slot_id},
                        )
                except ImportError:
                    pass
                yield
            finally:
                lock_context.__exit__(None, None, None)

        return _guarded_slot_operation()

    def _hold_session_lock(self, provider: str, environment_id: str, session_id: str):
        lock_name = _session_lock_name(provider, environment_id, session_id)
        if (str(self.home_dir.resolve()), lock_name) in _HELD_SESSION_LOCKS.get():
            return contextlib.nullcontext()
        return _session_runtime_lock_ctx(self.home_dir, provider, environment_id, session_id, blocking=False)

    def _check_slot_available(self, slot_id: str) -> None:
        with self._hold_slot_lock(slot_id):
            pass

    def _check_session_available(self, provider: str, environment_id: str, session_id: str) -> None:
        with self._hold_session_lock(provider, environment_id, session_id):
            pass

    def observe_runtime_sessions(self, requests: Sequence[tuple[str, str, str]]) -> dict[tuple[str, str, str], Any]:
        """Observe exact sessions in batches using one fresh snapshot per local environment."""
        unique_requests = list(dict.fromkeys(requests))
        if not unique_requests:
            return {}
        environments = {env.environment_id: env for env in self.materializer.list_environments()}
        from .environment import detect_runtime_kind
        from .runtime_discovery import PsutilProcessEnumerator, RuntimeDiscovery, SessionKey

        local_runtime = detect_runtime_kind()
        grouped: dict[str, list[tuple[str, str, str]]] = {}
        results: dict[tuple[str, str, str], Any] = {}
        for item in unique_requests:
            provider, env_id, session_id = item
            environment = environments.get(env_id)
            if (environment is None or not environment_is_locally_owned(self.home_dir, environment)
                    or environment.runtime_kind != local_runtime):
                results[item] = None
                continue
            grouped.setdefault(env_id, []).append(item)

        for env_id, items in grouped.items():
            environment = environments[env_id]
            observer = RuntimeDiscovery(
                process_enumerator=PsutilProcessEnumerator(),
                runtime_kind=environment.runtime_kind,
                environment_id=environment.environment_id,
            )
            snapshot = observer.capture_snapshot()
            for start in range(0, len(items), 256):
                chunk = items[start:start + 256]
                keys = [
                    SessionKey(
                        provider=provider,
                        native_session_id=session_id,
                        environment_id=environment.environment_id,
                        runtime_kind=environment.runtime_kind,
                    )
                    for provider, _, session_id in chunk
                ]
                observations = observer.observe_many(keys, snapshot=snapshot)
                for item, observation in zip(chunk, observations, strict=True):
                    results[item] = observation
        return results

    def observe_runtime_session(self, provider: str, environment_id: str, session_id: str):
        """Observe one exact session through the shared, read-only runtime-discovery API."""
        return self.observe_runtime_sessions([(provider, environment_id, session_id)]).get(
            (provider, environment_id, session_id)
        )

    def get_slot(self, *, gui: str, name: str) -> dict[str, Any]:
        conversation = self._gui(gui)
        slot = self._slot(conversation["gui_id"], name)
        history = self._history(slot["slot_id"])
        return {**slot, "gui_alias": conversation["alias"], "history": history,
                "current": history[-1] if history else None}

    def get_slot_by_id(self, slot_id: str) -> dict[str, Any]:
        self._sync()
        row = self._row(
            "SELECT g.alias FROM agent_slots s JOIN dispatcher_gui_conversations g USING(gui_id) WHERE s.slot_id = ?",
            (slot_id,),
        )
        if row is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Agent slot not found: {slot_id!r}.")
        return self.get_slot(gui=row["alias"], name=slot_id)

    def get_pending_launch(self, launch_id: str) -> dict[str, Any]:
        self._sync()
        launch = self._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?", (launch_id,))
        if launch is None or launch["status"] != "pending":
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Pending launch not found: {launch_id!r}.")
        return self._with_captured_bootstrap_id(launch)

    def _with_captured_bootstrap_id(self, launch: dict[str, Any]) -> dict[str, Any]:
        captured = self._rows(
            """SELECT DISTINCT native_session_id FROM activity_events
               WHERE event_type = ? AND json_extract(payload_json, '$.launch_id') = ?
                 AND json_extract(payload_json, '$.outcome') = 'bootstrap_id_captured'
                 AND native_session_id IS NOT NULL""",
            (EventType.DISPATCHER_PROCESS_OBSERVED.value, launch["launch_id"]),
        )
        reserved = self._rows(
            """SELECT DISTINCT native_session_id FROM activity_events
               WHERE event_type = ? AND json_extract(payload_json, '$.launch_id') = ?
                 AND json_extract(payload_json, '$.outcome') = 'claude_session_id_reserved'""",
            (EventType.DISPATCHER_PROCESS_OBSERVED.value, launch["launch_id"]),
        )
        reserved_count = self._row(
            """SELECT COUNT(*) AS event_count FROM activity_events
               WHERE event_type = ? AND json_extract(payload_json, '$.launch_id') = ?
                 AND json_extract(payload_json, '$.outcome') = 'claude_session_id_reserved'""",
            (EventType.DISPATCHER_PROCESS_OBSERVED.value, launch["launch_id"]),
        )
        claude_claims = self._rows(
            """SELECT native_session_id FROM activity_events
               WHERE event_type = ? AND json_extract(payload_json, '$.launch_id') = ?
                 AND json_extract(payload_json, '$.outcome') = 'claude_launch_claimed'""",
            (EventType.DISPATCHER_PROCESS_OBSERVED.value, launch["launch_id"]),
        )
        reserved_ids = {item["native_session_id"] for item in reserved if item["native_session_id"]}
        claim_ids = {item["native_session_id"] for item in claude_claims if item["native_session_id"]}
        reserved_conflict = (len(reserved_ids) > 1
                             or len(reserved_ids) != int((reserved_count or {}).get("event_count", 0)))
        claim_conflict = len(claim_ids) > 1 or len(claim_ids) != len(claude_claims)
        return {**launch, "captured_session_id": captured[0]["native_session_id"] if len(captured) == 1 else None,
                "captured_session_conflict": len(captured) > 1,
                "reserved_session_id": next(iter(reserved_ids)) if len(reserved_ids) == 1 else None,
                "reserved_session_conflict": reserved_conflict,
                "claude_launch_attempted": bool(claude_claims),
                "claude_launch_claim_conflict": claim_conflict}

    def reserve_claude_session_id(self, *, launch_id: str, slot_id: str) -> str:
        """Durably allocate exactly one UUID for a pending Claude launch."""
        with _mutation_lock(self.home_dir):
            self._sync()
            launch = self._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?", (launch_id,))
            if launch is None or launch["status"] != "pending" or launch["slot_id"] != slot_id:
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Claude launch is no longer pending for this agent.")
            if launch["provider"] != "claude":
                raise ContinuityError(ErrorCode.INVALID_INPUT, "UUID reservation is only valid for Claude launches.")
            if launch.get("failure_detail"):
                raise ContinuityError(ErrorCode.INVALID_INPUT, "This launch has unresolved failure evidence and cannot be retried.")
            evidence = self._with_captured_bootstrap_id(launch)
            if evidence["reserved_session_conflict"] or evidence["claude_launch_claim_conflict"]:
                raise ContinuityError(ErrorCode.ASSOCIATION_CONFLICT,
                                      "Claude launch UUID reservation or launch claim is ambiguous; inspect `llmd doctor`.")
            if evidence["reserved_session_id"]:
                return evidence["reserved_session_id"]

            session_id = str(uuid.uuid4())
            event = self._event(
                EventType.DISPATCHER_PROCESS_OBSERVED,
                environment_id=launch["environment_id"], provider="claude", session_id=session_id,
                payload={"slot_id": slot_id, "launch_id": launch_id, "return_code": 0,
                         "outcome": "claude_session_id_reserved",
                         "detail": "UUID reserved; native creation and resumability are unconfirmed.",
                         "native_session_id": session_id},
            )
            self.continuity._emit_and_materialize([event])
            return session_id

    def claim_claude_launch(self, *, launch_id: str, slot_id: str, session_id: str) -> None:
        """Atomically claim the single interactive spawn attempt for a reserved UUID."""
        with _mutation_lock(self.home_dir):
            self._sync()
            launch = self._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?", (launch_id,))
            if launch is None or launch["status"] != "pending" or launch["slot_id"] != slot_id:
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Claude launch is no longer pending for this agent.")
            evidence = self._with_captured_bootstrap_id(launch)
            if (launch["provider"] != "claude" or evidence["reserved_session_conflict"]
                    or evidence["reserved_session_id"] != session_id):
                raise ContinuityError(ErrorCode.ASSOCIATION_CONFLICT,
                                      "Claude launch UUID reservation changed; no provider process was started.")
            if evidence["claude_launch_attempted"] or evidence["claude_launch_claim_conflict"]:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      "This Claude launch has already been attempted; inspect its exact UUID or recover it without relaunching.")
            event = self._event(
                EventType.DISPATCHER_PROCESS_OBSERVED,
                environment_id=launch["environment_id"], provider="claude", session_id=session_id,
                payload={"slot_id": slot_id, "launch_id": launch_id, "return_code": 0,
                         "outcome": "claude_launch_claimed",
                         "detail": "One-shot claim persisted before the Claude interactive process spawn.",
                         "native_session_id": session_id},
            )
            self.continuity._emit_and_materialize([event])

    def current_working_directory(self, slot: dict[str, Any]) -> str:
        current = slot.get("current")
        if current:
            local_env = load_or_create_environment(self.home_dir, persist=False)
            native = self.materializer.get_session(current["provider"], current["environment_id"], current["native_session_id"])
            if current["environment_id"] == local_env.environment_id and native and native.cwd_native:
                return native.cwd_native
        return str(Path.cwd())

    def latest_session_for_provider(self, *, gui: str, name: str, provider: str) -> dict[str, Any] | None:
        sessions = self.sessions_for_provider(gui=gui, name=name, provider=provider)
        return sessions[0] if sessions else None

    def sessions_for_provider(self, *, gui: str, name: str, provider: str) -> list[dict[str, Any]]:
        provider_name = self.continuity._validate_provider(provider)
        view = self.get_slot(gui=gui, name=name)
        seen: set[tuple[str, str, str]] = set()
        out: list[dict[str, Any]] = []
        for activation in reversed(view["history"]):
            key = (activation["provider"], activation["environment_id"], activation["native_session_id"])
            if activation["provider"] == provider_name and key not in seen:
                seen.add(key)
                out.append(activation)
        return out

    def begin_launch(
        self, *, gui: str, name: str, provider: str, cwd: str | None = None,
        environment_selector: str | None = None, expected_current: tuple[str, str, str] | None = None,
        check_current: bool = False, reactivate: bool = False, apply: bool = False
    ) -> dict[str, Any]:
        conversation = self._gui(gui)
        slot = self._slot(conversation["gui_id"], name)
        provider_name = self.continuity._validate_provider(provider)
        if slot["state"] == "completed":
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "Completed agents require an explicit lifecycle change before starting.")
        if slot["state"] == "inactive" and not reactivate:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
        local_env = load_or_create_environment(self.home_dir, persist=apply)
        env = resolve_environment_selector(environment_selector, self.materializer.list_environments(), local_env)
        if provider_name == "claude" and env.runtime_kind == "wsl":
            raise ContinuityError(
                ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                "New Claude sessions in WSL are not qualified: LLMD cannot verify the exact transcript in that runtime. "
                "Use a Windows environment or explicitly attach a WSL Claude session after verifying its ID.",
            )
        launch_id = generate_id("launch")
        event = self._event(
            EventType.DISPATCHER_LAUNCH_REQUESTED,
            environment_id=env.environment_id,
            provider=provider_name,
            payload={"launch_id": launch_id, "slot_id": slot["slot_id"], "cwd": cwd},
        )
        events = []
        if slot["state"] == "inactive" and reactivate:
            events.append(self._event(EventType.DISPATCHER_SLOT_STATE_CHANGED, environment_id=env.environment_id,
                                      payload={"slot_id": slot["slot_id"], "state": "active"}))
        events.append(event)
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                latest_slot = self._slot(conversation["gui_id"], slot["slot_id"])
                if latest_slot["state"] == "completed":
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "Completed agents require an explicit lifecycle change before starting.")
                if latest_slot["state"] == "inactive" and not reactivate:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "This agent is inactive; pass --reactivate before switching providers.")
                if latest_slot["state"] == "inactive" and reactivate:
                    events = [self._event(EventType.DISPATCHER_SLOT_STATE_CHANGED, environment_id=env.environment_id,
                                          payload={"slot_id": slot["slot_id"], "state": "active"}), event]
                current = self._history(slot["slot_id"])
                current_key = ((current[-1]["provider"], current[-1]["environment_id"],
                                current[-1]["native_session_id"]) if current else None)
                if check_current and current_key != expected_current:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "Agent selection changed while provider switch was prepared; retry.")
                pending = self._row("SELECT 1 FROM dispatcher_pending_launches WHERE slot_id = ? AND status = 'pending'",
                                    (slot["slot_id"],))
                if pending:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "A launch is already pending for this agent; inspect `llmd pending` before retrying.")
            with contextlib.ExitStack() as held_locks:
                    held_locks.enter_context(self._hold_slot_lock(slot["slot_id"]))
                    if current:
                        held_locks.enter_context(self._hold_session_lock(
                            current[-1]["provider"], current[-1]["environment_id"], current[-1]["native_session_id"]
                        ))
                    environment_events = self.continuity._ensure_environment_event(
                        env, self.materializer.list_environments(), event.observed_timestamp
                    )
                    self.continuity._emit_and_materialize([*environment_events, *events])
        return {
            "action": "launch-request",
            "applied": apply,
            "summary": (
                f"{'Created' if apply else 'Dry-run: would create'} pending {provider_name} launch for {slot['name']}. "
                "A new session uses one short model initialization turn to capture its exact native ID, then resumes that ID interactively."
            ),
            "details": {"launch_id": launch_id, "slot_id": slot["slot_id"], "provider": provider_name,
                        "environment_id": env.environment_id, "cwd": cwd, "status": "pending"},
            "events": [item.to_dict() for item in events],
        }

    def prepare_start(
        self,
        *,
        gui: str,
        name: str,
        provider: str,
        cwd: str | None = None,
        environment_selector: str | None = None,
        reactivate: bool = False,
        defer_reactivate: bool = False,
        expected_current: tuple[str, str, str] | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        """Atomically plan/register a GUI and slot and request one new launch."""
        gui_name = gui.strip()
        agent_name = name.strip()
        if not gui_name or len(gui_name) > 120 or not agent_name or len(agent_name) > 120:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "GUI and agent names must contain 1–120 characters.")
        provider_name = self.continuity._validate_provider(provider)
        self._sync()
        local_env = load_or_create_environment(self.home_dir, persist=apply)
        env = resolve_environment_selector(environment_selector, self.materializer.list_environments(), local_env)
        if provider_name == "claude" and env.runtime_kind == "wsl":
            raise ContinuityError(
                ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                "New Claude sessions in WSL are not qualified: LLMD cannot verify the exact transcript in that runtime. "
                "Use a Windows environment or explicitly attach a WSL Claude session after verifying its ID.",
            )
        conversation = self._row(
            "SELECT * FROM dispatcher_gui_conversations WHERE alias_key = ?", (gui_name.casefold(),)
        )
        slot = (self._row("SELECT * FROM agent_slots WHERE gui_id = ? AND name_key = ?",
                          (conversation["gui_id"], agent_name.casefold())) if conversation else None)
        if slot and slot["state"] == "completed":
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Completed agents require an explicit lifecycle change before starting.")
        if slot and slot["state"] == "inactive" and not (reactivate or defer_reactivate):
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
        initial_history = self._history(slot["slot_id"]) if slot else []
        initial_current = ((initial_history[-1]["provider"], initial_history[-1]["environment_id"],
                            initial_history[-1]["native_session_id"]) if initial_history else None)
        if initial_current != expected_current:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Agent selection changed while start was prepared; retry.")

        gui_id = conversation["gui_id"] if conversation else generate_id("gui")
        slot_id = slot["slot_id"] if slot else generate_id("slot")
        launch_id = generate_id("launch")
        now = now_utc_iso()
        events: list[EventEnvelope] = []
        if not conversation:
            events.append(self._event(EventType.DISPATCHER_GUI_REGISTERED, environment_id=env.environment_id,
                                      payload={"gui_id": gui_id, "alias": gui_name, "alias_key": gui_name.casefold()},
                                      timestamp=now))
        if not slot:
            events.append(self._event(EventType.DISPATCHER_SLOT_CREATED, environment_id=env.environment_id,
                                      payload={"slot_id": slot_id, "gui_id": gui_id, "name": agent_name,
                                               "name_key": agent_name.casefold()}, timestamp=now))
        if slot and slot["state"] == "inactive" and reactivate and not defer_reactivate:
            events.append(self._event(EventType.DISPATCHER_SLOT_STATE_CHANGED, environment_id=env.environment_id,
                                      payload={"slot_id": slot_id, "state": "active"}, timestamp=now))
        events.append(self._event(EventType.DISPATCHER_LAUNCH_REQUESTED, environment_id=env.environment_id,
                                  provider=provider_name,
                                  payload={"launch_id": launch_id, "slot_id": slot_id, "cwd": cwd}, timestamp=now))
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                latest_conversation = self._row(
                    "SELECT * FROM dispatcher_gui_conversations WHERE alias_key = ?", (gui_name.casefold(),)
                )
                latest_slot = (self._row("SELECT * FROM agent_slots WHERE gui_id = ? AND name_key = ?",
                                         (latest_conversation["gui_id"], agent_name.casefold()))
                               if latest_conversation else None)
                if (latest_conversation or {}).get("gui_id") != (conversation or {}).get("gui_id"):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "GUI registration changed while start was prepared; retry.")
                if (latest_slot or {}).get("slot_id") != (slot or {}).get("slot_id"):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Agent registration changed while start was prepared; retry.")
                if latest_slot:
                    if latest_slot["state"] == "completed":
                        raise ContinuityError(ErrorCode.INVALID_INPUT, "Completed agents require an explicit lifecycle change before starting.")
                    if latest_slot["state"] == "inactive" and not (reactivate or defer_reactivate):
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
                    current = self._history(latest_slot["slot_id"])
                    current_key = ((current[-1]["provider"], current[-1]["environment_id"],
                                    current[-1]["native_session_id"]) if current else None)
                    if current_key != expected_current:
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Agent selection changed while start was prepared; retry.")
                    pending = self._row("SELECT 1 FROM dispatcher_pending_launches WHERE slot_id = ? AND status = 'pending'",
                                        (latest_slot["slot_id"],))
                    if pending:
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "A launch is already pending for this agent; inspect `llmd pending` before retrying.")
                with contextlib.ExitStack() as held_locks:
                    if latest_slot:
                        held_locks.enter_context(self._hold_slot_lock(latest_slot["slot_id"]))
                        if current:
                            held_locks.enter_context(self._hold_session_lock(
                                current[-1]["provider"], current[-1]["environment_id"], current[-1]["native_session_id"]
                            ))
                    env_now = load_or_create_environment(self.home_dir, persist=True)
                    if env_now.environment_id != local_env.environment_id:
                        raise ContinuityError(ErrorCode.INVALID_INPUT, "Runtime environment changed while start was prepared; retry.")
                    if not latest_slot:
                        slot_event = next(item for item in events
                                          if item.event_type == EventType.DISPATCHER_SLOT_CREATED.value)
                        slot_event.payload["agent_number"] = self._next_agent_number(gui_id)
                    env_events = self.continuity._ensure_environment_event(
                        env, self.materializer.list_environments(), now
                    )
                    self.continuity._emit_and_materialize([*env_events, *events])
        registration_summary = []
        if conversation is None:
            registration_summary.append(f"{'Registered' if apply else 'Would register'} GUI {gui_name!r}")
        if slot is None:
            registration_summary.append(f"{'created' if apply else 'would create'} agent slot {agent_name!r}")
        summary_prefix = "; ".join(registration_summary)
        summary_text = ((f"{summary_prefix}; " if summary_prefix else "")
                        + f"{'Created' if apply else 'Dry-run: would create'} pending {provider_name} launch for {agent_name}. "
                        + "A new session uses one short initialization turn to capture its exact native ID.")
        return {
            "action": "launch-request", "applied": apply,
            "summary": summary_text,
            "details": {"launch_id": launch_id, "slot_id": slot_id, "provider": provider_name,
                        "environment_id": env.environment_id, "cwd": cwd, "status": "pending",
                        "gui_created": conversation is None, "slot_created": slot is None,
                        "agent_number": (self._row("SELECT agent_number FROM agent_slots WHERE slot_id = ?", (slot_id,)) or {}).get("agent_number") if apply else (self._next_agent_number(gui_id) if slot is None else slot.get("agent_number"))},
            "events": [event.to_dict() for event in events],
        }

    def list_pending_launches(self, *, gui: str | None = None) -> list[dict[str, Any]]:
        self._sync()
        if gui:
            conversation = self._gui(gui)
            launches = self._rows(
                """SELECT l.*, s.name AS agent_name, g.alias AS gui_alias
                   FROM dispatcher_pending_launches l JOIN agent_slots s USING(slot_id)
                   JOIN dispatcher_gui_conversations g USING(gui_id)
                   WHERE g.gui_id = ? AND l.status = 'pending' ORDER BY l.requested_at""",
                (conversation["gui_id"],),
            )
        else:
            launches = self._rows("SELECT * FROM dispatcher_pending_launches WHERE status = 'pending' ORDER BY requested_at")
        return [self._with_captured_bootstrap_id(launch) for launch in launches]

    def mark_launch_failed(self, *, launch_id: str, detail: str, apply: bool = True) -> dict[str, Any]:
        self._sync()
        pending = self._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?", (launch_id,))
        if pending is None or pending["status"] != "pending":
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"No pending launch {launch_id!r}.")
        event = self._event(
            EventType.DISPATCHER_LAUNCH_FAILED,
            environment_id=pending["environment_id"],
            provider=pending["provider"],
            payload={"launch_id": launch_id, "detail": detail},
        )
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                pending_now = self._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?", (launch_id,))
                if pending_now is None or pending_now["status"] != "pending":
                    raise ContinuityError(ErrorCode.INVALID_INPUT, f"No pending launch {launch_id!r}.")
                self.continuity._emit_and_materialize([event])
        return {"action": "launch-failed", "applied": apply, "summary": "Marked pending launch as failed.",
                "details": {"launch_id": launch_id, "status": "failed"}, "events": [event.to_dict()]}

    def recover_captured_launch(self, *, gui: str, name: str, apply: bool = False) -> dict[str, Any]:
        """Resolve a pending launch only when its exact bootstrap session ID was durably captured."""
        conversation = self._row("SELECT * FROM dispatcher_gui_conversations WHERE alias_key = ? OR gui_id = ?",
                                 (gui.strip().casefold(), gui.strip()))
        if conversation is None:
            raise ContinuityError(ErrorCode.WORKFLOW_NOT_FOUND, f"GUI conversation not found: {gui!r}.")
        slot = self._row("SELECT * FROM agent_slots WHERE gui_id = ? AND (slot_id = ? OR name_key = ?)",
                         (conversation["gui_id"], name.strip(), name.strip().casefold()))
        if slot is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Agent slot not found: {name!r}.")
        current_history = self._history(slot["slot_id"])
        expected_current = current_history[-1] if current_history else None
        pending = self._row("""SELECT * FROM dispatcher_pending_launches
                             WHERE slot_id = ? ORDER BY requested_at DESC, launch_id DESC LIMIT 1""", (slot["slot_id"],))
        if pending is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "No pending launch exists for this agent.")
        if pending["status"] == "resolved":
            return {"action": "recover", "applied": False, "status": "already_recovered",
                    "summary": "This captured launch is already resolved; no metadata changed.",
                    "details": {"launch_id": pending["launch_id"]}}
        if pending["status"] != "pending":
            raise ContinuityError(ErrorCode.INVALID_INPUT, "The latest launch is not pending; no recovery was applied.")
        pending = self._with_captured_bootstrap_id(pending)
        session_id = pending.get("captured_session_id")
        provenance = "dispatcher_recovery"
        runtime_process_match = False
        if (not session_id and not pending.get("captured_session_conflict")
                and pending.get("provider") == "claude"):
            reserved_id = pending.get("reserved_session_id")
            adapter = self.continuity.adapters.get("claude")
            evidence = None
            evidence_error: ContinuityError | None = None
            try:
                evidence = adapter.get_session_metadata(reserved_id) if reserved_id and adapter else None
            except ContinuityError as exc:
                evidence_error = exc
            if evidence:
                session_id = reserved_id
                provenance = "claude_transcript_recovery"
            elif reserved_id:
                observation = self.observe_runtime_session("claude", pending["environment_id"], reserved_id)
                runtime_process_match = bool(
                    observation
                    and observation.process_session_match.value == "exact"
                    and observation.process_liveness.value == "running"
                    and observation.session_identity_state.value == "reserved"
                    and not observation.identity_conflict
                    and not observation.evidence_conflict
                )
                if runtime_process_match:
                    session_id = reserved_id
                    provenance = "claude_exact_runtime_process"
                elif evidence_error:
                    raise evidence_error
        if not session_id or pending.get("captured_session_conflict") or pending.get("reserved_session_conflict"):
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                "Recovery is unresolved: no exact session identity with provider evidence was found. Inspect provider state and use llmd attach with a verified ID.")
        environments = self.materializer.list_environments()
        env = next((item for item in environments if item.environment_id == pending["environment_id"]), None)
        if env is None or not environment_is_locally_owned(self.home_dir, env):
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                "Recovery refused because runtime ownership cannot be established for this host and environment.")
        if not apply:
            return {"action": "recover", "applied": False, "status": "preview",
                    "summary": f"Would associate captured {pending['provider']} session {session_id} and resolve pending launch {pending['launch_id']}; no provider will be launched.",
                    "details": {"launch_id": pending["launch_id"], "session_id": session_id}}
        with _mutation_lock(self.home_dir):
            self._sync()
            latest = self._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ? AND status = 'pending'",
                               (pending["launch_id"],))
            if latest is None:
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Pending launch changed concurrently; inspect `llmd doctor` and retry recovery.")
            captured_now = self._with_captured_bootstrap_id(latest)
            if provenance in {"claude_transcript_recovery", "claude_exact_runtime_process"}:
                adapter = self.continuity.adapters.get("claude")
                if (captured_now.get("reserved_session_id") != session_id
                        or captured_now.get("reserved_session_conflict")):
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "Claude UUID reservation changed; recovery was not applied.")
                if provenance == "claude_transcript_recovery":
                    try:
                        evidence = adapter.get_session_metadata(session_id) if adapter else None
                    except ContinuityError:
                        evidence = None
                    if not evidence:
                        observation = self.observe_runtime_session("claude", latest["environment_id"], session_id)
                        runtime_process_match = bool(
                            observation
                            and observation.process_session_match.value == "exact"
                            and observation.process_liveness.value == "running"
                            and observation.session_identity_state.value == "reserved"
                            and not observation.identity_conflict
                            and not observation.evidence_conflict
                        )
                        if not runtime_process_match:
                            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                "Claude transcript evidence is unavailable and the exact reserved process is no longer observed; recovery was not applied.")
                        provenance = "claude_exact_runtime_process"
                else:
                    observation = self.observe_runtime_session("claude", latest["environment_id"], session_id)
                    runtime_process_match = bool(
                        observation
                        and observation.process_session_match.value == "exact"
                        and observation.process_liveness.value == "running"
                        and observation.session_identity_state.value == "reserved"
                        and not observation.identity_conflict
                        and not observation.evidence_conflict
                    )
                    if not runtime_process_match:
                        adapter_evidence = None
                        with contextlib.suppress(ContinuityError):
                            adapter_evidence = adapter.get_session_metadata(session_id) if adapter else None
                        if not adapter_evidence:
                            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                "Exact Claude process evidence ended and transcript evidence is unavailable; recovery was not applied.")
                        provenance = "claude_transcript_recovery"
            elif captured_now.get("captured_session_id") != session_id or captured_now.get("captured_session_conflict"):
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Captured session metadata changed; recovery was not applied.")
            slot = self._slot(conversation["gui_id"], slot["slot_id"])
            history = self._history(slot["slot_id"])
            current = history[-1] if history else None
            expected_key = ((expected_current["provider"], expected_current["environment_id"], expected_current["native_session_id"])
                            if expected_current else None)
            current_key = ((current["provider"], current["environment_id"], current["native_session_id"])
                           if current else None)
            if current_key != expected_key:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                    "Agent selection changed while recovery was prepared; no metadata was overwritten. Inspect doctor and retry.")
            current_is_target = current and (current["provider"], current["environment_id"], current["native_session_id"]) == (
                pending["provider"], env.environment_id, session_id)
            live_claude_process = provenance == "claude_exact_runtime_process"
            if not live_claude_process and pending["provider"] == "claude" and provenance == "claude_transcript_recovery":
                obs = self.observe_runtime_session("claude", env.environment_id, session_id)
                live_claude_process = bool(
                    obs
                    and obs.process_session_match.value == "exact"
                    and obs.process_liveness.value == "running"
                    and obs.session_identity_state.value == "reserved"
                    and not obs.identity_conflict
                    and not obs.evidence_conflict
                )
            with contextlib.ExitStack() as held_locks:
                if current and not current_is_target:
                    held_locks.enter_context(self._hold_session_lock(
                        current["provider"], current["environment_id"], current["native_session_id"]
                    ))
                if not live_claude_process:
                    held_locks.enter_context(self._hold_slot_lock(slot["slot_id"]))
                    held_locks.enter_context(self._hold_session_lock(
                        pending["provider"], env.environment_id, session_id
                    ))
                now = now_utc_iso()
                events: list[EventEnvelope] = []
                known_envs = self.materializer.list_environments()
                events.extend(self.continuity._ensure_environment_event(env, known_envs, now))
                if not self.materializer.get_session(pending["provider"], env.environment_id, session_id):
                    events.append(self._event(EventType.SESSION_REGISTERED, environment_id=env.environment_id,
                        provider=pending["provider"], session_id=session_id, timestamp=now,
                        payload={"environment": env.to_dict(), "cwd_native": pending.get("cwd"),
                                 "cwd_canonical": normalize_path_canonical(pending.get("cwd")),
                                 "repository_identity": normalize_repo_identity(pending.get("cwd")),
                                 "first_observed_at": now, "last_seen_at": now, "metadata_source": provenance}))
                same = current and (current["provider"], current["environment_id"], current["native_session_id"]) == (
                    pending["provider"], env.environment_id, session_id)
                if not same:
                    activation_id = generate_id("act")
                    events.append(self._event(EventType.DISPATCHER_SESSION_ACTIVATED,
                        environment_id=env.environment_id, provider=pending["provider"], session_id=session_id,
                        timestamp=now, payload={"slot_id": slot["slot_id"], "activation_id": activation_id,
                            "sequence": (current["sequence"] if current else 0) + 1, "provenance": provenance}))
                events.append(self._event(EventType.DISPATCHER_LAUNCH_RESOLVED,
                    environment_id=env.environment_id, provider=pending["provider"], session_id=session_id,
                    payload={"launch_id": pending["launch_id"], "native_session_id": session_id}))
                base = datetime.now(UTC)
                events = [replace(event,
                    source_timestamp=(base + timedelta(microseconds=index + 1)).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                    observed_timestamp=(base + timedelta(microseconds=index + 1)).isoformat(timespec="microseconds").replace("+00:00", "Z"))
                    for index, event in enumerate(events)]
                self.continuity._emit_and_materialize(events)
        return {"action": "recover", "applied": True, "status": "recovered",
                "summary": f"Associated exact {pending['provider']} session {session_id} and resolved pending launch. No provider was launched.",
                "details": {"launch_id": pending["launch_id"], "session_id": session_id,
                            "activation_added": not bool(current and same), "provenance": provenance,
                            "association_state": "confirmed",
                            "identity_state": "reserved" if provenance == "claude_exact_runtime_process" else "exact",
                            "resumability": "unverified" if provenance == "claude_exact_runtime_process" else (
                                "transcript_observed" if provenance == "claude_transcript_recovery" else "provider_captured"
                            )}}

    def record_process_observation(
        self, *, slot_id: str, launch_id: str | None, return_code: int, outcome: str,
        detail: str | None = None, native_session_id: str | None = None,
        session_identity: tuple[str, str, str] | None = None,
    ) -> None:
        slot = self.get_slot_by_id(slot_id)
        current = slot["current"]
        pending = None
        if launch_id:
            self._sync()
            pending = self._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?", (launch_id,))
            if pending is None:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Launch record not found: {launch_id!r}.")
        if pending:
            provider = pending["provider"]
            environment_id = pending["environment_id"]
            session_id = native_session_id
        elif session_identity:
            provider, environment_id, session_id = session_identity
        else:
            provider = current["provider"] if current else None
            environment_id = current["environment_id"] if current else None
            session_id = native_session_id or (current["native_session_id"] if current else None)
        if not provider or not environment_id:
            return
        with _mutation_lock(self.home_dir):
            self._sync()
            if launch_id and self._row(
                """SELECT 1 FROM activity_events WHERE event_type = ?
                   AND json_extract(payload_json, '$.launch_id') = ?
                   AND json_extract(payload_json, '$.outcome') = ?
                   AND json_extract(payload_json, '$.return_code') = ?
                   AND COALESCE(json_extract(payload_json, '$.native_session_id'), '') = COALESCE(?, '') LIMIT 1""",
                (EventType.DISPATCHER_PROCESS_OBSERVED.value, launch_id, outcome, return_code, native_session_id),
            ):
                return
            event = self._event(
                EventType.DISPATCHER_PROCESS_OBSERVED,
                environment_id=environment_id,
                provider=provider,
                session_id=session_id,
                payload={"slot_id": slot_id, "launch_id": launch_id, "return_code": return_code,
                         "outcome": outcome, "detail": detail, "native_session_id": native_session_id},
            )
            self.continuity._emit_and_materialize([event])

    def record_portable_launch_context(
        self,
        *,
        slot_id: str,
        provider: str,
        environment_id: str,
        session_id: str,
        snapshot: Mapping[str, Any],
    ) -> None:
        """Persist normalized, non-secret portable context against one exact native session."""
        if not all(isinstance(value, str) and value for value in (provider, environment_id, session_id)):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Portable context snapshots require exact session identity.")
        value = dict(snapshot)
        if value.get("schema_version") != 1 or value.get("provider") != provider:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Portable context snapshot schema or provider identity is invalid.")
        try:
            json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Portable context snapshot must contain JSON-safe metadata.") from exc
        with _mutation_lock(self.home_dir):
            self._sync()
            slot = self.get_slot_by_id(slot_id)
            exact = (provider, environment_id, session_id)
            if not any((item["provider"], item["environment_id"], item["native_session_id"]) == exact
                       for item in slot.get("history", [])):
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      "Portable context snapshot does not match this slot's session history.")
            event = self._event(
                EventType.DISPATCHER_PROCESS_OBSERVED,
                environment_id=environment_id,
                provider=provider,
                session_id=session_id,
                payload={"slot_id": slot_id, "outcome": "portable_context_snapshot", "return_code": 0,
                         "native_session_id": session_id, "portable_context_snapshot": value},
            )
            self.continuity._emit_and_materialize([event])

    def get_portable_launch_context(
        self, *, slot_id: str, provider: str, environment_id: str, session_id: str,
    ) -> dict[str, Any] | None:
        """Return the newest snapshot only for the exact slot/provider/environment/native session."""
        row = self._row(
            """SELECT payload_json FROM activity_events
               WHERE event_type = ? AND provider = ? AND environment_id = ? AND native_session_id = ?
                 AND json_extract(payload_json, '$.slot_id') = ?
                 AND json_extract(payload_json, '$.outcome') = 'portable_context_snapshot'
               ORDER BY observed_timestamp DESC, event_id DESC LIMIT 1""",
            (EventType.DISPATCHER_PROCESS_OBSERVED.value, provider, environment_id, session_id, slot_id),
        )
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        snapshot = payload.get("portable_context_snapshot")
        return dict(snapshot) if isinstance(snapshot, dict) else None

    def open_request(self, *, gui: str, cwd_override: str | None = None) -> dict[str, Any]:
        """Build ordered dispatcher-side pane records; terminal geometry belongs to terminal_launcher."""
        conversation = self._gui(gui)
        slots = self.list_slots(gui=gui, active_only=True)
        panes: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        seen_sessions: set[tuple[str, str, str]] = set()
        for slot in slots:
            session_id = slot.get("current_session_id")
            provider = slot.get("current_provider")
            if slot.get("pending_launch_id"):
                unresolved.append({"slot_id": slot["slot_id"], "agent_name": slot["name"],
                                   "reason": f"pending {slot.get('pending_provider') or 'provider'} destination must be recovered before opening this slot"})
                continue
            if not session_id or not provider:
                unresolved.append({"slot_id": slot["slot_id"], "agent_name": slot["name"],
                                   "reason": "no selected native session"})
                continue
            slot_lock_state = _probe_existing_lock_file(self.home_dir / _slot_lock_name(slot["slot_id"]))
            session_lock_state = _probe_existing_lock_file(
                self.home_dir / _session_lock_name(provider, slot["current_environment_id"], session_id)
            )
            if slot_lock_state == "contended" or session_lock_state == "contended":
                unresolved.append({"slot_id": slot["slot_id"], "agent_name": slot["name"],
                                   "reason": "slot or selected session is already in use"})
                continue
            native = self.materializer.get_session(provider, slot["current_environment_id"], session_id)
            if native is None:
                unresolved.append({"slot_id": slot["slot_id"], "agent_name": slot["name"], "reason": "selected session is not materialized"})
                continue
            session_key = (provider, slot["current_environment_id"], session_id)
            if session_key in seen_sessions:
                unresolved.append({"slot_id": slot["slot_id"], "agent_name": slot["name"],
                                   "reason": "same native session is already assigned to another active slot"})
                continue
            seen_sessions.add(session_key)
            environment = next((env for env in self.materializer.list_environments()
                                if env.environment_id == slot["current_environment_id"]), None)
            adapter = self.continuity.adapters.get(provider)
            native_plan = adapter.resolve_resume_command(
                session_id,
                cwd=native.cwd_native,
                environment_id=slot["current_environment_id"],
                runtime_kind=environment.runtime_kind if environment else "",
            ) if adapter else None
            pane_cwd = cwd_override or native.cwd_native
            if environment and environment.runtime_kind == "wsl":
                from .environment import detect_runtime_kind

                if detect_runtime_kind() == "windows":
                    pane_cwd = None
            panes.append({
                "slot_id": slot["slot_id"],
                "title": slot["name"],
                "provider": provider,
                "environment_id": slot["current_environment_id"],
                "native_session_id": session_id,
                "cwd": pane_cwd,
                "provider_cwd": native.cwd_native,
                "provider_argv": native_plan.argv if native_plan else None,
                "argv": [
                    "llmd", "pane-run", "--slot-id", slot["slot_id"],
                    "--expected-provider", provider,
                    "--expected-environment", slot["current_environment_id"],
                    "--expected-session-id", session_id,
                ],
            })
        return {"gui_id": conversation["gui_id"], "gui_alias": conversation["alias"],
                "panes": panes, "unresolved": unresolved}

    def set_slot_state(self, *, gui: str, name: str, state: str, apply: bool = False) -> dict[str, Any]:
        normalized = state.strip().lower()
        if normalized not in _VALID_STATES:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Invalid slot state {state!r}.")
        conversation = self._gui(gui)
        slot = self._slot(conversation["gui_id"], name)
        if slot["state"] == normalized:
            return {"action": "slot-state", "applied": False, "summary": f"Slot is already {normalized}.",
                    "details": {"slot_id": slot["slot_id"], "state": normalized}, "events": []}
        env = load_or_create_environment(self.home_dir, persist=apply)
        event = self._event(EventType.DISPATCHER_SLOT_STATE_CHANGED, environment_id=env.environment_id,
                            payload={"slot_id": slot["slot_id"], "state": normalized})
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                latest_slot = self._slot(conversation["gui_id"], slot["slot_id"])
                if latest_slot["state"] == normalized:
                    return {"action": "slot-state", "applied": False, "summary": f"Slot is already {normalized}.",
                            "details": {"slot_id": slot["slot_id"], "state": normalized}, "events": []}
                with self._hold_slot_lock(slot["slot_id"]):
                    self.continuity._emit_and_materialize([event])
        return {"action": "slot-state", "applied": apply,
                "summary": f"{'Updated' if apply else 'Dry-run: would update'} slot {slot['name']!r} to {normalized}.",
                "details": {"slot_id": slot["slot_id"], "state": normalized}, "events": [event.to_dict()]}

    def active_review_cycle(self, *, slot_id: str) -> dict[str, Any] | None:
        self._sync()
        return self._row(
            """SELECT * FROM dispatcher_review_cycles
               WHERE status = 'active' AND (original_slot_id = ? OR reviewer_slot_id = ?)
               ORDER BY updated_at DESC LIMIT 1""",
            (slot_id, slot_id),
        )

    def open_review_cycle(self, *, slot_id: str) -> dict[str, Any] | None:
        self._sync()
        return self._row(
            """SELECT * FROM dispatcher_review_cycles
               WHERE status IN ('pending', 'active') AND (original_slot_id = ? OR reviewer_slot_id = ?)
               ORDER BY updated_at DESC LIMIT 1""",
            (slot_id, slot_id),
        )

    def record_pending_review_cycle(self, *, gui: str, cycle: dict[str, Any],
                                    expected_original: tuple[str, str, str],
                                    allow_inactive_original: bool = False, apply: bool = False) -> dict[str, Any]:
        """Persist review intent after explicit launch authorization, before provider bootstrap."""
        conversation = self._gui(gui)
        original = self._slot(conversation["gui_id"], cycle["original_slot_id"])
        reviewer = self._slot(conversation["gui_id"], cycle["reviewer_slot_id"])
        original_states = {"active", "inactive"} if allow_inactive_original else {"active"}
        if cycle.get("status") != "pending" or original["state"] not in original_states:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Pending review cycle requires an eligible original agent.")
        event = self._event(
            EventType.DISPATCHER_SLOTS_TRANSITIONED,
            environment_id=expected_original[1],
            payload={"slot_changes": [], "review_cycle": cycle},
        )
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                latest_original = self._slot(conversation["gui_id"], original["slot_id"])
                latest_history = self._history(original["slot_id"])
                latest_identity = ((latest_history[-1]["provider"], latest_history[-1]["environment_id"],
                                   latest_history[-1]["native_session_id"]) if latest_history else None)
                if latest_original["state"] not in original_states or latest_identity != expected_original:
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Original agent changed before review launch; retry.")
                if self._row("SELECT 1 FROM dispatcher_pending_launches WHERE slot_id=? AND status='pending'",
                             (reviewer["slot_id"],)) is None:
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Reviewer launch is not pending.")
                for slot_id in (original["slot_id"], reviewer["slot_id"]):
                    if self.open_review_cycle(slot_id=slot_id):
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "One of these slots already has an open review cycle.")
            with contextlib.ExitStack() as held_locks:
                    held_locks.enter_context(self._hold_slot_lock(original["slot_id"]))
                    held_locks.enter_context(self._hold_slot_lock(reviewer["slot_id"]))
                    self.continuity._emit_and_materialize([event])
        return {"action": "review-cycle", "applied": apply, "cycle": cycle,
                "summary": "Pending review cycle persisted." if apply else "Preview: review cycle not persisted.",
                "events": [event.to_dict()]}

    def transition_slots(
        self,
        *,
        gui: str,
        source_slot_id: str,
        destination_slot_id: str,
        source_state: str,
        destination_state: str,
        expected_source: tuple[str, str, str] | None = None,
        expected_destination: tuple[str, str, str] | None = None,
        review_cycle: dict[str, Any] | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        """Atomically change two slot states and optionally update one review cycle."""
        conversation = self._gui(gui)
        if source_slot_id == destination_slot_id:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "A slot cannot transition to itself.")
        source = self._slot(conversation["gui_id"], source_slot_id)
        destination = self._slot(conversation["gui_id"], destination_slot_id)

        def validate() -> tuple[dict[str, Any], dict[str, Any]]:
            latest_source = self._slot(conversation["gui_id"], source_slot_id)
            latest_destination = self._slot(conversation["gui_id"], destination_slot_id)
            for slot, expected in ((latest_source, expected_source), (latest_destination, expected_destination)):
                if expected is not None:
                    history = self._history(slot["slot_id"])
                    current = history[-1] if history else None
                    identity = ((current["provider"], current["environment_id"], current["native_session_id"])
                                if current else None)
                    if identity != expected:
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              f"Agent {slot['name']!r} session changed during transition.")
                pending = self._row(
                    "SELECT 1 FROM dispatcher_pending_launches WHERE slot_id = ? AND status = 'pending'",
                    (slot["slot_id"],),
                )
                if pending:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          f"Agent {slot['name']!r} has an unresolved provider launch.")
            source_history = self._history(source_slot_id)
            destination_history = self._history(destination_slot_id)
            if source_history and destination_history:
                source_identity = tuple(source_history[-1][key] for key in
                                        ("provider", "environment_id", "native_session_id"))
                destination_identity = tuple(destination_history[-1][key] for key in
                                             ("provider", "environment_id", "native_session_id"))
                if source_identity == destination_identity:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "Source and destination slots share the same native session.")
            return latest_source, latest_destination

        if source["gui_id"] != destination["gui_id"]:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Agent transition must stay under one GUI.")
        validate()
        now = now_utc_iso()
        event = self._event(
            EventType.DISPATCHER_SLOTS_TRANSITIONED,
            environment_id=load_or_create_environment(self.home_dir, persist=apply).environment_id,
            payload={"slot_changes": [{"slot_id": source_slot_id, "state": source_state},
                                      {"slot_id": destination_slot_id, "state": destination_state}],
                     "review_cycle": review_cycle},
            timestamp=now,
        )
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                with contextlib.ExitStack() as held_locks:
                    held_locks.enter_context(self._hold_slot_lock(source_slot_id))
                    held_locks.enter_context(self._hold_slot_lock(destination_slot_id))
                    validate()
                    self.continuity._emit_and_materialize([event])
        return {"action": "slot-transition", "applied": apply,
                "summary": "Agent transition applied." if apply else "Preview: agent transition not applied.",
                "details": {"source_slot_id": source_slot_id, "destination_slot_id": destination_slot_id},
                "events": [event.to_dict()]}

    def complete_agent_transition(
        self,
        *,
        gui: str,
        source_slot_id: str,
        destination_slot_id: str,
        provider: str,
        environment_id: str,
        session_id: str,
        source_state: str,
        destination_state: str,
        expected_source: tuple[str, str, str] | None,
        expected_destination: tuple[str, str, str] | None,
        cwd: str | None = None,
        launch_id: str | None = None,
        allow_inactive_source: bool = False,
        provenance: str = "agent_transition",
        review_cycle: dict[str, Any] | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        """Commit exact session selection, slot states, launch resolution and review link in one event."""
        conversation = self._gui(gui)
        self._slot(conversation["gui_id"], source_slot_id)
        self._slot(conversation["gui_id"], destination_slot_id)
        provider_name = self.continuity._validate_provider(provider)
        session = session_id.strip()
        if not session or source_slot_id == destination_slot_id:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Transition requires two slots and an exact native session ID.")

        def validate() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            current_source = self._slot(conversation["gui_id"], source_slot_id)
            current_destination = self._slot(conversation["gui_id"], destination_slot_id)
            source_states = {"active", "inactive"} if allow_inactive_source else {"active"}
            if current_source["state"] not in source_states or current_destination["state"] == "completed":
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      "Transition requires an eligible source and a noncompleted destination.")
            source_history = self._history(source_slot_id)
            destination_history = self._history(destination_slot_id)
            for slot, history, expected in ((current_source, source_history, expected_source),
                                            (current_destination, destination_history, expected_destination)):
                identity = ((history[-1]["provider"], history[-1]["environment_id"], history[-1]["native_session_id"])
                            if history else None)
                if identity != expected:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          f"Agent {slot['name']!r} session changed during transition.")
                pending = self._row("SELECT 1 FROM dispatcher_pending_launches WHERE slot_id=? AND status='pending'",
                                    (slot["slot_id"],))
                if pending and not (slot["slot_id"] == destination_slot_id and launch_id):
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          f"Agent {slot['name']!r} has an unresolved provider launch.")
            if not launch_id:
                target = destination_history[-1] if destination_history else None
                if not target or (target["provider"], target["environment_id"], target["native_session_id"]) != (
                        provider_name, environment_id, session):
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "Destination does not currently select the requested exact session.")
            else:
                pending = self._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id=? AND slot_id=? AND status='pending'",
                                    (launch_id, destination_slot_id))
                if not pending or (pending["provider"], pending["environment_id"]) != (provider_name, environment_id):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Pending launch does not match the destination session.")
            source_identity = (source_history[-1]["provider"], source_history[-1]["environment_id"],
                               source_history[-1]["native_session_id"]) if source_history else None
            if source_identity == (provider_name, environment_id, session):
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Source and destination cannot share a native session.")
            duplicate = self._row(
                """SELECT slot_id FROM agent_slot_activations WHERE provider=? AND environment_id=?
                   AND native_session_id=? AND slot_id NOT IN (?, ?) LIMIT 1""",
                (provider_name, environment_id, session, source_slot_id, destination_slot_id),
            )
            if duplicate:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      "Destination native session is already assigned to a different slot.")
            if review_cycle:
                if review_cycle["status"] == "active":
                    original_identity = (review_cycle["original_provider"],
                                         review_cycle["original_environment_id"],
                                         review_cycle["original_session_id"])
                    reviewer_identity = (review_cycle.get("reviewer_provider"),
                                         review_cycle.get("reviewer_environment_id"),
                                         review_cycle.get("reviewer_session_id"))
                    if (review_cycle["original_slot_id"], review_cycle["reviewer_slot_id"]) != (
                            source_slot_id, destination_slot_id):
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Review relationship does not match the transition slots.")
                    if original_identity != expected_source or reviewer_identity != (
                            provider_name, environment_id, session):
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Review relationship session identities changed during transition.")
                    existing_cycle = self._row(
                        "SELECT * FROM dispatcher_review_cycles WHERE cycle_id=?",
                        (review_cycle["cycle_id"],),
                    )
                    if existing_cycle and (existing_cycle["status"] != "pending"
                            or (existing_cycle["original_slot_id"], existing_cycle["reviewer_slot_id"]) != (
                                source_slot_id, destination_slot_id)):
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Review cycle ID is already bound to a different transition.")
                    active_cycle = self._row(
                        """SELECT cycle_id FROM dispatcher_review_cycles WHERE status='active'
                           AND cycle_id != ? AND (original_slot_id IN (?, ?) OR reviewer_slot_id IN (?, ?)) LIMIT 1""",
                        (review_cycle["cycle_id"], source_slot_id, destination_slot_id, source_slot_id, destination_slot_id),
                    )
                    if active_cycle:
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "One of these slots already has an active review cycle.")
                else:
                    active_cycle = self._row(
                        "SELECT * FROM dispatcher_review_cycles WHERE cycle_id=? AND status='active'",
                        (review_cycle["cycle_id"],),
                    )
                    if not active_cycle:
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Review cycle is no longer active; no transition was applied.")
                    if (active_cycle["reviewer_slot_id"], active_cycle["original_slot_id"]) != (
                            source_slot_id, destination_slot_id):
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Review cycle does not link these source and destination slots.")
                    if expected_source != (active_cycle["reviewer_provider"],
                                           active_cycle["reviewer_environment_id"],
                                           active_cycle["reviewer_session_id"]) or expected_destination != (
                            active_cycle["original_provider"], active_cycle["original_environment_id"],
                            active_cycle["original_session_id"]):
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Review cycle session identities changed; no transition was applied.")
            return source_history, destination_history

        validate()
        timestamp = now_utc_iso()
        destination_history = self._history(destination_slot_id)
        next_sequence = (destination_history[-1]["sequence"] if destination_history else 0) + 1
        payload = {
            "slot_changes": [{"slot_id": source_slot_id, "state": source_state},
                             {"slot_id": destination_slot_id, "state": destination_state}],
            "activation": {"activation_id": generate_id("act"), "slot_id": destination_slot_id,
                           "sequence": next_sequence, "provenance": provenance},
            "session": {"cwd_native": cwd, "cwd_canonical": normalize_path_canonical(cwd),
                        "repository_identity": normalize_repo_identity(cwd),
                        "metadata_source": "dispatcher_transition"},
            "launch_id": launch_id,
            "review_cycle": review_cycle,
        }
        event = self._event(EventType.DISPATCHER_AGENT_TRANSITION_COMPLETED,
                            environment_id=environment_id, provider=provider_name,
                            session_id=session, payload=payload, timestamp=timestamp)
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                with contextlib.ExitStack() as held_locks:
                    held_locks.enter_context(self._hold_slot_lock(source_slot_id))
                    held_locks.enter_context(self._hold_slot_lock(destination_slot_id))
                    identities = [identity for identity in (expected_source,
                                                            None if launch_id else (provider_name, environment_id, session))
                                  if identity]
                    for runtime_provider, runtime_environment, runtime_session in sorted(set(identities)):
                        held_locks.enter_context(self._hold_session_lock(
                            runtime_provider, runtime_environment, runtime_session
                        ))
                    validate()
                    latest_history = self._history(destination_slot_id)
                    payload["activation"]["sequence"] = (latest_history[-1]["sequence"] if latest_history else 0) + 1
                    payload["activation"]["activation_id"] = generate_id("act")
                    self.continuity._emit_and_materialize([event])
        return {"action": "agent-transition", "applied": apply,
                "summary": "Agent transition applied." if apply else "Preview: agent transition not applied.",
                "details": {"source_slot_id": source_slot_id, "destination_slot_id": destination_slot_id,
                            "provider": provider_name, "environment_id": environment_id,
                            "native_session_id": session, "launch_id": launch_id},
                "events": [event.to_dict()]}

    def attach_session(
        self,
        *,
        gui: str,
        name: str,
        provider: str,
        session_id: str,
        environment_selector: str | None = None,
        cwd: str | None = None,
        launch_id: str | None = None,
        expected_current: tuple[str, str, str] | None = None,
        check_current: bool = False,
        reactivate: bool = False,
        apply: bool = False,
        provenance: str = "explicit_attach",
    ) -> dict[str, Any]:
        conversation = self._gui(gui)
        slot = self._slot(conversation["gui_id"], name)
        provider_name = self.continuity._validate_provider(provider)
        session = session_id.strip()
        if not session:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Native session ID cannot be empty.")
        self._sync()
        local_env = load_or_create_environment(self.home_dir, persist=apply)
        env = resolve_environment_selector(environment_selector, self.materializer.list_environments(), local_env)
        session_row = self.materializer.get_session(provider_name, env.environment_id, session)
        history = self._history(slot["slot_id"])
        already_selected = bool(history and (
            history[-1]["provider"], history[-1]["environment_id"], history[-1]["native_session_id"]
        ) == (
            provider_name, env.environment_id, session
        ))
        if (already_selected and not launch_id and not (apply and check_current)
                and not (apply and reactivate and slot["state"] == "inactive")):
            return {"action": "attach", "applied": False, "summary": "Session is already selected for this slot.",
                    "details": {"slot_id": slot["slot_id"], "session_id": session}, "events": []}

        timestamp = now_utc_iso()
        events: list[EventEnvelope] = []
        known_envs = self.materializer.list_environments()
        env_registered = any(item.environment_id == env.environment_id for item in known_envs)
        if apply and not env_registered:
            events.append(self._event(
                EventType.ENVIRONMENT_REGISTERED, environment_id=env.environment_id,
                payload=env.to_dict(), timestamp=timestamp,
            ))
        if session_row is None:
            session_payload = {
                "environment": env.to_dict(), "cwd_native": cwd,
                "cwd_canonical": normalize_path_canonical(cwd),
                "repository_identity": normalize_repo_identity(cwd),
                "first_observed_at": timestamp, "last_seen_at": timestamp,
                "metadata_source": "dispatcher_attach",
            }
            events.append(self._event(EventType.SESSION_REGISTERED, environment_id=env.environment_id,
                                      payload=session_payload, provider=provider_name, session_id=session,
                                      timestamp=timestamp))
        sequence = (history[-1]["sequence"] if history else 0) + 1
        activation_id = generate_id("act")
        activation_time = (datetime.now(UTC) + timedelta(microseconds=2)).isoformat(timespec="microseconds").replace("+00:00", "Z")
        activation_event = self._event(
            EventType.DISPATCHER_SESSION_ACTIVATED, environment_id=env.environment_id,
            payload={"slot_id": slot["slot_id"], "activation_id": activation_id, "sequence": sequence,
                     "provenance": provenance},
            provider=provider_name, session_id=session, timestamp=activation_time,
        )
        events.append(activation_event)
        pending = None
        if launch_id:
            pending = self._row(
                "SELECT * FROM dispatcher_pending_launches WHERE launch_id = ? AND slot_id = ? AND status = 'pending'",
                (launch_id, slot["slot_id"]),
            )
            if pending is None or (pending["provider"], pending["environment_id"]) != (provider_name, env.environment_id):
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Pending launch does not match the slot, provider, and environment.")
        if pending:
            resolved_at = (datetime.now(UTC) + timedelta(microseconds=4)).isoformat(timespec="microseconds").replace("+00:00", "Z")
            events.append(self._event(
                EventType.DISPATCHER_LAUNCH_RESOLVED, environment_id=env.environment_id,
                provider=provider_name, session_id=session,
                payload={"launch_id": launch_id, "native_session_id": session}, timestamp=resolved_at,
            ))
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                if launch_id:
                    pending_now = self._row(
                        "SELECT * FROM dispatcher_pending_launches WHERE launch_id = ? AND slot_id = ? AND status = 'pending'",
                        (launch_id, slot["slot_id"]),
                    )
                    if pending_now is None:
                        raise ContinuityError(ErrorCode.INVALID_INPUT, "Pending launch was already resolved or failed.")
                current_slot = self._slot(conversation["gui_id"], slot["slot_id"])
            with contextlib.ExitStack() as held_locks:
                    held_locks.enter_context(
                        self._hold_slot_lock(current_slot["slot_id"], wait_for_metadata_contention=True)
                    )
                    if not launch_id and self._row(
                        "SELECT 1 FROM dispatcher_pending_launches WHERE slot_id = ? AND status = 'pending' LIMIT 1",
                        (current_slot["slot_id"],),
                    ):
                        raise ContinuityError(
                            ErrorCode.INVALID_INPUT,
                            "This agent has an unresolved pending launch; recover or resolve it before attaching another session.",
                        )
                    latest = self._history(current_slot["slot_id"])
                    latest_identity = ((latest[-1]["provider"], latest[-1]["environment_id"],
                                        latest[-1]["native_session_id"]) if latest else None)
                    if check_current and latest_identity != expected_current:
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Agent selection changed while provider switch was prepared; retry.")
                    if check_current and current_slot["state"] == "completed":
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "Completed agents require an explicit lifecycle change before resumption.")
                    if check_current and current_slot["state"] == "inactive" and not reactivate:
                        raise ContinuityError(ErrorCode.INVALID_INPUT,
                                              "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
                    if latest and (latest[-1]["provider"], latest[-1]["environment_id"], latest[-1]["native_session_id"]) == (
                        provider_name, env.environment_id, session
                    ):
                        if launch_id:
                            resolved_event = self._event(
                                EventType.DISPATCHER_LAUNCH_RESOLVED, environment_id=env.environment_id,
                                provider=provider_name, session_id=session,
                                payload={"launch_id": launch_id, "native_session_id": session},
                            )
                            self.continuity._emit_and_materialize([resolved_event])
                            return {"action": "attach", "applied": True,
                                    "summary": f"Completed pending launch resolution for {provider_name} session {session}.",
                                    "details": {"slot_id": slot["slot_id"], "session_id": session, "launch_id": launch_id},
                                    "events": [resolved_event.to_dict()]}
                        if reactivate and current_slot["state"] == "inactive":
                            state_event = self._event(
                                EventType.DISPATCHER_SLOT_STATE_CHANGED, environment_id=env.environment_id,
                                payload={"slot_id": slot["slot_id"], "state": "active"},
                            )
                            self.continuity._emit_and_materialize([state_event])
                            return {"action": "slot-state", "applied": True,
                                    "summary": "Reactivated the selected exact session.",
                                    "details": {"slot_id": slot["slot_id"], "state": "active"},
                                    "events": [state_event.to_dict()]}
                        return {
                            "action": "attach", "applied": False,
                            "summary": "Session became current before this request was applied.",
                            "details": {"slot_id": slot["slot_id"], "session_id": session}, "events": [],
                        }
                    try:
                        held_locks.enter_context(self._hold_session_lock(provider_name, env.environment_id, session))
                    except ContinuityError as exc:
                        raise ContinuityError(
                            ErrorCode.INVALID_INPUT,
                            f"Cannot attach target session {session} while it is in use.",
                        ) from exc
                    current = latest[-1] if latest else None
                    if current:
                        try:
                            held_locks.enter_context(self._hold_session_lock(
                                current["provider"], current["environment_id"], current["native_session_id"]
                            ))
                        except ContinuityError as exc:
                            raise ContinuityError(
                                ErrorCode.INVALID_INPUT,
                                f"Cannot change selection while current session {current['native_session_id']} is in use.",
                            ) from exc
                    if reactivate and current_slot["state"] == "inactive":
                        events.insert(0, self._event(
                            EventType.DISPATCHER_SLOT_STATE_CHANGED, environment_id=env.environment_id,
                            payload={"slot_id": slot["slot_id"], "state": "active"},
                        ))
                    next_sequence = (latest[-1]["sequence"] if latest else 0) + 1
                    sequence = next_sequence
                    activation_event.payload["sequence"] = next_sequence
                    activation_event.payload["activation_id"] = generate_id("act")
                    self.continuity._emit_and_materialize(events)
        return {"action": "attach", "applied": apply,
                "summary": f"{'Selected' if apply else 'Dry-run: would select'} {provider_name} session {session} for {slot['name']}.",
                "details": {"slot_id": slot["slot_id"], "provider": provider_name,
                            "environment_id": env.environment_id, "native_session_id": session,
                            "sequence": sequence, "launch_id": launch_id}, "events": [event.to_dict() for event in events]}

    def reconcile_claude_launch_exit(
        self,
        *,
        slot_id: str,
        launch_id: str,
        environment_id: str,
        session_id: str,
        return_code: int,
        cwd: str | None = None,
        transition_source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Idempotently reconcile eventual Claude wrapper exit with live recovery."""
        adapter = self.continuity.adapters.get("claude")
        evidence = None
        evidence_error: ContinuityError | None = None
        try:
            evidence = adapter.get_session_metadata(session_id) if adapter and session_id else None
        except ContinuityError as exc:
            evidence_error = exc

        with _mutation_lock(self.home_dir):
            self._sync()
            pending = self._row(
                "SELECT * FROM dispatcher_pending_launches WHERE launch_id = ? AND slot_id = ?",
                (launch_id, slot_id),
            )
            if pending is None:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Launch record not found: {launch_id!r}.")
            pending = self._with_captured_bootstrap_id(pending)
            if pending.get("reserved_session_id") and pending["reserved_session_id"] != session_id:
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    "Claude launch reservation changed concurrently; inspect `llmd doctor`.",
                )
            status = pending["status"]
            slot = self.get_slot_by_id(slot_id)
            current = slot["current"]
            if status == "resolved":
                if pending.get("resolved_session_id") != session_id:
                    raise ContinuityError(
                        ErrorCode.INVALID_INPUT,
                        "Pending launch resolved to a different session ID; inspect `llmd doctor`.",
                    )
                if not current or (current["provider"], current["environment_id"], current["native_session_id"]) != (
                    "claude", environment_id, session_id
                ):
                    raise ContinuityError(
                        ErrorCode.INVALID_INPUT,
                        "Agent selection changed while Claude was running; inspect `llmd doctor`.",
                    )
                return {
                    "status": "already_resolved",
                    "transcript_observed": bool(evidence),
                    "evidence_error": str(evidence_error) if evidence_error else None,
                }
            if status != "pending":
                raise ContinuityError(
                    ErrorCode.INVALID_INPUT,
                    f"Claude launch {launch_id} is {status}; inspect `llmd doctor`.",
                )

        if return_code != 0:
            return {"status": "pending_nonzero_exit", "transcript_observed": bool(evidence)}
        if not evidence:
            return {
                "status": "pending_no_transcript",
                "transcript_observed": False,
                "evidence_error": str(evidence_error) if evidence_error else None,
            }

        try:
            if transition_source:
                if transition_source.get("review_cycle"):
                    transition_source["review_cycle"].update({
                        "reviewer_provider": "claude",
                        "reviewer_environment_id": environment_id,
                        "reviewer_session_id": session_id,
                    })
                self.complete_agent_transition(
                    gui=slot["gui_alias"], source_slot_id=transition_source["slot_id"],
                    destination_slot_id=slot_id, provider="claude", environment_id=environment_id,
                    session_id=session_id,
                    source_state=transition_source.get("source_state", "inactive"),
                    destination_state=transition_source.get("destination_state", "active"),
                    expected_source=transition_source["expected_source"], expected_destination=None,
                    cwd=cwd, launch_id=launch_id,
                    provenance=transition_source.get("provenance", "agent_transition"),
                    allow_inactive_source=transition_source.get("allow_inactive_source", False),
                    review_cycle=transition_source.get("review_cycle"), apply=True,
                )
            else:
                self.attach_session(
                    gui=slot["gui_alias"], name=slot["name"], provider="claude", session_id=session_id,
                    environment_selector=environment_id, cwd=cwd, launch_id=launch_id, apply=True,
                    provenance="claude_transcript_verified",
                )
        except ContinuityError as exc:
            with _mutation_lock(self.home_dir):
                self._sync()
                latest = self._row(
                    "SELECT * FROM dispatcher_pending_launches WHERE launch_id = ? AND slot_id = ?",
                    (launch_id, slot_id),
                )
                if latest and latest["status"] == "resolved" and latest.get("resolved_session_id") == session_id:
                    latest_slot = self.get_slot_by_id(slot_id)
                    latest_current = latest_slot["current"]
                    if latest_current and (
                        latest_current["provider"], latest_current["environment_id"], latest_current["native_session_id"]
                    ) == ("claude", environment_id, session_id):
                        return {"status": "already_resolved", "transcript_observed": True, "evidence_error": None}
                if latest and latest["status"] == "pending":
                    self.mark_launch_failed(
                        launch_id=launch_id,
                        detail=f"Claude transcript exists for {session_id}, but association failed: {exc}",
                        apply=True,
                    )
            raise
        return {"status": "resolved", "transcript_observed": True, "evidence_error": None}
