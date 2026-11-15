#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

function Get-VmLabDefaultManifestRoot {
    if (-not [string]::IsNullOrWhiteSpace($env:VM_LAB_MANIFEST_ROOT)) {
        return $env:VM_LAB_MANIFEST_ROOT
    }
    $localApp = if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { $env:LOCALAPPDATA } else { [System.IO.Path]::GetTempPath() }
    return (Join-Path $localApp 'vm_lab\manifests')
}

function Get-VmLabDriveFreeBytes {
    param([Parameter(Mandatory)][string]$TargetPath)
    $root = [System.IO.Path]::GetPathRoot($TargetPath)
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw "Could not determine drive root for path: $TargetPath"
    }
    return [int64]([System.IO.DriveInfo]::new($root)).AvailableFreeSpace
}

function Get-VmLabHostMemoryInfo {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
    return [pscustomobject]@{
        TotalPhysicalBytes = [int64]$os.TotalVisibleMemorySize * 1KB
        FreePhysicalBytes  = [int64]$os.FreePhysicalMemory * 1KB
    }
}

function Test-VmLabAdministrator {
    if ($IsWindows -or $PSVersionTable.Platform -eq 'Win32NT' -or -not $PSVersionTable.Platform) {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    }
    return $false
}

function Assert-VmLabNoReparsePoint {
    param(
        [Parameter(Mandatory)][string]$FullPath,
        [Parameter(Mandatory)][string]$Label
    )
    $root = [System.IO.Path]::GetPathRoot($FullPath)
    $current = $FullPath
    while (-not [string]::IsNullOrWhiteSpace($current) -and $current -ne $root) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label path traverses a reparse point/symlink at '$current'."
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Get-VmLabTemplate {
    [CmdletBinding()]
    param(
        [string]$TemplateName = 'windows11-h4',
        [string]$ConfigPath
    )
    $path = if (-not [string]::IsNullOrWhiteSpace($ConfigPath)) {
        $ConfigPath
    } else {
        Join-Path $PSScriptRoot "templates\$TemplateName.json"
    }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "VM template/config not found: $path"
    }
    return (Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json)
}

function Test-VmLabConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][psobject]$Config
    )
    $errors = [System.Collections.Generic.List[string]]::new()
    if ([string]::IsNullOrWhiteSpace($Config.vm_name) -or $Config.vm_name -match '[\\/:*?"<>|]') {
        $errors.Add("Invalid vm_name '$($Config.vm_name)'.")
    }
    if ([string]::IsNullOrWhiteSpace($Config.vm_root)) {
        $errors.Add('vm_root is required.')
    }
    if ([int]$Config.generation -ne 2) {
        $errors.Add("Only Generation 2 VMs are supported by vm_lab (got '$($Config.generation)').")
    }
    if ([int]$Config.cpu_count -lt 1 -or [int]$Config.cpu_count -gt 64) {
        $errors.Add("cpu_count must be between 1 and 64 (got '$($Config.cpu_count)').")
    }
    $minMem = [int64]$Config.memory_minimum_bytes
    $startMem = [int64]$Config.memory_startup_bytes
    $maxMem = [int64]$Config.memory_maximum_bytes
    if ($minMem -lt 512MB -or $startMem -lt $minMem -or $maxMem -lt $startMem) {
        $errors.Add("Invalid memory bounds: min=$minMem, startup=$startMem, max=$maxMem.")
    }
    if ([int64]$Config.vhdx_size_bytes -lt 20GB) {
        $errors.Add("vhdx_size_bytes must be at least 20 GiB (got '$($Config.vhdx_size_bytes)').")
    }
    if ($Config.vhdx_format -notin @('Dynamic', 'Fixed')) {
        $errors.Add("vhdx_format must be Dynamic or Fixed (got '$($Config.vhdx_format)').")
    }
    if ($Config.checkpoint_type -notin @('Standard', 'Production', 'ProductionOnly', 'Disabled')) {
        $errors.Add("Unsupported checkpoint_type '$($Config.checkpoint_type)'.")
    }
    if ([string]::IsNullOrWhiteSpace($Config.owner_namespace)) {
        $errors.Add('owner_namespace is required.')
    }
    if ($errors.Count -gt 0) {
        throw ("VM configuration validation failed: " + ($errors -join ' '))
    }
    return [pscustomobject]@{
        valid  = $true
        config = $Config
    }
}

