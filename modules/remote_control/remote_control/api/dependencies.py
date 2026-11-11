"""FastAPI dependencies for authentication, CSRF enforcement, and request validation."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from remote_control.auth.crypto import constant_time_compare
from remote_control.auth.service import AuthService
from remote_control.models import SessionModel

logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    """Extract client IP address, handling proxy headers only from trusted local boundaries."""
    client = request.client
    return client.host if client else "127.0.0.1"


def get_cookie_name(request: Request) -> str:
    """Determine cookie name based on scheme or configuration (__Host- prefix on HTTPS)."""
    is_https = request.url.scheme == "https"
    cookie_secure = getattr(request.app.state.config, "cookie_secure", False)
    return "__Host-rc_session" if (is_https or cookie_secure) else "rc_session"


async def get_current_session(request: Request) -> SessionModel:
    """
    Authenticate request via session cookie or Authorization Bearer header.
    Fails closed if the service is unbootstrapped, unauthenticated, expired, or revoked.
    """
    auth_service: AuthService = request.app.state.auth_service

    if not auth_service.is_bootstrapped():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ok": False, "error": "operator_not_bootstrapped", "message": "Remote control is not bootstrapped. Run 'scripts-remote-control bootstrap' on the host."},
        )

    # 1. Check cookies
    cookie_name = get_cookie_name(request)
    raw_token = request.cookies.get(cookie_name)

    # Also check fallback un-prefixed cookie if HTTPS cookie is not found
    if not raw_token and cookie_name != "rc_session":
        raw_token = request.cookies.get("rc_session")

    # 2. Check Authorization header
    if not raw_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw_token = auth_header[7:].strip()

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"ok": False, "error": "unauthenticated", "message": "Authentication required. Please log in."},
        )

    ip = get_client_ip(request)
    session = auth_service.validate_session(raw_token, ip_address=ip)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"ok": False, "error": "session_expired_or_revoked", "message": "Session has expired or was revoked. Please log in again."},
        )

    return session


async def verify_csrf(
    request: Request,
    session: SessionModel = Depends(get_current_session),
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token"),
) -> None:
    """Enforce CSRF token verification for all state-changing HTTP operations."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        if not x_csrf_token or not constant_time_compare(x_csrf_token, session.csrf_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"ok": False, "error": "csrf_validation_failed", "message": "Invalid or missing CSRF token."},
            )
