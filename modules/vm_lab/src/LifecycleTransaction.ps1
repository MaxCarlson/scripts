#Requires -Version 7.0

function Wait-VmLabGuestReady {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [int]$TimeoutSeconds = 120,
        [int]$PollIntervalMs = 500,
        [hashtable]$IdentityPolicy,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Assert-VmLabTargetNotProtected -VmName $Name
    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) { throw "VM '$Name' was not found." }
    Assert-VmLabTargetNotProtected -VmName $vm.Name -VmId ([string]$vm.Id)
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    if (-not $own.owned) { throw "VM '$Name' is not owned by vm_lab: $($own.reason)" }

    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        return [pscustomobject]@{
            status      = 'AWAITING_INTERACTION'
            reason_code = 'guest_credentials_required'
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
        }
    }

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds([Math]::Max(1, $TimeoutSeconds))
    $attempts = 0
    $lastReason = 'guest_readiness_timeout'
    $lastDetail = $null

    while ([DateTimeOffset]::UtcNow -le $deadline) {
        $attempts++
        $gs = Get-VmLabGuestStatus -Name $vm.Name -Credential $cred -ManifestRoot $ManifestRoot
        if ($gs.guest_state -eq 'ps_direct_auth_failed') {
            return [pscustomobject]@{
                status      = 'FAILED'
                reason_code = 'ps_direct_auth_failed'
                vm_name     = $vm.Name
                vm_id       = [string]$vm.Id
                attempts    = $attempts
                guest       = $gs
            }
        }
        if ($gs.guest_state -eq 'guest_ready' -and $gs.ps_direct_available) {
            if ($IdentityPolicy) {
                $idRes = Test-VmLabGuestIdentityPolicy -Name $vm.Name -Credential $cred -Policy $IdentityPolicy -ManifestRoot $ManifestRoot
                if ($idRes.status -ne 'SUCCEEDED') {
                    return [pscustomobject]@{
                        status      = 'FAILED'
                        reason_code = $idRes.reason_code
                        vm_name     = $vm.Name
                        vm_id       = [string]$vm.Id
                        attempts    = $attempts
                        identity    = $idRes
                    }
                }
            }
            return [pscustomobject]@{
                status      = 'SUCCEEDED'
                reason_code = 'guest_ready'
                vm_name     = $vm.Name
                vm_id       = [string]$vm.Id
                attempts    = $attempts
                guest       = $gs
            }
        }
        $lastReason = $gs.guest_state
        $lastDetail = $gs.detail
        if ([DateTimeOffset]::UtcNow -ge $deadline) { break }
        Start-Sleep -Milliseconds ([Math]::Max(20, $PollIntervalMs))
    }

    return [pscustomobject]@{
        status      = 'PARTIAL'
        reason_code = 'guest_readiness_timeout'
        last_state  = $lastReason
        detail      = $lastDetail
        vm_name     = $vm.Name
        vm_id       = [string]$vm.Id
        attempts    = $attempts
    }
}

