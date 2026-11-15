#Requires -Version 7.0
<#
.SYNOPSIS
    Provision an isolated disposable Windows 11 Hyper-V VM for Resource Coordinator H4 acceptance.
.DESCRIPTION
    Performs read-only preflight validation (PowerShell version, Hyper-V service/cmdlets,
    ISO readability and digest, canonical/reparse-point-free paths, host disk & memory
    capacity, and virtual switch validation) before any mutation.
    Dry-run by default: pass -Apply (-a) to create the VM. Supports -WhatIf.
    Confines all files to -VmRoot and never deletes existing VMs or VHDXs.
.PARAMETER IsoPath
    Path to the Windows 11 installation ISO file (alias: -i).
.PARAMETER VmName
    Name of the Hyper-V VM to create (default: RC-H4-Windows-Acceptance, alias: -n).
.PARAMETER VmRoot
    Root directory for VM configuration and VHDX storage (default: C:\H4-VM-Staging\RC-H4-Windows-Acceptance, alias: -r).
.PARAMETER SwitchName
    Optional existing Hyper-V virtual switch name. Disconnected by default (alias: -s).
.PARAMETER Apply
    Perform actual VM and storage creation. Without -Apply, runs in read-only dry-run mode (alias: -a).
.EXAMPLE
    .\Provision-H4TestVM.ps1 -IsoPath 'C:\Users\mcarls\Downloads\Windows11_Client_x64_en-us_26300_9457.iso'
    Runs read-only preflight and prints the proposed H4 VM configuration.
.EXAMPLE
    .\Provision-H4TestVM.ps1 -IsoPath 'C:\Users\mcarls\Downloads\Windows11_Client_x64_en-us_26300_9457.iso' -Apply
    Provisions the isolated H4 Windows 11 VM in an elevated PowerShell 7 session.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory)][Alias('i')][string]$IsoPath,
    [Alias('n')][string]$VmName = "RC-H4-Windows-Acceptance",
    [Alias('r')][string]$VmRoot = "C:\H4-VM-Staging\RC-H4-Windows-Acceptance",
    [Alias('s')][string]$SwitchName = "",
    [Alias('a')][switch]$Apply
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command -Name Test-IsAdministrator -ErrorAction SilentlyContinue)) {
    function Test-IsAdministrator {
        if ($IsWindows -or $PSVersionTable.Platform -eq 'Win32NT' -or -not $PSVersionTable.Platform) {
            $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
            $principal = [Security.Principal.WindowsPrincipal]::new($identity)
            return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        }
        return $false
    }
}

if (-not (Get-Command -Name Get-H4DriveFreeBytes -ErrorAction SilentlyContinue)) {
    function Get-H4DriveFreeBytes {
        param([Parameter(Mandatory)][string]$TargetPath)
        $root = [System.IO.Path]::GetPathRoot($TargetPath)
        if ([string]::IsNullOrWhiteSpace($root)) {
            throw "Could not determine drive root for path: $TargetPath"
        }
        $drive = [System.IO.DriveInfo]::new($root)
        return [int64]$drive.AvailableFreeSpace
    }
}

if (-not (Get-Command -Name Get-H4HostMemoryInfo -ErrorAction SilentlyContinue)) {
    function Get-H4HostMemoryInfo {
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        return [pscustomobject]@{
            TotalPhysicalBytes = [int64]$os.TotalVisibleMemorySize * 1KB
            FreePhysicalBytes  = [int64]$os.FreePhysicalMemory * 1KB
        }
    }
}

