"""Named GUI-conversation and agent-slot registry built on continuity events."""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .environment import load_or_create_environment, resolve_environment_selector
from .errors import ContinuityError, ErrorCode
from .identifiers import generate_id, normalize_path_canonical, normalize_repo_identity, now_utc_iso
from .models import EventEnvelope, EventType
from .service import ADAPTER_VERSION, SCHEMA_EVENT_VERSION, ContinuityService

_VALID_STATES = {"active", "inactive", "completed"}


@contextlib.contextmanager
def _mutation_lock(home_dir: Path, lock_name: str = "dispatcher.lock") -> Iterator[None]:
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

            deadline = time.monotonic() + 10.0
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ContinuityError(
                            ErrorCode.METADATA_INACCESSIBLE,
                            "Timed out waiting for dispatcher registry lock.",
                        ) from None
                    time.sleep(0.02)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
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
            raise ContinuityError(ErrorCode.INVALID_INPUT, "GUI and agent names must contain 1–120 characters.")
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
                if (current['provider'], current['environment_id'], current['native_session_id']) != (
                    provider, env.environment_id, session_id
                ) and not select:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "A different session is selected; pass --select to change it.")
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
        environment_selector: str | None = None, apply: bool = False
    ) -> dict[str, Any]:
        conversation = self._gui(gui)
        slot = self._slot(conversation["gui_id"], name)
        provider_name = self.continuity._validate_provider(provider)
        local_env = load_or_create_environment(self.home_dir, persist=apply)
        env = resolve_environment_selector(environment_selector, self.materializer.list_environments(), local_env)
        launch_id = generate_id("launch")
        event = self._event(
            EventType.DISPATCHER_LAUNCH_REQUESTED,
            environment_id=env.environment_id,
            provider=provider_name,
            payload={"launch_id": launch_id, "slot_id": slot["slot_id"], "cwd": cwd},
        )
        if apply:
            with _mutation_lock(self.home_dir):
                self._sync()
                environment_events = self.continuity._ensure_environment_event(
                    env, self.materializer.list_environments(), event.observed_timestamp
                )
                self.continuity._emit_and_materialize([*environment_events, event])
        return {
            "action": "launch-request",
            "applied": apply,
            "summary": (
                f"{'Created' if apply else 'Dry-run: would create'} pending {provider_name} launch for {slot['name']}. "
                "A new session uses one short model initialization turn to capture its exact native ID, then resumes that ID interactively."
            ),
            "details": {"launch_id": launch_id, "slot_id": slot["slot_id"], "provider": provider_name,
                        "environment_id": env.environment_id, "cwd": cwd, "status": "pending"},
            "events": [event.to_dict()],
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

    def record_process_observation(
        self, *, slot_id: str, launch_id: str | None, return_code: int, outcome: str,
        detail: str | None = None, native_session_id: str | None = None,
    ) -> None:
        slot = self.get_slot_by_id(slot_id)
        current = slot["current"]
        pending = self.get_pending_launch(launch_id) if launch_id else None
        provider = pending["provider"] if pending else (current["provider"] if current else None)
        environment_id = pending["environment_id"] if pending else (current["environment_id"] if current else None)
        session_id = native_session_id or (None if pending else (current["native_session_id"] if current else None))
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
        if history and (history[-1]["provider"], history[-1]["environment_id"], history[-1]["native_session_id"]) == (
            provider_name, env.environment_id, session
        ):
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
                if latest and (latest[-1]["provider"], latest[-1]["environment_id"], latest[-1]["native_session_id"]) == (
                    provider_name, env.environment_id, session
                ):
                    return {
                        "action": "attach", "applied": False,
                        "summary": "Session became current before this request was applied.",
                        "details": {"slot_id": slot["slot_id"], "session_id": session}, "events": [],
                    }
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
