#Requires -Version 7.0
<#
.SYNOPSIS
    Resumable, gated operational smoke harness for real Hyper-V qualification of vm_lab.
.DESCRIPTION
    Non-default qualification script supporting explicit phases:
      preflight (default, read-only), provision, guest, finalize, full.
    Explicitly refuses RC-H4-Windows-Acceptance (d8483f98-8884-4758-abd1-cd6107c83c03)
    by name or VM ID, refuses unmanaged VMs, and revalidates target identity before
    every mutating step.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory)][string]$VmName,
    [Parameter(Mandatory)][string]$VmRoot,
    [ValidateSet('preflight', 'provision', 'guest', 'finalize', 'full')][string]$Phase = 'preflight',
    [string]$TemplateName = 'windows11-light',
    [string]$IsoPath,
    [pscredential]$Credential,
    [ValidateSet('windows-minimal', 'python-dev', 'powershell-dev')][string]$GuestProfile = 'windows-minimal',
    [string]$ManifestRoot,
    [string]$AcceptanceStatePath,
    [string]$ExpectedVmId,
    [int]$ShutdownTimeoutSeconds = 30,
    [switch]$AuthorizeDisposableTest,
    [switch]$AuthorizeProvision,
    [switch]$AuthorizeGuest,
    [switch]$AuthorizeFinalize,
    [switch]$AuthorizeShutdown,
    [switch]$Start,
    [switch]$Connect,
    [switch]$RunGuestChecks
)

$ErrorActionPreference = 'Stop'

$ProtectedVmIds = @('d8483f98-8884-4758-abd1-cd6107c83c03')
$ProtectedVmNames = @('RC-H4-Windows-Acceptance')

$moduleRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Module -Name vm_lab)) {
    Import-Module (Join-Path $moduleRoot 'vm_lab.psd1') -Force -WarningAction SilentlyContinue
}

$manifestArgs = @{}
if (-not [string]::IsNullOrWhiteSpace($ManifestRoot)) {
    $manifestArgs.ManifestRoot = $ManifestRoot
}

function Assert-SmokeNoReparsePoint {
    param([Parameter(Mandatory)][string]$TargetPath)
    $cur = $TargetPath
    while (-not [string]::IsNullOrWhiteSpace($cur)) {
        if (Test-Path -LiteralPath $cur) {
            $item = Get-Item -LiteralPath $cur -Force -ErrorAction Stop
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "Refusing reparse-point path in operational smoke harness: '$cur'."
            }
        }
        $parent = Split-Path -Parent $cur
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $cur) { break }
        $cur = $parent
    }
}

function Read-SmokeAcceptanceState {
    param([string]$Path)
    Assert-SmokeNoReparsePoint -TargetPath $Path
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop)
    } catch {
        throw "Corrupt acceptance state file '$Path': $($_.Exception.Message)"
    }
}

