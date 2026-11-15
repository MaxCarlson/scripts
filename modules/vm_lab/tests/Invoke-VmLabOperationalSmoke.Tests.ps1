#Requires -Version 7.0

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Split-Path -Parent $here
$moduleManifest = Join-Path $moduleRoot 'vm_lab.psd1'
$smokeScript = Join-Path $here 'Invoke-VmLabOperationalSmoke.ps1'

Describe 'Invoke-VmLabOperationalSmoke harness' {
    $tmpRoot = Join-Path $moduleRoot '.pytest_tmp_root\pester_smoke'
    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

    function Invoke-SmokeDriver {
        param(
            [Parameter(Mandatory)][string]$CaseDir,
            [Parameter(Mandatory)][string]$MockSetupCode,
            [Parameter(Mandatory)][string]$SmokeArgsCode
        )
        New-Item -ItemType Directory -Path $CaseDir -Force | Out-Null
        $driverPath = Join-Path $CaseDir 'driver.ps1'
        $scriptBody = @"
Import-Module Pester -Force
Import-Module '$moduleManifest' -Force
Describe 'smoke-driver' {
    It 'runs' {
        $MockSetupCode
        & '$smokeScript' $SmokeArgsCode
        exit `$LASTEXITCODE
    }
}
"@
        [System.IO.File]::WriteAllText($driverPath, $scriptBody, [System.Text.UTF8Encoding]::new($false))
        $psi = [System.Diagnostics.ProcessStartInfo]::new('pwsh')
        $psi.ArgumentList.Add('-NoProfile')
        $psi.ArgumentList.Add('-File')
        $psi.ArgumentList.Add($driverPath)
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $proc = [System.Diagnostics.Process]::Start($psi)
        $stdout = $proc.StandardOutput.ReadToEnd()
        $stderr = $proc.StandardError.ReadToEnd()
        $proc.WaitForExit()
        $jsonIdx = $stdout.IndexOf('{')
        $parsed = if ($jsonIdx -ge 0) { $stdout.Substring($jsonIdx) | ConvertFrom-Json } else { $null }
        return [pscustomobject]@{
            exit_code = $proc.ExitCode
            json      = $parsed
            stdout    = $stdout
            stderr    = $stderr
        }
    }

    $baseThreeVmSetup = @'
$Global:smokeVms = @(
    [pscustomobject]@{ Name = 'RC-H4-Windows-Acceptance'; Id = [guid]'d8483f98-8884-4758-abd1-cd6107c83c03'; State = 'Running'; ConfigurationLocation = 'C:\Protected\H4' },
    [pscustomobject]@{ Name = 'Other-Managed-VM'; Id = [guid]'22222222-2222-2222-2222-222222222222'; State = 'Running'; ConfigurationLocation = 'C:\Other\Managed' },
    [pscustomobject]@{ Name = 'Unmanaged-VM'; Id = [guid]'33333333-3333-3333-3333-333333333333'; State = 'Off'; ConfigurationLocation = 'C:\Other\Unmanaged' }
)
$Global:smokeLog = [System.Collections.Generic.List[string]]::new()
Mock Get-VM { return @($Global:smokeVms) }
Mock -ModuleName vm_lab Get-VM { return @($Global:smokeVms) }
Mock -ModuleName vm_lab Get-VMHost { return [pscustomobject]@{ ComputerName = 'TESTHOST'; MemoryCapacity = 64GB } }
Mock -ModuleName vm_lab Get-CimInstance { return [pscustomobject]@{ FreePhysicalMemory = 16777216 } }
Mock Test-VmLabPlan {
    param($Config, $ManifestRoot)
    return [pscustomobject]@{ status = 'planned'; vm_name = $Config.vm_name; vm_root = $Config.vm_root }
}
Mock -ModuleName vm_lab Test-VmLabOwnership {
    param($Vm, $ManifestRoot)
    if ($Vm.Name -eq 'Unmanaged-VM') {
        return [pscustomobject]@{ owned = $false; reason = 'No ownership manifest' }
    }
    return [pscustomobject]@{ owned = $true; manifest = [pscustomobject]@{ vm_id = [string]$Vm.Id; vm_name = $Vm.Name } }
}
'@

    It 'allows unrelated disposable target when protected H4 VM exists, and rejects H4 by name or renamed ID' {
        $c1 = Join-Path $tmpRoot 'c1'
        $vmRoot1 = Join-Path $c1 'disp_vm'
        $resOk = Invoke-SmokeDriver -CaseDir $c1 -MockSetupCode $baseThreeVmSetup -SmokeArgsCode "-VmName 'Disp-Smoke-01' -VmRoot '$vmRoot1' -Phase preflight"
        $resOk.exit_code | Should Be 0
        $resOk.json.status | Should Be 'preflight_passed'
        $resOk.json.reason_code | Should Be 'preflight_ok'

        # Reject H4 by exact name
        $resH4Name = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c1_h4name') -MockSetupCode $baseThreeVmSetup -SmokeArgsCode "-VmName 'RC-H4-Windows-Acceptance' -VmRoot '$vmRoot1' -Phase preflight"
        $resH4Name.exit_code | Should Be 1
        $resH4Name.json.status | Should Be 'acceptance_failed'
        $resH4Name.json.detail | Should Match 'protected VM name'

        # Reject H4 by ID even if renamed
        $renamedSetup = $baseThreeVmSetup + "`n" + @'
$Global:smokeVms[0].Name = 'Renamed-H4-VM'
'@
        $resH4Id = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c1_h4id') -MockSetupCode $renamedSetup -SmokeArgsCode "-VmName 'Renamed-H4-VM' -VmRoot '$vmRoot1' -Phase preflight"
        $resH4Id.exit_code | Should Be 1
        $resH4Id.json.status | Should Be 'acceptance_failed'
        $resH4Id.json.detail | Should Match 'protected VM ID'
    }

    It 'rejects unmanaged targets, corrupt manifests, and identity mismatches' {
        $c2 = Join-Path $tmpRoot 'c2'
        $resUnm = Invoke-SmokeDriver -CaseDir $c2 -MockSetupCode $baseThreeVmSetup -SmokeArgsCode "-VmName 'Unmanaged-VM' -VmRoot '$c2\unm' -Phase preflight"
        $resUnm.exit_code | Should Be 1
        $resUnm.json.detail | Should Match 'unmanaged'

        $idMismatchSetup = $baseThreeVmSetup + "`n" + @'
Mock -ModuleName vm_lab Test-VmLabOwnership {
    param($Vm, $ManifestRoot)
    return [pscustomobject]@{ owned = $true; manifest = [pscustomobject]@{ vm_id = '99999999-9999-9999-9999-999999999999'; vm_name = $Vm.Name } }
}
'@
        $resIdMis = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c2_mis') -MockSetupCode $idMismatchSetup -SmokeArgsCode "-VmName 'Other-Managed-VM' -VmRoot '$c2\mis' -Phase preflight"
        $resIdMis.exit_code | Should Be 1
        $resIdMis.json.detail | Should Match 'identity mismatch'
    }

    It 'blocks unauthorized mutating phases and performs zero mutations in -WhatIf' {
        $c3 = Join-Path $tmpRoot 'c3'
        $setupMut = $baseThreeVmSetup + "`n" + @'
Mock New-VmLabMachine { throw 'MUST_NOT_MUTATE' }
Mock Start-VmLabMachine { throw 'MUST_NOT_MUTATE' }
'@
        $resNoAuth = Invoke-SmokeDriver -CaseDir $c3 -MockSetupCode $setupMut -SmokeArgsCode "-VmName 'Disp-Smoke-02' -VmRoot '$c3\vm' -Phase provision"
        $resNoAuth.exit_code | Should Be 1
        $resNoAuth.json.status | Should Be 'blocked'
        $resNoAuth.json.reason_code | Should Be 'authorization_required'

        $resWhatIf = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c3_wi') -MockSetupCode $setupMut -SmokeArgsCode "-VmName 'Disp-Smoke-02' -VmRoot '$c3\vm' -Phase provision -AuthorizeDisposableTest -WhatIf"
        $resWhatIf.exit_code | Should Be 0
        $resWhatIf.json.status | Should Be 'blocked'
        $resWhatIf.json.reason_code | Should Be 'whatif_dry_run'
    }

    It 'provisions fresh VM to awaiting_windows_installation, distinguishes guest pending/auth states, and resumes to acceptance_passed or partial' {
        $c4 = Join-Path $tmpRoot 'c4'
        $vmRoot4 = Join-Path $c4 'disp_vm4'
        $provSetup = $baseThreeVmSetup + "`n" + @'
Mock New-VmLabMachine {
    param($Config, $Apply, $ManifestRoot)
    $Global:smokeVms += [pscustomobject]@{ Name = $Config.vm_name; Id = [guid]'44444444-4444-4444-4444-444444444444'; State = 'Off'; ConfigurationLocation = $Config.vm_root }
    return [pscustomobject]@{ status = 'created'; vm_id = '44444444-4444-4444-4444-444444444444'; vm_name = $Config.vm_name }
}
Mock Start-VmLabMachine {
    param($Name, $Apply, $ManifestRoot)
    return [pscustomobject]@{ status = 'started'; state = 'Running' }
}
'@
        $resProv = Invoke-SmokeDriver -CaseDir $c4 -MockSetupCode $provSetup -SmokeArgsCode "-VmName 'Disp-Smoke-04' -VmRoot '$vmRoot4' -Phase provision -AuthorizeDisposableTest -Start"
        $resProv.exit_code | Should Be 0
        $resProv.json.status | Should Be 'awaiting_windows_installation'
        $resProv.json.vm_id | Should Be '44444444-4444-4444-4444-444444444444'
        (Test-Path -LiteralPath (Join-Path $vmRoot4 'acceptance-state.json')) | Should Be $true

        # Existing owned VM cannot be overwritten by -Phase provision
        $ownedRunningSetup = $baseThreeVmSetup + "`n" + @'
$Global:smokeVms += [pscustomobject]@{ Name = 'Disp-Smoke-04'; Id = [guid]'44444444-4444-4444-4444-444444444444'; State = 'Running'; ConfigurationLocation = 'C:\Disp4' }
'@
        $resReprov = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c4_reprov') -MockSetupCode $ownedRunningSetup -SmokeArgsCode "-VmName 'Disp-Smoke-04' -VmRoot '$vmRoot4' -Phase provision -AuthorizeDisposableTest"
        $resReprov.exit_code | Should Be 1
        $resReprov.json.detail | Should Match 'already exists'

        # Missing credentials -> awaiting_guest_credentials
        $noCredSetup = $ownedRunningSetup + "`n" + @'
Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'ps_direct_auth_unavailable'; ps_direct_available = $false } }
'@
        $resNoCred = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c4_nocred') -MockSetupCode $noCredSetup -SmokeArgsCode "-VmName 'Disp-Smoke-04' -VmRoot '$vmRoot4' -Phase guest -AuthorizeDisposableTest"
        $resNoCred.exit_code | Should Be 1
        $resNoCred.json.status | Should Be 'awaiting_guest_credentials'

        # OOBE incomplete -> awaiting_windows_installation
        $oobeSetup = $ownedRunningSetup + "`n" + @'
Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'windows_booted_account_unavailable'; ps_direct_available = $false } }
'@
        $resOobe = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c4_oobe') -MockSetupCode $oobeSetup -SmokeArgsCode "-VmName 'Disp-Smoke-04' -VmRoot '$vmRoot4' -Phase guest -AuthorizeDisposableTest"
        $resOobe.exit_code | Should Be 1
        $resOobe.json.status | Should Be 'awaiting_windows_installation'

        # Auth failed -> acceptance_failed
        $authFailSetup = $ownedRunningSetup + "`n" + @'
Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'ps_direct_auth_failed'; ps_direct_available = $false } }
'@
        $resAuthFail = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c4_authfail') -MockSetupCode $authFailSetup -SmokeArgsCode "-VmName 'Disp-Smoke-04' -VmRoot '$vmRoot4' -Phase guest -AuthorizeDisposableTest"
        $resAuthFail.exit_code | Should Be 1
        $resAuthFail.json.status | Should Be 'acceptance_failed'
        $resAuthFail.json.reason_code | Should Be 'ps_direct_auth_failed'

        # Successful guest + finalize (with shutdown_requested -> partial)
        $guestPassSetup = $ownedRunningSetup + "`n" + @'
