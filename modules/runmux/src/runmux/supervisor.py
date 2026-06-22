"""Detached supervisor process used by runmux."""

from __future__ import annotations

import argparse
import errno
import json
import os
import selectors
import signal
import socketserver
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from runmux.constants import (
    DEFAULT_LEASE_TIMEOUT_SECONDS,
    DEFAULT_LOCK_IDLE_TRANSFER_SECONDS,
    DEFAULT_LOCK_MINIMUM_TENURE_SECONDS,
    STATUS_FAILED,
    STATUS_FINISHED,
    STATUS_KILLED,
    STATUS_PAUSED,
)
from runmux.history import record_run_finished
from runmux.ipc import encode_request
from runmux.models import RunRecord
from runmux.store import RunStore

if sys.platform != "win32":
    import fcntl
    import pty
    import termios


@dataclass
class AttachmentSession:
    """Supervisor-local state for one attached client."""

    session_id: str
    mode: str
    connected_at: float
    last_heartbeat: float


class InputLockCoordinator:
    """Coordinate FIFO ownership of managed-program input."""

    def __init__(
        self,
        *,
        minimum_tenure_seconds: float = DEFAULT_LOCK_MINIMUM_TENURE_SECONDS,
        idle_transfer_seconds: float = DEFAULT_LOCK_IDLE_TRANSFER_SECONDS,
    ) -> None:
        self.minimum_tenure_seconds = minimum_tenure_seconds
        self.idle_transfer_seconds = idle_transfer_seconds
        self.holder_id: str | None = None
        self.holder_since = 0.0
        self.last_input_at = 0.0
        self.queue: deque[str] = deque()

    def add_interactor(self, session_id: str, *, now: float) -> None:
        """Give the first interactor initial ownership."""

        if self.holder_id is None:
            self.holder_id = session_id
            self.holder_since = now
            self.last_input_at = now

    def request(self, session_id: str, *, now: float) -> None:
        """Queue an ownership request once."""

        if session_id == self.holder_id or session_id in self.queue:
            return
        self.queue.append(session_id)
        self.maybe_transfer(now=now)

    def remove(self, session_id: str, *, now: float) -> None:
        """Remove a disconnected session and hand off if it held ownership."""

        self.queue = deque(item for item in self.queue if item != session_id)
        if self.holder_id == session_id:
            self.holder_id = None
            self._assign_next(now=now)

    def note_input_complete(self, session_id: str, *, now: float) -> None:
        """Record completion of an accepted holder input write."""

        if session_id == self.holder_id:
            self.last_input_at = now

    def maybe_transfer(self, *, now: float) -> bool:
        """Transfer ownership when tenure and input-idle requirements are met."""

        if self.holder_id is None:
            return self._assign_next(now=now)
        if not self.queue:
            return False
        tenure_elapsed = now - self.holder_since >= self.minimum_tenure_seconds
        idle_elapsed = now - self.last_input_at >= self.idle_transfer_seconds
        if not tenure_elapsed or not idle_elapsed:
            return False
        self.holder_id = None
        return self._assign_next(now=now)

    def queue_position(self, session_id: str) -> int | None:
        """Return a one-based FIFO queue position."""

        try:
            return list(self.queue).index(session_id) + 1
        except ValueError:
            return None

    def _assign_next(self, *, now: float) -> bool:
        if not self.queue:
            return False
        self.holder_id = self.queue.popleft()
        self.holder_since = now
        self.last_input_at = now
        return True


