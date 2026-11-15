#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

$srcFiles = @(
    'Config.ps1',
    'Host.ps1',
    'Inventory.ps1',
    'Provisioning.ps1',
    'Lifecycle.ps1',
    'Checkpoints.ps1',
    'Guest.ps1',
    'Bootstrap.ps1',
    'Recovery.ps1',
    'Wizard.ps1',
    'Output.ps1'
)

foreach ($srcFile in $srcFiles) {
    $srcPath = Join-Path $PSScriptRoot "src\$srcFile"
    if (Test-Path -LiteralPath $srcPath -PathType Leaf) {
        . $srcPath
    }
}

Set-Alias -Name 'vm-lab' -Value 'Invoke-VmLab'
Export-ModuleMember -Function @(
    'Get-VmLabTemplate',
    'Get-VmLabTemplates',
    'Get-VmLabTemplateInfo',
    'Test-VmLabConfig',
    'Get-VmLabOwnershipManifest',
    'Test-VmLabOwnership',
    'Get-VmLabList',
    'Get-VmLabStatus',
    'Test-VmLabPlan',
    'New-VmLabMachine',
    'Invoke-VmLabQuickstart',
    'Invoke-VmLabWizard',
    'Start-VmLabMachine',
    'Stop-VmLabMachine',
    'Connect-VmLabMachine',
    'Start-AndConnectVmLabMachine',
    'Get-VmLabBootDiagnostics',
    'Get-VmLabGuestStatus',
    'Copy-VmLabGuestItem',
    'Invoke-VmLabGuestBootstrap',
    'Test-VmLabGuestVerify',
    'New-VmLabCheckpoint',
    'New-VmLabBaselineCheckpoint',
    'Get-VmLabCheckpoint',
    'Get-VmLabRecoveryPlan',
    'New-VmLabUnattendXml',
    'Invoke-VmLab'
) -Alias @('vm-lab')
