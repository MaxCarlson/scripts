#Requires -Version 7.0

function Invoke-VmLab {
    <#
    .SYNOPSIS
        Unified CLI and PowerShell entry point for vm_lab Hyper-V lab operations.
    .DESCRIPTION
        Supports read-only inspection (list, status, plan, checkpoints) and dry-run-by-default
        mutating operations (create, start, stop, checkpoint) requiring -Apply.
    .EXAMPLE
        Invoke-VmLab -Operation list -OwnedOnly -Json
    .EXAMPLE
        Invoke-VmLab -o plan -t windows11-h4 -n Lab-Test-01 -r C:\Lab\Lab-Test-01 -j
    .EXAMPLE
        Invoke-VmLab -o create -n Lab-Test-01 -r C:\Lab\Lab-Test-01 -Apply
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
        [Alias('oo')][switch]$OwnedOnly,
        [Alias('rb')][int64]$MinReserveBytes = 4GB,
        [Alias('st')][int]$ShutdownTimeoutSeconds = 30,
        [Alias('mr')][string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )

    $result = switch ($Operation) {
        'list' {
            @(Get-VmLabList -OwnedOnly:$OwnedOnly -ManifestRoot $ManifestRoot)
        }
        'status' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for status.' }
            Get-VmLabStatus -Name $Name -ManifestRoot $ManifestRoot
        }
        'plan' {
            $cfg = Get-VmLabTemplate -TemplateName $TemplateName -ConfigPath $ConfigPath
            if ($PSBoundParameters.ContainsKey('Name')) { $cfg.vm_name = $Name }
            if ($PSBoundParameters.ContainsKey('IsoPath')) { $cfg.iso_path = $IsoPath }
            if ($PSBoundParameters.ContainsKey('VmRoot')) { $cfg.vm_root = $VmRoot }
            if ($PSBoundParameters.ContainsKey('SwitchName')) { $cfg.switch_name = $SwitchName }
            Test-VmLabPlan -Config $cfg -ManifestRoot $ManifestRoot
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
        if ($Operation -in @('list', 'checkpoints')) {
            return (ConvertTo-Json -InputObject @($result) -Depth 8)
        }
        return (ConvertTo-Json -InputObject $result -Depth 8)
    }
    return $result
}
