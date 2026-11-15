#Requires -Version 7.0

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

function Get-VmLabModuleRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-VmLabTemplate {
    [CmdletBinding()]
    param(
        [string]$TemplateName = 'windows11-h4',
        [string]$ConfigPath
    )
    $modRoot = Get-VmLabModuleRoot
    $path = if (-not [string]::IsNullOrWhiteSpace($ConfigPath)) {
        $ConfigPath
    } else {
        Join-Path $modRoot "templates\$TemplateName.json"
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
