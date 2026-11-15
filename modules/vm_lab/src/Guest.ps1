#Requires -Version 7.0

function Resolve-VmLabGuestCredential {
    param(
        [pscredential]$Credential,
        [switch]$PromptCredential
    )
    if ($null -ne $Credential) {
        return $Credential
    }
    if ($PromptCredential) {
        if (-not (Test-VmLabInteractiveDesktop)) {
            throw 'Interactive credential prompt requires an interactive desktop session. Pass -Credential explicitly.'
        }
        return (Get-Credential -UserName 'Administrator' -Message 'Enter local Windows guest credentials for PowerShell Direct')
    }
    return $null
}

function New-VmLabPSSession {
    param([guid]$VmId, [pscredential]$Credential)
    return (New-PSSession -VMId $VmId -Credential $Credential -ErrorAction Stop)
}

function Invoke-VmLabPSSessionCommand {
    param([object]$Session, [scriptblock]$ScriptBlock, [object[]]$ArgumentList)
    if ($null -ne $ArgumentList -and $ArgumentList.Count -gt 0) {
        return (Invoke-Command -Session $Session -ScriptBlock $ScriptBlock -ArgumentList $ArgumentList -ErrorAction Stop)
    }
    return (Invoke-Command -Session $Session -ScriptBlock $ScriptBlock -ErrorAction Stop)
}

function Copy-VmLabPSSessionItem {
    param([object]$Session, [string]$SourcePath, [string]$DestinationPath, [string]$Direction, [switch]$Overwrite)
    if ($Direction -eq 'ToGuest') {
        Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -ToSession $Session -Force:$Overwrite -ErrorAction Stop
    } else {
        Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -FromSession $Session -Force:$Overwrite -ErrorAction Stop
    }
}

function Remove-VmLabPSSession {
    param([object]$Session)
    Remove-PSSession -Session $Session -ErrorAction SilentlyContinue
}

function Invoke-VmLabGuestSession {
    param(
        [Parameter(Mandatory)][guid]$VmId,
        [Parameter(Mandatory)][string]$VmName,
        [Parameter(Mandatory)][pscredential]$Credential,
        [Parameter(Mandatory)][scriptblock]$ScriptBlock
    )
    $session = $null
    try {
        try {
            $session = New-VmLabPSSession -VmId $VmId -Credential $Credential
        } catch {
            $msg = $_.Exception.Message
            if ($msg -match 'logon failure|access is denied|password|user name|authentication|credential') {
                throw "PowerShell Direct authentication failed for VM '$VmName': $msg"
            }
            throw "PowerShell Direct connection failed for VM '$VmName' (guest may still be booting or in OOBE): $msg"
        }
        return (& $ScriptBlock $session)
    } finally {
        if ($null -ne $session) {
            Remove-VmLabPSSession -Session $session
        }
    }
}

