@{
    RootModule        = 'vm_lab.psm1'
    ModuleVersion     = '0.1.0'
    GUID              = '7b8c9d10-4f2a-4c6e-9a1b-3d5e7f901234'
    Author            = 'MaxCarlson'
    Description       = 'Disposable Hyper-V lab VM lifecycle, ownership, and safety wrapper.'
    PowerShellVersion = '7.0'
    FunctionsToExport = @(
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
        'New-VmLabCheckpoint',
        'Get-VmLabCheckpoint',
        'Invoke-VmLab'
    )
    AliasesToExport   = @('vm-lab')
}
