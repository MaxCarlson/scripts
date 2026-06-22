from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from runmux import supervisor
from runmux.store import RunStore


def create_supervisor_record(store: RunStore, tmp_path: Path):
    run_id = "20260622-020202-abcdef"
    run_dir = store.runs_dir / run_id
    run_dir.mkdir(parents=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"")
    return store.create_run(
        run_id=run_id,
        name=None,
        status="running",
        program="python",
        argv_json=json.dumps(["python", "-V"]),
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="token",
        log_path=log_path,
        command_line="python -V",
    )


def test_launch_windows_child_falls_back_when_pty_unavailable(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_pipe_child(argv, *, cwd, env):
        called["argv"] = argv
        called["cwd"] = cwd
        called["env"] = env
        return "pipe"

    monkeypatch.setattr(supervisor, "launch_pipe_child", fake_pipe_child)
    monkeypatch.setattr(
        supervisor,
        "launch_windows_pty_child",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("conpty unavailable")),
    )

    result = supervisor.launch_windows_child(
        ["python", "-V"],
        cwd="C:\\work",
        env={"PATH": "x"},
        rows=40,
        columns=120,
    )

    assert result == "pipe"
    assert called == {"argv": ["python", "-V"], "cwd": "C:\\work", "env": {"PATH": "x"}}


def test_launch_windows_pty_child_uses_pywinpty_dimensions(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakePtyProcess:
        @staticmethod
        def spawn(argv, *, cwd, env, dimensions, backend):
            calls["argv"] = argv
            calls["cwd"] = cwd
            calls["env"] = env
            calls["dimensions"] = dimensions
            calls["backend"] = backend
            return "pty"

    fake_backend = types.SimpleNamespace(ConPTY=0)
    monkeypatch.setitem(
        sys.modules,
        "winpty",
        types.SimpleNamespace(PtyProcess=FakePtyProcess, Backend=fake_backend),
    )

    result = supervisor.launch_windows_pty_child(
        ["python", "-V"],
        cwd="C:\\work",
        env={"PATH": "x"},
        rows=40,
        columns=120,
    )

    assert result == "pty"
    assert calls == {
        "argv": ["python", "-V"],
        "cwd": "C:\\work",
        "env": {"PATH": "x"},
        "dimensions": (40, 120),
        "backend": 0,
    }


def test_launch_pipe_child_hides_windows_console(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakePopen:
        def __init__(self, argv, **kwargs) -> None:
            calls["argv"] = argv
            calls["kwargs"] = kwargs

    monkeypatch.setattr(supervisor.sys, "platform", "win32")
    monkeypatch.setattr(
        supervisor.subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        0x00000200,
        raising=False,
    )
    monkeypatch.setattr(supervisor.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(supervisor.subprocess, "Popen", FakePopen)

    supervisor.launch_pipe_child(["python", "-V"], cwd="C:\\work", env={"PATH": "x"})

    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    assert int(kwargs["creationflags"]) & 0x08000000


def test_supervisor_state_writes_input_to_windows_pty(monkeypatch, tmp_path) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, value: str) -> None:
            self.writes.append(value)

    process = FakeProcess()
    record = types.SimpleNamespace(id="run", log_path=str(tmp_path / "output.ansi"))
    store = types.SimpleNamespace(get_run=lambda run_id: record)
    state = supervisor.SupervisorState(store=store, record=record)
    state.process = process
    state.windows_pty = True

    monkeypatch.setattr(supervisor.sys, "platform", "win32")
    state.write_input(b"hello\r\n")

    assert process.writes == ["hello\r\n"]


def test_respond_to_terminal_queries_writes_basic_answers(tmp_path) -> None:
    class FakeState:
        def __init__(self) -> None:
            self.inputs: list[bytes] = []

        def write_input(self, data: bytes) -> None:
            self.inputs.append(data)

    state = FakeState()

    supervisor.respond_to_terminal_queries(state, "\x1b[1t\x1b[c\x1b[6n")

    assert state.inputs == [b"\x1b[?1;2c", b"\x1b[1;1R"]


def test_get_process_exit_code_for_live_windows_pty() -> None:
    class FakePtyProcess:
        def isalive(self) -> bool:
            return True

    assert supervisor.get_process_exit_code(FakePtyProcess(), windows_pty=True) is None


def test_input_lock_coordinator_transfers_fifo_after_tenure_and_idle() -> None:
    lock = supervisor.InputLockCoordinator(
        minimum_tenure_seconds=10.0,
        idle_transfer_seconds=0.25,
    )
    lock.add_interactor("first", now=0.0)
    lock.request("second", now=1.0)
    lock.request("third", now=2.0)

    assert lock.holder_id == "first"
    assert list(lock.queue) == ["second", "third"]
    assert lock.maybe_transfer(now=9.99) is False
    assert lock.maybe_transfer(now=10.0) is True
    assert lock.holder_id == "second"
    assert lock.queue_position("third") == 1


def test_input_lock_coordinator_waits_for_holder_input_idle() -> None:
    lock = supervisor.InputLockCoordinator(
        minimum_tenure_seconds=1.0,
        idle_transfer_seconds=0.25,
    )
    lock.add_interactor("first", now=0.0)
    lock.request("second", now=0.1)
    lock.note_input_complete("first", now=1.0)

    assert lock.maybe_transfer(now=1.20) is False
    assert lock.maybe_transfer(now=1.25) is True
    assert lock.holder_id == "second"


def test_input_lock_holder_disconnects_into_next_request() -> None:
    lock = supervisor.InputLockCoordinator()
    lock.add_interactor("first", now=0.0)
    lock.request("second", now=1.0)

    lock.remove("first", now=2.0)

    assert lock.holder_id == "second"


def test_supervisor_state_accepts_input_only_from_lock_holder(monkeypatch, tmp_path: Path) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, value: str) -> None:
            self.writes.append(value)

    store = RunStore(tmp_path)
    record = create_supervisor_record(store, tmp_path)
    state = supervisor.SupervisorState(store=store, record=record)
    process = FakeProcess()
    state.process = process
    state.windows_pty = True
    monkeypatch.setattr(supervisor.sys, "platform", "win32")

    first = state.register_attachment("first", "interact")
    second = state.register_attachment("second", "interact")
    queued = state.request_input_lock("second")

    assert first["session_holds_lock"] is True
    assert second["session_holds_lock"] is False
    assert queued["session_queue_position"] == 1
    assert state.write_session_input("second", b"blocked") is False
    assert state.write_session_input("first", b"accepted") is True
    assert process.writes == ["accepted"]

    state.disconnect_attachment("first")

    assert state.session_status("second")["session_holds_lock"] is True
    assert state.write_session_input("second", b"next") is True
    assert process.writes == ["accepted", "next"]


def test_supervisor_state_expires_stale_lock_holder(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = create_supervisor_record(store, tmp_path)
    state = supervisor.SupervisorState(store=store, record=record)
    state.register_attachment("first", "interact")
    state.register_attachment("second", "interact")
    state.request_input_lock("second")
    state.sessions["first"].last_heartbeat = 0.0

    state.expire_stale_sessions(now=10.0)

    assert "first" not in state.sessions
    assert state.input_lock.holder_id == "second"
