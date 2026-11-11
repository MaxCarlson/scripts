"""API package."""

from remote_control.api.auth_routes import router as auth_router
from remote_control.api.dashboard_routes import router as dashboard_router

__all__ = ["auth_router", "dashboard_router"]
