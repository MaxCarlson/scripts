"""Authenticated versioned HTTP API for the standalone inference overview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from .inference_service import InferenceMonitoringService

STATIC_DIR = Path(__file__).resolve().parent / "web_static"
SESSION_COOKIE_NAME = "llm_monitor_session"


def create_inference_web_app(
    service: InferenceMonitoringService,
    *,
    login_code: str,
    static_dir: str | Path = STATIC_DIR,
) -> FastAPI:
    """Create the standalone UI app without opening a telemetry database."""
    try:
        from web_ui_tools import create_app
    except ImportError as error:
        raise RuntimeError("Install llm-monitor[web] to use the browser dashboard.") from error

    router = APIRouter(prefix="/api/inference/v1")

    @router.get("/status")
    def status() -> dict[str, Any]:
        snapshot = service.snapshot()
        return {
            "schema_version": 1,
            "availability": snapshot["server"]["connection_state"],
            "revision": snapshot["revision"],
            "refreshed_at": snapshot["refreshed_at"],
            "capabilities": snapshot["capabilities"],
            "recording": snapshot["recording"],
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
            "availability": "available",
            "capture_state": snapshot["capabilities"]["request_lifecycle"]["state"],
            "requests": snapshot["requests"],
        }

    @router.get("/requests/{request_id}")
    def request_detail(request_id: str) -> dict[str, Any]:
        snapshot = service.snapshot()
        request = next((item for item in snapshot["requests"] if item["request_id"] == request_id), None)
        if request is None:
            raise HTTPException(status_code=404, detail="Inference request not found")
        return {"schema_version": 1, "request": request}

    app = create_app(
        api_router=router,
        static_dir=static_dir,
        login_code=login_code,
        session_cookie_name=SESSION_COOKIE_NAME,
    )
    app.add_event_handler("startup", service.start)
    app.add_event_handler("shutdown", service.stop)
    app.state.inference_service = service
    return app
