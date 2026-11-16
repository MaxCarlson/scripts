#Requires -Version 7.0
<#
.SYNOPSIS
    Synchronizes canonical H4 qualification PowerShell scripts to C:\H4-VM-Staging and the in-repo snapshot.
.DESCRIPTION
    Copies canonical scripts from modules/resource_coordinator/tools/h4_qualification/ to
    their matching targets in -StagingRoot (default C:\H4-VM-Staging) and
    modules/resource_coordinator/h4_vm_staging_snapshot/scripts/, then verifies SHA-256 equality.
    Never modifies binary archives, installers, wheels, VM disks, or evidence directories.
#>
[CmdletBinding()]
param(
    [string]$StagingRoot = 'C:\H4-VM-Staging',
    [switch]$VerifyOnly,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$qualRoot = $PSScriptRoot
$moduleRoot = [System.IO.Path]::GetFullPath((Join-Path $qualRoot '..\..'))
$snapshotScripts = Join-Path $moduleRoot 'h4_vm_staging_snapshot\scripts'

$fileNames = @(
    'Invoke-H4GuestQualification.ps1',
    'Bootstrap-H4GuestBundle.ps1',
    'Provision-H4TestVM.ps1'
)

$results = [System.Collections.Generic.List[object]]::new()
$allMatch = $true

foreach ($name in $fileNames) {
    $src = Join-Path $qualRoot $name
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) {
        throw "Canonical source file not found: $src"
    }
    $srcHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $src -ErrorAction Stop).Hash

    $targets = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $StagingRoot -PathType Container) {
        $targets.Add((Join-Path $StagingRoot $name))
    }
    if (Test-Path -LiteralPath $snapshotScripts -PathType Container) {
        $targets.Add((Join-Path $snapshotScripts $name))
    }

    foreach ($dst in $targets) {
        if (-not $VerifyOnly) {
            Copy-Item -LiteralPath $src -Destination $dst -Force -ErrorAction Stop
        }
        $dstExists = Test-Path -LiteralPath $dst -PathType Leaf
        $dstHash = if ($dstExists) { (Get-FileHash -Algorithm SHA256 -LiteralPath $dst -ErrorAction Stop).Hash } else { $null }
        $matched = $dstExists -and ($srcHash -eq $dstHash)
        if (-not $matched) { $allMatch = $false }
        $results.Add([pscustomobject]@{
            file          = $name
            source        = $src
            target        = $dst
            source_sha256 = $srcHash
            target_sha256 = $dstHash
            matched       = $matched
        })
    }
}

if ($Json) {
    [pscustomobject]@{
        verify_only = [bool]$VerifyOnly
        all_matched = $allMatch
        files       = $results
    } | ConvertTo-Json -Depth 5
} else {
    $results | Format-Table file, matched, target -AutoSize
}

if (-not $allMatch) {
    exit 1
}
exit 0
