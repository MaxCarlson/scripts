"""Windows Task Scheduler integration for the persistent scheduler daemon."""
from __future__ import annotations

import base64
import getpass
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

RUNNER_TASK_NAME = "ScriptsSchedulerDaemon"
ADMIN_WORKER_TASK_NAME = "ScriptsSchedulerAdminWorker"
DEFAULT_CHECK_INTERVAL_SECONDS = 30


def _require_windows() -> None:
    if os.name != "nt":
        raise OSError("Windows Task Scheduler integration is only available on Windows.")


def _ps_quote(value: str) -> str:
    """Quote a value as a PowerShell single-quoted string."""
    return "'" + value.replace("'", "''") + "'"


def _encode_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def _run_powershell(script: str, *, elevated: bool = False) -> subprocess.CompletedProcess[str]:
    """Run PowerShell and return its output and exit status.

    Elevated actions use a temporary encoded script and capture output to files.
    PowerShell's `-Verb RunAs` cannot be combined reliably with native output
    redirection parameters, so the elevated script owns its output capture.
    """
    _require_windows()
    powershell = os.environ.get("WINDIR", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    encoded = _encode_powershell(script)

    if not elevated:
        return subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    with tempfile.TemporaryDirectory(prefix="scheduler-task-") as temp_dir:
        stdout_path = Path(temp_dir) / "stdout.txt"
        stderr_path = Path(temp_dir) / "stderr.txt"
        # Create the files before elevation so their owner and ACL remain
        # readable by the unelevated parent after the child exits.
        stdout_path.touch()
        stderr_path.touch()
        wrapped_script = "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                "try {",
                "  & {",
                script,
                f"  }} *>&1 | Out-File -LiteralPath {_ps_quote(str(stdout_path))} -Encoding utf8",
                "  exit 0",
                "} catch {",
                f"  $_ | Out-File -LiteralPath {_ps_quote(str(stderr_path))} -Encoding utf8",
                "  exit 1",
                "}",
            ]
        )
        encoded_child = _encode_powershell(wrapped_script)
        child_args = f"-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded_child}"
        launcher = (
            f"$child = Start-Process -FilePath {_ps_quote(powershell)} "
            f"-ArgumentList {_ps_quote(child_args)} -Verb RunAs -Wait -PassThru -WindowStyle Hidden; "
            "$child.Refresh(); exit $child.ExitCode"
        )
        outer = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", launcher],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        try:
            stdout = stdout_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            stdout = ""
        try:
            stderr = stderr_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            stderr = ""
        return subprocess.CompletedProcess(
            args=outer.args,
            returncode=outer.returncode,
            stdout=stdout or outer.stdout,
            stderr=stderr or outer.stderr,
        )


def _registration_script(
    data_file: Path,
    interval_seconds: int,
    task_name: str,
    user_id: str,
    admin_worker_task_name: str = ADMIN_WORKER_TASK_NAME,
) -> str:
    if interval_seconds < 1:
        raise ValueError("The daemon check interval must be at least one second.")

    python_path = str(Path(sys.executable).resolve())
    module_dir = str(Path(__file__).resolve().parent.parent)
    arguments = subprocess.list2cmdline(
        ["-m", "scheduler.cli", "--config-file", str(data_file.resolve()), "daemon", "--interval", str(interval_seconds)]
    )
    worker_arguments = subprocess.list2cmdline(
        ["-m", "scheduler.cli", "--config-file", str(data_file.resolve()), "daemon", "--admin-worker", "--interval", "1"]
    )
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$user = {_ps_quote(user_id)}",
            "$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user",
            "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)",
            f"$daemonAction = New-ScheduledTaskAction -Execute {_ps_quote(python_path)} -Argument {_ps_quote(arguments)} -WorkingDirectory {_ps_quote(module_dir)}",
            f"$daemonPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited",
            f"Register-ScheduledTask -TaskName {_ps_quote(task_name)} -Description 'Runs the scripts scheduler daemon at user logon.' -Action $daemonAction -Trigger $trigger -Principal $daemonPrincipal -Settings $settings -Force | Out-Null",
            f"$workerAction = New-ScheduledTaskAction -Execute {_ps_quote(python_path)} -Argument {_ps_quote(worker_arguments)} -WorkingDirectory {_ps_quote(module_dir)}",
            "$workerPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest",
            f"Register-ScheduledTask -TaskName {_ps_quote(admin_worker_task_name)} -Description 'Runs Admin-flagged scheduler tasks at user logon.' -Action $workerAction -Trigger $trigger -Principal $workerPrincipal -Settings $settings -Force | Out-Null",
            "Write-Output 'Registered the limited scheduler daemon and elevated Admin task worker.'",
        ]
    )


