from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import runmux.runner as runner
from runmux.cli import build_parser, handle_ls, handle_remove_finished
from runmux.client import (
    AttachCommand,
    IpcError,
    build_list_rows,
    encode_windows_console_key,
    forward_input_loop,
    interact_run,
    make_command_handler,
    refresh_active_statuses,
    send_resize,
    tail_file,
)
from runmux.models import RunRecord
from runmux.runner import (
    build_env_overrides,
    command_line_for_display,
    normalize_program_args,
    remove_finished_runs,
    start_supervisor,
)
from runmux.store import RunStore


def test_normalize_program_args_strips_double_dash() -> None:
    assert normalize_program_args(["--", "python", "-V"]) == ["python", "-V"]


def test_normalize_program_args_accepts_no_double_dash() -> None:
    assert normalize_program_args(["python", "-V"]) == ["python", "-V"]


def test_command_line_for_display_contains_program() -> None:
    rendered = command_line_for_display(["python", "-c", "print('hello')"])

    assert "python" in rendered
    assert "hello" in rendered


def test_env_overrides_force_utf8_python_output() -> None:
    overrides = build_env_overrides(force_color=True)

    assert overrides["PYTHONIOENCODING"] == "utf-8"


def test_ls_alias_defaults_to_one_shot_list(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--state-dir", str(tmp_path), "ls"])

    assert args.func is handle_ls


def test_remove_finished_command_parses(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        ["--state-dir", str(tmp_path), "remove-finished", "--clean-only"]
    )

    assert args.func is handle_remove_finished
    assert args.clean_only is True


def test_windows_enter_is_forwarded_as_carriage_return() -> None:
    assert encode_windows_console_key("\r") == b"\r"


def test_windows_arrow_key_is_forwarded_as_terminal_escape(monkeypatch) -> None:
    with patch("runmux.client.msvcrt.getwch", return_value="H"):
        assert encode_windows_console_key("\xe0") == b"\x1b[A"


def test_interact_prefix_can_switch_to_view(tmp_path: Path) -> None:
    record = RunRecord(
        id="20260611-010101-abcdef",
        numeric_id=3,
        name=None,
        status="running",
        created_at="2026-06-11T00:00:00+00:00",
        updated_at="2026-06-11T00:00:00+00:00",
        started_at="2026-06-11T00:00:00+00:00",
        ended_at=None,
        exit_code=None,
        pid=123,
        supervisor_pid=456,
        program="python",
        argv_json="[]",
        cwd=str(tmp_path),
        env_overrides_json="{}",
        port=999,
        auth_token="token",
        log_path=str(tmp_path / "output.ansi"),
        command_line="python -c print('hello')",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )
    store = Mock()

    command = make_command_handler(record, store, mode="interact")(b"v")

    assert command is not None
    assert command.action == "view"


def test_prefix_jump_reads_target_id(tmp_path: Path) -> None:
    record = RunRecord(
        id="20260611-010101-abcdef",
        numeric_id=3,
        name=None,
        status="running",
        created_at="2026-06-11T00:00:00+00:00",
        updated_at="2026-06-11T00:00:00+00:00",
        started_at="2026-06-11T00:00:00+00:00",
        ended_at=None,
        exit_code=None,
        pid=123,
        supervisor_pid=456,
        program="python",
        argv_json="[]",
        cwd=str(tmp_path),
        env_overrides_json="{}",
        port=999,
        auth_token="token",
        log_path=str(tmp_path / "output.ansi"),
        command_line="python -c print('hello')",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )
    store = Mock()

    with patch("runmux.client.read_prefixed_argument", return_value="7"):
        command = make_command_handler(record, store, mode="view")(b"j")

    assert command is not None
    assert command.action == "jump"
    assert command.target_id == "7"


def test_refresh_marks_missing_supervisor_as_lost(tmp_path: Path) -> None:
    from runmux.store import RunStore

    store = RunStore(tmp_path)
    run_dir = store.runs_dir / "20260611-010101-abcdef"
    run_dir.mkdir(parents=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"")
    record = store.create_run(
        run_id="20260611-010101-abcdef",
        name=None,
        status="running",
        program="python",
        argv_json="[]",
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="token",
        log_path=log_path,
        command_line="python -V",
    )
    record = store.update_run(record.id, port=12345, supervisor_pid=999999)

    with (
        patch("runmux.client.request_json", side_effect=IpcError("no server")),
        patch("runmux.client.is_pid_alive", return_value=False),
    ):
        refreshed = refresh_active_statuses([record], store)

    assert refreshed[0].status == "lost"


def test_tail_file_follows_appends_after_eof(tmp_path: Path) -> None:
    path = tmp_path / "output.ansi"
    path.write_bytes(b"first")
    stop_event = threading.Event()
    output = io.BytesIO()

    class FakeStdout:
        buffer = output

    with patch("runmux.client.sys.stdout", FakeStdout()):
        thread = threading.Thread(
            target=tail_file,
            kwargs={
                "path": path,
                "follow": True,
                "from_end": False,
                "tail_lines": None,
                "should_stop": stop_event.is_set,
            },
        )
        thread.start()
        deadline = time.monotonic() + 2
        while output.getvalue() != b"first" and time.monotonic() < deadline:
            time.sleep(0.01)
        with path.open("ab") as stream:
            stream.write(b"second")
        deadline = time.monotonic() + 2
        while output.getvalue() != b"firstsecond" and time.monotonic() < deadline:
            time.sleep(0.01)
        stop_event.set()
        thread.join(timeout=2)

    assert output.getvalue() == b"firstsecond"


def test_tail_file_pauses_without_advancing_position(tmp_path: Path) -> None:
    path = tmp_path / "output.ansi"
    path.write_bytes(b"first")
    stop_event = threading.Event()
    pause_event = threading.Event()
    pause_event.set()
    output = io.BytesIO()

    class FakeStdout:
        buffer = output

    with patch("runmux.client.sys.stdout", FakeStdout()):
        thread = threading.Thread(
            target=tail_file,
            kwargs={
                "path": path,
                "follow": True,
                "from_end": False,
                "tail_lines": None,
                "should_stop": stop_event.is_set,
                "output_paused": pause_event.is_set,
            },
        )
        thread.start()
        time.sleep(0.1)
        assert output.getvalue() == b""
        pause_event.clear()
        deadline = time.monotonic() + 2
        while output.getvalue() != b"first" and time.monotonic() < deadline:
            time.sleep(0.01)
        stop_event.set()
        thread.join(timeout=2)

    assert output.getvalue() == b"first"


def test_send_resize_reserves_bottom_row(tmp_path: Path) -> None:
    record = RunRecord(
        id="20260611-010101-abcdef",
        numeric_id=0,
        name=None,
        status="running",
        created_at="2026-06-11T00:00:00+00:00",
        updated_at="2026-06-11T00:00:00+00:00",
        started_at="2026-06-11T00:00:00+00:00",
        ended_at=None,
        exit_code=None,
        pid=123,
        supervisor_pid=456,
        program="python",
        argv_json="[]",
        cwd=str(tmp_path),
        env_overrides_json="{}",
        port=999,
        auth_token="token",
        log_path=str(tmp_path / "output.ansi"),
        command_line="python -c print('hello')",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )
    terminal_size = argparse.Namespace(lines=40, columns=120)

    with (
        patch("runmux.client.shutil.get_terminal_size", return_value=terminal_size),
        patch("runmux.client.request_json") as request_json,
    ):
        send_resize(record, reserve_rows=1)

    request_json.assert_called_once_with(record, op="resize", payload={"rows": 39, "columns": 120})


def test_forward_input_loop_pauses_output_while_prefix_command(monkeypatch) -> None:
    if sys.platform == "win32":
        return

    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[bytes] = []

        def sendall(self, data: bytes) -> None:
            self.sent.append(data)

    reads = iter([b"\x18", b"q"])
    pause_event = threading.Event()
    observed_paused: list[bool] = []

    def fake_read(fd, count):
        return next(reads)

    def fake_handler(command: bytes) -> AttachCommand | None:
        observed_paused.append(pause_event.is_set())
        return AttachCommand("detach") if command == b"q" else None

    monkeypatch.setattr("runmux.client.os.read", fake_read)
    monkeypatch.setattr("runmux.client.os.isatty", lambda fd: True)
    monkeypatch.setattr("runmux.client.termios.tcgetattr", lambda fd: [])
    monkeypatch.setattr("runmux.client.termios.tcsetattr", lambda *args: None)
    monkeypatch.setattr("runmux.client.tty.setraw", lambda fd: None)
    monkeypatch.setattr("runmux.client.sys.stdin", Mock(fileno=lambda: 0))

    command = forward_input_loop(
        FakeSocket(),
        control_prefix=b"\x18",
        on_command=fake_handler,
        output_pause_event=pause_event,
    )

    assert command == AttachCommand("detach")
    assert observed_paused == [True]
    assert not pause_event.is_set()


def test_list_rows_show_numeric_id_and_selected_actions() -> None:
    record = RunRecord(
        id="20260611-010101-abcdef",
        numeric_id=3,
        name=None,
        status="running",
        created_at="2026-06-11T00:00:00+00:00",
        updated_at="2026-06-11T00:00:00+00:00",
        started_at="2026-06-11T00:00:00+00:00",
        ended_at=None,
        exit_code=None,
        pid=123,
        supervisor_pid=456,
        program="python",
        argv_json="[]",
        cwd=str(tmp_path := Path.cwd()),
        env_overrides_json="{}",
        port=999,
        auth_token="token",
        log_path=str(tmp_path / "output.ansi"),
        command_line="python -c print('hello')",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )

    rows = build_list_rows([record], width=80, selected_index=0)

    assert any("3" in row and "python" in row for row in rows)
    assert any("i=interact" in row and "v=view" in row for row in rows)


def test_run_defaults_rows_columns_to_terminal_size(tmp_path: Path) -> None:
    from runmux.runner import create_managed_run

    terminal_size = argparse.Namespace(lines=33, columns=111)
    with (
        patch("runmux.runner.shutil.get_terminal_size", return_value=terminal_size),
        patch("runmux.runner.start_supervisor", return_value=Mock(pid=1234)),
    ):
        started = create_managed_run(
            RunStore(tmp_path),
            program_args=["python", "-V"],
            cwd=None,
            name=None,
            force_color=True,
        )

    assert started.record.rows == 33
    assert started.record.columns == 111
    assert started.record.cwd == str(Path.cwd().resolve())


def test_start_supervisor_hides_windows_console(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    class FakePopen:
        pid = 1234

        def __init__(self, command, **kwargs) -> None:
            calls["command"] = command
            calls["kwargs"] = kwargs

    monkeypatch.setattr(runner.sys, "platform", "win32")
    monkeypatch.setattr(runner.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(runner.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(runner.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)

    start_supervisor("run-id", state_dir=tmp_path)

    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    creationflags = int(kwargs["creationflags"])
    assert creationflags & 0x08000000
    assert not creationflags & 0x00000008
    assert kwargs["stdin"] is runner.subprocess.DEVNULL
    assert kwargs["stdout"] is runner.subprocess.DEVNULL
    assert kwargs["stderr"] is runner.subprocess.DEVNULL


def test_remove_finished_cleans_leftover_supervisor_process(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run_dir = store.runs_dir / "20260611-010101-abcdef"
    run_dir.mkdir(parents=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"")
    record = store.create_run(
        run_id="20260611-010101-abcdef",
        name=None,
        status="pending",
        program="python",
        argv_json=json.dumps(["python", "-V"]),
        cwd=str(tmp_path),
        env_overrides_json=json.dumps({}),
        auth_token="token",
        log_path=log_path,
        command_line="python -V",
    )
    store.update_run(record.id, status="finished", supervisor_pid=4321)

    with patch("runmux.runner.terminate_pid") as terminate_pid:
        removed = remove_finished_runs(store)

    assert [record.numeric_id for record in removed] == [0]
    terminate_pid.assert_called_once_with(4321, force=True)
    assert store.list_runs() == []


def test_interact_tails_from_end_for_live_tui_without_tail_lines(tmp_path: Path) -> None:
    record = RunRecord(
        id="20260611-010101-abcdef",
        numeric_id=0,
        name=None,
        status="running",
        created_at="2026-06-11T00:00:00+00:00",
        updated_at="2026-06-11T00:00:00+00:00",
        started_at="2026-06-11T00:00:00+00:00",
        ended_at=None,
        exit_code=None,
        pid=123,
        supervisor_pid=456,
        program="python",
        argv_json="[]",
        cwd=str(tmp_path),
        env_overrides_json="{}",
        port=999,
        auth_token="token",
        log_path=str(tmp_path / "output.ansi"),
        command_line="python -c print('hello')",
        restart_of=None,
        duplicate_of=None,
        rows=24,
        columns=80,
    )
    store = Mock()
    store.get_run.return_value = record
    tail_kwargs: dict[str, object] = {}

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def shutdown(self, how):
            return None

    class ImmediateThread:
        def __init__(self, *, target, kwargs, name, daemon) -> None:
            self.kwargs = kwargs

        def start(self) -> None:
            tail_kwargs.update(self.kwargs)

        def join(self, timeout=None) -> None:
            return None

    with (
        patch("runmux.client.send_resize"),
        patch("runmux.client.open_input_socket", return_value=FakeSocket()),
        patch("runmux.client.forward_input_loop", return_value=AttachCommand("detach")),
        patch("runmux.client.threading.Thread", ImmediateThread),
        patch("runmux.client.set_terminal_title"),
    ):
        result = interact_run(store, run_id="0", tail_lines=None)

    assert result == 0
    assert tail_kwargs["from_end"] is True
    assert tail_kwargs["tail_lines"] is None
