"""Runmux Web UI server lifecycle, instance discovery, and safe control."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

HEALTH_DOMAIN = "runmux-health-v1"
SHUTDOWN_DOMAIN = "runmux-shutdown-v1"


class ServerLifecycleError(RuntimeError):
    """Base exception for server lifecycle failures."""


class ServerSecurityError(ServerLifecycleError):
    """Raised when server descriptor permissions or identity verification fails."""


@dataclass
class ServerDescriptor:
    """Owner-scoped metadata describing an active or requested Runmux Web server."""

    instance_id: str
    version: int
    protocol: str
    host: str
    port: int
    state_dir: str
    pid: int
    process_create_time: float | None
    started_at: str
    access_code: str
    control_token: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerDescriptor:
        return cls(
            instance_id=str(data["instance_id"]),
            version=int(data["version"]),
            protocol=str(data["protocol"]),
            host=str(data["host"]),
            port=int(data["port"]),
            state_dir=str(data["state_dir"]),
            pid=int(data["pid"]),
            process_create_time=(
                float(data["process_create_time"])
                if data.get("process_create_time") is not None
                else None
            ),
            started_at=str(data["started_at"]),
            access_code=str(data["access_code"]),
            control_token=str(data["control_token"]),
        )


def normalize_host_for_filename(host: str) -> str:
    """Normalize host address into a filesystem-safe identifier."""
    clean = host.strip("[]").replace(":", "_").replace("/", "_")
    return clean or "127.0.0.1"


def descriptor_dir(state_dir: Path | str) -> Path:
    """Return the owner-scoped web directory within the state tree."""
    directory = Path(state_dir).resolve() / "web"
    directory.mkdir(parents=True, exist_ok=True)
    enforce_owner_permissions(directory, is_dir=True)
    return directory


def descriptor_path(state_dir: Path | str, host_or_port: str | int, port: int | None = None) -> Path:
    """Return the descriptor file path for a given host and port."""
    if port is None:
        target_port = int(host_or_port)
        host_str = "127.0.0.1"
    else:
        host_str = str(host_or_port)
        target_port = int(port)

    clean_host = normalize_host_for_filename(host_str)
    specific_path = descriptor_dir(state_dir) / f"server_{clean_host}_{target_port}.json"
    if specific_path.exists():
        return specific_path
    legacy_path = descriptor_dir(state_dir) / f"server_{target_port}.json"
    if legacy_path.exists():
        return legacy_path
    return specific_path


def is_reparse_point_or_symlink(path: Path) -> bool:
    """Check whether a path is a symbolic link or a junction/reparse point."""
    if path.is_symlink() or os.path.islink(path):
        return True
    if sys.platform == "win32" and path.exists():
        try:
            st = os.lstat(path)
            # 0x0400 is FILE_ATTRIBUTE_REPARSE_POINT (junction, symlink, mount point)
            if getattr(st, "st_file_attributes", 0) & 0x0400:
                return True
        except OSError:
            return True
    return False


def enforce_owner_permissions(path: Path, is_dir: bool = False) -> None:
    """Restrict access permissions exclusively to the current owner."""
    if is_reparse_point_or_symlink(path):
        raise ServerSecurityError(f"Symbolic link or reparse point detected at {path}; prohibited.")

    if sys.platform == "win32":
        username = os.environ.get("USERNAME")
        if username and shutil.which("icacls"):
            result = subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:(F)"],
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", errors="replace")
                raise ServerSecurityError(f"Failed to enforce owner-only ACL on {path}: {err}")
    else:
        mode = 0o700 if is_dir else 0o600
        try:
            os.chmod(path, mode)
        except OSError as err:
            raise ServerSecurityError(f"Failed to enforce owner-only mode on {path}: {err}") from err


def verify_owner_permissions(path: Path) -> bool:
    """Verify that path exists, is not a symlink/reparse point, and is owned by the current user."""
    if not path.exists():
        return False
    if is_reparse_point_or_symlink(path):
        raise ServerSecurityError(f"Symbolic link or reparse point detected at {path}; prohibited.")

    if sys.platform != "win32":
        try:
            st = path.stat()
            if st.st_uid != os.getuid():
                return False
            # Check no group/other read/write/execute
            if st.st_mode & 0o077:
                return False
        except OSError:
            return False
    return True


def write_descriptor(path: Path, descriptor: ServerDescriptor) -> None:
    """Atomically write an owner-protected instance descriptor."""
    if is_reparse_point_or_symlink(path):
        raise ServerSecurityError(f"Symbolic link or reparse point detected at {path}; refusing to overwrite.")

    path.parent.mkdir(parents=True, exist_ok=True)
    enforce_owner_permissions(path.parent, is_dir=True)

    temp_path = path.parent / f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    data = json.dumps(descriptor.to_dict(), indent=2).encode("utf-8")

    try:
        if sys.platform != "win32":
            # Atomically create with 0600 mode on POSIX
            fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        else:
            temp_path.write_bytes(data)
            enforce_owner_permissions(temp_path, is_dir=False)

        os.replace(temp_path, path)
        enforce_owner_permissions(path, is_dir=False)
    except Exception:
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()
        raise


def read_descriptor(path: Path) -> ServerDescriptor | None:
    """Read and validate a server descriptor, rejecting symlinks and malformed files."""
    if not path.exists():
        return None
    if is_reparse_point_or_symlink(path):
        raise ServerSecurityError(f"Symbolic link or reparse point detected at {path}; refusing to read.")

    if not verify_owner_permissions(path):
        raise ServerSecurityError(f"Insecure permissions or ownership on descriptor at {path}.")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return ServerDescriptor.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return None


def remove_descriptor(path: Path) -> bool:
    """Safely remove a descriptor file if it exists."""
    if is_reparse_point_or_symlink(path):
        raise ServerSecurityError(f"Symbolic link or reparse point detected at {path}; refusing to remove.")
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def list_descriptors(state_dir: Path | str) -> list[ServerDescriptor]:
    """Scan and return all valid descriptors in the state directory."""
    directory = Path(state_dir).resolve() / "web"
    if not directory.is_dir() or is_reparse_point_or_symlink(directory):
        return []

    descriptors: list[ServerDescriptor] = []
    for item in sorted(directory.glob("server_*.json")):
        if item.is_file() and not is_reparse_point_or_symlink(item):
            try:
                desc = read_descriptor(item)
                if desc is not None:
                    descriptors.append(desc)
            except ServerSecurityError:
                continue
    return descriptors


def is_process_alive(pid: int, expected_create_time: float | None = None) -> bool:
    """Verify that a process with PID is alive and matches the expected creation time."""
    if not psutil.pid_exists(pid):
        return False
    try:
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return False
        return not (expected_create_time is not None and abs(proc.create_time() - expected_create_time) > 1.0)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def compute_challenge_hmac(token: str, instance_id: str, challenge: str) -> str:
    """Compute HMAC-SHA256 signature for health challenge with explicit domain separation."""
    message = f"{HEALTH_DOMAIN}:{instance_id}:{challenge}"
    return hmac.new(token.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_shutdown_hmac(token: str, instance_id: str, timestamp: float, nonce: str) -> str:
    """Compute HMAC-SHA256 signature for authenticated shutdown with explicit domain separation."""
    message = f"{SHUTDOWN_DOMAIN}:{instance_id}:POST:/_runmux/control/shutdown:{timestamp:.3f}:{nonce}"
    return hmac.new(token.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_running_instance(descriptor: ServerDescriptor, timeout: float = 2.0) -> bool:
    """Verify that the live server matches the descriptor using challenge-response."""
    if not is_process_alive(descriptor.pid, descriptor.process_create_time):
        return False

    challenge = secrets.token_hex(16)
    expected_sig = compute_challenge_hmac(descriptor.control_token, descriptor.instance_id, challenge)

    host = descriptor.host
    http_host = f"[{host}]" if ":" in host and not host.startswith("[") else host

    try:
        conn = http.client.HTTPConnection(descriptor.host, descriptor.port, timeout=timeout)
        conn.request(
            "GET",
            f"/_runmux/health?challenge={challenge}",
            headers={"Host": f"{http_host}:{descriptor.port}"},
        )
        resp = conn.getresponse()
        if resp.status != 200:
            conn.close()
            return False
        payload = json.loads(resp.read().decode("utf-8"))
        conn.close()

        if payload.get("status") != "ok":
            return False
        if payload.get("instance_id") != descriptor.instance_id:
            return False
        if payload.get("pid") != descriptor.pid:
            return False
        sig = payload.get("signature")
        return bool(sig and hmac.compare_digest(sig, expected_sig))
    except (OSError, http.client.HTTPException, json.JSONDecodeError, ValueError):
        return False


def request_instance_shutdown(descriptor: ServerDescriptor, timeout: float = 5.0) -> bool:
    """Send an authenticated signed shutdown command to the verified running server."""
    timestamp = time.time()
    nonce = secrets.token_hex(16)
    signature = compute_shutdown_hmac(descriptor.control_token, descriptor.instance_id, timestamp, nonce)

    host = descriptor.host
    http_host = f"[{host}]" if ":" in host and not host.startswith("[") else host

    body = json.dumps(
        {
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature,
        }
    ).encode("utf-8")

    try:
        conn = http.client.HTTPConnection(descriptor.host, descriptor.port, timeout=timeout)
        conn.request(
            "POST",
            "/_runmux/control/shutdown",
            body=body,
            headers={
                "Host": f"{http_host}:{descriptor.port}",
                "Content-Type": "application/json",
            },
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return resp.status == 200 and data.get("status") == "shutting_down"
    except (OSError, http.client.HTTPException, json.JSONDecodeError, ValueError):
        return False


def bind_loopback_socket(host: str, port: int) -> socket.socket:
    """Safely pre-bind a loopback socket with exclusive address options."""
    family = socket.AF_INET6 if (":" in host) else socket.AF_INET
    sock = socket.socket(family=family, type=socket.SOCK_STREAM)

    if sys.platform == "win32":
        with contextlib.suppress(OSError):
            # SO_EXCLUSIVEADDRUSE prevents port hijacking / reuse races on Windows
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    sock.bind((host, port))
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


class ShutdownPayload(BaseModel):
    """Authenticated shutdown payload."""

    timestamp: float
    nonce: str
    signature: str


def mount_control_routes(
    app: FastAPI,
    descriptor: ServerDescriptor,
    shutdown_event: asyncio.Event,
) -> None:
    """Mount internal challenge health check and signed shutdown routes."""
    if not hasattr(app.state, "seen_shutdown_nonces"):
        app.state.seen_shutdown_nonces = {}

    @app.get("/_runmux/health", include_in_schema=False)
    async def runmux_health(challenge: str | None = None) -> Response:
        resp_data: dict[str, Any] = {
            "status": "ok",
            "instance_id": descriptor.instance_id,
        }
        if challenge:
            resp_data["signature"] = compute_challenge_hmac(descriptor.control_token, descriptor.instance_id, challenge)
            resp_data["pid"] = os.getpid()
        return Response(
            content=json.dumps(resp_data),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/_runmux/control/shutdown", include_in_schema=False)
    async def runmux_shutdown(payload: ShutdownPayload, request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise HTTPException(status_code=403, detail="Forbidden cross-origin shutdown request")

        now = time.time()
        if abs(now - payload.timestamp) > 30.0:
            raise HTTPException(status_code=403, detail="Shutdown request timestamp expired or invalid")

        # Concurrency-safe, bounded nonce replay check
        seen = app.state.seen_shutdown_nonces
        expired_keys = [k for k, exp in seen.items() if exp < now]
        for k in expired_keys:
            seen.pop(k, None)

        if payload.nonce in seen:
            raise HTTPException(status_code=403, detail="Shutdown nonce already used (replay rejected)")
        seen[payload.nonce] = now + 60.0

        expected_sig = compute_shutdown_hmac(
            descriptor.control_token,
            descriptor.instance_id,
            payload.timestamp,
            payload.nonce,
        )
        if not hmac.compare_digest(payload.signature, expected_sig):
            raise HTTPException(status_code=403, detail="Invalid shutdown authorization signature")

        shutdown_event.set()
        server = getattr(app.state, "server", None)
        if server is not None:
            server.should_exit = True

        return Response(
            content=json.dumps({"status": "shutting_down"}),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


def find_target_descriptor(
    state_dir: Path | str,
    port: int | None = None,
    host: str = "127.0.0.1",
) -> tuple[ServerDescriptor | None, str | None]:
    """Find the target descriptor, disambiguating if needed."""
    resolved_state_dir = Path(state_dir).resolve()
    if port is not None:
        p = descriptor_path(resolved_state_dir, host, port)
        desc = read_descriptor(p)
        return (desc, None)

    descriptors = list_descriptors(resolved_state_dir)
    if not descriptors:
        default_p = descriptor_path(resolved_state_dir, host, 8787)
        desc = read_descriptor(default_p)
        return (desc, None)

    if len(descriptors) == 1:
        return (descriptors[0], None)

    ports = ", ".join(f"{d.host}:{d.port}" for d in descriptors)
    return (
        None,
        f"Multiple Runmux Web servers are running ({ports}). Specify -p/--port to select an instance.",
    )


def stop_server(
    state_dir: Path | str,
    port: int | None = None,
    host: str = "127.0.0.1",
    timeout: float = 5.0,
    as_json: bool = False,
) -> int:
    """Stop the running Runmux Web server gracefully."""
    resolved_state_dir = Path(state_dir).resolve()
    descriptor, error_msg = find_target_descriptor(resolved_state_dir, port, host)
    if error_msg:
        if as_json:
            print(json.dumps({"status": "error", "error": error_msg}))
        else:
            print(f"runmux: web: {error_msg}", file=sys.stderr)
        return 1

    if descriptor is None:
        if as_json:
            print(json.dumps({"status": "not_running", "stopped": True}))
        else:
            print("Runmux Web UI")
            print("Status: Not running\n")
            print("No matching server needs to be stopped.")
        return 0

    desc_path = descriptor_path(resolved_state_dir, descriptor.host, descriptor.port)
    if not is_process_alive(descriptor.pid, descriptor.process_create_time):
        remove_descriptor(desc_path)
        if as_json:
            print(json.dumps({"status": "not_running", "stopped": True}))
        else:
            print("Runmux Web UI")
            print("Status: Not running\n")
            print("No matching server needs to be stopped.")
        return 0

    if not verify_running_instance(descriptor):
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "unverifiable",
                        "error": (
                            f"Process {descriptor.pid} on port {descriptor.port} "
                            "could not be verified as genuine Runmux."
                        ),
                    }
                )
            )
        else:
            print("Runmux Web UI", file=sys.stderr)
            print("Status: Unverifiable", file=sys.stderr)
            print(
                f"Error: Process {descriptor.pid} on port {descriptor.port} could not be verified as genuine Runmux.",
                file=sys.stderr,
            )
        return 1

    browser_host = f"[{descriptor.host}]" if ":" in descriptor.host else descriptor.host
    url = f"http://{browser_host}:{descriptor.port}/"

    if not as_json:
        print("Runmux Web UI")
        print("Status: Stopping")
        print(f"URL:    {url}")
        print(f"PID:    {descriptor.pid}\n")

    requested = request_instance_shutdown(descriptor, timeout=timeout)
    if not requested and not as_json:
        print("Warning: Shutdown request did not receive expected acknowledgement.", file=sys.stderr)

    deadline = time.time() + timeout
    stopped = False
    while time.time() < deadline:
        if not is_process_alive(descriptor.pid, descriptor.process_create_time):
            stopped = True
            break
        time.sleep(0.1)

    remove_descriptor(desc_path)

    if stopped:
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "stopped",
                        "stopped": True,
                        "pid": descriptor.pid,
                        "url": url,
                    }
                )
            )
        else:
            print("Server stopped successfully.")
            print("Managed processes remain running.")
        return 0

    if as_json:
        print(
            json.dumps(
                {
                    "status": "timeout",
                    "stopped": False,
                    "pid": descriptor.pid,
                    "warning": f"Server process {descriptor.pid} did not exit within {timeout} seconds.",
                }
            )
        )
    else:
        print(f"Warning: Server process {descriptor.pid} did not exit within {timeout} seconds.", file=sys.stderr)
        print("Managed processes remain running.")
    return 1


def status_server(
    state_dir: Path | str,
    port: int | None = None,
    host: str = "127.0.0.1",
    as_json: bool = False,
) -> int:
    """Report the status of the Runmux Web server without modifying state."""
    resolved_state_dir = Path(state_dir).resolve()
    descriptor, error_msg = find_target_descriptor(resolved_state_dir, port, host)
    if error_msg:
        if as_json:
            print(json.dumps({"status": "error", "error": error_msg}))
        else:
            print(f"runmux: web: {error_msg}", file=sys.stderr)
        return 1

    if descriptor is None:
        if as_json:
            print(json.dumps({"status": "not_running", "running": False}))
        else:
            print("Runmux Web UI")
            print("Status: Not running")
        return 0

    browser_host = f"[{descriptor.host}]" if ":" in descriptor.host else descriptor.host
    url = f"http://{browser_host}:{descriptor.port}/"

    if not is_process_alive(descriptor.pid, descriptor.process_create_time):
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "not_running",
                        "running": False,
                        "stale_descriptor": True,
                        "pid": descriptor.pid,
                        "warning": f"Stale descriptor found for PID {descriptor.pid} (process not running).",
                    }
                )
            )
        else:
            print("Runmux Web UI")
            print("Status: Not running")
            print(f"Warning: Stale descriptor found for PID {descriptor.pid} (process not running).")
        return 0

    if not verify_running_instance(descriptor):
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "unverifiable",
                        "running": False,
                        "url": url,
                        "pid": descriptor.pid,
                        "warning": "Process is running but did not pass Runmux instance verification.",
                    }
                )
            )
        else:
            print("Runmux Web UI")
            print("Status: Unverifiable")
            print(f"URL:    {url}")
            print(f"PID:    {descriptor.pid}")
            print("Warning: Process is running but did not pass Runmux instance verification.")
        return 1

    if as_json:
        print(
            json.dumps(
                {
                    "status": "running",
                    "running": True,
                    "url": url,
                    "access_code": descriptor.access_code,
                    "pid": descriptor.pid,
                    "state_dir": descriptor.state_dir,
                    "host": descriptor.host,
                    "port": descriptor.port,
                },
                indent=2,
            )
        )
        return 0

    print("Runmux Web UI")
    print("Status: Running")
    print(f"URL:    {url}")
    print(f"Access code: {descriptor.access_code}")
    print(f"PID:    {descriptor.pid}")
    print(f"State directory: {descriptor.state_dir}")
    return 0


class RunmuxWebServer(uvicorn.Server):
    """Uvicorn server subclass that signals when lifespan startup and socket listening succeed."""

    def __init__(self, config: uvicorn.Config, on_ready: Callable[[], None] | None = None) -> None:
        super().__init__(config)
        self.on_ready = on_ready
        self.ready_event = asyncio.Event()

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started and not self.should_exit:
            self.ready_event.set()
            if self.on_ready:
                self.on_ready()


def run_web_server(
    state_dir: Path | str,
    host: str = "127.0.0.1",
    port: int = 8787,
    no_telemetry_history: bool = False,
) -> int:
    """Start or discover an existing Runmux Web server."""
    resolved_state_dir = Path(state_dir).resolve()
    desc_path = descriptor_path(resolved_state_dir, host, port)
    browser_host = f"[{host}]" if ":" in host else host
    url = f"http://{browser_host}:{port}/"

    # Step 1: Check if an instance is already registered for this host and port
    existing = read_descriptor(desc_path)
    if (
        existing is not None
        and is_process_alive(existing.pid, existing.process_create_time)
        and verify_running_instance(existing)
    ):
        print("Runmux Web UI")
        print("Status: Already running")
        print(f"URL:    {url}")
        print(f"Access code: {existing.access_code}")
        print(f"PID:    {existing.pid}\n")
        if no_telemetry_history:
            print("Note: Preserved running server's active telemetry configuration.\n")
        print("The existing server was left running.")
        return 0

    if existing is not None:
        remove_descriptor(desc_path)

    # Step 2: Attempt to pre-bind the loopback socket
    try:
        sock = bind_loopback_socket(host, port)
    except OSError as err:
        deadline = time.time() + 2.0
        while time.time() < deadline:
            time.sleep(0.1)
            cand = read_descriptor(desc_path)
            if (
                cand is not None
                and is_process_alive(cand.pid, cand.process_create_time)
                and verify_running_instance(cand)
            ):
                print("Runmux Web UI")
                print("Status: Already running")
                print(f"URL:    {url}")
                print(f"Access code: {cand.access_code}")
                print(f"PID:    {cand.pid}\n")
                if no_telemetry_history:
                    print("Note: Preserved running server's active telemetry configuration.\n")
                print("The existing server was left running.")
                return 0

        print(
            f"runmux: web: Port {port} is already in use by an unrelated service or unresponsive process: {err}",
            file=sys.stderr,
        )
        return 1

    # Step 3: Socket bound successfully. Initialize application and descriptor.
    try:
        from web_ui_tools import LOOPBACK_HOSTS

        from runmux.web import create_runmux_web_app
    except ImportError:
        sock.close()
        print(
            "runmux: web: view dependencies are not installed; install the optional runmux web extra "
            "and the web-ui-tools package.",
            file=sys.stderr,
        )
        return 2

    login_code = secrets.token_urlsafe(24)
    control_token = secrets.token_urlsafe(32)
    instance_id = secrets.token_hex(16)
    my_pid = os.getpid()
    try:
        my_create_time = psutil.Process(my_pid).create_time()
    except Exception:
        my_create_time = None

    descriptor = ServerDescriptor(
        instance_id=instance_id,
        version=1,
        protocol="runmux_web_v1",
        host=host,
        port=port,
        state_dir=str(resolved_state_dir),
        pid=my_pid,
        process_create_time=my_create_time,
        started_at=datetime.now(timezone.utc).isoformat(),
        access_code=login_code,
        control_token=control_token,
    )

    enable_telemetry_history = not no_telemetry_history
    if os.environ.get("RUNMUX_NO_TELEMETRY_HISTORY", "").lower() in {"1", "true", "yes"}:
        enable_telemetry_history = False

    try:
        app = create_runmux_web_app(
            resolved_state_dir,
            login_code=login_code,
            allowed_hosts=(*LOOPBACK_HOSTS, host),
            enable_telemetry_history=enable_telemetry_history,
        )
    except Exception as err:
        sock.close()
        print(f"runmux: web: application initialization failed: {err}", file=sys.stderr)
        return 1

    shutdown_event = asyncio.Event()
    mount_control_routes(app, descriptor, shutdown_event)

    # Write descriptor to disk before starting server
    try:
        write_descriptor(desc_path, descriptor)
    except Exception as err:
        sock.close()
        print(f"runmux: web: failed to write instance descriptor: {err}", file=sys.stderr)
        return 1

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        access_log=False,
        log_level="info",
        ws="wsproto",
    )

    def print_startup_banner():
        print("Runmux Web UI")
        print("Status: Started")
        print(f"URL:    {url}")
        print(f"Access code: {login_code}")
        print(f"PID:    {my_pid}\n")
        print("Press Ctrl+C to close the browser service; managed processes keep running.")

    server = RunmuxWebServer(config, on_ready=print_startup_banner)
    app.state.server = server

    async def _serve():
        async def _watcher():
            await shutdown_event.wait()
            server.should_exit = True

        watcher = asyncio.create_task(_watcher())
        try:
            await server.serve(sockets=[sock])
        finally:
            watcher.cancel()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        return 130
    finally:
        remove_descriptor(desc_path)
        with contextlib.suppress(OSError):
            sock.close()

    return 0
