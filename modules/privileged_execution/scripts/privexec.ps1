#Requires -Version 7.0
<#
.SYNOPSIS
    Agent-facing PrivExec CLI wrapper usable from any working directory.
.DESCRIPTION
    Resolves either the staged protected client directory (when invoked from
    C:\ProgramData\PrivExec\client) or the module root (when invoked from
    modules\privileged_execution\scripts) and runs `python -m privexec.cli`.
#>
$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $here 'privexec\__init__.py') -PathType Leaf) {
    $clientRoot = $here
} else {
    $clientRoot = Split-Path -Parent $here
}

$pythonCmd = $null
foreach ($candidate in @('python', 'python3')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        $pythonCmd = $found.Source
        break
    }
}
if (-not $pythonCmd) {
    $pyLauncher = Get-Command 'py' -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $prevPyPath = $env:PYTHONPATH
        try {
            $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($prevPyPath)) { $clientRoot } else { "$clientRoot;$prevPyPath" }
            & $pyLauncher.Source -3 -m privexec.cli @args
            exit $LASTEXITCODE
        } finally {
            $env:PYTHONPATH = $prevPyPath
        }
    }
    throw 'Python 3.11+ was not found on PATH.'
}

$prevPyPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($prevPyPath)) { $clientRoot } else { "$clientRoot;$prevPyPath" }
    & $pythonCmd -m privexec.cli @args
    exit $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $prevPyPath
}
