#Requires -Version 7.0

function Resolve-VmLabTargetVm {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$NameOrId,
        [string]$ExpectedVmId,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Assert-VmLabTargetNotProtected -VmName $NameOrId -VmId $ExpectedVmId
    $parsedGuid = [guid]::Empty
    $isGuid = [guid]::TryParse($NameOrId, [ref]$parsedGuid)
    $allVms = @(Get-VM -ErrorAction Stop)
    $vm = if ($isGuid) {
        $allVms | Where-Object { [string]$_.Id -ieq $parsedGuid.ToString() } | Select-Object -First 1
    } else {
        $allVms | Where-Object { $_.Name -eq $NameOrId } | Select-Object -First 1
    }
    if (-not $vm) {
        throw "VM '$NameOrId' was not found in Hyper-V inventory."
    }
    Assert-VmLabTargetNotProtected -VmName $vm.Name -VmId ([string]$vm.Id)
    if (-not [string]::IsNullOrWhiteSpace($ExpectedVmId) -and ([string]$vm.Id).ToLowerInvariant() -ne $ExpectedVmId.Trim().ToLowerInvariant()) {
        throw "VM ID mismatch for '$($vm.Name)': expected '$ExpectedVmId', actual '$($vm.Id)'."
    }
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    return [pscustomobject]@{
        vm        = $vm
        ownership = $own
    }
}

function Test-VmLabIsoMedia {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$IsoPath,
        [string]$ExpectedSha256,
        [int64]$MinSizeBytes = 1048576
    )
    $full = Test-VmLabSafePath -Path $IsoPath -Label 'IsoPath' -CheckReparsePoints
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        return [pscustomobject]@{
            status      = 'FAILED'
            reason_code = 'iso_not_found'
            iso_path    = $full
        }
    }
    $fi = Get-Item -LiteralPath $full -Force
    if ($fi.Length -lt $MinSizeBytes) {
        return [pscustomobject]@{
            status      = 'FAILED'
            reason_code = 'iso_too_small'
            iso_path    = $full
            length      = [int64]$fi.Length
            min_bytes   = $MinSizeBytes
        }
    }
    $sha = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
        if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
            throw "Invalid ExpectedSha256 format: '$ExpectedSha256'."
        }
        if ($sha -ne $ExpectedSha256.ToLowerInvariant()) {
            return [pscustomobject]@{
                status          = 'FAILED'
                reason_code     = 'iso_sha256_mismatch'
                iso_path        = $full
                length          = [int64]$fi.Length
                actual_sha256   = $sha
                expected_sha256 = $ExpectedSha256.ToLowerInvariant()
            }
        }
    }
    return [pscustomobject]@{
        status      = 'SUCCEEDED'
        reason_code = 'iso_verified'
        iso_path    = $full
        length      = [int64]$fi.Length
        sha256      = $sha
    }
}

