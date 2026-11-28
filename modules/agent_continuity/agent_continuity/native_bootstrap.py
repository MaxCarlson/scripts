"""Inference-free native session allocation for LLMD-60 (Codex app-server, AGY ACP, Claude UUIDv4)."""

from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import closing, suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import ErrorCode
from .models import Provider

MAX_RPC_FRAME_BYTES = 262_144
MAX_NOTIFICATIONS = 64
MAX_INTERNAL_QUEUE_ITEMS = 256
MAX_STDERR_LINES = 32
MAX_STDERR_LINE_CHARS = 256
GRACEFUL_SHUTDOWN_WAIT_SECONDS = 0.4
MAX_PERSISTENCE_METADATA_BYTES = 65_536
MAX_CODEX_ROLLOUT_RECORDS = 32
MAX_CODEX_ROLLOUT_RECORD_BYTES = 65_536
_AGY_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_ANSI_AND_CTRL_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\x00-\x08\x0b-\x1f\x7f]")


class NativeAllocationStatus:
    """Outcome states for inference-free native session allocation."""

    ALLOCATED = "allocated"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class VerifiedLiveQualification:
    """Bound live-resume qualification tied to exact provider, version, runtime, and mechanism."""

    provider: str
    provider_version: str
    runtime_kind: str
    mechanism: str
    qualified: bool = False


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
    expected_approval_policy: str | None = None
    expected_sandbox_type: str | None = None
    requested_settings: dict[str, Any] = field(default_factory=dict)
    live_qualification: VerifiedLiveQualification | None = None
    command_override: Sequence[str] | None = None


@dataclass(frozen=True, slots=True)
class NativeSessionAllocation:
    """Structured allocation result distinguishing identity, persistence, resumability, and context."""

    provider: str
    status: str
    native_session_id: str | None
    persisted: bool
    interactively_resumable: bool
    requested_context: dict[str, Any] = field(default_factory=dict)
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
            "instruction_delivery_performed": False,
            "supports_ordered_instruction_snapshots": False,
            "workflow_init_mode": "unsupported",
            "initial_prompt_delivery": "unsupported",
        }
    )

    def __post_init__(self) -> None:
        if self.provider == Provider.CODEX.value:
            contract = {
                "requires_bootstrap_model_turn": False,
                "instruction_delivery_performed": False,
                "supports_ordered_instruction_snapshots": True,
                "workflow_init_mode": "deferred_to_guarded_interactive_attach",
                "initial_prompt_delivery": "one_time_on_guarded_interactive_attach",
            }
        elif self.provider == Provider.CLAUDE.value:
            contract = {
                "requires_bootstrap_model_turn": False,
                "instruction_delivery_performed": False,
                "supports_ordered_instruction_snapshots": False,
                "workflow_init_mode": "unsupported",
                "initial_prompt_delivery": "one_time_on_interactive_attach_mechanism_unqualified",
            }
        else:
            contract = {
                "requires_bootstrap_model_turn": False,
                "instruction_delivery_performed": False,
                "supports_ordered_instruction_snapshots": False,
                "workflow_init_mode": "unsupported",
                "initial_prompt_delivery": "unsupported",
            }
        object.__setattr__(self, "prompt_delivery_contract", contract)

    @property
    def can_authorize_interactive_resume(self) -> bool:
        """Allocated ID alone never authorizes interactive resume without persistence + bound qualification."""
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
        stderr_tail: list[str] | None = None,
        uncertain_evidence: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.message = message
        self.notifications = notifications or []
        self.stderr_tail = stderr_tail or []
        self.uncertain_evidence = uncertain_evidence or {}


def _sanitize_stderr_line(raw: str) -> str:
    cleaned = _ANSI_AND_CTRL_RE.sub("", raw.replace("\r", "")).strip()
    if len(cleaned) > MAX_STDERR_LINE_CHARS:
        return cleaned[: MAX_STDERR_LINE_CHARS - 3] + "..."
    return cleaned


def _current_runtime_kind() -> str:
    if os.name == "nt":
        return "windows"
    if platform.system().lower() == "darwin":
        return "macos"
    return "linux"


def _normalize_resolved_path(raw: str) -> str:
    p = Path(raw).resolve()
    text = str(p)
    return os.path.normcase(text) if os.name == "nt" else text


def _normalize_observed_cwd(raw: str) -> str | None:
    path = Path(raw)
    if not path.is_absolute():
        return None
    try:
        return _normalize_resolved_path(raw)
    except (OSError, RuntimeError, ValueError):
        return None


def _validate_cwd(raw_cwd: str) -> str:
    if not raw_cwd or not raw_cwd.strip():
        raise _ProtocolFailure(
            NativeAllocationStatus.FAILED,
            ErrorCode.INVALID_INPUT,
            "cwd must be a non-empty directory path.",
        )
    resolved = Path(raw_cwd).resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise _ProtocolFailure(
            NativeAllocationStatus.FAILED,
            ErrorCode.INVALID_INPUT,
            f"Resolved cwd does not exist or is not a directory: {resolved}",
        )
    return str(resolved)


def _kill_process_tree(proc: subprocess.Popen[str]) -> str:
    mode = "forced_terminate"
    if proc.poll() is None:
        if os.name != "nt":
            with suppress(OSError):
                os.killpg(proc.pid, signal.SIGTERM)
        with suppress(OSError):
            proc.terminate()
        try:
            proc.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            mode = "forced_kill"
    if os.name == "nt":
        with suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=1.5,
                check=False,
            )
    else:
        with suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    if proc.poll() is None:
        with suppress(OSError):
            proc.kill()
        with suppress(OSError, subprocess.TimeoutExpired):
            proc.wait(timeout=1.0)
    return mode


