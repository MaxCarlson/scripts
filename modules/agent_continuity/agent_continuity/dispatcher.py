"""Named GUI-conversation and agent-slot registry built on continuity events."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .environment import environment_is_locally_owned, load_or_create_environment, resolve_environment_selector
from .errors import ContinuityError, ErrorCode
from .identifiers import generate_id, normalize_path_canonical, normalize_repo_identity, now_utc_iso
from .models import EventEnvelope, EventType
from .service import ADAPTER_VERSION, SCHEMA_EVENT_VERSION, ContinuityService

_VALID_STATES = {"active", "inactive", "completed"}


@contextlib.contextmanager
def _mutation_lock(home_dir: Path, lock_name: str = "dispatcher.lock", *, blocking: bool = True) -> Iterator[None]:
    """Serialize sequence allocation and spool appends across dispatcher processes."""
    lock_path = home_dir / lock_name
    lock_path.parent.mkdir(parents=True, exist_ok=True)
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
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as exc:
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Session is already in use.") from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class DispatcherService:
    """Durable dispatcher operations sharing the existing continuity spool and index."""

    def __init__(self, continuity: ContinuityService | None = None, home_dir: Path | str | None = None) -> None:
        if continuity is not None and home_dir is not None:
            raise ValueError("Pass either a ContinuityService or home_dir, not both.")
        self.continuity = continuity or ContinuityService(home_dir)
        self.materializer = self.continuity.materializer
        self.home_dir = self.continuity.home_dir

    def _sync(self) -> None:
        if self.continuity._can_write_sqlite():
            self.materializer.sync_from_spools()

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
        if status not in {"running", "exited", "failed", "interrupted"}:
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
                events.append(self._event(EventType.DISPATCHER_SLOT_CREATED, environment_id=env.environment_id,
                    payload={'slot_id': slot_id, 'gui_id': gui_id, 'name': name, 'name_key': name.casefold()},
                    timestamp=timestamp))
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
                for event in [*env_events, *events]:
                    self.continuity._emit_and_materialize([event])
        return {'action': 'register', 'applied': bool(apply and events), 'events': [e.to_dict() for e in events],
                'details': {'gui_id': gui_id, 'slot_id': slot_id},
                'summary': ('Registered' if apply and events else 'Dry-run: would register' if events else 'Already registered') + f' {gui!r}' + (f' / {name!r}' if name else '') + '.'}

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
            "SELECT slot_id, name FROM agent_slots WHERE gui_id = ? AND name_key = ?",
            (conversation["gui_id"], clean.casefold()),
        )
        if existing:
            return {"action": "slot-create", "applied": False, "summary": "Agent slot already exists.",
                    "details": {"slot_id": existing["slot_id"], "existing_name": existing["name"]}, "events": []}
        slot_id = generate_id("slot")
        env = load_or_create_environment(self.home_dir, persist=apply)
        event = self._event(
            EventType.DISPATCHER_SLOT_CREATED,
            environment_id=env.environment_id,
            payload={"slot_id": slot_id, "gui_id": conversation["gui_id"], "name": clean, "name_key": clean.casefold()},
        )
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                if self._row("SELECT 1 FROM agent_slots WHERE gui_id = ? AND name_key = ?", (conversation["gui_id"], clean.casefold())):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, f"Agent name {clean!r} was registered concurrently.")
                self.continuity._emit_and_materialize([event])
        return {"action": "slot-create", "applied": apply,
                "summary": f"{'Created' if apply else 'Dry-run: would create'} agent slot {clean!r}.",
                "details": {"slot_id": slot_id, "gui_id": conversation["gui_id"], "name": clean},
                "events": [event.to_dict()]}

    def list_slots(self, *, gui: str, active_only: bool = True) -> list[dict[str, Any]]:
        conversation = self._gui(gui)
        state_filter = "AND s.state = 'active'" if active_only else ""
        return self._rows(
            f"""SELECT s.*, a.provider AS current_provider, a.environment_id AS current_environment_id,
                       a.native_session_id AS current_session_id, a.provenance AS current_provenance,
                       p.launch_id AS pending_launch_id, p.provider AS pending_provider
                FROM agent_slots s
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
        return {**launch, "captured_session_id": captured[0]["native_session_id"] if len(captured) == 1 else None,
                "captured_session_conflict": len(captured) > 1}

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
                if current:
                    key = hashlib.sha256(
                        f"{current[-1]['provider']}\0{current[-1]['environment_id']}\0{current[-1]['native_session_id']}".encode()
                    ).hexdigest()[:24]
                    with _mutation_lock(self.home_dir, f"session-{key}.lock", blocking=False):
                        pass
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
                    if current:
                        lock_key = hashlib.sha256(
                            f"{current[-1]['provider']}\0{current[-1]['environment_id']}\0{current[-1]['native_session_id']}".encode()
                        ).hexdigest()[:24]
                        with _mutation_lock(self.home_dir, f"session-{lock_key}.lock", blocking=False):
                            pass
                env_now = load_or_create_environment(self.home_dir, persist=True)
                if env_now.environment_id != local_env.environment_id:
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Runtime environment changed while start was prepared; retry.")
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
                        "gui_created": conversation is None, "slot_created": slot is None},
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
        import hashlib

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
        if not session_id or pending.get("captured_session_conflict"):
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                "Recovery is unresolved: no single exact bootstrap session ID was captured. Inspect provider state and use llmd attach with a verified ID.")
        environments = self.materializer.list_environments()
        env = next((item for item in environments if item.environment_id == pending["environment_id"]), None)
        if env is None or not environment_is_locally_owned(self.home_dir, env):
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                "Recovery refused because runtime ownership cannot be established for this host and environment.")
        key = hashlib.sha256(f"{pending['provider']}\0{pending['environment_id']}\0{session_id}".encode()).hexdigest()[:24]
        lock_name = f"session-{key}.lock"
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
            if captured_now.get("captured_session_id") != session_id or captured_now.get("captured_session_conflict"):
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
            if current and not current_is_target:
                ckey = hashlib.sha256(f"{current['provider']}\0{current['environment_id']}\0{current['native_session_id']}".encode()).hexdigest()[:24]
                with _mutation_lock(self.home_dir, f"session-{ckey}.lock", blocking=False):
                    pass
            with _mutation_lock(self.home_dir, lock_name, blocking=False):
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
                                 "first_observed_at": now, "last_seen_at": now, "metadata_source": "dispatcher_recovery"}))
                same = current and (current["provider"], current["environment_id"], current["native_session_id"]) == (
                    pending["provider"], env.environment_id, session_id)
                if not same:
                    activation_id = generate_id("act")
                    events.append(self._event(EventType.DISPATCHER_SESSION_ACTIVATED,
                        environment_id=env.environment_id, provider=pending["provider"], session_id=session_id,
                        timestamp=now, payload={"slot_id": slot["slot_id"], "activation_id": activation_id,
                            "sequence": (current["sequence"] if current else 0) + 1, "provenance": "dispatcher_recovery"}))
                events.append(self._event(EventType.DISPATCHER_LAUNCH_RESOLVED,
                    environment_id=env.environment_id, provider=pending["provider"], session_id=session_id,
                    payload={"launch_id": pending["launch_id"], "native_session_id": session_id}))
                base = datetime.now(UTC)
                events = [replace(event,
                    source_timestamp=(base + timedelta(microseconds=index + 1)).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                    observed_timestamp=(base + timedelta(microseconds=index + 1)).isoformat(timespec="microseconds").replace("+00:00", "Z"))
                    for index, event in enumerate(events)]
                for event in events:
                    self.continuity._emit_and_materialize([event])
        return {"action": "recover", "applied": True, "status": "recovered",
                "summary": f"Associated captured session {session_id} and resolved pending launch. No provider was launched.",
                "details": {"launch_id": pending["launch_id"], "session_id": session_id,
                            "activation_added": not bool(current and same)}}

    def record_process_observation(
        self, *, slot_id: str, launch_id: str | None, return_code: int, outcome: str,
        detail: str | None = None, native_session_id: str | None = None,
        session_identity: tuple[str, str, str] | None = None,
    ) -> None:
        slot = self.get_slot_by_id(slot_id)
        current = slot["current"]
        pending = self.get_pending_launch(launch_id) if launch_id else None
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
        event = self._event(
            EventType.DISPATCHER_PROCESS_OBSERVED,
            environment_id=environment_id,
            provider=provider,
            session_id=session_id,
            payload={"slot_id": slot_id, "launch_id": launch_id, "return_code": return_code,
                     "outcome": outcome, "detail": detail, "native_session_id": native_session_id},
        )
        with _mutation_lock(self.home_dir):
            self.continuity._emit_and_materialize([event])

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
            if not session_id or not provider:
                reason = f"native {slot['pending_provider']} session identity pending" if slot.get("pending_launch_id") else "no selected native session"
                unresolved.append({"slot_id": slot["slot_id"], "agent_name": slot["name"], "reason": reason})
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
                "argv": ["llmd", "pane-run", "--slot-id", slot["slot_id"]],
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
                validate()
                identities = [identity for identity in (expected_source,
                                                        None if launch_id else (provider_name, environment_id, session))
                              if identity]
                for runtime_provider, runtime_environment, runtime_session in sorted(set(identities)):
                    lock_key = hashlib.sha256(
                        f"{runtime_provider}\0{runtime_environment}\0{runtime_session}".encode()
                    ).hexdigest()[:24]
                    with _mutation_lock(self.home_dir, f"session-{lock_key}.lock", blocking=False):
                        pass
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
        if (already_selected and not (apply and check_current)
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
                current = latest[-1] if latest else None
                if current:
                    import hashlib

                    lock_key = hashlib.sha256(
                        f"{current['provider']}\0{current['environment_id']}\0{current['native_session_id']}".encode()
                    ).hexdigest()[:24]
                    try:
                        with _mutation_lock(self.home_dir, f"session-{lock_key}.lock", blocking=False):
                            pass
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
                for event in events:
                    self.continuity._emit_and_materialize([event])
        return {"action": "attach", "applied": apply,
                "summary": f"{'Selected' if apply else 'Dry-run: would select'} {provider_name} session {session} for {slot['name']}.",
                "details": {"slot_id": slot["slot_id"], "provider": provider_name,
                            "environment_id": env.environment_id, "native_session_id": session,
                            "sequence": sequence, "launch_id": launch_id}, "events": [event.to_dict() for event in events]}