function Write-SmokeAcceptanceStateAtomic {
    param([string]$Path, [hashtable]$State)
    Assert-SmokeNoReparsePoint -TargetPath $Path
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Assert-SmokeNoReparsePoint -TargetPath $dir
    $tmp = "$Path.tmp.$PID.$([guid]::NewGuid().ToString('N'))"
    try {
        $json = $State | ConvertTo-Json -Depth 10
        [System.IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::Move($tmp, $Path, $true)
    } catch {
        if (Test-Path -LiteralPath $tmp -PathType Leaf) {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

function Assert-VmLabSmokeTargetSafe {
    param(
        [Parameter(Mandatory)][string]$TargetName,
        [ValidateSet('any', 'create', 'resume')][string]$Mode = 'any',
        [string]$PinnedVmId
    )
    if ([string]::IsNullOrWhiteSpace($TargetName)) {
        throw 'Target -VmName is required.'
    }
    if ($ProtectedVmNames -contains $TargetName) {
        throw "Refusing operational smoke test against protected VM name '$TargetName'."
    }

    $allVms = @(Get-VmLabList @manifestArgs)
    $byName = @($allVms | Where-Object { $_.name -eq $TargetName })
    if ($byName.Count -gt 1) {
        throw "Multiple Hyper-V VMs matched name '$TargetName'."
    }
    $targetSummary = if ($byName.Count -eq 1) { $byName[0] } else { $null }

    if ($null -ne $targetSummary) {
        $resolvedId = ([string]$targetSummary.id).ToLowerInvariant()
        if ($ProtectedVmIds -contains $resolvedId) {
            throw "Refusing operational smoke test against protected VM ID '$resolvedId' (name='$($targetSummary.name)')."
        }
        if ($Mode -eq 'create') {
            throw "VM '$TargetName' already exists (Id=$resolvedId). Refusing to overwrite existing VM in provision mode."
        }
        $vmStatus = Get-VmLabStatus -Name $TargetName @manifestArgs
        if (-not $vmStatus.owned) {
            throw "Refusing unmanaged target VM '$TargetName' ($($vmStatus.ownership_reason))."
        }
        if ($vmStatus.manifest -and [string]$vmStatus.manifest.vm_id -and ([string]$vmStatus.manifest.vm_id).ToLowerInvariant() -ne $resolvedId) {
            throw "Target VM '$TargetName' identity mismatch: manifest=$($vmStatus.manifest.vm_id), hyperv=$resolvedId."
        }
        if (-not [string]::IsNullOrWhiteSpace($PinnedVmId) -and $PinnedVmId.ToLowerInvariant() -ne $resolvedId) {
            throw "Target VM '$TargetName' identity changed: expected=$PinnedVmId, actual=$resolvedId."
        }
        return [pscustomobject]@{
            exists = $true
            vm     = [pscustomobject]@{ Name = $vmStatus.name; Id = $vmStatus.id; State = $vmStatus.state }
            vm_id  = $resolvedId
            status = $vmStatus
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($PinnedVmId)) {
        $pinnedLower = $PinnedVmId.ToLowerInvariant()
        if ($ProtectedVmIds -contains $pinnedLower) {
            throw "Refusing protected VM ID '$pinnedLower'."
        }
        $byId = @($allVms | Where-Object { ([string]$_.id).ToLowerInvariant() -eq $pinnedLower })
        if ($byId.Count -gt 0) {
            throw "Pinned VM ID '$pinnedLower' exists under different name '$($byId[0].name)' instead of '$TargetName'."
        }
    }

    if ($Mode -eq 'resume') {
        throw "Cannot resume against '$TargetName': VM is not registered in Hyper-V."
    }

    return [pscustomobject]@{
        exists = $false
        vm     = $null
        vm_id  = $null
        status = $null
    }
}

function Emit-SmokeResult {
    param(
        [string]$Status,
        [string]$ReasonCode,
        [int]$ExitCode,
        [string]$TargetName,
        [string]$TargetId,
        [hashtable]$Phases,
        [string]$Detail
    )
    $out = [pscustomobject]@{
        status                = $Status
        reason_code           = $ReasonCode
        exit_code             = $ExitCode
        phase                 = $Phase
        vm_name               = $TargetName
        vm_id                 = $TargetId
        vm_root               = $VmRoot
        acceptance_state_path = $AcceptanceStatePath
        detail                = $Detail
        phases                = $Phases
    }
    $out | ConvertTo-Json -Depth 10
    exit $ExitCode
}

$phases = [ordered]@{}
$pinnedId = if (-not [string]::IsNullOrWhiteSpace($ExpectedVmId)) { $ExpectedVmId } else { $null }

$saveState = {
    param([string]$VmIdVal, [bool]$WinPending, [string]$LastStatus, [string]$LastReason)
    $stateObj = [ordered]@{
        schema_version               = 1
        vm_name                      = $VmName
        vm_id                        = $VmIdVal
        vm_root                      = $VmRoot
        template_name                = $TemplateName
        windows_installation_pending = $WinPending
        last_status                  = $LastStatus
        last_reason_code             = $LastReason
        updated_at                   = [DateTimeOffset]::UtcNow.ToString('o')
        phases                       = $phases
    }
    Write-SmokeAcceptanceStateAtomic -Path $AcceptanceStatePath -State $stateObj
}

try {
    $vmRootFull = [System.IO.Path]::GetFullPath($VmRoot).TrimEnd('\', '/')
    if ($vmRootFull -match '^\\\\') {
        throw "UNC paths are not allowed for -VmRoot: '$VmRoot'."
    }
    if ([string]::IsNullOrWhiteSpace($AcceptanceStatePath)) {
        $AcceptanceStatePath = Join-Path $vmRootFull 'acceptance-state.json'
    } else {
        $AcceptanceStatePath = [System.IO.Path]::GetFullPath($AcceptanceStatePath)
        $prefix = $vmRootFull + [System.IO.Path]::DirectorySeparatorChar
        if (-not $AcceptanceStatePath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "AcceptanceStatePath '$AcceptanceStatePath' must reside within VmRoot '$vmRootFull'."
        }
    }

    $existingState = Read-SmokeAcceptanceState -Path $AcceptanceStatePath
    if ($null -ne $existingState) {
        if ($existingState.vm_name -and [string]$existingState.vm_name -ne $VmName) {
            throw "Acceptance state '$AcceptanceStatePath' belongs to VM '$($existingState.vm_name)', not '$VmName'."
        }
        if ($existingState.vm_root) {
            $stateRootNorm = [System.IO.Path]::GetFullPath([string]$existingState.vm_root).TrimEnd('\', '/')
            if (-not $stateRootNorm.Equals($vmRootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Acceptance state '$AcceptanceStatePath' belongs to VmRoot '$stateRootNorm', not '$vmRootFull'."
            }
        }
        if ($existingState.vm_id -and -not [string]::IsNullOrWhiteSpace($ExpectedVmId) -and ([string]$existingState.vm_id).ToLowerInvariant() -ne $ExpectedVmId.ToLowerInvariant()) {
            throw "Acceptance state '$AcceptanceStatePath' VM ID '$($existingState.vm_id)' conflicts with -ExpectedVmId '$ExpectedVmId'."
        }
        if ($existingState.phases) {
            foreach ($p in $existingState.phases.PSObject.Properties) {
                $phases[$p.Name] = $p.Value
            }
        }
        if ([string]::IsNullOrWhiteSpace($pinnedId) -and $existingState.vm_id) {
            $pinnedId = [string]$existingState.vm_id
        }
    }

    $preCheck = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'any' -PinnedVmId $pinnedId
    $cfg = Get-VmLabTemplate -TemplateName $TemplateName
    $cfg.vm_name = $VmName
    $cfg.vm_root = $VmRoot
    if (-not [string]::IsNullOrWhiteSpace($IsoPath)) {
        $cfg.iso_path = $IsoPath
    }

    if ($preCheck.exists) {
        $preStatus = Get-VmLabStatus -Name $VmName @manifestArgs
        $phases.preflight = [ordered]@{
            status      = 'passed'
            target_mode = 'existing_owned'
            vm_id       = $preCheck.vm_id
            vm_state    = [string]$preCheck.vm.State
            vm_status   = $preStatus
        }
        if (-not $pinnedId) { $pinnedId = $preCheck.vm_id }
    } else {
        $planRes = Test-VmLabPlan -Config $cfg @manifestArgs
        $phases.preflight = [ordered]@{
            status      = 'passed'
            target_mode = 'new_disposable'
            plan        = $planRes
        }
    }

    if ($Phase -eq 'preflight') {
        Emit-SmokeResult -Status 'preflight_passed' -ReasonCode 'preflight_ok' -ExitCode 0 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Read-only preflight passed.'
    }

    if (-not $AuthorizeDisposableTest) {
        Emit-SmokeResult -Status 'blocked' -ReasonCode 'authorization_required' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail "Mutating phase '$Phase' requires -AuthorizeDisposableTest."
    }
    if ($WhatIfPreference -or -not $PSCmdlet.ShouldProcess($VmName, "Execute vm_lab operational smoke phase '$Phase'")) {
        Emit-SmokeResult -Status 'blocked' -ReasonCode 'whatif_dry_run' -ExitCode 0 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Dry-run / -WhatIf prevented Hyper-V mutations.'
    }

    $runProvision = ($Phase -eq 'provision') -or ($Phase -eq 'full' -and -not $preCheck.exists)
    if ($runProvision) {
        if (-not $AuthorizeProvision) {
            Emit-SmokeResult -Status 'blocked' -ReasonCode 'phase_authorization_required' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Provision phase requires explicit -AuthorizeProvision.'
        }
        $null = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'create'
        $createRes = New-VmLabMachine -Config $cfg -Apply @manifestArgs
        $pinnedId = [string]$createRes.vm_id

        $startRes = $null
        if ($Start) {
            $null = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'resume' -PinnedVmId $pinnedId
            $startRes = Start-VmLabMachine -Name $VmName -Apply @manifestArgs
        }
        $connectRes = $null
        if ($Connect -and (Test-VmLabInteractiveDesktop)) {
            $null = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'resume' -PinnedVmId $pinnedId
            $connectRes = Connect-VmLabMachine -Name $VmName @manifestArgs
        }
        $phases.provision = [ordered]@{
            status  = 'provisioned'
            vm_id   = $pinnedId
            create  = $createRes
            start   = $startRes
            connect = $connectRes
        }
        & $saveState $pinnedId $true 'awaiting_windows_installation' 'windows_installation_pending'
        Emit-SmokeResult -Status 'awaiting_windows_installation' -ReasonCode 'windows_installation_pending' -ExitCode 0 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Disposable VM provisioned. Install Windows/complete OOBE, then resume with -Phase guest.'
    }

    $runGuest = ($Phase -eq 'guest') -or ($Phase -eq 'full' -and $preCheck.exists)
    if ($runGuest) {
        if (-not $AuthorizeGuest) {
            Emit-SmokeResult -Status 'blocked' -ReasonCode 'phase_authorization_required' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Guest phase requires explicit -AuthorizeGuest.'
        }
        $target = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'resume' -PinnedVmId $pinnedId
        $pinnedId = $target.vm_id
        if ([string]$target.vm.State -ne 'Running') {
            $phases.guest = [ordered]@{ status = 'blocked'; reason_code = 'vm_not_running'; vm_state = [string]$target.vm.State }
            & $saveState $pinnedId $false 'blocked' 'vm_not_running'
            Emit-SmokeResult -Status 'blocked' -ReasonCode 'vm_not_running' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail "VM '$VmName' must be Running before guest acceptance (state=$($target.vm.State))."
        }

        $gs = Get-VmLabGuestStatus -Name $VmName -Credential $Credential @manifestArgs
        if ($gs.guest_state -eq 'ps_direct_auth_unavailable') {
            $phases.guest = [ordered]@{ status = 'awaiting_guest_credentials'; guest_status = $gs }
            & $saveState $pinnedId $false 'awaiting_guest_credentials' 'credentials_required'
            Emit-SmokeResult -Status 'awaiting_guest_credentials' -ReasonCode 'credentials_required' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Guest credentials (-Credential) are required for PowerShell Direct checks.'
        }
        if ($gs.guest_state -eq 'windows_booted_account_unavailable') {
            $phases.guest = [ordered]@{ status = 'awaiting_windows_installation'; guest_status = $gs }
            & $saveState $pinnedId $true 'awaiting_windows_installation' 'oobe_or_account_unavailable'
            Emit-SmokeResult -Status 'awaiting_windows_installation' -ReasonCode 'oobe_or_account_unavailable' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Windows OOBE / local guest account is not ready.'
        }
        if ($gs.guest_state -eq 'ps_direct_auth_failed') {
            $phases.guest = [ordered]@{ status = 'failed'; reason_code = 'ps_direct_auth_failed'; guest_status = $gs }
            & $saveState $pinnedId $false 'acceptance_failed' 'ps_direct_auth_failed'
            Emit-SmokeResult -Status 'acceptance_failed' -ReasonCode 'ps_direct_auth_failed' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'PowerShell Direct authentication failed.'
        }
        if (-not $gs.ps_direct_available) {
            $phases.guest = [ordered]@{ status = 'blocked'; reason_code = $gs.guest_state; guest_status = $gs }
            & $saveState $pinnedId $true 'blocked' $gs.guest_state
            Emit-SmokeResult -Status 'blocked' -ReasonCode $gs.guest_state -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail "Guest is not ready for PowerShell Direct ($($gs.guest_state))."
        }

        $null = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'resume' -PinnedVmId $pinnedId
        $bsRes = Invoke-VmLabGuestBootstrap -Name $VmName -Profile $GuestProfile -Credential $Credential -Apply @manifestArgs
        if ($bsRes.status -ne 'bootstrapped') {
            $phases.guest = [ordered]@{ status = 'failed'; reason_code = 'guest_bootstrap_failed'; bootstrap = $bsRes }
            & $saveState $pinnedId $false 'acceptance_failed' 'guest_bootstrap_failed'
            Emit-SmokeResult -Status 'acceptance_failed' -ReasonCode 'guest_bootstrap_failed' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail "Guest bootstrap did not complete (status=$($bsRes.status))."
        }

        $gvRes = Test-VmLabGuestVerify -Name $VmName -Profile $GuestProfile -Credential $Credential @manifestArgs
        if ($gvRes.status -ne 'verified') {
            $phases.guest = [ordered]@{ status = 'failed'; reason_code = 'guest_verify_failed'; bootstrap = $bsRes; verify = $gvRes }
            & $saveState $pinnedId $false 'acceptance_failed' 'guest_verify_failed'
            Emit-SmokeResult -Status 'acceptance_failed' -ReasonCode 'guest_verify_failed' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail "Guest verification failed ($($gvRes.status))."
        }

        $null = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'resume' -PinnedVmId $pinnedId
        $smokeDir = Join-Path $VmRoot 'smoke_transfer'
        if (-not (Test-Path -LiteralPath $smokeDir)) { New-Item -ItemType Directory -Path $smokeDir -Force | Out-Null }
        $probeLocalIn = Join-Path $smokeDir 'smoke_probe_in.txt'
        $probeLocalOut = Join-Path $smokeDir 'smoke_probe_out.txt'
        $probeGuest = 'C:\ProgramData\vm_lab\smoke_probe.txt'
        [System.IO.File]::WriteAllText($probeLocalIn, "vm-lab-smoke-$pinnedId")
        $copyTo = Copy-VmLabGuestItem -Name $VmName -SourcePath $probeLocalIn -DestinationPath $probeGuest -Direction ToGuest -Credential $Credential -Overwrite -Apply @manifestArgs
        $copyFrom = Copy-VmLabGuestItem -Name $VmName -SourcePath $probeGuest -DestinationPath $probeLocalOut -Direction FromGuest -Credential $Credential -Overwrite -Apply @manifestArgs

        $null = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'resume' -PinnedVmId $pinnedId
        $cpRes = New-VmLabBaselineCheckpoint -Name $VmName -CheckpointName 'acceptance-baseline' -RequireGuestVerified -GuestProfile $GuestProfile -Credential $Credential -Apply @manifestArgs
        if ($cpRes.status -ne 'baseline_created' -or -not $cpRes.baseline_qualified) {
            $phases.guest = [ordered]@{ status = 'failed'; reason_code = 'baseline_checkpoint_failed'; checkpoint = $cpRes }
            & $saveState $pinnedId $false 'acceptance_failed' 'baseline_checkpoint_failed'
            Emit-SmokeResult -Status 'acceptance_failed' -ReasonCode 'baseline_checkpoint_failed' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail "Qualified baseline checkpoint was not created (status=$($cpRes.status), baseline_qualified=$($cpRes.baseline_qualified))."
        }

        $phases.guest = [ordered]@{
            status       = 'guest_ready'
            guest_status = $gs
            bootstrap    = $bsRes
            verify       = $gvRes
            copy_to      = $copyTo
            copy_from    = $copyFrom
            baseline     = $cpRes
        }
        & $saveState $pinnedId $false 'guest_ready' 'guest_checks_passed'

        if ($Phase -eq 'guest') {
            Emit-SmokeResult -Status 'guest_ready' -ReasonCode 'guest_checks_passed' -ExitCode 0 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Guest readiness, bootstrap, verification, round-trip transfer, and qualified baseline passed.'
        }
    }

    if ($Phase -eq 'finalize' -or $Phase -eq 'full') {
        if (-not $AuthorizeFinalize) {
            Emit-SmokeResult -Status 'blocked' -ReasonCode 'phase_authorization_required' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Finalize phase requires explicit -AuthorizeFinalize.'
        }
        $target = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'resume' -PinnedVmId $pinnedId
        $pinnedId = $target.vm_id

        if (-not $phases.Contains('guest') -or $phases.guest.status -ne 'guest_ready') {
            $phases.finalize = [ordered]@{ status = 'failed'; reason_code = 'guest_acceptance_incomplete' }
            & $saveState $pinnedId $false 'acceptance_failed' 'guest_acceptance_incomplete'
            Emit-SmokeResult -Status 'acceptance_failed' -ReasonCode 'guest_acceptance_incomplete' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail 'Cannot finalize acceptance before guest acceptance phase passes.'
        }

        $stopRes = $null
        $shutdownStatus = 'skipped_not_authorized'
        if ($AuthorizeShutdown) {
            $null = Assert-VmLabSmokeTargetSafe -TargetName $VmName -Mode 'resume' -PinnedVmId $pinnedId
            $stopRes = Stop-VmLabMachine -Name $VmName -ShutdownTimeoutSeconds $ShutdownTimeoutSeconds -Apply @manifestArgs
            if ($stopRes.status -in @('stopped', 'already_stopped')) {
                $shutdownStatus = 'shutdown_confirmed'
            } else {
                $shutdownStatus = 'shutdown_requested_unconfirmed'
            }
        }

        $finalStatus = if ($shutdownStatus -eq 'shutdown_requested_unconfirmed') { 'partial' } else { 'acceptance_passed' }
        $finalReason = if ($shutdownStatus -eq 'shutdown_requested_unconfirmed') { 'shutdown_not_confirmed' } else { 'all_checks_passed' }
        $finalExit = if ($finalStatus -eq 'acceptance_passed') { 0 } else { 1 }

        $phases.finalize = [ordered]@{
            status          = $finalStatus
            shutdown_status = $shutdownStatus
            stop            = $stopRes
        }
        & $saveState $pinnedId $false $finalStatus $finalReason
        Emit-SmokeResult -Status $finalStatus -ReasonCode $finalReason -ExitCode $finalExit -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail "Finalization completed with shutdown_status=$shutdownStatus."
    }
} catch {
    $msg = $_.Exception.Message
    Emit-SmokeResult -Status 'acceptance_failed' -ReasonCode 'unhandled_error' -ExitCode 1 -TargetName $VmName -TargetId $pinnedId -Phases $phases -Detail $msg
}
