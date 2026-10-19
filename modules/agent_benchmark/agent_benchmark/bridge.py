"""Thin supported MCP dispatch plus fresh OpenCode HTTP reconciliation.

Targets opencode-mcp 3.0.0 and the OpenCode 1.19 message/session schemas.
No services are started and no inference request is retried automatically.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
import math
import os
from pathlib import Path
import shutil
from urllib.parse import quote

import httpx

from .lifecycle import Observation, WorkerHandle

ToolCaller = Callable[[str, dict], Awaitable[dict]]


class SubmissionUncertain(RuntimeError):
    """The worker may exist; preserve workspace and receipt, do not resubmit."""

    def __init__(self, receipt: dict):
        super().__init__("Submission outcome uncertain; preserve workspace and reconcile before any retry")
        self.receipt = receipt


def _ordered(history: list) -> list:
    def _sort_key(m: object) -> tuple[float, str]:
        if not isinstance(m, dict):
            return (0.0, "")
        info = m.get("info")
        if not isinstance(info, dict):
            return (0.0, "")
        time_info = info.get("time")
        created = time_info.get("created") if isinstance(time_info, dict) else 0
        if not isinstance(created, (int, float)) or isinstance(created, bool) or not math.isfinite(created):
            created = 0.0
        return (float(created), str(info.get("id") or ""))

    return sorted(history, key=_sort_key)


def parse_observation(handle: WorkerHandle, statuses: object, history: object) -> Observation:
    """Parse raw remote evidence; absent session entry in a valid map means idle.

    OpenCode omits idle sessions from /session/status. A valid session lookup,
    matching user turn, completed assistant and terminal tools are still required.
    """
    unknown = Observation("unknown", None, False, True, False, "Missing or malformed fresh session evidence")
    if not isinstance(statuses, dict) or not isinstance(history, list) or not history:
        return unknown
    try:
        history = _ordered(history)
        if any(not isinstance(m, dict) or not isinstance(m.get("info"), dict)
               or not isinstance(m["info"].get("id"), str)
               or m["info"].get("sessionID") != handle.session_id
               for m in history):
            return unknown
        users = [m for m in history if isinstance(m.get("info"), dict) and m["info"].get("role") == "user"]
        if not users or users[-1]["info"]["id"] != handle.message_id:
            return unknown
        assistants = [m for m in history if isinstance(m.get("info"), dict)
                      and m["info"].get("role") == "assistant"
                      and m["info"].get("parentID") == handle.message_id]
        if not assistants:
            return unknown
        final = assistants[-1]["info"] if isinstance(assistants[-1].get("info"), dict) else {}
        error = final.get("error") if isinstance(final.get("error"), dict) else {}
        has_authoritative_error = bool(error)
        time_info = final.get("time") if isinstance(final.get("time"), dict) else {}
        completed = time_info.get("completed")
        has_completed_time = (
            isinstance(completed, (int, float))
            and not isinstance(completed, bool)
            and math.isfinite(completed)
        )
        finish_reason = final.get("finish")
        has_valid_structured = final.get("structured") is not None

        normal_finished = has_completed_time and (
            has_valid_structured
            or (finish_reason is not None and finish_reason not in ("tool-calls", "unknown"))
        )
        finished = normal_finished or has_authoritative_error
        tools_running = False
        for message in assistants:
            parts = message.get("parts")
            if not isinstance(parts, list):
                tools_running = True
                continue
            for part in parts:
                if not isinstance(part, dict):
                    tools_running = True
                elif part.get("type") == "tool" and (
                    not isinstance(part.get("state"), dict)
                    or part["state"].get("status") not in ("completed", "error")
                ):
                    tools_running = True
        raw = statuses.get(handle.session_id, "idle")
        state = raw if isinstance(raw, str) else raw.get("type", raw.get("state", "unknown"))
        status = ("cancelled" if error.get("name") == "MessageAbortedError" else "failed") if has_authoritative_error else (
            "completed" if finished else "running"
        )
        return Observation(status, state, finished, tools_running, True)
    except (KeyError, TypeError, AttributeError, ValueError):
        return unknown


class OpenCodeBridge:
    def __init__(self, call_tool: ToolCaller, http: httpx.AsyncClient):
        self.call_tool = call_tool
        self.http = http
        self.last_receipt: dict = {}
        self.last_history: list = []

    async def preflight(self, directory: Path, *, provider: str, model: str, agent: str) -> dict:
        """Read-only check; explicit configured local model and worker role required."""
        health = await self._get("/global/health", directory)
        providers = await self._get("/provider", directory)
        agents = await self._get("/agent", directory)
        if provider != "lmstudio":
            raise ValueError("This initial slice supports only explicit lmstudio models")
        configured = next((p for p in providers.get("all", []) if p.get("id") == provider), None)
        if (not configured or model not in configured.get("models", {})
                or provider not in providers.get("connected", [])):
            raise ValueError("Requested local model/provider is not configured and connected")
        role = next((a for a in agents if a.get("name") == agent), None)
        if role is None or agent not in ("local-worker", "local-reviewer"):
            raise ValueError("Requested bounded local role is unavailable")
        # Preserve the role permissions as observable configuration, not a sandbox claim.
        return {"opencode_version": health.get("version"), "provider": provider, "model": model,
                "agent": agent, "permissions": role.get("permission"), "bridge_version": "3.0.0"}

    async def dispatch(self, workspace: Path, prompt: str, *, provider: str, model: str, agent: str) -> WorkerHandle:
        if not provider or not model or not agent:
            raise ValueError("Explicit provider, model and role are required")
        self.last_history = []
        self.last_receipt = {"directory": str(workspace), "status": "unknown"}
        try:
            receipt = await self.call_tool("opencode_fire", {
                "directory": str(workspace), "prompt": prompt, "providerID": provider,
                "modelID": model, "agent": agent, "title": "agent-benchmark first attempt",
            })
            self.last_receipt = receipt if isinstance(receipt, dict) else self.last_receipt
        except Exception as error:
            if isinstance(error, SubmissionUncertain):
                self.last_receipt = error.receipt
            raise SubmissionUncertain(self.last_receipt) from error
        if not isinstance(receipt, dict):
            raise SubmissionUncertain(self.last_receipt)
        if not all(isinstance(receipt.get(k), str) and receipt[k] for k in ("jobId", "sessionId", "messageId")):
            raise SubmissionUncertain(receipt)
        # Unknown status with known handles is observed, never re-submitted.
        return WorkerHandle(receipt["jobId"], receipt["sessionId"], receipt["messageId"], workspace)

    async def _get(self, path: str, directory: Path) -> object:
        response = await self.http.get(path, params={"directory": str(directory)})
        response.raise_for_status()
        return response.json()

    async def observe(self, handle: WorkerHandle) -> Observation:
        sid = quote(handle.session_id, safe="")
        session = await self._get(f"/session/{sid}", handle.workspace)
        if (not isinstance(session, dict) or session.get("id") != handle.session_id
                or Path(session.get("directory", "")).resolve() != handle.workspace.resolve()):
            return Observation("unknown", None, False, True, False, "Session identity/directory mismatch")
        history = await self._get(f"/session/{sid}/message", handle.workspace)
        # Read status after messages; never substitute a cached terminal job response.
        statuses = await self._get("/session/status", handle.workspace)
        self.last_history = history if isinstance(history, list) else []
        return parse_observation(handle, statuses, history)

    async def cancel(self, handle: WorkerHandle) -> object:
        if not handle.session_id or not handle.message_id or not handle.job_id:
            raise RuntimeError("No confirmed job/session ownership; cancellation refused")
        history = await self._get(f"/session/{quote(handle.session_id, safe='')}/message", handle.workspace)
        users = [m for m in _ordered(history) if m["info"].get("role") == "user"]
        if (not users or users[-1]["info"].get("id") != handle.message_id
                or users[-1]["info"].get("sessionID") != handle.session_id):
            raise RuntimeError("Session ownership changed to a newer turn; cancellation refused")
        return await self.call_tool("opencode_job_cancel", {"jobId": handle.job_id})


@asynccontextmanager
async def connected_bridge(*, base_url: str = "http://127.0.0.1:4096", request_seconds: float = 10):
    """Use the official MCP SDK and cached pinned bridge. No package auto-install.

    Only the benchmark-owned stdio MCP client subprocess is closed on exit.
    Shared OpenCode and LM Studio services are never started/stopped by this code.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if not math.isfinite(request_seconds) or request_seconds <= 0:
        raise ValueError("Request timeout must be finite and positive")
    command = shutil.which("npx")
    if command is None:
        raise FileNotFoundError("npx is unavailable; install the configured bridge separately")
    environment = {**os.environ, "OPENCODE_BASE_URL": base_url, "OPENCODE_AUTO_SERVE": "false",
                   "OPENCODE_TOOL_PROFILE": "essential"}
    password = os.environ.get("OPENCODE_SERVER_PASSWORD")
    auth = (os.environ.get("OPENCODE_SERVER_USERNAME", "opencode"), password) if password else None
    params = StdioServerParameters(command=command, args=["--offline", "--yes", "opencode-mcp@3.0.0"], env=environment)
    async with httpx.AsyncClient(base_url=base_url, timeout=request_seconds, auth=auth, trust_env=False) as http:
        # Fail before launching MCP if the existing server is unavailable.
        response = await http.get("/global/health")
        response.raise_for_status()
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=request_seconds)) as session:
                await session.initialize()

                async def call_tool(name: str, args: dict) -> dict:
                    result = await session.call_tool(name, args, read_timeout_seconds=timedelta(seconds=request_seconds))
                    data = result.structuredContent
                    if result.isError or not isinstance(data, dict) or data.get("isError"):
                        payload = dict(data) if isinstance(data, dict) else {}
                        if "error" not in payload and getattr(result, "content", None):
                            text_parts = [
                                getattr(c, "text", "") for c in result.content
                                if getattr(c, "type", "") == "text" and isinstance(getattr(c, "text", None), str)
                            ]
                            if text_parts:
                                raw_err = "\n".join(text_parts)
                                if password and password in raw_err:
                                    raw_err = raw_err.replace(password, "***")
                                payload["error"] = raw_err
                        if isinstance(payload.get("error"), str) and password and password in payload["error"]:
                            payload["error"] = payload["error"].replace(password, "***")
                        raise SubmissionUncertain(payload)
                    return data

                yield OpenCodeBridge(call_tool, http)