Mock New-VmLabMachine { throw 'MUST_NOT_REPROVISION' }
Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'guest_ready'; ps_direct_available = $true } }
Mock Invoke-VmLabGuestBootstrap { return [pscustomobject]@{ status = 'bootstrapped'; profile = 'windows-minimal' } }
Mock Test-VmLabGuestVerify { return [pscustomobject]@{ status = 'verified'; failures = @() } }
Mock Copy-VmLabGuestItem { return [pscustomobject]@{ status = 'copied'; sha256_verified = $true } }
Mock New-VmLabBaselineCheckpoint { return [pscustomobject]@{ status = 'baseline_created'; baseline_qualified = $true } }
Mock Stop-VmLabMachine { return [pscustomobject]@{ status = 'shutdown_requested'; state = 'Running' } }
'@
        $resPartial = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c4_partial') -MockSetupCode $guestPassSetup -SmokeArgsCode "-VmName 'Disp-Smoke-04' -VmRoot '$vmRoot4' -Phase full -AuthorizeDisposableTest -AuthorizeShutdown"
        $resPartial.exit_code | Should Be 1
        $resPartial.json.status | Should Be 'partial'
        $resPartial.json.phases.finalize.shutdown_status | Should Be 'shutdown_requested_unconfirmed'

        # Confirmed shutdown -> acceptance_passed
        $guestConfirmedSetup = $guestPassSetup + "`n" + @'
