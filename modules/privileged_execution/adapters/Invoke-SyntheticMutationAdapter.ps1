#Requires -Version 7.0
<#
.SYNOPSIS
    Safe synthetic child-process adapter for PrivExec Gate 2 validation.
.DESCRIPTION
    Supports read-only dry-run (default) and explicitly authorized -Apply mutation
    strictly scoped to a single marker file inside the broker-pinned working directory.
    Does not touch Hyper-V, Scheduled Tasks, Services, or Resource Coordinator.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$OperationId,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9_-]{1,64}$')][string]$TargetId,
    [switch]$Apply,
    [ValidatePattern('^[A-Za-z0-9._-]{1,64}$')][string]$Marker = 'default',
    [ValidateRange(0, 20)][int]$SleepSeconds = 0
)

$ErrorActionPreference = 'Stop'

if ($SleepSeconds -gt 0) {
    Start-Sleep -Seconds $SleepSeconds
}

$workDir = [System.IO.Path]::GetFullPath((Get-Location).Path)
$stateFile = [System.IO.Path]::GetFullPath((Join-Path $workDir "synthetic-$TargetId.json"))
if (-not $stateFile.StartsWith($workDir.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing synthetic state path outside working directory: '$stateFile'."
}

$item = Get-Item -LiteralPath $workDir -Force -ErrorAction Stop
if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Working directory is a reparse point: '$workDir'."
}

$existingCount = 0
if (Test-Path -LiteralPath $stateFile -PathType Leaf) {
    $prev = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json -ErrorAction Stop
    $existingCount = [int]$prev.apply_count
}

if (-not $Apply) {
    [ordered]@{
        synthetic    = $true
        mode         = 'dry_run'
        operation_id = $OperationId
        target_id    = $TargetId
        marker       = $Marker
        apply_count  = $existingCount
        state_file   = $stateFile
    } | ConvertTo-Json -Compress
    exit 0
}

$newCount = $existingCount + 1
$record = [ordered]@{
    synthetic    = $true
    mode         = 'apply'
    operation_id = $OperationId
    target_id    = $TargetId
    marker       = $Marker
    apply_count  = $newCount
    updated_at   = (Get-Date).ToUniversalTime().ToString('o')
}
$record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $stateFile -Encoding utf8NoBOM
$record | ConvertTo-Json -Compress
exit 0