function Invoke-VmLabCheckpointTransaction {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$CheckpointName,
        [bool]$RequireOff = $true,
        [switch]$RestartAfter,
        [int]$ShutdownTimeoutSeconds = 60,
        [int]$ReadinessTimeoutSeconds = 120,
        [int]$PollIntervalMs = 500,
        [int64]$MinHostReserveBytes = 4GB,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [hashtable]$IdentityPolicy,
        [switch]$Apply,
        [switch]$AuthorizeVmLifecycle,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Assert-VmLabTargetNotProtected -VmName $Name
    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) { throw "VM '$Name' was not found." }
    Assert-VmLabTargetNotProtected -VmName $vm.Name -VmId ([string]$vm.Id)
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    if (-not $own.owned) { throw "VM '$Name' is not owned by vm_lab: $($own.reason)" }

    $authorized = Test-VmLabCapabilityAuthorized -Capability 'vm_lifecycle' -Apply:$Apply -AuthorizeVmLifecycle:$AuthorizeVmLifecycle
    if (-not $authorized -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($vm.Name, "Execute checkpoint transaction '$CheckpointName'")) {
        $reason = if (-not $Apply -or $WhatIfPreference) { 'dry_run_not_applied' } else { 'vm_lifecycle_authorization_required' }
        return [pscustomobject]@{
            status          = if ($reason -eq 'dry_run_not_applied') { 'PLANNED' } else { 'BLOCKED' }
            reason_code     = $reason
            dry_run         = $true
            vm_name         = $vm.Name
            vm_id           = [string]$vm.Id
            checkpoint_name = $CheckpointName
            require_off     = $RequireOff
            restart_after   = [bool]$RestartAfter
        }
    }

    if ([string]$vm.CheckpointType -ne 'Standard') {
        return [pscustomobject]@{
            status      = 'FAILED'
            reason_code = 'checkpoint_type_not_standard'
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
            detail      = "VM CheckpointType is '$($vm.CheckpointType)', expected 'Standard'."
        }
    }

    $existingSnaps = @(Get-VmLabCheckpoint -Name $vm.Name -ManifestRoot $ManifestRoot)
    if ($existingSnaps | Where-Object { $_.checkpoint_name -eq $CheckpointName }) {
        return [pscustomobject]@{
            status          = 'FAILED'
            reason_code     = 'duplicate_checkpoint_name'
            vm_name         = $vm.Name
            vm_id           = [string]$vm.Id
            checkpoint_name = $CheckpointName
        }
    }

    # Step 1: Close any lingering PS Direct sessions for this VM before graceful shutdown
    try {
        Get-PSSession -ErrorAction SilentlyContinue | Where-Object { $_.ComputerName -eq $vm.Name } | Remove-PSSession -ErrorAction SilentlyContinue
    } catch {}

    $shutdownRes = $null
    if ($RequireOff -and [string]$vm.State -ne 'Off') {
        $shutdownRes = Stop-VmLabMachine -Name $vm.Name -ShutdownTimeoutSeconds $ShutdownTimeoutSeconds -Apply -ManifestRoot $ManifestRoot
        if ($shutdownRes.status -notin @('stopped', 'already_stopped')) {
            return [pscustomobject]@{
                status          = 'PARTIAL'
                reason_code     = 'shutdown_not_confirmed'
                vm_name         = $vm.Name
                vm_id           = [string]$vm.Id
                checkpoint_name = $CheckpointName
                shutdown        = $shutdownRes
            }
        }
    }

    # Step 2: Reacquire VM by ID and verify name/ownership before Checkpoint
    $vmRe = Get-VM -ErrorAction Stop | Where-Object { [string]$_.Id -eq [string]$vm.Id } | Select-Object -First 1
    if (-not $vmRe -or $vmRe.Name -ne $vm.Name) {
        return [pscustomobject]@{
            status      = 'FAILED'
            reason_code = 'vm_identity_changed'
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
        }
    }
    $cpRes = New-VmLabCheckpoint -Name $vmRe.Name -CheckpointName $CheckpointName -Apply -ManifestRoot $ManifestRoot
    if ($cpRes.status -ne 'created') {
        return [pscustomobject]@{
            status      = 'FAILED'
            reason_code = 'checkpoint_creation_failed'
            vm_name     = $vmRe.Name
            vm_id       = [string]$vmRe.Id
            checkpoint  = $cpRes
        }
    }

    $startRes = $null
    $readyRes = $null
    if ($RestartAfter) {
        $startRes = Start-VmLabMachine -Name $vmRe.Name -MinHostReserveBytes $MinHostReserveBytes -Apply -ManifestRoot $ManifestRoot
        if ($startRes.status -notin @('started', 'already_running')) {
            return [pscustomobject]@{
                status          = 'PARTIAL'
                reason_code     = 'restart_failed_after_checkpoint'
                vm_name         = $vmRe.Name
                vm_id           = [string]$vmRe.Id
                checkpoint_id   = $cpRes.checkpoint_id
                checkpoint_name = $CheckpointName
                shutdown        = $shutdownRes
                checkpoint      = $cpRes
                start           = $startRes
            }
        }
        $readyRes = Wait-VmLabGuestReady -Name $vmRe.Name -Credential $Credential -PromptCredential:$PromptCredential -TimeoutSeconds $ReadinessTimeoutSeconds -PollIntervalMs $PollIntervalMs -IdentityPolicy $IdentityPolicy -ManifestRoot $ManifestRoot
        if ($readyRes.status -ne 'SUCCEEDED') {
            return [pscustomobject]@{
                status          = $readyRes.status
                reason_code     = $readyRes.reason_code
                vm_name         = $vmRe.Name
                vm_id           = [string]$vmRe.Id
                checkpoint_id   = $cpRes.checkpoint_id
                checkpoint_name = $CheckpointName
                shutdown        = $shutdownRes
                checkpoint      = $cpRes
                start           = $startRes
                readiness       = $readyRes
            }
        }
    }

    return [pscustomobject]@{
        status          = 'SUCCEEDED'
        reason_code     = 'lifecycle_transaction_complete'
        vm_name         = $vmRe.Name
        vm_id           = [string]$vmRe.Id
        checkpoint_id   = $cpRes.checkpoint_id
        checkpoint_name = $CheckpointName
        checkpoint_type = $cpRes.checkpoint_type
        shutdown        = $shutdownRes
        checkpoint      = $cpRes
        start           = $startRes
        readiness       = $readyRes
    }
}