class SupervisorState:
    """Mutable state shared by the supervisor and IPC handlers."""

    def __init__(self, *, store: RunStore, record: RunRecord) -> None:
        self.store = store
        self.record = record
        self.process: Any | None = None
        self.windows_pty = False
        self.master_fd: int | None = None
        self.log_file = Path(record.log_path)
        self.stop_requested = threading.Event()
        self.io_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.sessions: dict[str, AttachmentSession] = {}
        self.session_lock = threading.RLock()
        self.input_lock = InputLockCoordinator()
        self.attachment_event_sequence = 0
        self.latest_attachment_event: dict[str, Any] | None = None

    def refresh_record(self) -> RunRecord:
        """Reload the record from the store."""

        self.record = self.store.get_run(self.record.id)
        return self.record

    def write_input(self, data: bytes) -> None:
        """Write raw bytes to the managed process input."""

        if not data:
            return
        with self.io_lock:
            if self.process is None:
                return
            if sys.platform == "win32":
                if self.windows_pty:
                    try:
                        self.process.write(data.decode("utf-8", errors="replace"))
                    except (EOFError, OSError):
                        return
                    return
                if self.process.stdin is None:
                    return
                try:
                    self.process.stdin.write(data)
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    return
            else:
                if self.master_fd is None:
                    return
                try:
                    os.write(self.master_fd, data)
                except OSError:
                    return

    def register_attachment(self, session_id: str, mode: str) -> dict[str, Any]:
        """Register an attached client and return its current session state."""

        if not session_id:
            raise RuntimeError("Attachment session ID is required.")
        if mode not in {"view", "interact"}:
            raise RuntimeError(f"Unsupported attachment mode: {mode}")
        now = time.monotonic()
        with self.session_lock:
            if session_id not in self.sessions:
                self.sessions[session_id] = AttachmentSession(
                    session_id=session_id,
                    mode=mode,
                    connected_at=now,
                    last_heartbeat=now,
                )
                self.store.register_attachment(
                    run_id=self.record.id,
                    session_id=session_id,
                    mode=mode,
                )
                if mode == "interact":
                    self.input_lock.add_interactor(session_id, now=now)
                self.attachment_event_sequence += 1
                self.latest_attachment_event = {
                    "sequence": self.attachment_event_sequence,
                    "session_id": session_id,
                    "mode": mode,
                    "event": "connected",
                }
                self._persist_lock_state()
            else:
                self.sessions[session_id].last_heartbeat = now
                self.store.heartbeat_attachment(session_id)
            return self.session_status(session_id, now=now)

    def heartbeat_attachment(self, session_id: str) -> dict[str, Any]:
        """Refresh a client lease and advance pending lock transfers."""

        now = time.monotonic()
        with self.session_lock:
            self.expire_stale_sessions(now=now)
            session = self.sessions.get(session_id)
            if session is None:
                raise RuntimeError("Attachment session is no longer active.")
            session.last_heartbeat = now
            self.store.heartbeat_attachment(session_id)
            if self.input_lock.maybe_transfer(now=now):
                self._persist_lock_state()
            return self.session_status(session_id, now=now)

    def request_input_lock(self, session_id: str) -> dict[str, Any]:
        """Queue an interact client for program-input ownership."""

        now = time.monotonic()
        with self.session_lock:
            session = self.sessions.get(session_id)
            if session is None or session.mode != "interact":
                raise RuntimeError("Only an active interact session can request the input lock.")
            self.input_lock.request(session_id, now=now)
            self._persist_lock_state()
            return self.session_status(session_id, now=now)

    def disconnect_attachment(self, session_id: str) -> None:
        """Remove an attached client and update lock ownership."""

        now = time.monotonic()
        with self.session_lock:
            session = self.sessions.pop(session_id, None)
            if session is None:
                return
            self.input_lock.remove(session_id, now=now)
            self.store.disconnect_attachment(session_id)
            self.attachment_event_sequence += 1
            self.latest_attachment_event = {
                "sequence": self.attachment_event_sequence,
                "session_id": session_id,
                "mode": session.mode,
                "event": "disconnected",
            }
            self._persist_lock_state()

    def write_session_input(self, session_id: str, data: bytes) -> bool:
        """Write input only when the requesting session owns the lock."""

        with self.session_lock:
            if self.input_lock.holder_id != session_id:
                return False
            self.write_input(data)
            self.input_lock.note_input_complete(session_id, now=time.monotonic())
            return True

    def expire_stale_sessions(self, *, now: float | None = None) -> None:
        """Disconnect clients whose heartbeats have expired."""

        current = time.monotonic() if now is None else now
        stale_ids = [
            session_id
            for session_id, session in self.sessions.items()
            if current - session.last_heartbeat > DEFAULT_LEASE_TIMEOUT_SECONDS
        ]
        for session_id in stale_ids:
            self.disconnect_attachment(session_id)

    def session_status(self, session_id: str | None, *, now: float | None = None) -> dict[str, Any]:
        """Return attachment and lock state, optionally for one session."""

        current = time.monotonic() if now is None else now
        with self.session_lock:
            self.expire_stale_sessions(now=current)
            if self.input_lock.maybe_transfer(now=current):
                self._persist_lock_state()
            current_viewers = sum(session.mode == "view" for session in self.sessions.values())
            current_interactors = sum(session.mode == "interact" for session in self.sessions.values())
            summary = self.store.attachment_summary(self.record.id)
            return {
                "current_viewers": current_viewers,
                "current_interactors": current_interactors,
                "lifetime_viewers": summary.lifetime_viewers,
                "lifetime_interactors": summary.lifetime_interactors,
                "lifetime_connections": summary.lifetime_connections,
                "lock_holder": self.input_lock.holder_id,
                "lock_queue_count": len(self.input_lock.queue),
                "session_holds_lock": session_id == self.input_lock.holder_id,
                "session_queue_position": (None if session_id is None else self.input_lock.queue_position(session_id)),
                "attachment_event_sequence": self.attachment_event_sequence,
                "latest_attachment_event": self.latest_attachment_event,
            }

    def _persist_lock_state(self) -> None:
        self.store.set_attachment_lock_state(
            run_id=self.record.id,
            holder_id=self.input_lock.holder_id,
            queued_ids=list(self.input_lock.queue),
        )

    def terminate(self, *, force: bool = False) -> None:
        """Terminate the managed process."""

        self.stop_requested.set()
        process = self.process
        if process is None:
            return
        if self.windows_pty:
            if not process.isalive():
                return
            process.close(force=force)
            return
        if process.poll() is not None:
            return
        if force:
            process.kill()
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    def pause(self) -> None:
        """Pause the managed process when the host OS supports it."""

        process = self.process
        if process is None or process.poll() is not None:
            raise RuntimeError("Process is not running.")
        if sys.platform == "win32":
            raise RuntimeError("Pause is not supported on Windows without an external process API.")
        os.kill(process.pid, signal.SIGSTOP)
        self.store.update_run(self.record.id, status=STATUS_PAUSED)

    def resume(self) -> None:
        """Resume the managed process when the host OS supports it."""

        process = self.process
        if process is None or process.poll() is not None:
            raise RuntimeError("Process is not running.")
        if sys.platform == "win32":
            raise RuntimeError("Resume is not supported on Windows without an external process API.")
        os.kill(process.pid, signal.SIGCONT)
        self.store.update_run(self.record.id, status="running")

    def resize(self, rows: int, columns: int) -> None:
        """Resize the PTY for Unix-like supervised programs."""

        if sys.platform == "win32":
            if self.windows_pty and self.process is not None and self.process.isalive():
                self.process.setwinsize(rows, columns)
            self.store.update_run(self.record.id, rows=rows, columns=columns)
            return
        if self.master_fd is None:
            self.store.update_run(self.record.id, rows=rows, columns=columns)
            return
        packed_size = struct.pack("HHHH", rows, columns, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, packed_size)
        self.store.update_run(self.record.id, rows=rows, columns=columns)


