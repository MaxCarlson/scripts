"""Read-only Runmux browser API, loaded only by the optional ``runmux web`` command."""

from __future__ import annotations

import asyncio
import json
import socket
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from web_ui_tools import LOOPBACK_HOSTS, create_app

from runmux.constants import TERMINAL_STATUSES
from runmux.ipc import IpcError, open_input_socket, request_json
from runmux.lifecycle import (
    InvalidLifecycleTransitionError,
    LifecycleError,
    LifecycleManager,
    LifecyclePlatformError,
    LifecycleSupervisorUnavailableError,
)
from runmux.lifecycle import (
    RunNotFoundError as LifecycleRunNotFoundError,
)
from runmux.platform_paths import get_state_dir
from runmux.runner import RunnerError, create_managed_run
from runmux.store import RunNotFoundError, RunStore
from runmux.web_adapter import (
    DEFAULT_LOG_CHUNK_BYTES,
    MAX_LOG_CHUNK_BYTES,
    ReadOnlyRunmux,
    RegistryReadError,
    read_output_chunk,
    read_terminal_chunk,
    serialize_run,
)

STATIC_DIR = Path(__file__).resolve().parent / "web_static"
MAX_LAUNCH_ARGUMENTS = 256
MAX_LAUNCH_VALUE_LENGTH = 4096
MAX_LAUNCH_TOTAL_LENGTH = 65536


class LaunchRequest(BaseModel):
    """Validated argv-based request for creating one supervised run."""

    program: str = Field(min_length=1, max_length=MAX_LAUNCH_VALUE_LENGTH)
    arguments: list[str] = Field(default_factory=list, max_length=MAX_LAUNCH_ARGUMENTS)
    name: str | None = Field(default=None, max_length=120)
    cwd: str | None = Field(default=None, max_length=MAX_LAUNCH_VALUE_LENGTH)

class StopRequest(BaseModel):
    """Optional configuration for terminating a managed process."""

    force: bool = False


class RestartRequest(BaseModel):
    """Optional configuration for restarting a managed run."""

    force_color: bool | None = None


class DuplicateRequest(BaseModel):
    """Optional configuration for duplicating a managed run."""

    force_color: bool | None = None


