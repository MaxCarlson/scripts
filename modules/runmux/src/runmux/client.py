"""Client-side view, interact, and live list functionality."""

from __future__ import annotations

import json
import os
import select
import shutil
import socket
import sys
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runmux.constants import (
    ATTACH_RESERVED_ROWS,
    DEFAULT_CONTROL_PREFIX,
    DEFAULT_CONTROL_PREFIX_NAME,
    DEFAULT_HEARTBEAT_SECONDS,
    STATUS_LOST,
    TERMINAL_STATUSES,
)
from runmux.ipc import IpcError, open_input_socket, request_json
from runmux.models import AttachmentSummary, RunRecord
from runmux.store import RunStore

if sys.platform == "win32":
    import msvcrt
else:
    import termios
    import tty


class ClientError(RuntimeError):
    """Raised when a client-side operation fails."""


@dataclass(frozen=True)
class AttachCommand:
    """A runmux command requested from view/interact prefix mode."""

    action: str
    target_id: str | None = None


class RawTerminal:
    """Context manager that enables raw terminal input on Unix-like systems."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.original_attrs: list[Any] | None = None

    def __enter__(self) -> RawTerminal:
        if sys.platform != "win32" and os.isatty(self.fd):
            self.original_attrs = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if sys.platform != "win32" and self.original_attrs is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.original_attrs)
        return False


class AttachmentRenderer:
    """Render child output inside a terminal region with runmux status rows."""

    def __init__(self, store: RunStore, record: RunRecord, *, mode: str) -> None:
        self.store = store
        self.record = record
        self.mode = mode
        self._write_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._size = shutil.get_terminal_size(fallback=(80, 24))
        self._thread: threading.Thread | None = None
        self._enabled = bool(getattr(sys.stdout, "isatty", lambda: False)())

    def start(self) -> None:
        if not self._enabled:
            return
        with self._write_lock:
            self._write_bytes(b"\x1b[?6l\x1b[2J")
            self._apply_frame_locked()
        self._thread = threading.Thread(
            target=self._refresh_loop,
            name=f"runmux-render-{self.record.numeric_id}",
            daemon=False,
        )
        self._thread.start()

    def write(self, chunk: bytes) -> None:
        if not self._enabled:
            self._write_bytes(chunk)
            return
        with self._write_lock:
            self._write_bytes(chunk)
            self._apply_frame_locked()

    def stop(self) -> None:
        if not self._enabled:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        with self._write_lock:
            lines = max(3, self._size.lines)
            self._write_bytes(
                f"\x1b[?6l\x1b[r\x1b[1;1H\x1b[2K\x1b[{lines};1H\x1b[2K\r\n".encode()
            )

    def _refresh_loop(self) -> None:
        while not self._stop_event.wait(0.25):
            current_size = shutil.get_terminal_size(fallback=(80, 24))
            if current_size != self._size:
                self._size = current_size
                send_resize(self.record, reserve_rows=ATTACH_RESERVED_ROWS)
            with self._write_lock:
                self._apply_frame_locked()

    def _apply_frame_locked(self) -> None:
        lines = max(3, self._size.lines)
        columns = max(1, self._size.columns)
        child_bottom = max(2, lines - 1)
        try:
            latest = self.store.get_run(self.record.id)
            summary = self.store.attachment_summary(self.record.id)
        except Exception:
            latest = self.record
            summary = None
        top = format_attachment_top_status(latest, mode=self.mode, width=columns)
        bottom = format_attachment_bottom_status(summary, width=columns)
        sequence = (
            f"\x1b[?6l\x1b[2;{child_bottom}r\x1b[?6h"
            f"\x1b7\x1b[?6l\x1b[1;1H\x1b[2K{top}"
            f"\x1b[{lines};1H\x1b[2K{bottom}\x1b[?6h\x1b8"
        )
        self._write_bytes(sequence.encode("utf-8", errors="replace"))

    @staticmethod
    def _write_bytes(payload: bytes) -> None:
        stream = getattr(sys.stdout, "buffer", sys.stdout)
        try:
            stream.write(payload)
        except TypeError:
            stream.write(payload.decode("utf-8", errors="replace"))
        stream.flush()


def format_attachment_top_status(record: RunRecord, *, mode: str, width: int) -> str:
    """Format the fixed top attachment status row."""

    value = (
        f" runmux {record.numeric_id} | {mode} | {record.status} | "
        f"{format_duration(record.runtime_seconds)} | {record.command_line}"
    )
    return truncate(value, width).ljust(width)


def format_attachment_bottom_status(
    summary: AttachmentSummary | None,
    *,
    width: int,
) -> str:
    """Format the fixed bottom attachment controls and input-lock status row."""

    if summary is None:
        lock = "input --"
    elif summary.lock_held:
        lock = f"input locked Q:{summary.lock_queue_count}"
    else:
        lock = f"input shared Q:{summary.lock_queue_count}"
    value = f" Ctrl-X ? help | Ctrl-X q detach | {lock}"
    return truncate(value, width).ljust(width)


def format_duration(seconds: float) -> str:
    """Format seconds as a compact duration."""

    total = int(max(0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def truncate(value: str, width: int) -> str:
    """Truncate text to fit a display width."""

    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 1:
        return "…"
    return value[: width - 1] + "…"


def colorize(value: str, color_code: str, *, enabled: bool) -> str:
    """Apply ANSI color when enabled."""

    if not enabled:
        return value
    return f"\x1b[{color_code}m{value}\x1b[0m"


def status_color(status: str) -> str:
    """Return a color code for a run status."""

    if status == "running":
        return "32"
    if status == "paused":
        return "33"
    if status in {"failed", "lost"}:
        return "31"
    if status in {"finished", "killed"}:
        return "90"
    return "37"


def build_list_rows(
    records: list[RunRecord],
    *,
    width: int,
    selected_index: int | None = None,
    color: bool = False,
    attachment_summaries: dict[str, AttachmentSummary] | None = None,
) -> list[str]:
    """Build display rows for the live list table."""

    id_width = 5
    status_width = 9
    runtime_width = 8
    pid_width = 8
    attach_width = 22
    fixed = id_width + status_width + runtime_width + pid_width + attach_width + 11
    command_width = max(20, width - fixed)
    rows = [
        colorize(
            f"{'ID':<{id_width}} {'STATUS':<{status_width}} {'RUNTIME':>{runtime_width}} "
            f"{'PID':>{pid_width}} {'ATTACH':<{attach_width}} COMMAND",
            "1;37",
            enabled=color,
        ),
        colorize(
            f"{'-' * id_width} {'-' * status_width} {'-' * runtime_width} "
            f"{'-' * pid_width} {'-' * attach_width} {'-' * command_width}",
            "2",
            enabled=color,
        ),
    ]
    for index, record in enumerate(records):
        pid = "" if record.pid is None else str(record.pid)
        status = colorize(
            f"{record.status:<{status_width}}",
            status_color(record.status),
            enabled=color,
        )
        runtime = colorize(
            f"{format_duration(record.runtime_seconds):>{runtime_width}}",
            "36",
            enabled=color,
        )
        command = colorize(truncate(record.command_line, command_width), "97", enabled=color)
        summary = (attachment_summaries or {}).get(record.id)
        attach = format_attachment_summary(summary, width=attach_width, color=color)
        row = (
            f"{str(record.numeric_id):<{id_width}} "
            f"{status} "
            f"{runtime} "
            f"{pid:>{pid_width}} "
            f"{attach} "
            f"{command}"
        )
        if selected_index == index:
            row = f"\x1b[7m{row}\x1b[0m"
        rows.append(row)
    if selected_index is not None and records:
        selected = records[selected_index]
        rows.append("")
        rows.append(f"Selected {selected.numeric_id}: i=interact  v=view  q=quit")
    return rows


def format_attachment_summary(
    summary: AttachmentSummary | None,
    *,
    width: int,
    color: bool,
) -> str:
    """Format current, lifetime, and input-lock attachment counts."""

    if summary is None:
        return f"{'--':<{width}}"
    parts = [
        colorize(f"I:{summary.current_interactors}", "32", enabled=color),
        colorize(f"V:{summary.current_viewers}", "36", enabled=color),
        colorize(f"T:{summary.lifetime_connections}", "35", enabled=color),
        colorize(f"L:{int(summary.lock_held)}", "33", enabled=color),
        colorize(f"Q:{summary.lock_queue_count}", "34", enabled=color),
    ]
    rendered = " ".join(parts)
    return rendered + (" " * max(0, width - visible_length(rendered)))


def visible_length(value: str) -> int:
    """Return display length for text containing runmux SGR colors."""

    import re

    return len(re.sub(r"\x1b\[[0-9;]*m", "", value))


def attachment_summaries_for(
    store: RunStore,
    records: list[RunRecord],
) -> dict[str, AttachmentSummary]:
    """Load attachment summaries for displayed records."""

    return {record.id: store.attachment_summary(record.id) for record in records}


def list_runs_live(
    store: RunStore,
    *,
    once: bool,
    include_all: bool,
    limit: int | None,
    refresh_seconds: float,
    output_json: bool,
) -> int:
    """Display runs once or as a live in-place table."""

    if output_json:
        records = refresh_active_statuses(store.list_runs(include_all=include_all, limit=limit), store)
        summaries = attachment_summaries_for(store, records)
        payload = [record_to_json(record, attachment=summaries[record.id]) for record in records]
        print(json.dumps(payload, indent=2))
        return 0

    if once:
        width = shutil.get_terminal_size(fallback=(120, 30)).columns
        records = refresh_active_statuses(store.list_runs(include_all=include_all, limit=limit), store)
        summaries = attachment_summaries_for(store, records)
        print(
            "\n".join(
                build_list_rows(
                    records,
                    width=width,
                    attachment_summaries=summaries,
                )
            )
        )
        return 0

    selected_index = 0
    print("\x1b[?25l", end="")
    try:
        while True:
            width = shutil.get_terminal_size(fallback=(120, 30)).columns
            records = refresh_active_statuses(store.list_runs(include_all=include_all, limit=limit), store)
            summaries = attachment_summaries_for(store, records)
            selected_index = max(0, min(selected_index, len(records) - 1)) if records else 0
            rows = build_list_rows(
                records,
                width=width,
                selected_index=selected_index if records else None,
                color=sys.stdout.isatty(),
                attachment_summaries=summaries,
            )
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            header = f"runmux live list - {timestamp} - Up/Down select, i interact, v view, q quit"
            screen = "\x1b[H\x1b[2J" + header + "\n\n" + "\n".join(rows) + "\n"
            sys.stdout.write(screen)
            sys.stdout.flush()
            deadline = time.monotonic() + refresh_seconds
            while time.monotonic() < deadline:
                key = read_key_nonblocking()
                if key is None:
                    time.sleep(0.05)
                    continue
                if key in {"q", "Q", "\x03"}:
                    return 0
                if key in {"UP", "k", "K"} and records:
                    selected_index = max(0, selected_index - 1)
                    break
                if key in {"DOWN", "j", "J"} and records:
                    selected_index = min(len(records) - 1, selected_index + 1)
                    break
                if key in {"v", "V"} and records:
                    sys.stdout.write("\x1b[?25h\x1b[H\x1b[2J")
                    sys.stdout.flush()
                    return view_run(
                        store,
                        run_id=str(records[selected_index].numeric_id),
                        follow=True,
                        from_end=False,
                        tail_lines=None,
                    )
                if key in {"i", "I"} and records:
                    sys.stdout.write("\x1b[?25h\x1b[H\x1b[2J")
                    sys.stdout.flush()
                    return interact_run(store, run_id=str(records[selected_index].numeric_id), tail_lines=None)
    except KeyboardInterrupt:
        return 0
    finally:
        print("\x1b[?25h", end="")
        sys.stdout.flush()


def read_key_nonblocking() -> str | None:
    """Read a single navigation key when one is already available."""

    if not sys.stdin.isatty():
        return None
    if sys.platform == "win32":
        if not msvcrt.kbhit():
            return None
        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            second = msvcrt.getwch()
            if second == "H":
                return "UP"
            if second == "P":
                return "DOWN"
            return second
        return key
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return None
    key = sys.stdin.read(1)
    if key == "\x1b" and select.select([sys.stdin], [], [], 0.001)[0]:
        rest = sys.stdin.read(2)
        if rest == "[A":
            return "UP"
        if rest == "[B":
            return "DOWN"
    return key


def refresh_active_statuses(records: list[RunRecord], store: RunStore) -> list[RunRecord]:
    """Refresh records whose supervisors can be contacted."""

    refreshed: list[RunRecord] = []
    for record in records:
        if record.status in TERMINAL_STATUSES or record.port is None:
            refreshed.append(record)
            continue
        try:
            response = request_json(record, op="status", timeout=0.2)
            status = str(response.get("status") or record.status)
            exit_code = response.get("exit_code")
            pid = response.get("pid")
            if status != record.status or pid != record.pid:
                record = store.update_run(record.id, status=status, pid=pid, exit_code=exit_code)
            else:
                record = store.get_run(record.id)
        except IpcError:
            if record.supervisor_pid is not None and not is_pid_alive(record.supervisor_pid):
                record = store.mark_finished(run_id=record.id, status=STATUS_LOST, exit_code=None)
            else:
                record = store.get_run(record.id)
        refreshed.append(record)
    return refreshed


def is_pid_alive(pid: int) -> bool:
    """Return whether a local process ID appears alive."""

    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                return False
            try:
                wait_timeout = 0x00000102
                return ctypes.windll.kernel32.WaitForSingleObject(process, 0) == wait_timeout
            finally:
                ctypes.windll.kernel32.CloseHandle(process)
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def record_to_json(
    record: RunRecord,
    *,
    attachment: AttachmentSummary | None = None,
) -> dict[str, Any]:
    """Convert a record to JSON-serializable output."""

    payload = {
        "id": record.id,
        "numeric_id": record.numeric_id,
        "name": record.name,
        "status": record.status,
        "runtime_seconds": record.runtime_seconds,
        "pid": record.pid,
        "supervisor_pid": record.supervisor_pid,
        "exit_code": record.exit_code,
        "cwd": record.cwd,
        "command_line": record.command_line,
        "log_path": record.log_path,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "ended_at": record.ended_at,
        "restart_of": record.restart_of,
        "duplicate_of": record.duplicate_of,
    }
    if attachment is not None:
        payload.update(
            {
                "current_viewers": attachment.current_viewers,
                "current_interactors": attachment.current_interactors,
                "lifetime_viewers": attachment.lifetime_viewers,
                "lifetime_interactors": attachment.lifetime_interactors,
                "lifetime_connections": attachment.lifetime_connections,
                "input_lock_held": attachment.lock_held,
                "input_lock_queue_count": attachment.lock_queue_count,
            }
        )
    return payload


def view_run(
    store: RunStore,
    *,
    run_id: str,
    follow: bool,
    from_end: bool,
    tail_lines: int | None,
) -> int:
    """View a run's output log, preserving ANSI bytes."""

    current_run_id = run_id
    current_from_end = from_end
    while True:
        record = store.get_run(current_run_id)
        if not follow:
            command = tail_file(
                record.log_file,
                follow=False,
                from_end=current_from_end,
                tail_lines=tail_lines,
            )
        else:
            command = follow_view_run(
                store,
                record=record,
                from_end=current_from_end or tail_lines is None,
                tail_lines=tail_lines,
            )
        if command is None or command.action == "detach":
            return 0
        if command.action == "jump" and command.target_id is not None:
            current_run_id = command.target_id
            current_from_end = True
            continue
        if command.action == "interact":
            return interact_run(store, run_id=record.id, tail_lines=None)
        return 0
    return 0