function Get-VmLabManifestPath {
    param(
        [Parameter(Mandatory)][string]$VmName,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    if ([string]::IsNullOrWhiteSpace($VmName) -or $VmName -match '[\\/:*?"<>|]') {
        throw "Invalid VM name '$VmName'."
    }
    return (Join-Path ([System.IO.Path]::GetFullPath($ManifestRoot)) "$VmName.json")
}

function Write-VmLabOwnershipManifest {
    param(
        [Parameter(Mandatory)][psobject]$Manifest,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $rootFull = [System.IO.Path]::GetFullPath($ManifestRoot)
    Assert-VmLabNoReparsePoint -FullPath $rootFull -Label 'Manifest root'
    if (-not (Test-Path -LiteralPath $rootFull)) {
        New-Item -ItemType Directory -Path $rootFull -Force -ErrorAction Stop | Out-Null
    }
    $targetPath = Get-VmLabManifestPath -VmName $Manifest.vm_name -ManifestRoot $rootFull
    $tmpPath = "$targetPath.$([guid]::NewGuid().ToString('N')).tmp"
    $json = $Manifest | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($tmpPath, $json, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::Move($tmpPath, $targetPath, $true)
    return $targetPath
}

function Get-VmLabOwnershipManifest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$VmName,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $path = Get-VmLabManifestPath -VmName $VmName -ManifestRoot $ManifestRoot
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return $null
    }
    return (Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json)
}

function Test-VmLabOwnership {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][psobject]$Vm,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $manifest = Get-VmLabOwnershipManifest -VmName $Vm.Name -ManifestRoot $ManifestRoot
    if (-not $manifest) {
        return [pscustomobject]@{
            owned    = $false
            reason   = "No ownership manifest found for '$($Vm.Name)'."
            manifest = $null
        }
    }
    if ([string]::IsNullOrWhiteSpace($manifest.vm_id) -or ([string]$Vm.Id) -ne ([string]$manifest.vm_id)) {
        return [pscustomobject]@{
            owned    = $false
            reason   = "VM ID mismatch for '$($Vm.Name)': live=$($Vm.Id), manifest=$($manifest.vm_id)."
            manifest = $manifest
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($Vm.ConfigurationLocation) -and -not [string]::IsNullOrWhiteSpace($manifest.vm_config_path)) {
        $liveCfg = [System.IO.Path]::GetFullPath($Vm.ConfigurationLocation).TrimEnd('\')
        $manCfg = [System.IO.Path]::GetFullPath($manifest.vm_config_path).TrimEnd('\')
        if (-not $liveCfg.StartsWith($manCfg, [System.StringComparison]::OrdinalIgnoreCase) -and
            -not $manCfg.StartsWith($liveCfg, [System.StringComparison]::OrdinalIgnoreCase)) {
            return [pscustomobject]@{
                owned    = $false
                reason   = "VM configuration path mismatch for '$($Vm.Name)'."
                manifest = $manifest
            }
        }
    }
    return [pscustomobject]@{
        owned    = $true
        reason   = 'Verified by ownership manifest and Hyper-V VM ID.'
        manifest = $manifest
    }
}

function Get-VmLabList {
    [CmdletBinding()]
    param(
        [switch]$OwnedOnly,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $vms = @(Get-VM -ErrorAction Stop)
    $results = foreach ($vm in $vms) {
        $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
        if ($OwnedOnly -and -not $own.owned) { continue }
        [pscustomobject]@{
            name            = $vm.Name
            id              = [string]$vm.Id
            state           = [string]$vm.State
            generation      = $vm.Generation
            cpu_count       = $vm.ProcessorCount
            memory_startup  = $vm.MemoryStartup
            owned           = $own.owned
            owner_namespace = if ($own.manifest) { $own.manifest.owner_namespace } else { $null }
            template_id     = if ($own.manifest) { $own.manifest.template_id } else { $null }
        }
    }
    return @($results)
}

function Get-VmLabStatus {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) {
        throw "VM '$Name' was not found in Hyper-V inventory."
    }
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    return [pscustomobject]@{
        name               = $vm.Name
        id                 = [string]$vm.Id
        state              = [string]$vm.State
        generation         = $vm.Generation
        cpu_count          = $vm.ProcessorCount
        memory_startup     = $vm.MemoryStartup
        memory_minimum     = $vm.MemoryMinimum
        memory_maximum     = $vm.MemoryMaximum
        checkpoint_type    = [string]$vm.CheckpointType
        configuration_path = $vm.ConfigurationLocation
        owned              = $own.owned
        ownership_reason   = $own.reason
        manifest           = $own.manifest
    }
}

function Test-VmLabPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][psobject]$Config,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $null = Test-VmLabConfig -Config $Config
    $vmRootFull = [System.IO.Path]::GetFullPath($Config.vm_root)
    Assert-VmLabNoReparsePoint -FullPath $vmRootFull -Label 'VM root'
    $vmPath = [System.IO.Path]::GetFullPath((Join-Path $vmRootFull 'vm'))
    $vhdxPath = [System.IO.Path]::GetFullPath((Join-Path $vmRootFull "vhdx\$($Config.vm_name).vhdx"))
    Assert-VmLabNoReparsePoint -FullPath $vmPath -Label 'VM config path'
    Assert-VmLabNoReparsePoint -FullPath $vhdxPath -Label 'VHDX path'

    if (-not [string]::IsNullOrWhiteSpace($Config.iso_path)) {
        if (-not (Test-Path -LiteralPath $Config.iso_path -PathType Leaf)) {
            throw "ISO file not found: $($Config.iso_path)"
        }
        $isoFull = [System.IO.Path]::GetFullPath($Config.iso_path)
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

    $vhdxDir = Split-Path -Parent $plan.vhdx_path
    foreach ($dir in @($plan.vm_root, $plan.vm_config_path, $vhdxDir)) {
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force -ErrorAction Stop | Out-Null
        }
    }

    $opId = [guid]::NewGuid().ToString('N')
    $newVm = New-VM `
        -Name $Config.vm_name `
        -Generation ([int]$Config.generation) `
        -MemoryStartupBytes ([int64]$Config.memory_startup_bytes) `
        -Path $plan.vm_config_path `
        -NewVHDPath $plan.vhdx_path `
        -NewVHDSizeBytes ([int64]$Config.vhdx_size_bytes) `
        -ErrorAction Stop

    Get-VMNetworkAdapter -VMName $Config.vm_name -ErrorAction Stop | Remove-VMNetworkAdapter -ErrorAction Stop
    if (-not [string]::IsNullOrWhiteSpace($Config.switch_name)) {
        Add-VMNetworkAdapter -VMName $Config.vm_name -SwitchName $Config.switch_name -ErrorAction Stop | Out-Null
    }

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

    if ($Config.secure_boot.enabled) {
        Set-VMFirmware -VMName $Config.vm_name -EnableSecureBoot On -SecureBootTemplate ([string]$Config.secure_boot.template) -ErrorAction Stop
    }
    if ($Config.vtpm_enabled) {
        Set-VMKeyProtector -VMName $Config.vm_name -NewLocalKeyProtector -ErrorAction Stop
        Enable-VMTPM -VMName $Config.vm_name -ErrorAction Stop
    }
    if (-not [string]::IsNullOrWhiteSpace($Config.iso_path)) {
        $isoFull = [System.IO.Path]::GetFullPath($Config.iso_path)
        $dvd = Add-VMDvdDrive -VMName $Config.vm_name -Path $isoFull -Passthru -ErrorAction Stop
        $vhd = Get-VMHardDiskDrive -VMName $Config.vm_name -ErrorAction Stop
        Set-VMFirmware -VMName $Config.vm_name -BootOrder $dvd, $vhd -ErrorAction Stop
    }

    $manifest = [pscustomobject]@{
        schema_version  = 1
        vm_name         = $Config.vm_name
        vm_id           = [string]$newVm.Id
        created_at      = [DateTimeOffset]::UtcNow.ToString('o')
        vm_config_path  = $plan.vm_config_path
        vhdx_path       = $plan.vhdx_path
        template_id     = [string]$Config.template_id
        owner_namespace = [string]$Config.owner_namespace
        operation_id    = $opId
    }
    $manifestPath = Write-VmLabOwnershipManifest -Manifest $manifest -ManifestRoot $ManifestRoot

    return [pscustomobject]@{
        status        = 'created'
        vm_name       = $Config.vm_name
        vm_id         = [string]$newVm.Id
        manifest_path = $manifestPath
        manifest      = $manifest
    }
}

function Assert-VmLabOwnedVm {
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) {
        throw "VM '$Name' was not found in Hyper-V inventory."
    }
    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    if (-not $own.owned) {
        throw "Refusing to modify unmanaged VM '$Name': $($own.reason)"
    }
    return [pscustomobject]@{
        vm       = $vm
        manifest = $own.manifest
    }
}

function Start-VmLabMachine {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [int64]$MinHostReserveBytes = 4GB,
        [Alias('a')][switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $owned = Assert-VmLabOwnedVm -Name $Name -ManifestRoot $ManifestRoot
    $vm = $owned.vm
    $memInfo = Get-VmLabHostMemoryInfo
    $requiredFree = [int64]$vm.MemoryStartup + $MinHostReserveBytes
    if ($memInfo.FreePhysicalBytes -lt $requiredFree) {
        throw ("Refusing to start VM '{0}': free host RAM ({1:N2} GiB) is below VM startup ({2:N2} GiB) + reserve ({3:N2} GiB)." -f `
            $Name, ($memInfo.FreePhysicalBytes / 1GB), ($vm.MemoryStartup / 1GB), ($MinHostReserveBytes / 1GB))
    }

    if (-not $Apply -or $WhatIfPreference) {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($Name, 'Start lab VM')
        }
        return [pscustomobject]@{
            status                 = 'planned'
            operation              = 'start'
            vm_name                = $Name
            vm_id                  = [string]$vm.Id
            free_ram_bytes         = $memInfo.FreePhysicalBytes
            required_free_bytes    = $requiredFree
            min_host_reserve_bytes = $MinHostReserveBytes
        }
    }
    if (-not (Test-VmLabAdministrator)) {
        throw 'Administrator elevation is required to start Hyper-V VMs.'
    }
    if (-not $PSCmdlet.ShouldProcess($Name, 'Start lab VM')) {
        return [pscustomobject]@{ status = 'declined'; operation = 'start'; vm_name = $Name }
    }

    # Revalidate immediately before VM startup
    $memNow = Get-VmLabHostMemoryInfo
    if ($memNow.FreePhysicalBytes -lt $requiredFree) {
        throw "Refusing to start VM '$Name': host free RAM dropped below safe reserve immediately before startup."
    }
    Start-VM -Name $Name -ErrorAction Stop
    return [pscustomobject]@{
        status    = 'started'
        operation = 'start'
        vm_name   = $Name
        vm_id     = [string]$vm.Id
    }
}

