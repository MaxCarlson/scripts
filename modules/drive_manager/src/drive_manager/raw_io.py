r"""Cross-platform raw device I/O.

On Windows, Python's os.open() uses the CRT _wopen() which cannot open raw
device paths like \\.\PhysicalDriveN.  This module calls CreateFile /
WriteFile / ReadFile directly via ctypes so the caller never has to care.
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Windows raw-device writes must be a multiple of the logical sector size.
SECTOR_SIZE = 512


if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

    _kernel32 = ctypes.windll.kernel32

    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x80

    # Make sure CreateFileW returns a proper HANDLE (not truncated int).
    _kernel32.CreateFileW.restype = ctypes.wintypes.HANDLE
    _kernel32.CreateFileW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.HANDLE,
    ]

    def _open_device(path: str, write: bool) -> ctypes.wintypes.HANDLE:
        access = _GENERIC_READ | (_GENERIC_WRITE if write else 0)
        handle = _kernel32.CreateFileW(
            path,
            access,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        # INVALID_HANDLE_VALUE is -1; ctypes may return it as a large positive
        # int or as None depending on platform pointer width — check both.
        invalid = ctypes.wintypes.HANDLE(-1).value
        if handle is None or handle == invalid or handle == 0xFFFFFFFF or handle == 0xFFFFFFFFFFFFFFFF:
            err = ctypes.GetLastError()
            raise PermissionError(
                f"Cannot open raw device {path} (Win32 error {err}). "
                "Ensure the process is running as Administrator."
            )
        return handle

    def _write_device(handle: ctypes.wintypes.HANDLE, data: bytes) -> int:
        written = ctypes.wintypes.DWORD(0)
        ok = _kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None)
        if not ok:
            raise OSError(ctypes.GetLastError(), "WriteFile failed")
        return written.value

    def _read_device(handle: ctypes.wintypes.HANDLE, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        nread = ctypes.wintypes.DWORD(0)
        ok = _kernel32.ReadFile(handle, buf, size, ctypes.byref(nread), None)
        if not ok:
            raise OSError(ctypes.GetLastError(), "ReadFile failed")
        return buf.raw[: nread.value]

    def _flush_device(handle: ctypes.wintypes.HANDLE) -> None:
        _kernel32.FlushFileBuffers(handle)

    def _close_device(handle: ctypes.wintypes.HANDLE) -> None:
        _kernel32.CloseHandle(handle)

    # FSCTLs needed to lock and dismount a volume before raw writes.
    _FSCTL_LOCK_VOLUME = 0x00090018
    _FSCTL_DISMOUNT_VOLUME = 0x00090020

    def lock_and_dismount_volumes(drive_letters: list[str]) -> list:
        """Lock and dismount each volume so the kernel allows raw writes.

        Must be called BEFORE opening the physical disk for writing.
        Returns a list of open volume handles — keep them open for the entire
        duration of the write, then pass to :func:`close_volume_handles`.
        """
        handles = []
        br = ctypes.wintypes.DWORD(0)
        for letter in drive_letters:
            path = f"\\\\.\\{letter}:"
            try:
                h = _open_device(path, write=True)
                # Lock: prevents other processes accessing the volume.
                _kernel32.DeviceIoControl(
                    h, _FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(br), None
                )
                # Dismount: flushes filesystem and marks volume as unmounted.
                _kernel32.DeviceIoControl(
                    h, _FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(br), None
                )
                handles.append(h)
            except Exception:
                # Volume may already be inaccessible; skip and continue.
                pass
        return handles

    def close_volume_handles(handles: list) -> None:
        """Release volume locks obtained by :func:`lock_and_dismount_volumes`."""
        for h in handles:
            try:
                _close_device(h)
            except Exception:
                pass

else:
    # Non-Windows stubs so image_writer.py can call unconditionally.
    def lock_and_dismount_volumes(drive_letters: list[str]) -> list:  # type: ignore[misc]
        return []

    def close_volume_handles(handles: list) -> None:  # type: ignore[misc]
        pass


class RawDevice:
    """Thin wrapper for reading/writing a raw device path.

    Pad writes to SECTOR_SIZE yourself, or use :func:`sector_pad`.
    """

    def __init__(self, path: str | Path, *, write: bool = True) -> None:
        self._path = str(path)
        self._write = write
        self._handle = None
        self._fd: int | None = None

    def __enter__(self) -> "RawDevice":
        if sys.platform == "win32":
            self._handle = _open_device(self._path, self._write)
        else:
            flags = os.O_RDWR if self._write else os.O_RDONLY
            self._fd = os.open(self._path, flags)
        return self

    def __exit__(self, *_) -> None:
        try:
            if sys.platform == "win32" and self._handle is not None:
                _close_device(self._handle)
            elif self._fd is not None:
                os.close(self._fd)
        except Exception:
            pass

    def write(self, data: bytes) -> int:
        if sys.platform == "win32":
            return _write_device(self._handle, data)
        return os.write(self._fd, data)

    def read(self, size: int) -> bytes:
        if sys.platform == "win32":
            return _read_device(self._handle, size)
        return os.read(self._fd, size)

    def flush(self) -> None:
        try:
            if sys.platform == "win32":
                _flush_device(self._handle)
            else:
                os.fsync(self._fd)
        except Exception:
            pass


def sector_pad(data: bytes, sector_size: int = SECTOR_SIZE) -> bytes:
    """Pad *data* to a multiple of *sector_size* with null bytes."""
    rem = len(data) % sector_size
    return data if rem == 0 else data + b"\x00" * (sector_size - rem)
