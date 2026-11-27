"""Durable restoration reservation and atomic ownership-transfer protocol (LLMD-43/44).

Coordinates slot-level exclusion using Agent #1's canonical slot lock
(`home_dir / f"slot-{slot_id}.lock"`) without holding the OS file lock across
child process execution (avoiding parent-holds-lock / child-acquires-lock deadlocks),
while allowing the child dispatcher to acquire `slot-<slot_id>.lock` once, consume
the reservation via `consume_reservation_locked(...)`, and retain that lock for
the duration of provider execution and exit reconciliation.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ContinuityError, ErrorCode
from .events import atomic_write_json
from .identifiers import generate_id, now_utc_iso

RESERVATION_SCHEMA_VERSION = 2

ACTIVE_RESERVATION_STATES = frozenset({"reserved", "submitted", "ambiguous"})


def canonical_slot_lock_path(home_dir: Path, slot_id: str) -> Path:
    """Return Agent #1's canonical slot lock path: `<home_dir>/slot-<slot_id>.lock`."""
    return Path(home_dir) / f"slot-{slot_id}.lock"


@contextlib.contextmanager
def acquire_canonical_slot_lock(
    home_dir: Path,
    slot_id: str,
    *,
    blocking: bool = False,
    timeout_seconds: float = 5.0,
) -> Iterator[None]:
    """Acquire `<home_dir>/slot-<slot_id>.lock` for reservation/metadata transitions."""
    lock_path = canonical_slot_lock_path(home_dir, slot_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    stream = lock_path.open("a+b")
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if not blocking or time.monotonic() >= deadline:
                    raise ContinuityError(
                        ErrorCode.ASSOCIATION_CONFLICT,
                        f"Slot {slot_id!r} lock is currently held by another operation.",
                        {"slot_id": slot_id, "lock_path": str(lock_path)},
                    ) from exc
                time.sleep(0.02)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                with contextlib.suppress(OSError):
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                with contextlib.suppress(OSError):
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


@dataclass(frozen=True, slots=True)
class RestorationReservation:
    """Durable, exact-session restoration reservation for atomic ownership transfer."""

    reservation_id: str
    reservation_token: str = field(repr=False)
    schema_version: int
    checkpoint_id: str
    queue_entry_id: str | None
    attempt: int
    slot_id: str
    provider: str
    native_session_id: str
    environment_id: str
    state: str
    created_at: str
    gui_id: str | None = None
    runtime_kind: str | None = None
    launch_id: str | None = None
    pane_id: str | None = None
    operator_id: str | None = None
    consumed_at: str | None = None
    consumer_pid: int | None = None
    provider_pid: int | None = None
    dispatcher_ownership_acknowledged: bool = False
    exact_association_confirmed: bool = False
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize reservation metadata without exposing the secret reservation_token."""
        data = asdict(self)
        data.pop("reservation_token", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RestorationReservation:
        return cls(
            reservation_id=str(data["reservation_id"]),
            reservation_token=str(data["reservation_token"]),
            schema_version=int(data.get("schema_version", RESERVATION_SCHEMA_VERSION)),
            checkpoint_id=str(data["checkpoint_id"]),
            queue_entry_id=str(data["queue_entry_id"]) if data.get("queue_entry_id") is not None else None,
            attempt=int(data.get("attempt", 1)),
            slot_id=str(data["slot_id"]),
            provider=str(data["provider"]),
            native_session_id=str(data["native_session_id"]),
            environment_id=str(data["environment_id"]),
            state=str(data["state"]),
            created_at=str(data["created_at"]),
            gui_id=str(data["gui_id"]) if data.get("gui_id") is not None else None,
            runtime_kind=str(data["runtime_kind"]) if data.get("runtime_kind") is not None else None,
            launch_id=str(data["launch_id"]) if data.get("launch_id") is not None else None,
            pane_id=str(data["pane_id"]) if data.get("pane_id") is not None else None,
            operator_id=str(data["operator_id"]) if data.get("operator_id") is not None else None,
            consumed_at=str(data["consumed_at"]) if data.get("consumed_at") is not None else None,
            consumer_pid=int(data["consumer_pid"]) if data.get("consumer_pid") is not None else None,
            provider_pid=int(data["provider_pid"]) if data.get("provider_pid") is not None else None,
            dispatcher_ownership_acknowledged=bool(data.get("dispatcher_ownership_acknowledged", False)),
            exact_association_confirmed=bool(data.get("exact_association_confirmed", False)),
            note=str(data["note"]) if data.get("note") is not None else None,
        )


def _require_non_empty(value: str | None, field_name: str) -> str:
    if not value or not str(value).strip():
        raise ContinuityError(
            ErrorCode.ASSOCIATION_CONFLICT,
            f"Missing required restoration identity field: {field_name}.",
            {"field": field_name},
        )
    return str(value)


class RestorationReservationStore:
    """Atomic store for exact-session restoration reservations under `<home_dir>/restoration_reservations/`."""

    def __init__(self, home_dir: Path) -> None:
        self.home_dir = Path(home_dir)
        self.reservations_dir = self.home_dir / "restoration_reservations"

    def _record_path(self, reservation_id: str) -> Path:
        return self.reservations_dir / f"{reservation_id}.json"

    def _active_slot_path(self, slot_id: str) -> Path:
        return self.reservations_dir / f"slot-{slot_id}.active.json"

    def _lease_path(self, slot_id: str) -> Path:
        return self.reservations_dir / f"slot-{slot_id}.lease.json"

    def get_active_lease(self, slot_id: str) -> dict[str, Any] | None:
        """Read-only inspection of an active preparation lease for `slot_id`."""
        lease_path = self._lease_path(slot_id)
        if not lease_path.exists():
            return None
        try:
            payload = json.loads(lease_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Preparation lease for slot {slot_id!r} is corrupt or unreadable: {exc}",
                {"slot_id": slot_id},
            ) from exc
        if not isinstance(payload, dict) or not payload.get("lease_token"):
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Preparation lease for slot {slot_id!r} is malformed.",
                {"slot_id": slot_id},
            )
        return payload

    def get_active_for_slot(self, slot_id: str) -> RestorationReservation | None:
        """Read-only check for an active restoration reservation blocking competing operations."""
        active_path = self._active_slot_path(slot_id)
        if not active_path.exists():
            return None
        try:
            payload = json.loads(active_path.read_text(encoding="utf-8"))
            res = RestorationReservation.from_dict(payload)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Active restoration reservation for slot {slot_id!r} is corrupt or unreadable: {exc}",
                {"slot_id": slot_id},
            ) from exc
        # Reconcile against the authoritative record in case a crash occurred between
        # writing the record update and updating/removing the active slot marker.
        rec_path = self._record_path(res.reservation_id)
        if rec_path.exists():
            rec = self.get_reservation(res.reservation_id)
            if rec.state in ACTIVE_RESERVATION_STATES:
                return rec
            return None
        if res.state in ACTIVE_RESERVATION_STATES:
            return res
        return None

    def ensure_slot_available_locked(self, slot_id: str) -> None:
        """Fail closed if `slot_id` has an active reservation or preparation lease (caller holds lock)."""
        active = self.get_active_for_slot(slot_id)
        if active is not None:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Slot {slot_id!r} is reserved for restoration {active.reservation_id!r} (state={active.state}).",
                {"slot_id": slot_id, "reservation_id": active.reservation_id, "state": active.state},
            )
        lease = self.get_active_lease(slot_id)
        if lease is not None:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Slot {slot_id!r} has an active restoration preparation lease ({lease.get('lease_token')!r}).",
                {"slot_id": slot_id, "lease_token": lease.get("lease_token"), "pid": lease.get("pid")},
            )

    def ensure_slot_available(self, slot_id: str, *, blocking: bool = False) -> None:
        """Acquire `slot-<slot_id>.lock` and verify no active reservation or preparation lease exists."""
        with acquire_canonical_slot_lock(self.home_dir, slot_id, blocking=blocking):
            self.ensure_slot_available_locked(slot_id)

    def get_reservation(self, reservation_id: str) -> RestorationReservation:
        path = self._record_path(reservation_id)
        if not path.exists():
            raise ContinuityError(
                ErrorCode.SESSION_NOT_FOUND,
                f"Restoration reservation {reservation_id!r} was not found.",
                {"reservation_id": reservation_id},
            )
        try:
            return RestorationReservation.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ContinuityError(
                ErrorCode.MATERIALIZER_FAILED,
                f"Restoration reservation {reservation_id!r} is corrupt: {exc}",
                {"reservation_id": reservation_id},
            ) from exc

    def create_reservation(
        self,
        *,
        checkpoint_id: str,
        queue_entry_id: str | None,
        attempt: int,
        slot_id: str,
        provider: str,
        native_session_id: str,
        environment_id: str,
        gui_id: str | None = None,
        runtime_kind: str | None = None,
        operator_id: str | None = None,
    ) -> RestorationReservation:
        """Atomically create a durable restoration reservation under `slot-<slot_id>.lock`."""
        _require_non_empty(checkpoint_id, "checkpoint_id")
        _require_non_empty(slot_id, "slot_id")
        _require_non_empty(provider, "provider")
        _require_non_empty(native_session_id, "native_session_id")
        _require_non_empty(environment_id, "environment_id")
        if int(attempt) < 1:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "attempt must be >= 1.")

        with acquire_canonical_slot_lock(self.home_dir, slot_id, blocking=False):
            existing = self.get_active_for_slot(slot_id)
            if existing is not None:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Slot {slot_id!r} already has active restoration reservation {existing.reservation_id!r} "
                    f"(state={existing.state}).",
                    {"slot_id": slot_id, "reservation_id": existing.reservation_id, "state": existing.state},
                )
            res = RestorationReservation(
                reservation_id=generate_id("rsv"),
                reservation_token=secrets.token_hex(16),
                schema_version=RESERVATION_SCHEMA_VERSION,
                checkpoint_id=checkpoint_id,
                queue_entry_id=queue_entry_id,
                attempt=int(attempt),
                slot_id=slot_id,
                provider=provider,
                native_session_id=native_session_id,
                environment_id=environment_id,
                state="reserved",
                created_at=now_utc_iso(),
                gui_id=gui_id,
                runtime_kind=runtime_kind,
                operator_id=operator_id,
            )
            # Persist active slot marker first so a crash before record write still blocks competing launches.
            atomic_write_json(self._active_slot_path(slot_id), res.to_dict())
            atomic_write_json(self._record_path(res.reservation_id), res.to_dict())
            return res

    def bind_launch(
        self,
        reservation_id: str,
        *,
        launch_id: str,
        pane_id: str,
    ) -> RestorationReservation:
        """Bind terminal launch_id and pane_id to the active reservation before submission."""
        _require_non_empty(reservation_id, "reservation_id")
        _require_non_empty(launch_id, "launch_id")
        _require_non_empty(pane_id, "pane_id")
        current = self.get_reservation(reservation_id)
        with acquire_canonical_slot_lock(self.home_dir, current.slot_id, blocking=True):
            latest = self.get_reservation(reservation_id)
            active = self.get_active_for_slot(latest.slot_id)
            if active is None or active.reservation_id != reservation_id:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Reservation {reservation_id!r} is not the current active reservation for slot {latest.slot_id!r}.",
                    {"slot_id": latest.slot_id, "reservation_id": reservation_id},
                )
            if latest.state not in {"reserved", "submitted"}:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Cannot bind launch to reservation {reservation_id!r} in state {latest.state!r}.",
                    {"slot_id": latest.slot_id, "reservation_id": reservation_id, "state": latest.state},
                )
            updated = RestorationReservation(
                **{
                    **latest.to_dict(),
                    "launch_id": launch_id,
                    "pane_id": pane_id,
                    "state": "submitted",
                }
            )
            atomic_write_json(self._record_path(reservation_id), updated.to_dict())
            atomic_write_json(self._active_slot_path(latest.slot_id), updated.to_dict())
            return updated

    def consume_reservation_locked(
        self,
        reservation_id: str,
        *,
        reservation_token: str,
        checkpoint_id: str,
        queue_entry_id: str | None = None,
        attempt: int,
        slot_id: str,
        provider: str,
        native_session_id: str,
        environment_id: str,
        launch_id: str,
        pane_id: str,
        consumer_pid: int | None = None,
        exact_association_confirmed: bool = False,
        require_bound_launch: bool = True,
    ) -> RestorationReservation:
        """Validate and consume the current active reservation while caller holds `slot-<slot_id>.lock`."""
        _require_non_empty(reservation_id, "reservation_id")
        _require_non_empty(reservation_token, "reservation_token")
        _require_non_empty(checkpoint_id, "checkpoint_id")
        _require_non_empty(slot_id, "slot_id")
        _require_non_empty(provider, "provider")
        _require_non_empty(native_session_id, "native_session_id")
        _require_non_empty(environment_id, "environment_id")
        _require_non_empty(launch_id, "launch_id")
        _require_non_empty(pane_id, "pane_id")

        active = self.get_active_for_slot(slot_id)
        if active is None or active.reservation_id != reservation_id:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Reservation {reservation_id!r} is not the current active reservation for slot {slot_id!r}.",
                {
                    "slot_id": slot_id,
                    "reservation_id": reservation_id,
                    "active_reservation_id": active.reservation_id if active is not None else None,
                },
            )

        res = self.get_reservation(reservation_id)
        if res.state not in {"reserved", "submitted"}:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Reservation {reservation_id!r} cannot be consumed from state {res.state!r}.",
                {"slot_id": slot_id, "reservation_id": reservation_id, "state": res.state},
            )
        if not secrets.compare_digest(res.reservation_token, reservation_token):
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Reservation token mismatch for {reservation_id!r}.",
                {"slot_id": slot_id, "reservation_id": reservation_id},
            )
        if (
            res.checkpoint_id != checkpoint_id
            or res.attempt != int(attempt)
            or res.queue_entry_id != queue_entry_id
            or res.slot_id != slot_id
            or res.provider != provider
            or res.native_session_id != native_session_id
            or res.environment_id != environment_id
        ):
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Reservation {reservation_id!r} identity mismatch.",
                {"expected_slot": res.slot_id, "actual_slot": slot_id, "reservation_id": reservation_id},
            )
        if require_bound_launch and (res.launch_id is None or res.pane_id is None):
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Reservation {reservation_id!r} has no bound launch_id/pane_id.",
                {"slot_id": slot_id, "reservation_id": reservation_id},
            )
        if res.launch_id is not None and res.launch_id != launch_id:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Reservation {reservation_id!r} launch_id mismatch.",
                {"slot_id": slot_id, "reservation_id": reservation_id},
            )
        if res.pane_id is not None and res.pane_id != pane_id:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Reservation {reservation_id!r} pane_id mismatch.",
                {"slot_id": slot_id, "reservation_id": reservation_id},
            )
        consumed = RestorationReservation(
            **{
                **res.to_dict(),
                "launch_id": launch_id,
                "pane_id": pane_id,
                "state": "consumed",
                "consumed_at": now_utc_iso(),
                "consumer_pid": consumer_pid or os.getpid(),
                "dispatcher_ownership_acknowledged": True,
                "exact_association_confirmed": bool(exact_association_confirmed),
            }
        )
        atomic_write_json(self._record_path(reservation_id), consumed.to_dict())
        with contextlib.suppress(OSError):
            self._active_slot_path(slot_id).unlink(missing_ok=True)
        return consumed

    def consume_reservation(
        self,
        reservation_id: str,
        *,
        reservation_token: str,
        checkpoint_id: str,
        queue_entry_id: str | None = None,
        attempt: int,
        slot_id: str,
        provider: str,
        native_session_id: str,
        environment_id: str,
        launch_id: str,
        pane_id: str,
        consumer_pid: int | None = None,
        exact_association_confirmed: bool = False,
        require_bound_launch: bool = True,
    ) -> RestorationReservation:
        """Acquire `slot-<slot_id>.lock` and atomically validate and consume a reservation."""
        _require_non_empty(slot_id, "slot_id")
        with acquire_canonical_slot_lock(self.home_dir, slot_id, blocking=True):
            return self.consume_reservation_locked(
                reservation_id,
                reservation_token=reservation_token,
                checkpoint_id=checkpoint_id,
                queue_entry_id=queue_entry_id,
                attempt=attempt,
                slot_id=slot_id,
                provider=provider,
                native_session_id=native_session_id,
                environment_id=environment_id,
                launch_id=launch_id,
                pane_id=pane_id,
                consumer_pid=consumer_pid,
                exact_association_confirmed=exact_association_confirmed,
                require_bound_launch=require_bound_launch,
            )

    def acknowledge_provider_association_locked(
        self,
        reservation_id: str,
        *,
        reservation_token: str,
        provider_pid: int | None = None,
        exact_association_confirmed: bool = False,
    ) -> RestorationReservation:
        """Record actual provider association separately after reservation consumption (caller holds lock)."""
        _require_non_empty(reservation_id, "reservation_id")
        _require_non_empty(reservation_token, "reservation_token")
        res = self.get_reservation(reservation_id)
        if res.state != "consumed" or not res.dispatcher_ownership_acknowledged:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Reservation {reservation_id!r} must be consumed before acknowledging provider association.",
                {"slot_id": res.slot_id, "reservation_id": reservation_id, "state": res.state},
            )
        if not secrets.compare_digest(res.reservation_token, reservation_token):
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Reservation token mismatch for {reservation_id!r}.",
                {"slot_id": res.slot_id, "reservation_id": reservation_id},
            )
        updated = RestorationReservation(
            **{
                **res.to_dict(),
                "provider_pid": provider_pid if provider_pid is not None else res.provider_pid,
                "exact_association_confirmed": bool(exact_association_confirmed),
            }
        )
        atomic_write_json(self._record_path(reservation_id), updated.to_dict())
        return updated

    def acknowledge_provider_association(
        self,
        reservation_id: str,
        *,
        reservation_token: str,
        provider_pid: int | None = None,
        exact_association_confirmed: bool = False,
    ) -> RestorationReservation:
        """Acquire `slot-<slot_id>.lock` and record provider association after consumption."""
        current = self.get_reservation(reservation_id)
        with acquire_canonical_slot_lock(self.home_dir, current.slot_id, blocking=True):
            return self.acknowledge_provider_association_locked(
                reservation_id,
                reservation_token=reservation_token,
                provider_pid=provider_pid,
                exact_association_confirmed=exact_association_confirmed,
            )

    def mark_ambiguous(
        self,
        reservation_id: str,
        *,
        reason: str,
        launch_id: str | None = None,
        pane_id: str | None = None,
    ) -> RestorationReservation:
        """Preserve an uncertain reservation without overwriting a newer attempt's active marker."""
        current = self.get_reservation(reservation_id)
        with acquire_canonical_slot_lock(self.home_dir, current.slot_id, blocking=True):
            return self.mark_ambiguous_locked(
                reservation_id, reason=reason, launch_id=launch_id, pane_id=pane_id,
            )

    def mark_ambiguous_locked(
        self,
        reservation_id: str,
        *,
        reason: str,
        launch_id: str | None = None,
        pane_id: str | None = None,
    ) -> RestorationReservation:
        """Record uncertainty while the caller retains the canonical slot lock."""
        latest = self.get_reservation(reservation_id)
        active = self.get_active_for_slot(latest.slot_id)
        if active is not None and active.reservation_id != reservation_id:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                f"Stale mark_ambiguous on {reservation_id!r}: slot {latest.slot_id!r} has newer active reservation {active.reservation_id!r}.",
                {"slot_id": latest.slot_id, "reservation_id": reservation_id},
            )
        updated = RestorationReservation(
            **{
                **latest.to_dict(),
                "launch_id": launch_id or latest.launch_id,
                "pane_id": pane_id or latest.pane_id,
                "state": "ambiguous",
                "note": reason,
            }
        )
        atomic_write_json(self._record_path(reservation_id), updated.to_dict())
        atomic_write_json(self._active_slot_path(latest.slot_id), updated.to_dict())
        return updated

    def abort_reservation(self, reservation_id: str, *, reason: str) -> RestorationReservation:
        """Release an unexecuted reservation without ever removing a newer attempt's active marker."""
        current = self.get_reservation(reservation_id)
        with acquire_canonical_slot_lock(self.home_dir, current.slot_id, blocking=True):
            latest = self.get_reservation(reservation_id)
            if latest.state == "consumed":
                return latest
            updated = RestorationReservation(
                **{
                    **latest.to_dict(),
                    "state": "aborted",
                    "note": reason,
                }
            )
            atomic_write_json(self._record_path(reservation_id), updated.to_dict())
            active = self.get_active_for_slot(latest.slot_id)
            if active is not None and active.reservation_id == reservation_id:
                with contextlib.suppress(OSError):
                    self._active_slot_path(latest.slot_id).unlink(missing_ok=True)
            return updated


