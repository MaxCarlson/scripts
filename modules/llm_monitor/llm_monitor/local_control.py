"""Local control channel and capability token management for LLM Monitor.

Provides a same-user, protected local IPC mechanism (Windows Named Pipe with SID ACL
and PIPE_REJECT_REMOTE_CLIENTS, or POSIX AF_UNIX socket) for issuing short-lived,
scoped read capability tokens to authorized benchmark/diagnostic clients without
requiring manual browser login codes or persistent cookie files.
"""

from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass
import hmac
import json
import os
from pathlib import Path
import secrets
import struct
import sys
import threading
import time
from typing import Any

from .server_lifecycle import get_current_owner_identity

PROTOCOL_VERSION = 1
MAX_FRAME_SIZE = 65536  # 64 KiB
DEFAULT_CAPABILITY_TTL = 120.0  # seconds

ALLOWED_READ_SCOPES = {
    "inference:models:read",
    "inference:status:read",
    "recording:health:read",
    "requests:summary:read",
    "history:verification:read",
}


@dataclass(frozen=True)
class LocalCapabilityToken:
    """Short-lived, memory-only capability token bound to an instance and scopes."""

    token: str
    instance_id: str
    issued_scopes: list[str]
    issued_at: float
    expires_at: float

    @property
    def expires_in_seconds(self) -> float:
        return max(0.0, self.expires_at - time.time())

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class LocalCapabilityManager:
    """Manages creation, verification, and revocation of short-lived capability tokens."""

    def __init__(self, instance_id: str) -> None:
        self.instance_id = instance_id
        self._tokens: dict[str, LocalCapabilityToken] = {}
        self._lock = threading.Lock()

    def issue_read_capability(
        self,
        requested_scopes: list[str] | None = None,
        ttl_seconds: float = DEFAULT_CAPABILITY_TTL,
    ) -> LocalCapabilityToken:
        """Issue a new scoped read capability token."""
        now = time.time()
        ttl = max(0.05, min(float(ttl_seconds), 300.0))
        if requested_scopes is None:
            scopes = sorted(ALLOWED_READ_SCOPES)
        else:
            scopes = sorted(s for s in requested_scopes if s in ALLOWED_READ_SCOPES)
            if not scopes:
                scopes = sorted(ALLOWED_READ_SCOPES)

        token = secrets.token_urlsafe(32)
        record = LocalCapabilityToken(
            token=token,
            instance_id=self.instance_id,
            issued_scopes=scopes,
            issued_at=now,
            expires_at=now + ttl,
        )

        with self._lock:
            # Prune expired tokens
            self._prune_expired_locked(now)
            self._tokens[token] = record

        return record

    def verify_token(self, token: str, required_scope: str, instance_id: str) -> bool:
        """Verify that token is valid, unexpired, matches instance, and holds required scope."""
        if not token or not instance_id:
            return False

        with self._lock:
            record = self._tokens.get(token)
            if record is None:
                return False

            # Constant-time compare token
            if not hmac.compare_digest(record.token, token):
                return False

            if record.instance_id != instance_id:
                return False

            if record.is_expired:
                self._tokens.pop(token, None)
                return False

            if required_scope not in record.issued_scopes:
                return False

            return True

    def revoke_token(self, token: str) -> bool:
        """Explicitly revoke a token."""
        with self._lock:
            return self._tokens.pop(token, None) is not None

    def revoke_all(self) -> None:
        """Revoke all tokens (e.g. on shutdown or restart)."""
        with self._lock:
            self._tokens.clear()

    def _prune_expired_locked(self, now: float) -> None:
        expired = [t for t, rec in self._tokens.items() if rec.expires_at <= now]
        for t in expired:
            self._tokens.pop(t, None)


def _build_windows_security_attributes() -> Any:
    """Build Windows SECURITY_ATTRIBUTES granting access to current user SID and SYSTEM only."""
    import win32api  # type: ignore
    import win32security  # type: ignore

    user_name = win32api.GetUserName()
    user_sid, _, _ = win32security.LookupAccountName(None, user_name)
    sid_str = win32security.ConvertSidToStringSid(user_sid)

    # Discretionary ACL: Full access to User SID (GA) and SYSTEM (GA), deny others
    sddl = f"D:(A;;GA;;;{sid_str})(A;;GA;;;SY)"
    sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        sddl, win32security.SDDL_REVISION_1
    )
    sa = win32security.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    sa.bInheritHandle = False
    return sa


