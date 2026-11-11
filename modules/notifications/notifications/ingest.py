"""Authenticated local loopback HTTP ingestion server using FastAPI."""

from __future__ import annotations

import hmac
import logging
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from notifications.exceptions import (
    IncidentNotFoundError,
    InvalidTransitionError,
    PayloadConflictError,
    StorageError,
    ValidationError,
)
from notifications.lifecycle import IncidentLifecycleEngine
from notifications.models import EventEnvelopeV1
from notifications.storage import StorageEngine

logger = logging.getLogger(__name__)


class AckRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=256)
    actor: Optional[str] = Field(default="api_client", max_length=64)


def create_ingest_app(
    storage: StorageEngine,
    lifecycle: Optional[IncidentLifecycleEngine] = None,
    auth_token: Optional[str] = None,
    default_providers: Optional[list[str]] = None,
    engine: Optional[IncidentLifecycleEngine] = None,
) -> FastAPI:
    """Create an authenticated FastAPI ASGI application for local notification ingestion."""
    if not auth_token:
        raise ValueError("auth_token must be provided for ingestion security")

    engine = engine or lifecycle or IncidentLifecycleEngine(storage)
    providers = default_providers or ["fake_provider"]

    app = FastAPI(title="Notifications Ingestion", docs_url=None, redoc_url=None, openapi_url=None)

    def verify_auth(request: Request) -> None:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or malformed Authorization bearer token",
            )
        token = auth_header[7:].strip()
        if not hmac.compare_digest(token.encode("utf-8"), auth_token.encode("utf-8")):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authorization token",
            )

    @app.get("/api/v1/health")
    async def health() -> dict[str, Any]:
        """Minimal public liveness probe."""
        try:
            ver = storage.get_schema_version()
            return {
                "status": "healthy",
                "service": "notifications",
                "schema_version": ver,
            }
        except Exception as exc:
            logger.error("Health check failed: %s", exc)
            return {"status": "degraded", "error": str(exc)}

    @app.post("/api/v1/publish", status_code=status.HTTP_202_ACCEPTED)
    async def publish_event(
        request: Request,
        _auth: None = Depends(verify_auth),
    ) -> dict[str, Any]:
        """Ingest and persist a validated notification event."""
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON: {exc}")

        try:
            event = EventEnvelopeV1.from_dict(body)
        except ValidationError as exc:
            return Response(
                content=f'{{"ok": false, "error": "{str(exc)}"}}',
                status_code=status.HTTP_400_BAD_REQUEST,
                media_type="application/json",
            )

        try:
            result = engine.process_event(event, providers=providers)
            return {"ok": True, "result": result.to_dict()}
        except PayloadConflictError as exc:
            return Response(
                content=f'{{"ok": false, "error": "{str(exc)}"}}',
                status_code=status.HTTP_409_CONFLICT,
                media_type="application/json",
            )
        except StorageError as exc:
            logger.error("Storage error during ingestion: %s", exc)
            return Response(
                content=f'{{"ok": false, "error": "{str(exc)}"}}',
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                media_type="application/json",
            )

    @app.get("/api/v1/incidents")
    async def list_incidents(
        status_filter: Optional[str] = None,
        limit: int = 50,
        _auth: None = Depends(verify_auth),
    ) -> dict[str, Any]:
        """List current incidents."""
        incidents = storage.list_incidents(status=status_filter, limit=limit)
        return {"ok": True, "incidents": [inc.to_dict() for inc in incidents]}

    @app.post("/api/v1/incidents/{incident_id}/acknowledge")
    async def acknowledge_incident(
        incident_id: str,
        body: AckRequest,
        _auth: None = Depends(verify_auth),
    ) -> dict[str, Any]:
        """Acknowledge an active incident without resolving it."""
        actor_name = f"api:{body.actor}" if body.actor else "api_client"
        try:
            updated = engine.acknowledge_incident(
                incident_id=incident_id,
                actor=actor_name,
                reason=body.reason,
            )
            return {
                "ok": True,
                "status": "acknowledged",
                "incident_id": incident_id,
                "incident": updated.to_dict(),
            }
        except IncidentNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
        except InvalidTransitionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return app