function Get-VmLabGuestStatus {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Name,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $vm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $vm) {
        return [pscustomobject]@{
            vm_name             = $Name
            vm_id               = $null
            owned               = $false
            guest_state         = 'vm_missing'
            vm_state            = 'Missing'
            heartbeat_status    = 'Unknown'
            ps_direct_available = $false
            bootstrap_state     = 'unknown'
            detail              = "VM '$Name' was not found in Hyper-V inventory."
        }
    }

    $own = Test-VmLabOwnership -Vm $vm -ManifestRoot $ManifestRoot
    $vmState = [string]$vm.State
    if ($vmState -eq 'Off') {
        return [pscustomobject]@{
            vm_name             = $vm.Name
            vm_id               = [string]$vm.Id
            owned               = $own.owned
            guest_state         = 'vm_powered_off'
            vm_state            = $vmState
            heartbeat_status    = 'NotRunning'
            ps_direct_available = $false
            bootstrap_state     = 'unknown'
            detail              = "VM '$($vm.Name)' is powered off."
        }
    }
    if ($vmState -ne 'Running') {
        return [pscustomobject]@{
            vm_name             = $vm.Name
            vm_id               = [string]$vm.Id
            owned               = $own.owned
            guest_state         = 'vm_transitional'
            vm_state            = $vmState
            heartbeat_status    = 'Unknown'
            ps_direct_available = $false
            bootstrap_state     = 'unknown'
            detail              = "VM '$($vm.Name)' is in state '$vmState'."
        }
    }

    $services = @(Get-VMIntegrationService -VMName $vm.Name -ErrorAction SilentlyContinue)
    $hb = $services | Where-Object { $_.Name -eq 'Heartbeat' } | Select-Object -First 1
    $hbStatus = if ($hb) { [string]$hb.PrimaryStatusDescription } else { 'Unknown' }
    $hbOk = ($hbStatus -eq 'OK')

    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        return [pscustomobject]@{
            vm_name             = $vm.Name
            vm_id               = [string]$vm.Id
            owned               = $own.owned
            guest_state         = if ($hbOk) { 'ps_direct_auth_unavailable' } else { 'vm_running_readiness_unknown' }
            vm_state            = $vmState
            heartbeat_status    = $hbStatus
            ps_direct_available = $false
            bootstrap_state     = 'unknown'
            detail              = if ($hbOk) {
                'VM is running and Heartbeat is OK; supply -Credential (or -PromptCredential) to probe PowerShell Direct.'
            } else {
                'VM is running, but guest OS readiness is unknown (Heartbeat not OK and no guest credential supplied).'
            }
        }
    }

    try {
        $probe = Invoke-VmLabGuestSession -VmId ([guid]$vm.Id) -VmName $vm.Name -Credential $cred -ScriptBlock {
            param($sess)
            Invoke-VmLabPSSessionCommand -Session $sess -ScriptBlock {
                $markerPath = 'C:\ProgramData\vm_lab\bootstrap-state.json'
                $bootState = 'incomplete'
                if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
                    try {
                        $m = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
                        if ($m.completed -eq $true) { $bootState = 'complete' }
                    } catch {
                        $bootState = 'incomplete'
                    }
                }
                [pscustomobject]@{
                    os_caption      = (Get-CimInstance Win32_OperatingSystem).Caption
                    computer_name   = $env:COMPUTERNAME
                    ps_version      = $PSVersionTable.PSVersion.ToString()
                    bootstrap_state = $bootState
                }
            }
        }

        $gState = if ($probe.bootstrap_state -eq 'complete') { 'guest_bootstrap_complete' } else { 'ps_direct_operational' }
        return [pscustomobject]@{
            vm_name             = $vm.Name
            vm_id               = [string]$vm.Id
            owned               = $own.owned
            guest_state         = $gState
            vm_state            = $vmState
            heartbeat_status    = $hbStatus
            ps_direct_available = $true
            bootstrap_state     = $probe.bootstrap_state
            guest_os            = $probe.os_caption
            guest_hostname      = $probe.computer_name
            guest_ps_version    = $probe.ps_version
            detail              = 'PowerShell Direct session succeeded.'
        }
    } catch {
        $msg = $_.Exception.Message
        $isAuthFail = $msg -match 'authentication failed'
        return [pscustomobject]@{
            vm_name             = $vm.Name
            vm_id               = [string]$vm.Id
            owned               = $own.owned
            guest_state         = if ($isAuthFail) { 'ps_direct_auth_failed' } else { 'windows_booted_account_unavailable' }
            vm_state            = $vmState
            heartbeat_status    = $hbStatus
            ps_direct_available = $false
            bootstrap_state     = 'unknown'
            detail              = $msg
        }
    }
}

