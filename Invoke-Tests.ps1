<#
.SYNOPSIS
Runs repository validation targets through the canonical dispatcher.

.DESCRIPTION
Preserves the repository's stable validation interface while delegating target
selection, native file discovery, command execution, evidence retention, and
development-ledger recording to validation/ValidationDispatcher.psm1.

.PARAMETER Target
One or more manifest target names. Use all to run every configured target.

.PARAMETER ListTargets
Lists configured targets without running validation.

.PARAMETER SkipBootstrap
Skips target bootstrap commands.

.PARAMETER IncludeProductionReadOnly
Enables explicitly configured production read-only checks.

.PARAMETER MaxHistoryPerTarget
Maximum number of prior artifacts retained per target and artifact type.

.PARAMETER MaxHistoryAgeDays
Maximum age of retained comparison artifacts.

.EXAMPLE
./Invoke-Tests.ps1

.EXAMPLE
./Invoke-Tests.ps1 -Target repository-workflow
#>
[CmdletBinding()]
param(
    [Parameter()]
    [Alias('Module')]
    [string[]]$Target,

    [Parameter()]
    [switch]$ListTargets,

    [Parameter()]
    [switch]$SkipBootstrap,

    [Parameter()]
    [switch]$IncludeProductionReadOnly,

    [Parameter()]
    [ValidateRange(1, 100)]
    [int]$MaxHistoryPerTarget = 3,

    [Parameter()]
    [ValidateRange(1, 3650)]
    [int]$MaxHistoryAgeDays = 14
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$DispatcherModule = Join-Path $PSScriptRoot 'validation\ValidationDispatcher.psm1'
if (-not (Test-Path -LiteralPath $DispatcherModule -PathType Leaf)) {
    throw "Validation dispatcher module is missing: $DispatcherModule"
}

Import-Module -Name $DispatcherModule -Force
try {
    $ExitCode = $null
    Invoke-RepositoryValidation `
        -RepoRoot $PSScriptRoot `
        -Target $Target `
        -ListTargets:$ListTargets `
        -SkipBootstrap:$SkipBootstrap `
        -IncludeProductionReadOnly:$IncludeProductionReadOnly `
        -MaxHistoryPerTarget $MaxHistoryPerTarget `
        -MaxHistoryAgeDays $MaxHistoryAgeDays |
        ForEach-Object {
            if ($_ -is [int]) {
                $ExitCode = [int]$_
            }
            else {
                Write-Output $_
            }
        }
    if ($null -eq $ExitCode) {
        throw 'Validation dispatcher did not return an exit code.'
    }
}
catch {
    [Console]::Error.WriteLine("ERROR: $($_.Exception.Message)")
    exit 1
}

exit $ExitCode
