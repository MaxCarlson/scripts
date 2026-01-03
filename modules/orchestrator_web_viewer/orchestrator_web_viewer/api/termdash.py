#!/usr/bin/env python3
"""
API endpoints for TermDash attachment mode.
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
import json

logger = logging.getLogger(__name__)

router = APIRouter()

# Global registry of attached termdash instances
_attached_dashboards: Dict[str, Any] = {}


def register_dashboard(dashboard_id: str, dashboard: Any) -> None:
    """Register a termdash dashboard instance for web viewing."""
    _attached_dashboards[dashboard_id] = dashboard
    logger.info(f"Registered termdash dashboard: {dashboard_id}")


def unregister_dashboard(dashboard_id: str) -> None:
    """Unregister a termdash dashboard."""
    if dashboard_id in _attached_dashboards:
        del _attached_dashboards[dashboard_id]
        logger.info(f"Unregistered termdash dashboard: {dashboard_id}")


@router.get("/dashboards")
async def list_dashboards():
    """List all available termdash dashboards."""
    return {
        "dashboards": [
            {"id": dashboard_id, "type": "termdash"}
            for dashboard_id in _attached_dashboards.keys()
        ]
    }


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard_state(dashboard_id: str):
    """Get current state of a termdash dashboard."""
    dashboard = _attached_dashboards.get(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail=f"Dashboard {dashboard_id} not found")
    
    try:
        from termdash.export import export_dashboard_state
        state = export_dashboard_state(dashboard)
        return state
    except Exception as e:
        logger.error(f"Error exporting dashboard state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/dashboards/{dashboard_id}/stream")
async def stream_dashboard(websocket: WebSocket, dashboard_id: str):
    """WebSocket endpoint for streaming termdash dashboard updates."""
    await websocket.accept()
    
    dashboard = _attached_dashboards.get(dashboard_id)
    if not dashboard:
        await websocket.close(code=1008, reason=f"Dashboard {dashboard_id} not found")
        return
    
    logger.info(f"Client connected to dashboard stream: {dashboard_id}")
    
    try:
        from termdash.export import export_dashboard_state
        import asyncio
        
        # Send initial state
        state = export_dashboard_state(dashboard)
        await websocket.send_json({"type": "state", "data": state})
        
        # Stream updates
        while True:
            # Poll for updates every 100ms
            await asyncio.sleep(0.1)
            
            try:
                state = export_dashboard_state(dashboard)
                await websocket.send_json({"type": "update", "data": state})
            except Exception as e:
                logger.error(f"Error sending dashboard update: {e}")
                break
                
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from dashboard stream: {dashboard_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close(code=1011, reason=str(e))
