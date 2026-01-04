"""API endpoints for logging Web UI interaction events."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class UiEvent(BaseModel):
    event: str
    details: Dict[str, Any] = {}
    view: Optional[str] = None
    timestamp: Optional[str] = None


@router.post("/ui-event")
async def record_ui_event(payload: UiEvent, request: Request):
    """Log UI interactions so server logs reflect every user action."""
    client_host = request.client.host if request.client else "unknown"
    logger.info(
        "UI_EVENT client=%s event=%s view=%s details=%s",
        client_host,
        payload.event,
        payload.view,
        payload.details,
    )
    return {"status": "ok"}
