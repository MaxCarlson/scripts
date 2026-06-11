"""Local IPC helpers for runmux supervisors."""

from __future__ import annotations

import json
import socket
from typing import Any

from runmux.constants import DEFAULT_SOCKET_TIMEOUT_SECONDS
from runmux.models import RunRecord


class IpcError(RuntimeError):
    """Raised when an IPC request fails."""


class IpcAuthError(IpcError):
    """Raised when the supervisor rejects authentication."""


def encode_request(request: dict[str, Any]) -> bytes:
    """Encode a JSON-line IPC request."""

    return (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")


def read_json_line(sock: socket.socket) -> dict[str, Any]:
    """Read a single JSON line from a socket."""

    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(1)
        if not chunk:
            raise IpcError("Connection closed before a JSON response was received.")
        if chunk == b"\n":
            break
        chunks.append(chunk)
    try:
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except json.JSONDecodeError as error:
        raise IpcError(f"Invalid JSON response from supervisor: {error}") from error
    if not isinstance(value, dict):
        raise IpcError("Supervisor returned a non-object JSON response.")
    return value


def request_json(
    record: RunRecord,
    *,
    op: str,
    payload: dict[str, Any] | None = None,
    timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Send a request to a supervisor and return the JSON response."""

    if record.port is None:
        raise IpcError(f"Run '{record.id}' does not currently have an active supervisor port.")

    request = {"token": record.auth_token, "op": op}
    if payload:
        request.update(payload)

    try:
        with socket.create_connection(("127.0.0.1", record.port), timeout=timeout) as sock:
            sock.sendall(encode_request(request))
            response = read_json_line(sock)
    except OSError as error:
        raise IpcError(f"Could not contact supervisor for run '{record.id}': {error}") from error

    if response.get("ok") is not True:
        message = str(response.get("error") or "Supervisor request failed.")
        if response.get("code") == "auth":
            raise IpcAuthError(message)
        raise IpcError(message)
    return response


def open_input_socket(
    record: RunRecord, *, timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS
) -> socket.socket:
    """Open an authenticated raw input socket to a running supervisor."""

    if record.port is None:
        raise IpcError(f"Run '{record.id}' does not currently have an active supervisor port.")

    try:
        sock = socket.create_connection(("127.0.0.1", record.port), timeout=timeout)
        sock.sendall(encode_request({"token": record.auth_token, "op": "input"}))
        response = read_json_line(sock)
    except OSError as error:
        raise IpcError(f"Could not open input channel for run '{record.id}': {error}") from error

    if response.get("ok") is not True:
        sock.close()
        message = str(response.get("error") or "Supervisor rejected input channel.")
        raise IpcError(message)

    sock.settimeout(None)
    return sock
