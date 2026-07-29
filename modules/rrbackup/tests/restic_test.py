from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rrbackup.models import ExecutionMode
from rrbackup.restic import (
    ResticExecutionError,
    ResticInterrupted,
    build_restic_command,
    ensure_backup_dry_run,
    execute_restic,
    redact_arguments,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


class FakeProcess:
    def __init__(self, lines=None, return_code=0):
        self.stdout = iter(lines or [])
        self.return_code = return_code
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        return self.return_code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class InterruptingOutput:
    def __iter__(self):
        return self

    def __next__(self):
        raise KeyboardInterrupt


class InterruptingProcess(FakeProcess):
    def __init__(self):
        super().__init__(return_code=130)
        self.stdout = InterruptingOutput()


def ticking_clock():
    values = iter([NOW, NOW + timedelta(seconds=1)])
    return lambda: next(values)


def test_build_command_uses_environment_for_password_file():
    command = build_restic_command(
        restic_executable="restic",
        repository="repo",
        arguments=["snapshots", "--json"],
        password_file="password.txt",
    )

    assert command.argv == ("restic", "-r", "repo", "snapshots", "--json")
    assert command.environment == {"RESTIC_PASSWORD_FILE": "password.txt"}


def test_build_command_rejects_multiple_credential_sources():
    with pytest.raises(ValueError, match="only one"):
        build_restic_command(
            restic_executable="restic",
            repository="repo",
            arguments=["snapshots"],
            password_file="password.txt",
            password="secret",
        )


def test_redaction_handles_secret_options_and_literals():
    assert redact_arguments(
        ["restic", "--password", "secret", "--password-command=echo token", "secret"],
        ["secret"],
    ) == [
        "restic",
        "--password",
        "<redacted>",
        "--password-command=<redacted>",
        "<redacted>",
    ]


def test_ensure_dry_run_adds_flag_exactly_once():
    command = build_restic_command(
        restic_executable="restic",
        repository="repo",
        arguments=["backup", "source"],
    )

    first = ensure_backup_dry_run(command)
    second = ensure_backup_dry_run(first)

    assert first.argv.count("--dry-run") == 1
    assert second.argv.count("--dry-run") == 1


def test_ensure_dry_run_rejects_non_backup_command():
    command = build_restic_command(
        restic_executable="restic",
        repository="repo",
        arguments=["snapshots"],
    )

    with pytest.raises(ValueError, match="backup commands"):
        ensure_backup_dry_run(command)


def test_preview_is_hard_execution_barrier(tmp_path):
    command = build_restic_command(
        restic_executable="restic",
        repository="repo",
        arguments=["backup", "source"],
    )

    def forbidden_popen(*args, **kwargs):
        pytest.fail("preview must not invoke Popen")

    result = execute_restic(
        command,
        mode=ExecutionMode.PREVIEW,
        popen_factory=forbidden_popen,
        clock=ticking_clock(),
        log_path=tmp_path / "preview.log",
    )

    assert not result.executed
    assert result.return_code is None
    assert "executed=false" in (tmp_path / "preview.log").read_text(encoding="utf-8")


def test_dry_run_executes_with_flag_and_preserves_mode(tmp_path):
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        return FakeProcess(["summary\n"], return_code=0)

    command = build_restic_command(
        restic_executable="restic",
        repository="repo",
        arguments=["backup", "source"],
        password_file="password.txt",
    )
    result = execute_restic(
        command,
        mode=ExecutionMode.DRY_RUN,
        popen_factory=fake_popen,
        clock=ticking_clock(),
        echo=False,
        log_path=tmp_path / "dry-run.log",
        base_environment={"BASE": "1"},
    )

    assert result.succeeded
    assert result.mode == ExecutionMode.DRY_RUN
    assert result.output == ("summary\n",)
    assert captured["argv"].count("--dry-run") == 1
    assert captured["env"]["BASE"] == "1"
    assert captured["env"]["RESTIC_PASSWORD_FILE"] == "password.txt"


def test_nonzero_return_is_reported_without_being_successful():
    command = build_restic_command(
        restic_executable="restic",
        repository="repo",
        arguments=["check"],
    )
    result = execute_restic(
        command,
        popen_factory=lambda *args, **kwargs: FakeProcess(return_code=3),
        clock=ticking_clock(),
        echo=False,
    )

    assert result.executed
    assert result.return_code == 3
    assert not result.succeeded


def test_start_failure_raises_actionable_error(tmp_path):
    command = build_restic_command(
        restic_executable="missing-restic",
        repository="repo",
        arguments=["check"],
    )

    def fail_start(*args, **kwargs):
        raise FileNotFoundError("missing-restic")

    with pytest.raises(ResticExecutionError, match="Unable to start"):
        execute_restic(
            command,
            popen_factory=fail_start,
            clock=ticking_clock(),
            log_path=tmp_path / "failure.log",
        )

    assert "start-failure" in (tmp_path / "failure.log").read_text(encoding="utf-8")


def test_keyboard_interrupt_terminates_child_and_returns_result():
    process = InterruptingProcess()
    command = build_restic_command(
        restic_executable="restic",
        repository="repo",
        arguments=["backup", "source"],
    )

    with pytest.raises(ResticInterrupted) as error:
        execute_restic(
            command,
            popen_factory=lambda *args, **kwargs: process,
            clock=ticking_clock(),
            echo=False,
        )

    assert process.terminated
    assert error.value.result.interrupted
    assert error.value.result.return_code == 130