class ReservationSlotExecutionGuard:
    """SlotExecutionGuard backed by canonical `slot-<slot_id>.lock` + durable lease/reservation state.

    The OS lock (`slot-<slot_id>.lock`) is acquired only around the atomic check/record
    and immediately released so child processes (e.g. `_pane_runner` / `llmd`) can
    acquire and retain the same canonical lock without parent-holds-lock/child-acquires-lock deadlock.
    """

    def __init__(
        self,
        home_dir: Path,
        *,
        blocking: bool = False,
        timeout_seconds: float = 5.0,
        process_identity_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self.home_dir = Path(home_dir)
        self.store = RestorationReservationStore(self.home_dir)
        self.blocking = blocking
        self.timeout_seconds = timeout_seconds
        self.process_identity_provider = process_identity_provider
        self._leases: dict[str, str] = {}

    def _lease_path(self, slot_id: str) -> Path:
        return self.store._lease_path(slot_id)

    def acquire_slot(
        self,
        slot_id: str,
        *,
        operator_id: str,
        checkpoint_id: str,
        queue_entry_id: str | None,
    ) -> Any:
        from .workspace_lifecycle import SlotGuardLease

        lease_path = self._lease_path(slot_id)
        try:
            with acquire_canonical_slot_lock(
                self.home_dir,
                slot_id,
                blocking=self.blocking,
                timeout_seconds=self.timeout_seconds,
            ), acquire_canonical_slot_lock(self.home_dir, f"lease-{slot_id}", blocking=True):
                existing = self.store.get_active_for_slot(slot_id)
                if existing is not None:
                    return SlotGuardLease(
                        slot_id=slot_id,
                        lease_token="",
                        acquired=False,
                        reason=f"active_reservation:{existing.state}",
                    )
                if lease_path.exists():
                    return SlotGuardLease(
                        slot_id=slot_id,
                        lease_token="",
                        acquired=False,
                        reason="slot_lock_held",
                    )
                token = generate_id("sgl")
                proc_identity = self.process_identity_provider() if self.process_identity_provider else None
                atomic_write_json(
                    lease_path,
                    {
                        "lease_token": token,
                        "slot_id": slot_id,
                        "operator_id": operator_id,
                        "checkpoint_id": checkpoint_id,
                        "queue_entry_id": queue_entry_id,
                        "pid": os.getpid(),
                        "process_identity": proc_identity,
                        "acquired_at": now_utc_iso(),
                    },
                )
        except ContinuityError:
            return SlotGuardLease(
                slot_id=slot_id,
                lease_token="",
                acquired=False,
                reason="slot_lock_held",
            )
        self._leases[token] = slot_id
        return SlotGuardLease(
            slot_id=slot_id,
            lease_token=token,
            acquired=True,
            reason="acquired",
        )

    def release_slot(self, lease: Any) -> None:
        """Release under a lease-specific lock, even while a child holds the slot lock."""
        slot_id = self._leases.pop(lease.lease_token, None)
        if slot_id is None:
            return
        lease_path = self._lease_path(slot_id)

        def _unlink_if_owner() -> None:
            if not lease_path.exists():
                return
            try:
                payload = json.loads(lease_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if payload.get("lease_token") == lease.lease_token:
                with contextlib.suppress(OSError):
                    lease_path.unlink(missing_ok=True)

        with acquire_canonical_slot_lock(self.home_dir, f"lease-{slot_id}", blocking=True):
            _unlink_if_owner()

    def recover_abandoned_lease(
        self,
        slot_id: str,
        *,
        operator_id: str,
        reason: str,
        verified_abandoned: bool = False,
        expected_lease_token: str | None = None,
        expected_pid: int | None = None,
        expected_process_identity: str | None = None,
        min_lease_age_seconds: float | None = None,
        live_process_checker: Callable[[int, str | None], bool] | None = None,
    ) -> dict[str, Any]:
        """Guarded recovery for an abandoned preparation lease; refuses live owners."""
        if not verified_abandoned:
            raise ContinuityError(
                ErrorCode.ASSOCIATION_CONFLICT,
                "Abandoned preparation-lease recovery requires explicit verified_abandoned=True.",
                {"slot_id": slot_id},
            )
        lease_path = self._lease_path(slot_id)
        with acquire_canonical_slot_lock(self.home_dir, slot_id, blocking=True), acquire_canonical_slot_lock(
            self.home_dir, f"lease-{slot_id}", blocking=True
        ):
            if not lease_path.exists():
                raise ContinuityError(
                    ErrorCode.SESSION_NOT_FOUND,
                    f"No preparation lease exists for slot {slot_id!r}.",
                    {"slot_id": slot_id},
                )
            try:
                payload = json.loads(lease_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ContinuityError(
                    ErrorCode.MATERIALIZER_FAILED,
                    f"Preparation lease for slot {slot_id!r} is corrupt: {exc}",
                    {"slot_id": slot_id},
                ) from exc
            if expected_lease_token is not None and payload.get("lease_token") != expected_lease_token:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Preparation lease token mismatch on slot {slot_id!r}.",
                    {"slot_id": slot_id},
                )
            lease_pid = payload.get("pid")
            lease_proc_id = payload.get("process_identity")
            if expected_pid is not None and lease_pid != expected_pid:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Preparation lease PID mismatch on slot {slot_id!r}: expected {expected_pid}, got {lease_pid}.",
                    {"slot_id": slot_id},
                )
            if expected_process_identity is not None and lease_proc_id != expected_process_identity:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Preparation lease process identity mismatch on slot {slot_id!r}.",
                    {"slot_id": slot_id},
                )
            if (
                live_process_checker is not None
                and isinstance(lease_pid, int)
                and live_process_checker(lease_pid, str(lease_proc_id) if lease_proc_id is not None else None)
            ):
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Cannot recover live preparation lease on slot {slot_id!r} (pid={lease_pid}).",
                    {"slot_id": slot_id, "pid": lease_pid},
                )
            if min_lease_age_seconds is not None and payload.get("acquired_at"):
                acquired_dt = datetime.fromisoformat(str(payload["acquired_at"]).replace("Z", "+00:00"))
                age = (datetime.now(UTC) - acquired_dt).total_seconds()
                if age < min_lease_age_seconds:
                    raise ContinuityError(
                        ErrorCode.ASSOCIATION_CONFLICT,
                        f"Preparation lease on slot {slot_id!r} is only {age:.2f}s old (< {min_lease_age_seconds:.2f}s).",
                        {"slot_id": slot_id},
                    )
            lease_path.unlink(missing_ok=True)
            return {
                **payload,
                "recovered_by": operator_id,
                "recovery_reason": reason,
                "recovered_at": now_utc_iso(),
            }


