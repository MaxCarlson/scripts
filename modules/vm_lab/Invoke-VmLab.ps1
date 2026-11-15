#Requires -Version 7.0
<#
.SYNOPSIS
    CLI entry point for the vm_lab disposable Hyper-V lab manager.
.DESCRIPTION
    Imports the local vm_lab module and invokes Invoke-VmLab with short and long flags.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory, Position = 0)]
    [Alias('o')]
    [ValidateSet('list', 'status', 'plan', 'create', 'start', 'stop', 'checkpoint', 'checkpoints')]
    [string]$Operation,

    [Alias('n')][string]$Name,
    [Alias('c')][string]$ConfigPath,
    [Alias('t')][string]$TemplateName = 'windows11-h4',
    [Alias('i')][string]$IsoPath,
    [Alias('r')][string]$VmRoot,
    [Alias('s')][string]$SwitchName,
    [Alias('m')][string]$CheckpointName,
    [Alias('a')][switch]$Apply,
    [Alias('j')][switch]$Json,
    [switch]$OwnedOnly,
    [int64]$MinReserveBytes = 4GB,
    [string]$ManifestRoot
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'vm_lab.psd1') -Force
Invoke-VmLab @PSBoundParameters
