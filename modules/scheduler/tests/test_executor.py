"""
Unit tests for scheduler task executor.
"""
import os
import subprocess
from unittest.mock import patch

import pytest
from scheduler.config import ConfigManager
from scheduler.executor import TaskExecutor
from scheduler.models import Task, ShellEnvironment


@pytest.fixture
def executor():
    cfg = ConfigManager.create_default_config()
    return TaskExecutor(config=cfg)


def test_execute_simple_command(executor):
    task = Task(
        name="EchoTest",
        environment=ShellEnvironment.TERMINAL.value,
        admin=False,
        code="echo 'Hello Scheduler Unit Test'",
    )

    result = executor.execute(task)
    assert result.success is True
    assert result.exit_code == 0
    assert "Hello Scheduler Unit Test" in result.stdout
    assert result.duration_sec >= 0.0


def test_execute_multiline_script(executor):
    code = """
@echo off
set A=foo
set B=bar
echo %A%-%B%
""" if os.name == "nt" else """
A="foo"
B="bar"
echo "$A-$B"
"""
    task = Task(
        name="MultiLineTest",
        environment=ShellEnvironment.TERMINAL.value,
        admin=False,
        code=code,
    )

    result = executor.execute(task)
    assert result.success is True
    assert result.exit_code == 0
    assert "foo-bar" in result.stdout.strip()


def test_execute_failing_command(executor):
    task = Task(
        name="FailTest",
        environment=ShellEnvironment.TERMINAL.value,
        admin=False,
        code="exit 42",
    )

    result = executor.execute(task)
    assert result.success is False
    assert result.exit_code == 42


def test_execute_unknown_environment(executor):
    task = Task(
        name="UnknownEnv",
        environment="non_existent_shell_12345",
        admin=False,
        code="echo test",
    )
    # Fallback to standard terminal allows graceful execution or returns valid result
    result = executor.execute(task)
    assert isinstance(result.exit_code, int)


def test_admin_task_runs_directly_when_windows_token_is_already_elevated(executor):
    task = Task(name="ElevatedTask", environment="terminal", admin=True, code="echo elevated")
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")

    with patch.object(executor, "_is_windows_platform", return_value=True), \
         patch.object(executor, "_is_windows_elevated", return_value=True), \
         patch("scheduler.executor.subprocess.run", return_value=completed) as run:
        result = executor.execute(task)

    assert result.success is True
    assert result.exit_code == 0
    assert "-Command" not in run.call_args.args[0]


def test_admin_task_waits_for_uac_child_and_returns_its_exit_code(executor):
    task = Task(name="ElevatedTask", environment="terminal", admin=True, code="exit 23")
    completed = subprocess.CompletedProcess(args=[], returncode=23, stdout="", stderr="child failed")

    with patch.object(executor, "_is_windows_platform", return_value=True), \
         patch.object(executor, "_is_windows_elevated", return_value=False), \
         patch("scheduler.executor.subprocess.run", return_value=completed) as run:
        result = executor.execute(task)

    command = run.call_args.args[0]
    assert command[-2] == "-Command"
    assert "$process.WaitForExit()" in command[-1]
    assert "$process.Refresh()" in command[-1]
    assert "exit $process.ExitCode" in command[-1]
    assert result.success is False
    assert result.exit_code == 23


def test_visible_runner_test_opens_new_console_without_capturing_output(executor):
    task = Task(name="ElevatedTask", environment="terminal", admin=True, code="echo elevated")
    process = type("Process", (), {"wait": lambda self, timeout=None: 0})()

    with patch.object(executor, "_is_windows_platform", return_value=True), \
         patch.object(executor, "_is_windows_elevated", return_value=True), \
         patch("scheduler.executor.subprocess.Popen", return_value=process) as popen:
        result = executor.execute(task, visible_window=True)

    assert result.success is True
    assert result.stdout == ""
    assert result.stderr == ""
    assert popen.call_args.kwargs["creationflags"] == getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)


def test_visible_admin_runner_test_fails_without_starting_uac(executor):
    task = Task(name="ElevatedTask", environment="terminal", admin=True, code="echo elevated")

    with patch.object(executor, "_is_windows_platform", return_value=True), \
         patch.object(executor, "_is_windows_elevated", return_value=False), \
         patch("scheduler.executor.subprocess.Popen") as popen, \
         patch("scheduler.executor.subprocess.run") as run:
        result = executor.execute(task, visible_window=True)

    assert result.success is False
    assert "refusing to show a UAC prompt" in result.stderr
    popen.assert_not_called()
    run.assert_not_called()