function Set-VmLabBootMedia {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$IsoPath,
        [switch]$Detach,
        [switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $resolved = Resolve-VmLabTargetVm -NameOrId $Name -ManifestRoot $ManifestRoot
    if (-not $resolved.ownership.owned) {
        throw "VM '$($resolved.vm.Name)' is not owned by vm_lab: $($resolved.ownership.reason)"
    }
    $vm = $resolved.vm
    $targetIso = if ($Detach) { $null } else { Test-VmLabSafePath -Path $IsoPath -Label 'IsoPath' -CheckReparsePoints }
    if (-not $Detach -and -not (Test-Path -LiteralPath $targetIso -PathType Leaf)) {
        throw "ISO file not found: '$targetIso'."
    }
    if (-not $Apply -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($vm.Name, $(if ($Detach) { 'Detach DVD ISO' } else { "Attach ISO '$targetIso'" }))) {
        return [pscustomobject]@{
            status      = 'PLANNED'
            reason_code = 'dry_run_not_applied'
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
            action      = if ($Detach) { 'detach' } else { 'attach' }
            iso_path    = $targetIso
        }
    }
    if (-not (Test-VmLabAdministrator)) {
        throw 'Administrator elevation is required to modify Hyper-V DVD media.'
    }
    $dvd = Get-VMDvdDrive -VMName $vm.Name -ErrorAction Stop | Select-Object -First 1
    if (-not $dvd) {
        if ($Detach) {
            return [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'no_dvd_drive_present'; vm_name = $vm.Name; vm_id = [string]$vm.Id }
        }
        $dvd = Add-VMDvdDrive -VMName $vm.Name -Path $targetIso -Passthru -ErrorAction Stop
    } else {
        Set-VMDvdDrive -VMDvdDrive $dvd -Path $targetIso -ErrorAction Stop
    }
    return [pscustomobject]@{
        status      = 'SUCCEEDED'
        reason_code = if ($Detach) { 'iso_detached' } else { 'iso_attached' }
        vm_name     = $vm.Name
        vm_id       = [string]$vm.Id
        iso_path    = $targetIso
    }
}

function Set-VmLabFirmwareBootOrder {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [switch]$PreferDvd,
        [switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $resolved = Resolve-VmLabTargetVm -NameOrId $Name -ManifestRoot $ManifestRoot
    if (-not $resolved.ownership.owned) {
        throw "VM '$($resolved.vm.Name)' is not owned by vm_lab: $($resolved.ownership.reason)"
    }
    $vm = $resolved.vm
    if (-not $Apply -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($vm.Name, 'Update UEFI firmware boot order')) {
        return [pscustomobject]@{
            status      = 'PLANNED'
            reason_code = 'dry_run_not_applied'
            vm_name     = $vm.Name
            vm_id       = [string]$vm.Id
            prefer_dvd  = [bool]$PreferDvd
        }
    }
    if (-not (Test-VmLabAdministrator)) {
        throw 'Administrator elevation is required to modify Hyper-V VM firmware.'
    }
    if ([string]$vm.State -ne 'Off') {
        throw "VM '$($vm.Name)' must be Off to change firmware boot order (current state: '$($vm.State)')."
    }
    $fw = Get-VMFirmware -VMName $vm.Name -ErrorAction Stop
    $dvd = @($fw.BootOrder | Where-Object { $_.BootType -eq 'Drive' -and $_.Device -match 'Dvd' })
    $hd = @($fw.BootOrder | Where-Object { $_.BootType -eq 'Drive' -and $_.Device -notmatch 'Dvd' })
    $other = @($fw.BootOrder | Where-Object { $_.BootType -ne 'Drive' })
    $newOrder = if ($PreferDvd) { @($dvd) + @($hd) + @($other) } else { @($hd) + @($dvd) + @($other) }
    Set-VMFirmware -VMName $vm.Name -BootOrder $newOrder -ErrorAction Stop
    return [pscustomobject]@{
        status      = 'SUCCEEDED'
        reason_code = 'firmware_boot_order_updated'
        vm_name     = $vm.Name
        vm_id       = [string]$vm.Id
        prefer_dvd  = [bool]$PreferDvd
    }
}

function Get-VmLabBootRecovery {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $resolved = Resolve-VmLabTargetVm -NameOrId $Name -ManifestRoot $ManifestRoot
    $vm = $resolved.vm
    $boot = Get-VmLabBootDiagnostics -Name $vm.Name -ManifestRoot $ManifestRoot
    $steps = @()
    if (-not $boot.dvd_first_in_boot_order) {
        $steps += "Run 'vm boot prepare $($vm.Name) --prefer-dvd -a' while VM is Off to place DVD ahead of VHDX."
    }
    $steps += "Open VMConnect ('vm connect $($vm.Name) -a'), trigger Reset if the 'Press any key to boot from CD or DVD' prompt timed out, and press a key immediately."
    return [pscustomobject]@{
        status                  = 'SUCCEEDED'
        reason_code             = 'boot_recovery_guidance'
        vm_name                 = $vm.Name
        vm_id                   = [string]$vm.Id
        vm_state                = [string]$vm.State
        dvd_first_in_boot_order = $boot.dvd_first_in_boot_order
        boot_diagnostics        = $boot
        recovery_steps          = @($steps)
    }
}
