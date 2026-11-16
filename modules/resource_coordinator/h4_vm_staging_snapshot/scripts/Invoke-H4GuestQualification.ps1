#Requires -Version 7.0
<#
.SYNOPSIS
    Staged, fail-closed H4 Windows 11 guest qualification orchestrator via Hyper-V PowerShell Direct.
.DESCRIPTION
    Automates read-only preflight, offline guest prerequisite installation, powered-off
    Standard baseline checkpointing, and the H4 Windows acceptance matrix (offline, task,
    full, 5x rollback fault stages, and scoped cleanup) inside the isolated H4 guest VM.

    Default invocation runs read-only Preflight only.
    Any host/guest mutation requires -Apply (-a).
    Guest Task Scheduler, lifecycle, rollback, and guest power-state mutations additionally
    require -AuthorizeGuestMutation.
    -WhatIf suppresses all mutations even when combined with -Apply.
.PARAMETER Stage
    Execution stage: Preflight (default), Setup, Checkpoint, Acceptance, or All.
.PARAMETER Apply
    Authorize filesystem, Hyper-V, and guest setup mutations (alias: -a).
.PARAMETER AuthorizeGuestMutation
    Explicitly authorize H4 guest Task Scheduler/lifecycle mutations and guest shutdown/checkpoint/start.
.PARAMETER Json
    Emit final stage summary as JSON (alias: -j).
.PARAMETER OperationId
    Optional unique operation ID for resumable evidence and test-root tracking.
.PARAMETER VmId
    Exact Hyper-V VM GUID (default: d8483f98-8884-4758-abd1-cd6107c83c03).
.PARAMETER VmName
    Expected Hyper-V VM name (default: RC-H4-Windows-Acceptance).
.PARAMETER ExpectedGuestHost
    Expected guest hostname (default: DESKTOP-1ITSJV0).
.PARAMETER Credential
    Guest local administrator credential for PowerShell Direct (never logged or persisted).
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [ValidateSet('Preflight', 'Setup', 'Checkpoint', 'Acceptance', 'All')]
    [string]$Stage = 'Preflight',
    [Alias('a')][switch]$Apply,
    [switch]$AuthorizeGuestMutation,
    [Alias('j')][switch]$Json,
    [string]$OperationId,
    [string]$VmId = 'd8483f98-8884-4758-abd1-cd6107c83c03',
    [string]$VmName = 'RC-H4-Windows-Acceptance',
    [string]$ExpectedGuestHost = 'DESKTOP-1ITSJV0',
    [pscredential]$Credential,
    [string]$BundleZip = 'C:\H4-VM-Staging\bundle-rc1-v3\h4-windows-acceptance.zip',
    [string]$ExpectedBundleSha256 = 'daaf9a7b7bd5534a17541f49660360c060a2ba3df946dbddca46e6b63797e7fe',
    [string]$BootstrapScript = (Join-Path $PSScriptRoot 'Bootstrap-H4GuestBundle.ps1'),
    [string]$ExpectedBootstrapSha256 = '5EFACFAFCECC45DF5459D53B75A999B21574C83D0A2F5339F0A4AB1AB5D01DE9',
    [string]$WheelsDir = 'C:\H4-VM-Staging\guest-deps\wheels',
    [string]$WheelsManifest = 'C:\H4-VM-Staging\guest-deps\wheels-sha256.txt',
    [string]$PythonInstaller = 'C:\H4-VM-Staging\guest-deps\installers\python-3.12.10-amd64.exe',
    [string]$ExpectedPythonSha256 = '67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB',
    [string]$PwshInstaller = 'C:\H4-VM-Staging\guest-deps\installers\PowerShell-7.6.10-win-x64.msi',
    [string]$ExpectedPwshSha256 = '7D8DAEA48B450D4D62FCD1AC4D6FAA7AC2DB5E11ABA5061EE81B7496ADCA8C07',
    [string]$EvidenceRoot = 'C:\H4-VM-Staging\evidence',
    [string]$CheckpointName = '',
    [ValidatePattern('^[a-zA-Z0-9_-]*$')]
    [string]$RunSuffix = ''
)

$ErrorActionPreference = 'Stop'
$H4AuthorizationPhrase = 'I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION'
$RollbackStages = @(
    'after_prepared_receipt',
    'after_old_service_stopped',
    'before_task_replacement',
    'after_task_replacement',
    'after_new_service_ready'
)