function Copy-VmLabGuestItem {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$SourcePath,
        [Parameter(Mandatory)][string]$DestinationPath,
        [ValidateSet('ToGuest', 'FromGuest')][string]$Direction = 'ToGuest',
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [switch]$Overwrite,
        [Alias('a')][switch]$Apply,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )
    $owned = Assert-VmLabOwnedVm -Name $Name -ManifestRoot $ManifestRoot
    $vm = $owned.vm
    if ([string]$vm.State -ne 'Running') {
        throw "Refusing guest-copy on VM '$Name': VM must be Running (current state: '$($vm.State)')."
    }

    $localHash = $null
    if ($Direction -eq 'ToGuest') {
        $srcFull = Resolve-VmLabFullPath -Path $SourcePath -Label 'SourcePath' -RejectDriveRoot
        Assert-VmLabNoReparsePoint -FullPath $srcFull -Label 'SourcePath'
        if (-not (Test-Path -LiteralPath $srcFull -PathType Leaf)) {
            throw "Source file not found: '$srcFull'."
        }
        $localHash = (Get-FileHash -LiteralPath $srcFull -Algorithm SHA256 -ErrorAction Stop).Hash
    } else {
        $dstFull = Resolve-VmLabFullPath -Path $DestinationPath -Label 'DestinationPath' -RejectDriveRoot
        Assert-VmLabNoReparsePoint -FullPath $dstFull -Label 'DestinationPath'
        if ((Test-Path -LiteralPath $dstFull) -and -not $Overwrite) {
            throw "Local destination file already exists and -Overwrite was not specified: '$dstFull'."
        }
    }

    if (-not $Apply -or $WhatIfPreference) {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($Name, "Copy '$SourcePath' -> '$DestinationPath' ($Direction)")
        }
        return [pscustomobject]@{
            status           = 'planned'
            operation        = 'guest-copy'
            vm_name          = $Name
            vm_id            = [string]$vm.Id
            direction        = $Direction
            source_path      = $SourcePath
            destination_path = $DestinationPath
            overwrite        = [bool]$Overwrite
            source_sha256    = $localHash
        }
    }

    $cred = Resolve-VmLabGuestCredential -Credential $Credential -PromptCredential:$PromptCredential
    if ($null -eq $cred) {
        throw 'Guest credentials are required for guest-copy (-Credential or -PromptCredential).'
    }
    if (-not $PSCmdlet.ShouldProcess($Name, "Copy '$SourcePath' -> '$DestinationPath' ($Direction)")) {
        return [pscustomobject]@{ status = 'declined'; operation = 'guest-copy'; vm_name = $Name }
    }

    return (Invoke-VmLabGuestSession -VmId ([guid]$vm.Id) -VmName $vm.Name -Credential $cred -ScriptBlock {
        param($sess)
        if ($Direction -eq 'ToGuest') {
            $existsOnGuest = Invoke-VmLabPSSessionCommand -Session $sess -ArgumentList @($DestinationPath) -ScriptBlock {
                param($p)
                Test-Path -LiteralPath $p
            }
            if ($existsOnGuest -and -not $Overwrite) {
                throw "Guest destination already exists and -Overwrite was not specified: '$DestinationPath'."
            }
            $dstParent = Split-Path -Parent $DestinationPath
            if (-not [string]::IsNullOrWhiteSpace($dstParent)) {
                $null = Invoke-VmLabPSSessionCommand -Session $sess -ArgumentList @($dstParent) -ScriptBlock {
                    param($d)
                    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
                }
            }
            Copy-VmLabPSSessionItem -Session $sess -SourcePath $SourcePath -DestinationPath $DestinationPath -Direction 'ToGuest' -Overwrite:$Overwrite
            $remoteHash = Invoke-VmLabPSSessionCommand -Session $sess -ArgumentList @($DestinationPath) -ScriptBlock {
                param($p)
                (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash
            }
            if ($remoteHash -ne $localHash) {
                throw "SHA-256 verification failed after ToGuest copy: local=$localHash, remote=$remoteHash."
            }
            return [pscustomobject]@{
                status             = 'copied'
                operation          = 'guest-copy'
                vm_name            = $Name
                direction          = $Direction
                source_path        = $SourcePath
                destination_path   = $DestinationPath
                source_sha256      = $localHash
                destination_sha256 = $remoteHash
                sha256_verified    = $true
            }
        } else {
            $remoteHash = Invoke-VmLabPSSessionCommand -Session $sess -ArgumentList @($SourcePath) -ScriptBlock {
                param($p)
                if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
                    throw "Guest source file not found: '$p'."
                }
                (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash
            }
            $dstParent = Split-Path -Parent $DestinationPath
            if (-not [string]::IsNullOrWhiteSpace($dstParent) -and -not (Test-Path -LiteralPath $dstParent)) {
                New-Item -ItemType Directory -Path $dstParent -Force | Out-Null
            }
            Copy-VmLabPSSessionItem -Session $sess -SourcePath $SourcePath -DestinationPath $DestinationPath -Direction 'FromGuest' -Overwrite:$Overwrite
            $actualLocalHash = (Get-FileHash -LiteralPath $DestinationPath -Algorithm SHA256 -ErrorAction Stop).Hash
            if ($actualLocalHash -ne $remoteHash) {
                throw "SHA-256 verification failed after FromGuest copy: remote=$remoteHash, local=$actualLocalHash."
            }
            return [pscustomobject]@{
                status             = 'copied'
                operation          = 'guest-copy'
                vm_name            = $Name
                direction          = $Direction
                source_path        = $SourcePath
                destination_path   = $DestinationPath
                source_sha256      = $remoteHash
                destination_sha256 = $actualLocalHash
                sha256_verified    = $true
            }
        }
    })
}
