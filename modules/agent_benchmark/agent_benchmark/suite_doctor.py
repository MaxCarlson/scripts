"""Context-aware environment diagnostics and stable failure taxonomy (agent-bench suite doctor).

Provides non-mutating inspection of runtime context, managed LLM Monitor,
authentication channel, inference provider (LM Studio), Docker, gateway mapping,
and recorder health conforming to the monitor-preflight-v1 schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import socket
import sys
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from llm_monitor.server_lifecycle import (
    compare_config_fingerprint,
    find_target_descriptor,
    get_current_owner_identity,
    is_port_in_use,
    is_process_alive,
)
from llm_monitor.local_client import ManagedMonitorClient


def find_active_server(port: int, host: str = "127.0.0.1") -> Any:
    """Discover active server descriptor for port."""
    desc, _ = find_target_descriptor(port=port, host=host or "127.0.0.1")
    return desc


@dataclass
class DoctorProbe:
    name: str
    status: str  # "ready", "degraded", "blocked", "skipped", "unknown"
    error_code: str | None = None
    duration_ms: float = 0.0
    observed_context: str = ""
    evidence_kind: str = ""
    retryable: bool = False
    suggested_action: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_component_dict(self) -> dict[str, Any]:
        return {
            "state": self.status,
            "error_code": self.error_code,
            "retryable": self.retryable,
            "elapsed_ms": round(self.duration_ms, 2),
            "evidence_kind": self.evidence_kind,
            "remedy": self.suggested_action,
            "details": self.details,
        }


def _is_port_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """Non-blocking socket check for port listener."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def probe_runtime_context() -> DoctorProbe:
    t0 = time.monotonic()
    details: dict[str, Any] = {
        "os": platform.system(),
        "platform_release": platform.release(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "owner_identity": get_current_owner_identity(),
    }
    # Sandbox access probe: check if basic loopback sockets work
    sandbox_restricted = False
    confidence = "observed"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.close()
    except PermissionError:
        sandbox_restricted = True
    except Exception:
        confidence = "inferred"

    details["sandbox_restricted"] = sandbox_restricted
    details["confidence"] = confidence
    elapsed = (time.monotonic() - t0) * 1000

    if sandbox_restricted:
        return DoctorProbe(
            name="runtime_context",
            status="blocked",
            error_code="LOCAL_SOCKET_RESTRICTED",
            duration_ms=elapsed,
            observed_context=platform.system(),
            evidence_kind="socket_creation_permission",
            retryable=False,
            suggested_action="USE_APPROVED_HOST_CONTEXT",
            details=details,
        )

    return DoctorProbe(
        name="runtime_context",
        status="ready",
        duration_ms=elapsed,
        observed_context=platform.system(),
        evidence_kind="runtime_environment",
        retryable=False,
        details=details,
    )


def probe_managed_monitor(
    host: str = "127.0.0.1",
    port: int = 8788,
    expected_gateway: bool = False,
    expected_recording: str = "off",
) -> tuple[DoctorProbe, Any]:
    t0 = time.monotonic()
    descriptor = find_active_server(port, host=host)
    listening = _is_port_listening(host, port)
    elapsed = (time.monotonic() - t0) * 1000

    details: dict[str, Any] = {
        "host": host,
        "port": port,
        "socket_listening": listening,
        "descriptor_found": descriptor is not None,
    }

    if not listening and descriptor is None:
        return (
            DoctorProbe(
                name="managed_monitor",
                status="blocked",
                error_code="MONITOR_NOT_RUNNING",
                duration_ms=elapsed,
                observed_context=f"{host}:{port}",
                evidence_kind="socket_and_descriptor_absent",
                retryable=True,
                suggested_action="START_MANAGED_MONITOR",
                details=details,
            ),
            None,
        )

    if listening and descriptor is None:
        return (
            DoctorProbe(
                name="managed_monitor",
                status="blocked",
                error_code="MONITOR_UNMANAGED_LISTENER",
                duration_ms=elapsed,
                observed_context=f"{host}:{port}",
                evidence_kind="socket_listening_without_descriptor",
                retryable=False,
                suggested_action="CHECK_MANAGED_MONITOR",
                details=details,
            ),
            None,
        )

    assert descriptor is not None
    details["pid"] = descriptor.pid
    details["gateway_enabled"] = descriptor.gateway_enabled
    details["recording_mode"] = descriptor.recording_mode

    # Verify process liveness
    if not is_process_alive(descriptor.pid, descriptor.process_create_time):
        return (
            DoctorProbe(
                name="managed_monitor",
                status="blocked",
                error_code="MONITOR_IDENTITY_MISMATCH",
                duration_ms=elapsed,
                observed_context=f"pid:{descriptor.pid}",
                evidence_kind="process_pid_or_createtime_mismatch",
                retryable=False,
                suggested_action="CHECK_MANAGED_MONITOR",
                details=details,
            ),
            None,
        )

    # Check config fingerprint
    config_match = compare_config_fingerprint(
        descriptor,
        gateway_enabled=expected_gateway,
        recording_mode=expected_recording,
    )
    details["config_match"] = config_match
    if not config_match:
        return (
            DoctorProbe(
                name="managed_monitor",
                status="blocked",
                error_code="MONITOR_CONFIG_MISMATCH",
                duration_ms=elapsed,
                observed_context=f"config:{descriptor.config_fingerprint}",
                evidence_kind="config_fingerprint_mismatch",
                retryable=False,
                suggested_action="FIX_CONFIGURATION",
                details=details,
            ),
            descriptor,
        )

    return (
        DoctorProbe(
            name="managed_monitor",
            status="ready",
            duration_ms=elapsed,
            observed_context=f"{host}:{port} pid:{descriptor.pid}",
            evidence_kind="verified_descriptor_and_liveness",
            retryable=False,
            details=details,
        ),
        descriptor,
    )


def probe_auth_channel(
    host: str = "127.0.0.1",
    port: int = 8788,
    monitor_ready: bool = True,
) -> tuple[DoctorProbe, str | None]:
    t0 = time.monotonic()
    if not monitor_ready:
        return (
            DoctorProbe(
                name="auth_channel",
                status="skipped",
                duration_ms=0.0,
                observed_context=f"{host}:{port}",
                evidence_kind="monitor_not_ready",
                retryable=False,
                details={"reason": "monitor not ready"},
            ),
            None,
        )

    token = None
    try:
        client = ManagedMonitorClient(port=port, host=host)
        token = client.acquire_capability_token()
    except PermissionError as err:
        elapsed = (time.monotonic() - t0) * 1000
        return (
            DoctorProbe(
                name="auth_channel",
                status="blocked",
                error_code="MONITOR_CONTROL_PERMISSION_DENIED",
                duration_ms=elapsed,
                observed_context=f"{host}:{port}",
                evidence_kind="pipe_or_socket_acl_denied",
                retryable=False,
                suggested_action="USE_APPROVED_HOST_CONTEXT",
                details={"error": "control channel permission denied"},
            ),
            None,
        )
    except Exception as err:
        elapsed = (time.monotonic() - t0) * 1000
        err_str = str(err)
        if "5" in err_str or "Access is denied" in err_str:
            return (
                DoctorProbe(
                    name="auth_channel",
                    status="blocked",
                    error_code="MONITOR_CONTROL_PERMISSION_DENIED",
                    duration_ms=elapsed,
                    observed_context=f"{host}:{port}",
                    evidence_kind="pipe_or_socket_acl_denied",
                    retryable=False,
                    suggested_action="USE_APPROVED_HOST_CONTEXT",
                    details={"error": "control channel access denied"},
                ),
                None,
            )
        return (
            DoctorProbe(
                name="auth_channel",
                status="blocked",
                error_code="MONITOR_CONTROL_UNREACHABLE",
                duration_ms=elapsed,
                observed_context=f"{host}:{port}",
                evidence_kind="control_channel_connect_failed",
                retryable=True,
                suggested_action="CHECK_MANAGED_MONITOR",
                details={"error": "control channel unreachable"},
            ),
            None,
        )

    if not token:
        elapsed = (time.monotonic() - t0) * 1000
        return (
            DoctorProbe(
                name="auth_channel",
                status="blocked",
                error_code="MONITOR_AUTH_BOOTSTRAP_FAILED",
                duration_ms=elapsed,
                observed_context=f"{host}:{port}",
                evidence_kind="token_issuance_failed",
                retryable=True,
                suggested_action="REAUTHENTICATE_MANAGED",
                details={"error": "no token issued"},
            ),
            None,
        )

    # Validate capability token via test HTTP probe
    origin = f"http://{host}:{port}"
    try:
        with httpx.Client(base_url=origin, trust_env=False, timeout=2.0) as http_client:
            resp = http_client.get(
                "/api/inference/v1/models",
                headers={"Origin": origin, "Authorization": f"Bearer {token}"},
            )
            elapsed = (time.monotonic() - t0) * 1000
            if resp.status_code == 401:
                return (
                    DoctorProbe(
                        name="auth_channel",
                        status="blocked",
                        error_code="MONITOR_HTTP_UNAUTHORIZED",
                        duration_ms=elapsed,
                        observed_context=origin,
                        evidence_kind="http_401_unauthorized",
                        retryable=True,
                        suggested_action="REAUTHENTICATE_MANAGED",
                        details={"status_code": 401},
                    ),
                    None,
                )
            if resp.status_code == 403:
                return (
                    DoctorProbe(
                        name="auth_channel",
                        status="blocked",
                        error_code="MONITOR_HTTP_ORIGIN_REJECTED",
                        duration_ms=elapsed,
                        observed_context=origin,
                        evidence_kind="http_403_origin_rejected",
                        retryable=False,
                        suggested_action="FIX_CONFIGURATION",
                        details={"status_code": 403},
                    ),
                    None,
                )
            if resp.status_code == 422:
                return (
                    DoctorProbe(
                        name="auth_channel",
                        status="blocked",
                        error_code="MONITOR_HTTP_INVALID_PAYLOAD",
                        duration_ms=elapsed,
                        observed_context=origin,
                        evidence_kind="http_422_unprocessable_entity",
                        retryable=False,
                        suggested_action="FIX_CONFIGURATION",
                        details={"status_code": 422},
                    ),
                    None,
                )
            if resp.status_code == 200:
                return (
                    DoctorProbe(
                        name="auth_channel",
                        status="ready",
                        duration_ms=elapsed,
                        observed_context=origin,
                        evidence_kind="scoped_capability_verified",
                        retryable=False,
                        details={"token_acquired": True, "http_status": 200},
                    ),
                    token,
                )
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return (
            DoctorProbe(
                name="auth_channel",
                status="blocked",
                error_code="MONITOR_CONTROL_UNREACHABLE",
                duration_ms=elapsed,
                observed_context=origin,
                evidence_kind="http_probe_failed",
                retryable=True,
                suggested_action="CHECK_MANAGED_MONITOR",
                details={"error": "http probe connection failure"},
            ),
            None,
        )

    elapsed = (time.monotonic() - t0) * 1000
    return (
        DoctorProbe(
            name="auth_channel",
            status="ready",
            duration_ms=elapsed,
            observed_context=origin,
            evidence_kind="token_acquired",
            details={"token_acquired": True},
        ),
        token,
    )


def probe_lm_studio(
    endpoint: str = "http://127.0.0.1:1234",
    model: str | None = None,
) -> DoctorProbe:
    t0 = time.monotonic()
    try:
        with httpx.Client(base_url=endpoint, trust_env=False, timeout=2.0) as client:
            resp = client.get("/v1/models")
            elapsed = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                body = resp.json()
                models = [m.get("id") for m in body.get("data", []) if isinstance(m, dict)]
                details: dict[str, Any] = {
                    "endpoint": endpoint,
                    "model_count": len(models),
                    "models": models[:10],
                }
                if model:
                    # Strip prefixes like openai/
                    bare_model = model.split("/", 1)[-1].lower()
                    matched = any(bare_model in (m or "").lower() for m in models)
                    details["requested_model"] = model
                    details["model_matched"] = matched
                    if not matched:
                        return DoctorProbe(
                            name="lm_studio",
                            status="degraded",
                            error_code="MONITOR_ROUTE_INCOMPATIBLE",
                            duration_ms=elapsed,
                            observed_context=endpoint,
                            evidence_kind="model_catalog_missing_requested_model",
                            retryable=False,
                            suggested_action="CHECK_PROVIDER",
                            details=details,
                        )
                return DoctorProbe(
                    name="lm_studio",
                    status="ready",
                    duration_ms=elapsed,
                    observed_context=endpoint,
                    evidence_kind="provider_models_api",
                    retryable=False,
                    details=details,
                )
            else:
                return DoctorProbe(
                    name="lm_studio",
                    status="blocked",
                    error_code="LM_STUDIO_UNREACHABLE",
                    duration_ms=elapsed,
                    observed_context=endpoint,
                    evidence_kind="provider_http_error",
                    retryable=True,
                    suggested_action="CHECK_PROVIDER",
                    details={"status_code": resp.status_code},
                )
    except httpx.ConnectError:
        elapsed = (time.monotonic() - t0) * 1000
        return DoctorProbe(
            name="lm_studio",
            status="blocked",
            error_code="LM_STUDIO_UNREACHABLE",
            duration_ms=elapsed,
            observed_context=endpoint,
            evidence_kind="connection_refused",
            retryable=True,
            suggested_action="CHECK_PROVIDER",
            details={"error": "connection refused"},
        )
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return DoctorProbe(
            name="lm_studio",
            status="blocked",
            error_code="LM_STUDIO_UNREACHABLE",
            duration_ms=elapsed,
            observed_context=endpoint,
            evidence_kind="probe_failed",
            retryable=True,
            suggested_action="CHECK_PROVIDER",
            details={"error": "provider probe failed"},
        )


def probe_docker(mock_pipe_error: Exception | None = None) -> DoctorProbe:
    t0 = time.monotonic()
    if mock_pipe_error:
        elapsed = (time.monotonic() - t0) * 1000
        if isinstance(mock_pipe_error, PermissionError) or "Access is denied" in str(mock_pipe_error):
            return DoctorProbe(
                name="docker",
                status="blocked",
                error_code="DOCKER_PIPE_ACCESS_DENIED",
                duration_ms=elapsed,
                observed_context="named_pipe:docker_engine",
                evidence_kind="named_pipe_acl_denied",
                retryable=False,
                suggested_action="USE_APPROVED_HOST_CONTEXT",
                details={"error": "docker named pipe access denied"},
            )
        return DoctorProbe(
            name="docker",
            status="blocked",
            error_code="DOCKER_UNAVAILABLE",
            duration_ms=elapsed,
            observed_context="docker_daemon",
            evidence_kind="docker_daemon_unavailable",
            retryable=False,
            suggested_action="CHECK_DOCKER",
            details={"error": "docker unavailable"},
        )

    # Lightweight probe for Docker
    if sys.platform == "win32":
        pipe_path = r"\\.\pipe\docker_engine"
        try:
            # Check pipe accessibility
            if os.path.exists(pipe_path):
                elapsed = (time.monotonic() - t0) * 1000
                return DoctorProbe(
                    name="docker",
                    status="ready",
                    duration_ms=elapsed,
                    observed_context=pipe_path,
                    evidence_kind="named_pipe_present",
                    retryable=False,
                    details={"transport": "named_pipe"},
                )
        except PermissionError:
            elapsed = (time.monotonic() - t0) * 1000
            return DoctorProbe(
                name="docker",
                status="blocked",
                error_code="DOCKER_PIPE_ACCESS_DENIED",
                duration_ms=elapsed,
                observed_context=pipe_path,
                evidence_kind="named_pipe_acl_denied",
                retryable=False,
                suggested_action="USE_APPROVED_HOST_CONTEXT",
                details={"error": "docker pipe permission denied"},
            )
        except Exception:
            pass

    # Check CLI without mutating/starting containers
    import shutil
    import subprocess

    docker_bin = shutil.which("docker")
    if not docker_bin:
        elapsed = (time.monotonic() - t0) * 1000
        return DoctorProbe(
            name="docker",
            status="blocked",
            error_code="DOCKER_UNAVAILABLE",
            duration_ms=elapsed,
            observed_context="cli",
            evidence_kind="docker_executable_not_found",
            retryable=False,
            suggested_action="CHECK_DOCKER",
            details={"error": "docker not in PATH"},
        )

    try:
        res = subprocess.run(
            [docker_bin, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        elapsed = (time.monotonic() - t0) * 1000
        if res.returncode == 0:
            return DoctorProbe(
                name="docker",
                status="ready",
                duration_ms=elapsed,
                observed_context="docker_info",
                evidence_kind="docker_server_running",
                retryable=False,
                details={"server_version": res.stdout.strip()},
            )
        else:
            err_str = res.stderr or ""
            if "Access is denied" in err_str or "permission denied" in err_str.lower():
                return DoctorProbe(
                    name="docker",
                    status="blocked",
                    error_code="DOCKER_PIPE_ACCESS_DENIED",
                    duration_ms=elapsed,
                    observed_context="docker_info",
                    evidence_kind="named_pipe_acl_denied",
                    retryable=False,
                    suggested_action="USE_APPROVED_HOST_CONTEXT",
                    details={"error": "docker permission denied"},
                )
            return DoctorProbe(
                name="docker",
                status="blocked",
                error_code="DOCKER_UNAVAILABLE",
                duration_ms=elapsed,
                observed_context="docker_info",
                evidence_kind="docker_daemon_not_responding",
                retryable=False,
                suggested_action="CHECK_DOCKER",
                details={"error": "docker info returned non-zero"},
            )
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return DoctorProbe(
            name="docker",
            status="blocked",
            error_code="DOCKER_UNAVAILABLE",
            duration_ms=elapsed,
            observed_context="docker_subprocess",
            evidence_kind="docker_command_failed",
            retryable=False,
            suggested_action="CHECK_DOCKER",
            details={"error": "docker check failed"},
        )


def probe_gateway_mapping(
    monitor_url: str = "http://host.docker.internal:8789/v1",
    monitor_host_url: str | None = None,
) -> DoctorProbe:
    t0 = time.monotonic()
    parsed = urlsplit(monitor_url)
    details: dict[str, Any] = {
        "monitor_url": monitor_url,
        "monitor_host_url": monitor_host_url,
    }
    elapsed = (time.monotonic() - t0) * 1000

    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return DoctorProbe(
            name="gateway_mapping",
            status="degraded",
            error_code="SUITE_CONFIGURATION_INVALID",
            duration_ms=elapsed,
            observed_context=monitor_url,
            evidence_kind="container_url_uses_host_loopback",
            retryable=False,
            suggested_action="FIX_CONFIGURATION",
            details={"reason": "container cannot reach host loopback via localhost; use host.docker.internal"},
        )

    return DoctorProbe(
        name="gateway_mapping",
        status="ready",
        duration_ms=elapsed,
        observed_context=monitor_url,
        evidence_kind="valid_container_target_mapping",
        retryable=False,
        details=details,
    )


def probe_recorder(
    origin: str = "http://127.0.0.1:8788",
    monitor_ready: bool = True,
    token: str | None = None,
) -> DoctorProbe:
    t0 = time.monotonic()
    if not monitor_ready:
        return DoctorProbe(
            name="recorder",
            status="skipped",
            duration_ms=0.0,
            observed_context=origin,
            evidence_kind="monitor_not_ready",
            retryable=False,
            details={"reason": "monitor not ready"},
        )

    headers = {"Origin": origin}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(base_url=origin, trust_env=False, timeout=2.0) as client:
            resp = client.get("/api/inference/v1/recording/status", headers=headers)
            elapsed = (time.monotonic() - t0) * 1000
            if resp.status_code == 200:
                data = resp.json()
                rec = data.get("recording", {})
                healthy = rec.get("healthy", False)
                dropped = rec.get("dropped_count", 0)
                mode = rec.get("mode", "off")
                details = {"healthy": healthy, "dropped_count": dropped, "mode": mode}
                if not healthy or dropped > 0:
                    return DoctorProbe(
                        name="recorder",
                        status="degraded",
                        error_code="MONITOR_RECORDER_UNHEALTHY",
                        duration_ms=elapsed,
                        observed_context=f"healthy:{healthy} dropped:{dropped}",
                        evidence_kind="recorder_status_unhealthy_or_dropped",
                        retryable=False,
                        suggested_action="REPAIR_RECORDER",
                        details=details,
                    )
                return DoctorProbe(
                    name="recorder",
                    status="ready",
                    duration_ms=elapsed,
                    observed_context=f"healthy:{healthy} drops:0",
                    evidence_kind="recorder_status_clean",
                    retryable=False,
                    details=details,
                )
    except Exception:
        pass

    elapsed = (time.monotonic() - t0) * 1000
    return DoctorProbe(
        name="recorder",
        status="skipped",
        duration_ms=elapsed,
        observed_context=origin,
        evidence_kind="recorder_status_unavailable",
        retryable=False,
        details={"reason": "could not retrieve recording status"},
    )


def determine_recommended_action(probes: dict[str, DoctorProbe]) -> tuple[str, str]:
    """Deterministically prioritize recommended action based on observed evidence."""
    # Priority 1: Context/Security restrictions
    for p in probes.values():
        if p.error_code in ("DOCKER_PIPE_ACCESS_DENIED", "MONITOR_CONTROL_PERMISSION_DENIED", "LOCAL_SOCKET_RESTRICTED"):
            return "blocked", "USE_APPROVED_HOST_CONTEXT"

    # Priority 2: Configuration mismatch
    for p in probes.values():
        if p.error_code in ("MONITOR_CONFIG_MISMATCH", "MONITOR_HTTP_ORIGIN_REJECTED", "SUITE_CONFIGURATION_INVALID"):
            return "blocked", "FIX_CONFIGURATION"

    # Priority 3: Monitor not running
    if probes.get("managed_monitor") and probes["managed_monitor"].error_code == "MONITOR_NOT_RUNNING":
        return "blocked", "START_MANAGED_MONITOR"

    # Priority 4: Unmanaged listener or identity mismatch
    for p in probes.values():
        if p.error_code in ("MONITOR_UNMANAGED_LISTENER", "MONITOR_IDENTITY_MISMATCH"):
            return "blocked", "CHECK_MANAGED_MONITOR"

    # Priority 5: Auth issues
    for p in probes.values():
        if p.error_code in ("MONITOR_AUTH_BOOTSTRAP_FAILED", "MONITOR_HTTP_UNAUTHORIZED"):
            return "blocked", "REAUTHENTICATE_MANAGED"

    # Priority 6: Provider / LM Studio
    if probes.get("lm_studio") and probes["lm_studio"].error_code in ("LM_STUDIO_UNREACHABLE", "MONITOR_ROUTE_INCOMPATIBLE"):
        return probes["lm_studio"].status, "CHECK_PROVIDER"

    # Priority 7: Docker unavailable
    if probes.get("docker") and probes["docker"].error_code == "DOCKER_UNAVAILABLE":
        return "blocked", "CHECK_DOCKER"

    # Priority 8: Recorder unhealthy
    if probes.get("recorder") and probes["recorder"].error_code == "MONITOR_RECORDER_UNHEALTHY":
        return "degraded", "REPAIR_RECORDER"

    # Any other blocked or degraded probe
    has_blocked = any(p.status == "blocked" for p in probes.values())
    if has_blocked:
        return "blocked", "REVIEW_DIAGNOSTIC_LOGS"

    has_degraded = any(p.status == "degraded" for p in probes.values())
    if has_degraded:
        return "degraded", "REVIEW_DIAGNOSTIC_LOGS"

    return "ready", "NONE"


def run_doctor(args: Any) -> int:
    t0 = time.monotonic()
    checked_at = datetime.now(timezone.utc).isoformat()

    full: bool = bool(getattr(args, "full", False))
    fmt: str = getattr(args, "format", "text")
    monitor_url: str = getattr(args, "monitor_url", "http://host.docker.internal:8789/v1")
    monitor_host_url: str | None = getattr(args, "monitor_host_url", None)
    endpoint: str = getattr(args, "endpoint", "http://127.0.0.1:1234") or "http://127.0.0.1:1234"
    model: str | None = getattr(args, "model", None)
    expected_recording: str = getattr(args, "recording", "off") or "off"

    # Derive host origin
    from .suite_monitor import host_monitor_origin
    host_origin = host_monitor_origin(monitor_url, monitor_host_url)
    parsed_origin = urlsplit(host_origin)
    host_addr = parsed_origin.hostname or "127.0.0.1"
    host_port = parsed_origin.port or 8788

    probes: dict[str, DoctorProbe] = {}

    # Probe 1: Runtime context
    probes["runtime_context"] = probe_runtime_context()

    # Probe 2: Managed Monitor
    probe_mon, descriptor = probe_managed_monitor(
        host=host_addr,
        port=host_port,
        expected_gateway=True,  # Benchmark suites require gateway
        expected_recording=expected_recording,
    )
    probes["managed_monitor"] = probe_mon
    mon_ready = (probe_mon.status == "ready")

    # Probe 3: Auth channel
    probe_auth, token = probe_auth_channel(
        host=host_addr,
        port=host_port,
        monitor_ready=mon_ready,
    )
    probes["auth_channel"] = probe_auth

    # Probe 4: Gateway mapping
    probes["gateway_mapping"] = probe_gateway_mapping(
        monitor_url=monitor_url,
        monitor_host_url=monitor_host_url,
    )

    # Probe 5: Recorder (if monitor is ready)
    probes["recorder"] = probe_recorder(
        origin=host_origin,
        monitor_ready=mon_ready,
        token=token,
    )

    # Extended probes (LM Studio & Docker)
    probes["lm_studio"] = probe_lm_studio(endpoint=endpoint, model=model)
    probes["docker"] = probe_docker()

    # Determine overall status and action
    overall_status, recommended_action = determine_recommended_action(probes)
    elapsed_ms = (time.monotonic() - t0) * 1000

    recovery: dict[str, Any] = {
        "can_recover_locally": (probe_mon.error_code == "MONITOR_NOT_RUNNING"),
        "recovery_command": (
            f"llm-monitor web start -p {host_port} --gateway -R {expected_recording} -n"
            if probe_mon.error_code == "MONITOR_NOT_RUNNING"
            else None
        ),
    }

    report: dict[str, Any] = {
        "schema_version": "monitor-preflight-v1",
        "status": overall_status,
        "execution_context": probes["runtime_context"].details,
        "components": {k: v.to_component_dict() for k, v in probes.items()},
        "recommended_action": recommended_action,
        "recovery": recovery,
        "inference_dispatched": False,
        "checked_at": checked_at,
        "elapsed_ms": round(elapsed_ms, 2),
    }

    if fmt == "json":
        print(json.dumps(report, indent=2))
    else:
        print("=== LLM Benchmark Suite Doctor ===")
        print(f"Status:             {overall_status.upper()}")
        print(f"Recommended Action: {recommended_action}")
        if recovery["recovery_command"]:
            print(f"Local Recovery:     {recovery['recovery_command']}")
        print("\nProbes:")
        for name, comp in report["components"].items():
            err_str = f" [{comp['error_code']}]" if comp.get("error_code") else ""
            print(f"  - {name:<18} {comp['state'].upper():<10} ({comp['elapsed_ms']}ms){err_str}")
            if comp.get("remedy"):
                print(f"      remedy: {comp['remedy']}")

    return 0 if overall_status == "ready" else 1