def follow_view_run(
    store: RunStore,
    *,
    record: RunRecord,
    from_end: bool,
    tail_lines: int | None,
    control_prefix: bytes = DEFAULT_CONTROL_PREFIX,
) -> AttachCommand | None:
    """Follow output in realtime while only listening for runmux prefix commands."""

    session_id = uuid.uuid4().hex
    request_json(
        record,
        op="attach",
        payload={"session_id": session_id, "mode": "view"},
    )
    send_resize(record, reserve_rows=ATTACH_RESERVED_ROWS)
    renderer = AttachmentRenderer(store, record, mode="view")
    renderer.start()
    stop_event = threading.Event()
    heartbeat_stop = threading.Event()
    output_pause_event = threading.Event()
    heartbeat_thread = start_attachment_heartbeat(
        record,
        session_id=session_id,
        stop_event=heartbeat_stop,
    )
    tail_thread = threading.Thread(
        target=tail_file,
        kwargs={
            "path": record.log_file,
            "follow": True,
            "from_end": from_end,
            "tail_lines": tail_lines,
            "should_stop": stop_event.is_set,
            "output_paused": output_pause_event.is_set,
            "output_writer": renderer.write,
        },
        name="runmux-tail",
        daemon=False,
    )
    tail_thread.start()

    try:
        set_terminal_title(f"runmux view {record.numeric_id} - prefix {DEFAULT_CONTROL_PREFIX_NAME}")
        return view_input_loop(
            control_prefix=control_prefix,
            on_command=make_command_handler(
                record,
                store,
                mode="view",
                session_id=session_id,
            ),
            output_pause_event=output_pause_event,
            should_stop=lambda: store.get_run(record.id).status in TERMINAL_STATUSES,
        )
    finally:
        set_terminal_title(None)
        stop_event.set()
        heartbeat_stop.set()
        tail_thread.join()
        heartbeat_thread.join()
        renderer.stop()
        detach_attachment(record, session_id)