Mock Stop-VmLabMachine { return [pscustomobject]@{ status = 'stopped'; state = 'Off' } }
'@
        $resPass = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c4_pass') -MockSetupCode $guestConfirmedSetup -SmokeArgsCode "-VmName 'Disp-Smoke-04' -VmRoot '$vmRoot4' -Phase full -AuthorizeDisposableTest -AuthorizeShutdown"
        $resPass.exit_code | Should Be 0
        $resPass.json.status | Should Be 'acceptance_passed'
        $resPass.json.phases.finalize.shutdown_status | Should Be 'shutdown_confirmed'

        # Identity change between acceptance-state.json and resume -> rejected
        $resChangedId = Invoke-SmokeDriver -CaseDir (Join-Path $tmpRoot 'c4_chg') -MockSetupCode $guestPassSetup -SmokeArgsCode "-VmName 'Disp-Smoke-04' -VmRoot '$vmRoot4' -ExpectedVmId '55555555-5555-5555-5555-555555555555' -Phase guest -AuthorizeDisposableTest"
        $resChangedId.exit_code | Should Be 1
        $resChangedId.json.detail | Should Match 'identity changed'
    }

    It 'surfaces guest bootstrap, transfer hash, and checkpoint failures cleanly' {
        $c5 = Join-Path $tmpRoot 'c5'
        $vmRoot5 = Join-Path $c5 'disp_vm5'
        $base5 = $baseThreeVmSetup + "`n" + @'
$Global:smokeVms += [pscustomobject]@{ Name = 'Disp-Smoke-05'; Id = [guid]'66666666-6666-6666-6666-666666666666'; State = 'Running'; ConfigurationLocation = 'C:\Disp5' }
Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'guest_ready'; ps_direct_available = $true } }
'@
        $bsFail = $base5 + "`n" + 'Mock Invoke-VmLabGuestBootstrap { return [pscustomobject]@{ status = "failed" } }'
        $rBsFail = Invoke-SmokeDriver -CaseDir (Join-Path $c5 'bs') -MockSetupCode $bsFail -SmokeArgsCode "-VmName 'Disp-Smoke-05' -VmRoot '$vmRoot5' -Phase guest -AuthorizeDisposableTest"
        $rBsFail.exit_code | Should Be 1
        $rBsFail.json.status | Should Be 'acceptance_failed'
        $rBsFail.json.reason_code | Should Be 'guest_bootstrap_failed'

        $cpFail = $base5 + "`n" + @'
