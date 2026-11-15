"""Per-user single-collector named mutex and owner heartbeat record."""

from __future__ import annotations

import ctypes
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any

from procwatch.config import DEFAULT_MUTEX_NAME, get_data_dir
from procwatch.models import utc_now_iso

ERROR_ALREADY_EXISTS = 183


class CollectorAlreadyRunningError(RuntimeError):
    """Raised when another live ProcWatch collector already owns the mutex."""

    def __init__(self, owner_info: dict[str, Any] | None = None) -> None:
        self.owner_info = owner_info or {}
        pid = self.owner_info.get("pid", "unknown")
        mode = self.owner_info.get("mode", "unknown")
        super().__init__(
            f"Another ProcWatch collector is already running (pid={pid}, mode={mode}). "
            "Stop the existing collector before starting a duplicate."
        )


@dataclass(slots=True)
class OwnerHeartbeat:
    """Diagnostic metadata written by the active collector owner."""

    pid: int
    mode: str
    command: str
    started_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_owner_heartbeat(data_dir: Path | None = None) -> dict[str, Any] | None:
    """Read the owner heartbeat file if present and valid JSON."""
    path = get_data_dir(data_dir) / "collector_owner.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


class CollectorMutex:
    """Acquires a per-user named Windows mutex to enforce single-collector ownership."""

    def __init__(
        self,
        name: str = DEFAULT_MUTEX_NAME,
        data_dir: Path | None = None,
        mode: str = "observe",
        command: str = "watch",
    ) -> None:
        self.name = name
        self.data_dir = get_data_dir(data_dir)
        self.mode = mode
        self.command = command
        self._handle: int | None = None
        self._heartbeat_path = self.data_dir / "collector_owner.json"

    @property
    def is_acquired(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        """Acquire the named mutex on Windows (or a lock marker in non-Windows tests)."""
        if self._handle is not None:
            return

        if sys.platform != "win32":
            # Non-Windows fallback for unit tests only; uses exclusive lockfile.
            self.data_dir.mkdir(parents=True, exist_ok=True)
            lock_file = self.data_dir / "collector.lock"
            if lock_file.exists():
                raise CollectorAlreadyRunningError(read_owner_heartbeat(self.data_dir))
            lock_file.write_text(str(os.getpid()), encoding="utf-8")
            self._handle = 1
            self._write_heartbeat()
            return

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            err = ctypes.get_last_error()
            raise OSError(err, f"CreateMutexW failed for {self.name!r} (error={err})")

        last_err = ctypes.get_last_error()
        if last_err == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            raise CollectorAlreadyRunningError(read_owner_heartbeat(self.data_dir))

        self._handle = int(handle)
        self._write_heartbeat()

    def _write_heartbeat(self) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            hb = OwnerHeartbeat(
                pid=os.getpid(),
                mode=self.mode,
                command=self.command,
                started_at_utc=utc_now_iso(),
            )
            self._heartbeat_path.write_text(json.dumps(hb.to_dict(), indent=2), encoding="utf-8")
        except OSError:
            pass

    def release(self) -> None:
        """Release the mutex and clean up the owner heartbeat file."""
        if self._handle is None:
            return
        try:
            if sys.platform != "win32":
                lock_file = self.data_dir / "collector.lock"
                if lock_file.exists():
                    lock_file.unlink(missing_ok=True)
            else:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.ReleaseMutex(self._handle)
                kernel32.CloseHandle(self._handle)
        finally:
            self._handle = None
            try:
                if self._heartbeat_path.exists():
                    self._heartbeat_path.unlink(missing_ok=True)
            except OSError:
                pass

    def __enter__(self) -> CollectorMutex:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()
