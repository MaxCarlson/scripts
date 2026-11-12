"""Outbox delivery worker, retry dispatcher, and background task management."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from notifications.config import default_db_path
from notifications.delivery.base import DeliveryProvider
from notifications.exceptions import LockContentionError, LockError, LockSetupError
from notifications.models import RenderedNotification
from notifications.storage import StorageEngine

logger = logging.getLogger(__name__)

OUTBOX_TASK_NAME = "ScriptsNotificationsOutboxDispatcher"

_TOKEN_PATTERN = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}")


def _sanitize_error_message(msg: str) -> str:
    """Strip secrets, bot tokens, and bound error message length."""
    if not msg:
        return ""
    cleaned = _TOKEN_PATTERN.sub("[REDACTED_TOKEN]", msg)
    return cleaned[:512]


def default_outbox_lock_path(db_path: Optional[Union[str, Path]] = None) -> Path:
    """Return canonical advisory lock file path for the outbox dispatcher."""
    if db_path is None:
        db_path = default_db_path()
    return Path(db_path).resolve().parent / ".outbox_worker.lock"


class OutboxLock:
    """Cross-process advisory file lock for outbox dispatcher executions."""

    def __init__(self, lock_path: Optional[Union[str, Path]] = None):
        if lock_path is None:
            lock_path = default_outbox_lock_path()
        self.lock_path = Path(lock_path).resolve()
        self._fd: Optional[Any] = None

    def __enter__(self) -> "OutboxLock":
        # 1. Directory and file setup
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = open(self.lock_path, "a+")
        except (PermissionError, OSError) as exc:
            self._cleanup_fd()
            raise LockSetupError(
                f"Failed to access or create outbox lock file at {self.lock_path}: {exc}"
            ) from exc
        except Exception as exc:
            self._cleanup_fd()
            raise LockSetupError(
                f"Unexpected error creating outbox lock file at {self.lock_path}: {exc}"
            ) from exc

        # 2. Acquire exclusive advisory lock
        try:
            if sys.platform == "win32":
                import msvcrt

                self._fd.seek(0)
                try:
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                except (OSError, PermissionError) as exc:
                    self._cleanup_fd()
                    raise LockContentionError(
                        f"Another outbox dispatcher is currently running (lock held at {self.lock_path})."
                    ) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except (BlockingIOError, OSError) as exc:
                    self._cleanup_fd()
                    import errno

                    if (
                        isinstance(exc, BlockingIOError)
                        or getattr(exc, "errno", None)
                        in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK)
                    ):
                        raise LockContentionError(
                            f"Another outbox dispatcher is currently running (lock held at {self.lock_path})."
                        ) from exc
                    raise LockSetupError(
                        f"Unexpected error acquiring lock at {self.lock_path}: {exc}"
                    ) from exc
        except LockError:
            raise
        except Exception as exc:
            self._cleanup_fd()
            raise LockSetupError(
                f"Unexpected locking API error for {self.lock_path}: {exc}"
            ) from exc

        # 3. Record PID and timestamp into lock file for diagnostics
        try:
            self._fd.seek(0)
            self._fd.truncate()
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._fd.write(f"pid={os.getpid()}\nstarted_at={now}\n")
            self._fd.flush()
        except Exception:
            pass

        return self

    def _cleanup_fd(self) -> None:
        if self._fd is not None:
            try:
                self._fd.close()
            except Exception:
                pass
            self._fd = None

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    try:
                        self._fd.seek(0)
                        msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl

                    try:
                        fcntl.flock(self._fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
            finally:
                self._cleanup_fd()


class OutboxWorker:
    """Processes pending outbox items and dispatches to registered providers."""

    def __init__(self, storage: StorageEngine, providers: dict[str, DeliveryProvider]) -> None:
        self.storage = storage
        self.providers = providers

    async def process_pending_once(self, limit: int = 50) -> int:
        """Claim and dispatch up to `limit` pending outbox items."""
        items = self.storage.list_pending_outbox(limit=limit)
        processed_count = 0

        for item in items:
            if not self.storage.claim_outbox_item(item.outbox_id):
                continue

            event = self.storage.get_event(item.event_id)
            if not event:
                self.storage.record_delivery_attempt(
                    outbox_id=item.outbox_id,
                    status="terminal_error",
                    error_category="missing_event",
                    error_message=f"Event '{item.event_id}' not found in journal",
                )
                processed_count += 1
                continue

            provider = self.providers.get(item.provider_id)
            if not provider:
                self.storage.record_delivery_attempt(
                    outbox_id=item.outbox_id,
                    status="terminal_error",
                    error_category="unknown_provider",
                    error_message=f"Delivery provider '{item.provider_id}' is not registered",
                )
                processed_count += 1
                continue

            # Render notification
            rendered = RenderedNotification(
                notification_id=str(item.outbox_id),
                event_id=event.event_id,
                incident_id=item.incident_id,
                severity=event.severity,
                title=f"[{event.severity.upper()}] {event.summary}",
                body=f"Source: {event.source}\nKind: {event.kind}\nTime: {event.occurred_at}",
                deep_link=None,
                created_at=item.created_at,
            )

            start_time = time.time()
            try:
                receipt = await provider.send(rendered)
            except Exception as exc:
                sanitized_msg = _sanitize_error_message(str(exc))
                logger.exception("Provider '%s' raised an unhandled exception: %s", item.provider_id, sanitized_msg)
                self.storage.record_delivery_attempt(
                    outbox_id=item.outbox_id,
                    status="retryable_error",
                    error_category="provider_exception",
                    error_message=sanitized_msg,
                )
                processed_count += 1
                continue

            duration_ms = int((time.time() - start_time) * 1000)
            sanitized_receipt_error = _sanitize_error_message(receipt.error_message or "") or None
            self.storage.record_delivery_attempt(
                outbox_id=item.outbox_id,
                status=receipt.status,
                provider_message_id=receipt.provider_message_id,
                duration_ms=duration_ms,
                error_category=receipt.error_category,
                error_message=sanitized_receipt_error,
                retry_after_seconds=receipt.retry_after_seconds,
            )
            processed_count += 1

        return processed_count

    def recover_stalled(self, stalled_seconds: float = 300.0) -> int:
        """Reset items stuck in 'attempting' state due to worker interruption."""
        return self.storage.reset_stalled_outbox_items(stalled_seconds=stalled_seconds)

    def run_dispatch(
        self,
        limit: int = 50,
        stalled_seconds: float = 300.0,
        lock: Optional[OutboxLock] = None,
    ) -> dict[str, Any]:
        """Execute stalled recovery and pending dispatch under exclusive advisory lock."""
        import concurrent.futures

        if lock is None:
            lock = OutboxLock(default_outbox_lock_path(self.storage.db_path))

        with lock:
            stalled_count = self.recover_stalled(stalled_seconds=stalled_seconds)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    processed = pool.submit(asyncio.run, self.process_pending_once(limit=limit)).result()
            else:
                processed = asyncio.run(self.process_pending_once(limit=limit))

            return {
                "ok": True,
                "recovered_stalled": stalled_count,
                "processed": processed,
            }

    async def async_run_dispatch(
        self,
        limit: int = 50,
        stalled_seconds: float = 300.0,
        lock: Optional[OutboxLock] = None,
    ) -> dict[str, Any]:
        """Async variant of run_dispatch for callers already in an async event loop."""
        if lock is None:
            lock = OutboxLock(default_outbox_lock_path(self.storage.db_path))

        with lock:
            stalled_count = self.recover_stalled(stalled_seconds=stalled_seconds)
            processed = await self.process_pending_once(limit=limit)
            return {
                "ok": True,
                "recovered_stalled": stalled_count,
                "processed": processed,
            }


def get_outbox_task_status() -> dict[str, Any]:
    """Inspect Windows Scheduled Task status for the Outbox Dispatcher."""
    if sys.platform != "win32":
        return {
            "ok": True,
            "task_name": OUTBOX_TASK_NAME,
            "task_installed": False,
            "state": "UnsupportedPlatform",
        }

    ps_cmd = """
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$taskName = $in.TaskName
try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
    $action = $task.Actions | Select-Object -First 1
    [PSCustomObject]@{
        Installed = $true
        State = [string]$task.State
        LastRunTime = if ($info -and $info.LastRunTime) { $info.LastRunTime.ToString("o") } else { $null }
        NextRunTime = if ($info -and $info.NextRunTime) { $info.NextRunTime.ToString("o") } else { $null }
        LastTaskResult = if ($info) { [int]$info.LastTaskResult } else { $null }
        Executable = $action.Execute
        Arguments = $action.Argument
    } | ConvertTo-Json -Compress
} catch [Microsoft.PowerShell.Cmdletization.MethodInvocationException], [System.Management.Automation.ItemNotFoundException] {
    [PSCustomObject]@{ Installed = $false; State = 'NotInstalled' } | ConvertTo-Json -Compress
} catch {
    [PSCustomObject]@{ Installed = $false; State = 'Error'; Error = $_.Exception.Message } | ConvertTo-Json -Compress
}
"""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            input=json.dumps({"TaskName": OUTBOX_TASK_NAME}),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            return {
                "ok": True,
                "task_name": OUTBOX_TASK_NAME,
                "task_installed": data.get("Installed", False),
                "state": data.get("State", "Unknown"),
                "last_run_time": data.get("LastRunTime"),
                "next_run_time": data.get("NextRunTime"),
                "last_task_result": data.get("LastTaskResult"),
                "executable": data.get("Executable"),
                "arguments": data.get("Arguments"),
            }
        return {
            "ok": True,
            "task_name": OUTBOX_TASK_NAME,
            "task_installed": False,
            "state": "NotInstalled",
        }
    except Exception as exc:
        return {
            "ok": False,
            "task_name": OUTBOX_TASK_NAME,
            "task_installed": False,
            "error": str(exc),
        }


def install_outbox_task(
    apply: bool = False,
    interval_minutes: int = 2,
    limit: int = 50,
    db_path: Optional[Union[str, Path]] = None,
    executable: Optional[Union[str, Path]] = None,
    working_directory: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    """Register or preview the Outbox Dispatcher Windows Scheduled Task."""
    try:
        eff_interval = int(interval_minutes)
        if eff_interval < 1 or eff_interval > 1440:
            return {
                "ok": False,
                "error": f"Invalid interval_minutes: {interval_minutes}. Must be between 1 and 1440.",
            }
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": f"Invalid interval_minutes: {interval_minutes}. Must be an integer between 1 and 1440.",
        }

    try:
        eff_limit = int(limit)
        if eff_limit < 1 or eff_limit > 1000:
            return {
                "ok": False,
                "error": f"Invalid limit: {limit}. Must be between 1 and 1000.",
            }
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": f"Invalid limit: {limit}. Must be an integer between 1 and 1000.",
        }

    for val_name, val in [
        ("db_path", str(db_path or "")),
        ("executable", str(executable or "")),
        ("working_directory", str(working_directory or "")),
    ]:
        if any(c in val for c in ("\x00", "\r", "\n")):
            return {
                "ok": False,
                "error": f"Invalid characters in {val_name}: newlines and null bytes are forbidden.",
            }

    python_exe = Path(executable).resolve() if executable else Path(sys.executable).resolve()
    work_dir = Path(working_directory).resolve() if working_directory else Path.home().resolve()

    args_list = ["-m", "notifications.cli", "outbox", "run", "--limit", str(eff_limit)]
    if db_path:
        args_list.extend(["-d", str(Path(db_path))])
    runner_args = subprocess.list2cmdline(args_list)

    preview = {
        "ok": True,
        "action": "install_outbox_task",
        "dry_run": not apply,
        "task_name": OUTBOX_TASK_NAME,
        "executable": str(python_exe),
        "arguments": runner_args,
        "working_directory": str(work_dir),
        "interval_minutes": eff_interval,
        "limit": eff_limit,
        "requires_apply": not apply,
    }

    if not apply:
        return preview

    if sys.platform != "win32":
        return {
            "ok": False,
            "error": "Scheduled Task installation is only supported on Windows.",
        }

    ps_cmd = """
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$taskName = $in.TaskName
$exe = $in.Executable
$argsStr = $in.Arguments
$workDir = $in.WorkingDirectory
$intervalMin = [int]$in.IntervalMinutes