function Stop-VmLabMachine {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Alias('a')][switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $owned = Assert-VmLabOwnedVm -Name $Name -ManifestRoot $ManifestRoot
    $vm = $owned.vm
    if (-not $Apply -or $WhatIfPreference) {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($Name, 'Request graceful guest shutdown')
        }
        return [pscustomobject]@{
            status    = 'planned'
            operation = 'stop'
            vm_name   = $Name
            vm_id     = [string]$vm.Id
            graceful  = $true
        }
    }
    if (-not (Test-VmLabAdministrator)) {
        throw 'Administrator elevation is required to stop Hyper-V VMs.'
    }
    if (-not $PSCmdlet.ShouldProcess($Name, 'Request graceful guest shutdown')) {
        return [pscustomobject]@{ status = 'declined'; operation = 'stop'; vm_name = $Name }
    }

    # Request graceful guest shutdown only (no -Force, no -TurnOff)
    Stop-VM -Name $Name -ErrorAction Stop
    return [pscustomobject]@{
        status    = 'stopped'
        operation = 'stop'
        vm_name   = $Name
        vm_id     = [string]$vm.Id
        graceful  = $true
    }
}

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
    Checkpoint-VM -Name $Name -SnapshotName $CheckpointName -ErrorAction Stop
    return [pscustomobject]@{
        status          = 'checkpoint_created'
        operation       = 'checkpoint'
        vm_name         = $Name
        vm_id           = [string]$vm.Id
        checkpoint_name = $CheckpointName
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
            vm_name      = $Name
            name         = $_.Name
            id           = [string]$_.Id
            created_at   = $_.CreationTime
            snapshot_type = [string]$_.SnapshotType
        }
    })
}

