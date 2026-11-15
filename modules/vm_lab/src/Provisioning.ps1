#Requires -Version 7.0

function Assert-VmLabDirectoryEmptyOrMissing {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label
    )
    if (Test-Path -LiteralPath $Path) {
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
            throw "$Label path exists and is not a directory: '$Path'."
        }
        $children = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction Stop)
        if ($children.Count -gt 0) {
            throw "$Label directory already exists and is not empty: '$Path'."
        }
    }
}

function Test-VmLabPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][psobject]$Config,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $null = Test-VmLabConfig -Config $Config
    $vmRootFull = Resolve-VmLabFullPath -Path $Config.vm_root -Label 'VM root' -RejectDriveRoot
    Assert-VmLabNoReparsePoint -FullPath $vmRootFull -Label 'VM root'
    $vmPath = Resolve-VmLabFullPath -Path (Join-Path $vmRootFull 'vm') -Label 'VM config path' -RejectDriveRoot
    $vhdxDir = Resolve-VmLabFullPath -Path (Join-Path $vmRootFull 'vhdx') -Label 'VHDX directory' -RejectDriveRoot
    $vhdxPath = Resolve-VmLabFullPath -Path (Join-Path $vhdxDir "$($Config.vm_name).vhdx") -Label 'VHDX path' -RejectDriveRoot
    Assert-VmLabNoReparsePoint -FullPath $vmPath -Label 'VM config path'
    Assert-VmLabNoReparsePoint -FullPath $vhdxPath -Label 'VHDX path'

    Assert-VmLabDirectoryEmptyOrMissing -Path $vmRootFull -Label 'VM root'
    Assert-VmLabDirectoryEmptyOrMissing -Path $vmPath -Label 'VM config'
    Assert-VmLabDirectoryEmptyOrMissing -Path $vhdxDir -Label 'VHDX'

    $manifestRootFull = Resolve-VmLabFullPath -Path $ManifestRoot -Label 'Manifest root' -RejectDriveRoot
    Assert-VmLabNoReparsePoint -FullPath $manifestRootFull -Label 'Manifest root'
    $manifestPath = Get-VmLabManifestPath -VmName $Config.vm_name -ManifestRoot $manifestRootFull
    Assert-VmLabNoReparsePoint -FullPath $manifestPath -Label 'Manifest file'
    if (Test-Path -LiteralPath $manifestPath) {
        throw "Ownership manifest already exists for '$($Config.vm_name)': $manifestPath. Refusing to overwrite or adopt."
    }

    if (-not [string]::IsNullOrWhiteSpace($Config.iso_path)) {
        $isoFull = Resolve-VmLabFullPath -Path $Config.iso_path -Label 'ISO' -RejectDriveRoot
        if (-not (Test-Path -LiteralPath $isoFull -PathType Leaf)) {
            throw "ISO file not found: $isoFull"
        }
        Assert-VmLabNoReparsePoint -FullPath $isoFull -Label 'ISO'
        $isoItem = Get-Item -LiteralPath $isoFull -Force -ErrorAction Stop
        if ($isoItem.Length -lt 3GB) {
            throw "ISO file is unexpectedly small ($($isoItem.Length) bytes): $isoFull"
        }
    }

    $null = Get-VMHost -ErrorAction Stop
    $existingVms = @(Get-VM -ErrorAction Stop)
    $existingSwitches = @(Get-VMSwitch -ErrorAction Stop)

    if ($existingVms | Where-Object { $_.Name -eq $Config.vm_name }) {
        throw "VM '$($Config.vm_name)' already exists in Hyper-V inventory."
    }
    foreach ($existing in $existingVms) {
        if (-not [string]::IsNullOrWhiteSpace($existing.ConfigurationLocation)) {
            $existingCfg = $null
            try {
                $existingCfg = Resolve-VmLabFullPath -Path $existing.ConfigurationLocation -Label 'Existing VM ConfigurationLocation' -RejectDriveRoot
            } catch {
                throw "Cannot safely verify path non-conflict against existing VM '$($existing.Name)' (ConfigurationLocation='$($existing.ConfigurationLocation)'): $($_.Exception.Message)"
            }
            if ((Test-VmLabPathIsDescendantOrEqual -BasePath $vmRootFull -CandidatePath $existingCfg) -or
                (Test-VmLabPathIsDescendantOrEqual -BasePath $existingCfg -CandidatePath $vmRootFull)) {
                throw "Target VM root '$vmRootFull' conflicts with existing VM '$($existing.Name)' configuration location '$existingCfg'."
            }
        }
    }

    if (Test-Path -LiteralPath $vhdxPath) {
        throw "Target VHDX already exists: $vhdxPath"
    }
    if (-not [string]::IsNullOrWhiteSpace($Config.switch_name)) {
        if (-not ($existingSwitches | Where-Object { $_.Name -eq $Config.switch_name })) {
            throw "Requested virtual switch '$($Config.switch_name)' does not exist."
        }
    }

    $freeDiskBytes = Get-VmLabDriveFreeBytes -TargetPath $vmRootFull
    if ($freeDiskBytes -lt [int64]$Config.vhdx_size_bytes) {
        throw "Insufficient disk space on target drive for '$vmRootFull': $freeDiskBytes bytes free < $($Config.vhdx_size_bytes) required."
    }

    $memInfo = Get-VmLabHostMemoryInfo
    return [pscustomobject]@{
        status          = 'planned'
        vm_name         = $Config.vm_name
        vm_root         = $vmRootFull
        vm_config_path  = $vmPath
        vhdx_path       = $vhdxPath
        vhdx_format     = $Config.vhdx_format
        vhdx_size_bytes = [int64]$Config.vhdx_size_bytes
        free_disk_bytes = $freeDiskBytes
        free_ram_bytes  = $memInfo.FreePhysicalBytes
        total_ram_bytes = $memInfo.TotalPhysicalBytes
        config          = $Config
    }
}