def create_runmux_web_app(
    state_dir: Path | None = None,
    *,
    login_code: str,
    allowed_hosts: tuple[str, ...] = LOOPBACK_HOSTS,
) -> FastAPI:
    """Create an authenticated browser view and process-launch API for Runmux."""

    resolved_state_dir = state_dir or get_state_dir()
    backend = ReadOnlyRunmux(resolved_state_dir)
    lifecycle = LifecycleManager(resolved_state_dir)
    default_cwd = Path.cwd().resolve()
    api = APIRouter(prefix="/api")

    @api.get("/runs")
    def list_runs() -> list[dict[str, Any]]:
        try:
            return [serialize_run(record) for record in backend.list_runs()]
        except RegistryReadError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @api.get("/launch-defaults")
    def launch_defaults() -> dict[str, str]:
        return {"cwd": str(default_cwd)}

    @api.post("/runs", status_code=201)
    async def launch_run(payload: LaunchRequest) -> dict[str, Any]:
        program = payload.program.strip()
        arguments = payload.arguments
        name = payload.name.strip() if payload.name and payload.name.strip() else None
        cwd_text = payload.cwd.strip() if payload.cwd and payload.cwd.strip() else None
        values = [program, *arguments, *(value for value in (name, cwd_text) if value is not None)]
        if not program:
            raise HTTPException(status_code=422, detail="Enter a program to launch.")
        if any(len(value) > MAX_LAUNCH_VALUE_LENGTH for value in values):
            raise HTTPException(
                status_code=422,
                detail="Each command, argument, name, and directory must be at most 4096 characters.",
            )
        if sum(len(value) for value in values) > MAX_LAUNCH_TOTAL_LENGTH:
            raise HTTPException(status_code=422, detail="The complete launch request must be at most 65536 characters.")
        if any("\x00" in value for value in values):
            raise HTTPException(
                status_code=422,
                detail="Program, arguments, name, and directory cannot contain NUL characters.",
            )
        try:
            cwd = Path(cwd_text).expanduser().resolve() if cwd_text else default_cwd
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=f"Working directory is invalid: {error}") from error
        if not cwd.exists() or not cwd.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"Working directory does not exist or is not a directory: {cwd}",
            )
        try:
            started = await run_in_threadpool(
                create_managed_run,
                RunStore(resolved_state_dir),
                program_args=[program, *arguments],
                cwd=cwd,
                name=name,
                force_color=True,
            )
            record = started.record
            record, connection = backend.refresh_display_status(record)
            return serialize_run(record, connection=connection)
        except RunnerError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except OSError as error:
            raise HTTPException(status_code=400, detail=f"Could not launch the process: {error}") from error

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

    @api.get("/runs/{run_id}/telemetry")
    async def run_telemetry(run_id: str) -> dict[str, Any]:
        try:
            return await run_in_threadpool(backend.get_run_telemetry, run_id)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except RegistryReadError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @api.get("/telemetry")
    async def overview_telemetry() -> dict[str, Any]:
        try:
            return await run_in_threadpool(backend.get_overview_telemetry)
        except RegistryReadError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @api.post("/runs/{run_id}/stop")
    async def stop_run_endpoint(
        run_id: str,
        payload: StopRequest | None = None,
    ) -> dict[str, Any]:
        force = payload.force if payload else False
        try:
            result = await run_in_threadpool(lifecycle.stop_run, run_id, force=force)
            return {
                "action": result.action,
                "status": result.status,
                "message": result.message,
                "run": serialize_run(result.run),
            }
        except LifecycleRunNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except InvalidLifecycleTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except LifecycleSupervisorUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except LifecycleError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @api.post("/runs/{run_id}/kill")
    async def kill_run_endpoint(
        run_id: str,
        payload: StopRequest | None = None,
    ) -> dict[str, Any]:
        force = payload.force if (payload and payload.force is not None) else True
        try:
            result = await run_in_threadpool(lifecycle.kill_run, run_id, force=force)
            return {
                "action": result.action,
                "status": result.status,
                "message": result.message,
                "run": serialize_run(result.run),
            }
        except LifecycleRunNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except InvalidLifecycleTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except LifecycleSupervisorUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except LifecycleError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @api.post("/runs/{run_id}/restart", status_code=201)
    async def restart_run_endpoint(
        run_id: str,
        payload: RestartRequest | None = None,
    ) -> dict[str, Any]:
        force_color = payload.force_color if payload else None
        try:
            result = await run_in_threadpool(lifecycle.restart_run, run_id, force_color=force_color)
            return {
                "action": result.action,
                "status": result.status,
                "message": result.message,
                "run": serialize_run(result.run),
                "new_run_id": result.new_run_id,
                "old_run_id": result.old_run_id,
            }
        except LifecycleRunNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except InvalidLifecycleTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except LifecycleSupervisorUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except LifecycleError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @api.post("/runs/{run_id}/duplicate", status_code=201)
    async def duplicate_run_endpoint(
        run_id: str,
        payload: DuplicateRequest | None = None,
    ) -> dict[str, Any]:
        force_color = payload.force_color if payload else None
        try:
            result = await run_in_threadpool(lifecycle.duplicate_run, run_id, force_color=force_color)
            return {
                "action": result.action,
                "status": result.status,
                "message": result.message,
                "run": serialize_run(result.run),
                "new_run_id": result.new_run_id,
                "source_run_id": result.old_run_id,
            }
        except LifecycleRunNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except InvalidLifecycleTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except LifecycleSupervisorUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except LifecycleError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @api.post("/runs/{run_id}/pause")
    async def pause_run_endpoint(run_id: str) -> dict[str, Any]:
        try:
            result = await run_in_threadpool(lifecycle.pause_run, run_id)
            return {
                "action": result.action,
                "status": result.status,
                "message": result.message,
                "run": serialize_run(result.run),
            }
        except LifecycleRunNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except LifecyclePlatformError as error:
            raise HTTPException(status_code=501, detail=str(error)) from error
        except InvalidLifecycleTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except LifecycleSupervisorUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except LifecycleError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @api.post("/runs/{run_id}/resume")
    async def resume_run_endpoint(run_id: str) -> dict[str, Any]:
        try:
            result = await run_in_threadpool(lifecycle.resume_run, run_id)
            return {
                "action": result.action,
                "status": result.status,
                "message": result.message,
                "run": serialize_run(result.run),
            }
        except LifecycleRunNotFoundError as error:
            raise HTTPException(status_code=404, detail="Run not found") from error
        except LifecyclePlatformError as error:
            raise HTTPException(status_code=501, detail=str(error)) from error
        except InvalidLifecycleTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except LifecycleSupervisorUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except LifecycleError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

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

    @api.websocket("/runs/{run_id}/terminal")
    async def run_terminal(websocket: WebSocket, run_id: str) -> None:
        await websocket.accept()
        record = None
        view_session_id = uuid.uuid4().hex
        input_session_id: str | None = None
        input_channel: socket.socket | Any | None = None
        can_input = False
        view_attached = False
        offset: int | None = None
        generation: str | None = None
        next_output_at = 0.0
        output_inflight = False
        next_heartbeat_at = time.monotonic() + 2.0
        try:
            record = backend.get_run(run_id)
            finished = record.status in TERMINAL_STATUSES
            if finished:
                terminal_status = _terminal_status({}, mode="view", finished=True)
            else:
                # Attempt cleanup even if the IPC reply is lost after the supervisor
                # registered the lease but before the browser receives its status.
                view_attached = True
                attachment = await run_in_threadpool(
                    request_json,
                    record,
                    op="attach",
                    payload={"session_id": view_session_id, "mode": "view"},
                    timeout=1.0,
                )
                terminal_status = _terminal_status(attachment, mode="view")
            await websocket.send_json(terminal_status)

            while True:
                now = time.monotonic()
                if not output_inflight and now >= next_output_at:
                    try:
                        chunk = await run_in_threadpool(
                            read_terminal_chunk,
                            Path(record.log_path),
                            state_dir=backend.state_dir,
                            run_id=record.id,
                            offset=offset,
                            generation=generation,
                        )
                    except ValueError:
                        await websocket.send_json({"type": "error", "message": "Output is unavailable."})
                        break
                    if chunk.reset:
                        await websocket.send_json(
                            {"type": "output_reset", "truncated": chunk.truncated, "state": chunk.state}
                        )
                    if chunk.data:
                        await websocket.send_bytes(chunk.data)
                        output_inflight = True
                    elif chunk.state != "available":
                        await websocket.send_json(
                            {"type": "output_state", "state": chunk.state, "message": chunk.message}
                        )
                    offset, generation = chunk.offset, chunk.generation
                    next_output_at = now + 0.08

                if view_attached and now >= next_heartbeat_at:
                    try:
                        attachment = await run_in_threadpool(
                            request_json,
                            record,
                            op="heartbeat",
                            payload={"session_id": view_session_id},
                            timeout=1.0,
                        )
                        if input_session_id is not None:
                            input_status = await run_in_threadpool(
                                request_json,
                                record,
                                op="heartbeat",
                                payload={"session_id": input_session_id},
                                timeout=1.0,
                            )
                            can_input = bool(input_status.get("session_holds_lock"))
                            attachment = input_status
                        await websocket.send_json(
                            _terminal_status(
                                attachment,
                                mode="interact" if input_session_id is not None else "view",
                            )
                        )
                    except IpcError:
                        await websocket.send_json({"type": "error", "message": "Run supervisor disconnected."})
                        break
                    next_heartbeat_at = now + 2.0

                try:
                    message = await asyncio.wait_for(websocket.receive(), timeout=0.05)
                except TimeoutError:
                    continue
                if message["type"] == "websocket.disconnect":
                    break
                binary = message.get("bytes")
                if binary is not None:
                    if input_channel is not None and can_input and len(binary) <= 4096:
                        with suppress(OSError):
                            await run_in_threadpool(input_channel.sendall, binary)
                    continue
                text = message.get("text")
                if not isinstance(text, str) or len(text) > 4096:
                    await websocket.send_json({"type": "error", "message": "Unsupported terminal message."})
                    continue
                try:
                    command = json.loads(text)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "message": "Invalid terminal message."})
                    continue
                if not isinstance(command, dict):
                    continue
                action = command.get("type")
                if action == "ack":
                    output_inflight = False
                    next_output_at = 0.0
                elif action == "control" and command.get("enabled") is True:
                    if record.status in TERMINAL_STATUSES:
                        await websocket.send_json({"type": "error", "message": "This run has already finished."})
                        continue
                    if input_channel is None:
                        input_session_id = uuid.uuid4().hex
                        try:
                            input_channel = await run_in_threadpool(
                                open_input_socket,
                                record,
                                session_id=input_session_id,
                                timeout=1.0,
                            )
                            attachment = await run_in_threadpool(
                                request_json,
                                record,
                                op="status",
                                payload={"session_id": input_session_id},
                                timeout=1.0,
                            )
                            can_input = bool(attachment.get("session_holds_lock"))
                        except IpcError:
                            _close_input_channel(input_channel)
                            input_channel = None
                            input_session_id = None
                            await websocket.send_json(
                                {"type": "error", "message": "Could not attach to the run supervisor."}
                            )
                            continue
                        await websocket.send_json(_terminal_status(attachment, mode="interact"))
                elif action == "control" and command.get("enabled") is False:
                    _close_input_channel(input_channel)
                    input_channel = None
                    input_session_id = None
                    can_input = False
                    await websocket.send_json({"type": "status", "mode": "view", "session_holds_lock": False})
                elif action == "lock" and input_session_id is not None:
                    try:
                        attachment = await run_in_threadpool(
                            request_json,
                            record,
                            op="lock",
                            payload={"session_id": input_session_id},
                            timeout=1.0,
                        )
                        can_input = bool(attachment.get("session_holds_lock"))
                        await websocket.send_json(_terminal_status(attachment, mode="interact"))
                    except IpcError:
                        await websocket.send_json({"type": "error", "message": "Input lock request failed."})
                elif action == "resize" and input_session_id is not None:
                    rows, columns = command.get("rows"), command.get("columns")
                    if (
                        can_input
                        and isinstance(rows, int)
                        and not isinstance(rows, bool)
                        and isinstance(columns, int)
                        and not isinstance(columns, bool)
                        and 1 <= rows <= 500
                        and 1 <= columns <= 500
                    ):
                        with suppress(IpcError):
                            await run_in_threadpool(
                                request_json,
                                record,
                                op="resize",
                                payload={"rows": rows, "columns": columns, "session_id": input_session_id},
                                timeout=1.0,
                            )
        except RunNotFoundError:
            await websocket.send_json({"type": "error", "message": "Run not found."})
            await websocket.close(code=4404)
        except IpcError:
            await websocket.send_json({"type": "error", "message": "Run supervisor is unavailable."})
            await websocket.close(code=1011)
        except WebSocketDisconnect:
            pass
        finally:
            _close_input_channel(input_channel)
            if view_attached and record is not None:
                with suppress(IpcError):
                    await run_in_threadpool(
                        request_json,
                        record,
                        op="detach",
                        payload={"session_id": view_session_id},
                        timeout=1.0,
                    )

    return create_app(
        api_router=api,
        static_dir=STATIC_DIR,
        login_code=login_code,
        allowed_hosts=allowed_hosts,
        allow_inline_styles=True,
    )


def _terminal_status(value: dict[str, Any], *, mode: str, finished: bool = False) -> dict[str, Any]:
    """Project only attachment and input-lock state to the browser terminal."""

    return {
        "type": "status",
        "mode": mode,
        "session_holds_lock": bool(value.get("session_holds_lock")),
        "session_queue_position": value.get("session_queue_position"),
        "lock_queue_count": value.get("lock_queue_count", 0),
        "current_interactors": value.get("current_interactors", 0),
        "finished": finished,
    }


def _close_input_channel(channel: Any | None) -> None:
    if channel is None:
        return
    with suppress(OSError):
        channel.shutdown(socket.SHUT_WR)
    with suppress(OSError):
        channel.close()
