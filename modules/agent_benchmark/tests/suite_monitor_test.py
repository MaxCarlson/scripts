from __future__ import annotations

import httpx
import pytest

from agent_benchmark.suite_monitor import MonitorPreflightError, request_snapshot, validate_monitor


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
