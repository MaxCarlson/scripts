"""Authentication and session management API routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from remote_control.api.dependencies import (
    get_client_ip,
    get_cookie_name,
    get_current_session,
    verify_csrf,
)
from remote_control.auth.service import (
    AuthenticationError,
    AuthService,
    RateLimitError,
)
from remote_control.models import SessionModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)
    totp_code: str = Field(..., min_length=6, max_length=8)
    device_id: Optional[str] = Field(None, max_length=64)
    device_name: Optional[str] = Field("Mobile Browser", max_length=64)


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
) -> Dict[str, Any]:
    """Authenticate operator credentials and issue HttpOnly session cookie."""
    auth_service: AuthService = request.app.state.auth_service
    if not auth_service.is_bootstrapped():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ok": False, "error": "not_bootstrapped", "message": "Remote control is not bootstrapped. Run 'scripts-remote-control bootstrap' on the host console."},
        )

    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent", "")[:256]

    try:
        session, raw_token = auth_service.authenticate_login(
            username=payload.username,
            password=payload.password,
            totp_code=payload.totp_code,
            device_id=payload.device_id,
            device_name=payload.device_name or "Mobile Browser",
            ip_address=ip,
            user_agent=ua,
        )

        # Set secure HttpOnly session cookie
        cookie_name = get_cookie_name(request)
        is_secure = getattr(request.app.state.config, "cookie_secure", False)
        samesite = getattr(request.app.state.config, "cookie_samesite", "strict")
        max_age = getattr(request.app.state.config, "session_max_age_seconds", 86400 * 7)

        response.set_cookie(
            key=cookie_name,
            value=raw_token,
            max_age=max_age,
            httponly=True,
            secure=is_secure,
            samesite=samesite,
            path="/",
        )

        return {
            "ok": True,
            "session": session.to_dict(),
            "csrf_token": session.csrf_token,
            "operator": {"username": payload.username.strip()},
        }
    except RateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"ok": False, "error": "rate_limit_exceeded", "message": str(exc)},
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"ok": False, "error": "invalid_credentials", "message": str(exc)},
        )


@router.post("/logout", dependencies=[Depends(verify_csrf)])
async def logout(
    request: Request,
    response: Response,
    session: SessionModel = Depends(get_current_session),
) -> Dict[str, Any]:
    """Revoke session and clear session cookie."""
    auth_service: AuthService = request.app.state.auth_service
    if not auth_service.is_bootstrapped():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ok": False, "error": "not_bootstrapped", "message": "Remote control is not bootstrapped. Run 'scripts-remote-control bootstrap' on the host console."},
        )

    ip = get_client_ip(request)

    auth_service.revoke_session(session.session_id, actor_id=session.operator_id, ip_address=ip)

    cookie_name = get_cookie_name(request)
    response.delete_cookie(key=cookie_name, path="/")
    response.delete_cookie(key="rc_session", path="/")

    return {"ok": True, "message": "Successfully logged out."}


@router.get("/session")
async def get_session_info(
    session: SessionModel = Depends(get_current_session),
) -> Dict[str, Any]:
    """Return active session metadata and CSRF token for frontend form requests."""
    return {
        "ok": True,
        "session": session.to_dict(),
        "csrf_token": session.csrf_token,
    }


@router.get("/devices")
async def list_devices(
    request: Request,
    session: SessionModel = Depends(get_current_session),
) -> Dict[str, Any]:
    """List operator's enrolled personal devices."""
    auth_service: AuthService = request.app.state.auth_service
    devices = auth_service.storage.list_devices()
    return {
        "ok": True,
        "devices": [d.to_dict() for d in devices],
    }


@router.post("/devices/{device_id}/revoke", dependencies=[Depends(verify_csrf)])
async def revoke_device(
    request: Request,
    device_id: str,
    session: SessionModel = Depends(get_current_session),
) -> Dict[str, Any]:
    """Permanently revoke a personal device and all associated active sessions."""
    auth_service: AuthService = request.app.state.auth_service
    if not auth_service.is_bootstrapped():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ok": False, "error": "not_bootstrapped", "message": "Remote control is not bootstrapped. Run 'scripts-remote-control bootstrap' on the host console."},
        )

    ip = get_client_ip(request)

    success = auth_service.revoke_device(device_id, actor_id=session.operator_id, ip_address=ip)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"ok": False, "error": "device_not_found", "message": f"Device '{device_id}' not found."},
        )

    return {"ok": True, "message": f"Device '{device_id}' and all active sessions revoked."}


@router.get("/audit")
async def list_audit_events(
    request: Request,
    limit: int = 50,
    session: SessionModel = Depends(get_current_session),
) -> Dict[str, Any]:
    """List recent security and authentication audit events."""
    auth_service: AuthService = request.app.state.auth_service
    events = auth_service.storage.list_audit_events(limit=min(max(1, limit), 100))
    return {
        "ok": True,
        "audit_events": [e.to_dict() for e in events],
    }