def _close_pipes(proc: subprocess.Popen[str]) -> None:
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe is not None:
            with suppress(OSError, ValueError):
                pipe.close()


class _JsonRpcStdioTransport:
    """Line-delimited JSON-RPC 2.0 stdio transport with bounded pipes, stderr drain, and clean shutdown."""

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
        self._lines: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=MAX_INTERNAL_QUEUE_ITEMS)
        self._stop_pumping = threading.Event()
        self._stderr_lines: deque[str] = deque(maxlen=MAX_STDERR_LINES)
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._next_id = 1
        self.notifications: list[dict[str, Any]] = []
        self.dropped_notifications = 0
        self._request_sent = False
        self.shutdown_mode = "not_started"
        self.helper_exit_code: int | None = None
        self.helper_shutdown_clean = False
        self._closed_cleanly = False

    def __enter__(self) -> _JsonRpcStdioTransport:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise _ProtocolFailure(
                NativeAllocationStatus.CANCELLED,
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Native session allocation cancelled before launch.",
            )
        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": self._cwd,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True
        try:
            self._proc = subprocess.Popen(self._argv, **popen_kwargs)
        except OSError as exc:
            raise _ProtocolFailure(
                NativeAllocationStatus.FAILED,
                ErrorCode.PROVIDER_UNAVAILABLE,
                f"Failed to spawn native allocation process {self._argv[0]!r}: {exc}",
            ) from exc

        def _enqueue(item: tuple[str, Any]) -> bool:
            while not self._stop_pumping.is_set():
                try:
                    self._lines.put(item, timeout=0.05)
                    return True
                except queue.Full:
                    continue
            return False

        def _pump_stdout() -> None:
            assert self._proc is not None and self._proc.stdout is not None
            try:
                while not self._stop_pumping.is_set():
                    raw = self._proc.stdout.readline(MAX_RPC_FRAME_BYTES + 1)
                    if raw == "":
                        _enqueue(("eof", None))
                        return
                    if len(raw.encode("utf-8", errors="replace")) > MAX_RPC_FRAME_BYTES and not raw.endswith("\n"):
                        _enqueue(("oversized", len(raw)))
                        return
                    if not _enqueue(("line", raw)):
                        return
            except Exception as exc:  # pragma: no cover - defensive pipe guard
                _enqueue(("err", exc))

        def _pump_stderr() -> None:
            assert self._proc is not None and self._proc.stderr is not None
            try:
                while not self._stop_pumping.is_set():
                    raw = self._proc.stderr.readline(MAX_STDERR_LINE_CHARS * 4)
                    if raw == "":
                        return
                    sanitized = _sanitize_stderr_line(raw)
                    if sanitized:
                        self._stderr_lines.append(sanitized)
            except Exception:  # pragma: no cover - defensive pipe guard
                return

        self._reader_thread = threading.Thread(target=_pump_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=_pump_stderr, daemon=True)
        self._reader_thread.start()
        self._stderr_thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._stop_pumping.set()
        if self._proc is not None:
            if not self._closed_cleanly:
                self.shutdown_mode = _kill_process_tree(self._proc)
                self.helper_exit_code = self._proc.poll()
                self.helper_shutdown_clean = False
            if self._proc.stdin is not None:
                with suppress(OSError, ValueError):
                    self._proc.stdin.close()
        for t, pipe in (
            (self._reader_thread, self._proc.stdout if self._proc is not None else None),
            (self._stderr_thread, self._proc.stderr if self._proc is not None else None),
        ):
            if t is not None and t.is_alive():
                t.join(timeout=0.15)
            # Only close TextIOWrapper if its reader thread exited; otherwise a descendant
            # holding the inherited pipe keeps readline() holding the buffer lock.
            if pipe is not None and (t is None or not t.is_alive()):
                with suppress(OSError, ValueError):
                    pipe.close()

    def _record_notification(self, msg: dict[str, Any]) -> None:
        if len(self.notifications) < MAX_NOTIFICATIONS:
            self.notifications.append(msg)
        else:
            self.dropped_notifications += 1

    def _check_cancel_and_deadline(self) -> float:
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise _ProtocolFailure(
                NativeAllocationStatus.CANCELLED,
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Native session allocation cancelled.",
                notifications=list(self.notifications),
                stderr_tail=list(self._stderr_lines),
            )
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise _ProtocolFailure(
                NativeAllocationStatus.TIMED_OUT,
                ErrorCode.PROVIDER_UNAVAILABLE,
                f"Native session allocation timed out after {self._timeout_seconds:.2f}s.",
                notifications=list(self.notifications),
                stderr_tail=list(self._stderr_lines),
            )
        return remaining

    def _write_line_bounded(self, payload: str, *, context_label: str) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        write_done = threading.Event()
        write_err: list[BaseException] = []

        def _do_write() -> None:
            assert self._proc is not None and self._proc.stdin is not None
            try:
                self._proc.stdin.write(payload)
                self._proc.stdin.flush()
            except BaseException as exc:  # pragma: no cover - pipe error guard
                write_err.append(exc)
            finally:
                write_done.set()

        writer = threading.Thread(target=_do_write, daemon=True)
        writer.start()
        while not write_done.wait(timeout=0.05):
            self._check_cancel_and_deadline()
        if write_err:
            status = NativeAllocationStatus.UNCERTAIN if self._request_sent else NativeAllocationStatus.FAILED
            raise _ProtocolFailure(
                status,
                ErrorCode.PROVIDER_UNAVAILABLE,
                f"Failed writing JSON-RPC {context_label}: {write_err[0]}",
                notifications=list(self.notifications),
                stderr_tail=list(self._stderr_lines),
            )

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC 2.0 notification (no id)."""
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._check_cancel_and_deadline()
        self._write_line_bounded(json.dumps(msg) + "\n", context_label=f"notification {method!r}")

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}) + "\n"
        self._check_cancel_and_deadline()
        self._request_sent = True
        self._write_line_bounded(payload, context_label=f"request {method!r}")

        while True:
            remaining = self._check_cancel_and_deadline()
            try:
                kind, value = self._lines.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue

            if kind == "oversized":
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"Oversized JSON-RPC frame (>{MAX_RPC_FRAME_BYTES} bytes) during {method!r}.",
                    notifications=list(self.notifications),
                    stderr_tail=list(self._stderr_lines),
                )
            if kind == "err":
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    f"Stdout read error during {method!r}: {value}",
                    notifications=list(self.notifications),
                    stderr_tail=list(self._stderr_lines),
                )
            if kind == "eof":
                assert self._proc is not None
                rc = self._proc.poll()
                tail = list(self._stderr_lines)
                detail = f"exit={rc}" + (f" ({tail[-1]})" if tail else "")
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    f"Provider closed stdout before responding to {method!r} ({detail}).",
                    notifications=list(self.notifications),
                    stderr_tail=tail,
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
                    stderr_tail=list(self._stderr_lines),
                ) from exc

            if not isinstance(msg, dict):
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"Non-object JSON-RPC frame during {method!r}.",
                    notifications=list(self.notifications),
                    stderr_tail=list(self._stderr_lines),
                )

            if "id" not in msg or msg["id"] is None:
                if "method" in msg:
                    self._record_notification(msg)
                    continue
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"Invalid JSON-RPC frame missing both id and method during {method!r}.",
                    notifications=list(self.notifications),
                    stderr_tail=list(self._stderr_lines),
                )

            if msg["id"] != req_id:
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"Mismatched JSON-RPC response id {msg['id']!r} (expected {req_id!r}) for {method!r}.",
                    notifications=list(self.notifications),
                    stderr_tail=list(self._stderr_lines),
                )

            if "error" in msg and msg["error"] is not None:
                err_obj = msg["error"]
                err_msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
                raise _ProtocolFailure(
                    NativeAllocationStatus.FAILED,
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    f"JSON-RPC error from {method!r}: {err_msg}",
                    notifications=list(self.notifications),
                    stderr_tail=list(self._stderr_lines),
                )

            result = msg.get("result")
            if not isinstance(result, dict):
                raise _ProtocolFailure(
                    NativeAllocationStatus.UNCERTAIN,
                    ErrorCode.HOOK_SCHEMA_MISMATCH,
                    f"JSON-RPC result for {method!r} must be an object.",
                    notifications=list(self.notifications),
                    stderr_tail=list(self._stderr_lines),
                )
            return result

    def close_gracefully(self) -> None:
        """Close stdin and wait briefly for clean helper exit/flush before forcing termination."""
        if self._proc is None:
            return
        if self._proc.stdin is not None:
            with suppress(OSError, ValueError):
                self._proc.stdin.close()
        wait_budget = min(GRACEFUL_SHUTDOWN_WAIT_SECONDS, max(0.05, self._deadline - time.monotonic()))
        try:
            rc = self._proc.wait(timeout=wait_budget)
            self.shutdown_mode = "graceful_eof"
            self.helper_exit_code = rc
            self.helper_shutdown_clean = rc == 0
        except subprocess.TimeoutExpired:
            self.shutdown_mode = _kill_process_tree(self._proc)
            self.helper_exit_code = self._proc.poll()
            self.helper_shutdown_clean = False
        self._closed_cleanly = True


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


def _effective_executable(argv: Sequence[str], which_fn: Callable[[str], str | None]) -> str | None:
    if not argv or not argv[0]:
        return None
    path = which_fn(argv[0]) or argv[0]
    try:
        return str(Path(path).resolve())
    except (OSError, RuntimeError, ValueError):
        return path


def _expected_executable(
    request: NativeBootstrapRequest,
    provider: str,
    which_fn: Callable[[str], str | None],
) -> str:
    expected = request.executable
    if not expected and request.command_override:
        expected = request.command_override[0]
    if not expected:
        expected = provider
    try:
        return str(Path(expected_path).resolve()) if (expected_path := which_fn(expected)) else expected
    except (OSError, RuntimeError, ValueError):
        return expected


def _evidence_status(expected: Any, effective: Any) -> str:
    if expected is None:
        return "not_requested" if effective is not None else "unavailable"
    if effective is None:
        return "missing"
    return "verified" if expected == effective else "mismatch"


def _verify_codex_persistence(
    thread_id: str,
    thread_path: str | None,
    codex_home: Path | None,
    expected_cwd: str,
) -> tuple[bool, dict[str, Any]]:
    evidence: dict[str, Any] = {
        "thread_path": thread_path,
        "rollout_path_valid": False,
        "rollout_exists": False,
        "rollout_id_verified": False,
        "rollout_cwd_status": "missing",
        "state_db_row": False,
        "state_db_cwd_verified": False,
        "state_db_cwd_status": "missing",
        "effective_cwd_status": "missing",
    }
    if thread_path and codex_home is not None:
        try:
            sessions_root = (codex_home / "sessions").resolve(strict=True)
            untrusted_path = Path(thread_path)
            p = untrusted_path.resolve(strict=True) if untrusted_path.is_absolute() else None
            if (
                p is not None
                and p.is_file()
                and p.suffix.lower() == ".jsonl"
                and p.name.startswith("rollout-")
                and p.is_relative_to(sessions_root)
                and p.stat().st_size > 0
            ):
                evidence["rollout_path_valid"] = True
                evidence["rollout_exists"] = True
                session_meta_ids: set[str] = set()
                rollout_cwds: set[str] = set()
                invalid_cwd = False
                with p.open("rb") as fh:
                    for _record_number in range(MAX_CODEX_ROLLOUT_RECORDS):
                        line = fh.readline(MAX_CODEX_ROLLOUT_RECORD_BYTES + 1)
                        if not line:
                            break
                        if len(line) > MAX_CODEX_ROLLOUT_RECORD_BYTES:
                            evidence["rollout_metadata_truncated"] = True
                            break
                        try:
                            rec = json.loads(line.decode("utf-8", errors="strict"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            evidence["rollout_metadata_invalid"] = True
                            break
                        if not isinstance(rec, dict) or rec.get("type") != "session_meta":
                            continue
                        payload = rec.get("payload")
                        if not isinstance(payload, dict):
                            evidence["rollout_metadata_invalid"] = True
                            break
                        rec_id = payload.get("id")
                        if isinstance(rec_id, str) and rec_id:
                            session_meta_ids.add(rec_id)
                        else:
                            evidence["rollout_metadata_invalid"] = True
                        if "cwd" in payload:
                            cwd = payload.get("cwd")
                            if isinstance(cwd, str) and cwd.strip():
                                normalized_cwd = _normalize_observed_cwd(cwd)
                                if normalized_cwd is None:
                                    invalid_cwd = True
                                else:
                                    rollout_cwds.add(normalized_cwd)
                            else:
                                invalid_cwd = True
                    else:
                        if fh.read(1):
                            evidence["rollout_metadata_truncated"] = True
                evidence["rollout_id_verified"] = (
                    session_meta_ids == {thread_id} and not evidence.get("rollout_metadata_invalid")
                )
                if len(session_meta_ids) > 1 or (session_meta_ids and thread_id not in session_meta_ids):
                    evidence["rollout_identity_conflict"] = True
                if invalid_cwd or len(rollout_cwds) > 1:
                    evidence["rollout_cwd_status"] = "mismatch"
                elif rollout_cwds:
                    evidence["rollout_cwd_status"] = (
                        "verified" if rollout_cwds == {_normalize_resolved_path(expected_cwd)} else "mismatch"
                    )
        except (OSError, RuntimeError, ValueError):
            evidence["rollout_path_valid"] = False
    if codex_home is not None:
        state_db = codex_home / "state_5.sqlite"
        if state_db.is_file():
            with suppress(sqlite3.Error), closing(
                sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=1.0)
            ) as conn:
                cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(threads)").fetchall()}
                if "id" in cols:
                    if "cwd" in cols:
                        row = conn.execute("SELECT id, cwd FROM threads WHERE id = ?", (thread_id,)).fetchone()
                        if row is not None:
                            evidence["state_db_row"] = True
                            db_cwd = str(row[1] or "").strip()
                            if db_cwd:
                                normalized_db_cwd = _normalize_observed_cwd(db_cwd)
                                evidence["state_db_cwd_status"] = (
                                    "verified"
                                    if normalized_db_cwd == _normalize_observed_cwd(expected_cwd)
                                    and normalized_db_cwd is not None
                                    else "mismatch"
                                )
                                evidence["state_db_cwd_verified"] = evidence["state_db_cwd_status"] == "verified"
                    else:
                        row = conn.execute("SELECT id FROM threads WHERE id = ?", (thread_id,)).fetchone()
                        if row is not None:
                            evidence["state_db_row"] = True
    cwd_statuses = [evidence["rollout_cwd_status"], evidence["state_db_cwd_status"]]
    if "mismatch" in cwd_statuses:
        evidence["effective_cwd_status"] = "mismatch"
    elif "verified" in cwd_statuses:
        evidence["effective_cwd_status"] = "verified"
    identity_verified = evidence["rollout_id_verified"] or evidence["state_db_row"]
    evidence["identity_verified"] = bool(identity_verified)
    persisted = bool(
        identity_verified
        and evidence["effective_cwd_status"] != "mismatch"
        and not (evidence["rollout_path_valid"] and evidence.get("rollout_metadata_invalid"))
        and not evidence.get("rollout_metadata_truncated")
    )
    return persisted, evidence


def _verify_agy_persistence(
    session_id: str,
    agy_home: Path | None,
) -> tuple[bool, dict[str, Any]]:
    evidence: dict[str, Any] = {
        "agy_home": str(agy_home) if agy_home else None,
        "session_id_valid": bool(_AGY_SESSION_ID_RE.fullmatch(session_id)) and session_id not in {".", ".."},
        "conversation_dir_exists": False,
        "metadata_id_verified": False,
        "metadata_path_valid": False,
        "transcript_jsonl_valid": False,
        "effective_workspace_source": "unavailable_in_verified_transcript_contract",
        "effective_cwd_status": "missing",
    }
    if agy_home is None or not evidence["session_id_valid"]:
        return False, evidence
    try:
        home = agy_home.resolve(strict=True)
        brain_dir = (home / "brain").resolve(strict=True)
        conv_dir = (brain_dir / session_id).resolve(strict=True)
        if not brain_dir.is_relative_to(home) or not conv_dir.is_relative_to(brain_dir) or conv_dir.name != session_id:
            evidence["metadata_path_valid"] = False
            return False, evidence
        if not conv_dir.is_dir():
            return False, evidence
        evidence["conversation_dir_exists"] = True
        # Antigravity documents this exact CLI transcript location; the transcript body has no
        # documented workspace metadata schema, so it is identity/path evidence only.
        transcript = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
        resolved_transcript = transcript.resolve(strict=True)
        if not resolved_transcript.is_file() or not resolved_transcript.is_relative_to(conv_dir):
            evidence["metadata_path_valid"] = False
            return False, evidence
        evidence["metadata_path_valid"] = True
        evidence["metadata_path"] = str(resolved_transcript)
        if resolved_transcript.stat().st_size > MAX_PERSISTENCE_METADATA_BYTES:
            evidence["metadata_oversized"] = True
            return False, evidence
        with resolved_transcript.open("rb") as fh:
            raw = fh.read(MAX_PERSISTENCE_METADATA_BYTES + 1)
        if len(raw) > MAX_PERSISTENCE_METADATA_BYTES:
            evidence["metadata_oversized"] = True
            return False, evidence
        lines = [line for line in raw.splitlines() if line.strip()]
        if not lines:
            evidence["metadata_invalid"] = True
            return False, evidence
        try:
            for line in lines:
                record = json.loads(line.decode("utf-8", errors="strict"))
                if not isinstance(record, dict):
                    raise ValueError("transcript record is not an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            evidence["metadata_invalid"] = True
            return False, evidence
        evidence["transcript_jsonl_valid"] = True
        # ACP sessionId and exact provider-store path establish identity; the official transcript
        # contract does not define a persisted workspace field, so cwd remains unknown.
        evidence["metadata_id_verified"] = True
        evidence["identity_evidence_source"] = "acp_session_id_at_exact_provider_transcript_path"
    except (OSError, RuntimeError, ValueError):
        evidence["metadata_path_valid"] = False
        return False, evidence
    persisted = bool(
        evidence["metadata_id_verified"]
        and evidence.get("metadata_path_valid") is True
        and evidence["transcript_jsonl_valid"]
    )
    return persisted, evidence


def _is_live_resume_authorized(
    *,
    provider: str,
    provider_version: str | None,
    mechanism: str,
    persisted: bool,
    qualification: VerifiedLiveQualification | None,
) -> bool:
    if not persisted or qualification is None or not qualification.qualified:
        return False
    return (
        qualification.provider == provider
        and qualification.mechanism == mechanism
        and qualification.runtime_kind == _current_runtime_kind()
        and bool(provider_version)
        and qualification.provider_version == provider_version
    )


def _detect_installed_version(executable: str, *, timeout_seconds: float = 2.0) -> str | None:
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    return out.splitlines()[0].strip() if out else None


def _validate_codex_context(
    request: NativeBootstrapRequest,
    resolved_cwd: str,
    start_result: dict[str, Any],
) -> dict[str, Any]:
    reported_cwd = start_result.get("cwd")
    if isinstance(reported_cwd, str) and reported_cwd.strip() and (
        _normalize_resolved_path(reported_cwd) != _normalize_resolved_path(resolved_cwd)
    ):
        raise _ProtocolFailure(
            NativeAllocationStatus.FAILED,
            ErrorCode.ASSOCIATION_CONFLICT,
            f"Codex thread/start returned mismatched cwd {reported_cwd!r} (expected {resolved_cwd!r}).",
        )
    approval_policy = start_result.get("approvalPolicy")
    if request.expected_approval_policy is not None and approval_policy != request.expected_approval_policy:
        raise _ProtocolFailure(
            NativeAllocationStatus.FAILED,
            ErrorCode.ASSOCIATION_CONFLICT,
            f"Codex approvalPolicy {approval_policy!r} does not match expected {request.expected_approval_policy!r}.",
        )
    sandbox = start_result.get("sandbox")
    sandbox_type = sandbox.get("type") if isinstance(sandbox, dict) else None
    if request.expected_sandbox_type is not None and sandbox_type != request.expected_sandbox_type:
        raise _ProtocolFailure(
            NativeAllocationStatus.FAILED,
            ErrorCode.ASSOCIATION_CONFLICT,
            f"Codex sandbox {sandbox_type!r} does not match expected {request.expected_sandbox_type!r}.",
        )
    effective_cwd = str(reported_cwd) if isinstance(reported_cwd, str) and reported_cwd.strip() else None
    model = start_result.get("model")
    if request.model is not None and model != request.model:
        raise _ProtocolFailure(
            NativeAllocationStatus.FAILED,
            ErrorCode.ASSOCIATION_CONFLICT,
            f"Codex effective model {model!r} does not match requested model {request.model!r}.",
        )
    return {
        "cwd": effective_cwd,
        "workspace_status": _evidence_status(resolved_cwd, effective_cwd),
        "model": start_result.get("model"),
        "model_status": _evidence_status(request.model, model),
        "model_provider": start_result.get("modelProvider"),
        "approval_policy": approval_policy,
        "sandbox": sandbox,
        "permission_evidence": {
            "approval_policy": {
                "requested": request.expected_approval_policy,
                "effective": approval_policy,
                "status": _evidence_status(request.expected_approval_policy, approval_policy),
            },
            "sandbox_type": {
                "requested": request.expected_sandbox_type,
                "effective": sandbox_type,
                "status": _evidence_status(request.expected_sandbox_type, sandbox_type),
            },
        },
    }


def _allocate_codex(
    request: NativeBootstrapRequest,
    resolved_cwd: str,
    which_fn: Callable[[str], str | None],
) -> NativeSessionAllocation:
    argv = (
        list(request.command_override)
        if request.command_override
        else [_resolve_executable("codex", request.executable, which_fn), "app-server", "--stdio"]
    )
    effective_executable = _effective_executable(argv, which_fn)
    expected_executable = _expected_executable(request, Provider.CODEX.value, which_fn)
    with _JsonRpcStdioTransport(
        argv,
        cwd=resolved_cwd,
        timeout_seconds=request.timeout_seconds,
        cancel_event=request.cancel_event,
    ) as rpc:
        init_result = rpc.call(
            "initialize",
            {"clientInfo": {"name": "agent_continuity", "version": "2.3.0"}},
        )
        rpc.notify("initialized")
        start_params: dict[str, Any] = {"cwd": resolved_cwd, "ephemeral": False}
        if request.model:
            start_params["model"] = request.model
        if request.expected_approval_policy is not None:
            start_params["approvalPolicy"] = request.expected_approval_policy
        if request.expected_sandbox_type is not None:
            start_params["sandbox"] = {"type": request.expected_sandbox_type}
        start_result = rpc.call("thread/start", start_params)
        rpc.close_gracefully()
        notifications = list(rpc.notifications)
        shutdown_info = {
            "shutdown_mode": rpc.shutdown_mode,
            "helper_exit_code": rpc.helper_exit_code,
            "helper_shutdown_clean": rpc.helper_shutdown_clean,
            "dropped_notifications": rpc.dropped_notifications,
            "stderr_tail": list(rpc._stderr_lines),
        }

    thread = start_result.get("thread")
    if not isinstance(thread, dict):
        return NativeSessionAllocation(
            provider=Provider.CODEX.value,
            status=NativeAllocationStatus.UNCERTAIN,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            persistence_evidence=shutdown_info,
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
            persistence_evidence=shutdown_info,
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
            persistence_evidence=shutdown_info,
            notifications=notifications,
            raw_result=start_result,
            error_code=ErrorCode.ASSOCIATION_CONFLICT,
            error_message="Codex thread/start returned conflicting ephemeral=True for non-ephemeral request.",
        )

    context = _validate_codex_context(request, resolved_cwd, start_result)
    user_agent = init_result.get("userAgent") if isinstance(init_result.get("userAgent"), str) else None
    thread_path = thread.get("path") if isinstance(thread.get("path"), str) else None
    context["user_agent"] = user_agent
    context["thread_path"] = thread_path
    expected_version = request.live_qualification.provider_version if request.live_qualification else None
    context.update(
        {
            "runtime_kind": _current_runtime_kind(),
            "runtime_status": "verified",
            "executable": effective_executable,
            "requested_executable": expected_executable,
            "executable_status": _evidence_status(expected_executable, effective_executable),
            "provider_version": user_agent,
            "requested_provider_version": expected_version,
            "provider_version_status": _evidence_status(expected_version, user_agent),
        }
    )

    requested_context = {
        "cwd": resolved_cwd,
        "model": request.model,
        "runtime_kind": _current_runtime_kind(),
        "executable": expected_executable,
        "provider_version": expected_version,
        "expected_approval_policy": request.expected_approval_policy,
        "expected_sandbox_type": request.expected_sandbox_type,
    }
    if not rpc.helper_shutdown_clean:
        return NativeSessionAllocation(
            provider=Provider.CODEX.value,
            status=NativeAllocationStatus.UNCERTAIN,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            requested_context=requested_context,
            effective_provider_context=context,
            persistence_evidence={**shutdown_info, "uncertain_native_session_id": thread_id},
            notifications=notifications,
            raw_result=start_result,
            error_code=ErrorCode.PROVIDER_UNAVAILABLE,
            error_message=(
                f"Codex app-server exited uncleanly during shutdown "
                f"(mode={rpc.shutdown_mode}, exit={rpc.helper_exit_code})."
            ),
        )

    persisted, evidence = _verify_codex_persistence(thread_id, thread_path, request.codex_home, resolved_cwd)
    evidence.update(shutdown_info)
    if context["workspace_status"] == "missing" and evidence["effective_cwd_status"] == "verified":
        context["cwd"] = resolved_cwd
        context["workspace_status"] = "verified"
        context["workspace_evidence_source"] = (
            "codex_rollout_session_meta"
            if evidence["rollout_cwd_status"] == "verified"
            else "codex_state_db"
        )
    elif context["workspace_status"] == "missing":
        context["workspace_evidence_source"] = "unavailable"
    evidence["effective_workspace_verified"] = context["workspace_status"] == "verified"
    resumable = _is_live_resume_authorized(
        provider=Provider.CODEX.value,
        provider_version=user_agent,
        mechanism="codex app-server --stdio",
        persisted=persisted,
        qualification=request.live_qualification,
    ) and context["workspace_status"] == "verified" and context["executable_status"] == "verified"
    return NativeSessionAllocation(
        provider=Provider.CODEX.value,
        status=NativeAllocationStatus.ALLOCATED,
        native_session_id=thread_id,
        persisted=persisted,
        interactively_resumable=resumable,
        requested_context=requested_context,
        effective_provider_context=context,
        persistence_evidence=evidence,
        notifications=notifications,
        raw_result=start_result,
    )


def _allocate_agy(
    request: NativeBootstrapRequest,
    resolved_cwd: str,
    which_fn: Callable[[str], str | None],
) -> NativeSessionAllocation:
    detected_version: str | None = None
    if request.command_override:
        argv = list(request.command_override)
    else:
        exe = _resolve_executable("agy", request.executable, which_fn)
        detected_version = _detect_installed_version(exe)
        argv = [exe, "acp", "--stdio"]
    effective_executable = _effective_executable(argv, which_fn)
    expected_executable = _expected_executable(request, Provider.AGY.value, which_fn)
    with _JsonRpcStdioTransport(
        argv,
        cwd=resolved_cwd,
        timeout_seconds=request.timeout_seconds,
        cancel_event=request.cancel_event,
    ) as rpc:
        init_result = rpc.call("initialize", {"protocolVersion": 1})
        proto_ver = init_result.get("protocolVersion")
        if proto_ver is not None and (isinstance(proto_ver, bool) or not isinstance(proto_ver, int) or proto_ver < 1):
            raise _ProtocolFailure(
                NativeAllocationStatus.FAILED,
                ErrorCode.PROVIDER_VERSION_UNSUPPORTED,
                f"Unsupported AGY ACP protocolVersion: {proto_ver!r}.",
                notifications=list(rpc.notifications),
            )
        agent_info = init_result.get("agentInfo")
        if detected_version is None and isinstance(agent_info, dict):
            raw_ver = agent_info.get("version")
            if isinstance(raw_ver, str) and raw_ver.strip():
                detected_version = raw_ver.strip()
        session_result = rpc.call(
            "session/new",
            {"cwd": resolved_cwd, "mcpServers": list(request.mcp_servers)},
        )
        rpc.close_gracefully()
        notifications = list(rpc.notifications)
        shutdown_info = {
            "shutdown_mode": rpc.shutdown_mode,
            "helper_exit_code": rpc.helper_exit_code,
            "helper_shutdown_clean": rpc.helper_shutdown_clean,
            "dropped_notifications": rpc.dropped_notifications,
            "stderr_tail": list(rpc._stderr_lines),
        }

    session_id = session_result.get("sessionId")
    if not isinstance(session_id, str) or not session_id.strip():
        return NativeSessionAllocation(
            provider=Provider.AGY.value,
            status=NativeAllocationStatus.UNCERTAIN,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            persistence_evidence=shutdown_info,
            notifications=notifications,
            raw_result=session_result,
            error_code=ErrorCode.HOOK_SCHEMA_MISMATCH,
            error_message="AGY ACP session/new response missing non-empty 'sessionId'.",
        )

    if not _AGY_SESSION_ID_RE.fullmatch(session_id) or session_id in {".", ".."}:
        return NativeSessionAllocation(
            provider=Provider.AGY.value,
            status=NativeAllocationStatus.UNCERTAIN,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            persistence_evidence={**shutdown_info, "invalid_native_session_id": True},
            notifications=notifications,
            raw_result={},
            error_code=ErrorCode.HOOK_SCHEMA_MISMATCH,
            error_message="AGY ACP session/new returned an invalid native session identifier; recovery is required.",
        )

    expected_version = request.live_qualification.provider_version if request.live_qualification else None
    requested_context = {
        "cwd": resolved_cwd,
        "runtime_kind": _current_runtime_kind(),
        "executable": expected_executable,
        "provider_version": expected_version,
        "mcp_server_count": len(request.mcp_servers),
    }
    context = {
        "cwd": None,
        "requested_cwd": resolved_cwd,
        "workspace_status": "missing",
        "protocol_version": proto_ver if proto_ver is not None else 1,
        "provider_version": detected_version,
        "requested_provider_version": expected_version,
        "provider_version_status": _evidence_status(expected_version, detected_version),
        "runtime_kind": _current_runtime_kind(),
        "runtime_status": "verified",
        "executable": effective_executable,
        "requested_executable": expected_executable,
        "executable_status": _evidence_status(expected_executable, effective_executable),
        "permission_evidence": {"status": "unavailable_from_acp_session_new"},
    }
    if not rpc.helper_shutdown_clean:
        return NativeSessionAllocation(
            provider=Provider.AGY.value,
            status=NativeAllocationStatus.UNCERTAIN,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            requested_context=requested_context,
            effective_provider_context=context,
            persistence_evidence={**shutdown_info, "uncertain_native_session_id": session_id},
            notifications=notifications,
            raw_result=session_result,
            error_code=ErrorCode.PROVIDER_UNAVAILABLE,
            error_message=(
                f"AGY ACP exited uncleanly during shutdown "
                f"(mode={rpc.shutdown_mode}, exit={rpc.helper_exit_code})."
            ),
        )

    persisted, evidence = _verify_agy_persistence(session_id, request.agy_home)
    evidence.update(shutdown_info)
    if evidence["effective_cwd_status"] == "verified":
        context["cwd"] = resolved_cwd
        context["workspace_status"] = "verified"
        context["workspace_evidence_source"] = "agy_session_metadata"
    else:
        context["workspace_evidence_source"] = "not_available_from_verified_provider_metadata"
    evidence["effective_workspace_verified"] = context["workspace_status"] == "verified"
    resumable = _is_live_resume_authorized(
        provider=Provider.AGY.value,
        provider_version=detected_version,
        mechanism="agy acp --stdio",
        persisted=persisted,
        qualification=request.live_qualification,
    ) and context["workspace_status"] == "verified" and context["executable_status"] == "verified"
    return NativeSessionAllocation(
        provider=Provider.AGY.value,
        status=NativeAllocationStatus.ALLOCATED,
        native_session_id=session_id,
        persisted=persisted,
        interactively_resumable=resumable,
        requested_context=requested_context,
        effective_provider_context=context,
        persistence_evidence=evidence,
        notifications=notifications,
        raw_result=session_result,
    )


def _allocate_claude(request: NativeBootstrapRequest, resolved_cwd: str) -> NativeSessionAllocation:
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
        requested_context={
            "cwd": resolved_cwd,
            "runtime_kind": _current_runtime_kind(),
            "model": request.model,
        },
        effective_provider_context={
            "cwd": None,
            "workspace_status": "not_observed_provider_not_started",
            "runtime_kind": None,
            "runtime_status": "not_observed_provider_not_started",
            "executable": None,
            "provider_version": None,
            "launch_flag": "--session-id",
            "model": request.model,
        },
        persistence_evidence={
            "mechanism": "deterministic_uuidv4_cli_flag",
            "identity_verified": False,
            "effective_workspace_verified": False,
            "provider_process_started": False,
        },
    )


def allocate_native_session(
    request: NativeBootstrapRequest,
    *,
    which_fn: Callable[[str], str | None] = shutil.which,
) -> NativeSessionAllocation:
    """Allocate a native provider session ID without running an LLM turn."""
    provider = request.provider.strip().lower()
    try:
        resolved_cwd = _validate_cwd(request.cwd)
        if provider == Provider.CODEX.value:
            unsupported = set(request.requested_settings) - {"model", "approval_policy", "sandbox"}
            if unsupported:
                return NativeSessionAllocation(
                    provider=provider,
                    status=NativeAllocationStatus.FAILED,
                    native_session_id=None,
                    persisted=False,
                    interactively_resumable=False,
                    requested_context={"unsupported_settings": sorted(unsupported)},
                    error_code=ErrorCode.RESUME_UNSUPPORTED,
                    error_message=(
                        "Native Codex allocation cannot verify requested settings: "
                        + ", ".join(sorted(unsupported))
                        + ". No provider process was started."
                    ),
                )
            if "model" in request.requested_settings and request.requested_settings["model"] != request.model:
                return NativeSessionAllocation(
                    provider=provider,
                    status=NativeAllocationStatus.FAILED,
                    native_session_id=None,
                    persisted=False,
                    interactively_resumable=False,
                    error_code=ErrorCode.INVALID_INPUT,
                    error_message=(
                        "Native Codex model request disagrees with requested settings; "
                        "no provider process was started."
                    ),
                )
            if request.requested_settings.get("approval_policy", request.expected_approval_policy) != request.expected_approval_policy:
                return NativeSessionAllocation(
                    provider=provider,
                    status=NativeAllocationStatus.FAILED,
                    native_session_id=None,
                    persisted=False,
                    interactively_resumable=False,
                    error_code=ErrorCode.INVALID_INPUT,
                    error_message=(
                        "Native Codex approval policy disagrees with requested settings; "
                        "no provider process was started."
                    ),
                )
            requested_sandbox = request.requested_settings.get("sandbox")
            if (
                requested_sandbox is not None
                and requested_sandbox not in {
                    "workspace-write", "read-only", "danger-full-access", "workspaceWrite", "readOnly", "dangerFullAccess",
                }
            ) or (
                request.expected_sandbox_type is not None
                and request.expected_sandbox_type not in {"workspaceWrite", "readOnly", "dangerFullAccess"}
            ):
                return NativeSessionAllocation(
                    provider=provider,
                    status=NativeAllocationStatus.FAILED,
                    native_session_id=None,
                    persisted=False,
                    interactively_resumable=False,
                    error_code=ErrorCode.INVALID_INPUT,
                    error_message=(
                        "Native Codex sandbox request is not a verified sandbox mapping; "
                        "no provider process was started."
                    ),
                )
        elif provider == Provider.AGY.value and request.requested_settings:
            return NativeSessionAllocation(
                provider=provider,
                status=NativeAllocationStatus.FAILED,
                native_session_id=None,
                persisted=False,
                interactively_resumable=False,
                requested_context={"unsupported_settings": sorted(request.requested_settings)},
                error_code=ErrorCode.RESUME_UNSUPPORTED,
                error_message=(
                    "AGY ACP session/new has no qualified mapping for requested launch settings: "
                    + ", ".join(sorted(request.requested_settings))
                    + ". No provider process was started."
                ),
            )
        if provider == Provider.CODEX.value:
            return _allocate_codex(request, resolved_cwd, which_fn)
        if provider == Provider.AGY.value:
            return _allocate_agy(request, resolved_cwd, which_fn)
        if provider == Provider.CLAUDE.value:
            return _allocate_claude(request, resolved_cwd)
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
        evidence = dict(exc.uncertain_evidence)
        if exc.stderr_tail:
            evidence["stderr_tail"] = exc.stderr_tail
        return NativeSessionAllocation(
            provider=provider,
            status=exc.status,
            native_session_id=None,
            persisted=False,
            interactively_resumable=False,
            persistence_evidence=evidence,
            notifications=exc.notifications,
            error_code=exc.error_code,
            error_message=exc.message,
        )


def provider_native_bootstrap_readiness() -> dict[str, dict[str, Any]]:
    """Return provider-by-provider readiness bound to verified versions, runtime, and mechanisms."""
    runtime = _current_runtime_kind()
    return {
        Provider.CLAUDE.value: {
            "verified_version": "claude 2.1.332",
            "runtime_kind": runtime,
            "mechanism": "claude --session-id <UUID>",
            "safe_to_enable_now": False,
            "reason": (
                "UUIDv4 reservation is deterministic and inference-free, but native allocation does not start the "
                "provider or prove persisted transcript identity, effective cwd, prompt delivery, or exact resume."
            ),
        },
        Provider.CODEX.value: {
            "verified_version": "codex-cli 0.172.0",
            "runtime_kind": runtime,
            "mechanism": "codex app-server --stdio (initialize -> initialized -> thread/start)",
            "safe_to_enable_now": False,
            "reason": (
                "Offline protocol is guarded-tested, not live-qualified; require exact in-store session_meta/state "
                "identity and matching persisted cwd, then verify executable/version, runtime, requested permissions, "
                "and exact pre-first-turn `codex resume <thread_id>`."
            ),
        },
        Provider.AGY.value: {
            "verified_version": "agy 1.5.18",
            "runtime_kind": runtime,
            "mechanism": "agy acp --stdio (initialize -> session/new)",
            "safe_to_enable_now": False,
            "reason": (
                "Offline ACP protocol is guarded-tested, not live-qualified; exact transcript identity can be "
                "checked under the CLI store, but the documented transcript contract does not expose a verified "
                "workspace field. Keep attach disabled until an isolated authenticated store and effective cwd, "
                "permissions, executable/version, runtime, and exact resume can be proven."
            ),
        },
    }
