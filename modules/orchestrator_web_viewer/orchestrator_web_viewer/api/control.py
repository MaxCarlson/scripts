"""Control endpoints for orchestrator settings (models, manual tasks)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from orchestrator_web_viewer.integrations.orchestrator_client import (
    orchestrator_get,
    orchestrator_post,
)

router = APIRouter()


class ModelSelectPayload(BaseModel):
    model_id: str


class ManualTaskPayload(BaseModel):
    project_id: str
    title: str
    description: str
    cli_preference: str = "claude"
    priority: int = Field(default=3, ge=1, le=5)
    working_dir: Optional[str] = None


@router.get("/models")
async def list_models():
    """Return available models from the orchestrator."""
    return await orchestrator_get("/config/models")


@router.post("/models/select")
async def select_model(payload: ModelSelectPayload):
    """Update the orchestrator's active model."""
    return await orchestrator_post("/config/models/select", payload.dict())


@router.post("/tasks")
async def queue_manual_task(payload: ManualTaskPayload):
    """Queue a manual task via the orchestrator."""
    return await orchestrator_post("/tasks/queue", payload.dict())
