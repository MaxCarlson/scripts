#Requires -Version 7.0

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