def install_runner(
    data_file: Path,
    interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS,
    task_name: str = RUNNER_TASK_NAME,
    admin_worker_task_name: str = ADMIN_WORKER_TASK_NAME,
) -> str:
    """Register/update the per-user logon task, requesting UAC elevation once."""
    _require_windows()
    domain = os.environ.get("USERDOMAIN")
    username = os.environ.get("USERNAME") or getpass.getuser()
    user_id = f"{domain}\\{username}" if domain else username
    result = _run_powershell(
        _registration_script(data_file, interval_seconds, task_name, user_id, admin_worker_task_name), elevated=True
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"PowerShell exited with code {result.returncode}."
        raise RuntimeError(f"Could not install the Windows scheduler runner: {detail}")
    return result.stdout.strip() or "Windows scheduler runner installed. It starts at the next user logon."


def start_runner(task_name: str = RUNNER_TASK_NAME, admin_worker_task_name: str = ADMIN_WORKER_TASK_NAME) -> str:
    """Start the elevated worker before the limited daemon."""
    _require_windows()
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$worker = Get-ScheduledTask -TaskName {_ps_quote(admin_worker_task_name)} -ErrorAction Stop",
            f"$daemon = Get-ScheduledTask -TaskName {_ps_quote(task_name)} -ErrorAction Stop",
            f"Start-ScheduledTask -TaskName {_ps_quote(admin_worker_task_name)}",
            f"Start-ScheduledTask -TaskName {_ps_quote(task_name)}",
            "Write-Output 'Started the elevated worker and limited scheduler daemon.'",
        ]
    )
    # Starting a task owned by this user does not require elevation. The task
    # itself is already configured to launch with its highest privilege token.
    result = _run_powershell(script)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"PowerShell exited with code {result.returncode}."
        raise RuntimeError(f"Could not start the Windows scheduler runner: {detail}")
    return result.stdout.strip() or "Windows scheduler runner started. Due catch-up tasks may run now."


def remove_runner(task_name: str = RUNNER_TASK_NAME, admin_worker_task_name: str = ADMIN_WORKER_TASK_NAME) -> str:
    """Remove both registered tasks, requesting UAC elevation once."""
    _require_windows()
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"Unregister-ScheduledTask -TaskName {_ps_quote(task_name)} -Confirm:$false -ErrorAction SilentlyContinue",
            f"Unregister-ScheduledTask -TaskName {_ps_quote(admin_worker_task_name)} -Confirm:$false -ErrorAction SilentlyContinue",
            "Write-Output 'Removed the scheduler daemon and elevated worker tasks if installed.'",
        ]
    )
    result = _run_powershell(script, elevated=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"PowerShell exited with code {result.returncode}."
        raise RuntimeError(f"Could not remove the Windows scheduler runner: {detail}")
    return result.stdout.strip() or "Windows scheduler runner removed."


def get_runner_status(task_name: str = RUNNER_TASK_NAME, admin_worker_task_name: str = ADMIN_WORKER_TASK_NAME) -> Dict[str, Any]:
    """Return read-only status for the limited daemon and elevated worker."""
    _require_windows()
    task_literal = _ps_quote(task_name)
    worker_literal = _ps_quote(admin_worker_task_name)
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "function Get-TaskStatus([string]$name) {",
            "  try { $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop }",
            "  catch { if ($_.CategoryInfo.Category -eq 'ObjectNotFound') { return @{ installed=$false } }; throw }",
            "  $info = Get-ScheduledTaskInfo -TaskName $name",
            "  $action = $task.Actions | Select-Object -First 1",
            "  return @{ installed=$true; enabled=[bool]$task.Settings.Enabled; state=[string]$task.State; user=$task.Principal.UserId; logonType=[string]$task.Principal.LogonType; runLevel=[string]$task.Principal.RunLevel; execute=$action.Execute; arguments=$action.Arguments; lastRunTime=$info.LastRunTime.ToString('o'); lastTaskResult=$info.LastTaskResult }",
            "}",
            "$daemon = Get-TaskStatus " + task_literal,
            "$worker = Get-TaskStatus " + worker_literal,
            "$daemon.adminWorker = $worker",
            "$daemon | ConvertTo-Json -Depth 4 -Compress",
        ]
    )
    result = _run_powershell(script)
    if result.returncode:
        detail = result.stderr.strip() or f"PowerShell exited with code {result.returncode}."
        raise RuntimeError(f"Could not inspect the Windows scheduler runner: {detail}")
    try:
        value = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("Windows returned an invalid scheduler runner status response.") from exc
    return value if isinstance(value, dict) else {"installed": False}