class ReservationOwnershipVerifier:
    """Verify atomic dispatcher ownership transfer via consumed RestorationReservation."""

    def __init__(self, home_dir: Path, dispatcher: Any | None = None) -> None:
        self.store = RestorationReservationStore(home_dir)
        self.dispatcher = dispatcher

    def verify_ownership(
        self,
        request: Any,
        *,
        launch_id: str,
        pane_id: str,
    ) -> tuple[bool, bool]:
        reservation_id = getattr(request, "reservation_id", None)
        if not reservation_id:
            return False, False
        try:
            res = self.store.get_reservation(reservation_id)
        except ContinuityError:
            return False, False
        if res.state != "consumed" or not res.dispatcher_ownership_acknowledged:
            return False, False
        if (
            res.slot_id != request.slot_id
            or res.provider != request.provider
            or res.native_session_id != request.native_session_id
            or res.environment_id != request.environment_id
        ):
            return False, False
        req_checkpoint_id = getattr(request, "checkpoint_id", None)
        if req_checkpoint_id is not None and res.checkpoint_id != req_checkpoint_id:
            return False, False
        req_queue_entry_id = getattr(request, "queue_entry_id", None)
        if req_queue_entry_id is not None and res.queue_entry_id != req_queue_entry_id:
            return False, False
        req_attempt = getattr(request, "attempt", None)
        if req_attempt is not None and res.attempt != int(req_attempt):
            return False, False
        if res.launch_id is None or res.launch_id != launch_id:
            return False, False
        if res.pane_id is None or res.pane_id != pane_id:
            return False, False
        if self.dispatcher is None:
            return True, bool(res.exact_association_confirmed)
        try:
            slot = self.dispatcher.get_slot_by_id(request.slot_id)
            current = slot.get("current") if isinstance(slot, dict) else None
            associated = bool(current and (
                current.get("provider"), current.get("environment_id"), current.get("native_session_id")
            ) == (request.provider, request.environment_id, request.native_session_id))
        except Exception:
            associated = False
        return True, associated
