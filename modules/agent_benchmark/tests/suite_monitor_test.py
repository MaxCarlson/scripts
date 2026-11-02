from __future__ import annotations

import httpx
import pytest

from agent_benchmark.suite_monitor import (
    MonitorPreflightError, host_monitor_origin, request_snapshot, validate_monitor, verify_recorded_requests,
)


def test_legacy_container_url_resolves_to_windows_host_loopback():
    assert host_monitor_origin("http://host.docker.internal:8788/v1") == "http://127.0.0.1:8788"
    assert host_monitor_origin("http://example:9999/v1", "http://127.0.0.1:4444") == "http://127.0.0.1:4444"


def test_monitor_preflight_uses_authenticated_host_api_and_container_gateway():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("origin")))
        assert request.url.host == "127.0.0.1"
        assert request.headers["origin"] == "http://127.0.0.1:8788"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"models": [{"provider_model_id": "qwen38_23GB", "state": "loaded"}]})
        if request.url.path.endswith("/status") and not request.url.path.endswith("/recording/status"):
            return httpx.Response(200, json={"availability": "connected"})
        if request.url.path.endswith("/requests"):
            return httpx.Response(200, json={"capture_state": "available", "requests": []})
        return httpx.Response(200, json={"recording": {"mode": "content", "healthy": True, "dropped_count": 0}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = validate_monitor(agent="opencode", model="openai/qwen38_23GB",
                                  monitor_url="http://host.docker.internal:8788/v1",
                                  monitor_host_url="http://127.0.0.1:8788", recording="content",
                                  api_format="openai_chat_completions", client=client)
    assert result["gateway_url"] == "http://host.docker.internal:8788/v1"
    assert any(url.endswith("/api/inference/v1/models") for url, _ in seen)


def test_missing_monitor_reports_endpoint_and_cause():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MonitorPreflightError, match="127.0.0.1:8788"):
            validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                             monitor_host_url="http://127.0.0.1:8788", client=client)


def test_recording_coverage_requires_completed_persisted_request_and_response():
    def handler(request):
        assert request.headers["origin"] == "http://127.0.0.1:8788"
        return httpx.Response(200, json={"request": {"request_id": "r1", "state": "completed",
            "recording_mode": "content", "content": [{"role": "user", "text": "private"},
                                                     {"role": "assistant", "text": "private"}]}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = verify_recorded_requests(monitor_url="http://127.0.0.1:8788", request_ids=["r1"],
                                          recording="content", client=client)
    assert result == {"recorded_request_ids": ["r1"], "input_observed": True, "output_observed": True}
    assert "private" not in str(result)


def test_recording_coverage_fails_closed_when_history_is_missing():
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(404))) as client:
        with pytest.raises(MonitorPreflightError, match="not persisted"):
            verify_recorded_requests(monitor_url="http://127.0.0.1:8788", request_ids=["r1"],
                                     recording="content", client=client, timeout_seconds=0)


def _client(recording: dict, availability: str = "available", model_id: str = "model") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, json={"data": [{"id": model_id}]})
        if request.url.path.endswith("/api/inference/v1/status"):
            return httpx.Response(200, json={"availability": availability})
        if request.url.path.endswith("/api/inference/v1/requests"):
            return httpx.Response(200, json={"capture_state": "available", "requests": []})
        return httpx.Response(200, json={"recording": recording})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_monitor_preflight_requires_exact_recording_mode():
    result = validate_monitor(
        agent="opencode", model="openai/qwen38_23GB", api_format="openai_chat_completions",
        recording="content", monitor_url="http://monitor:8788/v1",
        client=_client({"mode": "content", "healthy": True, "dropped_count": 0}, model_id="qwen38_23GB"),
    )
    assert result["verified"] is True
    assert result["recording_mode"] == "content"


def test_monitor_preflight_fails_closed_on_responses_protocol():
    with pytest.raises(MonitorPreflightError, match="requires openai_chat_completions"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_responses", client=_client({}))


def test_monitor_preflight_rejects_unavailable_gateway():
    with pytest.raises(MonitorPreflightError, match="not available"):
        validate_monitor(
            agent="opencode", model="openai/model", api_format="openai_chat_completions",
            client=_client({"mode": "off"}, availability="unavailable"),
        )


def test_monitor_preflight_rejects_dropped_observations():
    with pytest.raises(MonitorPreflightError, match="recorder health"):
        validate_monitor(
            agent="opencode", model="openai/model", api_format="openai_chat_completions",
            recording="metadata", client=_client({"mode": "metadata", "healthy": False, "dropped_count": 1}),
        )


def test_monitor_preflight_rejects_missing_effective_model():
    client = _client({"mode": "off", "status": "disabled"})
    with pytest.raises(MonitorPreflightError, match="model is absent"):
        validate_monitor(agent="opencode", model="openai/other", api_format="openai_chat_completions", client=client)


def test_monitor_preflight_requires_live_request_capture():
    client = _client({"mode": "off", "status": "disabled"})
    client._transport = httpx.MockTransport(lambda request: (
        httpx.Response(200, json={"data": [{"id": "model"}]}) if request.url.path.endswith("/v1/models") else
        httpx.Response(200, json={"availability": "available"}) if request.url.path.endswith("/api/inference/v1/status") else
        httpx.Response(200, json={"capture_state": "unavailable", "requests": []}) if request.url.path.endswith("/api/inference/v1/requests") else
        httpx.Response(200, json={"recording": {"status": "disabled"}})
    ))
    with pytest.raises(MonitorPreflightError, match="request capture is unavailable"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions", client=client)


def test_request_snapshot_keeps_correlation_and_token_metadata_without_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"capture_state": "available", "requests": [{
            "request_id": "r-1", "provider_model_id": "model", "input_tokens": 12,
            "output_tokens": 3, "content": [{"text": "private prompt"}],
        }]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = request_snapshot(monitor_url="http://monitor/v1", client=client)
    assert result["request_ids"] == ["r-1"]
    assert result["requests"][0]["input_tokens"] == 12
    assert "content" not in result["requests"][0]


def test_build_monitor_headers_auto_bootstraps_managed_capability(monkeypatch):
    from agent_benchmark.suite_monitor import _build_monitor_headers

    monkeypatch.delenv("LLM_MONITOR_AUTHORIZATION", raising=False)
    monkeypatch.delenv("LLM_MONITOR_SESSION_COOKIE", raising=False)

    # Mock resolve_managed_monitor_auth
    monkeypatch.setattr(
        "agent_benchmark.suite_monitor.resolve_managed_monitor_auth",
        lambda origin: "token-managed-xyz-123",
    )

    headers = _build_monitor_headers("http://127.0.0.1:8788")
    assert headers["Origin"] == "http://127.0.0.1:8788"
    assert headers["Authorization"] == "Bearer token-managed-xyz-123"
    assert "Cookie" not in headers

