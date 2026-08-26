<#+
.SYNOPSIS
    Windows environment smoke validation for Saved Game Archiver.
.DESCRIPTION
    Uses isolated module-local configuration/state by default. Optional production read-only
    validation inspects the machine's Steam installation but writes results only to the isolated
    test root. This script never installs or deletes Scheduled Tasks.
.PARAMETER RepoRoot
    Root of the scripts repository.
.PARAMETER PythonExecutable
    Python interpreter used for validation.
.PARAMETER IncludeProductionReadOnly
    When set, exercise default Steam discovery against the real machine using isolated output.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot,

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [Parameter()]
    [switch]$IncludeProductionReadOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$ModuleRoot = Join-Path $RepoRoot 'modules\saved_game_archiver'
$TempRoot = Join-Path $ModuleRoot '.pytest_tmp_root\windows-environment'
$ConfigPath = Join-Path $TempRoot 'config.json'
$DataRoot = Join-Path $TempRoot 'state'
$GameRoot = Join-Path $TempRoot 'games'
$FakeGame = Join-Path $GameRoot 'Synthetic Game'

Write-Debug "ModuleRoot=${ModuleRoot}"
Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $FakeGame -Force | Out-Null
Set-Content -LiteralPath (Join-Path $FakeGame 'SyntheticGame.exe') -Value 'fixture' -Encoding Ascii

function Invoke-SgaCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    Write-Debug ("SGA args: " + ($Arguments -join ' '))
    & $PythonExecutable -m saved_game_archiver -c $ConfigPath -d $DataRoot @Arguments
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "Saved Game Archiver command failed with exit code ${ExitCode}: $($Arguments -join ' ')"
    }
}

Invoke-SgaCommand -Arguments @('config', 'archive-root', (Join-Path $TempRoot 'archive'), '--apply')
Invoke-SgaCommand -Arguments @('config', 'game-root', 'add', $GameRoot, '--apply')
Invoke-SgaCommand -Arguments @('modify', 'scan', '--apply')
Invoke-SgaCommand -Arguments @('schedule', 'running', '--rates', 'change', '15m', '--keep-cycles', '2', '--exit-keep', '10')
Invoke-SgaCommand -Arguments @('schedule', 'install')
Invoke-SgaCommand -Arguments @('watch', '--plain', '--once')
Invoke-SgaCommand -Arguments @('stats', 'overview')

if ($IncludeProductionReadOnly) {
    Write-Host 'Running production read-only Steam discovery with isolated state...'
    Invoke-SgaCommand -Arguments @('modify', 'scan', '--apply')
    Invoke-SgaCommand -Arguments @('stats', 'playtime')
}

Write-Host 'Saved Game Archiver Windows environment smoke validation passed.'
