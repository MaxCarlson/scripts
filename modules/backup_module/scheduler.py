from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from backup_module.core import format_command, run_command_streaming


@dataclass
class ScheduleRequest:
    task_name: str
    python_executable: str
    config_path: Optional[str]
    frequency: str
    modifier: int
    start_time: str
    day_of_week: str | None
    backup_arguments: list[str]
    force: bool
    run_highest: bool
    print_only: bool


WINDOWS_FREQUENCY_MAP = {
    "minute": "MINUTE",
    "hourly": "HOURLY",
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "monthly": "MONTHLY",
    "once": "ONCE",
}


def build_backup_invocation(
    *,
    python_executable: str,
    config_path: Optional[str],
    backup_arguments: Sequence[str],
) -> list[str]:
    command = [
        python_executable,
        "-m",
        "backup_module",
        "backup",
    ]

    if config_path:
        command.extend(["--config_path", config_path])

    command.extend(backup_arguments)
    return command


def create_schedule(request: ScheduleRequest) -> int:
    if os.name == "nt":
        return create_windows_task(request)
    return create_cron_task(request)


def list_schedule(task_name: str | None) -> int:
    if os.name == "nt":
        command = ["schtasks", "/Query", "/FO", "LIST", "/V"]
        if task_name:
            command.extend(["/TN", task_name])
        return run_command_streaming(command)

    return list_cron_tasks(task_name)


def delete_schedule(task_name: str, *, force: bool) -> int:
    if os.name == "nt":
        command = ["schtasks", "/Delete", "/TN", task_name]
        if force:
            command.append("/F")
        return run_command_streaming(command)

    return delete_cron_task(task_name)


def run_schedule(task_name: str) -> int:
    if os.name == "nt":
        return run_command_streaming(["schtasks", "/Run", "/TN", task_name])

    print(
        "Running scheduled tasks by name is only implemented for Windows Task Scheduler.",
        file=sys.stderr,
    )
    return 2


def create_windows_task(request: ScheduleRequest) -> int:
    frequency = WINDOWS_FREQUENCY_MAP[request.frequency]
    task_command = format_command(
        build_backup_invocation(
            python_executable=request.python_executable,
            config_path=request.config_path,
            backup_arguments=request.backup_arguments,
        )
    )

    command = [
        "schtasks",
        "/Create",
        "/TN",
        request.task_name,
        "/TR",
        task_command,
        "/SC",
        frequency,
        "/ST",
        request.start_time,
    ]

    if request.modifier > 1 and frequency != "ONCE":
        command.extend(["/MO", str(request.modifier)])

    if frequency == "WEEKLY" and request.day_of_week:
        command.extend(["/D", request.day_of_week.upper()])

    if request.run_highest:
        command.extend(["/RL", "HIGHEST"])

    if request.force:
        command.append("/F")

    if request.print_only:
        print(format_command(command))
        return 0

    return run_command_streaming(command)


def cron_marker(task_name: str) -> str:
    return f"# backup_module:{task_name}"


def create_cron_task(request: ScheduleRequest) -> int:
    cron_line = build_cron_line(request)

    if request.print_only:
        print(cron_line)
        return 0

    if shutil.which("crontab") is None:
        print(
            "crontab was not found. Re-run with --print_only and install manually.",
            file=sys.stderr,
        )
        print(cron_line)
        return 2

    existing = read_crontab()
    marker = cron_marker(request.task_name)
    filtered = [line for line in existing if marker not in line]
    filtered.append(marker)
    filtered.append(cron_line)

    return write_crontab(filtered)


def list_cron_tasks(task_name: str | None) -> int:
    if shutil.which("crontab") is None:
        print("crontab was not found.", file=sys.stderr)
        return 2

    marker = cron_marker(task_name) if task_name else "# backup_module:"
    for line in read_crontab():
        if marker in line or "backup_module" in line:
            print(line)
    return 0


def delete_cron_task(task_name: str) -> int:
    if shutil.which("crontab") is None:
        print("crontab was not found.", file=sys.stderr)
        return 2

    marker = cron_marker(task_name)
    existing = read_crontab()
    filtered: list[str] = []
    skip_next = False

    for line in existing:
        if skip_next:
            skip_next = False
            continue
        if marker in line:
            skip_next = True
            continue
        filtered.append(line)

    return write_crontab(filtered)


def read_crontab() -> list[str]:
    process = subprocess.run(
        ["crontab", "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if process.returncode != 0:
        return []

    return process.stdout.splitlines()


def write_crontab(lines: Sequence[str]) -> int:
    process = subprocess.run(
        ["crontab", "-"],
        input="\n".join(lines).rstrip() + "\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if process.stdout:
        print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, end="", file=sys.stderr)

    return process.returncode


def build_cron_line(request: ScheduleRequest) -> str:
    hour, minute = parse_start_time(request.start_time)
    command = build_backup_invocation(
        python_executable=request.python_executable,
        config_path=request.config_path,
        backup_arguments=request.backup_arguments,
    )
    command_text = " ".join(sh_quote(part) for part in command)

    if request.frequency == "minute":
        schedule = f"*/{request.modifier} * * * *"
    elif request.frequency == "hourly":
        schedule = f"{minute} */{request.modifier} * * *"
    elif request.frequency == "daily":
        schedule = f"{minute} {hour} */{request.modifier} * *"
    elif request.frequency == "weekly":
        day = normalize_cron_day(request.day_of_week)
        schedule = f"{minute} {hour} * * {day}"
    elif request.frequency == "monthly":
        schedule = f"{minute} {hour} 1 */{request.modifier} *"
    elif request.frequency == "once":
        raise ValueError("Cron does not support one-shot schedules through this CLI.")
    else:
        raise ValueError(f"Unsupported frequency: {request.frequency}")

    return f"{schedule} {command_text}"


def parse_start_time(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("start_time must use HH:MM format.")

    hour = int(parts[0])
    minute = int(parts[1])

    if hour < 0 or hour > 23:
        raise ValueError("start_time hour must be between 00 and 23.")
    if minute < 0 or minute > 59:
        raise ValueError("start_time minute must be between 00 and 59.")

    return hour, minute


def normalize_cron_day(value: str | None) -> str:
    if not value:
        return "0"

    normalized = value.strip().lower()
    mapping = {
        "sun": "0",
        "sunday": "0",
        "mon": "1",
        "monday": "1",
        "tue": "2",
        "tuesday": "2",
        "wed": "3",
        "wednesday": "3",
        "thu": "4",
        "thursday": "4",
        "fri": "5",
        "friday": "5",
        "sat": "6",
        "saturday": "6",
    }

    return mapping.get(normalized, normalized)


def sh_quote(value: str) -> str:
    if os.name == "nt":
        return value

    import shlex

    return shlex.quote(value)


def default_python_executable() -> str:
    return str(Path(sys.executable).resolve())
