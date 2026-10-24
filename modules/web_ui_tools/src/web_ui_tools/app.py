"""Small authenticated ASGI service for locally hosted application views."""

from __future__ import annotations

import hmac
import ipaddress
import secrets
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
SESSION_COOKIE = "web_ui_session"
SESSION_MAX_AGE = 8 * 60 * 60
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
}


class LoginRequest(BaseModel):
    """Login code entered by the local user."""

    code: str = Field(min_length=1, max_length=256)


def create_app(
    *,
    api_router: APIRouter,
    static_dir: str | Path,
    login_code: str,
    allowed_hosts: Sequence[str] = LOOPBACK_HOSTS,
) -> FastAPI:
    """Create an application with explicit routes, static assets, and local session authentication.

    The supplied router is mounted unchanged. API routes should live below ``/api`` so the shared
    service can enforce same-origin requests, authentication, and no-store response headers.
    """

    if not login_code:
        raise ValueError("login_code must not be empty")
    root = Path(static_dir).expanduser().resolve()
    index_file = root / "index.html"
    assets_dir = root / "assets"
    if not index_file.is_file():
        raise ValueError(f"Static UI index does not exist: {index_file}")
    if not assets_dir.is_dir():
        raise ValueError(f"Static UI asset directory does not exist: {assets_dir}")
    if any(route.path != "/api" and not route.path.startswith("/api/") for route in api_router.routes):
        raise ValueError("Application routes must be mounted below /api for authentication to protect them.")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.login_code = login_code
    app.state.sessions = {}
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    app.include_router(api_router)

    @app.middleware("http")
    async def secure_local_requests(request: Request, call_next: Any) -> Response:
        if not _trusted_host(request, allowed_hosts):
            return Response(status_code=400, headers=SECURITY_HEADERS)
        path = request.url.path
        protected = path == "/api" or path.startswith("/api/") or path == "/auth/logout"
        auth_route = path.startswith("/auth/")
        if (protected or auth_route) and not _same_origin(request):
            return Response(status_code=403, headers={**SECURITY_HEADERS, "Cache-Control": "no-store"})
        if protected:
            session_id = request.cookies.get(SESSION_COOKIE)
            expires_at = app.state.sessions.get(session_id)
            if expires_at is None or expires_at <= time.time():
                if session_id:
                    app.state.sessions.pop(session_id, None)
                return Response(status_code=401, headers={**SECURITY_HEADERS, "Cache-Control": "no-store"})

        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if protected or auth_route:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/auth/login", status_code=204)
    async def login(payload: LoginRequest, response: Response) -> None:
        if not hmac.compare_digest(payload.code.encode("utf-8"), login_code.encode("utf-8")):
            raise HTTPException(status_code=401, detail="Invalid login code")
        session_id = secrets.token_urlsafe(32)
        app.state.sessions[session_id] = time.time() + SESSION_MAX_AGE
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=False,  # Local HTTP loopback; SameSite and strict origin checks provide browser CSRF protection.
            samesite="strict",
            path="/",
        )

    @app.post("/auth/logout", status_code=204)
    async def logout(request: Request, response: Response) -> None:
        session_id = request.cookies.get(SESSION_COOKIE)
        if session_id:
            app.state.sessions.pop(session_id, None)
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(index_file, headers=SECURITY_HEADERS)

    app.mount("/assets", StaticFiles(directory=assets_dir, check_dir=True), name="assets")
    return app


def create_server(app: FastAPI, *, host: str = "127.0.0.1", port: int = 8787) -> uvicorn.Server:
    """Create a Uvicorn server after requiring an IP loopback bind address."""

    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ValueError("Web service host must be a loopback IP address (127.0.0.1 or ::1).") from error
    if not address.is_loopback:
        raise ValueError("Web service host must be a loopback IP address (127.0.0.1 or ::1).")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    config = uvicorn.Config(app, host=host, port=port, access_log=False, log_level="info", ws="none")
    return uvicorn.Server(config)


def run_server(app: FastAPI, *, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Run a local server until Ctrl+C or a caller-requested shutdown."""

    create_server(app, host=host, port=port).run()


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if not host:
        return False
    if not origin:
        # Chromium omits Origin on same-origin GET fetches. Fetch Metadata is browser-controlled,
        # so accept only safe read methods carrying the explicit same-origin marker.
        return request.method in {"GET", "HEAD"} and request.headers.get("sec-fetch-site") == "same-origin"
    return hmac.compare_digest(origin.rstrip("/").lower(), f"{request.url.scheme}://{host}".lower())


def _trusted_host(request: Request, allowed_hosts: Sequence[str]) -> bool:
    host_header = request.headers.get("host")
    if not host_header:
        return False
    try:
        host_name = urlsplit(f"//{host_header}").hostname
    except ValueError:
        return False
    if not host_name:
        return False
    trusted = {host.strip("[]").lower() for host in allowed_hosts}
    return host_name.lower() in trusted
