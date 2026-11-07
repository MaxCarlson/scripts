"""Opt-in real Windows tests for the bounded Task Scheduler helper transport.

The transport probe validates the file-backed helper/result protocol without
reading or modifying production Task Scheduler entries.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from resource_coordinator.installation import WindowsStartupTaskBackend


@pytest.mark.skipif(os.name != "nt" or os.environ.get("RC_WINDOWS_TASK_INTEGRATION") != "1",
                    reason="set RC_WINDOWS_TASK_INTEGRATION=1 to create a disposable Windows Scheduled Task")
def test_windows_disposable_task_registration_snapshot_restore_and_verification(tmp_path):
    """Exercise the real Task Scheduler cmdlets without touching RC production tasks."""
    powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    task_name = "RC-Disposable-" + os.urandom(12).hex()
    script = r"""
$ErrorActionPreference = 'Stop'
$name = '__TASK_NAME__'
$created = $false
try {
  $exe = $env:ComSpec
  if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    throw 'Disposable task name already exists; refusing to overwrite it.'
  }
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddDays(2)
  $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
  $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
  $action = New-ScheduledTaskAction -Execute $exe -Argument '/d /c exit 0'
  Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Disposable Resource Coordinator integration test' | Out-Null
  $created = $true
  Disable-ScheduledTask -TaskName $name | Out-Null
  $before = Get-ScheduledTask -TaskName $name -ErrorAction Stop
  $snapshot = Export-ScheduledTask -TaskName $name -ErrorAction Stop
  if ([string]::IsNullOrWhiteSpace($snapshot)) { throw 'Scheduled Task snapshot was empty.' }

  $changed = New-ScheduledTaskAction -Execute $exe -Argument '/d /c exit 7'
  Register-ScheduledTask -TaskName $name -Action $changed -Trigger $trigger -Principal $principal -Settings $settings -Description 'Disposable task mutation' -Force | Out-Null
  $mutated = Get-ScheduledTask -TaskName $name -ErrorAction Stop
  if ($mutated.Actions[0].Arguments -notmatch 'exit 7') { throw 'Disposable task mutation was not observable.' }

  Register-ScheduledTask -TaskName $name -Xml $snapshot -Force | Out-Null
  $restored = Get-ScheduledTask -TaskName $name -ErrorAction Stop
  $restoredEnabled = [bool]$restored.Settings.Enabled
  $actionRestored = $restored.Actions.Count -eq 1 -and $restored.Actions[0].Execute -eq $exe -and $restored.Actions[0].Arguments -match 'exit 0'
  $principalRestored = $restored.Principal.UserId -eq $before.Principal.UserId
  if (-not $actionRestored -or -not $principalRestored -or $restoredEnabled) {
    throw 'Restored task does not match the snapshot action, principal, or disabled state.'
  }
  [pscustomobject]@{status='verified'; task_name=$name; snapshot_chars=$snapshot.Length; action_restored=$actionRestored; principal_restored=$principalRestored; disabled=$(-not $restoredEnabled)} | ConvertTo-Json -Compress
} finally {
  if ($created) { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue }
}
""".replace("__TASK_NAME__", task_name)
    script_path = Path(tmp_path) / "disposable-task-integration.ps1"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
        capture_output=True, text=True, timeout=90,
    )
    if result.returncode:
        details = (result.stderr or result.stdout).strip()
        if any(text in details.casefold() for text in (
            "access to a cim resource was not available", "access is denied", "0x80070005",
        )):
            pytest.skip(f"Task Scheduler access is denied in this execution context: {details}")
        pytest.fail(f"Disposable Scheduled Task integration failed: {details}")
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["status"] == "verified"
    assert data["action_restored"] and data["principal_restored"] and data["disabled"]
    assert data["snapshot_chars"] > 0


@pytest.mark.skipif(os.name != "nt" or os.environ.get("RC_WINDOWS_INTEGRATION") != "1",
                    reason="set RC_WINDOWS_INTEGRATION=1 on Windows to run the real read-only helper test")
def test_windows_helper_processes_large_request_from_protected_file(tmp_path):
    backend = WindowsStartupTaskBackend(managed_root=Path(tmp_path) / "Resource Coordinator Integration")
    definition = "<Task>" + ("x" * 100_000) + "</Task>"
    result = backend._run({"operation": "transport_probe", "definition": definition})
    details = json.loads(result.stdout)
    assert details["status"] == "validated"
    assert details["definition_length"] == len(definition)
    assert list(backend.managed_root.glob("operation-*")) == []


@pytest.mark.skipif(os.name != "nt" or os.environ.get("RC_WINDOWS_UAC_INTEGRATION") != "1",
                    reason="set RC_WINDOWS_UAC_INTEGRATION=1 to test Start-Process -Verb RunAs")
def test_windows_uac_helper_processes_large_request_and_verifies_completion(tmp_path):
    backend = WindowsStartupTaskBackend(managed_root=Path(tmp_path) / "Resource Coordinator UAC Integration")
    if backend._admin():
        pytest.skip("run from a non-elevated PowerShell session to exercise the UAC child process")
    definition = "<Task>" + ("x" * 100_000) + "</Task>"
    result = backend._run({"operation": "transport_probe", "definition": definition}, elevated=True)
    details = json.loads(result.stdout)
    assert details["status"] == "validated"
    assert details["definition_length"] == len(definition)
    assert list(backend.managed_root.glob("operation-*")) == []
