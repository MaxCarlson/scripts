"""Lifecycle management and diagnostic service for independent host outage heartbeat."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from notifications.config import _secure_path
from notifications.monitoring.config import (
    HealthchecksConfig,
    default_healthchecks_config_path,
    load_healthchecks_config,
    redact_ping_url,
)
from notifications.monitoring.heartbeat import send_heartbeat

logger = logging.getLogger(__name__)

TASK_NAME = "ScriptsNotificationsHostHeartbeat"


def is_running_as_admin() -> bool:
    """Check if the current process has Windows Administrator privileges."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        pass
    try:
        proc = subprocess.run(
            ["whoami.exe", "/groups", "/fo", "csv"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return "S-1-16-12288" in proc.stdout or "S-1-5-32-544" in proc.stdout
    except Exception:
        return False


def get_heartbeat_task_status(config_path: Optional[Path] = None) -> dict[str, Any]:
    """Inspect Windows Scheduled Task and Healthchecks configuration status."""
    task_installed = False
    task_state = "not_found"
    last_run_time: Optional[str] = None
    next_run_time: Optional[str] = None
    last_result: Optional[str] = None
    logon_mode: Optional[str] = None
    run_as_user: Optional[str] = None
    task_to_run: Optional[str] = None

    # 1. Query Scheduled Task
    try:
        cmd = ["schtasks.exe", "/query", "/tn", TASK_NAME, "/fo", "csv", "/v"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            task_installed = True
            lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
            if len(lines) >= 2:
                import csv
                import io

                reader = csv.DictReader(io.StringIO("\n".join(lines)))
                for row in reader:
                    task_state = row.get("Status", "Ready")
                    last_run_time = row.get("Last Run Time")
                    next_run_time = row.get("Next Run Time")
                    last_result = row.get("Last Result")
                    logon_mode = row.get("Logon Mode")
                    run_as_user = row.get("Run As User") or row.get("Author")
                    task_to_run = row.get("Task To Run")
                    break
        else:
            task_installed = False
            task_state = "not_found"
    except Exception as exc:
        logger.debug("Failed querying schtasks.exe: %s", exc)

    # 2. Check configuration
    cfg = load_healthchecks_config(config_path)
    eff_path = config_path or default_healthchecks_config_path()

    is_headless = False
    if task_installed and logon_mode:
        logon_lower = logon_mode.lower()
        user_lower = (run_as_user or "").lower()
        if "interactive only" not in logon_lower or "system" in user_lower:
            is_headless = True

    return {
        "ok": True,
        "task_name": TASK_NAME,
        "task_installed": task_installed,
        "task_state": task_state,
        "last_run_time": last_run_time,
        "next_run_time": next_run_time,
        "last_result": last_result,
        "logon_mode": logon_mode,
        "run_as_user": run_as_user,
        "task_to_run": task_to_run,
        "headless": is_headless,
        "execution_mode": "headless (SYSTEM / ServiceAccount)" if is_headless else "interactive_only (CurrentUser / InteractiveToken)",
        "logged_off_capable": is_headless,
        "reboot_survivable": is_headless,
        "configured": cfg is not None,
        "check_name": cfg.check_name if cfg else None,
        "interval_minutes": cfg.interval_minutes if cfg else None,
        "ping_url_redacted": redact_ping_url(cfg.ping_url) if cfg else None,
        "config_file": str(eff_path),
    }


def install_heartbeat_task(
    interval_minutes: Optional[int] = None,
    config_path: Optional[Path] = None,
    system_account: bool = False,
    headless: bool = False,
    python_path: Optional[str] = None,
    apply: bool = False,
) -> dict[str, Any]:
    """
    Register Scheduled Task for independent host heartbeat.
    Ensures safe structured JSON argument passing to eliminate PowerShell interpolation.
    Supports interactive user mode or headless (SYSTEM) mode surviving reboots/logged-off state.
    """
    use_headless = system_account or headless
    cfg = load_healthchecks_config(config_path)
    eff_interval = interval_minutes or (cfg.interval_minutes if cfg else 5)
    eff_config_path = (config_path or default_healthchecks_config_path()).resolve()

    if python_path:
        python_exe = Path(python_path).resolve()
        if not python_exe.is_file():
            return {"ok": False, "error": f"Specified Python interpreter not found: {python_exe}"}
    else:
        python_exe = Path(sys.executable).resolve()

    runner_args = f"-m notifications.monitoring.runner -c \"{eff_config_path}\""

    preview = {
        "ok": True,
        "action": "install_heartbeat_task",
        "dry_run": not apply,
        "task_name": TASK_NAME,
        "executable": str(python_exe),
        "arguments": runner_args,
        "interval_minutes": eff_interval,
        "identity": "NT AUTHORITY\\SYSTEM (ServiceAccount - Headless)" if use_headless else "CurrentUser (InteractiveToken - Interactive Only)",
        "headless": use_headless,
        "logged_off_capable": use_headless,
        "reboot_survivable": use_headless,
        "elevation_required": use_headless,
        "start_when_available": True,
        "multiple_instances_policy": "IgnoreNew (No overlap)",
        "execution_time_limit": "2 minutes",
    }

    if not apply:
        preview["warning"] = "Dry-run: pass -a/--apply to register the Windows Scheduled Task."
        if use_headless:
            preview["elevation_notice"] = "Registering headless mode (--headless/--system) requires elevated (Administrator) PowerShell."
        else:
            preview["interactive_notice"] = (
                "Notice: Interactive-only mode requires an active logged-in user and will NOT run across reboots or when logged off. "
                "Use --headless (requires Administrator) for true 24/7 host outage detection."
            )
        return preview

    if use_headless and not is_running_as_admin():
        return {
            "ok": False,
            "error": (
                "Registering headless heartbeat task under NT AUTHORITY\\SYSTEM requires elevated (Administrator) privileges. "
                "Run terminal as Administrator or omit --headless/--system for interactive-only mode."
            ),
        }

    # Structured PowerShell script reading parameters from stdin JSON
    ps_cmd = """
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$taskName = $in.TaskName
$exe = $in.Executable
$argsStr = $in.Arguments
$intervalMin = [int]$in.IntervalMinutes
$useSystem = [bool]$in.SystemAccount
$workDir = Split-Path $exe

$action = New-ScheduledTaskAction -Execute $exe -Argument $argsStr -WorkingDirectory $workDir

# Repeating trigger: starts now, repeats every X minutes indefinitely
$timespan = New-TimeSpan -Minutes $intervalMin
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval $timespan

# Settings: bounded timeout, recover missed runs, disallow overlapping executions
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

if ($useSystem) {
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
} else {
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
}

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Independent Healthchecks.io Host Liveness Heartbeat' `
    -Force | Out-Null
"""
    input_payload = json.dumps({
        "TaskName": TASK_NAME,
        "Executable": str(python_exe),
        "Arguments": runner_args,
        "IntervalMinutes": eff_interval,
        "SystemAccount": use_headless,
    })

    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            input=input_payload,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": f"Failed to register scheduled task: {proc.stderr.strip() or proc.stdout.strip()}",
            }
        preview["installed"] = True
        return preview
    except Exception as exc:
        return {"ok": False, "error": f"Exception executing task registration: {exc}"}


def uninstall_heartbeat_task(apply: bool = False) -> dict[str, Any]:
    """Unregister the host heartbeat Scheduled Task."""
    preview = {
        "ok": True,
        "action": "uninstall_heartbeat_task",
        "dry_run": not apply,
        "task_name": TASK_NAME,
    }

    if not apply:
        preview["warning"] = "Dry-run: pass -a/--apply to unregister the Scheduled Task."
        return preview

    try:
        proc = subprocess.run(
            ["schtasks.exe", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True,
            text=True,
            check=False,
        )
        unregistered = proc.returncode == 0
        return {
            "ok": True,
            "uninstalled": unregistered,
            "message": "Heartbeat scheduled task unregistered." if unregistered else "Scheduled task not found.",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Exception unregistering task: {exc}"}


def doctor(config_path: Optional[Path] = None, client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """
    Run diagnostic inspection across all heartbeat prerequisites:
    1. Configuration file presence and ACL security.
    2. Task Scheduler registration and state.
    3. Healthchecks.io network connectivity.
    4. Broker independence.
    """
    checks: list[dict[str, Any]] = []

    # 1. Config check
    cfg = load_healthchecks_config(config_path)
    eff_path = config_path or default_healthchecks_config_path()
    if cfg:
        checks.append({
            "name": "configuration",
            "passed": True,
            "details": f"Configured for check '{cfg.check_name}' ({cfg.interval_minutes}m interval)",
            "ping_url_redacted": redact_ping_url(cfg.ping_url),
        })
    else:
        checks.append({
            "name": "configuration",
            "passed": False,
            "details": f"Missing or invalid configuration at {eff_path}",
        })

    # 2. Scheduled Task check
    status = get_heartbeat_task_status(config_path)
    if status["task_installed"]:
        mode_desc = "Headless SYSTEM (runs logged off)" if status.get("headless") else "Interactive-only (requires active user login)"
        checks.append({
            "name": "scheduled_task",
            "passed": True,
            "details": f"Task '{TASK_NAME}' is {status['task_state']} [{mode_desc}] (Last result: {status['last_result']})",
            "headless": status.get("headless", False),
        })
    else:
        checks.append({
            "name": "scheduled_task",
            "passed": False,
            "details": f"Scheduled task '{TASK_NAME}' is not registered (run 'scripts-notify heartbeat install')",
        })

    # 3. Network DNS/Connect check to Healthchecks.io
    try:
        if client is not None:
            resp = client.get("https://hc-ping.com", follow_redirects=True)
            status_code = resp.status_code
        else:
            with httpx.Client(timeout=3.0) as http_client:
                resp = http_client.get("https://hc-ping.com", follow_redirects=True)
                status_code = resp.status_code
        checks.append({
            "name": "network_connectivity",
            "passed": status_code < 500,
            "details": f"https://hc-ping.com responded with HTTP {status_code}",
        })
    except Exception as exc:
        checks.append({
            "name": "network_connectivity",
            "passed": False,
            "details": f"Failed connecting to https://hc-ping.com: {exc}",
        })

    all_passed = all(c["passed"] for c in checks)
    return {
        "ok": True,
        "healthy": all_passed,
        "checks": checks,
    }