function Invoke-VmLab {
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
        [switch]$OwnedOnly,
        [int64]$MinReserveBytes = 4GB,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )

    $result = switch ($Operation) {
        'list' {
            Get-VmLabList -OwnedOnly:$OwnedOnly -ManifestRoot $ManifestRoot
        }
        'status' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for status.' }
            Get-VmLabStatus -Name $Name -ManifestRoot $ManifestRoot
        }
        'plan' {
            $cfg = Get-VmLabTemplate -TemplateName $TemplateName -ConfigPath $ConfigPath
            if (-not [string]::IsNullOrWhiteSpace($Name)) { $cfg.vm_name = $Name }
            if (-not [string]::IsNullOrWhiteSpace($IsoPath)) { $cfg.iso_path = $IsoPath }
            if (-not [string]::IsNullOrWhiteSpace($VmRoot)) { $cfg.vm_root = $VmRoot }
            if ($PSBoundParameters.ContainsKey('SwitchName')) { $cfg.switch_name = $SwitchName }
            Test-VmLabPlan -Config $cfg -ManifestRoot $ManifestRoot
        }
        'create' {
            $cfg = Get-VmLabTemplate -TemplateName $TemplateName -ConfigPath $ConfigPath
            if (-not [string]::IsNullOrWhiteSpace($Name)) { $cfg.vm_name = $Name }
            if (-not [string]::IsNullOrWhiteSpace($IsoPath)) { $cfg.iso_path = $IsoPath }
            if (-not [string]::IsNullOrWhiteSpace($VmRoot)) { $cfg.vm_root = $VmRoot }
            if ($PSBoundParameters.ContainsKey('SwitchName')) { $cfg.switch_name = $SwitchName }
            New-VmLabMachine -Config $cfg -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'start' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for start.' }
            Start-VmLabMachine -Name $Name -MinHostReserveBytes $MinReserveBytes -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'stop' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for stop.' }
            Stop-VmLabMachine -Name $Name -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'checkpoint' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for checkpoint.' }
            if ([string]::IsNullOrWhiteSpace($CheckpointName)) { throw '-CheckpointName (-m) is required for checkpoint.' }
            New-VmLabCheckpoint -Name $Name -CheckpointName $CheckpointName -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
        }
        'checkpoints' {
            if ([string]::IsNullOrWhiteSpace($Name)) { throw '-Name (-n) is required for checkpoints.' }
            Get-VmLabCheckpoint -Name $Name -ManifestRoot $ManifestRoot
        }
    }

    if ($Json) {
        return ($result | ConvertTo-Json -Depth 8)
    }
    return $result
}

Set-Alias -Name 'vm-lab' -Value 'Invoke-VmLab'
Export-ModuleMember -Function @(
    'Get-VmLabTemplate',
    'Test-VmLabConfig',
    'Get-VmLabOwnershipManifest',
    'Test-VmLabOwnership',
    'Get-VmLabList',
    'Get-VmLabStatus',
    'Test-VmLabPlan',
    'New-VmLabMachine',
    'Start-VmLabMachine',
    'Stop-VmLabMachine',
    'New-VmLabCheckpoint',
    'Get-VmLabCheckpoint',
    'Invoke-VmLab'
) -Alias @('vm-lab')
