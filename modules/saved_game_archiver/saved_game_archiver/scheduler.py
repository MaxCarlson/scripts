from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from .retention import parse_interval


WATCH_MARKER = "# saved_game_archiver:watch"
MAINT_MARKER = "# saved_game_archiver:maintenance"


def build_python_command(config_path: Path | None, *args: str) -> list[str]:
    command = [str(Path(sys.executable).resolve()), "-m", "saved_game_archiver"]
    if config_path is not None:
        command.extend(["-c", str(config_path)])
    command.extend(args)
    return command


def scheduler_plan(config: dict, config_path: Path | None) -> list[list[str] | str]:
    if os.name == "nt":
        watch_name = config["scheduler"]["watch_task_name"]
        maintenance_name = config["scheduler"]["maintenance_task_name"]
        watch_command = subprocess.list2cmdline(build_python_command(config_path, "watch", "-P"))
        maintenance_command = subprocess.list2cmdline(build_python_command(config_path, "run", "cycle"))
        interval_seconds = parse_interval(config["backup"]["maintenance_interval"])
        minutes = max(1, int(round(interval_seconds / 60.0)))
        return [
            ["schtasks", "/Create", "/TN", watch_name, "/TR", watch_command, "/SC", "ONLOGON", "/F"],
            [
                "schtasks", "/Create", "/TN", maintenance_name, "/TR", maintenance_command,
                "/SC", "MINUTE", "/MO", str(minutes), "/F",
            ],
        ]
    interval_seconds = parse_interval(config["backup"]["maintenance_interval"])
    minutes = max(1, int(round(interval_seconds / 60.0)))
    watch = f"@reboot {_shell_command(build_python_command(config_path, 'watch', '-P'))}"
    maintenance = f"*/{minutes} * * * * {_shell_command(build_python_command(config_path, 'run', 'cycle'))}"
    return [WATCH_MARKER, watch, MAINT_MARKER, maintenance]


def install_scheduler(config: dict, config_path: Path | None, *, apply: bool) -> list[str]:
    plan = scheduler_plan(config, config_path)
    rendered: list[str] = []
    if os.name == "nt":
        for item in plan:
            assert isinstance(item, list)
            rendered.append(subprocess.list2cmdline(item))
            if apply:
                process = subprocess.run(item, check=False)
                if process.returncode != 0:
                    raise RuntimeError(f"Task Scheduler command failed ({process.returncode}): {rendered[-1]}")
        return rendered
    lines = [str(item) for item in plan]
    rendered.extend(lines)
    if not apply:
        return rendered
    if shutil.which("crontab") is None:
        raise RuntimeError("crontab was not found; use the preview output to install scheduling manually")
    existing = _read_crontab()
    filtered = _remove_marked(existing)
    filtered.extend(lines)
    _write_crontab(filtered)
    return rendered


def remove_scheduler(config: dict, *, apply: bool) -> list[str]:
    rendered: list[str] = []
    if os.name == "nt":
        for name in (config["scheduler"]["watch_task_name"], config["scheduler"]["maintenance_task_name"]):
            command = ["schtasks", "/Delete", "/TN", name, "/F"]
            rendered.append(subprocess.list2cmdline(command))
            if apply:
                subprocess.run(command, check=False)
        return rendered
    existing = _read_crontab() if shutil.which("crontab") else []
    filtered = _remove_marked(existing)
    rendered = filtered
    if apply and shutil.which("crontab"):
        _write_crontab(filtered)
    return rendered


def scheduler_health(config: dict) -> tuple[bool, list[str]]:
    if os.name == "nt":
        missing: list[str] = []
        for name in (config["scheduler"]["watch_task_name"], config["scheduler"]["maintenance_task_name"]):
            process = subprocess.run(
                ["schtasks", "/Query", "/TN", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if process.returncode != 0:
                missing.append(name)
        return not missing, missing
    if shutil.which("crontab") is None:
        return False, ["crontab unavailable"]
    text = "\n".join(_read_crontab())
    missing = [marker for marker in (WATCH_MARKER, MAINT_MARKER) if marker not in text]
    return not missing, missing


def _shell_command(parts: Iterable[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _read_crontab() -> list[str]:
    process = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    return process.stdout.splitlines() if process.returncode == 0 else []


def _remove_marked(lines: list[str]) -> list[str]:
    output: list[str] = []
    skip = False
    for line in lines:
        if skip:
            skip = False
            continue
        if line in (WATCH_MARKER, MAINT_MARKER):
            skip = True
            continue
        output.append(line)
    return output


def _write_crontab(lines: list[str]) -> None:
    process = subprocess.run(
        ["crontab", "-"], input="\n".join(lines).rstrip() + "\n", text=True, capture_output=True, check=False
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or "Failed to update crontab")
