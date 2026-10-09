[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot,

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [switch]$IncludeProductionReadOnly
)

$ModuleRoot = Join-Path $RepoRoot 'modules/scheduler'
$TempRoot = Join-Path $ModuleRoot '.pytest_tmp_root'
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
$GeneratedScript = Join-Path $TempRoot ("windows-runner-parse-$([guid]::NewGuid().ToString()).ps1")
$env:SCHEDULER_CHECK_SCRIPT_PATH = $GeneratedScript
$env:SCHEDULER_CHECK_DATA_FILE = Join-Path $ModuleRoot 'scheduler_data.json'

$Generator = @'
import os
from pathlib import Path
from scheduler.windows_task import _registration_script

script = _registration_script(
    Path(os.environ["SCHEDULER_CHECK_DATA_FILE"]),
    30,
    "ValidationRunner",
    r"MACHINE\ValidationUser",
)
Path(os.environ["SCHEDULER_CHECK_SCRIPT_PATH"]).write_text(script, encoding="utf-8")
'@

try {
    $Generator | & $PythonExecutable -
    if ($LASTEXITCODE -ne 0) {
        throw "Python failed to generate the runner registration script (exit $LASTEXITCODE)."
    }

    $Source = Get-Content -LiteralPath $GeneratedScript -Raw
    $Tokens = $null
    $ParseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseInput($Source, [ref]$Tokens, [ref]$ParseErrors)
    if ($ParseErrors.Count -gt 0) {
        $Details = ($ParseErrors | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        throw "Generated runner PowerShell has syntax errors:`n$Details"
    }

    foreach ($RequiredText in @(
        'New-ScheduledTaskTrigger -AtLogOn',
        '-LogonType Interactive -RunLevel Limited',
        '-LogonType Interactive -RunLevel Highest',
        '--admin-worker',
        'scheduler.cli',
        'ValidationRunner'
    )) {
        if ($Source -notlike "*$RequiredText*") {
            throw "Generated runner PowerShell is missing expected configuration: $RequiredText"
        }
    }

    Write-Output 'Generated Windows runner registration script parses and assigns separate limited and elevated principals.'
}
finally {
    if (Test-Path -LiteralPath $GeneratedScript) {
        Remove-Item -LiteralPath $GeneratedScript
    }
    Remove-Item Env:SCHEDULER_CHECK_SCRIPT_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:SCHEDULER_CHECK_DATA_FILE -ErrorAction SilentlyContinue
}
