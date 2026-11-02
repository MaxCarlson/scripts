"""Authenticated versioned HTTP API for the standalone inference overview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .gateway import OpenAIInferenceGateway, RequestEventHub
from .inference_analysis import compute_model_analytics
from .inference_models import InferenceRequest
from .inference_service import InferenceMonitoringService

STATIC_DIR = Path(__file__).resolve().parent / "web_static"
SESSION_COOKIE_NAME = "llm_monitor_session"


class RecordingModePayload(BaseModel):
    mode: str


def create_inference_web_app(
    service: InferenceMonitoringService,
    *,
    login_code: str,
    static_dir: str | Path = STATIC_DIR,
    gateway: OpenAIInferenceGateway | None = None,
    event_hub: RequestEventHub | None = None,
    recorder: Any | None = None,
    history_store: Any | None = None,
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
        return {
            "schema_version": 1,
            "availability": snapshot["server"]["connection_state"],
            "revision": snapshot["revision"],
            "refreshed_at": snapshot["refreshed_at"],
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

    app = create_app(
        api_router=router,
        static_dir=static_dir,
        login_code=login_code,
        session_cookie_name=SESSION_COOKIE_NAME,
    )

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
