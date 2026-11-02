"""
Single-instance host process locking mechanism.

Ensures that only one Resource Coordinator instance can supervise a managed resource
or miner process at any time, preventing duplicate coordinators and dual ownership.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SingleInstanceLockError(RuntimeError):
    """Raised when an exclusive coordinator instance lock cannot be acquired."""


class SingleInstanceLock:
    """
    OS-level single-instance lock scoped to a file path.

    Uses msvcrt file locking on Windows and fcntl advisory flock on POSIX.
    """

    def __init__(self, lock_path: str | Path) -> None:
        self.lock_path = Path(lock_path).resolve()
        self._fd: Optional[int] = None
        self._acquired = False

    @property
    def is_acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        """Attempt to acquire exclusive single-instance lock. Returns True on success, False if already held."""
        if self._acquired:
            return True

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                import msvcrt

                fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT)
                # LK_NBLCK is non-blocking exclusive lock for 1 byte
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                self._fd = fd
                self._acquired = True
                # Record PID in lock file for diagnostics
                os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
                return True
            else:
                import fcntl

                fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                self._acquired = True
                os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
                return True
        except (OSError, IOError, PermissionError) as exc:
            logger.warning("Single-instance lock at '%s' is held by another process: %s", self.lock_path, exc)
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None
            self._acquired = False
            return False

    def release(self) -> None:
        """Release the held single-instance lock."""
        if not self._acquired or self._fd is None:
            return

        try:
            if os.name == "nt":
                import msvcrt

                try:
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(self._fd)
        except OSError as exc:
            logger.debug("Error releasing single-instance lock: %s", exc)
        finally:
            self._fd = None
            self._acquired = False
            try:
                if self.lock_path.exists():
                    self.lock_path.unlink()
            except OSError:
                pass

    def __enter__(self) -> SingleInstanceLock:
        if not self.acquire():
            raise SingleInstanceLockError(
                f"Another coordinator instance is already running (locked at {self.lock_path})"
            )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()
