#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

function Get-VmLabDefaultManifestRoot {
    if (-not [string]::IsNullOrWhiteSpace($env:VM_LAB_MANIFEST_ROOT)) {
        return $env:VM_LAB_MANIFEST_ROOT
    }
    $localApp = if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { $env:LOCALAPPDATA } else { [System.IO.Path]::GetTempPath() }
    return (Join-Path $localApp 'vm_lab\manifests')
}

function Resolve-VmLabFullPath {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label,
        [switch]$RejectDriveRoot
    )
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$Label path cannot be empty."
    }
    if ($Path.StartsWith('\\')) {
        throw "$Label path must be a local path, not a UNC path: '$Path'."
    }
    if (-not [System.IO.Path]::IsPathFullyQualified($Path)) {
        throw "$Label path must be fully qualified: '$Path'."
    }
    if ($Path -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "$Label path must not contain parent-directory traversal ('..'): '$Path'."
    }
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    if ([string]::IsNullOrWhiteSpace($root) -or $root.StartsWith('\\')) {
        throw "$Label path does not have a valid local drive root: '$full'."
    }
    $trimmed = $full.TrimEnd('\', '/')
    $rootTrimmed = $root.TrimEnd('\', '/')
    if ($RejectDriveRoot -and $trimmed.Equals($rootTrimmed, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label path cannot be a bare drive root: '$full'."
    }
    return $trimmed
}

function Test-VmLabPathIsDescendantOrEqual {
    param(
        [Parameter(Mandatory)][string]$BasePath,
        [Parameter(Mandatory)][string]$CandidatePath
    )
    $baseFull = Resolve-VmLabFullPath -Path $BasePath -Label 'Base' -RejectDriveRoot
    $candFull = Resolve-VmLabFullPath -Path $CandidatePath -Label 'Candidate' -RejectDriveRoot
    $baseRoot = [System.IO.Path]::GetPathRoot($baseFull)
    $candRoot = [System.IO.Path]::GetPathRoot($candFull)
    if (-not $baseRoot.Equals($candRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    if ($candFull.Equals($baseFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $prefix = $baseFull + [System.IO.Path]::DirectorySeparatorChar
    return $candFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
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
    $resolved = Resolve-VmLabFullPath -Path $FullPath -Label $Label
    $root = ([System.IO.Path]::GetPathRoot($resolved)).TrimEnd('\', '/')
    $current = $resolved
    while (-not [string]::IsNullOrWhiteSpace($current) -and -not $current.Equals($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label path traverses a reparse point/symlink at '$current'."
            }
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) { break }
        $current = $parent.TrimEnd('\', '/')
    }
}

function Test-VmLabStrictInt {
    param($Value)
    return ($null -ne $Value) -and ($Value -is [int] -or $Value -is [int64])
}

function Test-VmLabStrictBool {
    param($Value)
    return ($null -ne $Value) -and ($Value -is [bool])
}

function Test-VmLabStrictString {
    param($Value)
    return ($null -ne $Value) -and ($Value -is [string])
}

function Test-VmLabValidVmName {
    param($VmName)
    if (-not (Test-VmLabStrictString $VmName)) { return $false }
    if ([string]::IsNullOrWhiteSpace($VmName)) { return $false }
    if ($VmName -ne $VmName.Trim()) { return $false }
    if ($VmName -eq '.' -or $VmName -eq '..') { return $false }
    if ($VmName.Length -gt 80) { return $false }
    if ($VmName -match '[\\/:*?"<>|]') { return $false }
    return $true
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
    Assert-VmLabNoReparsePoint -FullPath ([System.IO.Path]::GetFullPath($path)) -Label 'Template/config'
    return (Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json)
}

function Test-VmLabConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][psobject]$Config
    )
    $errors = [System.Collections.Generic.List[string]]::new()
    $propNames = @($Config.PSObject.Properties.Name)

    if ('schema_version' -notin $propNames -or -not (Test-VmLabStrictInt $Config.schema_version) -or $Config.schema_version -ne 1) {
        $errors.Add("Unsupported or invalid schema_version '$($Config.schema_version)' (expected integer 1).")
    }
    if (-not (Test-VmLabValidVmName $Config.vm_name)) {
        $errors.Add("Invalid vm_name '$($Config.vm_name)'.")
    }
    if ('vm_root' -notin $propNames -or -not (Test-VmLabStrictString $Config.vm_root) -or [string]::IsNullOrWhiteSpace($Config.vm_root)) {
        $errors.Add('vm_root must be a non-empty fully qualified local path.')
    } else {
        try {
            $null = Resolve-VmLabFullPath -Path $Config.vm_root -Label 'vm_root' -RejectDriveRoot
        } catch {
            $errors.Add($_.Exception.Message)
        }
    }
    if ('generation' -notin $propNames -or -not (Test-VmLabStrictInt $Config.generation) -or $Config.generation -ne 2) {
        $errors.Add("Only Generation 2 VMs (integer 2) are supported by vm_lab (got '$($Config.generation)').")
    }
    if ('cpu_count' -notin $propNames -or -not (Test-VmLabStrictInt $Config.cpu_count) -or $Config.cpu_count -lt 1 -or $Config.cpu_count -gt 64) {
        $errors.Add("cpu_count must be an integer between 1 and 64 (got '$($Config.cpu_count)').")
    }

    $hasMin = ('memory_minimum_bytes' -in $propNames) -and (Test-VmLabStrictInt $Config.memory_minimum_bytes)
    $hasStart = ('memory_startup_bytes' -in $propNames) -and (Test-VmLabStrictInt $Config.memory_startup_bytes)
    $hasMax = ('memory_maximum_bytes' -in $propNames) -and (Test-VmLabStrictInt $Config.memory_maximum_bytes)
    if (-not ($hasMin -and $hasStart -and $hasMax)) {
        $errors.Add('memory_minimum_bytes, memory_startup_bytes, and memory_maximum_bytes must be integers.')
    } else {
        $minMem = [int64]$Config.memory_minimum_bytes
        $startMem = [int64]$Config.memory_startup_bytes
        $maxMem = [int64]$Config.memory_maximum_bytes
        if ($minMem -lt 512MB -or $startMem -lt $minMem -or $maxMem -lt $startMem) {
            $errors.Add("Invalid memory bounds: min=$minMem, startup=$startMem, max=$maxMem.")
        }
    }

    if ('vhdx_size_bytes' -notin $propNames -or -not (Test-VmLabStrictInt $Config.vhdx_size_bytes) -or $Config.vhdx_size_bytes -lt 20GB) {
        $errors.Add("vhdx_size_bytes must be an integer of at least 20 GiB (got '$($Config.vhdx_size_bytes)').")
    }
    if ('vhdx_format' -notin $propNames -or -not (Test-VmLabStrictString $Config.vhdx_format) -or $Config.vhdx_format -notin @('Dynamic', 'Fixed')) {
        $errors.Add("vhdx_format must be 'Dynamic' or 'Fixed' (got '$($Config.vhdx_format)').")
    }
    if ('checkpoint_type' -notin $propNames -or -not (Test-VmLabStrictString $Config.checkpoint_type) -or $Config.checkpoint_type -notin @('Standard', 'Production', 'ProductionOnly', 'Disabled')) {
        $errors.Add("Unsupported checkpoint_type '$($Config.checkpoint_type)'.")
    }
    if ('automatic_checkpoints_enabled' -notin $propNames -or -not (Test-VmLabStrictBool $Config.automatic_checkpoints_enabled)) {
        $errors.Add('automatic_checkpoints_enabled must be a boolean.')
    }
    if ('automatic_start_action' -notin $propNames -or -not (Test-VmLabStrictString $Config.automatic_start_action) -or $Config.automatic_start_action -notin @('Nothing', 'StartIfRunning', 'Start')) {
        $errors.Add("Unsupported automatic_start_action '$($Config.automatic_start_action)'.")
    }
    if ('owner_namespace' -notin $propNames -or -not (Test-VmLabStrictString $Config.owner_namespace) -or [string]::IsNullOrWhiteSpace($Config.owner_namespace)) {
        $errors.Add('owner_namespace must be a non-empty string.')
    }
    if ('vtpm_enabled' -notin $propNames -or -not (Test-VmLabStrictBool $Config.vtpm_enabled)) {
        $errors.Add('vtpm_enabled must be a boolean.')
    }

    if ('secure_boot' -notin $propNames -or $null -eq $Config.secure_boot -or ($Config.secure_boot -isnot [psobject])) {
        $errors.Add('secure_boot object is required.')
    } else {
        $sbProps = @($Config.secure_boot.PSObject.Properties.Name)
        $allowedSbProps = @('enabled', 'template')
        foreach ($p in $sbProps) {
            if ($p -notin $allowedSbProps) {
                $errors.Add("Unrecognized secure_boot property '$p'.")
            }
        }
        if ('enabled' -notin $sbProps -or -not (Test-VmLabStrictBool $Config.secure_boot.enabled)) {
            $errors.Add('secure_boot.enabled must be a boolean.')
        }
        if ('template' -notin $sbProps -or -not (Test-VmLabStrictString $Config.secure_boot.template)) {
            $errors.Add('secure_boot.template must be a string.')
        } elseif ($Config.secure_boot.enabled -eq $true -and $Config.secure_boot.template -notin @('MicrosoftWindows', 'MicrosoftUEFICertificateAuthority', 'OpenSourceShieldedVM')) {
            $errors.Add("Unsupported secure_boot.template '$($Config.secure_boot.template)'.")
        }
    }

    if ('iso_path' -in $propNames) {
        if (-not (Test-VmLabStrictString $Config.iso_path)) {
            $errors.Add('iso_path must be a string.')
        } elseif (-not [string]::IsNullOrWhiteSpace($Config.iso_path)) {
            try {
                $null = Resolve-VmLabFullPath -Path $Config.iso_path -Label 'iso_path' -RejectDriveRoot
            } catch {
                $errors.Add($_.Exception.Message)
            }
        }
    }
    if ('switch_name' -in $propNames) {
        if (-not (Test-VmLabStrictString $Config.switch_name)) {
            $errors.Add('switch_name must be a string.')
        } elseif ($Config.switch_name.Length -gt 0 -and [string]::IsNullOrWhiteSpace($Config.switch_name)) {
            $errors.Add('switch_name cannot be whitespace-only.')
        }
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
    if (-not (Test-VmLabValidVmName $VmName)) {
        throw "Invalid VM name '$VmName'."
    }
    $rootFull = Resolve-VmLabFullPath -Path $ManifestRoot -Label 'Manifest root' -RejectDriveRoot
    return (Join-Path $rootFull "$VmName.json")
}

function Test-VmLabManifestRecord {
    param([Parameter(Mandatory)][psobject]$Manifest)
    $props = @($Manifest.PSObject.Properties.Name)
    if ('schema_version' -notin $props -or -not (Test-VmLabStrictInt $Manifest.schema_version) -or $Manifest.schema_version -ne 1) {
        throw "Unsupported or invalid manifest schema_version '$($Manifest.schema_version)'."
    }
    if (-not (Test-VmLabValidVmName $Manifest.vm_name)) {
        throw "Manifest has invalid vm_name '$($Manifest.vm_name)'."
    }
    $parsedGuid = [guid]::Empty
    if (-not (Test-VmLabStrictString $Manifest.vm_id) -or -not [guid]::TryParse($Manifest.vm_id, [ref]$parsedGuid) -or $parsedGuid -eq [guid]::Empty) {
        throw "Manifest has invalid vm_id '$($Manifest.vm_id)'."
    }
    $parsedTime = [DateTimeOffset]::MinValue
    $createdValid = ($Manifest.created_at -is [datetime]) -or
        ($Manifest.created_at -is [DateTimeOffset]) -or
        ((Test-VmLabStrictString $Manifest.created_at) -and [DateTimeOffset]::TryParse($Manifest.created_at, [ref]$parsedTime))
    if (-not $createdValid) {
        throw "Manifest has invalid created_at '$($Manifest.created_at)'."
    }
    if (-not (Test-VmLabStrictString $Manifest.vm_config_path)) {
        throw 'Manifest vm_config_path must be a string.'
    }
    $null = Resolve-VmLabFullPath -Path $Manifest.vm_config_path -Label 'Manifest vm_config_path' -RejectDriveRoot
    if (-not (Test-VmLabStrictString $Manifest.vhdx_path)) {
        throw 'Manifest vhdx_path must be a string.'
    }
    $null = Resolve-VmLabFullPath -Path $Manifest.vhdx_path -Label 'Manifest vhdx_path' -RejectDriveRoot
    if (-not (Test-VmLabStrictString $Manifest.owner_namespace) -or [string]::IsNullOrWhiteSpace($Manifest.owner_namespace)) {
        throw 'Manifest owner_namespace is required.'
    }
    if (-not (Test-VmLabStrictString $Manifest.operation_id) -or [string]::IsNullOrWhiteSpace($Manifest.operation_id)) {
        throw 'Manifest operation_id is required.'
    }
}

function Write-VmLabOwnershipManifest {
    param(
        [Parameter(Mandatory)][psobject]$Manifest,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    Test-VmLabManifestRecord -Manifest $Manifest
    $rootFull = Resolve-VmLabFullPath -Path $ManifestRoot -Label 'Manifest root' -RejectDriveRoot
    Assert-VmLabNoReparsePoint -FullPath $rootFull -Label 'Manifest root'
    if (-not (Test-Path -LiteralPath $rootFull)) {
        New-Item -ItemType Directory -Path $rootFull -Force -ErrorAction Stop | Out-Null
    }
    $targetPath = Get-VmLabManifestPath -VmName $Manifest.vm_name -ManifestRoot $rootFull
    Assert-VmLabNoReparsePoint -FullPath $targetPath -Label 'Manifest file'
    if (Test-Path -LiteralPath $targetPath) {
        throw "Ownership manifest already exists at '$targetPath'. Refusing to overwrite existing ownership record."
    }

    $tmpPath = "$targetPath.$([guid]::NewGuid().ToString('N')).tmp"
    $json = $Manifest | ConvertTo-Json -Depth 6
    try {
        $fs = [System.IO.File]::Open($tmpPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try {
            $writer = [System.IO.StreamWriter]::new($fs, [System.Text.UTF8Encoding]::new($false))
            try {
                $writer.Write($json)
                $writer.Flush()
            } finally {
                $writer.Dispose()
            }
        } finally {
            $fs.Dispose()
        }
        [System.IO.File]::Move($tmpPath, $targetPath, $false)
    } finally {
        if (Test-Path -LiteralPath $tmpPath) {
            Remove-Item -LiteralPath $tmpPath -Force -ErrorAction SilentlyContinue
        }
    }
    return $targetPath
}

function Read-VmLabOwnershipManifestRecord {
    param(
        [Parameter(Mandatory)][string]$VmName,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $path = $null
    try {
        $rootFull = Resolve-VmLabFullPath -Path $ManifestRoot -Label 'Manifest root' -RejectDriveRoot
        Assert-VmLabNoReparsePoint -FullPath $rootFull -Label 'Manifest root'
        $path = Get-VmLabManifestPath -VmName $VmName -ManifestRoot $rootFull
        Assert-VmLabNoReparsePoint -FullPath $path -Label 'Manifest file'
    } catch {
        return [pscustomobject]@{
            state    = 'untrusted'
            manifest = $null
            reason   = $_.Exception.Message
            path     = $path
        }
    }

    if (-not (Test-Path -LiteralPath $path)) {
        return [pscustomobject]@{
            state    = 'missing'
            manifest = $null
            reason   = "No ownership manifest found for '$VmName'."
            path     = $path
        }
    }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return [pscustomobject]@{
            state    = 'untrusted'
            manifest = $null
            reason   = "Ownership manifest path is not a regular file: '$path'."
            path     = $path
        }
    }

    $parsed = $null
    try {
        $raw = Get-Content -LiteralPath $path -Raw -Encoding utf8 -ErrorAction Stop
        if ([string]::IsNullOrWhiteSpace($raw)) {
            throw 'Ownership manifest file is empty.'
        }
        $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $parsed -or ($parsed -isnot [psobject])) {
            throw 'Ownership manifest JSON did not decode to an object.'
        }
    } catch {
        return [pscustomobject]@{
            state    = 'corrupt'
            manifest = $null
            reason   = "Ownership manifest for '$VmName' is corrupt or unreadable: $($_.Exception.Message)"
            path     = $path
        }
    }

    try {
        Test-VmLabManifestRecord -Manifest $parsed
    } catch {
        return [pscustomobject]@{
            state    = 'untrusted'
            manifest = $null
            reason   = "Ownership manifest for '$VmName' failed trust/schema validation: $($_.Exception.Message)"
            path     = $path
        }
    }

    return [pscustomobject]@{
        state    = 'ok'
        manifest = $parsed
        reason   = 'Manifest loaded and validated.'
        path     = $path
    }
}

function Get-VmLabOwnershipManifest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$VmName,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $rec = Read-VmLabOwnershipManifestRecord -VmName $VmName -ManifestRoot $ManifestRoot
    switch ($rec.state) {
        'missing' { return $null }
        'ok'      { return $rec.manifest }
        default   { throw $rec.reason }
    }
}

function Test-VmLabOwnership {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][psobject]$Vm,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    if ($null -eq $Vm -or -not (Test-VmLabValidVmName $Vm.Name)) {
        return [pscustomobject]@{
            owned           = $false
            ownership_state = 'untrusted'
            reason          = 'Live VM object is missing a valid Name.'
            manifest        = $null
        }
    }
    $liveId = [guid]::Empty
    if ($null -eq $Vm.Id -or -not [guid]::TryParse([string]$Vm.Id, [ref]$liveId) -or $liveId -eq [guid]::Empty) {
        return [pscustomobject]@{
            owned           = $false
            ownership_state = 'untrusted'
            reason          = "Live VM '$($Vm.Name)' is missing a valid VM ID."
            manifest        = $null
        }
    }
    if ([string]::IsNullOrWhiteSpace($Vm.ConfigurationLocation)) {
        return [pscustomobject]@{
            owned           = $false
            ownership_state = 'untrusted'
            reason          = "Live VM '$($Vm.Name)' is missing ConfigurationLocation evidence."
            manifest        = $null
        }
    }
    try {
        $liveCfgFull = Resolve-VmLabFullPath -Path $Vm.ConfigurationLocation -Label 'Live VM ConfigurationLocation' -RejectDriveRoot
        Assert-VmLabNoReparsePoint -FullPath $liveCfgFull -Label 'Live VM ConfigurationLocation'
    } catch {
        return [pscustomobject]@{
            owned           = $false
            ownership_state = 'untrusted'
            reason          = "Live VM '$($Vm.Name)' has unsafe ConfigurationLocation: $($_.Exception.Message)"
            manifest        = $null
        }
    }

    $rec = Read-VmLabOwnershipManifestRecord -VmName $Vm.Name -ManifestRoot $ManifestRoot
    if ($rec.state -ne 'ok') {
        return [pscustomobject]@{
            owned           = $false
            ownership_state = $rec.state
            reason          = $rec.reason
            manifest        = $null
        }
    }
    $manifest = $rec.manifest

    if (-not $manifest.vm_name.Equals($Vm.Name, [System.StringComparison]::OrdinalIgnoreCase)) {
        return [pscustomobject]@{
            owned           = $false
            ownership_state = 'mismatched'
            reason          = "VM name mismatch for '$($Vm.Name)': manifest=$($manifest.vm_name)."
            manifest        = $manifest
        }
    }

    $manId = [guid]$manifest.vm_id
    if ($liveId -ne $manId) {
        return [pscustomobject]@{
            owned           = $false
            ownership_state = 'mismatched'
            reason          = "VM ID mismatch for '$($Vm.Name)': live=$liveId, manifest=$manId."
            manifest        = $manifest
        }
    }

    try {
        $manCfgFull = Resolve-VmLabFullPath -Path $manifest.vm_config_path -Label 'Manifest vm_config_path' -RejectDriveRoot
        Assert-VmLabNoReparsePoint -FullPath $manCfgFull -Label 'Manifest vm_config_path'
    } catch {
        return [pscustomobject]@{
            owned           = $false
            ownership_state = 'untrusted'
            reason          = "Manifest configuration path for '$($Vm.Name)' is unsafe: $($_.Exception.Message)"
            manifest        = $manifest
        }
    }

    if (-not (Test-VmLabPathIsDescendantOrEqual -BasePath $manCfgFull -CandidatePath $liveCfgFull)) {
        return [pscustomobject]@{
            owned           = $false
            ownership_state = 'mismatched'
            reason          = "VM configuration path mismatch for '$($Vm.Name)': live='$liveCfgFull', manifest='$manCfgFull'."
            manifest        = $manifest
        }
    }

    return [pscustomobject]@{
        owned           = $true
        ownership_state = 'owned'
        reason          = 'Verified by ownership manifest, Hyper-V VM ID, and configuration path.'
        manifest        = $manifest
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
            ownership_state = $own.ownership_state
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
        ownership_state    = $own.ownership_state
        ownership_reason   = $own.reason
        manifest           = $own.manifest
    }
}

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
            try {
                $existingCfg = Resolve-VmLabFullPath -Path $existing.ConfigurationLocation -Label 'Existing VM ConfigurationLocation' -RejectDriveRoot
                if ((Test-VmLabPathIsDescendantOrEqual -BasePath $vmRootFull -CandidatePath $existingCfg) -or
                    (Test-VmLabPathIsDescendantOrEqual -BasePath $existingCfg -CandidatePath $vmRootFull)) {
                    throw "Target VM root '$vmRootFull' conflicts with existing VM '$($existing.Name)' configuration location '$existingCfg'."
                }
            } catch [System.Management.Automation.RuntimeException] {
                if ($_.Exception.Message -like 'Target VM root * conflicts with existing VM *') {
                    throw
                }
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

function Assert-VmLabReverifiedTarget {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][guid]$ExpectedId,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $vmNow = Get-VM -ErrorAction Stop | Where-Object { $_.Id -eq $ExpectedId } | Select-Object -First 1
    if (-not $vmNow) {
        throw "VM '$Name' with verified ID '$ExpectedId' is no longer present in Hyper-V inventory."
    }
    if (-not $vmNow.Name.Equals($Name, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "VM identity changed before mutation: ID '$ExpectedId' now belongs to '$($vmNow.Name)' instead of '$Name'."
    }
    $own = Test-VmLabOwnership -Vm $vmNow -ManifestRoot $ManifestRoot
    if (-not $own.owned) {
        throw "Ownership re-verification failed immediately before mutation for '$Name': $($own.reason)"
    }
    return $vmNow
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
    $stateStr = [string]$vm.State
    if ($stateStr -eq 'Running') {
        return [pscustomobject]@{
            status    = 'already_running'
            operation = 'start'
            vm_name   = $Name
            vm_id     = [string]$vm.Id
            state     = $stateStr
        }
    }
    $transitionalStates = @('Starting', 'Stopping', 'Saving', 'Pausing', 'Resuming', 'Reset')
    if ($stateStr -in $transitionalStates) {
        throw "Refusing to start VM '$Name': VM is in transitional state '$stateStr'."
    }

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
            state                  = $stateStr
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

    $vmNow = Assert-VmLabReverifiedTarget -Name $Name -ExpectedId ([guid]$vm.Id) -ManifestRoot $ManifestRoot
    $stateNow = [string]$vmNow.State
    if ($stateNow -eq 'Running') {
        return [pscustomobject]@{
            status    = 'already_running'
            operation = 'start'
            vm_name   = $Name
            vm_id     = [string]$vmNow.Id
            state     = $stateNow
        }
    }
    if ($stateNow -in $transitionalStates) {
        throw "Refusing to start VM '$Name': VM entered transitional state '$stateNow'."
    }

    # Revalidate host RAM immediately before VM startup
    $memNow = Get-VmLabHostMemoryInfo
    $requiredNow = [int64]$vmNow.MemoryStartup + $MinHostReserveBytes
    if ($memNow.FreePhysicalBytes -lt $requiredNow) {
        throw "Refusing to start VM '$Name': host free RAM dropped below safe reserve immediately before startup."
    }

    if ($vmNow.GetType().FullName -eq 'Microsoft.HyperV.PowerShell.VirtualMachine') {
        Start-VM -VM $vmNow -ErrorAction Stop
    } else {
        Start-VM -Name $vmNow.Name -ErrorAction Stop
    }
    $afterVm = Get-VM -ErrorAction Stop | Where-Object { $_.Id -eq $vmNow.Id } | Select-Object -First 1
    $afterState = if ($afterVm) { [string]$afterVm.State } else { 'Unknown' }
    return [pscustomobject]@{
        status    = if ($afterState -eq 'Running') { 'started' } else { 'start_requested' }
        operation = 'start'
        vm_name   = $Name
        vm_id     = [string]$vmNow.Id
        state     = $afterState
    }
}

function Stop-VmLabMachine {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [int]$ShutdownTimeoutSeconds = 30,
        [Alias('a')][switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $owned = Assert-VmLabOwnedVm -Name $Name -ManifestRoot $ManifestRoot
    $vm = $owned.vm
    $stateStr = [string]$vm.State
    if ($stateStr -eq 'Off') {
        return [pscustomobject]@{
            status    = 'already_stopped'
            operation = 'stop'
            vm_name   = $Name
            vm_id     = [string]$vm.Id
            state     = $stateStr
            graceful  = $true
        }
    }
    $transitionalStates = @('Starting', 'Stopping', 'Saving', 'Pausing', 'Resuming', 'Reset')
    if ($stateStr -in $transitionalStates) {
        throw "Refusing to stop VM '$Name': VM is in transitional state '$stateStr'."
    }

    if (-not $Apply -or $WhatIfPreference) {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($Name, 'Request graceful guest shutdown')
        }
        return [pscustomobject]@{
            status    = 'planned'
            operation = 'stop'
            vm_name   = $Name
            vm_id     = [string]$vm.Id
            state     = $stateStr
            graceful  = $true
        }
    }
    if (-not (Test-VmLabAdministrator)) {
        throw 'Administrator elevation is required to stop Hyper-V VMs.'
    }
    if (-not $PSCmdlet.ShouldProcess($Name, 'Request graceful guest shutdown')) {
        return [pscustomobject]@{ status = 'declined'; operation = 'stop'; vm_name = $Name }
    }

    $vmNow = Assert-VmLabReverifiedTarget -Name $Name -ExpectedId ([guid]$vm.Id) -ManifestRoot $ManifestRoot
    if ([string]$vmNow.State -eq 'Off') {
        return [pscustomobject]@{
            status    = 'already_stopped'
            operation = 'stop'
            vm_name   = $Name
            vm_id     = [string]$vmNow.Id
            state     = 'Off'
            graceful  = $true
        }
    }

    # Request graceful guest shutdown only (no -Force, no -TurnOff)
    try {
        if ($vmNow.GetType().FullName -eq 'Microsoft.HyperV.PowerShell.VirtualMachine') {
            Stop-VM -VM $vmNow -ErrorAction Stop
        } else {
            Stop-VM -Name $vmNow.Name -ErrorAction Stop
        }
    } catch {
        throw "Graceful guest shutdown failed for VM '$Name' (hard power-off is disabled by policy): $($_.Exception.Message)"
    }

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds([Math]::Max(0, $ShutdownTimeoutSeconds))
    $afterVm = Get-VM -ErrorAction Stop | Where-Object { $_.Id -eq $vmNow.Id } | Select-Object -First 1
    while ($afterVm -and [string]$afterVm.State -ne 'Off' -and [DateTimeOffset]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 250
        $afterVm = Get-VM -ErrorAction Stop | Where-Object { $_.Id -eq $vmNow.Id } | Select-Object -First 1
    }
    $afterState = if ($afterVm) { [string]$afterVm.State } else { 'Unknown' }
    $reachedOff = ($afterState -eq 'Off')

    return [pscustomobject]@{
        status    = if ($reachedOff) { 'stopped' } else { 'shutdown_requested' }
        operation = 'stop'
        vm_name   = $Name
        vm_id     = [string]$vmNow.Id
        state     = $afterState
        timed_out = (-not $reachedOff)
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
            Start-VmLabMachine -Name $Name -MinHostReserveBytes $MinHostReserveBytes -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
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
