from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from runmux.client import interact_run
from runmux.ipc import IpcError
from runmux.runner import RunnerError, wait_for_supervisor_ready
from runmux.store import RunStore


class LiveSupervisor:
    pid = 4321

    def poll(self) -> None:
        return None


def create_run(store: RunStore, tmp_path: Path):
    run_id = "20260622-010101-abcdef"
    run_dir = store.runs_dir / run_id
    run_dir.mkdir(parents=True)
    log_path = run_dir / "output.ansi"
    log_path.write_bytes(b"")
    return store.create_run(
        run_id=run_id,
        name=None,
        status="pending",
        program="python",
        argv_json=json.dumps(["python", "-V"]),
        cwd=str(tmp_path),
        env_overrides_json="{}",
        auth_token="token",
        log_path=log_path,
        command_line="python -V",
    )


def test_wait_for_supervisor_ready_handles_delayed_port(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = create_run(store, tmp_path)
    attempts = 0

    def get_run(run_id: str):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            store.mark_started(run_id=record.id, pid=123, supervisor_pid=4321, port=9876)
        return RunStore.get_run(store, run_id)

    with (
        patch.object(store, "get_run", side_effect=get_run),
        patch("runmux.runner.request_json", return_value={"ok": True}),
        patch("runmux.runner.time.sleep"),
    ):
        ready = wait_for_supervisor_ready(
            store,
            run_id=record.id,
            supervisor=LiveSupervisor(),
            timeout_seconds=1,
        )

    assert ready.status == "running"
    assert ready.port == 9876


def test_wait_for_supervisor_ready_reports_terminal_failure(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = create_run(store, tmp_path)
    record.log_file.write_text("first line\nspecific startup failure\n", encoding="utf-8")
    store.mark_finished(run_id=record.id, status="failed", exit_code=7)

    with pytest.raises(RunnerError, match="specific startup failure") as error:
        wait_for_supervisor_ready(
            store,
            run_id=record.id,
            supervisor=LiveSupervisor(),
            timeout_seconds=1,
        )

    assert "exit_code=7" in str(error.value)


def test_wait_for_supervisor_ready_timeout_leaves_attach_hint(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = create_run(store, tmp_path)

    with pytest.raises(RunnerError, match=r"runmux view -i 0"):
        wait_for_supervisor_ready(
            store,
            run_id=record.id,
            supervisor=LiveSupervisor(),
            timeout_seconds=0,
        )

    assert store.get_run(record.id).status == "pending"


def test_interact_cleans_tail_thread_when_input_socket_fails(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = create_run(store, tmp_path)
    record = store.mark_started(run_id=record.id, pid=123, supervisor_pid=4321, port=9876)
    thread_state = SimpleNamespace(started=False, joined=False, should_stop=None)

    class FakeThread:
        def __init__(self, *, target, kwargs, name, daemon) -> None:
            thread_state.should_stop = kwargs["should_stop"]

        def start(self) -> None:
            thread_state.started = True

        def join(self) -> None:
            thread_state.joined = True

    with (
        patch("runmux.client.send_resize"),
        patch("runmux.client.threading.Thread", FakeThread),
        patch("runmux.client.open_input_socket", side_effect=IpcError("not ready")),
        patch("runmux.client.set_terminal_title"),
        pytest.raises(IpcError, match="not ready"),
    ):
        interact_run(store, run_id=record.id, tail_lines=None)

    assert thread_state.started is True
    assert thread_state.joined is True
    assert thread_state.should_stop() is True
