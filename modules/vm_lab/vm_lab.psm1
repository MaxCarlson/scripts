#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

$srcFiles = @(
    'Config.ps1',
    'Host.ps1',
    'Inventory.ps1',
    'Provisioning.ps1',
    'Lifecycle.ps1',
    'Checkpoints.ps1',
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
    'Test-VmLabConfig',
    'Get-VmLabOwnershipManifest',
    'Test-VmLabOwnership',
    'Get-VmLabList',
    'Get-VmLabStatus',
    'Test-VmLabPlan',
    'New-VmLabMachine',
    'Start-VmLabMachine',
    'Stop-VmLabMachine',
    'New-VmLabCheckpoint',
    'Get-VmLabCheckpoint',
    'Invoke-VmLab'
) -Alias @('vm-lab')
