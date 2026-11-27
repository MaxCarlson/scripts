#Requires -Version 7.0

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

function Test-VmLabInteractiveDesktop {
    if ($env:VM_LAB_NONINTERACTIVE -eq '1') {
        return $false
    }
    return [Environment]::UserInteractive
}

function Resolve-VmLabVmConnectPath {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:SystemRoot)) {
        $candidates += (Join-Path $env:SystemRoot 'System32\vmconnect.exe')
    }
    $cmd = Get-Command -Name 'vmconnect.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) {
        $candidates += $cmd.Source
    }
    foreach ($cand in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($cand) -and (Test-Path -LiteralPath $cand -PathType Leaf)) {
            return $cand
        }
    }
    throw 'vmconnect.exe was not found. Ensure Hyper-V Management Tools are installed on this Windows host.'
}

function Start-VmLabProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList
    )
    return (Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -PassThru -ErrorAction Stop)
}

function Get-VmLabHostResources {
    [CmdletBinding()]
    param(
        [int64]$MinReserveBytes = 4GB,
        [string]$TargetPath
    )

    $diagnostics = [System.Collections.Generic.List[string]]::new()

    $hostname = $env:COMPUTERNAME
    if ([string]::IsNullOrWhiteSpace($hostname)) {
        try {
            $hostname = [System.Net.Dns]::GetHostName()
        } catch {
            $hostname = $null
            $diagnostics.Add("Hostname collection failed: $($_.Exception.Message)")
        }
    }

    $logicalCpuCount = $null
    try {
        $cpu = [Environment]::ProcessorCount
        if ($cpu -gt 0) {
            $logicalCpuCount = [int]$cpu
        } else {
            $diagnostics.Add('Logical CPU count was not positive.')
        }
    } catch {
        $diagnostics.Add("Logical CPU count collection failed: $($_.Exception.Message)")
    }

    $totalBytes = $null
    $availableBytes = $null
    $usedBytes = $null
    $memoryCollected = $false
    try {
        $memInfo = Get-VmLabHostMemoryInfo
        if ($null -eq $memInfo -or $null -eq $memInfo.TotalPhysicalBytes -or $null -eq $memInfo.FreePhysicalBytes -or [int64]$memInfo.TotalPhysicalBytes -le 0) {
            $diagnostics.Add('Host memory counters returned missing or non-positive values.')
        } else {
            $totalBytes = [int64]$memInfo.TotalPhysicalBytes
            $availableBytes = [int64]$memInfo.FreePhysicalBytes
            if ($availableBytes -lt 0) {
                $diagnostics.Add("Available physical memory counter was negative ($availableBytes).")
                $availableBytes = $null
            } else {
                $usedBytes = [int64][Math]::Max(0L, ($totalBytes - $availableBytes))
                $memoryCollected = $true
            }
        }
    } catch {
        $diagnostics.Add("Host memory collection failed: $($_.Exception.Message)")
    }

    $effectiveStoragePath = if (-not [string]::IsNullOrWhiteSpace($TargetPath)) {
        $TargetPath
    } elseif (-not [string]::IsNullOrWhiteSpace($env:SystemDrive)) {
        "$($env:SystemDrive)\"
    } else {
        'C:\'
    }

    $storageRoot = $null
    $storageAvailableBytes = $null
    try {
        $storageRoot = [System.IO.Path]::GetPathRoot($effectiveStoragePath)
        $storageAvailableBytes = [int64](Get-VmLabDriveFreeBytes -TargetPath $effectiveStoragePath)
    } catch {
        $diagnostics.Add("Storage free-space collection failed for '$effectiveStoragePath': $($_.Exception.Message)")
    }

    $reserveSatisfied = $null
    if ($memoryCollected) {
        $reserveSatisfied = ($availableBytes -ge $MinReserveBytes)
    }

    $status = 'OK'
    $reasonCode = 'host_resources_ok'
    $errorMessage = $null
    if (-not $memoryCollected) {
        $status = 'ERROR'
        $reasonCode = 'host_resource_collection_failed'
        $errorMessage = if ($diagnostics.Count -gt 0) { $diagnostics -join ' ' } else { 'Failed to collect required host memory metrics.' }
    } elseif (-not $reserveSatisfied) {
        $status = 'OK'
        $reasonCode = 'host_memory_below_reserve'
    } elseif ($diagnostics.Count -gt 0) {
        $reasonCode = 'host_resources_partial'
    }

    $payload = [ordered]@{
        status                   = $status
        reason_code              = $reasonCode
        operation                = 'host-resources'
        hostname                 = $hostname
        logical_cpu_count        = $logicalCpuCount
        total_physical_bytes     = $totalBytes
        available_physical_bytes = $availableBytes
        used_physical_bytes      = $usedBytes
        min_reserve_bytes        = [int64]$MinReserveBytes
        reserve_satisfied        = $reserveSatisfied
        storage_path             = $effectiveStoragePath
        storage_root             = $storageRoot
        storage_available_bytes  = $storageAvailableBytes
        diagnostics              = @($diagnostics)
    }
    if ($null -ne $errorMessage) {
        $payload.error = $errorMessage
    }
    return [pscustomobject]$payload
}
