#Requires -Version 7.0
$ErrorActionPreference = 'Stop'

$scriptPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\tools\h4_qualification\Invoke-H4GuestQualification.ps1'))

Describe 'Invoke-H4GuestQualification.ps1' {
    $testTemp = Join-Path $PSScriptRoot '..\.pytest_tmp_root\pester_h4_qual'
    if (Test-Path -LiteralPath $testTemp) {
        Remove-Item -LiteralPath $testTemp -Recurse -Force
    }
    New-Item -ItemType Directory -Path $testTemp -Force | Out-Null

    # Create tiny dummy files with known SHA-256 hashes for fast offline tests
    $bundleZip = Join-Path $testTemp 'bundle.zip'
    Set-Content -LiteralPath $bundleZip -Value 'bundle-bytes' -NoNewline
    $bundleSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundleZip).Hash

    $bootstrapPs1 = Join-Path $testTemp 'Bootstrap-H4GuestBundle.ps1'
    Set-Content -LiteralPath $bootstrapPs1 -Value '# bootstrap' -NoNewline
    $bootstrapSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $bootstrapPs1).Hash

    $pyExe = Join-Path $testTemp 'python.exe'
    Set-Content -LiteralPath $pyExe -Value 'py-bytes' -NoNewline
    $pySha = (Get-FileHash -Algorithm SHA256 -LiteralPath $pyExe).Hash

    $pwshMsi = Join-Path $testTemp 'pwsh.msi'
    Set-Content -LiteralPath $pwshMsi -Value 'pwsh-bytes' -NoNewline
    $pwshSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $pwshMsi).Hash

    $wheelsDir = Join-Path $testTemp 'wheels'
    New-Item -ItemType Directory -Path $wheelsDir -Force | Out-Null
    $whlFile = Join-Path $wheelsDir 'dummy-1.0.0-py3-none-any.whl'
    Set-Content -LiteralPath $whlFile -Value 'wheel-bytes' -NoNewline
    $whlLen = (Get-Item -LiteralPath $whlFile).Length
    $whlSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $whlFile).Hash
    $wheelsManifest = Join-Path $testTemp 'wheels-sha256.txt'
    Set-Content -LiteralPath $wheelsManifest -Value "$whlSha  dummy-1.0.0-py3-none-any.whl ($whlLen bytes)"

    # Stub injectable functions in test scope for Pester 3.4.0 Mock
    function Get-H4HostVm { param([string]$Id) }
    function Start-H4HostVm { param([string]$Id) }
    function Stop-H4HostVm { param([string]$Id) }
    function Get-H4HostCheckpoints { param([string]$Id) }
    function New-H4HostCheckpoint { param([string]$Id, [string]$SnapshotName) }
    function Open-H4GuestSession { param([string]$Id, [pscredential]$Cred) }
    function Close-H4GuestSession { param($Session) }
    function Invoke-H4GuestScript { param($Session, [scriptblock]$ScriptBlock, [object[]]$ArgumentList) }
    function Copy-H4ToGuest { param($Session, [string]$SourcePath, [string]$DestinationPath) }
    function Copy-H4FromGuest { param($Session, [string]$SourcePath, [string]$DestinationPath) }
    function Request-H4GuestCredential { param([string]$UserHint) }

    function Initialize-QualMocks {
        param(
            [string]$VmState = 'Running',
            [string]$GuestHostname = 'DESKTOP-1ITSJV0',
            [string]$GuestManufacturer = 'Microsoft Corporation',
            [string]$GuestModel = 'Virtual Machine',
            [switch]$ThrowTaskInventory,
            [switch]$ThrowOpenSession,
            [switch]$FailPreflight,
            [switch]$InvalidRunnerJson,
            [switch]$TaskSkipped,
            [string]$FailAtPhase = '',
            [switch]$DuplicateCheckpoint,
            [switch]$ExistingExtractedBundle,
            [switch]$MissingSetupReceipt,
            [switch]$ThrowCopyFromGuest,
            [switch]$InstallerRebootRequired
        )
        $Global:qEvents = [System.Collections.Generic.List[string]]::new()
        $Global:qRunnerCalls = [System.Collections.Generic.List[string]]::new()
        $Global:qVmState = $VmState
        $Global:qThrowTaskInv = [bool]$ThrowTaskInventory
        $Global:qGuestHost = $GuestHostname
        $Global:qGuestMfg = $GuestManufacturer
        $Global:qGuestModel = $GuestModel
        $Global:qFailPreflight = [bool]$FailPreflight
        $Global:qInvalidJson = [bool]$InvalidRunnerJson
        $Global:qTaskSkipped = [bool]$TaskSkipped
        $Global:qFailPhase = $FailAtPhase
        $Global:qExistingBundle = [bool]$ExistingExtractedBundle
        $Global:qMissingReceipt = [bool]$MissingSetupReceipt
        $Global:qRebootReq = [bool]$InstallerRebootRequired
        $Global:qSecCred = [pscredential]::new('DESKTOP-1ITSJV0\mcarls', (ConvertTo-SecureString 'DummyPass!123' -AsPlainText -Force))

        Mock Request-H4GuestCredential { return $Global:qSecCred }
        Mock Get-H4HostVm {
            param($Id)
            if ($Id -ne 'd8483f98-8884-4758-abd1-cd6107c83c03') { return $null }
            return [pscustomobject]@{
                Id    = [guid]'d8483f98-8884-4758-abd1-cd6107c83c03'
                Name  = 'RC-H4-Windows-Acceptance'
                State = $Global:qVmState
            }
        }
        Mock Start-H4HostVm {
            $Global:qEvents.Add('Start-H4HostVm')
            $Global:qVmState = 'Running'
        }
        Mock Stop-H4HostVm {
            $Global:qEvents.Add('Stop-H4HostVm')
            $Global:qVmState = 'Off'
        }
        if ($DuplicateCheckpoint) {
            Mock Get-H4HostCheckpoints {
                return @([pscustomobject]@{ Id = [guid]'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'; Name = 'dup-cp' })
            }
        } else {
            Mock Get-H4HostCheckpoints { return @() }
        }
        Mock New-H4HostCheckpoint {
            param($Id, $SnapshotName)
            $Global:qEvents.Add("Checkpoint:$SnapshotName`:state=$($Global:qVmState)")
            return [pscustomobject]@{
                Id           = [guid]'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
                Name         = $SnapshotName
                CreationTime = [datetime]'2026-11-15T12:00:00Z'
            }
        }
        if ($ThrowOpenSession) {
            Mock Open-H4GuestSession { throw 'PowerShell Direct connection failed' }
        } else {
            Mock Open-H4GuestSession {
                $Global:qEvents.Add('Open-H4GuestSession')
                return [pscustomobject]@{ Id = 1; ComputerName = 'RC-H4-Windows-Acceptance' }
            }
        }
        Mock Close-H4GuestSession { $Global:qEvents.Add('Close-H4GuestSession') }
        Mock Copy-H4ToGuest {
            param($Session, $SourcePath, $DestinationPath)
            $Global:qEvents.Add("CopyTo:$DestinationPath")
        }
        if ($ThrowCopyFromGuest) {
            Mock Copy-H4FromGuest { throw 'Simulated remote copy failure' }
        } else {
            Mock Copy-H4FromGuest {
                param($Session, $SourcePath, $DestinationPath)
                $Global:qEvents.Add("CopyFrom:$SourcePath->$DestinationPath")
            }
        }
        Mock Invoke-H4GuestScript {
            param($Session, $ScriptBlock, $ArgumentList)
            $text = $ScriptBlock.ToString()
            if ($text -match 'Win32_ComputerSystem') {
                if ($Global:qThrowTaskInv) { throw 'Get-ScheduledTask access denied' }
                return [pscustomobject]@{
                    hostname         = $Global:qGuestHost
                    user             = 'DESKTOP-1ITSJV0\mcarls'
                    is_admin         = $true
                    manufacturer     = $Global:qGuestMfg
                    model            = $Global:qGuestModel
                    os_caption       = 'Microsoft Windows 11 Pro'
                    os_version       = '10.0.26300'
                    os_build         = '26300'
                    os_arch          = '64-bit'
                    rc_task_count    = 0
                    rc_service_count = 0
                    rc_proc_count    = 0
                }
            }
            if ($text -match 'Bootstrap-H4GuestBundle\.ps1') {
                if ($Global:qExistingBundle) {
                    throw 'Target extraction directory already exists; refusing destructive overwrite: C:\H4-Guest-Work\bundles\existing'
                }
                if ($Global:qRebootReq) {
                    return [pscustomobject]@{ status = 'reboot_required'; pwsh_version = $null; python_version = $null }
                }
                $Global:qEvents.Add('GuestSetup')
                return [pscustomobject]@{
                    status         = 'ready'
                    pwsh_version   = 'PowerShell 7.6.10'
                    python_version = 'Python 3.12.10'
                    bundle_dest    = $ArgumentList[4]
                }
            }
            if ($text -match 'Verify-H4GuestBundle\.ps1') {
                $Global:qVerifyScriptBlock = $ScriptBlock
                $Global:qVerifyArgs = $ArgumentList
                if ($Global:qMissingReceipt) {
                    throw "Setup receipt not found for OperationId '$($ArgumentList[0])'."
                }
                return "C:\H4-Guest-Work\bundles\$($ArgumentList[0])"
            }
            if ($text -match 'RC_H4_DISPOSABLE_GUEST_AUTHORIZED' -and $text -match '--profile cleanup') {
                $Global:qEvents.Add('ScopedCleanup')
                return [pscustomobject]@{ exit_code = 0; output = '{"status":"verified"}' }
            }
            if ($text -match '--source-manifest \$manifest --json') {
                # Read-only preflight
                if ($Global:qFailPreflight) {
                    return [pscustomobject]@{
                        exit_code = 3
                        output    = '{"guest_verified":false,"observed_guard_reasons":["not_guest"],"profile_blockers":["not_guest"]}'
                    }
                }
                return [pscustomobject]@{
                    exit_code = 0
                    output    = '{"guest_verified":true,"observed_guard_reasons":[],"profile_blockers":[]}'
                }
            }
            if ($text -match 'RC_H4_DISPOSABLE_GUEST_AUTHORIZED') {
                $rDir = $ArgumentList[3]
                $argsArr = @($ArgumentList[5] | ConvertFrom-Json)
                $cmdStr = "$rDir|" + ($argsArr -join ' ')
                $Global:qRunnerCalls.Add($cmdStr)
                if ($Global:qInvalidJson) {
                    return [pscustomobject]@{ exit_code = 0; output = 'NOT-JSON' }
                }
                if ($Global:qTaskSkipped -and ($argsArr -contains 'task')) {
                    return [pscustomobject]@{ exit_code = 0; output = '{"status":"passed","counts":{"tests":1,"skipped":1}}' }
                }
                if ($Global:qFailPhase -and $cmdStr -match [regex]::Escape($Global:qFailPhase)) {
                    return [pscustomobject]@{ exit_code = 4; output = '{"status":"failed","exit_code":4}' }
                }
                return [pscustomobject]@{ exit_code = 0; output = '{"status":"passed","counts":{"tests":1,"skipped":0}}' }
            }
            return $null
        }
    }

    function Invoke-Qual {
        param([hashtable]$Extra = @{})
        $evDir = Join-Path $testTemp ('ev_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        $base = @{
            BundleZip            = $bundleZip
            ExpectedBundleSha256 = $bundleSha
            BootstrapScript      = $bootstrapPs1
            ExpectedBootstrapSha256 = $bootstrapSha
            WheelsDir            = $wheelsDir
            WheelsManifest       = $wheelsManifest
            PythonInstaller      = $pyExe
            ExpectedPythonSha256 = $pySha
            PwshInstaller        = $pwshMsi
            ExpectedPwshSha256   = $pwshSha
            EvidenceRoot         = $evDir
            OperationId          = 'optest01'
            Json                 = $true
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
        $errors.Count | Should Be 0
    }

    It '1-2: default invocation and -WhatIf -Apply perform no writes' {
        Initialize-QualMocks
        $r1 = Invoke-Qual
        $r1.ExitCode | Should Be 0
        (Test-Path -LiteralPath $r1.EvidenceDir) | Should Be $false
        ($Global:qEvents | Where-Object { $_ -like 'CopyTo:*' -or $_ -eq 'GuestSetup' }).Count | Should Be 0

        $r2 = Invoke-Qual -Extra @{ Stage = 'All'; Apply = $true; AuthorizeGuestMutation = $true; WhatIf = $true }
        $r2.ExitCode | Should Be 0
        (Test-Path -LiteralPath $r2.EvidenceDir) | Should Be $false
    }

    It '3-6: rejects wrong VM ID, wrong guest hostname, non-guest host, and unavailable task inventory' {
        Initialize-QualMocks
        (Invoke-Qual -Extra @{ VmId = '00000000-0000-0000-0000-000000000000' }).ExitCode | Should Not Be 0

        Initialize-QualMocks -GuestHostname 'XERES'
        (Invoke-Qual).ExitCode | Should Not Be 0

        Initialize-QualMocks -GuestManufacturer 'Dell Inc.' -GuestModel 'Precision'
        (Invoke-Qual).ExitCode | Should Not Be 0

        Initialize-QualMocks -ThrowTaskInventory
        (Invoke-Qual).ExitCode | Should Not Be 0
    }

    It '7-9: rejects invalid or blank checksums, missing bootstrap script, and missing wheel manifest' {
        Initialize-QualMocks
        (Invoke-Qual -Extra @{ ExpectedBundleSha256 = ('0' * 64) }).ExitCode | Should Not Be 0
        (Invoke-Qual -Extra @{ ExpectedBootstrapSha256 = '' }).ExitCode | Should Not Be 0
        (Invoke-Qual -Extra @{ ExpectedBootstrapSha256 = 'not-a-hex-digest' }).ExitCode | Should Not Be 0
        (Invoke-Qual -Extra @{ BootstrapScript = (Join-Path $testTemp 'missing-bootstrap.ps1') }).ExitCode | Should Not Be 0
        (Invoke-Qual -Extra @{ WheelsManifest = (Join-Path $testTemp 'missing-wheels.txt') }).ExitCode | Should Not Be 0
    }

    It '10-12, 22, 25, 27-28: executes full end-to-end mocked run with h4-rc- roots, auth flags, manifest, powered-off checkpoint, and no persisted secrets' {
        Initialize-QualMocks
        $r = Invoke-Qual -Extra @{ Stage = 'All'; Apply = $true; AuthorizeGuestMutation = $true; CheckpointName = 'cp-clean-01' }
        $r.ExitCode | Should Be 0
        $parsed = $r.Output | ConvertFrom-Json
        $parsed.stage_results.Preflight | Should Be 'PASS'
        $parsed.stage_results.Setup | Should Be 'PASS'
        $parsed.stage_results.Checkpoint | Should Be 'PASS'
        $parsed.stage_results.Acceptance | Should Be 'PASS'
        $parsed.profiles.Count | Should Be 8
        $parsed.profiles[0].evidence_transfer_status | Should Be 'COMPLETE'
        ($Global:qRunnerCalls -join "`n") | Should Not Match 'h4-windows-acceptance'

        # Test roots begin with h4-rc-
        foreach ($p in $parsed.profiles) {
            (Split-Path -Leaf $p.test_root) | Should Match '^h4-rc-'
        }
        # Task profile has --authorize-guest-mutation and --source-manifest
        $taskCall = $Global:qRunnerCalls | Where-Object { $_ -match '--profile task' }
        $taskCall | Should Match '--authorize-guest-mutation'
        $taskCall | Should Match '--source-manifest'
        # Full and rollback profiles have --source-manifest and --old-source-root
        $fullCall = $Global:qRunnerCalls | Where-Object { $_ -match '--profile full' }
        $fullCall | Should Match '--source-manifest'
        $fullCall | Should Match '--old-source-root'
        # Checkpoint occurred only while VM state was Off after Stop-H4HostVm
        ($Global:qEvents -contains 'Stop-H4HostVm') | Should Be $true
        ($Global:qEvents -contains 'Checkpoint:cp-clean-01:state=Off') | Should Be $true
        # No password persisted in evidence
        $allEvidenceText = (Get-ChildItem -LiteralPath $r.EvidenceDir -Recurse -File | Get-Content -Raw) -join "`n"
        $allEvidenceText | Should Not Match 'DummyPass!123'
    }

    It '13: failed preflight blocks subsequent work' {
        Initialize-QualMocks -FailPreflight
        $r = Invoke-Qual -Extra @{ Stage = 'Setup'; Apply = $true }
        $r.ExitCode | Should Not Be 0
        $Global:qRunnerCalls.Count | Should Be 0
    }

    It '14-18, 26: invalid JSON, nonzero exit, skipped task, and mid-rollback failure stop matrix, run scoped cleanup, and preserve evidence' {
        Initialize-QualMocks -InvalidRunnerJson
        $rJson = Invoke-Qual -Extra @{ Stage = 'Acceptance'; Apply = $true; AuthorizeGuestMutation = $true }
        $rJson.ExitCode | Should Not Be 0
        $Global:qRunnerCalls.Count | Should Be 1

        Initialize-QualMocks -TaskSkipped
        $rSkip = Invoke-Qual -Extra @{ Stage = 'Acceptance'; Apply = $true; AuthorizeGuestMutation = $true }
        $rSkip.ExitCode | Should Not Be 0
        $Global:qRunnerCalls.Count | Should Be 2

        Initialize-QualMocks -FailAtPhase 'after_old_service_stopped'
        $rRb = Invoke-Qual -Extra @{ Stage = 'Acceptance'; Apply = $true; AuthorizeGuestMutation = $true }
        $rRb.ExitCode | Should Not Be 0
        # Ran offline + task + full + 2 rollback phases, stopped before remaining 3 rollback phases
        $Global:qRunnerCalls.Count | Should Be 5
        ($Global:qEvents -contains 'ScopedCleanup') | Should Be $true
        (Test-Path -LiteralPath (Join-Path $rRb.EvidenceDir 'final-summary.json')) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $rRb.EvidenceDir 'matrix-summary.json')) | Should Be $true
    }

    It '19-21, 23-24: preserves existing bundle, rejects duplicate checkpoint, never falls back on PS Direct error, handles 3010 and CopyFrom failure' {
        Initialize-QualMocks -ExistingExtractedBundle
        (Invoke-Qual -Extra @{ Stage = 'Setup'; Apply = $true }).ExitCode | Should Not Be 0

        Initialize-QualMocks -DuplicateCheckpoint
        (Invoke-Qual -Extra @{ Stage = 'Checkpoint'; Apply = $true; AuthorizeGuestMutation = $true; CheckpointName = 'dup-cp' }).ExitCode | Should Not Be 0

        Initialize-QualMocks -ThrowOpenSession
        $rPs = Invoke-Qual -Extra @{ Stage = 'Acceptance'; Apply = $true; AuthorizeGuestMutation = $true }
        $rPs.ExitCode | Should Not Be 0
        $Global:qRunnerCalls.Count | Should Be 0

        Initialize-QualMocks -InstallerRebootRequired
        $r3010 = Invoke-Qual -Extra @{ Stage = 'Setup'; Apply = $true }
        $r3010.ExitCode | Should Be 2

        Initialize-QualMocks -ThrowCopyFromGuest
        $rCopy = Invoke-Qual -Extra @{ Stage = 'Acceptance'; Apply = $true; AuthorizeGuestMutation = $true }
        $rCopy.ExitCode | Should Be 5
        $copyJson = $rCopy.Output | ConvertFrom-Json
        $copyJson.stage_results.Acceptance | Should Be 'INCOMPLETE'
        $copyJson.error_category | Should Be 'evidence_transfer_incomplete'
        $copyJson.profiles[0].status | Should Be 'PASS'
        $copyJson.profiles[0].evidence_transfer_status | Should Be 'INCOMPLETE'
        (Test-Path -LiteralPath (Join-Path $rCopy.EvidenceDir 'final-summary.json')) | Should Be $true

        Initialize-QualMocks -MissingSetupReceipt
        $rMissingRec = Invoke-Qual -Extra @{ Stage = 'Acceptance'; Apply = $true; AuthorizeGuestMutation = $true }
        $rMissingRec.ExitCode | Should Not Be 0
        $Global:qRunnerCalls.Count | Should Be 0
    }

    It 'real archive integration: Bootstrap-H4GuestBundle.ps1 extracts bundle directly into destination root and Verify-H4GuestBundle.ps1 passes' {
        $realBundle = 'C:\H4-VM-Staging\bundle-rc1-v3\h4-windows-acceptance.zip'
        $realBootstrap = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\tools\h4_qualification\Bootstrap-H4GuestBundle.ps1'))
        $realBundleSha = 'daaf9a7b7bd5534a17541f49660360c060a2ba3df946dbddca46e6b63797e7fe'
        (Test-Path -LiteralPath $realBundle -PathType Leaf) | Should Be $true
        (Test-Path -LiteralPath $realBootstrap -PathType Leaf) | Should Be $true

        $extractRoot = Join-Path $testTemp 'real_extract'
        $bootOut = & pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $realBootstrap `
            -ArchivePath $realBundle `
            -ExpectedSha256 $realBundleSha `
            -DestinationRoot $extractRoot *>&1
        # Verify-H4GuestBundle.ps1 runs read-only preflight which exits 3 on non-guest host after manifest/source verification
        $LASTEXITCODE | Should Be 3
        ($bootOut -join "`n") | Should Match '"verified": true'
        ($bootOut -join "`n") | Should Match 'guest_identity_not_independently_verified'

        (Test-Path -LiteralPath (Join-Path $extractRoot 'h4-windows-acceptance')) | Should Be $false
        (Test-Path -LiteralPath (Join-Path $extractRoot 'manifest.json') -PathType Leaf) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $extractRoot 'scripts\Verify-H4GuestBundle.ps1') -PathType Leaf) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $extractRoot 'dependencies\requirements.txt') -PathType Leaf) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $extractRoot 'dependencies\requirements-dev.txt') -PathType Leaf) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $extractRoot 'harness\windows_acceptance.py') -PathType Leaf) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $extractRoot 'sources\rc-1.0.0') -PathType Container) | Should Be $true
        (Test-Path -LiteralPath (Join-Path $extractRoot 'sources\rc-0.14.0') -PathType Container) | Should Be $true
    }

    It 'resumed Acceptance verification passes guest venv Python, captures stdout without polluting return value, and throws on nonzero exit' {
        Initialize-QualMocks
        $rAcc = Invoke-Qual -Extra @{ Stage = 'Acceptance'; Apply = $true; AuthorizeGuestMutation = $true }
        $rAcc.ExitCode | Should Be 0
        $Global:qVerifyArgs[2] | Should Be 'C:\H4-Guest-Work\venv\Scripts\python.exe'

        $vRoot = Join-Path $testTemp 'verify_stdout_test'
        $vReceipts = Join-Path $vRoot 'receipts'
        $vBundle = Join-Path $vRoot 'bundle'
        $vScripts = Join-Path $vBundle 'scripts'
        New-Item -ItemType Directory -Path $vReceipts, $vScripts -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $vBundle 'manifest.json') -Value '{}' -Encoding UTF8

        $pyRecordFile = Join-Path $vRoot 'recorded_python.txt'
        $fakeVerifyScript = Join-Path $vScripts 'Verify-H4GuestBundle.ps1'
        @"