# Injectable host/guest boundary helpers for Pester testability
if (-not (Get-Command -Name Get-H4HostVm -ErrorAction SilentlyContinue)) {
    function Get-H4HostVm {
        param([Parameter(Mandatory)][string]$Id)
        $vmGuid = [guid]$Id
        $vms = @(Get-VM -Id $vmGuid -ErrorAction Stop)
        if ($vms.Count -ne 1) {
            throw "Expected exactly 1 Hyper-V VM for ID '$Id', found $($vms.Count)."
        }
        return $vms[0]
    }
}
if (-not (Get-Command -Name Start-H4HostVm -ErrorAction SilentlyContinue)) {
    function Start-H4HostVm {
        param([Parameter(Mandatory)][string]$Id, [string]$ExpectedName = $VmName)
        $vmObj = Get-H4HostVm -Id $Id
        if (-not $vmObj -or [string]$vmObj.Id -ne $Id -or ($ExpectedName -and $vmObj.Name -ne $ExpectedName)) {
            throw "Hyper-V VM verification failed before Start-VM for ID '$Id' (found name='$($vmObj.Name)', id='$($vmObj.Id)')."
        }
        Start-VM -VM $vmObj -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Stop-H4HostVm -ErrorAction SilentlyContinue)) {
    function Stop-H4HostVm {
        param([Parameter(Mandatory)][string]$Id, [string]$ExpectedName = $VmName)
        $vmObj = Get-H4HostVm -Id $Id
        if (-not $vmObj -or [string]$vmObj.Id -ne $Id -or ($ExpectedName -and $vmObj.Name -ne $ExpectedName)) {
            throw "Hyper-V VM verification failed before Stop-VM for ID '$Id' (found name='$($vmObj.Name)', id='$($vmObj.Id)')."
        }
        # Graceful guest shutdown only; never -TurnOff or -Force
        Stop-VM -VM $vmObj -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Get-H4HostCheckpoints -ErrorAction SilentlyContinue)) {
    function Get-H4HostCheckpoints {
        param([Parameter(Mandatory)][string]$Id)
        $vmObj = Get-H4HostVm -Id $Id
        return @(Get-VMSnapshot -VM $vmObj -ErrorAction Stop)
    }
}
if (-not (Get-Command -Name New-H4HostCheckpoint -ErrorAction SilentlyContinue)) {
    function New-H4HostCheckpoint {
        param([Parameter(Mandatory)][string]$Id, [Parameter(Mandatory)][string]$SnapshotName)
        $vmObj = Get-H4HostVm -Id $Id
        return Checkpoint-VM -VM $vmObj -SnapshotName $SnapshotName -Passthru -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Open-H4GuestSession -ErrorAction SilentlyContinue)) {
    function Open-H4GuestSession {
        param([Parameter(Mandatory)][string]$Id, [Parameter(Mandatory)][pscredential]$Cred)
        return New-PSSession -VMId $Id -Credential $Cred -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Close-H4GuestSession -ErrorAction SilentlyContinue)) {
    function Close-H4GuestSession {
        param($Session)
        if ($Session) { Remove-PSSession -Session $Session -ErrorAction SilentlyContinue }
    }
}
if (-not (Get-Command -Name Invoke-H4GuestScript -ErrorAction SilentlyContinue)) {
    function Invoke-H4GuestScript {
        param($Session, [Parameter(Mandatory)][scriptblock]$ScriptBlock, [object[]]$ArgumentList = @())
        return Invoke-Command -Session $Session -ScriptBlock $ScriptBlock -ArgumentList $ArgumentList -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Copy-H4ToGuest -ErrorAction SilentlyContinue)) {
    function Copy-H4ToGuest {
        param($Session, [Parameter(Mandatory)][string]$SourcePath, [Parameter(Mandatory)][string]$DestinationPath)
        Copy-Item -ToSession $Session -LiteralPath $SourcePath -Destination $DestinationPath -Force -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Copy-H4FromGuest -ErrorAction SilentlyContinue)) {
    function Copy-H4FromGuest {
        param($Session, [Parameter(Mandatory)][string]$SourcePath, [Parameter(Mandatory)][string]$DestinationPath)
        Copy-Item -FromSession $Session -Path $SourcePath -Destination $DestinationPath -Recurse -Force -ErrorAction Stop
    }
}
if (-not (Get-Command -Name Request-H4GuestCredential -ErrorAction SilentlyContinue)) {
    function Request-H4GuestCredential {
        param([string]$UserHint = 'DESKTOP-1ITSJV0\mcarls')
        return Get-Credential -UserName $UserHint -Message 'Enter Windows 11 guest local admin credentials for PowerShell Direct'
    }
}

