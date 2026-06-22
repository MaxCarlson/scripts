"""Cross-process locks for ytaedl source URL files."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import BinaryIO, Callable, Dict, Optional


LOCK_SUFFIX = ".ytaedl.lock"
DEFAULT_LOCK_DIR = Path("./archive/locks")
LOCK_HELD_RC = 73
LOCK_ERROR_RC = 74


@dataclass(frozen=True)
class LockAttempt:
    status: str
    source_path: Path
    lock_path: Path
    owner: Optional[Dict[str, object]] = None
    error: Optional[str] = None

    @property
    def acquired(self) -> bool:
        return self.status == "acquired"


def canonical_source_path(source_path: Path) -> Path:
    return source_path.expanduser().resolve()


def lock_path_for(source_path: Path, lock_dir: Optional[Path] = None) -> Path:
    source = canonical_source_path(source_path)
    identity = os.path.normcase(str(source))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    readable_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source.name).strip("._") or "urlfile"
    root = (lock_dir or DEFAULT_LOCK_DIR).expanduser().resolve()
    return root / f"{readable_name}.{digest}{LOCK_SUFFIX}"


def _read_metadata(path: Path) -> Optional[Dict[str, object]]:
    try:
        with path.open("rb") as fh:
            fh.seek(1)
            raw = fh.read().decode("utf-8", errors="replace").strip()
        data = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


class UrlFileLock:
    """A process-owned advisory lock for one canonical source URL file."""

    def __init__(
        self,
        source_path: Path,
        *,
        worker_slot: int = 0,
        manager_pid: Optional[int] = None,
        mode: str = "worker",
        lock_dir: Optional[Path] = None,
    ) -> None:
        self.source_path = canonical_source_path(source_path)
        self.path = lock_path_for(self.source_path, lock_dir)
        self.worker_slot = int(worker_slot or 0)
        self.manager_pid = int(manager_pid) if manager_pid else None
        self.mode = mode
        self._fh: Optional[BinaryIO] = None

    def _lock_handle(self, fh: BinaryIO) -> None:
        fh.seek(0)
        if os.name == "nt":
            import msvcrt  # type: ignore

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return

        import fcntl  # type: ignore

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_handle(self, fh: BinaryIO) -> None:
        fh.seek(0)
        if os.name == "nt":
            import msvcrt  # type: ignore

            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl  # type: ignore

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _write_metadata(self, fh: BinaryIO) -> None:
        metadata = {
            "pid": os.getpid(),
            "manager_pid": self.manager_pid,
            "acquired_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source_path": str(self.source_path),
            "worker_slot": self.worker_slot,
            "mode": self.mode,
        }
        payload = json.dumps(metadata, sort_keys=True).encode("utf-8") + b"\n"
        fh.seek(1)
        fh.truncate(1)
        fh.write(payload)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
        fh.seek(0)

    def try_acquire(self) -> LockAttempt:
        if self._fh is not None:
            return LockAttempt("acquired", self.source_path, self.path)

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fh = self.path.open("a+b")
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(b"\x00")
                fh.flush()
        except OSError as exc:
            return LockAttempt("error", self.source_path, self.path, error=str(exc))

        try:
            self._lock_handle(fh)
        except OSError as exc:
            try:
                fh.close()
            except Exception:
                pass
            owner = _read_metadata(self.path)
            return LockAttempt("held", self.source_path, self.path, owner=owner, error=str(exc))
        except ImportError as exc:
            fh.close()
            return LockAttempt("error", self.source_path, self.path, error=str(exc))

        try:
            self._write_metadata(fh)
        except OSError as exc:
            try:
                self._unlock_handle(fh)
            finally:
                fh.close()
            return LockAttempt("error", self.source_path, self.path, error=str(exc))

        self._fh = fh
        return LockAttempt("acquired", self.source_path, self.path)

    def acquire_waiting(
        self,
        stop_requested: Callable[[], bool],
        *,
        poll_seconds: float = 0.5,
        on_wait: Optional[Callable[[LockAttempt], None]] = None,
    ) -> LockAttempt:
        while True:
            attempt = self.try_acquire()
            if attempt.status != "held":
                return attempt
            if on_wait is not None:
                on_wait(attempt)
            if stop_requested():
                return LockAttempt(
                    "stopped",
                    self.source_path,
                    self.path,
                    owner=attempt.owner,
                )
            time.sleep(max(0.05, poll_seconds))

    def release(self) -> None:
        fh = self._fh
        if fh is None:
            return
        try:
            self._unlock_handle(fh)
        except OSError:
            pass
        try:
            fh.close()
        finally:
            self._fh = None

    def __enter__(self) -> "UrlFileLock":
        attempt = self.try_acquire()
        if not attempt.acquired:
            raise RuntimeError(attempt.error or f"URL file lock unavailable: {attempt.lock_path}")
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()


def probe_urlfile_lock(source_path: Path, lock_dir: Optional[Path] = None) -> LockAttempt:
    lock = UrlFileLock(source_path, mode="probe", lock_dir=lock_dir)
    if not lock.path.exists():
        return LockAttempt("available", lock.source_path, lock.path)
    attempt = lock.try_acquire()
    if attempt.acquired:
        lock.release()
        return LockAttempt("available", attempt.source_path, attempt.lock_path)
    return attempt
