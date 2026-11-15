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
