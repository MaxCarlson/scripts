#Requires -Version 7.0

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

function Get-VmLabBootDiagnostics {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $owned = Assert-VmLabOwnedVm -Name $Name -ManifestRoot $ManifestRoot
    $vm = $owned.vm
    $dvds = @(Get-VMDvdDrive -VMName $Name -ErrorAction SilentlyContinue)
    $attachedIso = @($dvds | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Path) } | Select-Object -ExpandProperty Path)
    $fw = Get-VMFirmware -VMName $Name -ErrorAction SilentlyContinue
    $secureBoot = if ($fw) { [string]$fw.SecureBoot } else { 'Unknown' }
    $firstBootDevice = if ($fw -and $fw.BootOrder -and $fw.BootOrder.Count -gt 0) { [string]$fw.BootOrder[0].BootType } else { 'Unknown' }

    $guidance = @(
        'If UEFI shows "SCSI DVD (0,1): The boot loader failed.", the "Press any key to boot from CD or DVD..." prompt likely timed out.',
        'Open VMConnect first, then perform a controlled restart (stop/start) and press any key immediately when prompted.',
        'Do not disable Secure Boot for standard Windows 11 installation media.'
    )

    return [pscustomobject]@{
        vm_name           = $Name
        vm_id             = [string]$vm.Id
        state             = [string]$vm.State
        attached_isos     = @($attachedIso)
        secure_boot       = $secureBoot
        first_boot_device = $firstBootDevice
        guidance          = $guidance
    }
}

function Connect-VmLabMachine {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $owned = Assert-VmLabOwnedVm -Name $Name -ManifestRoot $ManifestRoot
    $vm = $owned.vm
    if (-not (Test-VmLabInteractiveDesktop)) {
        throw 'VMConnect requires an interactive Windows desktop session (non-interactive/headless session detected).'
    }
    $vmconnectExe = Resolve-VmLabVmConnectPath

    if ($WhatIfPreference) {
        $null = $PSCmdlet.ShouldProcess($Name, "Launch VMConnect ($vmconnectExe localhost '$Name')")
        return [pscustomobject]@{
            status         = 'planned'
            operation      = 'connect'
            vm_name        = $Name
            vm_id          = [string]$vm.Id
            vm_state       = [string]$vm.State
            vmconnect_path = $vmconnectExe
            arguments      = @('localhost', $Name)
        }
    }
    if (-not $PSCmdlet.ShouldProcess($Name, "Launch VMConnect ($vmconnectExe localhost '$Name')")) {
        return [pscustomobject]@{ status = 'declined'; operation = 'connect'; vm_name = $Name }
    }

    $proc = Start-VmLabProcess -FilePath $vmconnectExe -ArgumentList @('localhost', $vm.Name)
    return [pscustomobject]@{
        status         = 'connected'
        operation      = 'connect'
        vm_name        = $vm.Name
        vm_id          = [string]$vm.Id
        vm_state       = [string]$vm.State
        vmconnect_path = $vmconnectExe
        process_id     = if ($proc -and $proc.Id) { [int]$proc.Id } else { $null }
        boot_hint      = 'If booting from Windows Setup ISO, click inside VMConnect and press any key promptly when prompted to boot from DVD.'
    }
}

function Start-AndConnectVmLabMachine {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [int64]$MinHostReserveBytes = 4GB,
        [Alias('a')][switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $startRes = Start-VmLabMachine -Name $Name -MinHostReserveBytes $MinHostReserveBytes -Apply:$Apply -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
    if (-not $Apply -or $WhatIfPreference) {
        return [pscustomobject]@{
            status    = 'planned'
            operation = 'start-connect'
            vm_name   = $Name
            start     = $startRes
            connect   = [pscustomobject]@{ status = 'planned'; interactive_desktop = (Test-VmLabInteractiveDesktop) }
        }
    }
    $connectRes = Connect-VmLabMachine -Name $Name -WhatIf:$WhatIfPreference -ManifestRoot $ManifestRoot
    return [pscustomobject]@{
        status    = 'started_and_connected'
        operation = 'start-connect'
        vm_name   = $Name
        vm_id     = $startRes.vm_id
        start     = $startRes
        connect   = $connectRes
    }
}
