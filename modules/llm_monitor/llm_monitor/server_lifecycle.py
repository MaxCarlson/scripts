"""LLM Monitor web server lifecycle, instance discovery, and safe control."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import asdict, dataclass
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
import psutil
import uvicorn

from .storage import default_database_path

HEALTH_DOMAIN = "llm-monitor-health-v1"
SHUTDOWN_DOMAIN = "llm-monitor-shutdown-v1"


class ServerLifecycleError(RuntimeError):
    """Base exception for server lifecycle failures."""


class ServerSecurityError(ServerLifecycleError):
    """Raised when server descriptor permissions or identity verification fails."""


@dataclass
class ServerDescriptor:
    """Owner-scoped metadata describing an active or requested LLM Monitor Web server."""

    instance_id: str
    version: int
    protocol: str
    host: str
    port: int
    pid: int
    process_create_time: float | None
    started_at: str
    control_token: str
    gateway_enabled: bool = False
    recording_mode: str | None = None
    database_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerDescriptor:
        return cls(
            instance_id=str(data["instance_id"]),
            version=int(data.get("version", 1)),
            protocol=str(data.get("protocol", "llm_monitor_web_v1")),
            host=str(data.get("host", "127.0.0.1")),
            port=int(data["port"]),
            pid=int(data["pid"]),
            process_create_time=(
                float(data["process_create_time"])
                if data.get("process_create_time") is not None
                else None
            ),
            started_at=str(data.get("started_at", "")),
            control_token=str(data["control_token"]),
            gateway_enabled=bool(data.get("gateway_enabled", False)),
            recording_mode=data.get("recording_mode"),
            database_path=data.get("database_path"),
        )


def normalize_host_for_filename(host: str) -> str:
    """Normalize host address into a filesystem-safe identifier."""
    clean = host.strip("[]").replace(":", "_").replace("/", "_")
    return clean or "127.0.0.1"


def default_runtime_dir(state_dir: Path | str | None = None) -> Path:
    """Return the owner-scoped directory for server instance descriptors."""
    if state_dir is not None:
        directory = Path(state_dir).resolve()
    elif "LLM_MONITOR_STATE_DIR" in os.environ:
        directory = Path(os.environ["LLM_MONITOR_STATE_DIR"]).resolve()
    else:
        directory = default_database_path().parent / "servers"

    directory.mkdir(parents=True, exist_ok=True)
    enforce_owner_permissions(directory, is_dir=True)
    return directory


def descriptor_path(
    port: int,
    host: str = "127.0.0.1",
    state_dir: Path | str | None = None,
) -> Path:
    """Return the descriptor file path for a given host and port."""
    dir_path = default_runtime_dir(state_dir)
    clean_host = normalize_host_for_filename(host)
    specific_path = dir_path / f"server_{clean_host}_{port}.json"
    if specific_path.exists():
        return specific_path
    legacy_path = dir_path / f"server_{port}.json"
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
            grant_spec = f"{username}:(OI)(CI)(F)" if is_dir else f"{username}:(F)"
            result = subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", grant_spec],
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

    if sys.platform == "win32":
        username = os.environ.get("USERNAME")
        if not username:
            return True
        if shutil.which("icacls"):
            proc = subprocess.run(
                ["icacls", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                return False
            output = proc.stdout.lower()
            # Strip path representations from output so path components like C:\Users do not trigger false positives
            norm_path = os.path.normpath(str(path)).lower()
            acl_text = output.replace(norm_path, "").replace(str(path).lower(), "")
            # Verify the current user is present
            if username.lower() not in acl_text:
                return False
            # Verify broad unauthorized groups are not granted access
            unauthorized = [
                "builtin\\users",
                ":\\users",
                "everyone",
                "authenticated users",
                "domain users",
            ]
            for group in unauthorized:
                if group in acl_text:
                    return False
        return True
    else:
        try:
            st = path.stat()
            if hasattr(os, "getuid") and st.st_uid != os.getuid():
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
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        fd = os.open(temp_path, flags, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        if sys.platform == "win32":
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


def remove_descriptor(path: Path, expected_instance_id: str | None = None) -> bool:
    """Safely remove a descriptor file if it exists, optionally verifying instance_id."""
    if is_reparse_point_or_symlink(path):
        raise ServerSecurityError(f"Symbolic link or reparse point detected at {path}; refusing to remove.")
    if expected_instance_id is not None and path.exists():
        desc = read_descriptor(path)
        if desc is not None and desc.instance_id != expected_instance_id:
            return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def list_descriptors(state_dir: Path | str | None = None) -> list[ServerDescriptor]:
    """Scan and return all valid descriptors in the runtime directory."""
    directory = default_runtime_dir(state_dir)
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
    """Verify that a process with PID is alive and optionally matches expected creation time."""
    if pid <= 0:
        return False
    if not psutil.pid_exists(pid):
        return False
    try:
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return False
        if expected_create_time is not None:
            return abs(proc.create_time() - expected_create_time) <= 1.0
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def verify_process_identity(descriptor: ServerDescriptor) -> bool:
    """Strictly verify process identity; missing PID or missing creation time cannot be verified."""
    if descriptor.pid <= 0 or descriptor.process_create_time is None:
        return False
    return is_process_alive(descriptor.pid, descriptor.process_create_time)


def compute_challenge_hmac(token: str, instance_id: str, challenge: str) -> str:
    """Compute HMAC-SHA256 signature for health challenge with explicit domain separation."""
    message = f"{HEALTH_DOMAIN}:{instance_id}:{challenge}"
    return hmac.new(token.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_shutdown_hmac(token: str, instance_id: str, timestamp: float, nonce: str) -> str:
    """Compute HMAC-SHA256 signature for authenticated shutdown with explicit domain separation."""
    message = f"{SHUTDOWN_DOMAIN}:{instance_id}:POST:/_llm_monitor/control/shutdown:{timestamp:.3f}:{nonce}"
    return hmac.new(token.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_running_instance(descriptor: ServerDescriptor, timeout: float = 2.0) -> dict[str, Any] | None:
    """Verify that the live server matches the descriptor using challenge-response."""
    if not is_process_alive(descriptor.pid, descriptor.process_create_time):
        return None

    challenge = secrets.token_hex(16)
    expected_sig = compute_challenge_hmac(descriptor.control_token, descriptor.instance_id, challenge)

    host = descriptor.host
    http_host = f"[{host}]" if ":" in host and not host.startswith("[") else host

    try:
        conn = http.client.HTTPConnection(descriptor.host, descriptor.port, timeout=timeout)
        conn.request(
            "GET",
            f"/_llm_monitor/health?challenge={challenge}",
            headers={"Host": f"{http_host}:{descriptor.port}"},
        )
        resp = conn.getresponse()
        if resp.status != 200:
            conn.close()
            return None
        payload = json.loads(resp.read().decode("utf-8"))
        conn.close()

        if payload.get("status") != "ok":
            return None
        if payload.get("instance_id") != descriptor.instance_id:
            return None
        if payload.get("pid") != descriptor.pid:
            return None
        sig = payload.get("signature")
        if not (sig and hmac.compare_digest(sig, expected_sig)):
            return None
        return payload
    except (OSError, http.client.HTTPException, json.JSONDecodeError, ValueError):
        return None


def request_instance_shutdown(descriptor: ServerDescriptor, timeout: float = 5.0) -> tuple[bool, str | None]:
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
            "/_llm_monitor/control/shutdown",
            body=body,
            headers={
                "Host": f"{http_host}:{descriptor.port}",
                "Content-Type": "application/json",
            },
        )
        resp = conn.getresponse()
        resp_bytes = resp.read().decode("utf-8")
        conn.close()
        try:
            data = json.loads(resp_bytes)
        except Exception:
            data = {}

        if resp.status == 200 and data.get("status") == "shutting_down":
            return (True, None)

        err_msg = data.get("detail") or data.get("error") or f"HTTP {resp.status}"
        return (False, err_msg)
    except (OSError, http.client.HTTPException, json.JSONDecodeError, ValueError) as exc:
        return (False, str(exc))


class ShutdownPayload(BaseModel):
    """Authenticated shutdown payload."""

    timestamp: float
    nonce: str
    signature: str


def mount_control_routes(
    app: FastAPI,
    descriptor: ServerDescriptor,
    shutdown_event: asyncio.Event,
    recorder: Any | None = None,
    live_store: Any | None = None,
) -> None:
    """Mount internal challenge health check and signed shutdown routes."""
    if not hasattr(app.state, "seen_shutdown_nonces"):
        app.state.seen_shutdown_nonces = {}

    @app.get("/_llm_monitor/health", include_in_schema=False)
    async def llm_monitor_health(challenge: str | None = None) -> Response:
        recorder_inst = recorder or getattr(app.state, "inference_recorder", None)
        resp_data: dict[str, Any] = {
            "status": "ok",
            "instance_id": descriptor.instance_id,
            "gateway_enabled": descriptor.gateway_enabled,
            "recording_mode": descriptor.recording_mode,
            "database_path": descriptor.database_path,
            "recorder_healthy": recorder_inst.is_healthy if recorder_inst is not None else None,
        }
        if challenge:
            resp_data["signature"] = compute_challenge_hmac(
                descriptor.control_token, descriptor.instance_id, challenge
            )
            resp_data["pid"] = os.getpid()
        return Response(
            content=json.dumps(resp_data),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/_llm_monitor/control/shutdown", include_in_schema=False)
    async def llm_monitor_shutdown(payload: ShutdownPayload, request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise HTTPException(status_code=403, detail="Forbidden cross-origin shutdown request")

        now = time.time()
        if abs(now - payload.timestamp) > 30.0:
            raise HTTPException(status_code=403, detail="Shutdown request timestamp expired or invalid")

        # Verify HMAC signature FIRST before modifying nonce tracking
        expected_sig = compute_shutdown_hmac(
            descriptor.control_token,
            descriptor.instance_id,
            payload.timestamp,
            payload.nonce,
        )
        if not hmac.compare_digest(payload.signature, expected_sig):
            raise HTTPException(status_code=403, detail="Invalid shutdown authorization signature")

        # Concurrency-safe, bounded nonce replay check
        seen: dict[str, float] = app.state.seen_shutdown_nonces
        expired_keys = [k for k, exp in seen.items() if exp < now]
        for k in expired_keys:
            seen.pop(k, None)

        if payload.nonce in seen:
            raise HTTPException(status_code=403, detail="Shutdown nonce already used (replay rejected)")
        if len(seen) > 1000:
            seen.clear()
        seen[payload.nonce] = now + 60.0

        # 1. Reject new inference requests
        app.state.shutting_down = True

        # 2. Allow active requests to finish within bounded shutdown period
        target_store = live_store or getattr(app.state, "live_store", None)
        if target_store is not None and hasattr(target_store, "active_request_count"):
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if target_store.active_request_count() == 0:
                    break
                await asyncio.sleep(0.05)

        # 3. Drain and flush the inference recorder
        recorder_inst = recorder or getattr(app.state, "inference_recorder", None)
        if recorder_inst is not None and hasattr(recorder_inst, "flush"):
            flush_ok = recorder_inst.flush(timeout=5.0)
            if not flush_ok:
                raise HTTPException(
                    status_code=500,
                    detail="Recorder shutdown flush timed out or failed; pending writes remain",
                )

        # 4. Trigger shutdown event and exit uvicorn server asynchronously to allow response flush
        shutdown_event.set()
        server = getattr(app.state, "server", None)
        if server is not None:
            async def _schedule_exit(srv: Any) -> None:
                await asyncio.sleep(0.05)
                srv.should_exit = True

            asyncio.create_task(_schedule_exit(server))

        return Response(
            content=json.dumps({"status": "shutting_down"}),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )


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


class LLMMonitorWebServer(uvicorn.Server):
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


def is_port_in_use(host: str, port: int) -> bool:
    """Check whether a port is currently listening on the given host."""
    family = socket.AF_INET6 if (":" in host) else socket.AF_INET
    sock = socket.socket(family=family, type=socket.SOCK_STREAM)
    try:
        sock.settimeout(0.5)
        result = sock.connect_ex((host, port))
        return result == 0
    except OSError:
        return False
    finally:
        sock.close()


def find_target_descriptor(
    port: int | None = None,
    host: str = "127.0.0.1",
    state_dir: Path | str | None = None,
) -> tuple[ServerDescriptor | None, str | None]:
    """Find target descriptor for a given port, or disambiguate if port is None."""
    if port is not None:
        p = descriptor_path(port, host, state_dir=state_dir)
        desc = read_descriptor(p)
        return (desc, None)

    descriptors = list_descriptors(state_dir=state_dir)
    if not descriptors:
        default_p = descriptor_path(8788, host, state_dir=state_dir)
        desc = read_descriptor(default_p)
        return (desc, None)

    active_descriptors = [
        d for d in descriptors if is_process_alive(d.pid, d.process_create_time)
    ]
    if len(active_descriptors) == 1:
        return (active_descriptors[0], None)
    if not active_descriptors and len(descriptors) == 1:
        return (descriptors[0], None)
    if not active_descriptors:
        default_p = descriptor_path(8788, host, state_dir=state_dir)
        return (read_descriptor(default_p), None)

    ports = ", ".join(f"{d.host}:{d.port}" for d in active_descriptors)
    return (
        None,
        f"Multiple LLM Monitor Web servers are running ({ports}). Specify -p/--port to select an instance.",
    )


def force_terminate_process(descriptor: ServerDescriptor, timeout: float = 3.0) -> bool:
    """Forcefully terminate a strictly verified process."""
    if not verify_process_identity(descriptor):
        return False
    try:
        proc = psutil.Process(descriptor.pid)
        # Extra safeguard: check process username when accessible
        with contextlib.suppress(Exception):
            expected_user = os.environ.get("USERNAME") or (os.getlogin() if hasattr(os, "getlogin") else None)
            if expected_user and proc.username():
                proc_user = proc.username().split("\\")[-1].lower()
                if proc_user != expected_user.lower():
                    return False

        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=timeout)
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return not psutil.pid_exists(descriptor.pid)


def stop_server(
    port: int | None = None,
    host: str = "127.0.0.1",
    execute: bool = False,
    force: bool = False,
    state_dir: Path | str | None = None,
    timeout: float = 5.0,
    as_json: bool = False,
) -> int:
    """Stop the running LLM Monitor Web server gracefully or forcefully with preview support."""
    descriptor, error_msg = find_target_descriptor(port, host, state_dir=state_dir)
    if error_msg:
        if as_json:
            print(json.dumps({"status": "error", "error": error_msg}))
        else:
            print(f"llm-monitor: web: {error_msg}", file=sys.stderr)
        return 1

    target_port = port if port is not None else 8788
    if descriptor is None:
        # Check if port is in use by an unmanaged listener
        if is_port_in_use(host, target_port):
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "unmanaged",
                            "stopped": False,
                            "port": target_port,
                            "error": (
                                f"Port {target_port} is occupied by an unmanaged or legacy server lacking "
                                "a valid instance descriptor. Identity cannot be verified; cannot be stopped."
                            ),
                        }
                    )
                )
            else:
                print("LLM Monitor Web UI", file=sys.stderr)
                print("Status: Unmanaged or legacy listener detected", file=sys.stderr)
                print(
                    f"Port {target_port} is occupied by an unmanaged or legacy server lacking "
                    "a valid instance descriptor. Identity cannot be verified; cannot be stopped automatically.",
                    file=sys.stderr,
                )
            return 1

        if as_json:
            print(json.dumps({"status": "not_running", "stopped": True}))
        else:
            print("LLM Monitor Web UI")
            print("Status: Not running\n")
            print("No matching server needs to be stopped.")
        return 0

    desc_path = descriptor_path(descriptor.port, descriptor.host, state_dir=state_dir)
    if not is_process_alive(descriptor.pid, descriptor.process_create_time):
        remove_descriptor(desc_path)
        if as_json:
            print(json.dumps({"status": "not_running", "stopped": True}))
        else:
            print("LLM Monitor Web UI")
            print("Status: Not running\n")
            print("No matching server needs to be stopped.")
        return 0

    browser_host = f"[{descriptor.host}]" if ":" in descriptor.host else descriptor.host
    url = f"http://{browser_host}:{descriptor.port}"

    info = verify_running_instance(descriptor, timeout=2.0)
    if info is None and not (force and execute):
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "unverifiable",
                        "error": (
                            f"Process {descriptor.pid} on port {descriptor.port} "
                            "could not be verified as genuine LLM Monitor."
                        ),
                    }
                )
            )
        else:
            print("LLM Monitor Web UI", file=sys.stderr)
            print("Status: Unverifiable", file=sys.stderr)
            print(
                f"Error: Process {descriptor.pid} on port {descriptor.port} could not be verified as genuine LLM Monitor.",
                file=sys.stderr,
            )
        return 1

    # Dry-run preview
    if not execute:
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "preview",
                        "action": "stop",
                        "port": descriptor.port,
                        "url": url,
                        "pid": descriptor.pid,
                        "gateway_enabled": descriptor.gateway_enabled,
                        "recording_mode": descriptor.recording_mode,
                        "database_path": descriptor.database_path,
                    },
                    indent=2,
                )
            )
        else:
            print("LLM Monitor Web UI")
            print("Status:          Running (dry-run preview)")
            print(f"Port:            {descriptor.port}")
            print(f"URL:             {url}")
            print(f"PID:             {descriptor.pid}")
            print(f"Gateway:         {'enabled' if descriptor.gateway_enabled else 'disabled'}")
            print(f"Recording mode:  {descriptor.recording_mode or 'disabled'}")
            print(f"Database:        {descriptor.database_path or 'none'}\n")
            print("No action taken. Pass -x/--execute to stop this server.")
        return 0

    # Execute shutdown
    if not as_json:
        print("LLM Monitor Web UI")
        print("Status: Stopping")
        print(f"URL:    {url}")
        print(f"PID:    {descriptor.pid}\n")

    requested, err_detail = request_instance_shutdown(descriptor, timeout=timeout)
    if not requested:
        if not force:
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "error": f"Server shutdown failed: {err_detail}",
                            "pid": descriptor.pid,
                        }
                    )
                )
            else:
                print(f"Error: Server shutdown failed: {err_detail}", file=sys.stderr)
            return 1
        elif not as_json:
            print(
                f"Warning: Graceful shutdown request failed ({err_detail}). Proceeding with force termination.",
                file=sys.stderr,
            )

    # Wait for process exit
    deadline = time.time() + timeout
    stopped = False
    while time.time() < deadline:
        if not is_process_alive(descriptor.pid, descriptor.process_create_time):
            stopped = True
            break
        time.sleep(0.1)

    if stopped:
        remove_descriptor(desc_path)
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
        return 0

    # Graceful shutdown timed out
    if force:
        if not as_json:
            print(
                "Warning: Forced termination may interrupt active inference requests and lose uncommitted recording data.",
                file=sys.stderr,
            )
        ok = force_terminate_process(descriptor)
        if ok:
            remove_descriptor(desc_path)
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "stopped",
                            "stopped": True,
                            "forced": True,
                            "pid": descriptor.pid,
                            "url": url,
                        }
                    )
                )
            else:
                print(f"Server process {descriptor.pid} forcefully terminated.")
            return 0
        else:
            if as_json:
                print(json.dumps({"status": "error", "error": "Force termination failed"}))
            else:
                print(f"Error: Failed to forcefully terminate process {descriptor.pid}.", file=sys.stderr)
            return 1

    # Preserve descriptor on timeout without force
    if as_json:
        print(
            json.dumps(
                {
                    "status": "timeout",
                    "stopped": False,
                    "pid": descriptor.pid,
                    "warning": (
                        f"Server process {descriptor.pid} did not exit within {timeout} seconds; "
                        "descriptor preserved for subsequent status inspection or retry."
                    ),
                }
            )
        )
    else:
        print(f"Warning: Server process {descriptor.pid} did not exit within {timeout} seconds.", file=sys.stderr)
        print("The server descriptor was preserved so shutdown can be retried.")
    return 1


def status_server(
    port: int | None = None,
    host: str = "127.0.0.1",
    state_dir: Path | str | None = None,
    as_json: bool = False,
) -> int:
    """Report the status of the LLM Monitor Web server without modifying state."""
    descriptor, error_msg = find_target_descriptor(port, host, state_dir=state_dir)
    if error_msg:
        if as_json:
            print(json.dumps({"status": "error", "error": error_msg}))
        else:
            print(f"llm-monitor: web: {error_msg}", file=sys.stderr)
        return 1

    target_port = port if port is not None else 8788
    if descriptor is None:
        if is_port_in_use(host, target_port):
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "unmanaged",
                            "running": False,
                            "port": target_port,
                            "warning": f"Port {target_port} is in use by an unmanaged or unrelated process.",
                        }
                    )
                )
            else:
                print("LLM Monitor Web UI")
                print("Status:  Unmanaged or unrelated listener detected")
                print(f"Port:    {target_port}")
                print(
                    f"Warning: Port {target_port} is in use by an unmanaged process. "
                    "Identity cannot be verified; this instance cannot be safely managed via llm-monitor web."
                )
            return 0

        if as_json:
            print(json.dumps({"status": "not_running", "running": False}))
        else:
            print("LLM Monitor Web UI")
            print("Status: Not running")
        return 0

    browser_host = f"[{descriptor.host}]" if ":" in descriptor.host else descriptor.host
    url = f"http://{browser_host}:{descriptor.port}"

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
            print("LLM Monitor Web UI")
            print("Status: Not running")
            print(f"Warning: Stale descriptor found for PID {descriptor.pid} (process not running).")
        return 0

    info = verify_running_instance(descriptor, timeout=2.0)
    if info is None:
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "unverifiable",
                        "running": False,
                        "url": url,
                        "pid": descriptor.pid,
                        "port": descriptor.port,
                        "warning": "Process is running but did not pass LLM Monitor instance verification.",
                    }
                )
            )
        else:
            print("LLM Monitor Web UI")
            print("Status: Unverifiable")
            print(f"URL:    {url}")
            print(f"PID:    {descriptor.pid}")
            print(f"Port:   {descriptor.port}")
            print("Warning: Process is running but did not pass LLM Monitor instance verification.")
        return 1

    recorder_healthy = info.get("recorder_healthy")
    if recorder_healthy is True:
        recorder_str = "healthy"
    elif recorder_healthy is False:
        recorder_str = "unhealthy"
    else:
        recorder_str = "n/a (no active recorder)"

    if as_json:
        print(
            json.dumps(
                {
                    "status": "running",
                    "running": True,
                    "url": url,
                    "pid": descriptor.pid,
                    "host": descriptor.host,
                    "port": descriptor.port,
                    "gateway_enabled": descriptor.gateway_enabled,
                    "recording_mode": descriptor.recording_mode,
                    "database_path": descriptor.database_path,
                    "recorder_healthy": recorder_healthy,
                },
                indent=2,
            )
        )
        return 0

    print("LLM Monitor Web UI")
    print("Status:          Running")
    print(f"Port:            {descriptor.port}")
    print(f"URL:             {url}")
    print(f"PID:             {descriptor.pid}")
    print(f"Gateway:         {'enabled' if descriptor.gateway_enabled else 'disabled'}")
    print(f"Recording mode:  {descriptor.recording_mode or 'disabled'}")
    print(f"Database:        {descriptor.database_path or 'none'}")
    print(f"Recorder health: {recorder_str}")
    return 0