class LocalControlServer:
    """Protected local IPC server accepting control commands over named pipe or AF_UNIX."""

    def __init__(
        self,
        instance_id: str,
        capability_manager: LocalCapabilityManager,
        state_dir: Path | str | None = None,
    ) -> None:
        self.instance_id = instance_id
        self.capability_manager = capability_manager
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.ready_event = threading.Event()

        if sys.platform == "win32":
            # Windows named pipe
            self.endpoint = rf"\\.\pipe\llm-monitor-{instance_id}"
            self._is_pipe = True
            self._pipe_handle: Any = None
        else:
            # POSIX domain socket
            self._is_pipe = False
            base_dir = Path(state_dir) if state_dir else Path(f"/tmp/llm_monitor_{os.getuid()}")
            base_dir.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                os.chmod(base_dir, 0o700)
            self.endpoint = str(base_dir / f"control_{instance_id}.sock")

    def start(self) -> None:
        """Start the local control server thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self.ready_event.clear()
        self._thread = threading.Thread(target=self._run, name="LocalControlServer", daemon=True)
        self._thread.start()
        self.ready_event.wait(timeout=2.0)

    def stop(self) -> None:
        """Stop the server thread and clean up endpoints."""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()

        if sys.platform == "win32":
            # Wake up any blocked ConnectNamedPipe by attempting a local connection
            try:
                import win32file
                handle = win32file.CreateFile(
                    self.endpoint,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None,
                )
                win32file.CloseHandle(handle)
            except Exception:
                pass
        else:
            with contextlib.suppress(OSError):
                Path(self.endpoint).unlink()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.capability_manager.revoke_all()

    def _run(self) -> None:
        if sys.platform == "win32":
            self._run_windows_pipe()
        else:
            self._run_posix_socket()

    def _run_windows_pipe(self) -> None:
        import win32file
        import win32pipe

        sa = _build_windows_security_attributes()
        pipe_flags = getattr(win32pipe, "PIPE_REJECT_REMOTE_CLIENTS", 8)
        self.ready_event.set()

        while self._running:
            pipe = win32pipe.CreateNamedPipe(
                self.endpoint,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT | pipe_flags,
                win32pipe.PIPE_UNLIMITED_INSTANCES,
                MAX_FRAME_SIZE,
                MAX_FRAME_SIZE,
                0,
                sa,
            )
            if self._stop_event.is_set() or not self._running:
                win32file.CloseHandle(pipe)
                break

            try:
                try:
                    win32pipe.ConnectNamedPipe(pipe, None)
                except Exception as conn_err:
                    import pywintypes
                    if isinstance(conn_err, pywintypes.error) and conn_err.winerror == 535:  # ERROR_PIPE_CONNECTED
                        pass
                    else:
                        raise

                if self._stop_event.is_set() or not self._running:
                    win32pipe.DisconnectNamedPipe(pipe)
                    win32file.CloseHandle(pipe)
                    break

                self._handle_client_pipe(pipe)
            except Exception:
                pass
            finally:
                with contextlib.suppress(Exception):
                    win32pipe.DisconnectNamedPipe(pipe)
                with contextlib.suppress(Exception):
                    win32file.CloseHandle(pipe)

    def _handle_client_pipe(self, pipe: Any) -> None:
        import win32file

        try:
            err, length_bytes = win32file.ReadFile(pipe, 4)
            if len(length_bytes) < 4:
                return
            length = struct.unpack("!I", length_bytes)[0]
            if length > MAX_FRAME_SIZE or length <= 0:
                return

            err, data = win32file.ReadFile(pipe, length)
            req = json.loads(data.decode("utf-8"))
            resp = self._dispatch(req)
            resp_bytes = json.dumps(resp).encode("utf-8")
            frame = struct.pack("!I", len(resp_bytes)) + resp_bytes
            win32file.WriteFile(pipe, frame)
            win32file.FlushFileBuffers(pipe)
        except Exception:
            pass

    def _run_posix_socket(self) -> None:
        import socket

        sock_path = Path(self.endpoint)
        if sock_path.exists():
            sock_path.unlink()

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(str(sock_path))
        with contextlib.suppress(OSError):
            os.chmod(str(sock_path), 0o600)
        server_sock.listen(16)
        server_sock.settimeout(0.5)
        self.ready_event.set()

        while self._running and not self._stop_event.is_set():
            try:
                conn, _ = server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                self._handle_client_socket(conn)
            finally:
                conn.close()

        server_sock.close()
        with contextlib.suppress(OSError):
            sock_path.unlink()

    def _handle_client_socket(self, conn: Any) -> None:
        try:
            length_bytes = conn.recv(4)
            if len(length_bytes) < 4:
                return
            length = struct.unpack("!I", length_bytes)[0]
            if length > MAX_FRAME_SIZE or length <= 0:
                return
            data = b""
            while len(data) < length:
                chunk = conn.recv(min(length - len(data), 4096))
                if not chunk:
                    break
                data += chunk

            req = json.loads(data.decode("utf-8"))
            resp = self._dispatch(req)
            resp_bytes = json.dumps(resp).encode("utf-8")
            conn.sendall(struct.pack("!I", len(resp_bytes)) + resp_bytes)
        except Exception:
            pass

    def _dispatch(self, req: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a single control command and return the JSON response."""
        req_inst = req.get("instance_id")
        if req_inst != self.instance_id:
            return {
                "protocol_version": PROTOCOL_VERSION,
                "error": "INSTANCE_ID_MISMATCH",
                "detail": f"Request instance {req_inst!r} does not match server {self.instance_id!r}",
            }

        cmd = req.get("command")
        req_id = req.get("request_id")

        if cmd == "hello":
            return {
                "protocol_version": PROTOCOL_VERSION,
                "status": "ok",
                "instance_id": self.instance_id,
                "capabilities": ["issue_read_capability", "revoke_capability"],
            }

        if cmd == "issue_read_capability":
            scopes = req.get("requested_scopes")
            ttl = float(req.get("ttl_seconds", DEFAULT_CAPABILITY_TTL))
            record = self.capability_manager.issue_read_capability(scopes, ttl_seconds=ttl)
            return {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": req_id,
                "instance_id": self.instance_id,
                "capability_token": record.token,
                "expires_in_seconds": record.expires_in_seconds,
                "issued_scopes": record.issued_scopes,
            }

        if cmd == "revoke_capability":
            token = req.get("token")
            ok = self.capability_manager.revoke_token(token or "")
            return {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": req_id,
                "instance_id": self.instance_id,
                "status": "revoked" if ok else "not_found",
            }

        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": req_id,
            "error": "UNKNOWN_COMMAND",
            "detail": f"Unrecognized command {cmd!r}",
        }