Mock Invoke-VmLabGuestBootstrap { return [pscustomobject]@{ status = 'bootstrapped' } }
Mock Test-VmLabGuestVerify { return [pscustomobject]@{ status = 'verified' } }
Mock Copy-VmLabGuestItem { throw 'SHA-256 verification failed after ToGuest copy.' }
'@
        $rCopyFail = Invoke-SmokeDriver -CaseDir (Join-Path $c5 'cp') -MockSetupCode $cpFail -SmokeArgsCode "-VmName 'Disp-Smoke-05' -VmRoot '$vmRoot5' -Phase guest -AuthorizeDisposableTest"
        $rCopyFail.exit_code | Should Be 1
        $rCopyFail.json.status | Should Be 'acceptance_failed'
        $rCopyFail.json.detail | Should Match 'SHA-256'

        $chkFail = $base5 + "`n" + @'
Mock Invoke-VmLabGuestBootstrap { return [pscustomobject]@{ status = 'bootstrapped' } }
Mock Test-VmLabGuestVerify { return [pscustomobject]@{ status = 'verified' } }
Mock Copy-VmLabGuestItem { return [pscustomobject]@{ status = 'copied'; sha256_verified = $true } }
Mock New-VmLabBaselineCheckpoint { throw 'Checkpoint creation failed.' }
'@
        $rChkFail = Invoke-SmokeDriver -CaseDir (Join-Path $c5 'chk') -MockSetupCode $chkFail -SmokeArgsCode "-VmName 'Disp-Smoke-05' -VmRoot '$vmRoot5' -Phase guest -AuthorizeDisposableTest"
        $rChkFail.exit_code | Should Be 1
        $rChkFail.json.status | Should Be 'acceptance_failed'
        $rChkFail.json.detail | Should Match 'Checkpoint creation failed'
    }
}
