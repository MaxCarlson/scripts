#Requires -Version 7.0

function Invoke-VmLab {
    <#
    .SYNOPSIS
        Unified CLI and PowerShell entry point for vm_lab Hyper-V lab operations.
    .DESCRIPTION
        Supports read-only inspection (list, status, plan, templates, template-info, checkpoints, boot-diagnostics),
        interactive setup (wizard), VMConnect (connect, start-connect), and dry-run-by-default
        mutating operations (quickstart, create, start, stop, checkpoint) requiring -Apply.
    .EXAMPLE
        Invoke-VmLab -Operation templates -Json
    .EXAMPLE
        Invoke-VmLab -o quickstart -t windows11-dev -n Dev-Win11-01 -r C:\VMs\Dev-Win11-01 -j
    .EXAMPLE
        Invoke-VmLab -o quickstart -t windows11-dev -n Dev-Win11-01 -r C:\VMs\Dev-Win11-01 -Apply -Start
    #>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory, Position = 0)]
        [Alias('o')]
        [ValidateSet('list', 'status', 'plan', 'quickstart', 'wizard', 'templates', 'template-info', 'create', 'start', 'stop', 'connect', 'start-connect', 'boot-diagnostics', 'checkpoint', 'checkpoints')]
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
        [Alias('oo')][switch]$OwnedOnly,
        [Alias('rb')][int64]$MinReserveBytes = 4GB,
        [Alias('st')][int]$ShutdownTimeoutSeconds = 30,
        [Alias('mr')][string]$ManifestRoot = (Get-VmLabDefaultManifestRoot),
        [switch]$Start,
        [switch]$Connect
    )

    $result = switch ($Operation) {
        'list' {
            @(Get-VmLabList -OwnedOnly:$OwnedOnly -ManifestRoot $ManifestRoot)
        }
        'status' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for status.' }
            Get-VmLabStatus -Name $Name -ManifestRoot $ManifestRoot
        }
        'templates' {
            @(Get-VmLabTemplates)
        }
        'template-info' {
            Get-VmLabTemplateInfo -TemplateName $TemplateName
        }
        'plan' {
            $cfg = Get-VmLabTemplate -TemplateName $TemplateName -ConfigPath $ConfigPath
            if ($PSBoundParameters.ContainsKey('Name')) { $cfg.vm_name = $Name }
            if ($PSBoundParameters.ContainsKey('IsoPath')) { $cfg.iso_path = $IsoPath }
            if ($PSBoundParameters.ContainsKey('VmRoot')) { $cfg.vm_root = $VmRoot }
            if ($PSBoundParameters.ContainsKey('SwitchName')) { $cfg.switch_name = $SwitchName }
            Test-VmLabPlan -Config $cfg -ManifestRoot $ManifestRoot
        }
        'quickstart' {
            $cfg = Get-VmLabTemplate -TemplateName $TemplateName -ConfigPath $ConfigPath
            if ($PSBoundParameters.ContainsKey('Name')) { $cfg.vm_name = $Name }
            if ($PSBoundParameters.ContainsKey('IsoPath')) { $cfg.iso_path = $IsoPath }
            if ($PSBoundParameters.ContainsKey('VmRoot')) { $cfg.vm_root = $VmRoot }
            if ($PSBoundParameters.ContainsKey('SwitchName')) { $cfg.switch_name = $SwitchName }
            Invoke-VmLabQuickstart -Config $cfg -Apply:$Apply -Start:$Start -Connect:$Connect -MinHostReserveBytes $MinReserveBytes -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'wizard' {
            if ($Json) {
                throw 'Interactive wizard cannot prompt in -Json mode. Use -o plan or -o quickstart with explicit parameters.'
            }
            Invoke-VmLabWizard -DefaultTemplate $TemplateName -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'create' {
            $cfg = Get-VmLabTemplate -TemplateName $TemplateName -ConfigPath $ConfigPath
            if ($PSBoundParameters.ContainsKey('Name')) { $cfg.vm_name = $Name }
            if ($PSBoundParameters.ContainsKey('IsoPath')) { $cfg.iso_path = $IsoPath }
            if ($PSBoundParameters.ContainsKey('VmRoot')) { $cfg.vm_root = $VmRoot }
            if ($PSBoundParameters.ContainsKey('SwitchName')) { $cfg.switch_name = $SwitchName }
            New-VmLabMachine -Config $cfg -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'start' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for start.' }
            Start-VmLabMachine -Name $Name -MinHostReserveBytes $MinReserveBytes -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'stop' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for stop.' }
            Stop-VmLabMachine -Name $Name -ShutdownTimeoutSeconds $ShutdownTimeoutSeconds -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'connect' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for connect.' }
            Connect-VmLabMachine -Name $Name -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'start-connect' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for start-connect.' }
            Start-AndConnectVmLabMachine -Name $Name -MinHostReserveBytes $MinReserveBytes -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'boot-diagnostics' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for boot-diagnostics.' }
            Get-VmLabBootDiagnostics -Name $Name -ManifestRoot $ManifestRoot
        }
        'checkpoint' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for checkpoint.' }
            if ([string]::IsNullOrWhiteSpace($CheckpointName)) { throw '-CheckpointName (-m) is required for checkpoint.' }
            New-VmLabCheckpoint -Name $Name -CheckpointName $CheckpointName -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'checkpoints' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for checkpoints.' }
            @(Get-VmLabCheckpoint -Name $Name -ManifestRoot $ManifestRoot)
        }
    }

    if ($Json) {
        if ($Operation -in @('list', 'checkpoints', 'templates')) {
            return (ConvertTo-Json -InputObject @($result) -Depth 8)
        }
        return (ConvertTo-Json -InputObject $result -Depth 8)
    }
    return $result
}
