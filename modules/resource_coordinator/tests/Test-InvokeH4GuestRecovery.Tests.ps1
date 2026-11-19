#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

$scriptPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\tools\h4_qualification\Invoke-H4GuestRecovery.ps1'))

Describe 'Invoke-H4GuestRecovery.ps1' {
    $testTemp = Join-Path $PSScriptRoot '..\.pytest_tmp_root\pester_h4_rec'
    if (Test-Path -LiteralPath $testTemp) {
        Remove-Item -LiteralPath $testTemp -Recurse -Force
    }
    New-Item -ItemType Directory -Path $testTemp -Force | Out-Null

    $bundleZip = Join-Path $testTemp 'bundle.zip'
    Set-Content -LiteralPath $bundleZip -Value 'bundle-v9-bytes' -NoNewline
    $bundleSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundleZip).Hash

    $bootstrapPs1 = Join-Path $testTemp 'Bootstrap-H4GuestBundle.ps1'
    Set-Content -LiteralPath $bootstrapPs1 -Value '# bootstrap' -NoNewline
    $bootstrapSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $bootstrapPs1).Hash

    $srcSha = '27764f44b7311072b62b0dbf8d8faa96260f3deb8a0f09bf0bef969368599989'
    $runId = '9ea7312c8c'
    $guestRoot = 'C:\H4-Guest-Work\runs\h4-rc-install-v8-install-20261115-194217-a283bd'
    $phaseRoot = "$guestRoot\runs\$runId-install"
    $taskBoot = "ResourceCoordinator-H4-$runId-install-boot"
    $taskLogon = "ResourceCoordinator-H4-$runId-install-logon"
    $taskViewer = "ResourceCoordinator-H4-$runId-install-viewer"

    $hostManifestPath = Join-Path $testTemp 'host-cleanup-manifest.json'
    @{
        schema_version = 1
        phases = @(
            @{
                schema_version     = 1
                run_id             = $runId
                phase              = 'install'
                port               = 49694
                root               = $phaseRoot
                source_tree_sha256 = $srcSha
                task_names         = @($taskBoot, $taskLogon, $taskViewer)
            }
        )
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $hostManifestPath -Encoding UTF8

    function Get-H4HostVm { param([string]$Id) }
    function Get-H4HostCheckpoints { param([string]$Id) }
    function Open-H4GuestSession { param([string]$Id, [pscredential]$Cred) }
    function Close-H4GuestSession { param($Session) }
    function Invoke-H4GuestScript { param($Session, [scriptblock]$ScriptBlock, [object[]]$ArgumentList) }
    function Copy-H4ToGuest { param($Session, [string]$SourcePath, [string]$DestinationPath) }
    function Copy-H4FromGuest { param($Session, [string]$SourcePath, [string]$DestinationPath) }
    function Request-H4GuestCredential { param([string]$UserHint) }

    function Initialize-RecoveryMocks {
        param(
            [string]$VmState = 'Running',
            [switch]$MissingCheckpoint,
            [string]$GuestHostname = 'DESKTOP-1ITSJV0',
            [switch]$MissingMarker,
            [switch]$MissingManifest,
            [string]$ManifestRunId = $runId,
            [string]$ManifestSourceSha = $srcSha,
            [string]$TaskAction = "$phaseRoot\start-coordinator-managed.ps1",
            [switch]$UnexpectedTask,
            [switch]$LiveService,
            [switch]$LiveProcess,
            [switch]$LiveListener,
            [switch]$BundleNotStaged,
            [switch]$DryRunFail,
            [switch]$ApplyFail,
            [switch]$PhaseRootMissingAfterApply,
            [switch]$TasksCleanInitially,
            [switch]$ExistingInvalidBundle,
            [int]$BootstrapFailExitCode = 0
        )
        $Global:rEvents = [System.Collections.Generic.List[string]]::new()
        $Global:rPyCalls = [System.Collections.Generic.List[object]]::new()
        $Global:rVmState = $VmState
        $Global:rTaskPresent = -not [bool]$TasksCleanInitially
        $Global:rLauncherPresent = -not [bool]$TasksCleanInitially
        $Global:rPhaseRootExists = $true
        $Global:rRecoveryApplied = $false
        $Global:rBundleReady = -not [bool]$BundleNotStaged
        $Global:rExistingInvalidBundle = [bool]$ExistingInvalidBundle
        $Global:rBootstrapFailExitCode = $BootstrapFailExitCode
        $Global:rGuestHostname = $GuestHostname
        $Global:rMissingMarker = [bool]$MissingMarker
        $Global:rMissingManifest = [bool]$MissingManifest
        $Global:rManifestRunId = $ManifestRunId
        $Global:rManifestSourceSha = $ManifestSourceSha
        $Global:rTaskAction = $TaskAction
        $Global:rUnexpectedTask = [bool]$UnexpectedTask
        $Global:rLiveService = [bool]$LiveService
        $Global:rLiveProcess = [bool]$LiveProcess
        $Global:rLiveListener = [bool]$LiveListener
        $Global:rDryRunFail = [bool]$DryRunFail
        $Global:rApplyFail = [bool]$ApplyFail
        $Global:rPhaseRootMissingAfterApply = [bool]$PhaseRootMissingAfterApply
        $Global:rRunId = $runId
        $Global:rGuestRoot = $guestRoot
        $Global:rPhaseRoot = $phaseRoot
        $Global:rTaskBoot = $taskBoot
        $Global:rTaskLogon = $taskLogon
        $Global:rTaskViewer = $taskViewer
        $Global:rSecCred = [pscredential]::new('DESKTOP-1ITSJV0\mcarls', (ConvertTo-SecureString 'DummyPass!123' -AsPlainText -Force))

        Mock Request-H4GuestCredential { return $Global:rSecCred }
        Mock Get-H4HostVm {
            param($Id)
            if ($Id -ne 'd8483f98-8884-4758-abd1-cd6107c83c03') { return $null }
            return [pscustomobject]@{
                Id    = [guid]'d8483f98-8884-4758-abd1-cd6107c83c03'
                Name  = 'RC-H4-Windows-Acceptance'
                State = $Global:rVmState
            }
        }
        if ($MissingCheckpoint) {
            Mock Get-H4HostCheckpoints { return @([pscustomobject]@{ Id = [guid]'11111111-1111-1111-1111-111111111111'; Name = 'other' }) }
        } else {
            Mock Get-H4HostCheckpoints { return @([pscustomobject]@{ Id = [guid]'9f45b469-382c-4be0-a50e-7a71384c7922'; Name = 'baseline' }) }
        }
        Mock Open-H4GuestSession { return [pscustomobject]@{ Id = 7; ComputerName = 'RC-H4-Windows-Acceptance' } }
        Mock Close-H4GuestSession { $Global:rEvents.Add('CloseSession') }
        Mock Copy-H4ToGuest {
            param($Session, $SourcePath, $DestinationPath)
            $Global:rEvents.Add("CopyTo:$DestinationPath")
        }
        Mock Copy-H4FromGuest {
            param($Session, $SourcePath, $DestinationPath)
            $Global:rEvents.Add("CopyFrom:$SourcePath->$DestinationPath")
        }

        Mock Invoke-H4GuestScript {
            param($Session, $ScriptBlock, $ArgumentList)
            $text = $ScriptBlock.ToString()
            if ($text -match 'Win32_ComputerSystem' -and $text -match 'manifestObj') {
                $rcTasks = [System.Collections.Generic.List[object]]::new()
                if ($Global:rTaskPresent) {
                    $rcTasks.Add([pscustomobject]@{ name = $Global:rTaskLogon; state = 'Disabled'; enabled = $false; actions = "pwsh.exe -File $($Global:rTaskAction)" })
                }
                if ($Global:rUnexpectedTask) {
                    $rcTasks.Add([pscustomobject]@{ name = 'ResourceCoordinator-Prod-Main'; state = 'Ready'; enabled = $true; actions = 'C:\Prod\run.ps1' })
                }
                $svcs = if ($Global:rLiveService) { @([pscustomobject]@{ name = 'ResourceCoordinator'; status = 'Running' }) } else { @() }
                $procs = if ($Global:rLiveProcess) { @([pscustomobject]@{ name = 'python.exe'; pid = 4444 }) } else { @() }
                $listeners = if ($Global:rLiveListener) { @([pscustomobject]@{ port = 49694; local_address = '127.0.0.1'; pid = 4444 }) } else { @() }
                return [pscustomobject]@{
                    hostname               = $Global:rGuestHostname
                    user                   = 'DESKTOP-1ITSJV0\mcarls'
                    is_admin               = $true
                    manufacturer           = 'Microsoft Corporation'
                    model                  = 'Virtual Machine'
                    hypervisor_present     = $true
                    os_caption             = 'Microsoft Windows 11 Pro'
                    os_version             = '10.0.26300'
                    os_build               = '26300'
                    test_root              = $Global:rGuestRoot
                    test_root_exists       = $true
                    test_root_has_reparse  = $false
                    marker_exists          = (-not $Global:rMissingMarker)
                    marker_root_id         = "$($Global:rRunId)aabbccddee"
                    manifest_exists        = (-not $Global:rMissingManifest)
                    manifest_schema        = 1
                    phases                 = @(
                        [pscustomobject]@{
                            phase              = 'install'
                            run_id             = $Global:rManifestRunId
                            port               = 49694
                            root               = $Global:rPhaseRoot
                            source_tree_sha256 = $Global:rManifestSourceSha
                            task_names         = @($Global:rTaskBoot, $Global:rTaskLogon, $Global:rTaskViewer)
                            root_exists        = $Global:rPhaseRootExists
                            file_count         = 4
                            launcher_exists    = $Global:rLauncherPresent
                            viewer_exists      = $false
                        }
                    )
                    manifest_tasks         = @($Global:rTaskBoot, $Global:rTaskLogon, $Global:rTaskViewer)
                    rc_tasks               = @($rcTasks)
                    rc_services            = $svcs
                    rc_processes           = $procs
                    listeners              = $listeners
                    recovery_result_exists = $Global:rRecoveryApplied
                    recovery_result_status = if ($Global:rRecoveryApplied) { 'applied' } else { $null }
                    test_results_preserved = $true
                }
            }
            if ($text -match 'Verify-H4GuestBundle\.ps1' -and $text -match 'recovery_root_identity_mismatch') {
                if ($Global:rExistingInvalidBundle) {
                    return [pscustomobject]@{ exists = $true; ready = $false; exit_code = 2; reason = "Existing recovery bundle uses stale tooling commit '005293bf8651fe81edc297f6c500e822d4c1ed9d'" }
                }
                if ($Global:rBundleReady) {
                    return [pscustomobject]@{ exists = $true; ready = $true; exit_code = 0; tooling_commit = '1b71f5c4cfa0ea6c09a9d0f294400c26d7415960'; reason = 'verified' }
                }
                return [pscustomobject]@{ exists = $false; ready = $false; exit_code = 2; reason = 'Recovery bundle not staged' }
            }
            if ($text -match 'Bootstrap-H4GuestBundle\.ps1' -and $text -match '-IntegrityOnly') {
                $Global:rEvents.Add('StageRecoveryBundle:-IntegrityOnly')
                if ($Global:rBootstrapFailExitCode -ne 0) {
                    return [pscustomobject]@{ status = 'bootstrap_failed'; exit_code = $Global:rBootstrapFailExitCode; output = "Simulated bootstrap failure ($($Global:rBootstrapFailExitCode))" }
                }
                $Global:rBundleReady = $true
                return [pscustomobject]@{ status = 'staged_and_verified'; exit_code = 0; tooling_commit = '1b71f5c4cfa0ea6c09a9d0f294400c26d7415960'; output = '{"verified":true}' }
            }
            if ($text -match 'RC_H4_DISPOSABLE_GUEST_AUTHORIZED') {
                $argsArr = @($ArgumentList[2] | ConvertFrom-Json)
                $hasApply = ($argsArr -contains '--apply')
                $hasAuth = ($ArgumentList.Count -ge 4 -and $ArgumentList[3] -eq 'I AUTHORIZE DISPOSABLE H4 WINDOWS MUTATION')
                $Global:rPyCalls.Add([pscustomobject]@{
                    apply = $hasApply
                    auth  = $hasAuth
                    args  = ($argsArr -join ' ')
                })
                if (-not $hasApply) {
                    if ($Global:rDryRunFail) {
                        return [pscustomobject]@{ exit_code = 4; output = '{"status":"failed","reason_code":"recovery_source_mismatch"}' }
                    }
                    return [pscustomobject]@{ exit_code = 0; output = '{"profile":"recover","status":"planned","phases":[]}' }
                }
                if ($Global:rApplyFail) {
                    return [pscustomobject]@{ exit_code = 4; output = '{"status":"failed","reason_code":"recovery_tasks_remain"}' }
                }
                $Global:rTaskPresent = $false
                $Global:rLauncherPresent = $false
                $Global:rRecoveryApplied = $true
                if ($Global:rPhaseRootMissingAfterApply) { $Global:rPhaseRootExists = $false }
                return [pscustomobject]@{ exit_code = 0; output = '{"profile":"recover","status":"applied","evidence_preserved":true,"phases":[]}' }
            }
            return $null
        }
    }

    function Invoke-Rec {
        param([hashtable]$Extra = @{})
        $evDir = Join-Path $testTemp ('rec_ev_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        $base = @{
            BundleZip               = $bundleZip
            ExpectedBundleSha256    = $bundleSha
            BootstrapScript         = $bootstrapPs1
            ExpectedBootstrapSha256 = $bootstrapSha
            HostCleanupManifest     = $hostManifestPath
            EvidenceRoot            = $evDir
            OperationId             = 'rec01'
            Json                    = $true
        }
        foreach ($k in $Extra.Keys) { $base[$k] = $Extra[$k] }
        $out = & $scriptPath @base *>&1
        return [pscustomobject]@{
            ExitCode    = $LASTEXITCODE
            Output      = ($out -join "`n")
            EvidenceDir = Join-Path $evDir $base.OperationId
        }
    }

    It 'parses cleanly with zero PowerShell syntax errors' {
        $tokens = $null; $errors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
        @($errors).Count | Should Be 0
    }

    It 'constructs exact Python dry-run and apply --profile recover commands without invoking qualification orchestrator' {
        $raw = Get-Content -LiteralPath $scriptPath -Raw
        $ast = [System.Management.Automation.Language.Parser]::ParseInput($raw, [ref]$null, [ref]$null)
        $fn = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-H4RecoveryCommandSpec' }, $true)
        . ([scriptblock]::Create($fn.Extent.Text))

        $dry = Get-H4RecoveryCommandSpec -PythonExe 'C:\H4-Guest-Work\venv\Scripts\python.exe' -BundleRoot 'C:\B' -TestRoot $guestRoot
        $dry.apply | Should Be $false
        ($dry.arguments -contains '--profile') | Should Be $true
        ($dry.arguments -contains 'recover') | Should Be $true
        ($dry.arguments -contains '--apply') | Should Be $false
        ($dry.arguments -contains '--source-manifest') | Should Be $true

        $applySpec = Get-H4RecoveryCommandSpec -PythonExe 'C:\H4-Guest-Work\venv\Scripts\python.exe' -BundleRoot 'C:\B' -TestRoot $guestRoot -ApplyMutation
        $applySpec.apply | Should Be $true
        ($applySpec.arguments -contains '--apply') | Should Be $true
        ($applySpec.arguments -contains '--authorize-guest-mutation') | Should Be $true
        ($applySpec.arguments -contains '--authorization') | Should Be $true
    }

    It 'defaults to read-only --profile recover dry-run with zero host or guest writes' {
        Initialize-RecoveryMocks
        $r = Invoke-Rec
        $r.ExitCode | Should Be 0
        $j = $r.Output | ConvertFrom-Json
        $j.mode | Should Be 'dry_run'
        $j.python_status | Should Be 'planned'
        $j.evidence_dir | Should Be $null
        $Global:rPyCalls.Count | Should Be 1
        $Global:rPyCalls[0].apply | Should Be $false
        $Global:rTaskPresent | Should Be $true
        $Global:rLauncherPresent | Should Be $true
    }

    It 'enforces separate -AuthorizeGuestMutation and honors -WhatIf on recovery apply' {
        Initialize-RecoveryMocks
        $rNoAuth = Invoke-Rec -Extra @{ Apply = $true }
        $rNoAuth.ExitCode | Should Be 3
        ($rNoAuth.Output | ConvertFrom-Json).error_category | Should Be 'authorization'
        $Global:rPyCalls.Count | Should Be 0

        $rWhatIf = Invoke-Rec -Extra @{ Apply = $true; AuthorizeGuestMutation = $true; WhatIf = $true }
        $rWhatIf.ExitCode | Should Be 0
        ($rWhatIf.Output | ConvertFrom-Json).python_status | Should Be 'planned'
        $Global:rPyCalls.Count | Should Be 1
        $Global:rPyCalls[0].apply | Should Be $false
        $Global:rTaskPresent | Should Be $true
    }

    It 'rejects wrong VM, missing protected checkpoint, bad source digest, missing manifests, unowned/unexpected tasks, and live RC services/processes/listeners' {
        Initialize-RecoveryMocks -MissingCheckpoint
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -VmState 'Off'
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -GuestHostname 'XERES'
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -MissingMarker
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -MissingManifest
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -ManifestRunId 'deadbeef00'
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -ManifestSourceSha ('0' * 64)
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -UnexpectedTask
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -TaskAction 'C:\Foreign\evil.ps1'
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -LiveService
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -LiveProcess
        (Invoke-Rec).ExitCode | Should Not Be 0

        Initialize-RecoveryMocks -LiveListener
        (Invoke-Rec).ExitCode | Should Not Be 0
    }

    It 'fails closed when recovery bundle is not staged unless -StageBundle is supplied, and handles Python failures safely' {
        Initialize-RecoveryMocks -BundleNotStaged
        $rNoStage = Invoke-Rec
        $rNoStage.ExitCode | Should Be 2
        ($rNoStage.Output | ConvertFrom-Json).python_status | Should Be 'bundle_not_staged'

        Initialize-RecoveryMocks -DryRunFail
        $rDryFail = Invoke-Rec
        $rDryFail.ExitCode | Should Be 4
        ($rDryFail.Output | ConvertFrom-Json).python_status | Should Be 'dry_run_failed'

        Initialize-RecoveryMocks -ApplyFail
        $rApplyFail = Invoke-Rec -Extra @{ Apply = $true; AuthorizeGuestMutation = $true }
        $rApplyFail.ExitCode | Should Be 4
        $jApplyFail = $rApplyFail.Output | ConvertFrom-Json
        $jApplyFail.python_status | Should Be 'apply_failed'
        ($Global:rEvents -contains "CopyFrom:$guestRoot\*->$($jApplyFail.evidence_dir)\guest-evidence") | Should Be $true
    }

    It 'fails closed on missing or invalid host cleanup manifest before staging or apply' {
        Initialize-RecoveryMocks
        $rMissing = Invoke-Rec -Extra @{ HostCleanupManifest = (Join-Path $testTemp 'nonexistent-manifest.json'); Apply = $true; AuthorizeGuestMutation = $true }
        $rMissing.ExitCode | Should Be 2
        ($rMissing.Output | ConvertFrom-Json).error_category | Should Be 'host_manifest_missing'
        $Global:rPyCalls.Count | Should Be 0

        $badJsonPath = Join-Path $testTemp 'bad-host-manifest.json'
        Set-Content -LiteralPath $badJsonPath -Value '{"schema_version":1,"phases":[]}' -Encoding UTF8
        $rInvalid = Invoke-Rec -Extra @{ HostCleanupManifest = $badJsonPath; Apply = $true; AuthorizeGuestMutation = $true }
        $rInvalid.ExitCode | Should Be 2
        ($rInvalid.Output | ConvertFrom-Json).error_category | Should Be 'host_manifest_invalid'
        $Global:rPyCalls.Count | Should Be 0
    }

    It 'rejects existing stale/corrupt bundle without deleting it, reuses verified bundle, and preserves bootstrap exit codes' {
        # 1. Existing partial/corrupt/stale directory fails closed even with -StageBundle
        Initialize-RecoveryMocks -ExistingInvalidBundle
        $rBadExisting = Invoke-Rec -Extra @{ StageBundle = $true }
        $rBadExisting.ExitCode | Should Be 2
        $jBad = $rBadExisting.Output | ConvertFrom-Json
        $jBad.bundle_status | Should Be 'existing_bundle_invalid'
        ($Global:rEvents -contains 'StageRecoveryBundle:-IntegrityOnly') | Should Be $false

        # 2. Already-verified bundle is reused without re-extracting even when -StageBundle is supplied
        Initialize-RecoveryMocks
        $rReuse = Invoke-Rec -Extra @{ StageBundle = $true }
        $rReuse.ExitCode | Should Be 0
        $jReuse = $rReuse.Output | ConvertFrom-Json
        $jReuse.bundle_status | Should Be 'reused_verified'
        ($Global:rEvents -contains 'StageRecoveryBundle:-IntegrityOnly') | Should Be $false

        # 3. Bootstrap error preserves exact exit code and details
        Initialize-RecoveryMocks -BundleNotStaged -BootstrapFailExitCode 7
        $rBootErr = Invoke-Rec -Extra @{ StageBundle = $true }
        $rBootErr.ExitCode | Should Be 7
        $jBootErr = $rBootErr.Output | ConvertFrom-Json
        $jBootErr.error_category | Should Be 'bundle_bootstrap_failed'
        $jBootErr.error | Should Match 'Simulated bootstrap failure \(7\)'
    }

    It 'executes gated apply: runs dry-run first, stages via -IntegrityOnly if requested, applies recovery, verifies post-recovery inventory, and preserves evidence' {
        Initialize-RecoveryMocks -BundleNotStaged
        $r = Invoke-Rec -Extra @{ Apply = $true; AuthorizeGuestMutation = $true; StageBundle = $true }
        $r.ExitCode | Should Be 0
        $j = $r.Output | ConvertFrom-Json
        $j.bundle_status | Should Be 'staged_and_verified'
        $j.python_status | Should Be 'applied'
        $j.evidence_preserved | Should Be $true
        $j.post_inventory.rc_tasks.Count | Should Be 0
        $j.post_inventory.phases[0].root_exists | Should Be $true
        ($Global:rEvents -contains 'StageRecoveryBundle:-IntegrityOnly') | Should Be $true
        $Global:rPyCalls.Count | Should Be 2
        $Global:rPyCalls[0].apply | Should Be $false
        $Global:rPyCalls[1].apply | Should Be $true
        $Global:rPyCalls[1].auth | Should Be $true
        (Test-Path -LiteralPath (Join-Path $r.EvidenceDir 'pre-recovery-inventory.json')) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $r.EvidenceDir 'dry-run-plan.json')) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $r.EvidenceDir 'recovery-apply-raw.json')) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $r.EvidenceDir 'post-recovery-inventory.json')) | Should Be $true

        # Fails if phase root disappears after apply
        Initialize-RecoveryMocks -PhaseRootMissingAfterApply
        $rMissing = Invoke-Rec -Extra @{ Apply = $true; AuthorizeGuestMutation = $true }
        $rMissing.ExitCode | Should Not Be 0

        # Preserves existing host evidence directory on collision
        $evCollideRoot = Join-Path $testTemp 'collide_rec_ev'
        $evCollideDir = Join-Path $evCollideRoot 'rec01'
        New-Item -ItemType Directory -Path $evCollideDir -Force | Out-Null
        $sentinel = Join-Path $evCollideDir 'final-recovery-summary.json'
        Set-Content -LiteralPath $sentinel -Value '{"keep":true}' -NoNewline -Encoding UTF8
        Initialize-RecoveryMocks
        $rCollide = Invoke-Rec -Extra @{ Apply = $true; AuthorizeGuestMutation = $true; EvidenceRoot = $evCollideRoot }
        $rCollide.ExitCode | Should Not Be 0
        (Get-Content -LiteralPath $sentinel -Raw) | Should Be '{"keep":true}'
    }

    It 'rejects stale v9 tooling commit when checking real bundle guard scriptblock logic' {
        $scriptAst = [System.Management.Automation.Language.Parser]::ParseInput((Get-Content -LiteralPath $scriptPath -Raw), [ref]$null, [ref]$null)
        $rawText = $scriptAst.Extent.Text
        $rawText | Should Match '005293bf8651fe81edc297f6c500e822d4c1ed9d'
        $rawText | Should Match '-IntegrityOnly'
        $rawText | Should Not Match 'Remove-Item[^\r\n]*\$bRoot'
    }

    It 'supports standalone read-only -PostInventory verification and fails if residual task remains' {
        Initialize-RecoveryMocks -TasksCleanInitially
        $rClean = Invoke-Rec -Extra @{ PostInventory = $true }
        $rClean.ExitCode | Should Be 0
        $jClean = $rClean.Output | ConvertFrom-Json
        $jClean.mode | Should Be 'post_inventory'
        $jClean.evidence_preserved | Should Be $true
        $jClean.post_inventory.rc_tasks.Count | Should Be 0
        $Global:rPyCalls.Count | Should Be 0

        Initialize-RecoveryMocks
        $rDirty = Invoke-Rec -Extra @{ PostInventory = $true }
        $rDirty.ExitCode | Should Not Be 0
    }
}