def interact_run(
    store: RunStore,
    *,
    run_id: str,
    tail_lines: int | None,
    control_prefix: bytes = DEFAULT_CONTROL_PREFIX,
) -> int:
    """Attach an interactive input channel while tailing the program output."""

    current_run_id = run_id
    while True:
        record = store.get_run(current_run_id)
        if record.status in TERMINAL_STATUSES:
            raise ClientError(f"Run '{record.id}' is not active; status is {record.status}.")

        send_resize(record, reserve_rows=ATTACH_RESERVED_ROWS)
        renderer = AttachmentRenderer(store, record, mode="interact")
        renderer.start()
        session_id = uuid.uuid4().hex
        stop_event = threading.Event()
        heartbeat_stop = threading.Event()
        output_pause_event = threading.Event()
        tail_thread = threading.Thread(
            target=tail_file,
            kwargs={
                "path": record.log_file,
                "follow": True,
                "from_end": tail_lines is None,
                "tail_lines": tail_lines,
                "should_stop": stop_event.is_set,
                "output_paused": output_pause_event.is_set,
                "output_writer": renderer.write,
            },
            name="runmux-tail",
            daemon=False,
        )
        tail_thread.start()

        try:
            with open_input_socket(record, session_id=session_id) as sock:
                heartbeat_thread = start_attachment_heartbeat(
                    record,
                    session_id=session_id,
                    stop_event=heartbeat_stop,
                )
                set_terminal_title(f"runmux interact {record.numeric_id} - prefix {DEFAULT_CONTROL_PREFIX_NAME}")
                try:
                    command = forward_input_loop(
                        sock,
                        control_prefix=control_prefix,
                        on_command=make_command_handler(
                            record,
                            store,
                            mode="interact",
                            session_id=session_id,
                        ),
                        output_pause_event=output_pause_event,
                    )
                finally:
                    heartbeat_stop.set()
                    heartbeat_thread.join()
                    with suppress(OSError):
                        sock.shutdown(socket.SHUT_WR)
        finally:
            set_terminal_title(None)
            stop_event.set()
            tail_thread.join()
            renderer.stop()
            detach_attachment(record, session_id)

        if command is None or command.action == "detach":
            return 0
        if command.action == "jump" and command.target_id is not None:
            current_run_id = command.target_id
            tail_lines = None
            continue
        if command.action == "view":
            return view_run(
                store,
                run_id=record.id,
                follow=True,
                from_end=False,
                tail_lines=None,
            )
        return 0


