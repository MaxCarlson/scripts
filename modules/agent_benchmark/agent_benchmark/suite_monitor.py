"""Fail-closed preflight for monitored Harbor runs."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from .suite import DEFAULT_MONITOR_URL

_LOCAL_HARBOR_AGENTS = {"qwen-coder", "opencode", "opencode-v2"}
_QUALIFICATION_MAX_AGE_SECONDS = 30.0


class MonitorPreflightError(RuntimeError):
    """The required monitor route or recording mode could not be verified."""


def _monitor_origin(gateway_url: str) -> str:
    parsed = urlsplit(gateway_url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise MonitorPreflightError("monitor URL must be an absolute HTTP(S) URL")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def host_monitor_origin(gateway_url: str, host_url: str | None = None) -> str:
    if host_url:
        return _monitor_origin(host_url)
    parsed = urlsplit(gateway_url)
    if parsed.hostname == "host.docker.internal":
        return urlunsplit((parsed.scheme, f"127.0.0.1:{parsed.port or 8788}", "", "", ""))
    return _monitor_origin(gateway_url)


def resolve_managed_monitor_auth(origin: str) -> str | None:
    """Attempt to acquire a scoped read capability token for a local managed Monitor."""
    parsed = urlsplit(origin)
    if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        port = parsed.port or 8788
        try:
            from llm_monitor.local_client import ManagedMonitorClient
            client = ManagedMonitorClient(port=port, host=parsed.hostname)
            return client.acquire_capability_token()
        except Exception:
            return None
    return None


def _build_monitor_headers(origin: str) -> dict[str, str]:
    headers = {"Origin": origin}
    auth = os.environ.get("LLM_MONITOR_AUTHORIZATION")
    if not auth:
        token = resolve_managed_monitor_auth(origin)
        if token:
            auth = f"Bearer {token}"
    cookie = os.environ.get("LLM_MONITOR_SESSION_COOKIE")
    if not cookie and not auth:
        candidates = [
            Path("reports/agent-bench-suite/monitor_session.env"),
            Path.cwd() / "reports/agent-bench-suite/monitor_session.env",
            *(p / "reports/agent-bench-suite/monitor_session.env" for p in Path(__file__).resolve().parents),
        ]
        for session_env in candidates:
            if session_env.is_file():
                try:
                    for line in session_env.read_text(encoding="utf-8").splitlines():
                        if line.startswith("LLM_MONITOR_SESSION_COOKIE="):
                            cookie = line.split("=", 1)[1].strip()
                            break
                except OSError:
                    pass
                if cookie:
                    break
    if auth:
        headers["Authorization"] = auth
    if cookie:
        headers["Cookie"] = cookie
    return headers


def request_snapshot(*, monitor_url: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """Return request IDs only; callers never persist prompt or response contents."""
    origin = _monitor_origin(monitor_url)
    headers = _build_monitor_headers(origin)
    own_client = client is None
    active_client = client or httpx.Client(timeout=3.0, follow_redirects=False, trust_env=False)
    try:
        response = active_client.get(f"{origin}/api/inference/v1/requests", headers=headers)
        response.raise_for_status()
        payload = response.json()
        if payload.get("capture_state") != "available":
            raise MonitorPreflightError("LLM Monitor live request capture is unavailable")
        rows = payload.get("requests")
        if not isinstance(rows, list):
            raise MonitorPreflightError("LLM Monitor returned an invalid request inventory")
        requests = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("request_id"):
                continue
            requests.append({key: row.get(key) for key in (
                "request_id", "provider_model_id", "model_name", "provider_request_id",
                "input_tokens", "output_tokens", "state", "started_at", "ended_at",
            ) if row.get(key) is not None})
        return {"capture_state": "available", "requests": requests,
                "request_ids": sorted(str(row["request_id"]) for row in requests)}
    except MonitorPreflightError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise MonitorPreflightError(
            f"LLM Monitor request capture check failed at {origin}: {type(error).__name__}: {error}"
        ) from error
    finally:
        if own_client:
            active_client.close()


def verify_recorded_requests(*, monitor_url: str, request_ids: list[str], recording: str,
                             client: httpx.Client | None = None, timeout_seconds: float = 10) -> dict[str, Any]:
    """Confirm observed request IDs reached durable history without emitting their content."""
    origin = _monitor_origin(monitor_url)
    headers = _build_monitor_headers(origin)
    own_client = client is None
    active_client = client or httpx.Client(timeout=3.0, follow_redirects=False, trust_env=False)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            recorded = []
            roles: set[str] = set()
            for request_id in request_ids:
                response = active_client.get(f"{origin}/api/inference/v1/history/{quote(request_id, safe='')}", headers=headers)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                row = response.json().get("request", {})
                if (row.get("request_id") == request_id and row.get("recording_mode") == recording
                        and row.get("state") in {"completed", "failed", "cancelled"}):
                    recorded.append(request_id)
                    roles.update(item.get("role") for item in row.get("content", []) if isinstance(item, dict))
            complete = len(recorded) == len(request_ids) and bool(request_ids)
            if complete and (recording != "content" or {"user", "assistant"}.issubset(roles)):
                return {"recorded_request_ids": recorded, "input_observed": "user" in roles,
                        "output_observed": "assistant" in roles}
            if time.monotonic() >= deadline:
                raise MonitorPreflightError("observed monitor requests or required content were not persisted")
            time.sleep(0.25)
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise MonitorPreflightError(f"monitor recording verification failed at {origin}: {type(error).__name__}") from error
    finally:
        if own_client:
            active_client.close()


def _evaluate_protected_route(
    status_payload: dict[str, Any],
    *,
    origin: str,
    require_protected_route: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    """Validate route/runtime qualification and Coordinator readiness, not future request admission."""
    if not require_protected_route:
        return ({"verified": False, "upstream_base_url": status_payload.get("gateway_upstream")},
                status_payload.get("runtime_identity"), status_payload.get("coordinator_readiness"))

    upstream_keys = ("gateway_upstream", "upstream_base_url", "upstream_url", "target_url",
                     "inference_base_url", "provider_url")
    configured_upstreams = [status_payload[key].strip() for key in upstream_keys
                            if isinstance(status_payload.get(key), str) and status_payload[key].strip()]
    if not configured_upstreams:
        raise MonitorPreflightError("legacy Monitor status lacks effective gateway upstream configuration")
    upstream_url = configured_upstreams[0]
    if any(value.rstrip("/") != upstream_url.rstrip("/") for value in configured_upstreams[1:]):
        raise MonitorPreflightError("LLM Monitor status reports contradictory upstream URLs")
    try:
        parsed = urlsplit(upstream_url)
        upstream_port = parsed.port
    except ValueError as error:
        raise MonitorPreflightError("LLM Monitor upstream URL is malformed") from error
    if upstream_port == 1234:
        raise MonitorPreflightError(
            "LLM Monitor upstream points to direct LM Studio (:1234), bypassing Resource Coordinator (:1235)"
        )
    if (parsed.scheme not in {"http", "https"} or upstream_port != 1235
            or (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
            or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
        raise MonitorPreflightError(
            f"LLM Monitor upstream {upstream_url!r} is not proven to route through Resource Coordinator (:1235)"
        )
    routing = {"verified": True, "upstream_base_url": upstream_url}

    raw_identity = status_payload.get("runtime_identity")
    if not isinstance(raw_identity, dict):
        raise MonitorPreflightError("LLM Monitor status lacks managed runtime identity")
    runtime_identity = dict(raw_identity)
    if (not isinstance(runtime_identity.get("instance_id"), str) or not runtime_identity["instance_id"].strip()
            or not isinstance(runtime_identity.get("config_fingerprint"), str)
            or not runtime_identity["config_fingerprint"].strip()):
        raise MonitorPreflightError("LLM Monitor status has incomplete managed runtime identity")
    fingerprint = runtime_identity["config_fingerprint"]
    fingerprint_digest = fingerprint.removeprefix("sha256:")
    if (not fingerprint.startswith("sha256:") or len(fingerprint_digest) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint_digest.lower())):
        raise MonitorPreflightError("LLM Monitor status has an invalid configuration fingerprint")
    if (status_payload.get("gateway_enabled") is not True or runtime_identity.get("gateway_enabled") is not True):
        raise MonitorPreflightError("LLM Monitor gateway is disabled or runtime identity contradicts gateway status")
    identity_upstream = runtime_identity.get("gateway_upstream")
    if not isinstance(identity_upstream, str) or identity_upstream.rstrip("/") != upstream_url.rstrip("/"):
        raise MonitorPreflightError("LLM Monitor runtime identity upstream does not match effective gateway upstream")
    if runtime_identity.get("host_origin", "").rstrip("/") != origin.rstrip("/"):
        raise MonitorPreflightError("LLM Monitor runtime identity does not match the selected Monitor origin")
    runtime_identity["host_origin"] = origin

    coordinator = status_payload.get("coordinator_readiness")
    if not isinstance(coordinator, dict):
        raise MonitorPreflightError("LLM Monitor status lacks bounded Coordinator readiness evidence")
    coordinator_url = coordinator.get("coordinator_url")
    parsed_origin = urlsplit(upstream_url)
    expected_coordinator_url = f"{parsed_origin.scheme}://{parsed_origin.netloc}"
    if not isinstance(coordinator_url, str) or coordinator_url.rstrip("/") != expected_coordinator_url.rstrip("/"):
        raise MonitorPreflightError("Coordinator readiness URL does not match the configured Monitor upstream")
    if coordinator.get("status") == "unavailable":
        raise MonitorPreflightError("Resource Coordinator readiness is unavailable")
    coordinator_runtime = coordinator.get("runtime_identity")
    if not isinstance(coordinator_runtime, dict) or not coordinator_runtime.get("instance_id"):
        raise MonitorPreflightError("Coordinator readiness lacks runtime identity")
    _require_fresh_timestamp(status_payload.get("observed_at"), "LLM Monitor qualification")
    _require_fresh_timestamp(status_payload.get("refreshed_at"), "LLM Monitor service snapshot")
    _require_fresh_timestamp(coordinator.get("observed_at"), "Coordinator readiness")
    restrictions = coordinator.get("active_restrictions")
    if not isinstance(restrictions, list):
        raise MonitorPreflightError("Coordinator readiness lacks active safety restriction evidence")
    if restrictions:
        raise MonitorPreflightError(f"Coordinator has active safety restrictions: {', '.join(map(str, restrictions))}")
    if coordinator.get("status") != "ready" or coordinator.get("is_ready") is not True:
        raise MonitorPreflightError("Resource Coordinator readiness is unavailable or blocked")
    return routing, runtime_identity, coordinator


def _require_fresh_timestamp(value: Any, label: str) -> None:
    from datetime import datetime, timezone

    if not isinstance(value, str) or not value.strip():
        raise MonitorPreflightError(f"{label} is missing its observed timestamp")
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MonitorPreflightError(f"{label} has a malformed observed timestamp") from error
    now = datetime.now(timezone.utc)
    if observed.utcoffset() is None or observed > now or (now - observed).total_seconds() > _QUALIFICATION_MAX_AGE_SECONDS:
        raise MonitorPreflightError(f"{label} timestamp is stale or invalid")


def validate_monitor(
    *, agent: str, model: str, monitor_url: str | None = None, recording: str = "off",
    api_format: str | None = None, client: httpx.Client | None = None, monitor_host_url: str | None = None,
) -> dict[str, Any]:
    if recording not in {"off", "metadata", "content"}:
        raise MonitorPreflightError(f"unsupported recording mode: {recording}")
    if agent.lower() in ("opencode", "opencode-v2") and api_format != "openai_chat_completions":
        raise MonitorPreflightError(f"{agent} monitor routing requires openai_chat_completions API format")
    gateway = monitor_url or DEFAULT_MONITOR_URL
    origin = host_monitor_origin(gateway, monitor_host_url)
    headers = _build_monitor_headers(origin)
    own_client = client is None
    active_client = client or httpx.Client(timeout=3.0, follow_redirects=False, trust_env=False)
    try:
        models_response = active_client.get(origin + "/api/inference/v1/models", headers=headers)
        models_response.raise_for_status()
        models_payload = models_response.json()
        model_list = models_payload.get("data", models_payload.get("models", []))
        if not isinstance(model_list, list) or not model_list:
            raise MonitorPreflightError("LLM Monitor gateway returned an invalid model inventory")
        model_ids = set()
        for item in model_list:
            if isinstance(item, dict) and item.get("state") != "not-loaded":
                model_ids.update(str(value) for value in (
                    item.get("provider_model_id"), item.get("id"), item.get("model_instance_id"),
                    *(item.get("loaded_instance_ids") or []),
                ) if value)
        model_leaf = model.split("/", 1)[-1]
        if model_ids and model_leaf not in model_ids and model not in model_ids:
            raise MonitorPreflightError("effective model is absent from the selected LLM Monitor gateway")
        response = active_client.get(f"{origin}/api/inference/v1/status", headers=headers)
        response.raise_for_status()
        status = response.json()
        availability = status.get("availability")
        if availability not in {"available", "connected"}:
            raise MonitorPreflightError("LLM Monitor inference service is not available")
        require_protected_route = agent.lower().strip() in _LOCAL_HARBOR_AGENTS
        routing, runtime_identity, coordinator_readiness = _evaluate_protected_route(
            status, origin=origin, require_protected_route=require_protected_route
        )
        recording_response = active_client.get(f"{origin}/api/inference/v1/recording/status", headers=headers)
        recording_response.raise_for_status()
        recording_payload = recording_response.json().get("recording", {})
        if recording == "off":
            actual = "off" if recording_payload.get("status") == "disabled" or recording_payload.get("recording_enabled") is False else recording_payload.get("mode")
        else:
            actual = recording_payload.get("mode")
        if actual != recording:
            raise MonitorPreflightError(
                f"required LLM Monitor recording mode {recording!r} does not match active mode {actual!r}"
            )
        dropped = recording_payload.get("dropped_count", 0)
        healthy = recording_payload.get("healthy", recording_payload.get("is_healthy"))
        if recording != "off" and (healthy is not True or dropped or recording_payload.get("last_error")):
            raise MonitorPreflightError("LLM Monitor recorder health is degraded or observations were dropped")
        capture = request_snapshot(monitor_url=origin, client=active_client)
        return {
            "verified": True, "gateway_url": gateway, "agent": agent, "model": model,
            "monitor_host_url": origin, "monitor_model_inventory_verified": True,
            "api_format": api_format, "monitor_availability": availability,
            "configured_protected_routing": routing,
            "qualified_runtime_identity": runtime_identity,
            "coordinator_readiness": coordinator_readiness,
            "qualification_observed_at": status.get("observed_at"),
            "dispatch_admission": {
                "status": "not_yet_observed",
                "enforced_by": coordinator_readiness.get("coordinator_url")
                if isinstance(coordinator_readiness, dict) else None,
            },
            "upstream_base_url": routing.get("upstream_base_url"),
            "recording_mode": actual,
            "recording_healthy": healthy,
            "dropped_observations": dropped,
            "recording_error": recording_payload.get("last_error"),
            "request_capture_state": capture["capture_state"],
        }
    except MonitorPreflightError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise MonitorPreflightError(f"LLM Monitor preflight failed at {origin}: {type(error).__name__}: {error}") from error
    finally:
        if own_client:
            active_client.close()
