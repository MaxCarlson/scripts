"""Executable example of an application-owned route hosted by web-ui-tools."""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, FastAPI

from web_ui_tools.app import create_app, run_server

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_hello_app(*, login_code: str | None = None) -> FastAPI:
    """Create a small app that uses the shared service and does not import runmux."""

    router = APIRouter(prefix="/api")

    @router.get("/hello")
    async def hello() -> dict[str, str]:
        return {"message": "Hello from an application that does not use runmux."}

    return create_app(
        api_router=router,
        static_dir=STATIC_DIR,
        login_code=login_code or secrets.token_urlsafe(24),
    )


def main() -> None:
    code = secrets.token_urlsafe(24)
    print(f"Open http://127.0.0.1:8787 and enter this startup login code: {code}")
    run_server(create_hello_app(login_code=code))


if __name__ == "__main__":
    main()