function New-VmLabMachine {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][psobject]$Config,
        [Alias('a')][switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $plan = Test-VmLabPlan -Config $Config -ManifestRoot $ManifestRoot
    if (-not $Apply -or $WhatIfPreference) {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($Config.vm_name, "Create lab VM at '$($plan.vm_root)'")
        }
        return $plan
    }
    if (-not (Test-VmLabAdministrator)) {
        throw 'Administrator elevation is required to create Hyper-V VMs.'
    }
    if (-not $PSCmdlet.ShouldProcess($Config.vm_name, "Create lab VM at '$($plan.vm_root)'")) {
        return $plan
    }

    $manifestRootFull = Resolve-VmLabFullPath -Path $ManifestRoot -Label 'Manifest root' -RejectDriveRoot
    Assert-VmLabNoReparsePoint -FullPath $manifestRootFull -Label 'Manifest root'
    if (-not (Test-Path -LiteralPath $manifestRootFull)) {
        New-Item -ItemType Directory -Path $manifestRootFull -Force -ErrorAction Stop | Out-Null
    }
    $lockPath = Join-Path $manifestRootFull "$($Config.vm_name).lock"
    $lockStream = $null
    try {
        try {
            $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        } catch {
            throw "Concurrent provisioning in progress or stale lock exists for '$($Config.vm_name)' at '$lockPath'."
        }

        # Revalidate immediately before mutation to reduce stale-preflight risk
        $plan = Test-VmLabPlan -Config $Config -ManifestRoot $manifestRootFull
        $opId = [guid]::NewGuid().ToString('N')
        $stage = 'directories'
        $newVm = $null
        $vhdCreated = $false
        $vmCreated = $false

        try {
            $vhdxDir = Split-Path -Parent $plan.vhdx_path
            foreach ($dir in @($plan.vm_root, $plan.vm_config_path, $vhdxDir)) {
                if (-not (Test-Path -LiteralPath $dir)) {
                    New-Item -ItemType Directory -Path $dir -Force -ErrorAction Stop | Out-Null
                }
            }

            $stage = 'create_vhd'
            if ($Config.vhdx_format -eq 'Fixed') {
                $null = New-VHD -Path $plan.vhdx_path -SizeBytes ([int64]$Config.vhdx_size_bytes) -Fixed -ErrorAction Stop
            } else {
                $null = New-VHD -Path $plan.vhdx_path -SizeBytes ([int64]$Config.vhdx_size_bytes) -Dynamic -ErrorAction Stop
            }
            $vhdCreated = $true

            $stage = 'create_vm'
            $newVm = New-VM `
                -Name $Config.vm_name `
                -Generation ([int]$Config.generation) `
                -MemoryStartupBytes ([int64]$Config.memory_startup_bytes) `
                -Path $plan.vm_config_path `
                -VHDPath $plan.vhdx_path `
                -ErrorAction Stop
            $vmCreated = $true

            $stage = 'configure_network'
            Get-VMNetworkAdapter -VMName $Config.vm_name -ErrorAction Stop | Remove-VMNetworkAdapter -ErrorAction Stop
            if (-not [string]::IsNullOrWhiteSpace($Config.switch_name)) {
                Add-VMNetworkAdapter -VMName $Config.vm_name -SwitchName $Config.switch_name -ErrorAction Stop | Out-Null
            }

            $stage = 'configure_vm'
            Set-VM -Name $Config.vm_name `
                -ProcessorCount ([int]$Config.cpu_count) `
                -DynamicMemory `
                -MemoryMinimumBytes ([int64]$Config.memory_minimum_bytes) `
                -MemoryStartupBytes ([int64]$Config.memory_startup_bytes) `
                -MemoryMaximumBytes ([int64]$Config.memory_maximum_bytes) `
                -CheckpointType ([string]$Config.checkpoint_type) `
                -AutomaticCheckpointsEnabled ([bool]$Config.automatic_checkpoints_enabled) `
                -AutomaticStartAction ([string]$Config.automatic_start_action) `
                -ErrorAction Stop

            $stage = 'configure_firmware'
            if ($Config.secure_boot.enabled) {
                Set-VMFirmware -VMName $Config.vm_name -EnableSecureBoot On -SecureBootTemplate ([string]$Config.secure_boot.template) -ErrorAction Stop
            } else {
                Set-VMFirmware -VMName $Config.vm_name -EnableSecureBoot Off -ErrorAction Stop
            }

            if ($Config.vtpm_enabled) {
                $stage = 'configure_vtpm'
                Set-VMKeyProtector -VMName $Config.vm_name -NewLocalKeyProtector -ErrorAction Stop
                Enable-VMTPM -VMName $Config.vm_name -ErrorAction Stop
            }

            if (-not [string]::IsNullOrWhiteSpace($Config.iso_path)) {
                $stage = 'attach_iso'
                $isoFull = Resolve-VmLabFullPath -Path $Config.iso_path -Label 'ISO' -RejectDriveRoot
                $dvd = Add-VMDvdDrive -VMName $Config.vm_name -Path $isoFull -Passthru -ErrorAction Stop
                $vhd = Get-VMHardDiskDrive -VMName $Config.vm_name -ErrorAction Stop
                Set-VMFirmware -VMName $Config.vm_name -BootOrder $dvd, $vhd -ErrorAction Stop
            }

            $stage = 'verify_vm'
            $verifiedVm = Get-VM -ErrorAction Stop | Where-Object { $_.Id -eq $newVm.Id } | Select-Object -First 1
            if (-not $verifiedVm) {
                throw "Created VM '$($Config.vm_name)' (ID $($newVm.Id)) could not be verified in Hyper-V inventory."
            }
            if ($verifiedVm.Generation -ne [int]$Config.generation) {
                throw "Verified VM generation '$($verifiedVm.Generation)' does not match requested '$($Config.generation)'."
            }
            if ($verifiedVm.ProcessorCount -ne [int]$Config.cpu_count) {
                throw "Verified VM ProcessorCount '$($verifiedVm.ProcessorCount)' does not match requested '$($Config.cpu_count)'."
            }

            $stage = 'write_manifest'
            $manifest = [pscustomobject]@{
                schema_version  = 1
                vm_name         = $Config.vm_name
                vm_id           = [string]$verifiedVm.Id
                created_at      = [DateTimeOffset]::UtcNow.ToString('o')
                vm_config_path  = $plan.vm_config_path
                vhdx_path       = $plan.vhdx_path
                vhdx_format     = [string]$Config.vhdx_format
                template_id     = [string]$Config.template_id
                owner_namespace = [string]$Config.owner_namespace
                operation_id    = $opId
            }
            $manifestPath = Write-VmLabOwnershipManifest -Manifest $manifest -ManifestRoot $manifestRootFull
        } catch {
            $vmIdInfo = if ($newVm -and $newVm.Id) { [string]$newVm.Id } else { 'none' }
            throw ("VM provisioning failed at stage '$stage' (op_id=$opId, vm_name=$($Config.vm_name), vm_id=$vmIdInfo, vhd_created=$vhdCreated, vm_created=$vmCreated, vhdx_path=$($plan.vhdx_path), vm_config_path=$($plan.vm_config_path)). Partial artifacts were preserved for inspection. Error: $($_.Exception.Message)")
        }

        return [pscustomobject]@{
            status        = 'created'
            vm_name       = $Config.vm_name
            vm_id         = [string]$verifiedVm.Id
            vhdx_format   = [string]$Config.vhdx_format
            manifest_path = $manifestPath
            manifest      = $manifest
        }
    } finally {
        if ($null -ne $lockStream) {
            $lockStream.Dispose()
            if (Test-Path -LiteralPath $lockPath) {
                Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
            }
        }
    }
}
