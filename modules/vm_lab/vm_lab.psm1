#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

$srcFiles = @(
    'Contracts.ps1',
    'Config.ps1',
    'Host.ps1',
    'Inventory.ps1',
    'Provisioning.ps1',
    'Lifecycle.ps1',
    'LifecycleTransaction.ps1',
    'Checkpoints.ps1',
    'Guest.ps1',
    'GuestExec.ps1',
    'Artifacts.ps1',
    'Evidence.ps1',
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
    'Get-VmLabProtectedVmRegistry',
    'Assert-VmLabTargetNotProtected',
    'Test-VmLabSafePath',
    'ConvertTo-VmLabCanonicalJson',
    'Get-VmLabCanonicalSha256',
    'Get-VmLabWorkflowAllowedOperations',
    'Get-VmLabWorkflowCapabilities',
    'Get-VmLabOperationStates',
    'Test-VmLabWorkflowSchema',
    'Test-VmLabArtifactManifestSchema',
    'Test-VmLabOperationJournalSchema',
    'Test-VmLabStageReceiptSchema',
    'Test-VmLabCapabilityAuthorized',
    'Test-VmLabGuestIdentityPolicy',
    'Invoke-VmLabGuestCommand',
    'New-VmLabArtifactManifest',
    'Publish-VmLabArtifactBundle',
    'Expand-VmLabGuestArchive',
    'Get-VmLabEvidencePlan',
    'Receive-VmLabGuestEvidence',
    'Wait-VmLabGuestReady',
    'Invoke-VmLabCheckpointTransaction',
    'Invoke-VmLab'
) -Alias @('vm-lab')
