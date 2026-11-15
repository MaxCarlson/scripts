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

function Invoke-VmLabQuickstart {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][psobject]$Config,
        [Alias('a')][switch]$Apply,
        [switch]$Start,
        [switch]$Connect,
        [int64]$MinHostReserveBytes = 4GB,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $null = Test-VmLabConfig -Config $Config
    $vmHost = Get-VMHost -ErrorAction Stop
    $hostName = if ($vmHost.ComputerName) { [string]$vmHost.ComputerName } else { $env:COMPUTERNAME }
    $netState = if ([string]::IsNullOrWhiteSpace($Config.switch_name)) { 'Disconnected (no virtual switch)' } else { "Connected ($($Config.switch_name))" }

    $existingVm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Config.vm_name } | Select-Object -First 1
    if ($existingVm) {
        $own = Test-VmLabOwnership -Vm $existingVm -ManifestRoot $ManifestRoot
        if (-not $own.owned) {
            throw "VM '$($Config.vm_name)' already exists in Hyper-V and is not owned by vm_lab ($($own.reason)). Refusing to adopt or recreate."
        }
        $vmState = [string]$existingVm.State
        $startRes = $null
        if ($Start -and $Apply -and -not $WhatIfPreference -and $vmState -ne 'Running') {
            $startRes = Start-VmLabMachine -Name $existingVm.Name -MinHostReserveBytes $MinHostReserveBytes -Apply -ManifestRoot $ManifestRoot
            $vmState = $startRes.state
        }
        $connectRes = $null
        if ($Connect -and -not $WhatIfPreference) {
            if (Test-VmLabInteractiveDesktop) {
                $connectRes = Connect-VmLabMachine -Name $existingVm.Name -ManifestRoot $ManifestRoot
            } else {
                $connectRes = [pscustomobject]@{ status = 'skipped_noninteractive'; reason = 'Interactive desktop session required for VMConnect.' }
            }
        }
        $nextAction = if ($vmState -ne 'Running') {
            "Start the existing owned VM with: vm-lab -o start -n '$($existingVm.Name)' -Apply"
        } elseif (-not [string]::IsNullOrWhiteSpace($Config.iso_path)) {
            "Connect via VMConnect (vm-lab -o connect -n '$($existingVm.Name)') and complete Windows Setup, then run: vm-lab -o guest-status -n '$($existingVm.Name)'"
        } else {
            "Verify guest readiness with: vm-lab -o guest-status -n '$($existingVm.Name)'"
        }
        return [pscustomobject]@{
            status               = if ($startRes) { $startRes.status } else { 'existing_owned' }
            operation            = 'quickstart'
            vm_name              = $existingVm.Name
            vm_id                = [string]$existingVm.Id
            host_name            = $hostName
            vm_config_path       = $own.manifest.vm_config_path
            vhdx_path            = $own.manifest.vhdx_path
            vhdx_size_bytes      = [int64]$Config.vhdx_size_bytes
            iso_path             = $Config.iso_path
            network_state        = $netState
            cpu_count            = [int]$existingVm.ProcessorCount
            memory_startup_bytes = [int64]$existingVm.MemoryStartup
            ownership_status     = 'owned'
            vm_state             = $vmState
            connect              = $connectRes
            next_action          = $nextAction
        }
    }

    $plan = Test-VmLabPlan -Config $Config -ManifestRoot $ManifestRoot
    if (-not $Apply -or $WhatIfPreference) {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($Config.vm_name, "Quickstart lab VM at '$($plan.vm_root)'")
        }
        return [pscustomobject]@{
            status               = 'planned'
            operation            = 'quickstart'
            vm_name              = $Config.vm_name
            vm_id                = $null
            host_name            = $hostName
            vm_config_path       = $plan.vm_config_path
            vhdx_path            = $plan.vhdx_path
            vhdx_size_bytes      = $plan.vhdx_size_bytes
            iso_path             = $Config.iso_path
            network_state        = $netState
            cpu_count            = [int]$Config.cpu_count
            memory_startup_bytes = [int64]$Config.memory_startup_bytes
            ownership_status     = 'planned'
            vm_state             = 'NotCreated'
            free_disk_bytes      = $plan.free_disk_bytes
            free_ram_bytes       = $plan.free_ram_bytes
            next_action          = "Re-run with -Apply (-a) to create '$($Config.vm_name)'."
        }
    }

    $created = New-VmLabMachine -Config $Config -Apply -ManifestRoot $ManifestRoot
    $vmState = 'Off'
    $startRes = $null
    if ($Start) {
        $startRes = Start-VmLabMachine -Name $Config.vm_name -MinHostReserveBytes $MinHostReserveBytes -Apply -ManifestRoot $ManifestRoot
        $vmState = $startRes.state
    }
    $connectRes = $null
    if ($Connect) {
        if (Test-VmLabInteractiveDesktop) {
            $connectRes = Connect-VmLabMachine -Name $Config.vm_name -ManifestRoot $ManifestRoot
        } else {
            $connectRes = [pscustomobject]@{ status = 'skipped_noninteractive'; reason = 'Interactive desktop session required for VMConnect.' }
        }
    }

    $nextAction = if (-not $Start) {
        "VM created. Start it with: vm-lab -o start -n '$($Config.vm_name)' -Apply (or -o start-connect -n '$($Config.vm_name)' -Apply)."
    } elseif (-not [string]::IsNullOrWhiteSpace($Config.iso_path)) {
        "VM started. Open VMConnect (vm-lab -o connect -n '$($Config.vm_name)') and press any key promptly when prompted to boot from DVD."
    } else {
        "VM started. Check guest readiness with: vm-lab -o guest-status -n '$($Config.vm_name)'"
    }

    return [pscustomobject]@{
        status               = if ($startRes) { 'created_and_started' } else { 'created' }
        operation            = 'quickstart'
        vm_name              = $Config.vm_name
        vm_id                = $created.vm_id
        host_name            = $hostName
        vm_config_path       = $created.manifest.vm_config_path
        vhdx_path            = $created.manifest.vhdx_path
        vhdx_size_bytes      = [int64]$Config.vhdx_size_bytes
        iso_path             = $Config.iso_path
        network_state        = $netState
        cpu_count            = [int]$Config.cpu_count
        memory_startup_bytes = [int64]$Config.memory_startup_bytes
        ownership_status     = 'owned'
        vm_state             = $vmState
        manifest_path        = $created.manifest_path
        connect              = $connectRes
        next_action          = $nextAction
    }
}

