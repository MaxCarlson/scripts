"""Platform setup readiness checks shared by the scheduler CLI and TUI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cross_platform import SystemUtils

from . import windows_task


@dataclass(frozen=True)
class SetupState:
    """Whether this platform has the scheduler integration required to run."""

    complete: bool
    platform_name: str
    message: str
    setup_command: Optional[str]


def get_setup_state() -> SetupState:
    """Check whether the current OS has a usable scheduler background runner."""
    system = SystemUtils()
    if not system.is_windows():
        platform_name = "Linux" if system.is_linux() else system.os_name.title()
        return SetupState(
            complete=False,
            platform_name=platform_name,
            message=f"Scheduler setup is not available on {platform_name} yet.",
            setup_command=None,
        )

    try:
        status = windows_task.get_runner_status()
    except (OSError, RuntimeError) as exc:
        return SetupState(
            complete=False,
            platform_name="Windows",
            message=f"Could not verify the Windows scheduler runner: {exc}",
            setup_command="scheduler setup windows",
        )

    if not status.get("installed"):
        return SetupState(
            complete=False,
            platform_name="Windows",
            message="The Windows scheduler runner has not been installed.",
            setup_command="scheduler setup windows",
        )

    problems = []
    if status.get("enabled") is False or str(status.get("state", "")).lower() == "disabled":
        problems.append("the runner is disabled")
    if str(status.get("runLevel", "")).lower() != "limited":
        problems.append("the scheduler daemon is not configured for limited privileges")
    logon_type = str(status.get("logonType", "")).lower()
    if logon_type not in {"interactive", "interactivetoken"}:
        problems.append("the runner is not configured for interactive user logon")
    action_arguments = str(status.get("arguments", "")).lower()
    if "scheduler.cli" not in action_arguments or "daemon" not in action_arguments:
        problems.append("the runner action is not configured to start the scheduler daemon")

    worker = status.get("adminWorker", {})
    if not worker.get("installed"):
        problems.append("the elevated Admin task worker has not been installed")
    if worker.get("enabled") is False or str(worker.get("state", "")).lower() == "disabled":
        problems.append("the elevated Admin task worker is disabled")
    if str(worker.get("runLevel", "")).lower() != "highest":
        problems.append("the Admin task worker is not configured for highest privileges")
    if str(worker.get("user", "")).lower() != str(status.get("user", "")).lower():
        problems.append("the Admin task worker is configured for a different user")
    if str(worker.get("logonType", "")).lower() not in {"interactive", "interactivetoken"}:
        problems.append("the Admin task worker is not configured for interactive user logon")
    worker_arguments = str(worker.get("arguments", "")).lower()
    if "scheduler.cli" not in worker_arguments or "--admin-worker" not in worker_arguments:
        problems.append("the elevated worker action is not configured for Admin task execution")

    if problems:
        return SetupState(
            complete=False,
            platform_name="Windows",
            message="The Windows scheduler runner needs repair: " + "; ".join(problems) + ".",
            setup_command="scheduler setup windows",
        )

    return SetupState(
        complete=True,
        platform_name="Windows",
        message="Windows scheduler setup is complete.",
        setup_command=None,
    )


def format_setup_warning(state: SetupState) -> str:
    """Build the red CLI warning shown before any normal command or help."""
    warning = f"[SETUP REQUIRED] {state.message}"
    if state.setup_command:
        warning += f" Run `{state.setup_command}` first."
    else:
        warning += f" {state.platform_name} setup has not been implemented yet; no setup command is available."
    return f"\033[91m{warning}\033[0m"
