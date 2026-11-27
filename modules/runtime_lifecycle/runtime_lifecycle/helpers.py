"""Reusable Windows runtime and cross-platform concurrency helpers."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


def _is_windows() -> bool:
    return os.name == "nt"


def resolve_pythonw(executable: Path | None = None) -> Path:
    """Resolve the windowless interpreter corresponding to Python."""
    interpreter = Path(executable or sys.executable)
    candidates = [interpreter.with_name("pythonw.exe"), Path(sys.base_prefix) / "pythonw.exe"]
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen and candidate.is_file():
            return candidate.resolve()
        seen.add(key)
    raise FileNotFoundError(f"Could not find pythonw.exe beside {interpreter} or under {sys.base_prefix}")


def spawn_detached(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    hidden: bool = True,
    breakaway: bool = True,
) -> subprocess.Popen[bytes]:
    """Spawn a process detached from a console and best-effort from a job object."""
    if not _is_windows():
        return subprocess.Popen(
            [str(arg) for arg in argv],
            cwd=str(cwd),
            env=dict(env) if env is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )

    flags = 0x00000200  # CREATE_NEW_PROCESS_GROUP
    if hidden:
        flags |= 0x00000008  # DETACHED_PROCESS
    if breakaway:
        flags |= 0x01000000  # CREATE_BREAKAWAY_FROM_JOB; retry without if the job denies it.
    args = [str(arg) for arg in argv]
    kwargs = {
        "cwd": str(cwd),
        "env": dict(env) if env is not None else None,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "creationflags": flags,
    }
    try:
        return subprocess.Popen(args, **kwargs)
    except OSError as exc:
        if not breakaway or flags & 0x01000000 == 0:
            raise
        if getattr(exc, "winerror", None) not in {5, 87}:
            raise
        fallback_flags = flags & ~0x01000000
        try:
            return subprocess.Popen(args, **(kwargs | {"creationflags": fallback_flags}))
        except OSError:
            raise exc


class NamedMutex:
    """Named exclusion lock with Windows mutex and non-Windows file-lock backends."""

    def __init__(
        self,
        name: str,
        *,
        timeout_seconds: float = 5.0,
        owner_metadata_path: Path | None = None,
    ) -> None:
        if not name or any(char in name for char in "\\/\0"):
            raise ValueError("mutex name must be non-empty and must not contain slashes")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.owner_metadata_path = owner_metadata_path
        self._handle: object | None = None
        self._file = None
        self._acquired = False

    def acquire(self) -> bool:
        """Acquire the mutex, returning False when the timeout expires."""
        if self._acquired:
            return True
        if _is_windows():
            self._acquire_windows()
        else:
            self._acquire_file()
        if self._acquired and self.owner_metadata_path:
            self.owner_metadata_path.parent.mkdir(parents=True, exist_ok=True)
            self.owner_metadata_path.write_text(
                json.dumps({"pid": os.getpid(), "acquired_at": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
        return self._acquired

    def _acquire_windows(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, f"Local\\{self.name}")
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
        self._handle = handle
        wait_ms = min(int(self.timeout_seconds * 1000), 0xFFFFFFFE)
        result = kernel32.WaitForSingleObject(handle, wait_ms)
        if result in (0x00000000, 0x00000080):  # WAIT_OBJECT_0 or WAIT_ABANDONED
            self._acquired = True
        elif result == 0x00000102:  # WAIT_TIMEOUT
            kernel32.CloseHandle(handle)
            self._handle = None
        else:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            self._handle = None
            raise OSError(error, "WaitForSingleObject failed")

    def _acquire_file(self) -> None:
        digest = hashlib.sha256(self.name.encode("utf-8")).hexdigest()[:24]
        lock_path = Path(tempfile.gettempdir()) / f"runtime-lifecycle-{digest}.lock"
        stream = lock_path.open("a+b")
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                self._file = stream
                self._acquired = True
                return
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    stream.close()
                    return
                time.sleep(0.05)

    def release(self) -> None:
        """Release a previously acquired mutex and close its handle."""
        if not self._acquired:
            return
        try:
            if self._handle is not None:
                import ctypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                if not kernel32.ReleaseMutex(self._handle):
                    raise OSError(ctypes.get_last_error(), "ReleaseMutex failed")
                kernel32.CloseHandle(self._handle)
                self._handle = None
            elif self._file is not None:
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                else:
                    import msvcrt

                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                self._file.close()
                self._file = None
        finally:
            self._acquired = False
            if self.owner_metadata_path:
                self.owner_metadata_path.unlink(missing_ok=True)

    def __enter__(self) -> NamedMutex:
        if not self.acquire():
            raise TimeoutError(f"Timed out waiting for mutex {self.name}")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()
