from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rrbackup.models import ExecutionMode
from rrbackup.monitored_restic import ResticExecutionControl, execute_restic_monitored
from rrbackup.restic import ResticCommand, ResticInterrupted


UTC = timezone.utc
START = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)


class FakeProcess:
    def __init__(self, lines=()) -> None:
        self.stdout = iter(lines)
        self.terminated = False
        self.killed = False
        self.wait_calls = []

    def poll(self):
        return None if not self.terminated and not self.killed else 130

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None) -> int:
        self.wait_calls.append(timeout)
        return 130 if self.terminated or self.killed else 0


def clock_values():
    values = iter((START, START + timedelta(seconds=5)))
    return lambda: next(values)


def test_monitored_executor_streams_lines_without_terminal_echo() -> None:
    process = FakeProcess(("first\n", "second\n"))
    observed = []
    result = execute_restic_monitored(
        ResticCommand(argv=("restic", "version")),
        mode=ExecutionMode.RUN,
        line_handler=observed.append,
        popen_factory=lambda *args, **kwargs: process,
        clock=clock_values(),
    )

    assert observed == ["first\n", "second\n"]
    assert result.output == ("first\n", "second\n")
    assert result.return_code == 0
    assert result.interrupted is False


def test_stop_requested_before_process_start_is_honored_on_attach() -> None:
    process = FakeProcess()
    control = ResticExecutionControl()
    assert control.request_stop() is False

    with pytest.raises(ResticInterrupted) as captured:
        execute_restic_monitored(
            ResticCommand(argv=("restic", "version")),
            control=control,
            popen_factory=lambda *args, **kwargs: process,
            clock=clock_values(),
        )

    assert process.terminated is True
    assert captured.value.result.interrupted is True
    assert captured.value.result.return_code == 130


def test_active_process_can_be_stopped_through_control() -> None:
    process = FakeProcess()
    control = ResticExecutionControl()
    control.attach(process)

    assert control.request_stop() is True
    assert process.terminated is True
    assert control.stop_requested is True

    control.detach(process)
