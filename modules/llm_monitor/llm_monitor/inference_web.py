"""Authenticated versioned HTTP API for the standalone inference overview."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .gateway import OpenAIInferenceGateway, RequestEventHub
from .inference_analysis import compute_model_analytics
from .inference_models import InferenceRequest
from .inference_service import InferenceMonitoringService

STATIC_DIR = Path(__file__).resolve().parent / "web_static"
SESSION_COOKIE_NAME = "llm_monitor_session"


class RecordingModePayload(BaseModel):
    mode: str


class CorrelationExecutionPayload(BaseModel):
    run_id: str
    task_id: str
    execution_id: str
    repetition_id: str | None = None
    variant_id: str | None = None


class CorrelationCompletionPayload(BaseModel):
    trial_id: str | None = None


def create_inference_web_app(
    service: InferenceMonitoringService,
    *,
    login_code: str,
    static_dir: str | Path = STATIC_DIR,
    gateway: OpenAIInferenceGateway | None = None,
    event_hub: RequestEventHub | None = None,
    recorder: Any | None = None,
    history_store: Any | None = None,
    capability_manager: Any | None = None,
    runtime_identity: dict[str, Any] | None = None,
) -> FastAPI:
    """Create the standalone UI app without opening a telemetry database."""
    try:
        from web_ui_tools import create_app
    except ImportError as error:
        raise RuntimeError("Install llm-monitor[web] to use the browser dashboard.") from error

    router = APIRouter(prefix="/api/inference/v1")
    events = event_hub or RequestEventHub()
    if hasattr(service, "gpu_sampler") and service.gpu_sampler is not None:
        service.gpu_sampler.event_hub = events

    @router.get("/status")
    def status() -> dict[str, Any]:
        snapshot = service.snapshot()
        capabilities = snapshot["capabilities"]
        if gateway is not None:
            capabilities = {
                **capabilities,
                "request_lifecycle": {"state": "available", "source": "gateway"},
                "structured_input": {"state": "available", "source": "gateway"},
                "reasoning_text": {"state": "streaming", "source": "upstream_sse"},
                "output_text": {"state": "streaming", "source": "upstream_sse"},
                "request_timing": {"state": "available", "source": "gateway_observed"},
                "token_usage": {"state": "available", "source": "provider_reported_or_unavailable"},
                "aggregate_metrics": {"state": "available", "source": "in_memory_analytics"},
            }
        if hasattr(service, "gpu_sampler") and service.gpu_sampler and service.gpu_sampler.is_available:
            capabilities["gpu_samples"] = {"state": "available", "source": "resource_metrics.nvidia_smi"}
        gateway_upstream = getattr(gateway, "upstream", None) if gateway is not None else None
        identity = _public_runtime_identity(
            runtime_identity,
            gateway_enabled=gateway is not None,
            gateway_upstream=gateway_upstream,
        )
        observed_at = datetime.now(timezone.utc).isoformat()
        coordinator_readiness = _coordinator_readiness(gateway_upstream) if gateway_upstream else {
            "status": "unavailable",
            "is_ready": False,
            "coordinator_url": None,
            "observed_at": observed_at,
            "runtime_identity": None,
            "active_restrictions": ["gateway_disabled"],
        }
        return {
            "schema_version": 1,
            "availability": snapshot["server"]["connection_state"],
            "revision": snapshot["revision"],
            "refreshed_at": snapshot["refreshed_at"],
            "observed_at": observed_at,
            "gateway_enabled": gateway is not None,
            "gateway_upstream": gateway_upstream,
            "upstream_base_url": gateway_upstream,
            "runtime_identity": identity,
            "coordinator_readiness": coordinator_readiness,
            "capabilities": capabilities,
            "recording": snapshot["recording"],
            "hardware_samples": snapshot.get("hardware_samples", []),
        }

    @router.get("/servers")
    def servers() -> dict[str, Any]:
        snapshot = service.snapshot()
        return {
            "schema_version": 1,
            "availability": snapshot["server"]["connection_state"],
            "servers": [snapshot["server"]],
        }

    @router.get("/models")
    def models() -> dict[str, Any]:
        snapshot = service.snapshot()
        return {
            "schema_version": 1,
            "availability": snapshot["server"]["connection_state"],
            "models": snapshot["models"],
        }

    @router.get("/requests")
    def requests() -> dict[str, Any]:
        snapshot = service.snapshot()
        return {
            "schema_version": 1,
            "availability": "available" if gateway is not None or snapshot["requests"] else "unavailable",
            "capture_state": "available" if gateway is not None else snapshot["capabilities"]["request_lifecycle"]["state"],
            "requests": snapshot["requests"],
        }

    @router.get("/requests/{request_id}")
    def request_detail(request_id: str) -> dict[str, Any]:
        snapshot = service.snapshot()
        request = next((item for item in snapshot["requests"] if item["request_id"] == request_id), None)
        if request is None:
            raise HTTPException(status_code=404, detail="Inference request not found")
        return {"schema_version": 1, "request": request}

    @router.get("/requests/{request_id}/telemetry")
    def request_telemetry(request_id: str) -> dict[str, Any]:
        snapshot = service.snapshot()
        request = next((item for item in snapshot["requests"] if item["request_id"] == request_id), None)
        if request is None:
            raise HTTPException(status_code=404, detail="Inference request not found")
        return {
            "schema_version": 1,
            "request_id": request_id,
            "timing": {
                "started_at": request.get("started_at"),
                "ended_at": request.get("ended_at"),
                "elapsed_seconds": request.get("elapsed_seconds"),
                "time_to_first_text_seconds": request.get("time_to_first_text_seconds"),
                "time_to_first_text_source": request.get("time_to_first_text_source"),
                "generation_tokens_per_second": request.get("generation_tokens_per_second"),
                "generation_speed_source": request.get("generation_speed_source"),
            },
            "tokens": {
                "input_tokens": request.get("input_tokens"),
                "reasoning_tokens": request.get("reasoning_tokens"),
                "output_tokens": request.get("output_tokens"),
                "generated_tokens": request.get("generated_tokens"),
                "usage_source": request.get("usage_source"),
            },
            "hardware": request.get("hardware_telemetry") or {
                "gpu_average_percent": request.get("gpu_average_percent"),
                "gpu_peak_vram_bytes": request.get("gpu_peak_vram_bytes"),
                "gpu_scope": request.get("gpu_scope"),
            },
            "coverage": request.get("coverage", {}),
        }

    @router.get("/hardware")
    def hardware(
        device_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        since: str | None = None,
    ) -> dict[str, Any]:
        status_info = service.gpu_sampler.status() if hasattr(service, "gpu_sampler") and service.gpu_sampler else {}
        is_avail = bool(service.gpu_sampler.is_available) if hasattr(service, "gpu_sampler") and service.gpu_sampler else False
        samples = service.store.hardware_samples(device_id=device_id, limit=limit, since_timestamp=since) if hasattr(service, "store") else []
        return {
            "schema_version": 1,
            "availability": "available" if is_avail else "unavailable",
            "source": "resource_metrics.nvidia_smi",
            "device_count": status_info.get("device_count", 0),
            "devices": status_info.get("devices", []),
            "samples": [s.to_dict() for s in samples],
        }

    @router.get("/analytics")
    def analytics(
        server_instance_id: str | None = None,
        model_id: str | None = None,
        window_seconds: float | None = Query(default=None, gt=0),
    ) -> dict[str, Any]:
        all_requests = service.store.requests() if hasattr(service, "store") else []
        all_samples = service.store.hardware_samples() if hasattr(service, "store") else []
        summary = compute_model_analytics(
            all_requests,
            all_samples,
            server_instance_id=server_instance_id,
            model_id=model_id,
            time_window_seconds=window_seconds,
        )
        return {
            "schema_version": 1,
            "server_instance_id": server_instance_id or "all",
            "model_id": model_id or "all",
            "window_seconds": window_seconds,
            "analytics": summary,
        }

    @router.get("/recording/status")
    def recording_status() -> dict[str, Any]:
        rec = recorder or getattr(service, "recorder", None) or getattr(gateway, "recorder", None)
        if rec is not None:
            rec_status = rec.status()
        else:
            rec_status = {
                "recording_enabled": False,
                "metadata": False,
                "content": False,
                "mode": "disabled",
                "status": "disabled",
                "healthy": True,
                "dropped_count": 0,
            }
        return {
            "schema_version": 1,
            "recording": rec_status,
        }

    @router.post("/recording/mode")
    def set_recording_mode(payload: RecordingModePayload) -> dict[str, Any]:
        rec = recorder or getattr(service, "recorder", None) or getattr(gateway, "recorder", None)
        if rec is None:
            raise HTTPException(
                status_code=400,
                detail="Inference recording is disabled on this server instance. Run with -R/--record-inferences to enable persistence.",
            )
        if payload.mode not in {"metadata", "content"}:
            raise HTTPException(status_code=400, detail="Recording mode must be 'metadata' or 'content'")
        rec.set_mode(payload.mode)
        return {
            "schema_version": 1,
            "recording": rec.status(),
        }

    @router.get("/history")
    def history(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        server_instance_id: str | None = None,
        model_id: str | None = None,
        state: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        target_store = history_store or (recorder.store if recorder is not None else None)
        if target_store is None:
            return {
                "schema_version": 1,
                "availability": "disabled",
                "requests": [],
                "total_count": 0,
                "limit": limit,
                "offset": offset,
            }
        reqs, total = target_store.list_inference_requests(
            server_instance_id=server_instance_id,
            model_id=model_id,
            state=state,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
        return {
            "schema_version": 1,
            "availability": "available",
            "requests": reqs,
            "total_count": total,
            "limit": limit,
            "offset": offset,
        }

    @router.get("/history/analytics")
    def history_analytics(
        server_instance_id: str | None = None,
        model_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        window_seconds: float | None = Query(default=None, gt=0),
    ) -> dict[str, Any]:
        target_store = history_store or (recorder.store if recorder is not None else None)
        if target_store is None:
            return {
                "schema_version": 1,
                "availability": "disabled",
                "server_instance_id": server_instance_id or "all",
                "model_id": model_id or "all",
                "analytics": {},
            }
        reqs, _ = target_store.list_inference_requests(
            server_instance_id=server_instance_id,
            model_id=model_id,
            since=since,
            until=until,
            limit=1000,
        )
        req_objects = [InferenceRequest.from_dict(r) for r in reqs]
        summary = compute_model_analytics(
            req_objects,
            [],
            server_instance_id=server_instance_id,
            model_id=model_id,
            time_window_seconds=window_seconds,
        )
        return {
            "schema_version": 1,
            "availability": "available",
            "server_instance_id": server_instance_id or "all",
            "model_id": model_id or "all",
            "window_seconds": window_seconds,
            "analytics": summary,
        }

    @router.get("/history/{request_id}")
    def history_detail(request_id: str) -> dict[str, Any]:
        target_store = history_store or (recorder.store if recorder is not None else None)
        if target_store is None:
            raise HTTPException(status_code=404, detail="Inference history recording is not enabled")
        data = target_store.get_inference_request(request_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Historical inference request not found")
        return {
            "schema_version": 1,
            "request": data,
        }

    if gateway is not None:
        @router.post("/correlation/executions")
        def register_correlation_execution(payload: CorrelationExecutionPayload) -> dict[str, Any]:
            try:
                context, credential = gateway.correlation_registry.register(
                    payload.run_id,
                    payload.task_id,
                    payload.execution_id,
                    repetition_id=payload.repetition_id,
                    variant_id=payload.variant_id,
                )
            except ValueError as error:
                raise HTTPException(status_code=409, detail="Correlation execution could not be registered") from error
            return {"context": context.to_dict(), "credential": credential}

        @router.post("/correlation/executions/{execution_id}/complete")
        def complete_correlation_execution(execution_id: str, payload: CorrelationCompletionPayload) -> dict[str, Any]:
            try:
                gateway.correlation_registry.complete(execution_id, payload.trial_id)
            except (KeyError, ValueError) as error:
                raise HTTPException(status_code=404, detail="Correlation execution not found") from error
            if recorder is not None:
                if not recorder.flush(timeout=3.0):
                    raise HTTPException(status_code=503, detail="Inference correlation history is not durable yet")
                current = gateway.correlation_registry.requests(execution_id)
                recorder.store.update_execution_correlation(execution_id, current["context"])
            return gateway.correlation_registry.requests(execution_id)

        @router.get("/correlation/executions/{execution_id}/requests")
        def correlation_execution_requests(execution_id: str) -> dict[str, Any]:
            return gateway.correlation_registry.requests(execution_id)

    app = create_app(
        api_router=router,
        static_dir=static_dir,
        login_code=login_code,
        session_cookie_name=SESSION_COOKIE_NAME,
    )

    if capability_manager is not None:
        def verify_capability(token: str, request: Request) -> bool:
            path = request.url.path
            if request.method == "POST" and path.startswith("/api/inference/v1/correlation/executions"):
                scope = "benchmark:correlation:write"
                return capability_manager.verify_token(token, scope, capability_manager.instance_id)
            if request.method != "GET":
                return False
            if path == "/api/inference/v1/models":
                scope = "inference:models:read"
            elif path == "/api/inference/v1/status":
                scope = "inference:status:read"
            elif path == "/api/inference/v1/recording/status":
                scope = "recording:health:read"
            elif path == "/api/inference/v1/requests":
                scope = "requests:summary:read"
            elif path.startswith("/api/inference/v1/correlation/executions/"):
                scope = "history:verification:read"
            elif path.startswith("/api/inference/v1/history"):
                scope = "history:verification:read"
            else:
                return False
            return capability_manager.verify_token(token, scope, capability_manager.instance_id)

        app.state.capability_verifier = verify_capability
        app.state.capability_manager = capability_manager

    @app.websocket("/api/inference/v1/stream")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            async for event in events.subscribe():
                await websocket.send_json(event)
        except WebSocketDisconnect:
            return
        except RuntimeError:
            await websocket.close(code=1013, reason="observer capacity reached")

    if gateway is not None:
        app.include_router(gateway.router())
    if recorder is not None:
        app.add_event_handler("startup", recorder.start)
    app.add_event_handler("startup", service.start)
    app.add_event_handler("shutdown", service.stop)
    app.state.inference_service = service
    app.state.inference_event_hub = events
    app.state.inference_gateway = gateway
    app.state.inference_recorder = recorder
    app.state.inference_history_store = history_store
    if gateway is not None:
        app.add_event_handler("shutdown", gateway.close)
    if recorder is not None:
        app.add_event_handler("shutdown", recorder.stop)
    return app


def _public_runtime_identity(
    descriptor: dict[str, Any] | None,
    *,
    gateway_enabled: bool,
    gateway_upstream: str | None,
) -> dict[str, Any] | None:
    if not isinstance(descriptor, dict):
        return None
    fields = ("instance_id", "config_fingerprint", "gateway_upstream", "host_origin", "started_at")
    result = {key: descriptor[key] for key in fields if isinstance(descriptor.get(key), str)}
    if isinstance(descriptor.get("gateway_enabled"), bool):
        result["gateway_enabled"] = descriptor["gateway_enabled"]
    result.setdefault("gateway_enabled", gateway_enabled)
    result.setdefault("gateway_upstream", gateway_upstream)
    return result


def _coordinator_readiness(gateway_upstream: str) -> dict[str, Any]:
    """Read a bounded, secret-free readiness snapshot from the configured Coordinator."""
    observed_at = datetime.now(timezone.utc).isoformat()
    coordinator_url = None
    try:
        upstream = urlsplit(gateway_upstream)
        if (upstream.scheme not in {"http", "https"} or not upstream.hostname or upstream.port != 1235
                or upstream.username is not None or upstream.password is not None or upstream.query or upstream.fragment):
            raise ValueError("gateway upstream is not a loopback Coordinator URL")
        if upstream.hostname.lower() not in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}:
            raise ValueError("gateway upstream is not a loopback Coordinator URL")
        coordinator_url = f"{upstream.scheme}://{upstream.netloc}"
        response = httpx.get(
            f"{coordinator_url}/_coordinator/status",
            timeout=0.75,
            follow_redirects=False,
            trust_env=False,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Coordinator status response is not an object")
    except (httpx.HTTPError, ValueError, TypeError) as error:
        return {
            "status": "unavailable",
            "is_ready": False,
            "coordinator_url": coordinator_url,
            "observed_at": observed_at,
            "runtime_identity": None,
            "active_restrictions": [f"coordinator_unavailable:{type(error).__name__}"],
        }

    restrictions: list[str] = []
    service_state = payload.get("service_state")
    if service_state != "ready":
        restrictions.append("coordinator_service_not_ready_or_unknown")
    if payload.get("is_ready") is not True:
        restrictions.append("coordinator_not_ready")
    gpu = payload.get("gpu_inference")
    if not isinstance(gpu, dict):
        restrictions.append("coordinator_safety_status_unavailable")
    else:
        if gpu.get("is_restart_inhibited") is not False:
            restrictions.append("restart_inhibited_or_unknown")
        if gpu.get("inhibition"):
            restrictions.append("safety_inhibition_active")
        recovery = gpu.get("recovery")
        if not isinstance(recovery, dict) or recovery.get("required") is not False:
            restrictions.append("recovery_required_or_unknown")
    maintenance = payload.get("maintenance")
    if not isinstance(maintenance, dict):
        restrictions.append("maintenance_status_unavailable")
    else:
        maintenance_state = maintenance.get("state")
        if maintenance_state not in {"idle", "inactive", "disabled"}:
            restrictions.append("maintenance_active_or_unknown")
        if maintenance.get("restart_inhibited") is not False:
            restrictions.append("maintenance_restart_inhibited_or_unknown")
        if maintenance.get("gpu_admission_permitted") is not True:
            restrictions.append("maintenance_gpu_admission_restricted_or_unknown")
        if maintenance.get("recovery_required_reason"):
            restrictions.append("maintenance_recovery_required")
    gaming = payload.get("gaming")
    if not isinstance(gaming, dict):
        restrictions.append("gaming_status_unavailable")
    elif gaming.get("state") not in {"inactive", "disabled"}:
        restrictions.append("gaming_mode_active_or_unknown")

    raw_runtime = payload.get("runtime")
    runtime = None
    if isinstance(raw_runtime, dict):
        safe_fields = ("version", "revision", "pid", "process_create_time")
        runtime = {key: raw_runtime[key] for key in safe_fields if isinstance(raw_runtime.get(key), (str, int, float))}
        pid, created = runtime.get("pid"), runtime.get("process_create_time")
        if isinstance(pid, int) and isinstance(created, (int, float)):
            runtime["instance_id"] = f"{pid}:{created:.6f}"
        elif isinstance(raw_runtime.get("instance_id"), str):
            runtime["instance_id"] = raw_runtime["instance_id"]
    if not isinstance(runtime, dict) or not runtime.get("instance_id"):
        restrictions.append("coordinator_runtime_identity_unavailable")

    ready = payload.get("status") == "online" and payload.get("is_ready") is True and not restrictions
    return {
        "status": "ready" if ready else "blocked",
        "is_ready": ready,
        "service_state": service_state if isinstance(service_state, str) else "unavailable",
        "coordinator_url": coordinator_url,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_identity": runtime,
        "active_restrictions": restrictions,
    }