def send_resize(record: RunRecord, *, reserve_rows: int = 0) -> None:
    """Best-effort resize notification to the supervisor."""

    size = shutil.get_terminal_size(fallback=(80, 24))
    rows = max(1, size.lines - max(0, reserve_rows))
    try:
        request_json(record, op="resize", payload={"rows": rows, "columns": size.columns})
    except IpcError:
        return


def start_attachment_heartbeat(
    record: RunRecord,
    *,
    session_id: str,
    stop_event: threading.Event,
) -> threading.Thread:
    """Start a heartbeat thread for one registered attachment."""

    thread = threading.Thread(
        target=attachment_heartbeat_loop,
        kwargs={
            "record": record,
            "session_id": session_id,
            "stop_event": stop_event,
        },
        name=f"runmux-heartbeat-{session_id[:8]}",
        daemon=False,
    )
    thread.start()
    return thread


def attachment_heartbeat_loop(
    *,
    record: RunRecord,
    session_id: str,
    stop_event: threading.Event,
) -> None:
    """Maintain an attachment lease until stopped or disconnected."""

    while not stop_event.wait(DEFAULT_HEARTBEAT_SECONDS):
        try:
            request_json(
                record,
                op="heartbeat",
                payload={"session_id": session_id},
            )
        except IpcError:
            return


