"""Local Windows named-pipe transport for the privexec client."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import re
import struct
from typing import Any

MAX_FRAME_BYTES = 4 * 1024 * 1024
_PIPE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class TransportError(RuntimeError):
    """Base error for named-pipe communication failures."""


class UnsupportedPlatformError(TransportError):
    """Raised on non-Windows platforms."""


class BrokerNotRunningError(TransportError):
    """Raised when the local named pipe does not exist."""


class PipeAccessDeniedError(TransportError):
    """Raised when the Windows client account lacks pipe access."""


def validate_pipe_name(pipe_name: str) -> str:
    """Ensure the pipe name is a local simple pipe identifier (no host/UNC)."""
    if not _PIPE_NAME_RE.match(pipe_name):
        raise ValueError(
            f"Invalid pipe name '{pipe_name}'. Must be a local pipe identifier matching ^[A-Za-z0-9._-]{{1,128}}$."
        )
    return pipe_name


def pipe_unc_path(pipe_name: str) -> str:
    """Return local-only Windows named-pipe path."""
    return rf"\\.\pipe\{validate_pipe_name(pipe_name)}"


class WindowsNamedPipeClient:
    """Synchronous Win32 named-pipe client using 4-byte LE length-prefixed UTF-8 JSON."""

    def __init__(self, pipe_name: str, timeout_ms: int = 5000) -> None:
        self.pipe_name = validate_pipe_name(pipe_name)
        self.timeout_ms = timeout_ms

    def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        if os.name != "nt":
            raise UnsupportedPlatformError(
                "PrivExec named-pipe transport is supported only on Windows 11."
            )
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_FRAME_BYTES:
            raise TransportError(f"Request frame exceeds {MAX_FRAME_BYTES} bytes.")

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _configure_kernel32(kernel32)

        path = pipe_unc_path(self.pipe_name)
        generic_read = 0x80000000
        generic_write = 0x40000000
        open_existing = 3
        invalid_handle = wintypes.HANDLE(-1).value
        err_file_not_found = 2
        err_access_denied = 5
        err_pipe_busy = 231

        handle = kernel32.CreateFileW(
            path,
            generic_read | generic_write,
            0,
            None,
            open_existing,
            0,
            None,
        )
        if handle == invalid_handle:
            err = ctypes.get_last_error()
            if err == err_pipe_busy:
                if not kernel32.WaitNamedPipeW(path, self.timeout_ms):
                    raise BrokerNotRunningError(
                        f"Named pipe '{path}' remained busy after {self.timeout_ms}ms."
                    )
                handle = kernel32.CreateFileW(
                    path,
                    generic_read | generic_write,
                    0,
                    None,
                    open_existing,
                    0,
                    None,
                )
            if handle == invalid_handle:
                err = ctypes.get_last_error()
                if err == err_file_not_found:
                    raise BrokerNotRunningError(
                        f"PrivExec broker is not running (pipe '{path}' not found)."
                    )
                if err == err_access_denied:
                    raise PipeAccessDeniedError(
                        f"Access denied connecting to named pipe '{path}'."
                    )
                raise TransportError(f"Failed to open pipe '{path}': Win32 error {err}.")

        try:
            frame = struct.pack("<I", len(encoded)) + encoded
            _write_exact(kernel32, handle, frame)
            header = _read_exact(kernel32, handle, 4)
            (resp_len,) = struct.unpack("<I", header)
            if resp_len == 0 or resp_len > MAX_FRAME_BYTES:
                raise TransportError(f"Invalid response frame size: {resp_len} bytes.")
            body = _read_exact(kernel32, handle, resp_len)
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict):
                raise TransportError("Broker response must be a JSON object.")
            return data
        finally:
            kernel32.CloseHandle(handle)


def _configure_kernel32(kernel32: ctypes.WinDLL) -> None:
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.WaitNamedPipeW.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


def _write_exact(kernel32: ctypes.WinDLL, handle: Any, data: bytes) -> None:
    offset = 0
    written = wintypes.DWORD(0)
    while offset < len(data):
        chunk = data[offset:]
        buf = ctypes.create_string_buffer(chunk, len(chunk))
        ok = kernel32.WriteFile(handle, buf, len(chunk), ctypes.byref(written), None)
        if not ok:
            err = ctypes.get_last_error()
            raise TransportError(f"WriteFile failed on pipe: Win32 error {err}.")
        if written.value == 0:
            raise TransportError("WriteFile wrote 0 bytes to pipe.")
        offset += written.value


def _read_exact(kernel32: ctypes.WinDLL, handle: Any, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    read_bytes = wintypes.DWORD(0)
    while remaining > 0:
        buf = ctypes.create_string_buffer(remaining)
        ok = kernel32.ReadFile(handle, buf, remaining, ctypes.byref(read_bytes), None)
        if not ok:
            err = ctypes.get_last_error()
            raise TransportError(f"ReadFile failed on pipe: Win32 error {err}.")
        if read_bytes.value == 0:
            raise TransportError("Unexpected EOF reading from broker pipe.")
        chunks.append(buf.raw[: read_bytes.value])
        remaining -= read_bytes.value
    return b"".join(chunks)
