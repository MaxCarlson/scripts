"""Safe Restic command construction and execution boundaries."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .models import ExecutionMode, ensure_utc, utc_now

PathInput = Union[os.PathLike[str], str]


class ResticCommandError(RuntimeError):
    """Base class for command construction or execution failures."""


class ResticExecutionError(ResticCommandError):
    """Raised when Restic cannot be started."""


class ResticInterrupted(ResticCommandError):
    """Raised when command execution is interrupted by the user."""

    def __init__(self, result: "ExecutionResult") -> None:
        super().__init__("Restic execution was interrupted.")
        self.result = result


@dataclass(frozen=True)
class ResticCommand:
    """A shell-free Restic command plus process environment overrides."""

    argv: Tuple[str, ...]
    environment: Mapping[str, str] = field(default_factory=dict)
    sensitive_values: Tuple[str, ...] = field(default_factory=tuple)

    def render(self, *, redacted: bool = True) -> str:
        """Render the command for logs or preview output."""

        values = list(self.argv)
        if redacted:
            values = redact_arguments(values, self.sensitive_values)
        if os.name == "nt":
            return subprocess.list2cmdline(values)
        return shlex.join(values)

    def with_arguments(self, *arguments: str) -> "ResticCommand":
        """Return a copy with additional arguments."""

        return ResticCommand(
            argv=self.argv + tuple(arguments),
            environment=dict(self.environment),
            sensitive_values=self.sensitive_values,
        )


@dataclass(frozen=True)
class ExecutionResult:
    """Result returned by the command execution boundary."""

    command: ResticCommand
    mode: ExecutionMode
    executed: bool
    return_code: Optional[int]
    started_utc: datetime
    finished_utc: datetime
    output: Tuple[str, ...]
    interrupted: bool = False

    @property
    def succeeded(self) -> bool:
        """Whether a real command completed successfully."""

        return self.executed and not self.interrupted and self.return_code == 0


def redact_arguments(
    arguments: Sequence[str],
    sensitive_values: Iterable[str] = (),
) -> List[str]:
    """Redact known secret-bearing arguments and literal sensitive values."""

    sensitive = {value for value in sensitive_values if value}
    result: List[str] = []
    redact_next = False

    for argument in arguments:
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue

        if argument in {"--password-command", "--password"}:
            result.append(argument)
            redact_next = True
            continue

        if argument.startswith("--password-command="):
            result.append("--password-command=<redacted>")
            continue
        if argument.startswith("--password="):
            result.append("--password=<redacted>")
            continue

        redacted_argument = argument
        for value in sensitive:
            if value in redacted_argument:
                redacted_argument = redacted_argument.replace(value, "<redacted>")
        result.append(redacted_argument)

    return result


def build_restic_command(
    *,
    restic_executable: str,
    repository: str,
    arguments: Sequence[str],
    password_file: Optional[str] = None,
    password: Optional[str] = None,
    password_command: Optional[str] = None,
    environment: Optional[Mapping[str, str]] = None,
) -> ResticCommand:
    """Build a Restic command with credentials supplied through environment variables."""

    if not restic_executable:
        raise ValueError("restic_executable is required.")
    if not repository:
        raise ValueError("repository is required.")

    configured_credentials = sum(
        value is not None for value in (password_file, password, password_command)
    )
    if configured_credentials > 1:
        raise ValueError(
            "Configure only one of password_file, password, or password_command."
        )

    command_environment: Dict[str, str] = dict(environment or {})
    sensitive_values: List[str] = []

    if password_file is not None:
        command_environment["RESTIC_PASSWORD_FILE"] = password_file
    elif password is not None:
        command_environment["RESTIC_PASSWORD"] = password
        sensitive_values.append(password)
    elif password_command is not None:
        command_environment["RESTIC_PASSWORD_COMMAND"] = password_command
        sensitive_values.append(password_command)

    return ResticCommand(
        argv=tuple([restic_executable, "-r", repository] + list(arguments)),
        environment=command_environment,
        sensitive_values=tuple(sensitive_values),
    )


def ensure_backup_dry_run(command: ResticCommand) -> ResticCommand:
    """Return a backup command containing Restic's `--dry-run` flag exactly once."""

    arguments = list(command.argv)
    try:
        backup_index = arguments.index("backup")
    except ValueError as exc:
        raise ValueError("Dry-run mode is valid only for Restic backup commands.") from exc

    if "--dry-run" not in arguments[backup_index + 1 :]:
        arguments.insert(backup_index + 1, "--dry-run")

    return ResticCommand(
        argv=tuple(arguments),
        environment=dict(command.environment),
        sensitive_values=command.sensitive_values,
    )