class LocalControlClient:
    """Client for communicating with a LocalControlServer."""

    def __init__(self, endpoint: str, instance_id: str, timeout: float = 3.0) -> None:
        self.endpoint = endpoint
        self.instance_id = instance_id
        self.timeout = timeout

    def hello(self) -> dict[str, Any]:
        return self._send_command({"command": "hello"})

    def issue_read_capability(
        self,
        requested_scopes: list[str] | None = None,
        ttl_seconds: float = DEFAULT_CAPABILITY_TTL,
    ) -> dict[str, Any]:
        req: dict[str, Any] = {
            "command": "issue_read_capability",
            "request_id": secrets.token_hex(8),
            "ttl_seconds": ttl_seconds,
        }
        if requested_scopes is not None:
            req["requested_scopes"] = requested_scopes
        return self._send_command(req)

    def revoke_capability(self, token: str) -> dict[str, Any]:
        return self._send_command(
            {
                "command": "revoke_capability",
                "request_id": secrets.token_hex(8),
                "token": token,
            }
        )

    def _send_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        full_payload = {
            "protocol_version": PROTOCOL_VERSION,
            "instance_id": self.instance_id,
            **payload,
        }
        data = json.dumps(full_payload).encode("utf-8")
        frame = struct.pack("!I", len(data)) + data

        if sys.platform == "win32":
            return self._send_windows_pipe(frame)
        else:
            return self._send_posix_socket(frame)

    def _send_windows_pipe(self, frame: bytes) -> dict[str, Any]:
        import win32file
        import pywintypes

        deadline = time.time() + self.timeout
        handle = None
        while time.time() < deadline:
            try:
                handle = win32file.CreateFile(
                    self.endpoint,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None,
                )
                break
            except pywintypes.error as e:
                # 2 = ERROR_FILE_NOT_FOUND, 231 = ERROR_PIPE_BUSY
                if e.winerror in (2, 231):
                    time.sleep(0.02)
                    continue
                raise
        if handle is None:
            raise TimeoutError(f"Timed out waiting to connect to named pipe {self.endpoint}")

        try:
            win32file.WriteFile(handle, frame)
            err, length_bytes = win32file.ReadFile(handle, 4)
            length = struct.unpack("!I", length_bytes)[0]
            err, resp_bytes = win32file.ReadFile(handle, length)
            return json.loads(resp_bytes.decode("utf-8"))
        finally:
            win32file.CloseHandle(handle)

    def _send_posix_socket(self, frame: bytes) -> dict[str, Any]:
        import socket

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.endpoint)
        try:
            sock.sendall(frame)
            length_bytes = sock.recv(4)
            length = struct.unpack("!I", length_bytes)[0]
            data = b""
            while len(data) < length:
                chunk = sock.recv(min(length - len(data), 4096))
                if not chunk:
                    break
                data += chunk
            return json.loads(data.decode("utf-8"))
        finally:
            sock.close()
