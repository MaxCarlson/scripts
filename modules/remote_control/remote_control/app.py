"""FastAPI application factory, security middleware, and static asset serving for Remote Control."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from remote_control.adapters.heartbeat_adapter import ReadOnlyMonitoringAdapter
from remote_control.adapters.notifications_adapter import ReadOnlyNotificationsAdapter
from remote_control.api.auth_routes import router as auth_router
from remote_control.api.dashboard_routes import router as dashboard_router
from remote_control.api.dependencies import get_effective_port, get_effective_scheme
from remote_control.auth.service import AuthService
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: Optional[RemoteControlConfig] = None) -> FastAPI:
    """Create and configure the hardened, read-only remote control FastAPI application."""
    cfg = config or RemoteControlConfig.from_env()

    app = FastAPI(
        title="Remote Control Dashboard",
        description="Authenticated read-only mobile dashboard and PWA for notifications and incident monitoring.",
        version="0.1.0",
        docs_url=None,  # Disabled in production/public interfaces for security
        redoc_url=None,
        openapi_url=None,
    )

    # Initialize services & state
    auth_storage = AuthStorage(cfg.auth_db_path)
    auth_service = AuthService(auth_storage, cfg)
    notif_adapter = ReadOnlyNotificationsAdapter(cfg.notifications_db_path)
    mon_adapter = ReadOnlyMonitoringAdapter(cfg.healthchecks_config_path)

    app.state.config = cfg
    app.state.auth_storage = auth_storage
    app.state.auth_service = auth_service
    app.state.notifications_adapter = notif_adapter
    app.state.monitoring_adapter = mon_adapter

    # ── Security Middleware ──────────────────────────────────────────────────────

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        # 1. Host header validation
        host_header = request.headers.get("host", "").split(":")[0].strip().lower()
        if host_header and host_header not in [h.lower() for h in cfg.allowed_hosts]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "error": "invalid_host_header", "message": f"Host '{host_header}' is not in allowed hosts."},
            )

        # 2. Strict Exact-Origin validation for state-changing requests
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            # Reject untrusted cross-site browser fetches
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"ok": False, "error": "forbidden_origin", "message": "Cross-site request rejected via Sec-Fetch-Site."},
                )

            eff_scheme = get_effective_scheme(request)
            eff_host = (request.url.hostname or "").lower()
            eff_port = get_effective_port(request)

            origin = request.headers.get("origin")
            if origin:
                if origin.strip().lower() == "null":
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"ok": False, "error": "forbidden_origin", "message": "Origin 'null' is not allowed."},
                    )

                parsed_origin = urlparse(origin)
                origin_scheme = (parsed_origin.scheme or "").lower()
                origin_host = (parsed_origin.hostname or "").lower()
                origin_port = parsed_origin.port or (443 if origin_scheme == "https" else 80)

                # Check explicit allowed_origins whitelist first
                allowed = False
                for ao in cfg.allowed_origins:
                    ao_clean = ao.strip().lower()
                    if ao_clean in (origin.strip().lower(), f"{origin_scheme}://{origin_host}:{origin_port}", f"{origin_scheme}://{origin_host}"):
                        allowed = True
                        break

                if not allowed:
                    # Enforce exact match: scheme + hostname + effective port
                    scheme_match = (origin_scheme == eff_scheme)
                    host_match = (origin_host in [h.lower() for h in cfg.allowed_hosts]) and (
                        origin_host == eff_host or eff_host in ("127.0.0.1", "localhost", "testserver")
                    )
                    port_match = (origin_port == eff_port)
                    allowed = scheme_match and host_match and port_match

                if not allowed:
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"ok": False, "error": "forbidden_origin", "message": f"Cross-origin request rejected from '{origin}'."},
                    )
            else:
                # Origin header is missing; check Referer
                referer = request.headers.get("referer")
                if referer:
                    parsed_ref = urlparse(referer)
                    ref_scheme = (parsed_ref.scheme or "").lower()
                    ref_host = (parsed_ref.hostname or "").lower()
                    ref_port = parsed_ref.port or (443 if ref_scheme == "https" else 80)

                    allowed = False
                    for ao in cfg.allowed_origins:
                        ao_clean = ao.strip().lower()
                        if ao_clean in (referer.strip().lower(), f"{ref_scheme}://{ref_host}:{ref_port}", f"{ref_scheme}://{ref_host}"):
                            allowed = True
                            break

                    if not allowed:
                        scheme_match = (ref_scheme == eff_scheme)
                        host_match = (ref_host in [h.lower() for h in cfg.allowed_hosts]) and (
                            ref_host == eff_host or eff_host in ("127.0.0.1", "localhost", "testserver")
                        )
                        port_match = (ref_port == eff_port)
                        allowed = scheme_match and host_match and port_match

                    if not allowed:
                        return JSONResponse(
                            status_code=status.HTTP_403_FORBIDDEN,
                            content={"ok": False, "error": "forbidden_origin", "message": f"Cross-origin request rejected from referer '{referer}'."},
                        )
                else:
                    fetch_site = request.headers.get("sec-fetch-site")
                    if fetch_site and fetch_site not in ("same-origin", "same-site", "none"):
                        return JSONResponse(
                            status_code=status.HTTP_403_FORBIDDEN,
                            content={"ok": False, "error": "forbidden_origin", "message": "Missing Origin header on cross-site request."},
                        )

        # Process request
        response: Response = await call_next(request)

        # 3. Security Headers
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "manifest-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )

        # 4. Cache-Control: strictly prevent browser or proxy caching of sensitive API responses
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"

        return response

    # ── Exception Handlers ───────────────────────────────────────────────────────

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            content = detail
        else:
            content = {"ok": False, "error": "http_error", "message": str(detail)}
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled server exception on %s: %s", request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"ok": False, "error": "internal_server_error", "message": "An unexpected error occurred."},
        )

    # ── Route Registration ───────────────────────────────────────────────────────

    app.include_router(auth_router)
    app.include_router(dashboard_router)

    # ── Static Asset Serving & PWA Shell ─────────────────────────────────────────

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_index():
            return FileResponse(STATIC_DIR / "index.html")

        @app.get("/manifest.json", include_in_schema=False)
        async def serve_manifest():
            return FileResponse(STATIC_DIR / "manifest.json", media_type="application/manifest+json")

        @app.get("/sw.js", include_in_schema=False)
        async def serve_sw():
            response = FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")
            # Service worker must not be cached by browser
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response

    return app