def make_handler(state: SupervisorState) -> type[socketserver.BaseRequestHandler]:
    """Create an IPC handler class bound to supervisor state."""

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                request = self._read_request()
                if request.get("token") != state.record.auth_token:
                    self._send_json({"ok": False, "code": "auth", "error": "Invalid auth token."})
                    return
                op = request.get("op")
                if op == "status":
                    self._send_status(request.get("session_id"))
                elif op == "attach":
                    attachment = state.register_attachment(
                        str(request.get("session_id") or ""),
                        str(request.get("mode") or ""),
                    )
                    self._send_json({"ok": True, **attachment})
                elif op == "heartbeat":
                    attachment = state.heartbeat_attachment(str(request.get("session_id") or ""))
                    self._send_json({"ok": True, **attachment})
                elif op == "detach":
                    state.disconnect_attachment(str(request.get("session_id") or ""))
                    self._send_json({"ok": True})
                elif op == "lock":
                    attachment = state.request_input_lock(str(request.get("session_id") or ""))
                    self._send_json({"ok": True, **attachment})
                elif op == "kill":
                    state.terminate(force=bool(request.get("force", False)))
                    self._send_json({"ok": True})
                elif op == "pause":
                    state.pause()
                    self._send_json({"ok": True})
                elif op == "resume":
                    state.resume()
                    self._send_json({"ok": True})
                elif op == "resize":
                    rows = int(request.get("rows") or 24)
                    columns = int(request.get("columns") or 80)
                    state.resize(rows, columns)
                    self._send_json({"ok": True})
                elif op == "input":
                    session_id = str(request.get("session_id") or "")
                    attachment = state.register_attachment(session_id, "interact")
                    self._send_json({"ok": True, **attachment})
                    try:
                        self._input_loop(session_id)
                    finally:
                        state.disconnect_attachment(session_id)
                else:
                    self._send_json({"ok": False, "error": f"Unsupported operation: {op!r}."})
            except Exception as error:  # noqa: BLE001 - supervisor must not crash on bad client input.
                try:
                    self._send_json({"ok": False, "error": str(error)})
                except OSError:
                    return

        def _read_request(self) -> dict[str, Any]:
            chunks: list[bytes] = []
            while True:
                chunk = self.request.recv(1)
                if not chunk:
                    raise RuntimeError("Connection closed before request was complete.")
                if chunk == b"\n":
                    break
                chunks.append(chunk)
            value = json.loads(b"".join(chunks).decode("utf-8"))
            if not isinstance(value, dict):
                raise RuntimeError("Request must be a JSON object.")
            return value

        def _send_json(self, value: dict[str, Any]) -> None:
            self.request.sendall(encode_request(value))

        def _send_status(self, session_id: Any = None) -> None:
            process = state.process
            exit_code = get_process_exit_code(process, windows_pty=state.windows_pty)
            record = state.refresh_record()
            attachment = state.session_status(str(session_id) if isinstance(session_id, str) else None)
            self._send_json(
                {
                    "ok": True,
                    "status": record.status,
                    "pid": None if process is None else process.pid,
                    "exit_code": exit_code,
                    **attachment,
                }
            )

        def _input_loop(self, session_id: str) -> None:
            while not state.stop_requested.is_set():
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                state.write_session_input(session_id, chunk)

    return Handler


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    """Threaded localhost TCP server with quick restarts."""

    allow_reuse_address = True
    daemon_threads = True