def detach_attachment(record: RunRecord, session_id: str) -> None:
    """Best-effort detach notification for a registered session."""

    with suppress(IpcError):
        request_json(
            record,
            op="detach",
            payload={"session_id": session_id},
        )


def make_command_handler(
    record: RunRecord,
    store: RunStore,
    *,
    mode: str,
    session_id: str | None = None,
) -> Callable[[bytes], AttachCommand | None]:
    """Create a handler for interact prefix commands.

    The handler returns None when attachment should continue, or an AttachCommand
    when the caller should change attachment state.
    """

    def handle(command: bytes) -> AttachCommand | None:
        if command in {b"q", b"Q"}:
            write_local_message("\r\n[runmux detached]\r\n")
            return AttachCommand("detach")
        if command in {b"?", b"h", b"H"}:
            show_prefix_menu()
            return None
        if command in {b"j", b"J"}:
            target_id = read_prefixed_argument("jump to run ID")
            if target_id:
                return AttachCommand("jump", target_id=target_id)
            return None
        if command in {b"v", b"V"}:
            if mode != "view":
                write_local_message("\r\n[runmux switching to view]\r\n")
                return AttachCommand("view")
            return None
        if command in {b"i", b"I"}:
            if mode != "interact":
                write_local_message("\r\n[runmux switching to interact]\r\n")
                return AttachCommand("interact")
            return None
        if command in {b"k", b"K"}:
            latest = store.get_run(record.id)
            request_json(latest, op="kill", payload={"force": False})
            write_local_message("\r\n[runmux kill requested]\r\n")
            return None
        if command == b"l" and mode == "interact" and session_id is not None:
            latest = store.get_run(record.id)
            response = request_json(
                latest,
                op="lock",
                payload={"session_id": session_id},
            )
            if response.get("session_holds_lock"):
                write_local_message("\r\n[runmux input lock acquired]\r\n")
            else:
                position = response.get("session_queue_position")
                write_local_message(f"\r\n[runmux input lock requested; queue {position or '--'}]\r\n")
            return None
        return None

    return handle


