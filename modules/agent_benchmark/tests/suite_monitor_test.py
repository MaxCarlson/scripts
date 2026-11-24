from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
                return httpx.Response(200, json=_valid_status_payload("http://127.0.0.1:8788"))
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


def _valid_status_payload(
    host_origin: str = "http://127.0.0.1:8788", availability: str = "available"
) -> dict:
    return {
        "availability": availability,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "gateway_enabled": True,
        "gateway_upstream": "http://127.0.0.1:1235",
        "runtime_identity": {
            "instance_id": "monitor-1", "config_fingerprint": "sha256:" + "a" * 64, "gateway_enabled": True,
            "gateway_upstream": "http://127.0.0.1:1235", "host_origin": host_origin,
        },
        "coordinator_readiness": {
            "status": "ready", "is_ready": True, "coordinator_url": "http://127.0.0.1:1235",
            "observed_at": datetime.now(timezone.utc).isoformat(), "runtime_identity": {"instance_id": "rc-1"},
            "active_restrictions": [],
        },
    }


def _client(
    recording: dict, availability: str = "available", model_id: str = "model",
    host_origin: str = "http://127.0.0.1:8788",
) -> httpx.Client:
    status_payload = _valid_status_payload(host_origin, availability)
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, json={"data": [{"id": model_id}]})
        if request.url.path.endswith("/api/inference/v1/status"):
            return httpx.Response(200, json=status_payload)
        if request.url.path.endswith("/api/inference/v1/requests"):
            return httpx.Response(200, json={"capture_state": "available", "requests": []})
        return httpx.Response(200, json={"recording": recording})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_with_status_payload(status_payload: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, json={"data": [{"id": "model"}]})
        if request.url.path.endswith("/api/inference/v1/status"):
            return httpx.Response(200, json=status_payload)
        if request.url.path.endswith("/api/inference/v1/requests"):
            return httpx.Response(200, json={"capture_state": "available", "requests": []})
        return httpx.Response(200, json={"recording": {"mode": "off", "status": "disabled"}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_monitor_preflight_requires_exact_recording_mode():
    result = validate_monitor(
        agent="opencode", model="openai/qwen38_23GB", api_format="openai_chat_completions",
        recording="content", monitor_url="http://monitor:8788/v1",
        client=_client({"mode": "content", "healthy": True, "dropped_count": 0}, model_id="qwen38_23GB",
                       host_origin="http://monitor:8788"),
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
        httpx.Response(200, json=_valid_status_payload()) if request.url.path.endswith("/api/inference/v1/status") else
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


def test_monitor_preflight_qualifies_protected_route_without_future_admission():
    # 1. Direct :1234 upstream fails closed
    with pytest.raises(MonitorPreflightError, match="bypassing Resource Coordinator"):
        validate_monitor(
            agent="opencode",
            model="openai/model",
            api_format="openai_chat_completions",
            client=_client_with_status_payload({"availability": "available", "upstream_base_url": "http://127.0.0.1:1234/v1"}),
        )

    # Route readiness qualifies dispatch; admission of a future request is not knowable here.
    res_proven = validate_monitor(
        agent="opencode",
        model="openai/model",
        api_format="openai_chat_completions",
        client=_client_with_status_payload({
            "schema_version": 1,
            "availability": "connected",
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "gateway_enabled": True,
            "gateway_upstream": "http://127.0.0.1:1235",
            "runtime_identity": {
                "instance_id": "inst-1",
                "config_fingerprint": "sha256:" + "a" * 64,
                "gateway_enabled": True,
                "gateway_upstream": "http://127.0.0.1:1235",
                "host_origin": "http://127.0.0.1:8788",
            },
            "coordinator_readiness": {
                "status": "ready",
                "is_ready": True,
                "coordinator_url": "http://127.0.0.1:1235",
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "runtime_identity": {"instance_id": "rc-1"},
                "active_restrictions": [],
            },
        }),
    )
    assert res_proven["verified"] is True
    assert res_proven["configured_protected_routing"]["verified"] is True
    assert res_proven["qualified_runtime_identity"]["instance_id"] == "inst-1"
    assert res_proven["coordinator_readiness"]["status"] == "ready"
    assert res_proven["dispatch_admission"]["status"] == "not_yet_observed"


def test_monitor_preflight_rejects_missing_readiness_timestamp():
    status = {
        "availability": "connected",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "gateway_enabled": True,
        "gateway_upstream": "http://127.0.0.1:1235",
        "runtime_identity": {
            "instance_id": "inst-1", "config_fingerprint": "sha256:" + "a" * 64, "gateway_enabled": True,
            "gateway_upstream": "http://127.0.0.1:1235", "host_origin": "http://127.0.0.1:8788",
        },
        "coordinator_readiness": {
            "status": "ready", "is_ready": True, "coordinator_url": "http://127.0.0.1:1235",
            "runtime_identity": {"instance_id": "rc-1"}, "active_restrictions": [],
        },
    }
    with pytest.raises(MonitorPreflightError, match="timestamp"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                         client=_client_with_status_payload(status))


def test_monitor_preflight_rejects_missing_service_snapshot_timestamp():
    status = _valid_status_payload()
    status.pop("refreshed_at")
    with pytest.raises(MonitorPreflightError, match="service snapshot is missing"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                         client=_client_with_status_payload(status))


def test_monitor_preflight_rejects_stale_or_contradictory_runtime_evidence():
    stale = _valid_status_payload()
    stale["observed_at"] = (datetime.now(timezone.utc) - timedelta(seconds=45)).isoformat()
    with pytest.raises(MonitorPreflightError, match="stale or invalid"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                         client=_client_with_status_payload(stale))

    mismatched = _valid_status_payload()
    mismatched["runtime_identity"]["gateway_upstream"] = "http://127.0.0.1:1236"
    with pytest.raises(MonitorPreflightError, match="does not match effective gateway upstream"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                         client=_client_with_status_payload(mismatched))

    conflicting = _valid_status_payload()
    conflicting["upstream_base_url"] = "http://127.0.0.1:1234/v1"
    with pytest.raises(MonitorPreflightError, match="contradictory upstream"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                         client=_client_with_status_payload(conflicting))

    invalid_fingerprint = _valid_status_payload()
    invalid_fingerprint["runtime_identity"]["config_fingerprint"] = "sha256:short"
    with pytest.raises(MonitorPreflightError, match="invalid configuration fingerprint"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                         client=_client_with_status_payload(invalid_fingerprint))


def test_monitor_preflight_rejects_legacy_and_unavailable_coordinator_status():
    with pytest.raises(MonitorPreflightError, match="legacy Monitor status"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                         client=_client_with_status_payload({"availability": "connected"}))

    unavailable = _valid_status_payload()
    unavailable["coordinator_readiness"].update(status="unavailable", is_ready=False)
    with pytest.raises(MonitorPreflightError, match="Coordinator readiness is unavailable"):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                         client=_client_with_status_payload(unavailable))


def test_cloud_agent_monitoring_remains_compatible_with_legacy_status():
    evidence = validate_monitor(
        agent="codex", model="openai/model", recording="off",
        client=_client_with_status_payload({"availability": "connected"}),
    )
    assert evidence["verified"] is True
    assert evidence["configured_protected_routing"]["verified"] is False


@pytest.mark.parametrize("restriction", ["maintenance_active", "recovery_required"])
def test_monitor_preflight_rejects_active_coordinator_restrictions(restriction):
    status = {
            "availability": "connected", "observed_at": datetime.now(timezone.utc).isoformat(),
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "gateway_enabled": True,
        "gateway_upstream": "http://127.0.0.1:1235",
        "runtime_identity": {
            "instance_id": "inst-1", "config_fingerprint": "sha256:" + "a" * 64, "gateway_enabled": True,
            "gateway_upstream": "http://127.0.0.1:1235", "host_origin": "http://127.0.0.1:8788",
        },
        "coordinator_readiness": {
            "status": "blocked", "is_ready": False, "coordinator_url": "http://127.0.0.1:1235",
            "observed_at": datetime.now(timezone.utc).isoformat(), "runtime_identity": {"instance_id": "rc-1"},
            "active_restrictions": [restriction],
        },
    }
    with pytest.raises(MonitorPreflightError, match=restriction):
        validate_monitor(agent="opencode", model="openai/model", api_format="openai_chat_completions",
                         client=_client_with_status_payload(status))


def test_actual_monitor_status_producer_qualifies_benchmark_consumer(tmp_path, monkeypatch):
    from fastapi import APIRouter
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from llm_monitor.inference_web import create_inference_web_app
    from llm_monitor.inference_models import CaptureCapabilities
    import sys
    from types import SimpleNamespace

    class CapabilityManager:
        instance_id = "monitor-1"

        @staticmethod
        def verify_token(token, _scope, instance_id):
            return token == "valid" and instance_id == "monitor-1"

    def create_app(*, api_router, **_kwargs):
        app = FastAPI()
        app.include_router(api_router)

        @app.middleware("http")
        async def require_capability(request, call_next):
            if request.url.path.startswith("/api/"):
                token = request.headers.get("authorization", "").removeprefix("Bearer ")
                verifier = getattr(app.state, "capability_verifier", None)
                if verifier is None or not verifier(token, request):
                    return JSONResponse({"detail": "unauthorized"}, status_code=401)
            return await call_next(request)

        return app

    monkeypatch.setitem(sys.modules, "web_ui_tools", SimpleNamespace(create_app=create_app))
    monkeypatch.setenv("LLM_MONITOR_AUTHORIZATION", "Bearer valid")

    class Service:
        gpu_sampler = None

        @staticmethod
        def start():
            pass

        @staticmethod
        def stop():
            pass

        def snapshot(self):
            return {
                "capabilities": CaptureCapabilities.passive_inventory(available=True).to_dict(),
                "server": {"connection_state": "connected"}, "revision": 4,
                "refreshed_at": datetime.now(timezone.utc).isoformat(), "recording": {},
                "hardware_samples": [], "models": [{"provider_model_id": "model", "state": "loaded"}],
                "requests": [],
            }

    class Gateway:
        upstream = "http://127.0.0.1:1235/v1"
        correlation_registry = None

        @staticmethod
        def router():
            router = APIRouter()

            @router.get("/v1/models")
            def models():
                return {"data": [{"id": "model"}]}

            return router

        @staticmethod
        def close():
            pass

    import httpx as monitor_httpx

    coordinator_state = {"payload": {
            "status": "online", "is_ready": True,
            "service_state": "ready",
            "runtime": {"instance_id": "rc-1", "revision": "source-1"},
            "gpu_inference": {"is_restart_inhibited": False, "recovery": {"required": False}},
                "maintenance": {"state": "idle", "restart_inhibited": False, "gpu_admission_permitted": True},
                "gaming": {"state": "inactive"},
    }}

    def coordinator_get(url, **kwargs):
        if coordinator_state["payload"] is None:
            request = monitor_httpx.Request("GET", url)
            raise monitor_httpx.ConnectError("offline", request=request)
        return monitor_httpx.Response(
            200, request=monitor_httpx.Request("GET", url), json=coordinator_state["payload"]
        )

    monkeypatch.setattr(monitor_httpx, "get", coordinator_get)
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_inference_web_app(
        Service(), login_code="local-code", static_dir=static_dir, gateway=Gateway(),
        capability_manager=CapabilityManager(),
        runtime_identity={
            "instance_id": "monitor-1", "config_fingerprint": "sha256:" + "d" * 64, "gateway_enabled": True,
            "gateway_upstream": Gateway.upstream, "host_origin": "http://127.0.0.1:8788",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    with TestClient(app, base_url="http://127.0.0.1:8788") as producer_client:
        def dispatch_to_monitor(request: httpx.Request) -> httpx.Response:
            headers = dict(request.headers)
            response = producer_client.request(request.method, str(request.url), headers=headers)
            return httpx.Response(response.status_code, headers=response.headers, content=response.content, request=request)

        with httpx.Client(transport=httpx.MockTransport(dispatch_to_monitor)) as benchmark_client:
            evidence = validate_monitor(
                agent="opencode", model="openai/model", monitor_url="http://host.docker.internal:8788/v1",
                monitor_host_url="http://127.0.0.1:8788", api_format="openai_chat_completions",
                client=benchmark_client,
            )
            coordinator_state["payload"]["service_state"] = "standalone"
            with pytest.raises(MonitorPreflightError, match="coordinator_service_not_ready_or_unknown"):
                validate_monitor(
                    agent="opencode", model="openai/model", monitor_url="http://host.docker.internal:8788/v1",
                    monitor_host_url="http://127.0.0.1:8788", api_format="openai_chat_completions",
                    client=benchmark_client,
                )
            coordinator_state["payload"]["service_state"] = "ready"
            coordinator_state["payload"]["maintenance"] = {
                "state": "active", "restart_inhibited": True, "gpu_admission_permitted": False,
            }
            with pytest.raises(MonitorPreflightError, match="maintenance_active_or_unknown"):
                validate_monitor(
                    agent="opencode", model="openai/model", monitor_url="http://host.docker.internal:8788/v1",
                    monitor_host_url="http://127.0.0.1:8788", api_format="openai_chat_completions",
                    client=benchmark_client,
                )
            coordinator_state["payload"]["maintenance"] = {
                "state": "idle", "restart_inhibited": False, "gpu_admission_permitted": True,
            }
            coordinator_state["payload"]["gpu_inference"]["recovery"] = {"required": True}
            with pytest.raises(MonitorPreflightError, match="recovery_required_or_unknown"):
                validate_monitor(
                    agent="opencode", model="openai/model", monitor_url="http://host.docker.internal:8788/v1",
                    monitor_host_url="http://127.0.0.1:8788", api_format="openai_chat_completions",
                    client=benchmark_client,
                )
            coordinator_state["payload"] = None
            with pytest.raises(MonitorPreflightError, match="readiness is unavailable"):
                validate_monitor(
                    agent="opencode", model="openai/model", monitor_url="http://host.docker.internal:8788/v1",
                    monitor_host_url="http://127.0.0.1:8788", api_format="openai_chat_completions",
                    client=benchmark_client,
                )

    assert evidence["verified"] is True
    assert evidence["qualified_runtime_identity"]["instance_id"] == "monitor-1"
    assert evidence["configured_protected_routing"]["upstream_base_url"] == Gateway.upstream
    assert evidence["coordinator_readiness"]["runtime_identity"]["instance_id"] == "rc-1"
    assert evidence["dispatch_admission"]["status"] == "not_yet_observed"


def test_post_execution_evidence_rejects_monitor_or_coordinator_replacement():
    from agent_benchmark.suite import _require_monitor_runtime_continuity

    before = {
        "qualified_runtime_identity": {"instance_id": "monitor-1", "config_fingerprint": "sha256:" + "a" * 64},
        "configured_protected_routing": {"verified": True, "upstream_base_url": "http://127.0.0.1:1235"},
        "coordinator_readiness": {"runtime_identity": {"instance_id": "rc-1", "revision": "one"}},
    }
    _require_monitor_runtime_continuity(before, before)

    changed_monitor = {
        **before,
        "qualified_runtime_identity": {"instance_id": "monitor-2", "config_fingerprint": "sha256:" + "b" * 64},
    }
    with pytest.raises(MonitorPreflightError, match="runtime changed"):
        _require_monitor_runtime_continuity(before, changed_monitor)

    changed_configuration = {
        **before,
        "qualified_runtime_identity": {"instance_id": "monitor-1", "config_fingerprint": "sha256:" + "c" * 64},
    }
    with pytest.raises(MonitorPreflightError, match="runtime changed"):
        _require_monitor_runtime_continuity(before, changed_configuration)

    changed_coordinator = {
        **before,
        "coordinator_readiness": {"runtime_identity": {"instance_id": "rc-2", "revision": "two"}},
    }
    with pytest.raises(MonitorPreflightError, match="runtime changed"):
        _require_monitor_runtime_continuity(before, changed_coordinator)