def run_supervisor(run_id: str, state_dir: Path | None = None) -> int:
    """Run the detached supervisor for one managed process."""

    store = RunStore(state_dir)
    record = store.get_run(run_id)
    state = SupervisorState(store=store, record=record)
    record.log_file.parent.mkdir(parents=True, exist_ok=True)

    server = ThreadingTcpServer(("127.0.0.1", 0), make_handler(state))
    server_thread = threading.Thread(target=server.serve_forever, name="runmux-ipc", daemon=True)
    server_thread.start()
    port = int(server.server_address[1])

    try:
        exit_code = supervise_child(state, port=port)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    return exit_code


def supervise_child(state: SupervisorState, *, port: int) -> int:
    """Launch and supervise the child process."""

    argv = json.loads(state.record.argv_json)
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        mark_finished_with_history(state, status=STATUS_FAILED, exit_code=2)
        return 2

    env = os.environ.copy()
    env.update(json.loads(state.record.env_overrides_json))
    cwd = state.record.cwd

    with open(state.log_file, "ab", buffering=0) as output_log:
        try:
            if sys.platform == "win32":
                process = launch_windows_child(
                    argv,
                    cwd=cwd,
                    env=env,
                    rows=state.record.rows,
                    columns=state.record.columns,
                )
                state.process = process
                state.windows_pty = not isinstance(process, subprocess.Popen)
                state.store.mark_started(
                    run_id=state.record.id,
                    pid=process.pid,
                    supervisor_pid=os.getpid(),
                    port=port,
                )
                if state.windows_pty:
                    exit_code = pump_windows_pty(state, output_log)
                else:
                    exit_code = pump_windows_pipe(state, output_log)
            else:
                master_fd, process = launch_pty_child(
                    argv,
                    cwd=cwd,
                    env=env,
                    rows=state.record.rows,
                    columns=state.record.columns,
                )
                state.master_fd = master_fd
                state.process = process
                state.store.mark_started(
                    run_id=state.record.id,
                    pid=process.pid,
                    supervisor_pid=os.getpid(),
                    port=port,
                )
                exit_code = pump_posix_pty(state, output_log)
        except FileNotFoundError as error:
            output_log.write(f"runmux: program not found: {error}\n".encode("utf-8", errors="replace"))
            mark_finished_with_history(state, status=STATUS_FAILED, exit_code=127)
            return 127
        except Exception as error:  # noqa: BLE001 - record launch errors in the managed log.
            output_log.write(f"runmux: supervisor error: {error}\n".encode("utf-8", errors="replace"))
            mark_finished_with_history(state, status=STATUS_FAILED, exit_code=1)
            return 1
        finally:
            if state.master_fd is not None:
                with suppress(OSError):
                    os.close(state.master_fd)

    if state.stop_requested.is_set():
        status = STATUS_KILLED
    elif exit_code == 0:
        status = STATUS_FINISHED
    else:
        status = STATUS_FAILED
    mark_finished_with_history(state, status=status, exit_code=exit_code)
    return exit_code


