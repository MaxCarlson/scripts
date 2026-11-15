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
