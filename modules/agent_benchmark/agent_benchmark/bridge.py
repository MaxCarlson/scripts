"""Thin supported MCP dispatch plus fresh OpenCode HTTP reconciliation.

Targets opencode-mcp 3.0.0 and the OpenCode 1.19 message/session schemas.
No services are started and no inference request is retried automatically.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
import math
import hashlib
import os
from pathlib import Path
import shutil
from urllib.parse import quote

import httpx

from .tool_profile import FILE_AGENT, runtime_output_evidence, validate_file_agent
from .lifecycle import Observation, WorkerHandle

ToolCaller = Callable[[str, dict], Awaitable[dict]]


class SubmissionUncertain(RuntimeError):
    """The worker may exist; preserve workspace and receipt, do not resubmit."""

    def __init__(self, receipt: dict):
        super().__init__("Submission outcome uncertain; preserve workspace and reconcile before any retry")
        self.receipt = receipt


class ModelConfigurationError(ValueError):
    """A requested local model is not available through OpenCode's configured provider."""


def _check_configured_models(providers: dict, requests: list[tuple[str, str]]) -> None:
    connected = providers.get("connected", [])
    all_providers = providers.get("all", [])
    if not isinstance(connected, list) or not isinstance(all_providers, list):
        raise RuntimeError("Malformed OpenCode provider model inventory")
    provider_ids = sorted(
        str(item["id"])
        for item in all_providers
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )
    for provider, model in requests:
        if provider != "lmstudio":
            raise ValueError("This initial slice supports only explicit lmstudio models")
        configured = next(
            (item for item in all_providers if isinstance(item, dict) and item.get("id") == provider),
            None,
        )
        configured_models = configured.get("models", {}) if configured else {}
        if not isinstance(configured_models, dict):
            raise RuntimeError(f"Malformed OpenCode model inventory for provider '{provider}'")
        model_ids = sorted(model_id for model_id in configured_models if isinstance(model_id, str))
        if configured is None:
            raise ModelConfigurationError(
                f"OpenCode provider '{provider}' is not configured. Configured providers: "
                f"{', '.join(provider_ids) or '(none)'}."
            )
        if provider not in connected:
            raise ModelConfigurationError(
                f"OpenCode provider '{provider}' is not connected. Requested model '{model}'. "
                f"Configured OpenCode model IDs: {', '.join(model_ids) or '(none)'}."
            )
        if model not in configured_models:
            raise ModelConfigurationError(
                f"OpenCode did not load the exact model ID '{model}' from the isolated trial project config under "
                f"provider '{provider}'. Effective model IDs: {', '.join(model_ids) or '(none)'}. "
                "The benchmark registers the exact LM Studio key per trial; check project-config discovery and "
                "provider/model overrides if this continues."
            )


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
        if len(users) != 1 or users[-1]["info"]["id"] != handle.message_id:
            return unknown
        assistants = [m for m in history if isinstance(m.get("info"), dict)
                      and m["info"].get("role") == "assistant"
                      and m["info"].get("parentID") == handle.message_id]
        if not assistants:
            return unknown
        if len(assistants) > 1:
            for message in assistants:
                stamp = message["info"].get("time")
                created = stamp.get("created") if isinstance(stamp, dict) else None
                if not isinstance(created, (int, float)) or isinstance(created, bool) or not math.isfinite(created):
                    return unknown  # Cannot choose a final step from ambiguous ordering.
        final = assistants[-1]["info"] if isinstance(assistants[-1].get("info"), dict) else {}
        error = final.get("error") if isinstance(final.get("error"), dict) else {}
        has_authoritative_error = isinstance(error.get("name"), str) and bool(error["name"])
        time_info = final.get("time") if isinstance(final.get("time"), dict) else {}
        completed = time_info.get("completed")
        has_completed_time = (
            isinstance(completed, (int, float))
            and not isinstance(completed, bool)
            and math.isfinite(completed)
        )
        finish_reason = final.get("finish")
        # OpenCode 1.19.3 prompt.ts sets structured after processing StructuredOutput
        # and immediately exits its loop, sometimes preserving finish="tool-calls".
        # Require that exact completed tool + requested format, not arbitrary data.
        user_format = users[-1]["info"].get("format")
        final_parts = assistants[-1].get("parts")
        has_terminal_structured = (
            final.get("structured") is not None
            and isinstance(user_format, dict) and user_format.get("type") == "json_schema"
            and isinstance(final_parts, list)
            and any(isinstance(part, dict) and part.get("type") == "tool" and part.get("tool") == "StructuredOutput"
                    and isinstance(part.get("state"), dict) and part["state"].get("status") == "completed"
                    for part in final_parts)
        )
        normal_finished = has_completed_time and (
            finish_reason in ("stop", "length", "content-filter")
            or (finish_reason == "tool-calls" and has_terminal_structured)
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
        diagnostic = ""
        if has_authoritative_error:
            error_name = str(error.get("name", "UnknownWorkerError"))[:200]
            error_message = error.get("data", {}).get("message") if isinstance(error.get("data"), dict) else None
            if not isinstance(error_message, str):
                error_message = error.get("message")
            diagnostic = error_name if not isinstance(error_message, str) or not error_message else (
                f"{error_name}: {error_message[:1000]}"
            )
            error_data = error.get("data") if isinstance(error.get("data"), dict) else {}
            for key in ("statusCode", "isRetryable", "responseBody"):
                value = error_data.get(key)
                if value is not None and isinstance(value, (str, int, bool)):
                    diagnostic += f"; {key}={str(value)[:1000]}"
            diagnostic = diagnostic[:3000]
        elif finish_reason == "length":
            diagnostic = "Provider finish reason: length (generation limit reached; context overflow not established)."
        elif finish_reason == "content-filter":
            diagnostic = "Provider finish reason: content-filter (output was filtered)."
        return Observation(status, state, finished, tools_running, True, diagnostic)
    except (KeyError, TypeError, AttributeError, ValueError):
        return unknown


class OpenCodeBridge:
    def __init__(self, call_tool: ToolCaller, http: httpx.AsyncClient):
        self.call_tool = call_tool
        self.http = http
        self.last_receipt: dict = {}
        self.last_history: list = []
        self.last_session: object = None
        self.project_context: dict | None = None
        self.prepared_session: dict | None = None
        self.submission_attempted = False
        self.session_creation_attempted = False
        self.session_evidence: dict = {}

    async def validate_models(self, requests: list[tuple[str, str]]) -> None:
        """Validate local model IDs once before allocating trial workspaces."""
        if not requests:
            return
        health = await self._get("/global/health", Path.cwd())
        providers = await self._get("/provider", Path.cwd())
        if not isinstance(health, dict) or not isinstance(providers, dict):
            raise RuntimeError("Malformed runtime/model preflight response")
        _check_configured_models(providers, requests)

    async def validate_provider(self, provider: str = "lmstudio") -> set[str]:
        """Validate provider connectivity without requiring project model registration yet."""
        health = await self._get("/global/health", Path.cwd())
        providers = await self._get("/provider", Path.cwd())
        if not isinstance(health, dict) or not isinstance(providers, dict):
            raise RuntimeError("Malformed runtime/model preflight response")
        connected = providers.get("connected", [])
        all_providers = providers.get("all", [])
        if not isinstance(connected, list) or not isinstance(all_providers, list):
            raise RuntimeError("Malformed OpenCode provider model inventory")
        entry = next((item for item in all_providers if isinstance(item, dict) and item.get("id") == provider), None)
        if entry is None:
            configured = sorted(str(item.get("id")) for item in all_providers if isinstance(item, dict) and item.get("id"))
            raise ModelConfigurationError(
                f"OpenCode provider '{provider}' is not configured. Configured providers: {', '.join(configured) or '(none)'}."
            )
        models = entry.get("models", {})
        if not isinstance(models, dict) or any(not isinstance(key, str) for key in models):
            raise RuntimeError(f"Malformed OpenCode model inventory for provider '{provider}'")
        if provider not in connected:
            raise ModelConfigurationError(f"OpenCode provider '{provider}' is not connected.")
        return set(models)

    async def preflight(self, directory: Path, *, provider: str, model: str, agent: str, project_id: str) -> dict:
        """Read-only model/role and exact trial-project validation; no prompt submission."""
        if self.submission_attempted or self.session_creation_attempted or self.prepared_session is not None:
            raise RuntimeError("Use a fresh bridge for each trial")
        self.project_context = None
        health = await self._get("/global/health", directory)
        providers = await self._get("/provider", directory)
        if not isinstance(health, dict) or not isinstance(providers, dict):
            raise RuntimeError("Malformed runtime/model/role preflight response")
        _check_configured_models(providers, [(provider, model)])
        agents = await self._get("/agent", directory)
        if not isinstance(agents, list):
            raise RuntimeError("Malformed runtime/model/role preflight response")
        role = next((a for a in agents if a.get("name") == agent), None)
        if role is None or agent not in ("local-worker", "local-reviewer", FILE_AGENT):
            raise ModelConfigurationError(f"Requested bounded local role '{agent}' is unavailable in this trial project")
        if agent == FILE_AGENT:
            try:
                output_trust = runtime_output_evidence(await self._get("/path", directory), health.get("version"), str(self.http.base_url))
                output_directory = Path(output_trust["directory"]) if output_trust else None
                validate_file_agent(role, trusted_output_directory=output_directory)
            except ValueError as error:
                raise ModelConfigurationError(f"OpenCode file-tools-v1 preflight failed: {error}") from error
        project = await self._validate_project(directory, project_id)
        self.project_context = project
        # Preserve permissions/configuration as observations, not a sandbox claim.
        return {"opencode_version": health.get("version"), "provider": provider, "model": model,
                "agent": agent, "permissions": role.get("permission"), "bridge_version": "3.0.0",
                "tool_output_trust": output_trust if agent == FILE_AGENT else None,
                "project": project,
                "agent_configuration": {"name": role.get("name"), "mode": role.get("mode"),
                                        "model": role.get("model"),
                                        "prompt_sha256": (hashlib.sha256(role["prompt"].encode()).hexdigest()
                                                          if isinstance(role.get("prompt"), str) else None)},
                "tool_metadata": {"source": "/agent", "tools": role.get("tools"),
                                  "availability": "available" if role.get("tools") is not None else "unavailable",
                                  "limitation": "Role metadata does not establish provider-bound tool schemas"}}

    @staticmethod
    def _same_directory(value: object, directory: Path) -> bool:
        if not isinstance(value, str) or not value:
            return False
        try:
            candidate = Path(value)
            return candidate.is_absolute() and candidate.resolve() == directory.resolve()
        except (OSError, ValueError):
            return False

    async def _validate_project(self, directory: Path, project_id: str) -> dict:
        if (not isinstance(project_id, str) or len(project_id) != 40
                or any(c not in "0123456789abcdef" for c in project_id)):
            raise RuntimeError("A committed trial Git project ID is required")
        path_info = await self._get("/path", directory)
        if (not isinstance(path_info, dict)
                or not self._same_directory(path_info.get("directory"), directory)
                or not self._same_directory(path_info.get("worktree"), directory)):
            raise RuntimeError("OpenCode directory/worktree does not match trial workspace")
        project = await self._get("/project/current", directory)
        if (not isinstance(project, dict) or project.get("id") != project_id
                or project.get("vcs") != "git"
                or not self._same_directory(project.get("worktree"), directory)):
            raise RuntimeError("OpenCode project must match the unique trial Git root commit")
        return {"id": project_id, "vcs": "git", "directory": str(directory.resolve()),
                "worktree": str(directory.resolve())}

    def _validate_session(self, session: object, directory: Path, project_id: str, session_id: str = "") -> dict:
        if (not isinstance(session, dict) or not isinstance(session.get("id"), str) or not session["id"]
                or session_id and session["id"] != session_id
                or not self._same_directory(session.get("directory"), directory)
                or session.get("projectID") != project_id):
            raise RuntimeError("Session identity/directory/project mismatch; inference refused")
        return session

    async def prepare_session(self, directory: Path, *, project_id: str) -> dict:
        """Create exactly one empty session, then validate its persisted binding."""
        if self.prepared_session is not None or self.submission_attempted or self.session_creation_attempted:
            raise RuntimeError("Use a fresh session and bridge for each trial")
        if (not self.project_context or self.project_context["id"] != project_id
                or not self._same_directory(self.project_context["directory"], directory)):
            raise RuntimeError("Project preflight is required before session creation")
        # Recheck the project before the first remote mutation; never retry POST.
        await self._validate_project(directory, project_id)
        self.session_creation_attempted = True
        response = await self.http.post("/session", json={"title": "agent-benchmark first attempt"},
                                        headers={"x-opencode-directory": str(directory.resolve())})
        response.raise_for_status()
        self.session_evidence["created"] = response.json()
        session = self._validate_session(self.session_evidence["created"], directory, project_id)
        sid = quote(session["id"], safe="")
        self.session_evidence["persisted"] = await self._get(f"/session/{sid}", directory)
        persisted = self._validate_session(self.session_evidence["persisted"], directory, project_id, session["id"])
        history = await self._get(f"/session/{sid}/message", directory)
        statuses = await self._get("/session/status", directory)
        self.session_evidence.update(history_empty=history == [], statuses=statuses)
        state = statuses.get(session["id"], "idle") if isinstance(statuses, dict) else None
        state = state.get("type") if isinstance(state, dict) else state
        if history != [] or not isinstance(statuses, dict) or state != "idle":
            raise RuntimeError("New benchmark session is not empty and idle; inference refused")
        self.prepared_session = {"id": persisted["id"], "directory": str(directory.resolve()),
                                 "projectID": project_id}
        return dict(self.prepared_session)

    async def dispatch(self, workspace: Path, prompt: str, *, provider: str, model: str, agent: str) -> WorkerHandle:
        if self.submission_attempted:
            raise RuntimeError("Inference may be submitted only once per fresh session")
        if not provider or not model or not agent:
            raise ValueError("Explicit provider, model and role are required")
        if not self.prepared_session or not self.project_context:
            raise RuntimeError("Validated project and empty session required before inference")
        session = self._validate_session(self.prepared_session, workspace, self.project_context["id"])
        self.last_history = []
        self.last_receipt = {"directory": str(workspace), "status": "unknown", "sessionId": session["id"],
                             "projectID": session["projectID"]}
        self.submission_attempted = True

        def remember(receipt: dict) -> None:
            # A mismatched response must not redirect cancellation to another session.
            if receipt.get("sessionId", session["id"]) != session["id"]:
                self.last_receipt["received_receipt"] = receipt
            self.last_receipt.update({k: v for k, v in receipt.items() if k not in ("sessionId", "projectID")})

        try:
            receipt = await self.call_tool("opencode_fire", {
                "directory": str(workspace), "sessionId": session["id"], "prompt": prompt,
                "providerID": provider, "modelID": model, "agent": agent,
                "title": "agent-benchmark first attempt",
            })
            if isinstance(receipt, dict):
                remember(receipt)
        except Exception as error:
            if isinstance(error, SubmissionUncertain) and isinstance(error.receipt, dict):
                remember(error.receipt)
            raise SubmissionUncertain(self.last_receipt) from error
        if (not isinstance(receipt, dict) or receipt.get("sessionId") != session["id"]
                or not all(isinstance(receipt.get(k), str) and receipt[k] for k in ("jobId", "messageId"))):
            raise SubmissionUncertain(self.last_receipt)
        return WorkerHandle(receipt["jobId"], session["id"], receipt["messageId"], workspace, session["projectID"])

    async def _get(self, path: str, directory: Path) -> object:
        response = await self.http.get(path, headers={"x-opencode-directory": str(directory.resolve())})
        response.raise_for_status()
        return response.json()

    async def observe(self, handle: WorkerHandle) -> Observation:
        sid = quote(handle.session_id, safe="")
        session = await self._get(f"/session/{sid}", handle.workspace)
        self.last_session = session
        if (not isinstance(session, dict) or session.get("id") != handle.session_id
                or not self._same_directory(session.get("directory"), handle.workspace)
                or handle.project_id and session.get("projectID") != handle.project_id):
            return Observation("unknown", None, False, True, False, "Session identity/directory/project mismatch")
        history = await self._get(f"/session/{sid}/message", handle.workspace)
        # Read status after messages; never substitute a cached terminal job response.
        statuses = await self._get("/session/status", handle.workspace)
        self.last_history = history if isinstance(history, list) else []
        return parse_observation(handle, statuses, history)

    async def cancel(self, handle: WorkerHandle) -> object:
        if not handle.session_id or not handle.message_id or not handle.job_id:
            raise RuntimeError("No confirmed job/session ownership; cancellation refused")
        if handle.project_id:
            session = await self._get(f"/session/{quote(handle.session_id, safe='')}", handle.workspace)
            self._validate_session(session, handle.workspace, handle.project_id, handle.session_id)
        history = await self._get(f"/session/{quote(handle.session_id, safe='')}/message", handle.workspace)
        if not isinstance(history, list):
            raise RuntimeError("Missing session history; cancellation refused")
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