def forward_input_loop(
    sock: socket.socket,
    *,
    control_prefix: bytes,
    on_command: Callable[[bytes], AttachCommand | None],
    output_pause_event: threading.Event | None = None,
) -> AttachCommand | None:
    """Forward local keyboard input to a supervisor input socket."""

    if sys.platform == "win32":
        return forward_windows_input(
            sock,
            control_prefix=control_prefix,
            on_command=on_command,
            output_pause_event=output_pause_event,
        )

    stdin_fd = sys.stdin.fileno()
    with RawTerminal(stdin_fd):
        while True:
            data = os.read(stdin_fd, 1)
            if not data:
                return None
            if data == control_prefix:
                with paused_output(output_pause_event):
                    show_prefix_menu()
                    command = os.read(stdin_fd, 1)
                    if command == control_prefix:
                        sock.sendall(control_prefix)
                        continue
                    attach_command = on_command(command)
                    if attach_command is not None:
                        return attach_command
                    continue
            sock.sendall(data)
    return None


def forward_windows_input(
    sock: socket.socket,
    *,
    control_prefix: bytes,
    on_command: Callable[[bytes], AttachCommand | None],
    output_pause_event: threading.Event | None = None,
) -> AttachCommand | None:
    """Forward Windows console keyboard input to the supervisor."""

    while True:
        char = msvcrt.getwch()
        data = encode_windows_console_key(char)
        if data == control_prefix:
            with paused_output(output_pause_event):
                show_prefix_menu()
                command = encode_windows_console_key(msvcrt.getwch())
                if command == control_prefix:
                    sock.sendall(control_prefix)
                    continue
                attach_command = on_command(command)
                if attach_command is not None:
                    return attach_command
                continue
        sock.sendall(data)
    return None