param([string]`$BundleRoot, [string]`$Python)
Set-Content -LiteralPath '$pyRecordFile' -Value `$Python -NoNewline -Encoding UTF8
Write-Output 'Verify-H4GuestBundle stdout line 1'
Write-Output 'Verify-H4GuestBundle stdout line 2'
exit 0
"@ | Set-Content -LiteralPath $fakeVerifyScript -Encoding UTF8

        $opId = 'optest01'
        @{
            operation_id  = $opId
            bundle_sha256 = $bundleSha.ToLowerInvariant()
            bundle_dest   = $vBundle
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $vReceipts "setup-$opId.json") -Encoding UTF8

        $pwshPath = (Get-Command pwsh).Source
        $adaptedCode = $Global:qVerifyScriptBlock.ToString().
            Replace('C:\H4-Guest-Work\receipts', $vReceipts).
            Replace('C:\Program Files\PowerShell\7\pwsh.exe', $pwshPath)
        $adaptedSb = [scriptblock]::Create($adaptedCode)

        $resolved = & $adaptedSb $Global:qVerifyArgs[0] $Global:qVerifyArgs[1] $Global:qVerifyArgs[2]
        ($resolved -is [string]) | Should Be $true
        (@($resolved).Count) | Should Be 1
        $resolved | Should Be $vBundle
        (Get-Content -LiteralPath $pyRecordFile -Raw) | Should Be 'C:\H4-Guest-Work\venv\Scripts\python.exe'

        @"
param([string]`$BundleRoot, [string]`$Python)
Write-Output 'Simulated verification failure output'
exit 4
"@ | Set-Content -LiteralPath $fakeVerifyScript -Encoding UTF8

        $threw = $false
        $errText = ''
        try {
            $null = & $adaptedSb $Global:qVerifyArgs[0] $Global:qVerifyArgs[1] $Global:qVerifyArgs[2]
        } catch {
            $threw = $true
            $errText = $_.Exception.Message
        }
        $threw | Should Be $true
        $errText | Should Match 'exit 4'
    }

    It 'Stop-H4HostVm and Start-H4HostVm match real Hyper-V cmdlet parameter contracts (-VM, no -Id, no -TurnOff/-Force) and verify VM identity' {
        $tokens = $null; $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
        $errors.Count | Should Be 0

        $fnAsts = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)
        $getFnAst = $fnAsts | Where-Object { $_.Name -eq 'Get-H4HostVm' } | Select-Object -First 1
        $startFnAst = $fnAsts | Where-Object { $_.Name -eq 'Start-H4HostVm' } | Select-Object -First 1
        $stopFnAst = $fnAsts | Where-Object { $_.Name -eq 'Stop-H4HostVm' } | Select-Object -First 1
        ($null -ne $getFnAst) | Should Be $true
        ($null -ne $startFnAst) | Should Be $true
        ($null -ne $stopFnAst) | Should Be $true

        # Verify real Hyper-V module cmdlet contracts when Hyper-V module is present on host
        $realStopVm = Get-Command -Name 'Stop-VM' -Module 'Hyper-V' -ErrorAction SilentlyContinue
        $realStartVm = Get-Command -Name 'Start-VM' -Module 'Hyper-V' -ErrorAction SilentlyContinue
        if ($realStopVm) {
            $realStopVm.Parameters.ContainsKey('Id') | Should Be $false
            $realStopVm.Parameters.ContainsKey('VM') | Should Be $true
        }
        if ($realStartVm) {
            $realStartVm.Parameters.ContainsKey('Id') | Should Be $false
            $realStartVm.Parameters.ContainsKey('VM') | Should Be $true
        }

        # Verify AST parameter usage directly on Stop-VM / Start-VM
        $stopText = $stopFnAst.Extent.Text
        $startText = $startFnAst.Extent.Text
        $stopText | Should Match 'Stop-VM\s+-VM\s+\$vmObj'
        $stopText | Should Not Match 'Stop-VM\b[^\r\n]*\s-Id\b'
        $stopText | Should Not Match 'Stop-VM\b[^\r\n]*\s-(TurnOff|Force)\b'
        $startText | Should Match 'Start-VM\s+-VM\s+\$vmObj'
        $startText | Should Not Match 'Start-VM\b[^\r\n]*\s-Id\b'

        # Execute the real helper definitions against strict Hyper-V contract stubs (no -Id on Stop-VM/Start-VM)
        $expectedId = 'd8483f98-8884-4758-abd1-cd6107c83c03'
        $probeScript = @"
`$ErrorActionPreference = 'Stop'
`$VmName = 'RC-H4-Windows-Acceptance'
`$calls = [System.Collections.Generic.List[string]]::new()
function Get-VM {
    param([Parameter(Mandatory)][guid]`$Id)
    `$calls.Add("Get-VM:`$Id")
    return [pscustomobject]@{ Id = `$Id; Name = 'RC-H4-Windows-Acceptance'; State = 'Running' }
}
function Stop-VM {
    param([Parameter(Mandatory)]`$VM)
    `$calls.Add("Stop-VM:`$(`$VM.Id):`$(`$VM.Name)")
}
function Start-VM {
    param([Parameter(Mandatory)]`$VM)
    `$calls.Add("Start-VM:`$(`$VM.Id):`$(`$VM.Name)")
}
$($getFnAst.Extent.Text)
$($startFnAst.Extent.Text)
$($stopFnAst.Extent.Text)
Stop-H4HostVm -Id '$expectedId'
Start-H4HostVm -Id '$expectedId'
`$mismatchThrew = `$false
try {
    Stop-H4HostVm -Id '$expectedId' -ExpectedName 'Wrong-VM'
} catch {
    `$mismatchThrew = `$true
}
[pscustomobject]@{ calls = @(`$calls); mismatch_threw = `$mismatchThrew } | ConvertTo-Json -Compress
"@
        $probeOut = & pwsh -NoProfile -NonInteractive -Command $probeScript
        $LASTEXITCODE | Should Be 0
        $probe = $probeOut | ConvertFrom-Json
        $probe.calls[0] | Should Be "Get-VM:$expectedId"
        $probe.calls[1] | Should Be "Stop-VM:${expectedId}:RC-H4-Windows-Acceptance"
        $probe.calls[2] | Should Be "Get-VM:$expectedId"
        $probe.calls[3] | Should Be "Start-VM:${expectedId}:RC-H4-Windows-Acceptance"
        $probe.calls[4] | Should Be "Get-VM:$expectedId"
        $probe.calls.Count | Should Be 5
        $probe.mismatch_threw | Should Be $true
    }

    It 'records Checkpoint stage as FAIL (not NOT_RUN) when checkpointing fails after entering Checkpoint stage' {
        Initialize-QualMocks -DuplicateCheckpoint
        $rCpFail = Invoke-Qual -Extra @{ Stage = 'Checkpoint'; Apply = $true; AuthorizeGuestMutation = $true; CheckpointName = 'dup-cp' }
        $rCpFail.ExitCode | Should Not Be 0
        $cpFailJson = $rCpFail.Output | ConvertFrom-Json
        $cpFailJson.stage_results.Checkpoint | Should Be 'FAIL'
        $savedSummary = Get-Content -LiteralPath (Join-Path $rCpFail.EvidenceDir 'final-summary.json') -Raw | ConvertFrom-Json
        $savedSummary.stage_results.Checkpoint | Should Be 'FAIL'
    }
}
