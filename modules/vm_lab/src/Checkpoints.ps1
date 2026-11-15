#Requires -Version 7.0

function New-VmLabCheckpoint {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$CheckpointName,
        [Alias('a')][switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    if ([string]::IsNullOrWhiteSpace($CheckpointName)) {
        throw 'CheckpointName is required.'
    }
    $owned = Assert-VmLabOwnedVm -Name $Name -ManifestRoot $ManifestRoot
    $vm = $owned.vm
    if ([string]$vm.CheckpointType -eq 'Disabled') {
        throw "Refusing to create checkpoint for VM '$Name': CheckpointType is 'Disabled'."
    }
    $transitionalStates = @('Starting', 'Stopping', 'Saving', 'Pausing', 'Resuming', 'Reset')
    if ([string]$vm.State -in $transitionalStates) {
        throw "Refusing to create checkpoint for VM '$Name': VM is in transitional state '$($vm.State)'."
    }

    $existingSnaps = @(Get-VMSnapshot -VMName $Name -ErrorAction Stop)
    if ($existingSnaps | Where-Object { $_.Name -eq $CheckpointName }) {
        throw "Checkpoint '$CheckpointName' already exists on VM '$Name'."
    }

    if (-not $Apply -or $WhatIfPreference) {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($Name, "Create checkpoint '$CheckpointName'")
        }
        return [pscustomobject]@{
            status          = 'planned'
            operation       = 'checkpoint'
            vm_name         = $Name
            vm_id           = [string]$vm.Id
            checkpoint_name = $CheckpointName
        }
    }
    if (-not (Test-VmLabAdministrator)) {
        throw 'Administrator elevation is required to checkpoint Hyper-V VMs.'
    }
    if (-not $PSCmdlet.ShouldProcess($Name, "Create checkpoint '$CheckpointName'")) {
        return [pscustomobject]@{ status = 'declined'; operation = 'checkpoint'; vm_name = $Name }
    }

    $vmNow = Assert-VmLabReverifiedTarget -Name $Name -ExpectedId ([guid]$vm.Id) -ManifestRoot $ManifestRoot
    if ($vmNow.GetType().FullName -eq 'Microsoft.HyperV.PowerShell.VirtualMachine') {
        Checkpoint-VM -VM $vmNow -SnapshotName $CheckpointName -ErrorAction Stop
    } else {
        Checkpoint-VM -Name $vmNow.Name -SnapshotName $CheckpointName -ErrorAction Stop
    }

    $createdSnap = @(Get-VMSnapshot -VMName $Name -ErrorAction Stop) |
        Where-Object { $_.Name -eq $CheckpointName } |
        Sort-Object -Property CreationTime -Descending |
        Select-Object -First 1
    if (-not $createdSnap) {
        throw "Checkpoint '$CheckpointName' could not be verified after Checkpoint-VM completed for '$Name'."
    }

    return [pscustomobject]@{
        status          = 'checkpoint_created'
        operation       = 'checkpoint'
        vm_name         = $Name
        vm_id           = [string]$vmNow.Id
        checkpoint_name = $createdSnap.Name
        checkpoint_id   = [string]$createdSnap.Id
        created_at      = $createdSnap.CreationTime
        snapshot_type   = [string]$createdSnap.SnapshotType
    }
}

function Get-VmLabCheckpoint {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) {
        throw "VM '$Name' was not found in Hyper-V inventory."
    }
    $snaps = @(Get-VMSnapshot -VMName $Name -ErrorAction Stop)
    return @($snaps | ForEach-Object {
        [pscustomobject]@{
            vm_name       = $Name
            name          = $_.Name
            id            = [string]$_.Id
            created_at    = $_.CreationTime
            snapshot_type = [string]$_.SnapshotType
        }
    })
}

function New-VmLabBaselineCheckpoint {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$CheckpointName = 'clean-baseline',
        [switch]$RequireGuestVerified,
        [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$GuestProfile = 'windows-minimal',
        [string]$VenvPath = 'C:\venvs\dev',
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [Alias('a')][switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $guestVerified = $false
    if ($RequireGuestVerified -and $Apply -and -not $WhatIfPreference) {
        $verifyRes = Test-VmLabGuestVerify -Name $Name -Profile $GuestProfile -VenvPath $VenvPath -Credential $Credential -PromptCredential:$PromptCredential -ManifestRoot $ManifestRoot
        if ($verifyRes.status -ne 'verified') {
            $reasons = if ($verifyRes.failures) { ($verifyRes.failures -join '; ') } else { 'unknown failure' }
            throw "Refusing qualified baseline checkpoint for '$Name': guest verification failed ($($verifyRes.status): $reasons)."
        }
        $guestVerified = $true
    }
    $res = New-VmLabCheckpoint -Name $Name -CheckpointName $CheckpointName -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
    if ($res.status -eq 'checkpoint_created') {
        $res | Add-Member -NotePropertyName 'baseline' -NotePropertyValue $true -Force
        $res.status = 'baseline_created'
    }
    $res | Add-Member -NotePropertyName 'guest_verified' -NotePropertyValue $guestVerified -Force
    $res | Add-Member -NotePropertyName 'baseline_qualified' -NotePropertyValue ($guestVerified -and ($res.status -eq 'baseline_created')) -Force
    $res.operation = 'baseline'
    return $res
}