def view_input_loop(
    *,
    control_prefix: bytes,
    on_command: Callable[[bytes], AttachCommand | None],
    output_pause_event: threading.Event | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> AttachCommand | None:
    """Read only runmux prefix keys while view output follows in another thread."""

    if sys.platform == "win32":
        return view_windows_input(
            control_prefix=control_prefix,
            on_command=on_command,
            output_pause_event=output_pause_event,
            should_stop=should_stop,
        )

    stdin_fd = sys.stdin.fileno()
    with RawTerminal(stdin_fd):
        while True:
            if should_stop is not None and should_stop():
                return None
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not ready:
                continue
            data = os.read(stdin_fd, 1)
            if not data:
                return None
            if data != control_prefix:
                continue
            with paused_output(output_pause_event):
                show_prefix_menu()
                command = os.read(stdin_fd, 1)
                if command == control_prefix:
                    continue
                attach_command = on_command(command)
                if attach_command is not None:
                    return attach_command


def view_windows_input(
    *,
    control_prefix: bytes,
    on_command: Callable[[bytes], AttachCommand | None],
    output_pause_event: threading.Event | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> AttachCommand | None:
    """Read only runmux prefix keys from a Windows console."""

    while True:
        if should_stop is not None and should_stop():
            return None
        if not msvcrt.kbhit():
            time.sleep(0.05)
            continue
        data = encode_windows_console_key(msvcrt.getwch())
        if data != control_prefix:
            continue
        with paused_output(output_pause_event):
            show_prefix_menu()
            command = encode_windows_console_key(msvcrt.getwch())
            if command == control_prefix:
                continue
            attach_command = on_command(command)
            if attach_command is not None:
                return attach_command


def encode_windows_console_key(char: str) -> bytes:
    """Translate a Windows console keypress to terminal input bytes."""

    if char not in {"\x00", "\xe0"}:
        return char.encode("utf-8", errors="ignore")

    second = msvcrt.getwch()
    special_keys = {
        "H": b"\x1b[A",
        "P": b"\x1b[B",
        "K": b"\x1b[D",
        "M": b"\x1b[C",
        "I": b"\x1b[5~",
        "Q": b"\x1b[6~",
        "G": b"\x1b[H",
        "O": b"\x1b[F",
        "S": b"\x1b[3~",
    }
    return special_keys.get(second, b"")


def show_prefix_menu() -> None:
    """Show runmux prefix commands out-of-band."""

    write_local_message(
        f"\x1b[s\x1b[999;1H\x1b[2K[runmux {DEFAULT_CONTROL_PREFIX_NAME}: "
        f"q detach | j jump | v view | "
        f"i interact | l input lock | k kill | ? help | "
        f"{DEFAULT_CONTROL_PREFIX_NAME} send prefix]\x1b[u"
    )


class paused_output:
    """Temporarily pause attach output while runmux reads a prefix command."""

    def __init__(self, event: threading.Event | None) -> None:
        self.event = event

    def __enter__(self) -> None:
        if self.event is not None:
            self.event.set()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if self.event is not None:
            self.event.clear()
        return False


def read_prefixed_argument(prompt: str) -> str | None:
    """Read a short argument while in runmux prefix command mode."""

    write_local_message(f"[runmux {prompt}: ")
    chars: list[str] = []
    while True:
        if sys.platform == "win32":
            char = msvcrt.getwch()
        else:
            char = os.read(sys.stdin.fileno(), 1).decode("utf-8", errors="ignore")
        if char in {"\r", "\n"}:
            write_local_message("]\r\n")
            value = "".join(chars).strip()
            return value or None
        if char in {"\x1b", "\x03"}:
            write_local_message("cancelled]\r\n")
            return None
        if char in {"\b", "\x7f"}:
            if chars:
                chars.pop()
                write_local_message("\b \b")
            continue
        if char.isprintable():
            chars.append(char)
            write_local_message(char)


def write_local_message(message: str) -> None:
    """Write an out-of-band runmux message to stderr."""

    sys.stderr.write(message)
    sys.stderr.flush()


def set_terminal_title(title: str | None) -> None:
    """Set or clear the local terminal title without touching screen contents."""

    value = "runmux" if title is None else title
    safe_value = value.replace("\x1b", "").replace("\x07", "")
    sys.stderr.write(f"\x1b]0;{safe_value}\x07")
    sys.stderr.flush()


def tail_file(
    path: Path,
    *,
    follow: bool,
    from_end: bool,
    tail_lines: int | None,
    should_stop: Callable[[], bool] | None = None,
    command_handler: Callable[[bytes], AttachCommand | None] | None = None,
    output_paused: Callable[[], bool] | None = None,
    output_writer: Callable[[bytes], None] | None = None,
) -> AttachCommand | None:
    """Write a file's bytes to stdout, optionally following appends."""

    wait_for_file(path)
    if tail_lines is not None:
        position = compute_tail_offset(path, tail_lines)
    elif from_end:
        position = path.stat().st_size
    else:
        position = 0

    while True:
        if output_paused is not None and output_paused():
            time.sleep(0.05)
            continue
        if should_stop is not None and should_stop():
            return None
        with path.open("rb") as stream:
            stream.seek(position)
            chunk = stream.read(8192)
            position = stream.tell()
        if chunk:
            if output_writer is not None:
                output_writer(chunk)
            else:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            continue
        if not follow:
            return None
        if command_handler is not None:
            command = read_view_command(command_handler)
            if command is not None:
                return command
        if should_stop is not None and should_stop():
            with path.open("rb") as stream:
                stream.seek(position)
                chunk = stream.read(8192)
                position = stream.tell()
            if chunk:
                if output_writer is not None:
                    output_writer(chunk)
                else:
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
            return None
        time.sleep(0.1)


def read_view_command(
    command_handler: Callable[[bytes], AttachCommand | None],
) -> AttachCommand | None:
    """Read runmux prefix commands while view is following output."""

    key = read_key_nonblocking()
    if key is None:
        return None
    data = key.encode("utf-8", errors="ignore")
    if data != DEFAULT_CONTROL_PREFIX:
        return None
    show_prefix_menu()
    command_key = read_blocking_key()
    if command_key is None:
        return None
    command = command_key.encode("utf-8", errors="ignore")
    if command == DEFAULT_CONTROL_PREFIX:
        return None
    return command_handler(command)


def read_blocking_key() -> str | None:
    """Read one key from the current terminal."""

    if sys.platform == "win32":
        return msvcrt.getwch()
    data = os.read(sys.stdin.fileno(), 1)
    if not data:
        return None
    return data.decode("utf-8", errors="ignore")


def wait_for_file(path: Path, *, timeout_seconds: float = 5.0) -> None:
    """Wait briefly for a log file to be created."""

    deadline = time.monotonic() + timeout_seconds
    while not path.exists():
        if time.monotonic() >= deadline:
            raise ClientError(f"Output log does not exist: {path}")
        time.sleep(0.05)


def compute_tail_offset(path: Path, line_count: int) -> int:
    """Return the byte offset for the last N lines of a file."""

    if line_count <= 0:
        return path.stat().st_size
    block_size = 8192
    remaining = line_count
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        position = stream.tell()
        while position > 0:
            read_size = min(block_size, position)
            position -= read_size
            stream.seek(position)
            block = stream.read(read_size)
            remaining -= block.count(b"\n")
            if remaining < 0:
                index = len(block)
                while remaining < 0 and index > 0:
                    index = block.rfind(b"\n", 0, index)
                    remaining += 1
                return position + index + 1
        return 0
