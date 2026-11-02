"""Bounded recoverable benchmark preflight state machine (Phase 04).

Manages deterministic discovery, owner/identity verification, configuration
fingerprinting, scoped capability acquisition, and bounded single-attempt
local recovery authorized by -r/--recover-local.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from llm_monitor.local_client import ManagedMonitorClient
from .suite_doctor import (
    _is_port_listening,
    find_active_server,
    probe_managed_monitor,
)
from .suite_monitor import (
    MonitorPreflightError,
    _build_monitor_headers,
    host_monitor_origin,
)


def _poll_for_server_ready(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 15.0,
) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        desc = find_active_server(port, host=host)
        if desc is not None and _is_port_listening(host, port):
            return desc
        time.sleep(0.2)
    return None


def recover_managed_monitor(
    *,
    host_origin: str = "http://127.0.0.1:8788",
    recording: str = "off",
    recover_local: bool = False,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Execute bounded preflight and optional single-attempt local recovery."""
    parsed = urlsplit(host_origin)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8788

    # Probe current state using doctor probe engine
    probe, descriptor = probe_managed_monitor(
        host=host,
        port=port,
        expected_gateway=True,
        expected_recording=recording,
    )

    if probe.status == "ready" and descriptor is not None:
        # Reusing existing healthy instance
        return {
            "schema_version": "monitor-preflight-v1",
            "status": "ready",
            "recovered_locally": False,
            "host_origin": host_origin,
            "port": port,
            "server_instance_id": getattr(descriptor, "instance_id", "verified-instance"),
            "config_fingerprint": getattr(descriptor, "config_fingerprint", None),
            "inference_dispatched": False,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    if probe.error_code == "MONITOR_NOT_RUNNING":
        if not recover_local:
            raise MonitorPreflightError(
                f"MONITOR_NOT_RUNNING: LLM Monitor is absent at {host}:{port}; "
                "authorize local start with -r/--recover-local or run 'llm-monitor web start -p ...'"
            )

        # Bounded single-start recovery
        cmd = [
            sys.executable, "-u", "-m", "llm_monitor", "web", "start",
            "-p", str(port), "--gateway", "-R", recording, "-n",
        ]
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except Exception as exc:
            raise MonitorPreflightError(
                f"MONITOR_START_FAILED: Could not spawn managed monitor: {exc}"
            ) from exc

        # Wait for verified readiness
        desc = _poll_for_server_ready(port=port, host=host, timeout=timeout_seconds)
        if desc is None:
            if proc.poll() is not None:
                err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
                raise MonitorPreflightError(
                    f"MONITOR_START_FAILED: Monitor exited prematurely with code {proc.returncode}: {err}"
                )
            raise MonitorPreflightError(
                f"MONITOR_STARTUP_TIMEOUT: Bounded local recovery did not observe verified ready monitor within {timeout_seconds}s"
            )

        # Acquire capability token over protected local IPC channel
        client = ManagedMonitorClient(port=port, host=host)
        token = client.acquire_capability_token()

        return {
            "schema_version": "monitor-preflight-v1",
            "status": "ready",
            "recovered_locally": True,
            "host_origin": host_origin,
            "port": port,
            "server_instance_id": getattr(desc, "instance_id", "recovered-instance"),
            "config_fingerprint": getattr(desc, "config_fingerprint", None),
            "inference_dispatched": False,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    if probe.error_code == "MONITOR_UNMANAGED_LISTENER":
        raise MonitorPreflightError(
            f"MONITOR_UNMANAGED_LISTENER: Port {port} is occupied by an unverified listener; "
            "cannot safely recover or attach to unmanaged process"
        )

    if probe.error_code == "MONITOR_CONFIG_MISMATCH":
        raise MonitorPreflightError(
            f"MONITOR_CONFIG_MISMATCH: Existing LLM Monitor at {host}:{port} has conflicting configuration; "
            "restart refused to protect active workloads"
        )

    if probe.error_code == "MONITOR_IDENTITY_MISMATCH":
        raise MonitorPreflightError(
            f"MONITOR_IDENTITY_MISMATCH: Server descriptor PID/createtime mismatch at {host}:{port}; "
            "inspect running processes"
        )

    raise MonitorPreflightError(
        f"{probe.error_code or 'MONITOR_PREFLIGHT_FAILED'}: {probe.suggested_action or 'Monitor recovery blocked'}"
    )


def check_task_boundary_recorder(
    *,
    monitor_url: str,
    baseline_dropped: int = 0,
    client: httpx.Client | None = None,
) -> bool:
    """Validate recorder health at task boundaries and halt if degraded."""
    origin = host_monitor_origin(monitor_url)
    headers = _build_monitor_headers(origin)
    own_client = client is None
    active_client = client or httpx.Client(timeout=3.0, follow_redirects=False, trust_env=False)

    try:
        resp = active_client.get(f"{origin}/api/inference/v1/recording/status", headers=headers)
        resp.raise_for_status()
        data = resp.json().get("recording", {})
        healthy = data.get("healthy", False)
        dropped = data.get("dropped_count", 0)

        if not healthy or dropped > baseline_dropped:
            raise MonitorPreflightError(
                f"MONITOR_RECORDER_UNHEALTHY: Recorder degraded at task boundary "
                f"(healthy={healthy}, dropped={dropped} > baseline={baseline_dropped}); halting benchmark"
            )
        return True
    except MonitorPreflightError:
        raise
    except Exception as exc:
        raise MonitorPreflightError(
            f"MONITOR_RECORDER_CHECK_FAILED: Could not verify recorder status at {origin}: {exc}"
        ) from exc
    finally:
        if own_client:
            active_client.close()