def mark_finished_with_history(
    state: SupervisorState,
    *,
    status: str,
    exit_code: int | None,
) -> RunRecord:
    """Mark a run finished and mirror completion into command history."""

    record = state.store.mark_finished(run_id=state.record.id, status=status, exit_code=exit_code)
    record_run_finished(record.id, status=status, runtime_seconds=record.runtime_seconds)
    return record


def launch_pipe_child(
    argv: Sequence[str],
    *,
    cwd: str,
    env: dict[str, str],
) -> subprocess.Popen[bytes]:
    """Launch a Windows child with pipe-backed I/O."""

    creationflags = 0
    if sys.platform == "win32":
        creationflags |= windows_child_creation_flags()
    return subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        creationflags=creationflags,
    )


def launch_windows_child(
    argv: Sequence[str],
    *,
    cwd: str,
    env: dict[str, str],
    rows: int | None,
    columns: int | None,
) -> Any:
    """Launch a Windows child using ConPTY when pywinpty is available."""

    try:
        return launch_windows_pty_child(
            argv,
            cwd=cwd,
            env=env,
            rows=rows,
            columns=columns,
        )
    except Exception:
        return launch_pipe_child(argv, cwd=cwd, env=env)


def launch_windows_pty_child(
    argv: Sequence[str],
    *,
    cwd: str,
    env: dict[str, str],
    rows: int | None,
    columns: int | None,
) -> Any:
    """Launch a Windows child under pywinpty."""

    from winpty import Backend, PtyProcess

    return PtyProcess.spawn(
        list(argv),
        cwd=cwd,
        env=env,
        dimensions=(rows or 24, columns or 80),
        backend=Backend.ConPTY,
    )


def windows_child_creation_flags() -> int:
    """Return Windows flags that keep pipe-backed children headless."""

    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


