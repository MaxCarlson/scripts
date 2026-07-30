"""Streaming Restic execution with progress callbacks and graceful stop control."""

from __future__ import annotations

import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Mapping, Optional

from .models import ExecutionMode, ensure_utc, utc_now
from .restic import (
    ExecutionResult,
    PathInput,
    ResticCommand,
    ResticExecutionError,
    ResticInterrupted,
    ensure_backup_dry_run,
)


class ResticExecutionControl:
    """Thread-safe control surface for one active Restic process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    @property
    def stop_requested(self) -> bool:
        """Whether a graceful stop has been requested."""

        with self._lock:
            return self._stop_requested

    def attach(self, process: subprocess.Popen) -> None:
        """Attach a newly started process and honor an earlier stop request."""

        should_terminate = False
        with self._lock:
            self._process = process
            should_terminate = self._stop_requested
        if should_terminate and process.poll() is None:
            process.terminate()

    def detach(self, process: subprocess.Popen) -> None:
        """Detach the process if it is still the active process."""

        with self._lock:
            if self._process is process:
                self._process = None

    def request_stop(self) -> bool:
        """Request graceful termination and return whether a process was active."""

        process: Optional[subprocess.Popen]
        with self._lock:
            self._stop_requested = True
            process = self._process
        if process is None or process.poll() is not None:
            return False
        process.terminate()
        return True


def _append_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text.rstrip("\n"))
        handle.write("\n")


def execute_restic_monitored(
    command: ResticCommand,
    *,
    mode: ExecutionMode = ExecutionMode.RUN,
    log_path: Optional[PathInput] = None,
    line_handler: Optional[Callable[[str], None]] = None,
    control: Optional[ResticExecutionControl] = None,
    base_environment: Optional[Mapping[str, str]] = None,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    clock: Callable[[], datetime] = utc_now,
) -> ExecutionResult:
    """Execute Restic without terminal echo while streaming every output line."""

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
        raise ResticExecutionError(
            "Unable to start Restic command: {0}".format(exc)
        ) from exc

    if control is not None:
        control.attach(process)

    return_code: Optional[int] = None
    interrupted = False
    try:
        if process.stdout is not None:
            for line in process.stdout:
                output.append(line)
                if line_handler is not None:
                    try:
                        line_handler(line)
                    except Exception:
                        pass
                if resolved_log_path is not None:
                    _append_log(resolved_log_path, line)
        return_code = int(process.wait())
        interrupted = bool(control is not None and control.stop_requested)
    except KeyboardInterrupt:
        interrupted = True
        process.terminate()
        try:
            return_code = int(process.wait(timeout=15))
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = int(process.wait())
    finally:
        if control is not None:
            control.detach(process)
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
