"""Proxy endpoints for project tracking metadata."""
from __future__ import annotations

from fastapi import APIRouter

from orchestrator_web_viewer.integrations.orchestrator_client import (
    orchestrator_get,
    orchestrator_post,
)

router = APIRouter()


@router.get("/")
async def list_project_tracking():
    """Return tracking status for all projects."""
    return await orchestrator_get("/projects/tracking")


@router.get("/{project_id}")
async def project_tracking_detail(project_id: str):
    """Detailed tracking info."""
    return await orchestrator_get(f"/projects/{project_id}/tracking")


@router.post("/{project_id}")
async def update_project_tracking(project_id: str, payload: dict):
    """Update tracking metadata."""
    return await orchestrator_post(f"/projects/{project_id}/tracking", payload)


@router.post("/{project_id}/index")
async def trigger_embedding(project_id: str, payload: dict):
    """Trigger a manual embedding/indexing run."""
    return await orchestrator_post(f"/projects/{project_id}/tracking/index", payload)