$action = New-ScheduledTaskAction -Execute $exe -Argument $argsStr -WorkingDirectory $workDir
$timespan = New-TimeSpan -Minutes $intervalMin
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval $timespan

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    [PSCustomObject]@{ Success = $true; TaskName = $taskName } | ConvertTo-Json -Compress
} catch {
    [PSCustomObject]@{ Success = $false; Error = $_.Exception.Message } | ConvertTo-Json -Compress
}
"""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            input=json.dumps({
                "TaskName": OUTBOX_TASK_NAME,
                "Executable": str(python_exe),
                "Arguments": runner_args,
                "WorkingDirectory": str(work_dir),
                "IntervalMinutes": eff_interval,
            }),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            res = json.loads(proc.stdout.strip())
            if res.get("Success"):
                return {
                    "ok": True,
                    "action": "install_outbox_task",
                    "dry_run": False,
                    "task_name": OUTBOX_TASK_NAME,
                    "interval_minutes": eff_interval,
                    "limit": eff_limit,
                    "executable": str(python_exe),
                    "arguments": runner_args,
                    "working_directory": str(work_dir),
                }
            return {"ok": False, "error": res.get("Error", "Unknown PowerShell error")}
        return {
            "ok": False,
            "error": proc.stderr.strip() or f"PowerShell returned code {proc.returncode}",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def uninstall_outbox_task(apply: bool = False) -> dict[str, Any]:
    """Unregister the Outbox Dispatcher Scheduled Task."""
    preview = {
        "ok": True,
        "action": "uninstall_outbox_task",
        "dry_run": not apply,
        "task_name": OUTBOX_TASK_NAME,
        "requires_apply": not apply,
    }

    if not apply:
        return preview

    if sys.platform != "win32":
        return {
            "ok": False,
            "error": "Scheduled Task uninstallation is only supported on Windows.",
        }

    ps_cmd = """
$ErrorActionPreference = 'Stop'
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$taskName = $in.TaskName
try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    [PSCustomObject]@{ Uninstalled = $true } | ConvertTo-Json -Compress
} catch [Microsoft.PowerShell.Cmdletization.MethodInvocationException], [System.Management.Automation.ItemNotFoundException] {
    [PSCustomObject]@{ Uninstalled = $true; AlreadyAbsent = $true } | ConvertTo-Json -Compress
} catch {
    [PSCustomObject]@{ Uninstalled = $false; Error = $_.Exception.Message } | ConvertTo-Json -Compress
}
"""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            input=json.dumps({"TaskName": OUTBOX_TASK_NAME}),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.strip()) if proc.stdout.strip() else {}
            if data.get("Uninstalled"):
                return {
                    "ok": True,
                    "action": "uninstall_outbox_task",
                    "dry_run": False,
                    "task_name": OUTBOX_TASK_NAME,
                    "already_absent": data.get("AlreadyAbsent", False),
                }
            return {"ok": False, "error": data.get("Error", "Failed to unregister task")}
        return {
            "ok": False,
            "error": proc.stderr.strip() or f"PowerShell returned code {proc.returncode}",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