function New-VmLabUnattendXml {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [string]$OutputPath,
        [string]$Locale = 'en-US',
        [string]$KeyboardLayout = 'en-US',
        [string]$ImageEdition,
        [int]$TargetDiskIndex = 0,
        [switch]$Overwrite,
        [Alias('a')][switch]$Apply
    )
    if ($TargetDiskIndex -lt 0 -or $TargetDiskIndex -gt 15) {
        throw "TargetDiskIndex must be between 0 and 15 (got $TargetDiskIndex)."
    }
    $safeLocale = [System.Security.SecurityElement]::Escape($Locale)
    $safeKb = [System.Security.SecurityElement]::Escape($KeyboardLayout)
    $imageInstallXml = if (-not [string]::IsNullOrWhiteSpace($ImageEdition)) {
        $safeEd = [System.Security.SecurityElement]::Escape($ImageEdition)
        @"
        <OSImage>
          <InstallFrom>
            <MetaData wcm:action="add">
              <Key>/IMAGE/NAME</Key>
              <Value>$safeEd</Value>
            </MetaData>
          </InstallFrom>
          <InstallTo>
            <DiskID>$TargetDiskIndex</DiskID>
            <PartitionID>3</PartitionID>
          </InstallTo>
        </OSImage>
"@
    } else {
        @"
        <OSImage>
          <InstallTo>
            <DiskID>$TargetDiskIndex</DiskID>
            <PartitionID>3</PartitionID>
          </InstallTo>
        </OSImage>
"@
    }

    $xml = @"
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <SetupUILanguage>
        <UILanguage>$safeLocale</UILanguage>
      </SetupUILanguage>
      <InputLocale>$safeKb</InputLocale>
      <SystemLocale>$safeLocale</SystemLocale>
      <UILanguage>$safeLocale</UILanguage>
      <UserLocale>$safeLocale</UserLocale>
    </component>
    <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>$TargetDiskIndex</DiskID>
          <WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add"><Order>1</Order><Type>EFI</Type><Size>260</Size></CreatePartition>
            <CreatePartition wcm:action="add"><Order>2</Order><Type>MSR</Type><Size>16</Size></CreatePartition>
            <CreatePartition wcm:action="add"><Order>3</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>FAT32</Format><Label>System</Label></ModifyPartition>
            <ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>2</PartitionID></ModifyPartition>
            <ModifyPartition wcm:action="add"><Order>3</Order><PartitionID>3</PartitionID><Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter></ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>
      <ImageInstall>
$imageInstallXml
      </ImageInstall>
      <UserData>
        <AcceptEula>true</AcceptEula>
      </UserData>
    </component>
  </settings>
</unattend>
"@

    if (-not $Apply -or $WhatIfPreference -or [string]::IsNullOrWhiteSpace($OutputPath)) {
        if ($WhatIfPreference -and -not [string]::IsNullOrWhiteSpace($OutputPath)) {
            $null = $PSCmdlet.ShouldProcess($OutputPath, 'Write Autounattend.xml')
        }
        return [pscustomobject]@{
            status      = 'planned'
            operation   = 'unattend-xml'
            output_path = $OutputPath
            locale      = $Locale
            edition     = $ImageEdition
            note        = 'No passwords are embedded; Windows Setup stops at the OOBE account-creation boundary.'
            xml         = $xml
        }
    }

    $outFull = Resolve-VmLabFullPath -Path $OutputPath -Label 'OutputPath' -RejectDriveRoot
    Assert-VmLabNoReparsePoint -FullPath $outFull -Label 'OutputPath'
    if ((Test-Path -LiteralPath $outFull) -and -not $Overwrite) {
        throw "OutputPath already exists and -Overwrite was not specified: '$outFull'."
    }
    if (-not $PSCmdlet.ShouldProcess($outFull, 'Write Autounattend.xml')) {
        return [pscustomobject]@{ status = 'declined'; operation = 'unattend-xml'; output_path = $outFull }
    }
    $parent = Split-Path -Parent $outFull
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($outFull, $xml, [System.Text.UTF8Encoding]::new($false))
    return [pscustomobject]@{
        status      = 'written'
        operation   = 'unattend-xml'
        output_path = $outFull
        locale      = $Locale
        edition     = $ImageEdition
        note        = 'No passwords are embedded; Windows Setup stops at the OOBE account-creation boundary.'
    }
}
