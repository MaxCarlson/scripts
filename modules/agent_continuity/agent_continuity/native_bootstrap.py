"""Inference-free native session allocation for LLMD-60 (Codex app-server, AGY ACP, Claude UUIDv4)."""

from __future__ import annotations

import json
import queue
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import closing, suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import ErrorCode
from .models import Provider


class NativeAllocationStatus:
    """Outcome states for inference-free native session allocation."""

    ALLOCATED = "allocated"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class NativeBootstrapRequest:
    """Narrow typed input contract for Agent #1 native session allocation."""

    provider: str
    cwd: str
    timeout_seconds: float = 10.0
    executable: str | None = None
    model: str | None = None
    mcp_servers: tuple[dict[str, Any], ...] = ()
    cancel_event: threading.Event | None = None
    codex_home: Path | None = None
    agy_home: Path | None = None
    live_resume_qualified: bool = False
    command_override: Sequence[str] | None = None


@dataclass(frozen=True, slots=True)
class NativeSessionAllocation:
    """Structured allocation result distinguishing identity, persistence, resumability, and context."""

    provider: str
    status: str
    native_session_id: str | None
    persisted: bool
    interactively_resumable: bool
    effective_provider_context: dict[str, Any] = field(default_factory=dict)
    persistence_evidence: dict[str, Any] = field(default_factory=dict)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    raw_result: dict[str, Any] = field(default_factory=dict)
    fallback_prohibited: bool = True
    error_code: str | None = None
    error_message: str | None = None
    prompt_delivery_contract: dict[str, Any] = field(
        default_factory=lambda: {
            "requires_bootstrap_model_turn": False,
            "initial_prompt_deferred_to_attach": True,
            "workflow_init_mode": "additive_without_extra_turn",
        }
    )

    @property
    def can_authorize_interactive_resume(self) -> bool:
        """Allocated ID alone never authorizes interactive resume without persistence + live qualification."""
        return (
            self.status == NativeAllocationStatus.ALLOCATED
            and bool(self.native_session_id)
            and self.persisted
            and self.interactively_resumable
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["can_authorize_interactive_resume"] = self.can_authorize_interactive_resume
        return data


class _ProtocolFailure(Exception):
    def __init__(
        self,
        status: str,
        error_code: str,
        message: str,
        *,
        notifications: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.message = message
        self.notifications = notifications or []


def _kill_and_reap(proc: subprocess.Popen[str]) -> None:
    if proc.stdin is not None:
        with suppress(OSError, ValueError):
            proc.stdin.close()
    if proc.poll() is None:
        with suppress(OSError):
            proc.terminate()
        try:
            proc.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            with suppress(OSError):
                proc.kill()
            with suppress(OSError, subprocess.TimeoutExpired):
                proc.wait(timeout=1.0)
    if proc.stdout is not None:
        with suppress(OSError, ValueError):
            proc.stdout.close()
    if proc.stderr is not None:
        with suppress(OSError, ValueError):
            proc.stderr.close()


class _JsonRpcStdioTransport:
    """Line-delimited JSON-RPC 2.0 stdio transport with correlation, notifications, timeout, and cancel."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout_seconds: float,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._argv = list(argv)
        self._cwd = cwd
        self._timeout_seconds = max(0.05, float(timeout_seconds))
        self._cancel_event = cancel_event
        self._deadline = time.monotonic() + self._timeout_seconds
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._next_id = 1
        self.notifications: list[dict[str, Any]] = []
        self._request_sent = False

    def __enter__(self) -> _JsonRpcStdioTransport:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise _ProtocolFailure(
                NativeAllocationStatus.CANCELLED,
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Native session allocation cancelled before launch.",
            )
        try:
            self._proc = subprocess.Popen(
                self._argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self._cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise _ProtocolFailure(
                NativeAllocationStatus.FAILED,
                ErrorCode.PROVIDER_UNAVAILABLE,
                f"Failed to spawn native allocation process {self._argv[0]!r}: {exc}",
            ) from exc

        def _pump_stdout() -> None:
            assert self._proc is not None and self._proc.stdout is not None
            try:
                for raw in self._proc.stdout:
                    self._lines.put(("line", raw))
                self._lines.put(("eof", None))
            except Exception as exc:  # pragma: no cover - defensive pipe guard
                self._lines.put(("err", exc))

        self._reader_thread = threading.Thread(target=_pump_stdout, daemon=True)
        self._reader_thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._proc is not None:
            _kill_and_reap(self._proc)
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=0.3)

    def _check_cancel_and_deadline(self) -> float:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise _ProtocolFailure(
                NativeAllocationStatus.CANCELLED,
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Native session allocation cancelled.",
                notifications=list(self.notifications),
            )
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise _ProtocolFailure(
                NativeAllocationStatus.TIMED_OUT,
                ErrorCode.PROVIDER_UNAVAILABLE,
                f"Native session allocation timed out after {self._timeout_seconds:.2f}s.",
                notifications=list(self.notifications),
            )
        return remaining

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self._proc is not None and self._proc.stdin is not None
        req_id = self._next_id
        self._next_id += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}) + "\n"
        self._check_cancel_and_deadline()
        try:
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
            self._request_sent = True
        except OSError as exc:
            status = NativeAllocationStatus.UNCERTAIN if self._request_sent else NativeAllocationStatus.FAILED
            raise _ProtocolFailure(
                status,
                ErrorCode.PROVIDER_UNAVAILABLE,
                f"Failed writing JSON-RPC request {method!r}: {exc}",
                notifications=list(self.notifications),
            ) from exc

        while True:
            remaining = self._check_cancel_and_deadline()
            try:
                kind, value = self._lines.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue

            if kind == "err":
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    f"Stdout read error during {method!r}: {value}",
                    notifications=list(self.notifications),
                )
            if kind == "eof":
                rc = self._proc.poll()
                stderr_tail = ""
                if self._proc.stderr is not None:
                    with suppress(OSError, ValueError):
                        stderr_tail = (self._proc.stderr.read() or "").strip()
                detail = f"exit={rc}" + (f" ({stderr_tail.splitlines()[-1]})" if stderr_tail else "")
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    f"Provider closed stdout before responding to {method!r} ({detail}).",
                    notifications=list(self.notifications),
                )

            raw_line = str(value).strip()
            if not raw_line:
                continue
            try:
                msg = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"Malformed JSON-RPC frame during {method!r}: {exc}",
                    notifications=list(self.notifications),
                ) from exc

            if not isinstance(msg, dict):
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"Non-object JSON-RPC frame during {method!r}.",
                    notifications=list(self.notifications),
                )

            if "id" not in msg or msg["id"] is None:
                if "method" in msg:
                    self.notifications.append(msg)
                    continue
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"Invalid JSON-RPC frame missing both id and method during {method!r}.",
                    notifications=list(self.notifications),
                )

            if msg["id"] != req_id:
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"Mismatched JSON-RPC response id {msg['id']!r} (expected {req_id!r}) for {method!r}.",
                    notifications=list(self.notifications),
                )

            if "error" in msg and msg["error"] is not None:
                err_obj = msg["error"]
                err_msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
                raise _ProtocolFailure(
                    NativeAllocationStatus.FAILED,
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    f"JSON-RPC error from {method!r}: {err_msg}",
                    notifications=list(self.notifications),
                )

            result = msg.get("result")
            if not isinstance(result, dict):
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"JSON-RPC result for {method!r} must be an object.",
                    notifications=list(self.notifications),
                )
            return result


def _resolve_executable(
    provider: str,
    explicit: str | None,
    which_fn: Callable[[str], str | None],
) -> str:
    if explicit:
        return explicit
    found = which_fn(provider)
    if not found:
        raise _ProtocolFailure(
            NativeAllocationStatus.FAILED,
            ErrorCode.PROVIDER_UNAVAILABLE,
            f"Executable for provider {provider!r} was not found on PATH.",
        )
    return found


def _verify_codex_persistence(
    thread_id: str,
    thread_path: str | None,
    codex_home: Path | None,
) -> tuple[bool, dict[str, Any]]:
    evidence: dict[str, Any] = {"thread_path": thread_path, "rollout_exists": False, "state_db_row": False}
    if thread_path:
        p = Path(thread_path)
        if p.is_file() and p.stat().st_size > 0:
            evidence["rollout_exists"] = True
    if codex_home is not None:
        state_db = codex_home / "state_5.sqlite"
        if state_db.is_file():
            with suppress(sqlite3.Error), closing(
                sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=1.0)
            ) as conn:
                row = conn.execute("SELECT 1 FROM threads WHERE id = ?", (thread_id,)).fetchone()
                if row is not None:
                    evidence["state_db_row"] = True
    return bool(evidence["rollout_exists"] or evidence["state_db_row"]), evidence


def _verify_agy_persistence(session_id: str, agy_home: Path | None) -> tuple[bool, dict[str, Any]]:
    evidence: dict[str, Any] = {"agy_home": str(agy_home) if agy_home else None, "conversation_dir_exists": False}
    if agy_home is not None:
        conv_dir = agy_home / "brain" / session_id
        if conv_dir.is_dir():
            evidence["conversation_dir_exists"] = True
    return bool(evidence["conversation_dir_exists"]), evidence


def _allocate_codex(request: NativeBootstrapRequest, which_fn: Callable[[str], str | None]) -> NativeSessionAllocation:
    argv = (
        list(request.command_override)
        if request.command_override
        else [_resolve_executable("codex", request.executable, which_fn), "app-server", "--stdio"]
    )
    with _JsonRpcStdioTransport(
        argv,
        cwd=request.cwd,
        timeout_seconds=request.timeout_seconds,
        cancel_event=request.cancel_event,
    ) as rpc:
        init_result = rpc.call(
            "initialize",
            {"clientInfo": {"name": "agent_continuity", "version": "2.3.0"}},
        )
        start_params: dict[str, Any] = {"cwd": request.cwd, "ephemeral": False}
        if request.model:
            start_params["model"] = request.model
        start_result = rpc.call("thread/start", start_params)
        notifications = list(rpc.notifications)

    thread = start_result.get("thread")
    if not isinstance(thread, dict):
        return NativeSessionAllocation(
            provider=Provider.CODEX.value,
            status=NativeAllocationStatus.UNCERTAIN,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            notifications=notifications,
            raw_result=start_result,
            error_code=ErrorCode.HOOK_SCHEMA_MISMATCH,
            error_message="Codex thread/start response missing 'thread' object.",
        )

    thread_id = thread.get("id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        return NativeSessionAllocation(
            provider=Provider.CODEX.value,
            status=NativeAllocationStatus.UNCERTAIN,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            notifications=notifications,
            raw_result=start_result,
            error_code=ErrorCode.HOOK_SCHEMA_MISMATCH,
            error_message="Codex thread/start response missing non-empty 'thread.id'.",
        )

    if thread.get("ephemeral") is True:
        return NativeSessionAllocation(
            provider=Provider.CODEX.value,
            status=NativeAllocationStatus.FAILED,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            notifications=notifications,
            raw_result=start_result,
            error_code=ErrorCode.ASSOCIATION_CONFLICT,
            error_message="Codex thread/start returned conflicting ephemeral=True for non-ephemeral request.",
        )

    thread_path = thread.get("path") if isinstance(thread.get("path"), str) else None
    persisted, evidence = _verify_codex_persistence(thread_id, thread_path, request.codex_home)
    context = {
        "cwd": start_result.get("cwd") or request.cwd,
        "model": start_result.get("model"),
        "model_provider": start_result.get("modelProvider"),
        "approval_policy": start_result.get("approvalPolicy"),
        "sandbox": start_result.get("sandbox"),
        "user_agent": init_result.get("userAgent"),
        "thread_path": thread_path,
    }
    return NativeSessionAllocation(
        provider=Provider.CODEX.value,
        status=NativeAllocationStatus.ALLOCATED,
        native_session_id=thread_id,
        persisted=persisted,
        interactively_resumable=bool(persisted and request.live_resume_qualified),
        effective_provider_context=context,
        persistence_evidence=evidence,
        notifications=notifications,
        raw_result=start_result,
    )


def _allocate_agy(request: NativeBootstrapRequest, which_fn: Callable[[str], str | None]) -> NativeSessionAllocation:
    argv = (
        list(request.command_override)
        if request.command_override
        else [_resolve_executable("agy", request.executable, which_fn), "acp", "--stdio"]
    )
    with _JsonRpcStdioTransport(
        argv,
        cwd=request.cwd,
        timeout_seconds=request.timeout_seconds,
        cancel_event=request.cancel_event,
    ) as rpc:
        init_result = rpc.call("initialize", {"protocolVersion": 1})
        proto_ver = init_result.get("protocolVersion")
        if proto_ver is not None and (not isinstance(proto_ver, int) or proto_ver < 1):
            raise _ProtocolFailure(
                NativeAllocationStatus.FAILED,
                ErrorCode.PROVIDER_VERSION_UNSUPPORTED,
                f"Unsupported AGY ACP protocolVersion: {proto_ver!r}.",
                notifications=list(rpc.notifications),
            )
        session_result = rpc.call(
            "session/new",
            {"cwd": request.cwd, "mcpServers": list(request.mcp_servers)},
        )
        notifications = list(rpc.notifications)

    session_id = session_result.get("sessionId")
    if not isinstance(session_id, str) or not session_id.strip():
        return NativeSessionAllocation(
            provider=Provider.AGY.value,
            status=NativeAllocationStatus.UNCERTAIN,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            notifications=notifications,
            raw_result=session_result,
            error_code=ErrorCode.HOOK_SCHEMA_MISMATCH,
            error_message="AGY ACP session/new response missing non-empty 'sessionId'.",
        )

    persisted, evidence = _verify_agy_persistence(session_id, request.agy_home)
    context = {
        "cwd": request.cwd,
        "protocol_version": proto_ver if proto_ver is not None else 1,
    }
    return NativeSessionAllocation(
        provider=Provider.AGY.value,
        status=NativeAllocationStatus.ALLOCATED,
        native_session_id=session_id,
        persisted=persisted,
        interactively_resumable=bool(persisted and request.live_resume_qualified),
        effective_provider_context=context,
        persistence_evidence=evidence,
        notifications=notifications,
        raw_result=session_result,
    )


def _allocate_claude(request: NativeBootstrapRequest) -> NativeSessionAllocation:
    if request.cancel_event is not None and request.cancel_event.is_set():
        return NativeSessionAllocation(
            provider=Provider.CLAUDE.value,
            status=NativeAllocationStatus.CANCELLED,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            error_code=ErrorCode.PROVIDER_UNAVAILABLE,
            error_message="Claude session allocation cancelled.",
        )
    session_id = str(uuid.uuid4())
    return NativeSessionAllocation(
        provider=Provider.CLAUDE.value,
        status=NativeAllocationStatus.ALLOCATED,
        native_session_id=session_id,
        persisted=False,
        interactively_resumable=False,
        effective_provider_context={
            "cwd": request.cwd,
            "launch_flag": "--session-id",
            "model": request.model,
        },
        persistence_evidence={"mechanism": "deterministic_uuidv4_cli_flag"},
    )


def allocate_native_session(
    request: NativeBootstrapRequest,
    *,
    which_fn: Callable[[str], str | None] = shutil.which,
) -> NativeSessionAllocation:
    """Allocate a native provider session ID without running an LLM turn."""
    provider = request.provider.strip().lower()
    try:
        if provider == Provider.CODEX.value:
            return _allocate_codex(request, which_fn)
        if provider == Provider.AGY.value:
            return _allocate_agy(request, which_fn)
        if provider == Provider.CLAUDE.value:
            return _allocate_claude(request)
        return NativeSessionAllocation(
            provider=provider,
            status=NativeAllocationStatus.FAILED,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            error_code=ErrorCode.INVALID_INPUT,
            error_message=f"Unsupported provider for native allocation: {request.provider!r}.",
        )
    except _ProtocolFailure as exc:
        return NativeSessionAllocation(
            provider=provider,
            status=exc.status,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            notifications=exc.notifications,
            error_code=exc.error_code,
            error_message=exc.message,
        )


def provider_native_bootstrap_readiness() -> dict[str, dict[str, Any]]:
    """Return provider-by-provider readiness and remaining live qualification gates."""
    return {
        Provider.CLAUDE.value: {
            "inference_free_mechanism": "claude --session-id <UUID>",
            "safe_to_enable_now": True,
            "reason": "Direct UUIDv4 CLI flag; does not require pre-launch server allocation or bootstrap turn.",
        },
        Provider.CODEX.value: {
            "inference_free_mechanism": "codex app-server --stdio (initialize -> thread/start)",
            "safe_to_enable_now": False,
            "reason": (
                "Offline protocol implemented and qualified; live gate remaining: verify on codex-cli 0.172.0 "
                "whether `codex resume <thread_id>` attaches cleanly pre-first-turn or requires thread/resume."
            ),
        },
        Provider.AGY.value: {
            "inference_free_mechanism": "agy acp --stdio (initialize -> session/new)",
            "safe_to_enable_now": False,
            "reason": (
                "Offline protocol implemented and qualified; live gate remaining: verify on agy 1.5.18 "
                "whether `agy --conversation <sessionId>` or ACP `session/load` attaches cleanly pre-first-turn."
            ),
        },
    }
