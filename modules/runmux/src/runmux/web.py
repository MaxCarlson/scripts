"""Read-only Runmux browser API, loaded only by the optional ``runmux web`` command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query
from web_ui_tools import LOOPBACK_HOSTS, create_app

from runmux.constants import TERMINAL_STATUSES
from runmux.platform_paths import get_state_dir
from runmux.store import RunNotFoundError
from runmux.web_adapter import (
    DEFAULT_LOG_CHUNK_BYTES,
    MAX_LOG_CHUNK_BYTES,
    ReadOnlyRunmux,
    RegistryReadError,
    read_output_chunk,
    serialize_run,
)

STATIC_DIR = Path(__file__).resolve().parent / "web_static"


def create_runmux_web_app(
    state_dir: Path | None = None,
    *,
    login_code: str,
    allowed_hosts: tuple[str, ...] = LOOPBACK_HOSTS,
) -> FastAPI:
    """Create an authenticated, read-only browser view of an existing Runmux registry."""

    backend = ReadOnlyRunmux(state_dir or get_state_dir())
    api = APIRouter(prefix="/api")

    @api.get("/runs")
    def list_runs() -> list[dict[str, Any]]:
        try:
            return [serialize_run(record) for record in backend.list_runs()]
        except RegistryReadError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @api.get("/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        try:
            record = backend.get_run(run_id)
            record, connection = backend.refresh_display_status(record)
            return serialize_run(record, connection=connection)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except RegistryReadError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @api.get("/runs/{run_id}/output")
    def run_output(
        run_id: str,
        cursor: str | None = Query(default=None, max_length=512),
        limit: int = Query(default=DEFAULT_LOG_CHUNK_BYTES, ge=1, le=MAX_LOG_CHUNK_BYTES),
    ) -> dict[str, Any]:
        try:
            record = backend.get_run(run_id)
            record, _connection = backend.refresh_display_status(record)
            finished = record.status in TERMINAL_STATUSES
            chunk = read_output_chunk(
                Path(record.log_path),
                state_dir=backend.state_dir,
                run_id=record.id,
                cursor=cursor,
                max_bytes=limit,
                finished=finished,
            )
            return {
                "state": chunk.state,
                "text": chunk.text,
                "cursor": chunk.cursor,
                "reset": chunk.reset,
                "truncated": chunk.truncated,
                "message": chunk.message,
                "at_end": chunk.at_end,
                "finished": finished,
            }
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except RegistryReadError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return create_app(api_router=api, static_dir=STATIC_DIR, login_code=login_code, allowed_hosts=allowed_hosts)
