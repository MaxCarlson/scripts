from __future__ import annotations

import sys
import types

from runmux import supervisor


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


def test_supervisor_state_allows_only_one_input_session(tmp_path) -> None:
    record = types.SimpleNamespace(id="run", log_path=str(tmp_path / "output.ansi"))
    store = types.SimpleNamespace(get_run=lambda run_id: record)
    state = supervisor.SupervisorState(store=store, record=record)

    assert state.input_session_lock.acquire(blocking=False) is True
    assert state.input_session_lock.acquire(blocking=False) is False
    state.input_session_lock.release()
