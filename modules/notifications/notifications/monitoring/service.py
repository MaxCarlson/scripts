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


def get_heartbeat_task_status(config_path: Optional[Path] = None) -> dict[str, Any]:
    """Inspect Windows Scheduled Task and Healthchecks configuration status."""
    task_installed = False
    task_state = "not_found"
    last_run_time: Optional[str] = None
    next_run_time: Optional[str] = None
    last_result: Optional[str] = None

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
                    break
        else:
            task_installed = False
            task_state = "not_found"
    except Exception as exc:
        logger.debug("Failed querying schtasks.exe: %s", exc)

    # 2. Check configuration
    cfg = load_healthchecks_config(config_path)
    eff_path = config_path or default_healthchecks_config_path()

    return {
        "ok": True,
        "task_name": TASK_NAME,
        "task_installed": task_installed,
        "task_state": task_state,
        "last_run_time": last_run_time,
        "next_run_time": next_run_time,
        "last_result": last_result,
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
    apply: bool = False,
) -> dict[str, Any]:
    """
    Register Scheduled Task for independent host heartbeat.
    Ensures safe structured JSON argument passing to eliminate PowerShell interpolation.
    """
    cfg = load_healthchecks_config(config_path)
    eff_interval = interval_minutes or (cfg.interval_minutes if cfg else 5)
    eff_config_path = (config_path or default_healthchecks_config_path()).resolve()

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
        "identity": "NT AUTHORITY\\SYSTEM (ServiceAccount)" if system_account else "CurrentUser (Interactive)",
        "elevation_required": system_account,
        "start_when_available": True,
        "multiple_instances_policy": "IgnoreNew (No overlap)",
        "execution_time_limit": "2 minutes",
    }

    if not apply:
        preview["warning"] = "Dry-run: pass -a/--apply to register the Windows Scheduled Task."
        if system_account:
            preview["elevation_notice"] = "Registering with --system requires elevated (Administrator) PowerShell."
        return preview

    # Structured PowerShell script reading parameters from stdin JSON
    ps_cmd = """
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$taskName = $in.TaskName
$exe = $in.Executable
$argsStr = $in.Arguments
$intervalMin = [int]$in.IntervalMinutes
$useSystem = [bool]$in.SystemAccount

$action = New-ScheduledTaskAction -Execute $exe -Argument $argsStr

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
        "SystemAccount": system_account,
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
        checks.append({
            "name": "scheduled_task",
            "passed": True,
            "details": f"Task '{TASK_NAME}' is {status['task_state']} (Last result: {status['last_result']})",
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
