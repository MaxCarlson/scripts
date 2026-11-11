"""Read-only dashboard API endpoints for incidents, notifications, and provider health."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from remote_control.adapters.heartbeat_adapter import ReadOnlyMonitoringAdapter
from remote_control.adapters.notifications_adapter import ReadOnlyNotificationsAdapter
from remote_control.api.dependencies import get_current_session
from remote_control.models import SessionModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"])


def get_notifications_adapter(request: Request) -> ReadOnlyNotificationsAdapter:
    return request.app.state.notifications_adapter


def get_monitoring_adapter(request: Request) -> ReadOnlyMonitoringAdapter:
    return request.app.state.monitoring_adapter


@router.get("/summary")
async def get_dashboard_summary(
    session: SessionModel = Depends(get_current_session),
    notif_adapter: ReadOnlyNotificationsAdapter = Depends(get_notifications_adapter),
    mon_adapter: ReadOnlyMonitoringAdapter = Depends(get_monitoring_adapter),
) -> Dict[str, Any]:
    """Aggregate top-level dashboard summary across incidents, heartbeat, and providers."""
    notif_summary = notif_adapter.get_summary()
    hb_status = mon_adapter.get_heartbeat_status()
    providers = mon_adapter.get_providers_status()

    # Coordinator placeholder contract (Phase 05 forward compatibility)
    coordinator_status = {
        "status": "unconnected",
        "available": False,
        "message": "Resource Coordinator adapter available in Phase 05.",
        "inhibition_active": False,
        "miner_state": "unknown",
    }

    return {
        "ok": True,
        "notifications": notif_summary,
        "heartbeat": {
            "configured": hb_status.get("configured", False),
            "task_installed": hb_status.get("task_installed", False),
            "task_state": hb_status.get("task_state", "not_found"),
            "execution_mode": hb_status.get("execution_mode", "unknown"),
            "logged_off_capable": hb_status.get("logged_off_capable", False),
            "last_run_time": hb_status.get("last_run_time"),
            "next_run_time": hb_status.get("next_run_time"),
            "last_result": hb_status.get("last_result"),
            "check_name": hb_status.get("check_name"),
        },
        "providers": providers,
        "coordinator": coordinator_status,
    }


@router.get("/incidents")
async def list_incidents(
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: SessionModel = Depends(get_current_session),
    adapter: ReadOnlyNotificationsAdapter = Depends(get_notifications_adapter),
) -> Dict[str, Any]:
    """List paginated incidents with optional status, severity, and source filters."""
    res = adapter.list_incidents(
        status=status_filter,
        severity=severity,
        source=source,
        limit=limit,
        offset=offset,
    )
    return {
        "ok": True,
        **res,
    }


@router.get("/incidents/{incident_id}")
async def get_incident_detail(
    incident_id: str,
    session: SessionModel = Depends(get_current_session),
    adapter: ReadOnlyNotificationsAdapter = Depends(get_notifications_adapter),
) -> Dict[str, Any]:
    """Fetch complete incident detail, occurrence history, and delivery records."""
    data = adapter.get_incident(incident_id)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "error": "incident_not_found", "message": f"Incident '{incident_id}' not found."},
        )
    return {
        "ok": True,
        "incident": data,
    }


@router.get("/notifications")
async def list_recent_notifications(
    limit: int = Query(50, ge=1, le=100),
    session: SessionModel = Depends(get_current_session),
    adapter: ReadOnlyNotificationsAdapter = Depends(get_notifications_adapter),
) -> Dict[str, Any]:
    """List recent rendered notifications and outbox tasks."""
    items = adapter.list_recent_notifications(limit=limit)
    return {
        "ok": True,
        "notifications": items,
        "count": len(items),
    }


@router.get("/providers")
async def list_providers_status(
    session: SessionModel = Depends(get_current_session),
    adapter: ReadOnlyMonitoringAdapter = Depends(get_monitoring_adapter),
) -> Dict[str, Any]:
    """Inspect delivery providers operational status."""
    providers = adapter.get_providers_status()
    return {
        "ok": True,
        "providers": providers,
    }


@router.get("/heartbeat")
async def get_heartbeat_status(
    session: SessionModel = Depends(get_current_session),
    adapter: ReadOnlyMonitoringAdapter = Depends(get_monitoring_adapter),
) -> Dict[str, Any]:
    """Inspect independent host outage monitoring status."""
    status_data = adapter.get_heartbeat_status()
    return {
        "ok": True,
        "heartbeat": status_data,
    }


@router.get("/coordinator")
async def get_coordinator_status(
    session: SessionModel = Depends(get_current_session),
) -> Dict[str, Any]:
    """Read-only placeholder contract for future Phase 05 Resource Coordinator integration."""
    return {
        "ok": True,
        "status": "unconnected",
        "available": False,
        "message": "Resource Coordinator adapter available in Phase 05.",
        "inhibition_active": False,
        "miner_state": "unknown",
    }
