"""Durable restoration reservation and atomic ownership-transfer protocol (LLMD-43/44).

Coordinates slot-level exclusion using Agent #1's canonical slot lock
(`home_dir / f"slot-{slot_id}.lock"`) without holding the OS file lock across
child process execution (avoiding parent-holds-lock / child-acquires-lock deadlocks).
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import ContinuityError, ErrorCode
from .events import atomic_write_json
from .identifiers import generate_id, now_utc_iso

RESERVATION_SCHEMA_VERSION = 1


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
    """Acquire `<home_dir>/slot-<slot_id>.lock` briefly for metadata/reservation transitions."""
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
    reservation_token: str
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
    dispatcher_ownership_acknowledged: bool = False
    exact_association_confirmed: bool = False
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

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
            dispatcher_ownership_acknowledged=bool(data.get("dispatcher_ownership_acknowledged", False)),
            exact_association_confirmed=bool(data.get("exact_association_confirmed", False)),
            note=str(data["note"]) if data.get("note") is not None else None,
        )


ACTIVE_RESERVATION_STATES = frozenset({"reserved", "submitted", "ambiguous"})


class RestorationReservationStore:
    """Atomic store for exact-session restoration reservations under `<home_dir>/restoration_reservations/`."""

    def __init__(self, home_dir: Path) -> None:
        self.home_dir = Path(home_dir)
        self.reservations_dir = self.home_dir / "restoration_reservations"

    def _record_path(self, reservation_id: str) -> Path:
        return self.reservations_dir / f"{reservation_id}.json"

    def _active_slot_path(self, slot_id: str) -> Path:
        return self.reservations_dir / f"slot-{slot_id}.active.json"

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
            ) from exc
        if res.state in ACTIVE_RESERVATION_STATES:
            return res
        return None

    def get_reservation(self, reservation_id: str) -> RestorationReservation:
        path = self._record_path(reservation_id)
        if not path.exists():
            raise ContinuityError(
                ErrorCode.SESSION_NOT_FOUND,
                f"Restoration reservation {reservation_id!r} was not found.",
            )
        try:
            return RestorationReservation.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ContinuityError(
                ErrorCode.MATERIALIZER_FAILED,
                f"Restoration reservation {reservation_id!r} is corrupt: {exc}",
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
                attempt=attempt,
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
            atomic_write_json(self._record_path(res.reservation_id), res.to_dict())
            atomic_write_json(self._active_slot_path(slot_id), res.to_dict())
            return res

    def bind_launch(
        self,
        reservation_id: str,
        *,
        launch_id: str,
        pane_id: str,
    ) -> RestorationReservation:
        """Bind terminal launch_id and pane_id to a reserved slot before submission."""
        current = self.get_reservation(reservation_id)
        with acquire_canonical_slot_lock(self.home_dir, current.slot_id, blocking=True):
            latest = self.get_reservation(reservation_id)
            if latest.state not in {"reserved", "submitted"}:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Cannot bind launch to reservation {reservation_id!r} in state {latest.state!r}.",
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

    def consume_reservation(
        self,
        reservation_id: str,
        *,
        reservation_token: str,
        slot_id: str,
        provider: str,
        native_session_id: str,
        environment_id: str,
        launch_id: str | None = None,
        pane_id: str | None = None,
        consumer_pid: int | None = None,
        exact_association_confirmed: bool = True,
    ) -> RestorationReservation:
        """Atomically validate and consume a reservation in the target dispatcher/pane process."""
        with acquire_canonical_slot_lock(self.home_dir, slot_id, blocking=True):
            res = self.get_reservation(reservation_id)
            if res.state not in {"reserved", "submitted"}:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Reservation {reservation_id!r} cannot be consumed from state {res.state!r}.",
                )
            if not secrets.compare_digest(res.reservation_token, reservation_token):
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Reservation token mismatch for {reservation_id!r}.",
                )
            if (
                res.slot_id != slot_id
                or res.provider != provider
                or res.native_session_id != native_session_id
                or res.environment_id != environment_id
            ):
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Reservation {reservation_id!r} identity mismatch.",
                    {"expected_slot": res.slot_id, "actual_slot": slot_id},
                )
            if res.launch_id is not None and launch_id is not None and res.launch_id != launch_id:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Reservation {reservation_id!r} launch_id mismatch.",
                )
            if res.pane_id is not None and pane_id is not None and res.pane_id != pane_id:
                raise ContinuityError(
                    ErrorCode.ASSOCIATION_CONFLICT,
                    f"Reservation {reservation_id!r} pane_id mismatch.",
                )
            consumed = RestorationReservation(
                **{
                    **res.to_dict(),
                    "launch_id": launch_id or res.launch_id,
                    "pane_id": pane_id or res.pane_id,
                    "state": "consumed",
                    "consumed_at": now_utc_iso(),
                    "consumer_pid": consumer_pid or os.getpid(),
                    "dispatcher_ownership_acknowledged": True,
                    "exact_association_confirmed": exact_association_confirmed,
                }
            )
            atomic_write_json(self._record_path(reservation_id), consumed.to_dict())
            with contextlib.suppress(OSError):
                self._active_slot_path(slot_id).unlink(missing_ok=True)
            return consumed

    def mark_ambiguous(
        self,
        reservation_id: str,
        *,
        reason: str,
        launch_id: str | None = None,
        pane_id: str | None = None,
    ) -> RestorationReservation:
        """Preserve an uncertain reservation so competing launches remain blocked until resolved."""
        current = self.get_reservation(reservation_id)
        with acquire_canonical_slot_lock(self.home_dir, current.slot_id, blocking=True):
            latest = self.get_reservation(reservation_id)
            if latest.state == "consumed":
                return latest
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
        """Release an unexecuted reservation only when non-execution is positively established."""
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
            with contextlib.suppress(OSError):
                self._active_slot_path(latest.slot_id).unlink(missing_ok=True)
            return updated


class ReservationSlotExecutionGuard:
    """SlotExecutionGuard backed by canonical `slot-<slot_id>.lock` + durable lease/reservation state.

    The OS lock (`slot-<slot_id>.lock`) is acquired only around the atomic check/record
    and immediately released so child processes (e.g. `_pane_runner` / `llmd`) can
    acquire the same canonical lock without parent-holds-lock/child-acquires-lock deadlock.
    """

    def __init__(
        self,
        home_dir: Path,
        *,
        blocking: bool = False,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.home_dir = Path(home_dir)
        self.store = RestorationReservationStore(self.home_dir)
        self.blocking = blocking
        self.timeout_seconds = timeout_seconds
        self._leases: dict[str, str] = {}

    def _lease_path(self, slot_id: str) -> Path:
        return self.store.reservations_dir / f"slot-{slot_id}.lease.json"

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
            ):
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
                atomic_write_json(
                    lease_path,
                    {
                        "lease_token": token,
                        "slot_id": slot_id,
                        "operator_id": operator_id,
                        "checkpoint_id": checkpoint_id,
                        "queue_entry_id": queue_entry_id,
                        "pid": os.getpid(),
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
        slot_id = self._leases.pop(lease.lease_token, None)
        if slot_id is None:
            return
        lease_path = self._lease_path(slot_id)
        with (
            contextlib.suppress(ContinuityError),
            acquire_canonical_slot_lock(self.home_dir, slot_id, blocking=True, timeout_seconds=2.0),
        ):
                if lease_path.exists():
                    try:
                        payload = json.loads(lease_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        payload = {}
                    if payload.get("lease_token") == lease.lease_token:
                        with contextlib.suppress(OSError):
                            lease_path.unlink(missing_ok=True)


class ReservationOwnershipVerifier:
    """Verify atomic dispatcher ownership transfer via consumed RestorationReservation."""

    def __init__(self, home_dir: Path) -> None:
        self.store = RestorationReservationStore(home_dir)

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
        if res.launch_id is not None and res.launch_id != launch_id:
            return False, False
        if res.pane_id is not None and res.pane_id != pane_id:
            return False, False
        return True, bool(res.exact_association_confirmed)