function Assert-H4NoReparsePoint {
    param([Parameter(Mandatory)][string]$FullPath, [Parameter(Mandatory)][string]$Label)
    $root = [System.IO.Path]::GetPathRoot($FullPath)
    $current = $FullPath
    while (-not [string]::IsNullOrWhiteSpace($current) -and $current -ne $root) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label path traverses a reparse point at '$current'."
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Assert-H4FileDigest {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$ExpectedSha256, [Parameter(Mandatory)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    if ([string]::IsNullOrWhiteSpace($ExpectedSha256) -or $ExpectedSha256 -notmatch '^[0-9A-Fa-f]{64}$') {
        throw "$Label expected SHA-256 must be a 64-character hex digest, got '$ExpectedSha256'"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path -ErrorAction Stop).Hash
    if ($actual.ToLowerInvariant() -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "$Label SHA-256 mismatch: expected $ExpectedSha256, got $actual"
    }
    return $actual
}

function Get-H4WheelManifestEntries {
    param([Parameter(Mandatory)][string]$ManifestPath, [Parameter(Mandatory)][string]$Dir)
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Wheel checksum manifest not found: $ManifestPath"
    }
    $entries = [System.Collections.Generic.List[object]]::new()
    foreach ($line in (Get-Content -LiteralPath $ManifestPath -Encoding utf8)) {
        if ($line -match '^\s*([0-9A-Fa-f]{64})\s+(\S+)\s+\((\d+)\s+bytes\)') {
            $sha = $Matches[1].ToUpperInvariant()
            $name = $Matches[2]
            $size = [int64]$Matches[3]
            $full = Join-Path $Dir $name
            $actual = Assert-H4FileDigest -Path $full -ExpectedSha256 $sha -Label "Wheel $name"
            $entries.Add([pscustomobject]@{ name = $name; sha256 = $actual; size = $size; path = $full })
        }
    }
    if ($entries.Count -eq 0) {
        throw "No valid entries found in wheel manifest: $ManifestPath"
    }
    return $entries
}

function Assert-H4GuestIdentity {
    param($Session, [Parameter(Mandatory)][string]$ExpectedHost, [switch]$RequireCleanRc)
    $info = Invoke-H4GuestScript -Session $Session -ScriptBlock {
        $ErrorActionPreference = 'Stop'
        $cs = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
        $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

        # Fail closed if task/service/process inventories cannot be read
        $tasks = @(Get-ScheduledTask -ErrorAction Stop)
        $rcTasks = @($tasks | Where-Object { $_.TaskName -like '*ResourceCoordinator*' -or $_.TaskName -like '*KRig*' })
        $services = @(Get-Service -ErrorAction Stop)
        $rcServices = @($services | Where-Object { $_.Name -like '*ResourceCoordinator*' -or $_.Name -like '*KRig*' })
        $procs = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
        $rcProcs = @($procs | Where-Object { $_.Name -match 'resource[-_]?coordinator|krig' -or $_.CommandLine -match 'resource_coordinator|krig-miner' })

        [pscustomobject]@{
            hostname         = $env:COMPUTERNAME
            user             = "$env:USERDOMAIN\$env:USERNAME"
            is_admin         = $isAdmin
            manufacturer     = [string]$cs.Manufacturer
            model            = [string]$cs.Model
            os_caption       = [string]$os.Caption
            os_version       = [string]$os.Version
            os_build         = [string]$os.BuildNumber
            os_arch          = [string]$os.OSArchitecture
            rc_task_count    = $rcTasks.Count
            rc_service_count = $rcServices.Count
            rc_proc_count    = $rcProcs.Count
        }
    }
    if (-not $info -or $info.hostname -ne $ExpectedHost -or $info.hostname -eq 'XERES') {
        throw "Guest hostname verification failed: got '$($info.hostname)', expected '$ExpectedHost' (must not be XERES)."
    }
    if ($info.manufacturer -notmatch 'Microsoft' -or $info.model -notmatch 'Virtual Machine') {
        throw "Guest hardware is not a Hyper-V virtual machine: $($info.manufacturer) / $($info.model)."
    }
    if ($info.os_caption -notmatch 'Windows 11') {
        throw "Guest OS is not Windows 11: $($info.os_caption)"
    }
    if (-not $info.is_admin) {
        throw "Guest session user '$($info.user)' does not have guest Administrator privileges."
    }
    if ($RequireCleanRc -and ($info.rc_task_count -gt 0 -or $info.rc_service_count -gt 0 -or $info.rc_proc_count -gt 0)) {
        throw "Guest is not clean of RC/KRig artifacts (tasks=$($info.rc_task_count), services=$($info.rc_service_count), procs=$($info.rc_proc_count))."
    }
    return $info
}

function Save-H4JsonArtifact {
    param([string]$Dir, [string]$FileName, $Data)
    if ($Dir -and (Test-Path -LiteralPath $Dir)) {
        $Data | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Dir $FileName) -Encoding utf8
    }
}

if ([string]::IsNullOrWhiteSpace($OperationId)) {
    $OperationId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
}
if ($OperationId -notmatch '^[A-Za-z0-9_-]{4,48}$') {
    throw "Invalid OperationId '$OperationId'."
}
if ([string]::IsNullOrWhiteSpace($CheckpointName)) {
    $CheckpointName = "H4-Win11-Clean-Prerequisites-$(Get-Date -Format 'yyyyMMdd')"
}

$isMutatingMode = $Apply -and -not $WhatIfPreference
$stagesToRun = switch ($Stage) {
    'Preflight'  { @('Preflight') }
    'Setup'      { @('Preflight', 'Setup') }
    'Checkpoint' { @('Preflight', 'Checkpoint') }
    'Acceptance' { @('Preflight', 'Acceptance') }
    'All'        { @('Preflight', 'Setup', 'Checkpoint', 'Acceptance') }
}

$stageResults = [ordered]@{
    Preflight  = 'NOT_RUN'
    Setup      = 'NOT_RUN'
    Checkpoint = 'NOT_RUN'
    Acceptance = 'NOT_RUN'
}
$summary = [ordered]@{
    schema_version    = 1
    operation_id      = $OperationId
    stage_requested   = $Stage
    apply_requested   = [bool]$Apply
    whatif            = [bool]$WhatIfPreference
    guest_authorized  = [bool]$AuthorizeGuestMutation
    vm_id             = $VmId
    vm_name           = $VmName
    expected_guest    = $ExpectedGuestHost
    evidence_dir      = $null
    stage_results     = $stageResults
    profiles          = @()
    checkpoint        = $null
    error             = $null
    error_category    = $null
}

$hostEvidenceDir = [System.IO.Path]::GetFullPath((Join-Path $EvidenceRoot $OperationId))
$session = $null
$overallExit = 0