def launch_pty_child(
    argv: Sequence[str],
    *,
    cwd: str,
    env: dict[str, str],
    rows: int | None,
    columns: int | None,
) -> tuple[int, subprocess.Popen[bytes]]:
    """Launch a Unix-like child under a PTY."""

    master_fd, slave_fd = pty.openpty()
    if rows and columns:
        packed_size = struct.pack("HHHH", rows, columns, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, packed_size)

    try:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            close_fds=True,
            bufsize=0,
        )
    finally:
        os.close(slave_fd)
    return master_fd, process


def pump_windows_pipe(state: SupervisorState, output_log: Any) -> int:
    """Copy Windows pipe output to the ANSI log until the child exits."""

    process = state.process
    if process is None or process.stdout is None:
        return 1
    while True:
        chunk = process.stdout.read(4096)
        if chunk:
            output_log.write(chunk)
        elif process.poll() is not None:
            break
        else:
            time.sleep(0.05)
    return int(process.wait())


def get_process_exit_code(process: Any | None, *, windows_pty: bool) -> int | None:
    """Return an exit code when the process has exited, otherwise None."""

    if process is None:
        return None
    if windows_pty:
        if process.isalive():
            return None
        return int(process.wait() or 0)
    return process.poll()


def pump_windows_pty(state: SupervisorState, output_log: Any) -> int:
    """Copy Windows pseudo-console output to the ANSI log until the child exits."""

    process = state.process
    if process is None:
        return 1
    while process.isalive():
        try:
            chunk = process.read(8192)
        except (EOFError, OSError):
            break
        if chunk:
            respond_to_terminal_queries(state, chunk)
            output_log.write(chunk.encode("utf-8", errors="replace"))
        else:
            time.sleep(0.01)
    return int(process.wait() or 0)


def respond_to_terminal_queries(state: SupervisorState, chunk: str) -> None:
    """Answer basic terminal probes for detached Windows ConPTY children."""

    responses: list[bytes] = []
    if "\x1b[c" in chunk or "\x1b[0c" in chunk:
        responses.append(b"\x1b[?1;2c")
    if "\x1b[6n" in chunk:
        responses.append(b"\x1b[1;1R")
    for response in responses:
        state.write_input(response)


def pump_posix_pty(state: SupervisorState, output_log: Any) -> int:
    """Copy PTY output to the ANSI log until the child exits."""

    process = state.process
    master_fd = state.master_fd
    if process is None or master_fd is None:
        return 1

    selector = selectors.DefaultSelector()
    selector.register(master_fd, selectors.EVENT_READ)
    try:
        while True:
            for key, _mask in selector.select(timeout=0.1):
                try:
                    chunk = os.read(key.fd, 8192)
                except OSError as error:
                    if error.errno in {errno.EIO, errno.EBADF}:
                        chunk = b""
                    else:
                        raise
                if chunk:
                    output_log.write(chunk)
                elif process.poll() is not None:
                    return int(process.wait())
            if process.poll() is not None:
                drain_posix_fd(master_fd, output_log)
                return int(process.wait())
    finally:
        with suppress_unregister(selector, master_fd):
            pass
        selector.close()


class suppress_unregister:
    """Context manager that suppresses selector unregister errors."""

    def __init__(self, selector: selectors.BaseSelector, fd: int) -> None:
        self.selector = selector
        self.fd = fd

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        with suppress(Exception):
            self.selector.unregister(self.fd)
        return False


def drain_posix_fd(master_fd: int, output_log: Any) -> None:
    """Drain any remaining bytes from a PTY fd."""

    while True:
        try:
            chunk = os.read(master_fd, 8192)
        except OSError:
            return
        if not chunk:
            return
        output_log.write(chunk)


def build_parser() -> argparse.ArgumentParser:
    """Build the supervisor-only argument parser."""

    parser = argparse.ArgumentParser(description="Internal runmux supervisor process.")
    parser.add_argument("-i", "--run-id", required=True, help="Run ID to supervise.")
    parser.add_argument("-s", "--state-dir", type=Path, default=None, help="State directory to use.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Supervisor entry point."""

    parser = build_parser()
    args = parser.parse_args(argv)
    return run_supervisor(args.run_id, args.state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
