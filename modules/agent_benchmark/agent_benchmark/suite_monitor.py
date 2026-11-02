"""Fail-closed preflight for monitored Harbor runs."""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from .suite import DEFAULT_MONITOR_URL


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


def request_snapshot(*, monitor_url: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """Return request IDs only; callers never persist prompt or response contents."""
    origin = _monitor_origin(monitor_url)
    headers = {"Origin": origin}
    if os.environ.get("LLM_MONITOR_AUTHORIZATION"):
        headers["Authorization"] = os.environ["LLM_MONITOR_AUTHORIZATION"]
    if os.environ.get("LLM_MONITOR_SESSION_COOKIE"):
        headers["Cookie"] = os.environ["LLM_MONITOR_SESSION_COOKIE"]
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
    headers = {"Origin": origin}
    if os.environ.get("LLM_MONITOR_AUTHORIZATION"):
        headers["Authorization"] = os.environ["LLM_MONITOR_AUTHORIZATION"]
    if os.environ.get("LLM_MONITOR_SESSION_COOKIE"):
        headers["Cookie"] = os.environ["LLM_MONITOR_SESSION_COOKIE"]
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


def validate_monitor(
    *, agent: str, model: str, monitor_url: str | None = None, recording: str = "off",
    api_format: str | None = None, client: httpx.Client | None = None, monitor_host_url: str | None = None,
) -> dict[str, Any]:
    if recording not in {"off", "metadata", "content"}:
        raise MonitorPreflightError(f"unsupported recording mode: {recording}")
    if agent.lower() == "opencode" and api_format != "openai_chat_completions":
        raise MonitorPreflightError("OpenCode monitor routing requires openai_chat_completions API format")
    gateway = monitor_url or DEFAULT_MONITOR_URL
    origin = host_monitor_origin(gateway, monitor_host_url)
    headers = {"Origin": origin}
    authorization = os.environ.get("LLM_MONITOR_AUTHORIZATION")
    if authorization:
        headers["Authorization"] = authorization
    cookie = os.environ.get("LLM_MONITOR_SESSION_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
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
