"""
Unit tests for scheduler task executor.
"""
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