function Assert-NoReparsePoint {
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
                throw "$Label path traverses a reparse point/symlink at '$current' (refusing untrusted target)."
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

$requiredCmdlets = @(
    'Get-VMHost', 'Get-VM', 'Get-VMSwitch', 'New-VM', 'Set-VM',
    'Set-VMFirmware', 'Get-VMFirmware', 'Set-VMKeyProtector', 'Enable-VMTPM',
    'Add-VMDvdDrive', 'Get-VMHardDiskDrive', 'Get-VMNetworkAdapter',
    'Remove-VMNetworkAdapter', 'Add-VMNetworkAdapter'
)

$completedStages = [System.Collections.Generic.List[string]]::new()
$createdDirectories = [System.Collections.Generic.List[string]]::new()
$createdVmName = $null
$createdVmId = $null
$createdVhdxPath = $null
$currentStage = "preflight"

try {
    # 1. PowerShell & Hyper-V cmdlet availability
    if ($PSVersionTable.PSVersion.Major -lt 7) {
        throw "PowerShell 7.0 or newer is required (found $($PSVersionTable.PSVersion))."
    }
    $missingCmdlets = @($requiredCmdlets | Where-Object { -not (Get-Command -Name $_ -ErrorAction SilentlyContinue) })
    if ($missingCmdlets.Count -gt 0) {
        throw "Missing required Hyper-V cmdlets: $($missingCmdlets -join ', '). Ensure the Hyper-V PowerShell module is installed."
    }

    # 2. Validate VM name and canonical target paths (before any Hyper-V or disk mutation)
    if ([string]::IsNullOrWhiteSpace($VmName) -or $VmName -match '[\\/:*?"<>|]') {
        throw "Invalid VM name '$VmName'."
    }
    $vmRootFull = [System.IO.Path]::GetFullPath($VmRoot)
    Assert-NoReparsePoint -FullPath $vmRootFull -Label "VM root"

    $vmPath = [System.IO.Path]::GetFullPath((Join-Path $vmRootFull "vm"))
    $vhdxDir = [System.IO.Path]::GetFullPath((Join-Path $vmRootFull "vhdx"))
    $vhdxPath = [System.IO.Path]::GetFullPath((Join-Path $vhdxDir "$VmName.vhdx"))
    Assert-NoReparsePoint -FullPath $vmPath -Label "VM config path"
    Assert-NoReparsePoint -FullPath $vhdxPath -Label "VHDX path"

    # 3. Validate ISO existence, readability, size, and local SHA-256
    if (-not (Test-Path -LiteralPath $IsoPath -PathType Leaf)) {
        throw "ISO file not found: $IsoPath"
    }
    $isoFull = [System.IO.Path]::GetFullPath($IsoPath)
    Assert-NoReparsePoint -FullPath $isoFull -Label "ISO"
    $isoItem = Get-Item -LiteralPath $isoFull -Force -ErrorAction Stop
    if ($isoItem.Length -lt 3GB) {
        throw "ISO file is unexpectedly small ($([math]::Round($isoItem.Length / 1GB, 2)) GB): $isoFull"
    }
    try {
        $stream = [System.IO.File]::OpenRead($isoItem.FullName)
        $stream.Dispose()
    } catch {
        throw "ISO file is not readable: $($isoItem.FullName) ($($_.Exception.Message))"
    }
    $isoSha = (Get-FileHash -LiteralPath $isoItem.FullName -Algorithm SHA256 -ErrorAction Stop).Hash
    Write-Host "ISO verified locally: $($isoItem.FullName) ($([math]::Round($isoItem.Length / 1GB, 2)) GiB; local SHA256=$isoSha; note: local digest only, not independent signature verification)"

    # 4. Verify Hyper-V service accessibility & permissions (do not swallow errors)
    Write-Host "Checking Hyper-V host, inventory, and switches..."
    $vmHost = Get-VMHost -ErrorAction Stop
    $existingVms = @(Get-VM -ErrorAction Stop)
    $existingSwitches = @(Get-VMSwitch -ErrorAction Stop)

    if ($existingVms | Where-Object { $_.Name -eq $VmName }) {
        throw "VM '$VmName' already exists in Hyper-V inventory. Aborting without modifying existing VMs."
    }
    if (Test-Path -LiteralPath $vhdxPath) {
        throw "Target VHDX already exists: $vhdxPath. Aborting without deleting or overwriting."
    }
    foreach ($preexistingDir in @($vmRootFull, $vmPath, $vhdxDir)) {
        if (Test-Path -LiteralPath $preexistingDir) {
            $leftover = @(Get-ChildItem -LiteralPath $preexistingDir -Force -ErrorAction Stop)
            if ($leftover.Count -gt 0) {
                throw "Target directory '$preexistingDir' is not empty ($($leftover.Count) existing item(s)). Refusing to reuse preexisting artifacts."
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($SwitchName)) {
        $matchedSwitch = $existingSwitches | Where-Object { $_.Name -eq $SwitchName } | Select-Object -First 1
        if (-not $matchedSwitch) {
            throw "Requested virtual switch '$SwitchName' does not exist. Refusing to create or modify host virtual switches."
        }
    }

    # 5. Host storage & memory preflight
    $vhdxMaxBytes = [int64]80GB
    $freeDiskBytes = Get-H4DriveFreeBytes -TargetPath $vmRootFull
    if ($freeDiskBytes -lt $vhdxMaxBytes) {
        throw ("Insufficient free disk space on target drive for '{0}': {1:N2} GiB free, requires at least {2:N2} GiB for the 80 GiB maximum dynamic VHDX." -f `
            $vmRootFull, ($freeDiskBytes / 1GB), ($vhdxMaxBytes / 1GB))
    }

    $memInfo = Get-H4HostMemoryInfo
    $runningVmStartupBytes = [int64](($existingVms | Where-Object { $_.State -eq 'Running' } | Measure-Object -Property MemoryStartup -Sum).Sum)

    # 6. Print proposed configuration
    Write-Host ""
    Write-Host "Proposed H4 VM Configuration:"
    Write-Host "  Host             : $($vmHost.ComputerName)"
    Write-Host "  VM Name          : $VmName"
    Write-Host "  VM Root          : $vmRootFull"
    Write-Host "  VM Config Path   : $vmPath"
    Write-Host "  VHDX Path        : $vhdxPath (80 GiB Dynamic, Generation 2)"
    Write-Host "  CPU / RAM        : 4 vCPU | 4 GiB min / 6 GiB startup / 8 GiB max (Dynamic)"
    Write-Host "  Security         : Secure Boot (MicrosoftWindows) + Local Key Protector + vTPM"
    Write-Host "  Checkpoints      : Standard (AutomaticCheckpointsEnabled = False)"
    Write-Host "  Network          : $(if ([string]::IsNullOrWhiteSpace($SwitchName)) { 'Disconnected (no NIC)' } else { "Switch '$SwitchName'" })"
    Write-Host "  AutoStart / Boot : AutomaticStartAction=Nothing | BootOrder=DVD, VHDX (no auto VM start)"
    Write-Host ("  Host Disk Free   : {0:N2} GiB (80 GiB VHDX max)" -f ($freeDiskBytes / 1GB))
    Write-Host ("  Host Memory      : {0:N2} GiB free / {1:N2} GiB total (running VM startup sum: {2:N2} GiB)" -f `
        ($memInfo.FreePhysicalBytes / 1GB), ($memInfo.TotalPhysicalBytes / 1GB), ($runningVmStartupBytes / 1GB))
    Write-Host ""

    $completedStages.Add("preflight")

    if (-not $Apply -or $WhatIfPreference) {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($VmName, "Provision Hyper-V VM at '$vmRootFull'")
        }
        Write-Host "DRY-RUN: No filesystem or Hyper-V changes made. Re-run with -Apply in an elevated PowerShell 7 session to provision."
        exit 0
    }

    if (-not (Test-IsAdministrator)) {
        throw "Interactive Administrator elevation is required to provision Hyper-V VMs. Re-run in an elevated PowerShell 7 session."
    }

    if (-not $PSCmdlet.ShouldProcess($VmName, "Provision Hyper-V VM at '$vmRootFull'")) {
        Write-Host "Operation declined by ShouldProcess; no changes made."
        exit 0
    }

    # Immediate pre-mutation existence re-check
    if (Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $VmName }) {
        throw "VM '$VmName' appeared before mutation. Aborting."
    }
    if (Test-Path -LiteralPath $vhdxPath) {
        throw "Target VHDX appeared before mutation: $vhdxPath. Aborting."
    }

    # Stage 1: Directories
    $currentStage = "create_directories"
    foreach ($dir in @($vmRootFull, $vmPath, $vhdxDir)) {
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force -ErrorAction Stop | Out-Null
            $createdDirectories.Add($dir)
        }
    }
    $completedStages.Add("create_directories")

    # Stage 2: Combined New-VM (New VHD parameter set)
    $currentStage = "new_vm"
    $newVm = New-VM `
        -Name $VmName `
        -Generation 2 `
        -MemoryStartupBytes 6GB `
        -Path $vmPath `
        -NewVHDPath $vhdxPath `
        -NewVHDSizeBytes 80GB `
        -ErrorAction Stop
    $createdVmName = $VmName
    if ($newVm -and $newVm.Id) { $createdVmId = [string]$newVm.Id }
    $createdVhdxPath = $vhdxPath
    $completedStages.Add("new_vm")

    # Stage 3: Network adapter
    $currentStage = "configure_network"
    Get-VMNetworkAdapter -VMName $VmName -ErrorAction Stop | Remove-VMNetworkAdapter -ErrorAction Stop
    if (-not [string]::IsNullOrWhiteSpace($SwitchName)) {
        Add-VMNetworkAdapter -VMName $VmName -SwitchName $SwitchName -ErrorAction Stop | Out-Null
    }
    $completedStages.Add("configure_network")

    # Stage 4: Compute, memory, checkpoints, boot policy
    $currentStage = "configure_vm"
    Set-VM -Name $VmName `
        -ProcessorCount 4 `
        -DynamicMemory `
        -MemoryMinimumBytes 4GB `
        -MemoryStartupBytes 6GB `
        -MemoryMaximumBytes 8GB `
        -CheckpointType Standard `
        -AutomaticCheckpointsEnabled $false `
        -AutomaticStartAction Nothing `
        -ErrorAction Stop
    $completedStages.Add("configure_vm")

    # Stage 5: Secure Boot + vTPM
    $currentStage = "configure_security"
    Set-VMFirmware -VMName $VmName -EnableSecureBoot On -SecureBootTemplate "MicrosoftWindows" -ErrorAction Stop
    Set-VMKeyProtector -VMName $VmName -NewLocalKeyProtector -ErrorAction Stop
    Enable-VMTPM -VMName $VmName -ErrorAction Stop
    $completedStages.Add("configure_security")

    # Stage 6: Attach ISO & set boot order
    $currentStage = "attach_iso_and_boot_order"
    $dvd = Add-VMDvdDrive -VMName $VmName -Path $isoItem.FullName -Passthru -ErrorAction Stop
    $vhdDrive = Get-VMHardDiskDrive -VMName $VmName -ErrorAction Stop
    if (-not $dvd -or -not $vhdDrive) {
        throw "Failed to resolve DVD or VHDX drive after attachment."
    }
    Set-VMFirmware -VMName $VmName -BootOrder $dvd, $vhdDrive -ErrorAction Stop
    $completedStages.Add("attach_iso_and_boot_order")

    # Stage 7: Final verification
    $currentStage = "verify_final_state"
    $finalVm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $VmName } | Select-Object -First 1
    $finalFirmware = Get-VMFirmware -VMName $VmName -ErrorAction Stop
    if (-not $finalVm -or $finalVm.Generation -ne 2 -or $finalVm.ProcessorCount -ne 4) {
        throw "Final VM verification failed: Generation or ProcessorCount mismatch."
    }
    $bootTypes = @($finalFirmware.BootOrder | ForEach-Object { $_.BootType })
    if ($bootTypes.Count -lt 2) {
        throw "Final VM firmware boot order verification failed: expected DVD and VHDX entries."
    }
    $completedStages.Add("verify_final_state")

    Write-Host "Provisioned and verified isolated VM '$VmName' at '$vmRootFull'."
    $finalVm | Select-Object Name, Id, Generation, State, ProcessorCount, MemoryStartup, MemoryMinimum, MemoryMaximum, CheckpointType | Format-List
    Write-Host "Next: Start-VM -Name '$VmName'; vmconnect.exe localhost '$VmName'"
    exit 0
}
catch {
    Write-Error ("Provisioning failed during stage '{0}': {1}" -f $currentStage, $_.Exception.Message) -ErrorAction Continue
    if ($completedStages.Count -gt 0) {
        Write-Host ("Completed stages: {0}" -f ($completedStages -join ', '))
    }
    if ($createdVmName -or $createdVhdxPath -or $createdDirectories.Count -gt 0) {
        Write-Host "Preserved invocation-owned artifacts (no automatic deletion performed):"
        if ($createdVmName) { Write-Host "  VM      : $createdVmName (Id=$createdVmId)" }
        if ($createdVhdxPath) { Write-Host "  VHDX    : $createdVhdxPath" }
        foreach ($d in $createdDirectories) { Write-Host "  Dir     : $d" }
        Write-Host "Manual cleanup for confirmed invocation-owned artifacts only:"
        if ($createdVmName) { Write-Host "  Remove-VM -Name '$createdVmName' -Force" }
        if ($createdVhdxPath) { Write-Host "  Remove-Item -LiteralPath '$createdVhdxPath'" }
    }
    exit 1
}
