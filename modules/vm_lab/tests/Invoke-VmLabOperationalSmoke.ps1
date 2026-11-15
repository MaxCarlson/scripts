#Requires -Version 7.0
<#
.SYNOPSIS
    Gated operational smoke harness for real Hyper-V qualification of vm_lab.
.DESCRIPTION
    Non-default manual qualification script. Refuses to run without -AuthorizeDisposableTest
    and an explicit disposable -VmName, and explicitly refuses RC-H4-Windows-Acceptance
    or any pre-existing unmanaged VM.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$VmName,
    [Parameter(Mandatory)][string]$VmRoot,
    [string]$TemplateName = 'windows11-light',
    [string]$IsoPath,
    [pscredential]$Credential,
    [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$GuestProfile = 'windows-minimal',
    [string]$ManifestRoot,
    [switch]$AuthorizeDisposableTest,
    [switch]$RunGuestChecks
)

$ErrorActionPreference = 'Stop'

if (-not $AuthorizeDisposableTest) {
    throw 'Refusing real Hyper-V operational smoke test without -AuthorizeDisposableTest.'
}
if ([string]::IsNullOrWhiteSpace($VmName)) {
    throw '-VmName is required.'
}
if ($VmName -eq 'RC-H4-Windows-Acceptance') {
    throw "Refusing operational smoke test against protected VM 'RC-H4-Windows-Acceptance'."
}

$moduleRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $moduleRoot 'vm_lab.psd1') -Force

$existing = @(Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $VmName -or [string]$_.Id -eq 'd8483f98-8884-4758-abd1-cd6107c83c03' })
foreach ($e in $existing) {
    if ([string]$e.Id -eq 'd8483f98-8884-4758-abd1-cd6107c83c03') {
        throw 'Protected VM ID d8483f98-8884-4758-abd1-cd6107c83c03 detected; aborting.'
    }
    if ($e.Name -eq $VmName) {
        throw "VM '$VmName' already exists. Provide a fresh disposable VM name."
    }
}

$manifestArgs = @{}
if (-not [string]::IsNullOrWhiteSpace($ManifestRoot)) {
    $manifestArgs.ManifestRoot = $ManifestRoot
}

$cfg = Get-VmLabTemplate -TemplateName $TemplateName
$cfg.vm_name = $VmName
$cfg.vm_root = $VmRoot
if (-not [string]::IsNullOrWhiteSpace($IsoPath)) {
    $cfg.iso_path = $IsoPath
}

$steps = [ordered]@{}
$steps.plan = Test-VmLabPlan -Config $cfg @manifestArgs
$steps.create = New-VmLabMachine -Config $cfg -Apply @manifestArgs
$steps.start = Start-VmLabMachine -Name $VmName -Apply @manifestArgs
$steps.status = Get-VmLabStatus -Name $VmName @manifestArgs

if ($RunGuestChecks -and $null -ne $Credential) {
    $steps.guest_status = Get-VmLabGuestStatus -Name $VmName -Credential $Credential @manifestArgs
    if ($steps.guest_status.ps_direct_available) {
        $steps.guest_bootstrap = Invoke-VmLabGuestBootstrap -Name $VmName -Profile $GuestProfile -Credential $Credential -Apply @manifestArgs
        $steps.guest_verify = Test-VmLabGuestVerify -Name $VmName -Profile $GuestProfile -Credential $Credential @manifestArgs
        if ($steps.guest_verify.status -eq 'verified') {
            $steps.baseline = New-VmLabBaselineCheckpoint -Name $VmName -CheckpointName 'smoke-baseline' -RequireGuestVerified -GuestProfile $GuestProfile -Credential $Credential -Apply @manifestArgs
        }
    }
}

$steps.stop = Stop-VmLabMachine -Name $VmName -Apply @manifestArgs

[pscustomobject]@{
    status    = 'completed'
    vm_name   = $VmName
    template  = $TemplateName
    steps     = $steps
} | ConvertTo-Json -Depth 10