try {
    # 1. Host asset & VM verification (read-only)
    $vm = Get-H4HostVm -Id $VmId
    if (-not $vm -or $vm.Name -ne $VmName) {
        throw "Hyper-V VM verification failed for ID '$VmId' (found name='$($vm.Name)', expected '$VmName')."
    }
    $bundleSha = Assert-H4FileDigest -Path $BundleZip -ExpectedSha256 $ExpectedBundleSha256 -Label 'Acceptance bundle'
    $bootstrapSha = Assert-H4FileDigest -Path $BootstrapScript -ExpectedSha256 $ExpectedBootstrapSha256 -Label 'Standalone Bootstrap-H4GuestBundle.ps1'
    $pySha = Assert-H4FileDigest -Path $PythonInstaller -ExpectedSha256 $ExpectedPythonSha256 -Label 'Python 3.12.10 installer'
    $pwshSha = Assert-H4FileDigest -Path $PwshInstaller -ExpectedSha256 $ExpectedPwshSha256 -Label 'PowerShell 7 MSI'
    $wheelEntries = Get-H4WheelManifestEntries -ManifestPath $WheelsManifest -Dir $WheelsDir

    if ($isMutatingMode) {
        Assert-H4NoReparsePoint -FullPath $hostEvidenceDir -Label 'Host evidence root'
        if (-not $PSCmdlet.ShouldProcess($VmName, "Execute H4 stage '$Stage' (OperationId=$OperationId)")) {
            $stageResults['Preflight'] = 'PASS'
            $summary['evidence_dir'] = $null
            if ($Json) { $summary | ConvertTo-Json -Depth 8 } else { Write-Host 'Operation declined by ShouldProcess; no changes made.' }
            exit 0
        }
        if ((Test-Path -LiteralPath $hostEvidenceDir) -and @(Get-ChildItem -LiteralPath $hostEvidenceDir -Force -ErrorAction SilentlyContinue).Count -gt 0) {
            throw "Host evidence directory already exists and is non-empty: '$hostEvidenceDir'. Supply a distinct -EvidenceRoot (or -OperationId) to preserve existing evidence."
        }
        New-Item -ItemType Directory -Path $hostEvidenceDir -Force -ErrorAction Stop | Out-Null
        $summary['evidence_dir'] = $hostEvidenceDir
    } else {
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess($VmName, "Execute H4 stage '$Stage' (OperationId=$OperationId)")
        }
    }

    # Establish PowerShell Direct only when VM is running (or required)
    if ($vm.State -ne 'Running' -and $Stage -ne 'Checkpoint') {
        throw "VM '$VmName' ($VmId) state is '$($vm.State)'; expected 'Running' for PowerShell Direct."
    }

    if ($vm.State -eq 'Running') {
        if (-not $Credential) {
            $Credential = Request-H4GuestCredential -UserHint "$ExpectedGuestHost\mcarls"
        }
        $session = Open-H4GuestSession -Id $VmId -Cred $Credential
        $guestInfo = Assert-H4GuestIdentity -Session $session -ExpectedHost $ExpectedGuestHost -RequireCleanRc
        Save-H4JsonArtifact -Dir $summary['evidence_dir'] -FileName 'guest-identity.json' -Data $guestInfo
        $summary['guest_os'] = "$($guestInfo.os_caption) Build $($guestInfo.os_build) ($($guestInfo.os_arch))"
    }

    $stageResults['Preflight'] = 'PASS'

    if (-not $isMutatingMode) {
        $summary['stage_results'] = $stageResults
        if ($Json) {
            $summary | ConvertTo-Json -Depth 8
        } else {
            Write-Host "DRY-RUN / READ-ONLY PREFLIGHT PASSED (OperationId=$OperationId, Stage=$Stage)."
            Write-Host "  VM: $VmName ($VmId) | Bundle SHA256=$bundleSha | Bootstrap SHA256=$bootstrapSha | Wheels=$($wheelEntries.Count)"
            Write-Host "  Re-run with -Apply to execute '$Stage' (and -AuthorizeGuestMutation for guest lifecycle/checkpoint mutations)."
        }
        exit 0
    }

    $guestBundleDest = "C:\H4-Guest-Work\bundles\$OperationId"
    $guestBundleRoot = $guestBundleDest
    $guestManifest = "$guestBundleRoot\manifest.json"
    $guestSrcNew = "$guestBundleRoot\sources\rc-1.0.0"
    $guestSrcOld = "$guestBundleRoot\sources\rc-0.14.0"
    $guestVenvPy = 'C:\H4-Guest-Work\venv\Scripts\python.exe'
    $guestRunner = "$guestBundleRoot\harness\windows_acceptance.py"

    # 2. Setup stage
    if ($stagesToRun -contains 'Setup') {
        $null = Assert-H4GuestIdentity -Session $session -ExpectedHost $ExpectedGuestHost -RequireCleanRc
        Invoke-H4GuestScript -Session $session -ScriptBlock {
            $ErrorActionPreference = 'Stop'
            foreach ($d in @('C:\H4-Guest-Work', 'C:\H4-Guest-Work\installers', 'C:\H4-Guest-Work\wheels', 'C:\H4-Guest-Work\bundle-src', 'C:\H4-Guest-Work\bundles', 'C:\H4-Guest-Work\runs', 'C:\H4-Guest-Work\wrapper-logs')) {
                if (-not (Test-Path -LiteralPath $d)) {
                    New-Item -ItemType Directory -Path $d -Force -ErrorAction Stop | Out-Null
                }
            }
        }
        Copy-H4ToGuest -Session $session -SourcePath $PythonInstaller -Destination 'C:\H4-Guest-Work\installers\python-3.12.10-amd64.exe'
        Copy-H4ToGuest -Session $session -SourcePath $PwshInstaller -Destination 'C:\H4-Guest-Work\installers\PowerShell-7.6.10-win-x64.msi'
        foreach ($w in $wheelEntries) {
            Copy-H4ToGuest -Session $session -SourcePath $w.path -Destination ("C:\H4-Guest-Work\wheels\" + $w.name)
        }
        Copy-H4ToGuest -Session $session -SourcePath $BundleZip -Destination 'C:\H4-Guest-Work\bundle-src\h4-windows-acceptance.zip'
        Copy-H4ToGuest -Session $session -SourcePath $BootstrapScript -Destination 'C:\H4-Guest-Work\bundle-src\Bootstrap-H4GuestBundle.ps1'

        $setupRes = Invoke-H4GuestScript -Session $session -ArgumentList @($pySha, $pwshSha, $bundleSha, $bootstrapSha, $guestBundleDest, ($wheelEntries | ConvertTo-Json -Compress), $OperationId) -ScriptBlock {
            param($expPy, $expPwsh, $expBundle, $expBoot, $destBundle, $wheelsJson, $opId)
            $ErrorActionPreference = 'Stop'

            $actPy = (Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\H4-Guest-Work\installers\python-3.12.10-amd64.exe').Hash
            if ($actPy.ToLowerInvariant() -ne $expPy.ToLowerInvariant()) { throw "Guest Python installer SHA-256 mismatch: $actPy" }
            $actPwsh = (Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\H4-Guest-Work\installers\PowerShell-7.6.10-win-x64.msi').Hash
            if ($actPwsh.ToLowerInvariant() -ne $expPwsh.ToLowerInvariant()) { throw "Guest pwsh MSI SHA-256 mismatch: $actPwsh" }
            $actBundle = (Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\H4-Guest-Work\bundle-src\h4-windows-acceptance.zip').Hash
            if ($actBundle.ToLowerInvariant() -ne $expBundle.ToLowerInvariant()) { throw "Guest bundle SHA-256 mismatch: $actBundle" }
            $actBoot = (Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\H4-Guest-Work\bundle-src\Bootstrap-H4GuestBundle.ps1').Hash
            if ($actBoot.ToLowerInvariant() -ne $expBoot.ToLowerInvariant()) { throw "Guest bootstrap script SHA-256 mismatch: $actBoot" }

            foreach ($w in ($wheelsJson | ConvertFrom-Json)) {
                $wPath = Join-Path 'C:\H4-Guest-Work\wheels' $w.name
                $wHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $wPath).Hash
                if ($wHash.ToLowerInvariant() -ne $w.sha256.ToLowerInvariant()) {
                    throw "Guest wheel SHA-256 mismatch for $($w.name): $wHash"
                }
            }

            $rebootRequired = $false
            $env:PYTHONDONTWRITEBYTECODE = '1'
            $pwshExe = 'C:\Program Files\PowerShell\7\pwsh.exe'
            if (-not (Test-Path -LiteralPath $pwshExe)) {
                $p = Start-Process -FilePath 'msiexec.exe' -ArgumentList '/i', 'C:\H4-Guest-Work\installers\PowerShell-7.6.10-win-x64.msi', '/quiet', '/norestart' -Wait -PassThru
                if ($p.ExitCode -eq 3010) { $rebootRequired = $true }
                elseif ($p.ExitCode -ne 0) { throw "PowerShell 7 MSI exited $($p.ExitCode)" }
            }

            $pyExe = 'C:\Program Files\Python312\python.exe'
            if (-not (Test-Path -LiteralPath $pyExe)) {
                $p = Start-Process -FilePath 'C:\H4-Guest-Work\installers\python-3.12.10-amd64.exe' -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0' -Wait -PassThru
                if ($p.ExitCode -eq 3010) { $rebootRequired = $true }
                elseif ($p.ExitCode -ne 0) { throw "Python 3.12.10 installer exited $($p.ExitCode)" }
            }
            if ($rebootRequired) {
                return [pscustomobject]@{ status = 'reboot_required'; pwsh_version = $null; python_version = $null }
            }

            $env:PYTHONDONTWRITEBYTECODE = '1'
            $venvPy = 'C:\H4-Guest-Work\venv\Scripts\python.exe'
            if (-not (Test-Path -LiteralPath $venvPy)) {
                & $pyExe -m venv 'C:\H4-Guest-Work\venv'
                if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
            }

            # Non-destructive immutable bundle extraction (never Remove-Item -Recurse -Force on existing dir)
            if (Test-Path -LiteralPath $destBundle) {
                throw "Target extraction directory already exists; refusing destructive overwrite: $destBundle"
            }
            & $pwshExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File 'C:\H4-Guest-Work\bundle-src\Bootstrap-H4GuestBundle.ps1' `
                -ArchivePath 'C:\H4-Guest-Work\bundle-src\h4-windows-acceptance.zip' `
                -ExpectedSha256 $expBundle `
                -DestinationRoot $destBundle `
                -Python $pyExe
            if ($LASTEXITCODE -ne 0) { throw "Bootstrap-H4GuestBundle.ps1 failed with exit $LASTEXITCODE" }

            $reqMain = "$destBundle\dependencies\requirements.txt"
            $reqDev = "$destBundle\dependencies\requirements-dev.txt"
            & $venvPy -m pip install --no-index --find-links 'C:\H4-Guest-Work\wheels' --upgrade setuptools wheel
            if ($LASTEXITCODE -ne 0) { throw "Offline setuptools/wheel install failed" }
            & $venvPy -m pip install --no-index --find-links 'C:\H4-Guest-Work\wheels' -r $reqMain -r $reqDev resource-metrics
            if ($LASTEXITCODE -ne 0) { throw "Offline pinned wheel install failed" }

            & $venvPy -B -c "import anyio, httpx, starlette, uvicorn, psutil, yaml, rich, pytest, pytest_asyncio, resource_metrics; print('DEPS_OK')"
            if ($LASTEXITCODE -ne 0) { throw "Guest dependency import verification failed" }

            $receiptDir = 'C:\H4-Guest-Work\receipts'
            New-Item -ItemType Directory -Path $receiptDir -Force | Out-Null
            $receiptPath = Join-Path $receiptDir "setup-$opId.json"
            $receipt = [pscustomobject]@{
                schema_version   = 1
                operation_id     = $opId
                bundle_dest      = $destBundle
                bundle_sha256    = $expBundle.ToLowerInvariant()
                bootstrap_sha256 = $expBoot.ToLowerInvariant()
                manifest_path    = "$destBundle\manifest.json"
                pwsh_exe         = $pwshExe
                venv_python      = $venvPy
                verified_at      = (Get-Date).ToString('o')
            }
            $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

            return [pscustomobject]@{
                status         = 'ready'
                pwsh_version   = [string](& $pwshExe --version)
                python_version = [string](& $venvPy --version)
                bundle_dest    = $destBundle
                receipt_path   = $receiptPath
            }
        }
        Save-H4JsonArtifact -Dir $hostEvidenceDir -FileName 'guest-setup.json' -Data $setupRes
        if ($setupRes.status -eq 'reboot_required') {
            $stageResults['Setup'] = 'BLOCKED'
            $summary['error_category'] = 'infrastructure'
            $summary['error'] = 'Guest installer returned exit code 3010 (reboot required). Gracefully restart guest before continuing.'
            $overallExit = 2
            throw $summary['error']
        }

        # Mandatory read-only guest preflight with valid h4-rc-* root
        $preflightRoot = "C:\H4-Guest-Work\runs\h4-rc-preflight-$OperationId"
        $preflightOut = Invoke-H4GuestScript -Session $session -ArgumentList @($guestVenvPy, $guestRunner, $guestSrcNew, $guestSrcOld, $guestManifest, $preflightRoot) -ScriptBlock {
            param($py, $runner, $srcNew, $srcOld, $manifest, $runDir)
            $ErrorActionPreference = 'Stop'
            New-Item -ItemType Directory -Path $runDir -Force | Out-Null
            $mod = Join-Path $srcNew 'modules\resource_coordinator'
            $env:PYTHONPATH = $mod
            $env:PYTHONDONTWRITEBYTECODE = '1'
            Set-Location $mod
            $stdout = & $py -B $runner --test-root $runDir --source-root $srcNew --old-source-root $srcOld --source-manifest $manifest --json 2>&1
            [pscustomobject]@{ exit_code = $LASTEXITCODE; output = ($stdout -join "`n") }
        }
        Save-H4JsonArtifact -Dir $hostEvidenceDir -FileName 'guest-preflight-raw.json' -Data $preflightOut
        $pfParsed = $preflightOut.output | ConvertFrom-Json -ErrorAction Stop
        if ($preflightOut.exit_code -ne 0 -or -not $pfParsed.guest_verified -or $pfParsed.observed_guard_reasons.Count -gt 0) {
            throw "Guest read-only preflight failed (exit=$($preflightOut.exit_code), reasons=$($pfParsed.profile_blockers -join ','))."
        }
        $stageResults['Setup'] = 'PASS'
    }

    # 3. Checkpoint stage (powered-off Standard checkpoint)
    if ($stagesToRun -contains 'Checkpoint') {
        if (-not $AuthorizeGuestMutation) {
            $stageResults['Checkpoint'] = 'BLOCKED'
            $summary['error_category'] = 'authorization'
            $summary['error'] = 'Checkpoint stage requires -AuthorizeGuestMutation to gracefully shut down and checkpoint the H4 guest.'
            $overallExit = 3
            throw $summary['error']
        }
        try {
            $existingCps = @(Get-H4HostCheckpoints -Id $VmId)
            if ($existingCps | Where-Object { $_.Name -eq $CheckpointName }) {
                throw "Checkpoint '$CheckpointName' already exists on VM '$VmName'. Supply a distinct -CheckpointName."
            }
            if ($session) {
                Close-H4GuestSession -Session $session
                $session = $null
            }
            $vmNow = Get-H4HostVm -Id $VmId
            if ($vmNow.State -ne 'Off') {
                Stop-H4HostVm -Id $VmId
                $deadline = (Get-Date).AddMinutes(3)
                do {
                    Start-Sleep -Seconds 2
                    $vmNow = Get-H4HostVm -Id $VmId
                } while ($vmNow.State -ne 'Off' -and (Get-Date) -lt $deadline)
                if ($vmNow.State -ne 'Off') {
                    throw "Guest '$VmName' did not shut down cleanly within timeout (state=$($vmNow.State))."
                }
            }
            $cp = New-H4HostCheckpoint -Id $VmId -SnapshotName $CheckpointName
            if (-not $cp -or $cp.Name -ne $CheckpointName) {
                throw "Checkpoint verification failed for '$CheckpointName'."
            }
            $cpRecord = [pscustomobject]@{
                vm_id         = $VmId
                vm_name       = $VmName
                checkpoint_id = [string]$cp.Id
                name          = $cp.Name
                creation_time = if ($cp.CreationTime) { $cp.CreationTime.ToString('o') } else { (Get-Date).ToString('o') }
            }
            $summary['checkpoint'] = $cpRecord
            Save-H4JsonArtifact -Dir $hostEvidenceDir -FileName 'clean-checkpoint.json' -Data $cpRecord
            $stageResults['Checkpoint'] = 'PASS'

            if ($stagesToRun -contains 'Acceptance') {
                Start-H4HostVm -Id $VmId
                $deadline = (Get-Date).AddMinutes(3)
                do {
                    Start-Sleep -Seconds 3
                    try { $session = Open-H4GuestSession -Id $VmId -Cred $Credential } catch { $session = $null }
                } while (-not $session -and (Get-Date) -lt $deadline)
                if (-not $session) {
                    throw "Failed to re-establish PowerShell Direct session after checkpoint restart."
                }
            }
        } catch {
            if ($stageResults['Checkpoint'] -eq 'NOT_RUN') {
                $stageResults['Checkpoint'] = 'FAIL'
            }
            throw
        }
    }

    # 4. Acceptance matrix stage
    if ($stagesToRun -contains 'Acceptance') {
        if (-not $AuthorizeGuestMutation) {
            $stageResults['Acceptance'] = 'BLOCKED'
            $summary['error_category'] = 'authorization'
            $summary['error'] = 'Acceptance stage requires -AuthorizeGuestMutation.'
            $overallExit = 3
            throw $summary['error']
        }
        if (-not $session) {
            if (-not $Credential) { $Credential = Request-H4GuestCredential -UserHint "$ExpectedGuestHost\mcarls" }
            $session = Open-H4GuestSession -Id $VmId -Cred $Credential
        }

        # Resolve and re-verify the exact setup-receipted bundle for this OperationId
        $resolvedBundle = Invoke-H4GuestScript -Session $session -ArgumentList @($OperationId, $ExpectedBundleSha256, $guestVenvPy) -ScriptBlock {
            param($opId, $expBundle, $pyExe)
            $ErrorActionPreference = 'Stop'
            $receiptPath = "C:\H4-Guest-Work\receipts\setup-$opId.json"
            if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
                throw "Setup receipt not found for OperationId '$opId': $receiptPath. Run -Stage Setup with -OperationId '$opId' first."
            }
            $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json -ErrorAction Stop
            if ($receipt.operation_id -ne $opId) {
                throw "Setup receipt operation_id mismatch: expected '$opId', got '$($receipt.operation_id)'."
            }
            if ([string]$receipt.bundle_sha256 -ne $expBundle.ToLowerInvariant()) {
                throw "Setup receipt bundle_sha256 mismatch: expected '$($expBundle.ToLowerInvariant())', got '$($receipt.bundle_sha256)'."
            }
            $bundleDir = [string]$receipt.bundle_dest
            $manifestFile = Join-Path $bundleDir 'manifest.json'
            $verifyScript = Join-Path $bundleDir 'scripts\Verify-H4GuestBundle.ps1'
            if (-not (Test-Path -LiteralPath $manifestFile -PathType Leaf)) {
                throw "Verified bundle manifest missing at '$manifestFile'."
            }
            if (-not (Test-Path -LiteralPath $verifyScript -PathType Leaf)) {
                throw "Bundle verification script missing at '$verifyScript'."
            }
            $env:PYTHONDONTWRITEBYTECODE = '1'
            $pwshExe = 'C:\Program Files\PowerShell\7\pwsh.exe'
            $verifyOutput = @(& $pwshExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $verifyScript -BundleRoot $bundleDir -Python $pyExe *>&1)
            if ($LASTEXITCODE -ne 0) {
                $detail = ($verifyOutput | ForEach-Object { [string]$_ }) -join "`n"
                throw "Verify-H4GuestBundle.ps1 failed for '$bundleDir' with exit ${LASTEXITCODE}: $detail"
            }
            return [string]$bundleDir
        }
        if ($resolvedBundle -is [array] -or [string]::IsNullOrWhiteSpace([string]$resolvedBundle)) {
            throw "Expected a single verified bundle directory path, got: $($resolvedBundle | ConvertTo-Json -Compress)"
        }
        $guestBundleRoot = [string]$resolvedBundle
        $guestManifest = "$guestBundleRoot\manifest.json"
        $guestSrcNew = "$guestBundleRoot\sources\rc-1.0.0"
        $guestSrcOld = "$guestBundleRoot\sources\rc-0.14.0"
        $guestRunner = "$guestBundleRoot\harness\windows_acceptance.py"

        $suffixPart = if ([string]::IsNullOrWhiteSpace($RunSuffix)) { '' } else { "-$RunSuffix" }
        $phaseSpecs = [System.Collections.Generic.List[object]]::new()
        $phaseSpecs.Add([pscustomobject]@{ name = 'offline'; run_name = "h4-rc-offline-$OperationId$suffixPart"; args = @('--apply', '--profile', 'offline', '--source-root', $guestSrcNew, '--json') })
        $phaseSpecs.Add([pscustomobject]@{ name = 'task'; run_name = "h4-rc-task-$OperationId$suffixPart"; args = @('--apply', '--profile', 'task', '--authorization', $H4AuthorizationPhrase, '--authorize-guest-mutation', '--source-root', $guestSrcNew, '--source-manifest', $guestManifest, '--json') })
        $phaseSpecs.Add([pscustomobject]@{ name = 'full'; run_name = "h4-rc-full-$OperationId$suffixPart"; args = @('--apply', '--profile', 'full', '--authorization', $H4AuthorizationPhrase, '--authorize-guest-mutation', '--source-root', $guestSrcNew, '--old-source-root', $guestSrcOld, '--source-manifest', $guestManifest, '--timeout-seconds', '900', '--json') })
        foreach ($rStage in $RollbackStages) {
            $phaseSpecs.Add([pscustomobject]@{ name = "rollback-$rStage"; run_name = "h4-rc-rb-$rStage-$OperationId$suffixPart"; args = @('--apply', '--profile', 'rollback', '--fault-stage', $rStage, '--authorization', $H4AuthorizationPhrase, '--authorize-guest-mutation', '--source-root', $guestSrcNew, '--old-source-root', $guestSrcOld, '--source-manifest', $guestManifest, '--timeout-seconds', '900', '--json') })
        }

        $profileOutcomes = [System.Collections.Generic.List[object]]::new()
        $matrixFailed = $false
        $evidenceIncomplete = $false
        foreach ($spec in $phaseSpecs) {
            $null = Assert-H4GuestIdentity -Session $session -ExpectedHost $ExpectedGuestHost -RequireCleanRc
            $runDir = "C:\H4-Guest-Work\runs\$($spec.run_name)"
            $res = Invoke-H4GuestScript -Session $session -ArgumentList @($guestVenvPy, $guestRunner, $guestSrcNew, $runDir, $H4AuthorizationPhrase, ($spec.args | ConvertTo-Json -Compress)) -ScriptBlock {
                param($py, $runner, $srcNew, $rDir, $authPhrase, $argsJson)
                $ErrorActionPreference = 'Stop'
                New-Item -ItemType Directory -Path $rDir -Force | Out-Null
                $mod = Join-Path $srcNew 'modules\resource_coordinator'
                $env:PYTHONPATH = $mod
                $env:PYTHONDONTWRITEBYTECODE = '1'
                $env:RC_H4_DISPOSABLE_GUEST_AUTHORIZED = $authPhrase
                Set-Location $mod
                $argList = @($runner, '--test-root', $rDir) + @($argsJson | ConvertFrom-Json)
                $stdout = & $py -B @argList 2>&1
                [pscustomobject]@{ exit_code = $LASTEXITCODE; output = ($stdout -join "`n") }
            }

            $hostPhaseDir = Join-Path $hostEvidenceDir $spec.name
            New-Item -ItemType Directory -Path $hostPhaseDir -Force | Out-Null
            $copyStatus = 'COMPLETE'
            $copyError = $null
            try {
                Copy-H4FromGuest -Session $session -SourcePath "$runDir\*" -Destination $hostPhaseDir
            } catch {
                $copyStatus = 'INCOMPLETE'
                $copyError = $_.Exception.Message
                $evidenceIncomplete = $true
            }

            $parsed = $null
            try { $parsed = $res.output | ConvertFrom-Json -ErrorAction Stop } catch { $parsed = $null }

            $passed = ($res.exit_code -eq 0) -and ($null -ne $parsed) -and ($parsed.status -eq 'passed')
            if ($spec.name -eq 'task' -and $passed -and $parsed.counts -and [int]$parsed.counts.skipped -gt 0) {
                $passed = $false
            }

            $entry = [pscustomobject]@{
                phase                    = $spec.name
                test_root                = $runDir
                exit_code                = $res.exit_code
                status                   = if ($passed) { 'PASS' } else { 'FAIL' }
                evidence_transfer_status = $copyStatus
                evidence_transfer_error  = $copyError
                guest_evidence_path      = $runDir
                retry_hint               = if ($copyStatus -eq 'INCOMPLETE') { "Re-copy guest evidence from '$runDir' on VM '$VmName' to '$hostPhaseDir'." } else { $null }
                parsed                   = $parsed
            }
            $profileOutcomes.Add($entry)
            Save-H4JsonArtifact -Dir $hostEvidenceDir -FileName 'matrix-summary.json' -Data $profileOutcomes

            if (-not $passed) {
                $matrixFailed = $true
                # Controlled scoped cleanup for failed mutating phase (never replaces failure result)
                if ($spec.name -ne 'offline') {
                    $cleanupRes = Invoke-H4GuestScript -Session $session -ArgumentList @($guestVenvPy, $guestRunner, $guestSrcNew, $runDir, $guestManifest, $H4AuthorizationPhrase) -ScriptBlock {
                        param($py, $runner, $srcNew, $rDir, $manifest, $authPhrase)
                        $ErrorActionPreference = 'Continue'
                        $mod = Join-Path $srcNew 'modules\resource_coordinator'
                        $env:PYTHONPATH = $mod
                        $env:PYTHONDONTWRITEBYTECODE = '1'
                        $env:RC_H4_DISPOSABLE_GUEST_AUTHORIZED = $authPhrase
                        Set-Location $mod
                        $out = & $py -B $runner --test-root $rDir --apply --profile cleanup --authorization $authPhrase --authorize-guest-mutation --source-root $srcNew --source-manifest $manifest --json 2>&1
                        [pscustomobject]@{ exit_code = $LASTEXITCODE; output = ($out -join "`n") }
                    }
                    Save-H4JsonArtifact -Dir $hostPhaseDir -FileName 'scoped-cleanup.json' -Data $cleanupRes
                }
                break
            }
            if ($copyStatus -eq 'INCOMPLETE') {
                break
            }
        }

        $summary['profiles'] = $profileOutcomes
        if ($matrixFailed) {
            $stageResults['Acceptance'] = 'FAIL'
            $summary['error_category'] = 'acceptance_test_failure'
            $failedPhase = ($profileOutcomes | Where-Object { $_.status -eq 'FAIL' } | Select-Object -First 1)
            $summary['error'] = "Acceptance matrix stopped at failed phase '$($failedPhase.phase)' (exit=$($failedPhase.exit_code))."
            $overallExit = 1
            throw $summary['error']
        }
        if ($evidenceIncomplete) {
            $stageResults['Acceptance'] = 'INCOMPLETE'
            $summary['error_category'] = 'evidence_transfer_incomplete'
            $incPhase = ($profileOutcomes | Where-Object { $_.evidence_transfer_status -eq 'INCOMPLETE' } | Select-Object -First 1)
            $summary['error'] = "Evidence transfer incomplete for phase '$($incPhase.phase)': $($incPhase.evidence_transfer_error). Guest evidence remains at '$($incPhase.guest_evidence_path)'."
            $overallExit = 5
            throw $summary['error']
        }
        $stageResults['Acceptance'] = 'PASS'
    }
}
catch {
    if (-not $summary['error']) {
        $summary['error_category'] = if ($summary['error_category']) { $summary['error_category'] } else { 'execution_error' }
        $summary['error'] = $_.Exception.Message
    }
    foreach ($k in @($stageResults.Keys)) {
        if ($stageResults[$k] -eq 'NOT_RUN' -and ($stagesToRun -contains $k) -and $k -eq $Stage) {
            $stageResults[$k] = 'FAIL'
        }
    }
    if ($overallExit -eq 0) { $overallExit = 1 }
}
finally {
    Close-H4GuestSession -Session $session
    $summary['stage_results'] = $stageResults
    Save-H4JsonArtifact -Dir $summary['evidence_dir'] -FileName 'final-summary.json' -Data $summary
}

if ($Json) {
    $summary | ConvertTo-Json -Depth 8
} elseif ($overallExit -ne 0) {
    Write-Error $summary['error'] -ErrorAction Continue
} else {
    Write-Host "H4 qualification stage '$Stage' completed cleanly (OperationId=$OperationId)."
}
exit $overallExit
