#Requires -Version 7.0

function Get-VmLabRecoveryPlan {
    [CmdletBinding()]
    param(
        [string]$Name,
        [string]$VmRoot,
        [pscredential]$Credential,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $manifestRootFull = Resolve-VmLabFullPath -Path $ManifestRoot -Label 'Manifest root' -RejectDriveRoot
    $findings = [System.Collections.Generic.List[string]]::new()
    $actions = [System.Collections.Generic.List[string]]::new()

    $vm = $null
    $hyperVError = $null
    try {
        $allVms = @(Get-VM -ErrorAction Stop)
        if (-not [string]::IsNullOrWhiteSpace($Name)) {
            $vm = $allVms | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
        }
    } catch {
        $hyperVError = $_.Exception.Message
        $findings.Add("Hyper-V inventory query failed: $hyperVError")
        $actions.Add('Run from an elevated Administrator or Hyper-V Administrators session.')
    }

    if ([string]::IsNullOrWhiteSpace($Name)) {
        $locks = @()
        if (Test-Path -LiteralPath $manifestRootFull -PathType Container) {
            $locks = @(Get-ChildItem -LiteralPath $manifestRootFull -Filter '*.lock' -File -ErrorAction SilentlyContinue)
        }
        foreach ($lk in $locks) {
            $findings.Add("Stale provisioning lock file found: '$($lk.FullName)' (last write: $($lk.LastWriteTimeUtc.ToString('o'))).")
            $actions.Add("Verify no provisioning operation is running for '$($lk.BaseName)', then inspect and remove '$($lk.FullName)' if stale.")
        }
        if ($findings.Count -eq 0) {
            $findings.Add('No stale provisioning locks or host-level errors detected.')
        }
        return [pscustomobject]@{
            status              = if ($actions.Count -gt 0) { 'attention_required' } else { 'healthy' }
            operation           = 'recovery-plan'
            manifest_root       = $manifestRootFull
            stale_locks         = @($locks | ForEach-Object { $_.FullName })
            findings            = @($findings)
            recommended_actions = @($actions)
        }
    }

    $lockPath = Join-Path $manifestRootFull "$Name.lock"
    $hasLock = Test-Path -LiteralPath $lockPath
    if ($hasLock) {
        $findings.Add("Provisioning lock exists for '$Name' at '$lockPath'.")
        $actions.Add("Verify no active New-VmLabMachine process is running for '$Name' before removing '$lockPath'.")
    }

    $manRec = Read-VmLabOwnershipManifestRecord -VmName $Name -ManifestRoot $manifestRootFull
    $findings.Add("Manifest state for '$Name': $($manRec.state) ($($manRec.reason)).")

    $vhdxPath = $null
    $vmCfgPath = $null
    if ($manRec.manifest) {
        $vhdxPath = $manRec.manifest.vhdx_path
        $vmCfgPath = $manRec.manifest.vm_config_path
    } elseif (-not [string]::IsNullOrWhiteSpace($VmRoot)) {
        $rootFull = Resolve-VmLabFullPath -Path $VmRoot -Label 'VmRoot' -RejectDriveRoot
        $vhdxPath = Join-Path $rootFull "vhdx\$Name.vhdx"
        $vmCfgPath = Join-Path $rootFull 'vm'
    }

    $vhdxExists = if ($vhdxPath) { Test-Path -LiteralPath $vhdxPath -PathType Leaf } else { $false }
    $cfgExists = if ($vmCfgPath) { Test-Path -LiteralPath $vmCfgPath -PathType Container } else { $false }

    if ($null -eq $vm -and $null -eq $hyperVError) {
        $findings.Add("VM '$Name' is not registered in Hyper-V.")
        if ($vhdxExists -or $cfgExists) {
            $findings.Add("Partial filesystem artifacts found (vhdx_exists=$vhdxExists, config_dir_exists=$cfgExists).")
            $actions.Add("Inspect preserved artifacts under '$vmCfgPath' / '$vhdxPath' and move or archive them before re-running creation.")
        } elseif ($manRec.state -eq 'ok') {
            $actions.Add("Manifest exists for '$Name' without a registered Hyper-V VM; inspect '$($manRec.path)' before archiving.")
        } else {
            $actions.Add("No partial artifacts found; you can safely run: vm-lab -o quickstart -t windows11-dev -n '$Name'")
        }
    } elseif ($null -ne $vm) {
        $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $manifestRootFull
        $findings.Add("Hyper-V VM '$Name' exists (Id=$($vm.Id), State=$($vm.State), Ownership=$($own.ownership_state)).")
        if (-not $own.owned) {
            $actions.Add("VM '$Name' is not owned by vm_lab ($($own.reason)). vm_lab will not adopt or modify it automatically.")
        } else {
            $snaps = @(Get-VMSnapshot -VMName $Name -ErrorAction SilentlyContinue)
            $findings.Add("Checkpoint count: $($snaps.Count).")
            if ([string]$vm.State -eq 'Off') {
                $actions.Add("Start VM with: vm-lab -o start -n '$Name' -Apply")
            } elseif ([string]$vm.State -eq 'Running') {
                $gs = Get-VmLabGuestStatus -Name $Name -Credential $Credential -ManifestRoot $manifestRootFull
                $findings.Add("Guest state: $($gs.guest_state) ($($gs.detail)).")
                if ($gs.guest_state -eq 'ps_direct_auth_failed') {
                    $actions.Add('Verify local Windows guest account credentials and retry guest-status.')
                } elseif ($gs.guest_state -eq 'windows_booted_account_unavailable') {
                    $actions.Add("Open VMConnect (vm-lab -o connect -n '$Name') to complete Windows Setup / local account creation.")
                } elseif ($gs.guest_state -eq 'ps_direct_operational') {
                    $actions.Add("Run guest bootstrap (vm-lab -o guest-bootstrap -n '$Name' -Apply) and capture baseline (vm-lab -o baseline -n '$Name' -Apply).")
                }
            } else {
                $actions.Add("VM is in state '$($vm.State)'; wait for transition to settle before mutating.")
            }
        }
    }

    return [pscustomobject]@{
        status              = if ($actions.Count -gt 0) { 'diagnostic_complete' } else { 'healthy' }
        operation           = 'recovery-plan'
        vm_name             = $Name
        vm_registered       = ($null -ne $vm)
        vm_state            = if ($vm) { [string]$vm.State } else { 'Missing' }
        manifest_state      = $manRec.state
        lock_present        = $hasLock
        vhdx_exists         = $vhdxExists
        config_dir_exists   = $cfgExists
        findings            = @($findings)
        recommended_actions = @($actions)
    }
}