def _append_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text.rstrip("\n"))
        handle.write("\n")


def execute_restic(
    command: ResticCommand,
    *,
    mode: ExecutionMode = ExecutionMode.RUN,
    log_path: Optional[PathInput] = None,
    echo: bool = True,
    base_environment: Optional[Mapping[str, str]] = None,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    clock: Callable[[], datetime] = utc_now,
) -> ExecutionResult:
    """Execute a Restic command or preview it without starting a process.

    `ExecutionMode.PREVIEW` is a hard execution barrier: `popen_factory` is never
    called. `ExecutionMode.DRY_RUN` executes Restic with `--dry-run` and remains
    distinguishable from a real successful backup.
    """

    effective_command = (
        ensure_backup_dry_run(command)
        if mode == ExecutionMode.DRY_RUN
        else command
    )
    started = ensure_utc(clock())
    resolved_log_path = None if log_path is None else Path(log_path)

    if resolved_log_path is not None:
        _append_log(
            resolved_log_path,
            "[{0}] START mode={1} {2}".format(
                started.isoformat(),
                mode.value,
                effective_command.render(redacted=True),
            ),
        )

    if mode == ExecutionMode.PREVIEW:
        finished = ensure_utc(clock())
        if resolved_log_path is not None:
            _append_log(
                resolved_log_path,
                "[{0}] END preview executed=false".format(finished.isoformat()),
            )
        return ExecutionResult(
            command=effective_command,
            mode=mode,
            executed=False,
            return_code=None,
            started_utc=started,
            finished_utc=finished,
            output=tuple(),
        )

    process_environment = dict(
        os.environ if base_environment is None else base_environment
    )
    process_environment.update(dict(effective_command.environment))
    output: List[str] = []

    try:
        process = popen_factory(
            list(effective_command.argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=process_environment,
        )
    except OSError as exc:
        finished = ensure_utc(clock())
        if resolved_log_path is not None:
            _append_log(
                resolved_log_path,
                "[{0}] END start-failure error={1}".format(
                    finished.isoformat(),
                    exc,
                ),
            )
        raise ResticExecutionError(
            "Unable to start Restic command: {0}".format(exc)
        ) from exc

    return_code: Optional[int] = None
    interrupted = False
    try:
        if process.stdout is not None:
            for line in process.stdout:
                output.append(line)
                if echo:
                    print(line, end="")
                if resolved_log_path is not None:
                    _append_log(resolved_log_path, line)
        return_code = int(process.wait())
    except KeyboardInterrupt:
        interrupted = True
        process.terminate()
        try:
            return_code = int(process.wait(timeout=15))
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = int(process.wait())
    finally:
        finished = ensure_utc(clock())
        if resolved_log_path is not None:
            _append_log(
                resolved_log_path,
                "[{0}] END exit_code={1} interrupted={2}".format(
                    finished.isoformat(),
                    return_code,
                    str(interrupted).lower(),
                ),
            )

    result = ExecutionResult(
        command=effective_command,
        mode=mode,
        executed=True,
        return_code=return_code,
        started_utc=started,
        finished_utc=finished,
        output=tuple(output),
        interrupted=interrupted,
    )

    if interrupted:
        raise ResticInterrupted(result)
    return result
