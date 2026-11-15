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
