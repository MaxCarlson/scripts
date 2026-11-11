"""Service and lifecycle manager for Windows desktop toast notification helper."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from notifications.config import default_token_path
from notifications.delivery.windows import WindowsDeliveryProvider
from notifications.models import RenderedNotification

logger = logging.getLogger(__name__)

TASK_NAME = "ScriptsNotificationsToastHelper"
DEFAULT_PORT = 1238


def get_helper_script_path() -> Path:
    """Find the path to helper.ps1."""
    # 1. Check co-located with service
    local_path = Path(__file__).resolve().parent / "helper.ps1"
    if local_path.is_file():
        return local_path

    # 2. Check top-level windows_helper directory
    top_path = Path(__file__).resolve().parent.parent.parent / "windows_helper" / "helper.ps1"
    if top_path.is_file():
        return top_path

    return local_path


def get_helper_status(
    port: int = DEFAULT_PORT,
    token_path: Optional[Path] = None,
    timeout: float = 1.5,
) -> dict[str, Any]:
    """Inspect Windows Scheduled Task and ping loopback helper health endpoint."""
    task_installed = False
    task_state = "not_found"

    # 1. Check Scheduled Task
    try:
        cmd = ["schtasks.exe", "/query", "/tn", TASK_NAME, "/fo", "csv", "/nh"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and TASK_NAME.lower() in res.stdout.lower():
            task_installed = True
            # Parse status from csv line e.g. "\ScriptsNotificationsToastHelper","Ready"
            parts = res.stdout.strip().split(",")
            if len(parts) >= 2:
                task_state = parts[1].strip().strip('"')
            else:
                task_state = "ready"
    except Exception as exc:
        logger.debug("Failed querying schtasks.exe: %s", exc)

    # 2. Check loopback helper process
    running = False
    helper_data: dict[str, Any] = {}
    helper_url = f"http://127.0.0.1:{port}"

    effective_token_path = token_path or default_token_path()
    token = ""
    if effective_token_path.is_file():
        try:
            token = effective_token_path.read_text("utf-8").strip()
        except Exception:
            token = ""

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{helper_url}/health", headers=headers)
            if resp.status_code == 200:
                running = True
                helper_data = resp.json()
            elif resp.status_code == 401:
                # Helper is running but rejected token
                running = True
                helper_data = {"error": "unauthorized", "note": "Helper active but token mismatched"}
    except Exception:
        running = False

    return {
        "ok": True,
        "task_name": TASK_NAME,
        "task_installed": task_installed,
        "task_state": task_state,
        "helper_running": running,
        "helper_port": port,
        "token_file": str(effective_token_path),
        "helper_script": str(get_helper_script_path()),
        "helper_details": helper_data,
    }


def install_scheduled_task(
    port: int = DEFAULT_PORT,
    token_path: Optional[Path] = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Register user-level logon task for the desktop notification helper."""
    script_path = get_helper_script_path().resolve()
    effective_token_path = (token_path or default_token_path()).resolve()

    ps_args = (
        f"-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass "
        f"-File \"{script_path}\" -Port {port} -TokenPath \"{effective_token_path}\""
    )

    preview = {
        "ok": True,
        "action": "install_scheduled_task",
        "dry_run": not apply,
        "task_name": TASK_NAME,
        "executable": "powershell.exe",
        "arguments": ps_args,
        "trigger": "AtLogon (Interactive User)",
        "elevation": "LeastPrivilege (Non-Elevated / asInvoker)",
    }

    if not apply:
        preview["warning"] = "Dry-run: pass -a/--apply to register the Windows Scheduled Task."
        return preview

    # Execute registration via PowerShell to set interactive logon trigger and non-elevated principal
    ps_cmd = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '{ps_args}'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Scripts Notifications User Toast Helper' -Force | Out-Null
"""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
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
        return {"ok": False, "error": f"Exception executing schtasks registration: {exc}"}


def uninstall_scheduled_task(
    port: int = DEFAULT_PORT,
    token_path: Optional[Path] = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Unregister the scheduled task and terminate running helper."""
    preview = {
        "ok": True,
        "action": "uninstall_scheduled_task",
        "dry_run": not apply,
        "task_name": TASK_NAME,
    }

    if not apply:
        preview["warning"] = "Dry-run: pass -a/--apply to unregister the Scheduled Task and stop helper."
        return preview

    # 1. Stop helper if running
    effective_token_path = token_path or default_token_path()
    if effective_token_path.is_file():
        try:
            token = effective_token_path.read_text("utf-8").strip()
            with httpx.Client(timeout=2.0) as client:
                client.post(
                    f"http://127.0.0.1:{port}/shutdown",
                    headers={"Authorization": f"Bearer {token}"},
                )
        except Exception:
            pass

    # 2. Unregister task
    try:
        proc = subprocess.run(
            ["schtasks.exe", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True,
            text=True,
            check=False,
        )
        # Note: if task was already gone, schtasks returns code 1
        unregistered = proc.returncode == 0
        return {
            "ok": True,
            "uninstalled": unregistered,
            "message": "Scheduled task unregistered and helper stopped." if unregistered else "Scheduled task not found.",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Exception unregistering task: {exc}"}


def send_test_toast(
    port: int = DEFAULT_PORT,
    token_path: Optional[Path] = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Send a diagnostic test notification through the Windows helper."""
    effective_token_path = token_path or default_token_path()
    preview = {
        "ok": True,
        "action": "test_toast",
        "dry_run": not apply,
        "helper_url": f"http://127.0.0.1:{port}",
        "token_file": str(effective_token_path),
        "notification": {
            "title": "[SCRIPTS-NOTIFY] Test Notification",
            "body": "Verifying Windows desktop toast notification delivery via helper.",
            "severity": "info",
        },
    }

    if not apply:
        preview["warning"] = "Dry-run: pass -a/--apply to send a live test toast."
        return preview

    provider = WindowsDeliveryProvider(
        helper_url=f"http://127.0.0.1:{port}",
        token_path=effective_token_path,
    )
    notification = RenderedNotification(
        notification_id="win-test-cli",
        event_id="00000000-0000-4000-8000-000000000002",
        incident_id="inc-test-win",
        severity="info",
        title="[SCRIPTS-NOTIFY] Windows Diagnostic",
        body="Desktop notification successfully delivered via interactive user helper.",
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

    receipt = asyncio.run(provider.send(notification))
    return {
        "ok": receipt.status == "provider_accepted",
        "status": receipt.status,
        "toast_id": receipt.provider_message_id,
        "error_category": receipt.error_category,
        "error_message": receipt.error_message,
        "receipt": receipt.to_dict(),
    }
