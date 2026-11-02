"""Fail-closed preflight for monitored Harbor runs."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .suite import DEFAULT_MONITOR_URL


class MonitorPreflightError(RuntimeError):
    """The required monitor route or recording mode could not be verified."""


def _monitor_origin(gateway_url: str) -> str:
    parsed = urlsplit(gateway_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MonitorPreflightError("monitor URL must be an absolute HTTP(S) URL")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def request_snapshot(*, monitor_url: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """Return request IDs only; callers never persist prompt or response contents."""
    origin = _monitor_origin(monitor_url)
    headers = {}
    if os.environ.get("LLM_MONITOR_AUTHORIZATION"):
        headers["Authorization"] = os.environ["LLM_MONITOR_AUTHORIZATION"]
    if os.environ.get("LLM_MONITOR_SESSION_COOKIE"):
        headers["Cookie"] = os.environ["LLM_MONITOR_SESSION_COOKIE"]
    own_client = client is None
    active_client = client or httpx.Client(timeout=3.0, follow_redirects=False)
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
        raise MonitorPreflightError(f"LLM Monitor request capture check failed: {type(error).__name__}") from error
    finally:
        if own_client:
            active_client.close()


def validate_monitor(
    *, agent: str, model: str, monitor_url: str | None = None, recording: str = "off",
    api_format: str | None = None, client: httpx.Client | None = None,
) -> dict[str, Any]:
    if recording not in {"off", "metadata", "content"}:
        raise MonitorPreflightError(f"unsupported recording mode: {recording}")
    if agent.lower() == "opencode" and api_format != "openai_chat_completions":
        raise MonitorPreflightError("OpenCode monitor routing requires openai_chat_completions API format")
    gateway = monitor_url or DEFAULT_MONITOR_URL
    origin = _monitor_origin(gateway)
    headers = {}
    authorization = os.environ.get("LLM_MONITOR_AUTHORIZATION")
    if authorization:
        headers["Authorization"] = authorization
    cookie = os.environ.get("LLM_MONITOR_SESSION_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    own_client = client is None
    active_client = client or httpx.Client(timeout=3.0, follow_redirects=False)
    try:
        models_response = active_client.get(gateway.rstrip("/") + "/models", headers=headers)
        models_response.raise_for_status()
        models_payload = models_response.json()
        model_list = models_payload.get("data", models_payload.get("models", []))
        if not isinstance(model_list, list) or not model_list:
            raise MonitorPreflightError("LLM Monitor gateway returned an invalid model inventory")
        model_ids = {str(item.get("id")) for item in model_list if isinstance(item, dict)}
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
        healthy = recording_payload.get("healthy", recording_payload.get("is_healthy", True))
        if recording != "off" and (healthy is False or dropped):
            raise MonitorPreflightError("LLM Monitor recorder health is degraded or observations were dropped")
        capture = request_snapshot(monitor_url=gateway, client=active_client)
        return {
            "verified": True, "gateway_url": gateway, "agent": agent, "model": model,
            "gateway_models_endpoint_verified": True,
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
        raise MonitorPreflightError(f"LLM Monitor preflight failed: {type(error).__name__}") from error
    finally:
        if own_client:
            active_client.close()
