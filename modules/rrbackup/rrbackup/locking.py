"""Process-identity-aware locking for backup execution."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Union

import psutil

from .models import datetime_to_text, utc_now


class LockError(RuntimeError):
    """Base class for lock failures."""


class AlreadyRunningError(LockError):
    """Raised when a matching live process owns the lock."""


class InvalidLockError(LockError):
    """Raised when an existing lock cannot be validated safely."""


class LockOwnershipError(LockError):
    """Raised when a process attempts to release another owner's lock."""


@dataclass(frozen=True)
class ProcessIdentity:
    """Stable process identity using PID plus process creation time."""

    pid: int
    create_time: float
    executable: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the process identity."""

        return {
            "pid": self.pid,
            "create_time": self.create_time,
            "executable": self.executable,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProcessIdentity":
        """Deserialize a process identity."""

        return cls(
            pid=int(payload["pid"]),
            create_time=float(payload["create_time"]),
            executable=(
                None
                if payload.get("executable") is None
                else str(payload["executable"])
            ),
        )


@dataclass(frozen=True)
class LockInspection:
    """Read-only inspection result for a lock file."""

    exists: bool
    active: bool
    stale: bool
    valid: bool
    identity: Optional[ProcessIdentity]
    token: Optional[str]
    reason: str


def current_process_identity() -> ProcessIdentity:
    """Return the current process identity."""

    process = psutil.Process(os.getpid())
    try:
        executable = process.exe()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        executable = None
    return ProcessIdentity(
        pid=process.pid,
        create_time=float(process.create_time()),
        executable=executable,
    )


def process_matches(identity: ProcessIdentity, *, tolerance: float = 0.01) -> bool:
    """Return whether the exact recorded process still exists."""

    try:
        process = psutil.Process(identity.pid)
        return abs(float(process.create_time()) - identity.create_time) <= tolerance
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return psutil.pid_exists(identity.pid)


def _read_payload(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Lock payload must be a JSON object.")
    return payload


class ProcessLock:
    """Atomic lock that protects against PID reuse and foreign release."""

    def __init__(
        self,
        lock_path: Union[os.PathLike[str], str],
        *,
        identity_factory: Callable[[], ProcessIdentity] = current_process_identity,
        matcher: Callable[[ProcessIdentity], bool] = process_matches,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.identity_factory = identity_factory
        self.matcher = matcher
        self.identity: Optional[ProcessIdentity] = None
        self.token: Optional[str] = None
        self.acquired = False

    def inspect(self) -> LockInspection:
        """Inspect the lock without mutating it."""

        if not self.lock_path.exists():
            return LockInspection(
                exists=False,
                active=False,
                stale=False,
                valid=True,
                identity=None,
                token=None,
                reason="Lock file does not exist.",
            )

        try:
            payload = _read_payload(self.lock_path)
            identity = ProcessIdentity.from_dict(payload["process"])
            token = str(payload["token"])
        except Exception as exc:
            return LockInspection(
                exists=True,
                active=False,
                stale=False,
                valid=False,
                identity=None,
                token=None,
                reason="Lock file is invalid: {0}".format(exc),
            )

        active = bool(self.matcher(identity))
        return LockInspection(
            exists=True,
            active=active,
            stale=not active,
            valid=True,
            identity=identity,
            token=token,
            reason=(
                "Lock belongs to a live matching process."
                if active
                else "Recorded process no longer exists or its creation time changed."
            ),
        )

    def _remove_stale_lock(self, expected_token: str) -> bool:
        """Remove a stale lock only if its ownership token is unchanged."""

        try:
            current_payload = _read_payload(self.lock_path)
        except FileNotFoundError:
            return False
        except Exception as exc:
            raise InvalidLockError(
                "Lock changed while validating stale ownership and is now invalid: {0}".format(
                    exc
                )
            )

        if str(current_payload.get("token", "")) != expected_token:
            return False

        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            return False
        return True

    def acquire(self) -> None:
        """Acquire the lock, removing only a positively identified stale lock."""

        if self.acquired:
            raise LockError("Lock is already acquired by this object.")

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        identity = self.identity_factory()
        token = uuid.uuid4().hex
        payload = {
            "schema_version": 1,
            "token": token,
            "acquired_utc": datetime_to_text(utc_now()),
            "process": identity.to_dict(),
        }

        for _ in range(3):
            try:
                descriptor = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=4, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                self.identity = identity
                self.token = token
                self.acquired = True
                return
            except FileExistsError:
                inspection = self.inspect()
                if not inspection.valid:
                    raise InvalidLockError(
                        "Refusing to remove an invalid lock automatically. {0} Path: {1}".format(
                            inspection.reason,
                            self.lock_path,
                        )
                    )
                if inspection.active:
                    assert inspection.identity is not None
                    raise AlreadyRunningError(
                        "Another backup process is running with PID {0}. Lock: {1}".format(
                            inspection.identity.pid,
                            self.lock_path,
                        )
                    )
                if inspection.token is None:
                    raise InvalidLockError(
                        "Stale lock has no ownership token: {0}".format(
                            self.lock_path
                        )
                    )
                self._remove_stale_lock(inspection.token)

        raise LockError("Unable to acquire lock after resolving concurrent changes.")

    def release(self) -> None:
        """Release the lock only when the ownership token still matches."""

        if not self.acquired:
            return

        try:
            payload = _read_payload(self.lock_path)
        except FileNotFoundError:
            self.acquired = False
            self.identity = None
            self.token = None
            return
        except Exception as exc:
            raise LockOwnershipError(
                "Unable to validate lock ownership before release: {0}".format(exc)
            )

        existing_token = str(payload.get("token", ""))
        if existing_token != self.token:
            raise LockOwnershipError(
                "Lock ownership changed; refusing to remove lock: {0}".format(
                    self.lock_path
                )
            )

        self.lock_path.unlink(missing_ok=True)
        self.acquired = False
        self.identity = None
        self.token = None

    def __enter__(self) -> "ProcessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()
