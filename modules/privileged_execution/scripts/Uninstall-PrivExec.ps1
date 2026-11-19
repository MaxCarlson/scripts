#Requires -Version 7.0
<#
.SYNOPSIS
    Dry-run-by-default uninstaller/rollback script for staged PrivExec directories.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\ProgramData\PrivExec',
    [switch]$PurgeState,
    [switch]$Apply,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$resolvedRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$exists = Test-Path -LiteralPath $resolvedRoot

$targets = @('bin', 'descriptors', 'adapters', 'h4_scripts', 'work')
if ($PurgeState) {
    $targets += 'state'
}

$plan = [ordered]@{
    schema_version = 1
    action         = 'privexec_uninstall'
    apply          = [bool]$Apply
    install_root   = $resolvedRoot
    exists         = $exists
    purge_state    = [bool]$PurgeState
    remove_subdirs = $targets
}

if (-not $Apply) {
    if ($Json) {
        $plan | ConvertTo-Json -Depth 5
    } else {
        Write-Host "PRIVEXEC UNINSTALL DRY-RUN (no changes made): target=$resolvedRoot purge_state=$PurgeState"
    }
    exit 0
}

if ($exists) {
    foreach ($sub in $targets) {
        $p = Join-Path $resolvedRoot $sub
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Recurse -Force
        }
    }
    if ($PurgeState -and @(Get-ChildItem -LiteralPath $resolvedRoot -Force -ErrorAction SilentlyContinue).Count -eq 0) {
        Remove-Item -LiteralPath $resolvedRoot -Force
    }
}

$plan['removed'] = $true
if ($Json) {
    $plan | ConvertTo-Json -Depth 5
} else {
    Write-Host "PrivExec uninstall completed for '$resolvedRoot'."
}
