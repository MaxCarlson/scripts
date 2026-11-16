#Requires -Version 7.0

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Split-Path -Parent $here
Import-Module (Join-Path $moduleRoot 'vm_lab.psd1') -Force

Describe 'vm_lab Phases 3-6 host/boot, guest/reboot, and workflow semantics' {
    $tmpRoot = Join-Path $moduleRoot '.pytest_tmp_root\pester_phase3_6'
    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

    It 'resolves VMs by name or GUID, verifies ISO SHA-256, and provides boot recovery guidance' {
        $isoFile = Join-Path $tmpRoot 'fake.iso'
        [System.IO.File]::WriteAllBytes($isoFile, [byte[]]::new(2048))
        $isoSha = (Get-FileHash -LiteralPath $isoFile -Algorithm SHA256).Hash.ToLowerInvariant()

        $okIso = Test-VmLabIsoMedia -IsoPath $isoFile -ExpectedSha256 $isoSha -MinSizeBytes 1024
        $okIso.status | Should Be 'SUCCEEDED'
        $badIso = Test-VmLabIsoMedia -IsoPath $isoFile -ExpectedSha256 ('0' * 64) -MinSizeBytes 1024
        $badIso.status | Should Be 'FAILED'
        $badIso.reason_code | Should Be 'iso_sha256_mismatch'

        InModuleScope vm_lab {
            Mock Get-VM { return @([pscustomobject]@{ Name = 'Disp-Boot-01'; Id = [guid]'12121212-1212-1212-1212-121212121212'; State = 'Off'; CheckpointType = 'Standard' }) }
            Mock Test-VmLabOwnership { return [pscustomobject]@{ owned = $true; reason = 'ok' } }
            Mock Get-VmLabBootDiagnostics { return [pscustomobject]@{ dvd_first_in_boot_order = $false } }

            $byGuid = Resolve-VmLabTargetVm -NameOrId '12121212-1212-1212-1212-121212121212'
            $byGuid.vm.Name | Should Be 'Disp-Boot-01'

            $rec = Get-VmLabBootRecovery -Name 'Disp-Boot-01'
            $rec.status | Should Be 'SUCCEEDED'
            $rec.recovery_steps.Count | Should Be 2

            $prepPlan = Set-VmLabFirmwareBootOrder -Name 'Disp-Boot-01' -PreferDvd
            $prepPlan.status | Should Be 'PLANNED'
        }
    }

    It 'honors script SHA-256, exit 3010 REBOOT_REQUIRED, checkpoint detail lookup, and workflow on_failure/non_repeatable semantics' {
        $scriptFile = Join-Path $tmpRoot 'install.ps1'
        [System.IO.File]::WriteAllText($scriptFile, 'exit 3010')
        $scriptSha = (Get-FileHash -LiteralPath $scriptFile -Algorithm SHA256).Hash.ToLowerInvariant()

        $env:VMLAB_P36_SCRIPT = $scriptFile
        $env:VMLAB_P36_SHA = $scriptSha
        $env:VMLAB_P36_ROOT = $tmpRoot

        InModuleScope vm_lab {
            $secPwd = ConvertTo-SecureString 'DummyPass123!' -AsPlainText -Force
            $cred = [pscredential]::new('Administrator', $secPwd)

            Mock Get-VM { return @([pscustomobject]@{ Name = 'Disp-P36-01'; Id = [guid]'34343434-3434-3434-3434-343434343434'; State = 'Running'; CheckpointType = 'Standard' }) }
            Mock Test-VmLabOwnership { return [pscustomobject]@{ owned = $true; reason = 'ok' } }
            Mock Copy-VmLabGuestItem { return [pscustomobject]@{ status = 'copied' } }
            Mock Resolve-VmLabGuestPowerShellPath { return 'C:\Program Files\PowerShell\7\pwsh.exe' }
            Mock Invoke-VmLabGuestCommand { return [pscustomobject]@{ status = 'FAILED'; reason_code = 'guest_command_nonzero_exit'; exit_code = 3010 } }

            $res3010 = Invoke-VmLabGuestScript -Name 'Disp-P36-01' -ScriptPath $env:VMLAB_P36_SCRIPT -ExpectedSha256 $env:VMLAB_P36_SHA -Reboot3010AsRebootRequired -Credential $cred -Apply -AuthorizeGuestExec
            $res3010.status | Should Be 'REBOOT_REQUIRED'
            $res3010.reason_code | Should Be 'installer_reboot_required_3010'

            Mock Get-VmLabCheckpoint { return @([pscustomobject]@{ vm_name = 'Disp-P36-01'; name = 'cp-a'; id = 'cp-id-a'; snapshot_type = 'Standard'; created_at = [datetime]::UtcNow }) }
            $cpDet = Get-VmLabCheckpointDetail -Name 'Disp-P36-01' -CheckpointId 'cp-id-a'
            $cpDet.status | Should Be 'SUCCEEDED'
            $cpDet.count | Should Be 1

            # Workflow on_failure cleanup_stage executes cleanup while retaining FAILED overall status
            $opRoot = Join-Path $env:VMLAB_P36_ROOT 'wf_on_fail'
            $wfPath = Join-Path $env:VMLAB_P36_ROOT 'on_fail.workflow.json'
            $wf = [ordered]@{
                schema_version = 1
                workflow_id    = 'on-failure-cleanup'
                operation_root = $opRoot
                vm             = [ordered]@{ name = 'Disp-P36-01'; template = 'windows11-dev'; root = (Join-Path $env:VMLAB_P36_ROOT 'vm') }
                commands       = [ordered]@{
                    failcmd = [ordered]@{ executable = 'C:\Guest\fail.exe' }
                    clean   = [ordered]@{ executable = 'C:\Guest\clean.exe' }
                }
                stages         = @(
                    [ordered]@{ id = 's_create'; type = 'vm.create'; depends_on = @(); capability = 'host_mutation' },
                    [ordered]@{ id = 's_start'; type = 'vm.start'; depends_on = @('s_create'); capability = 'vm_lifecycle' },
                    [ordered]@{ id = 's_wait'; type = 'guest.wait'; depends_on = @('s_start'); timeout_seconds = 15 },
                    [ordered]@{ id = 's_run'; type = 'guest.exec'; depends_on = @('s_wait'); command_ref = 'failcmd'; capability = 'guest_exec'; on_failure = 'cleanup_stage:s_clean'; idempotency_class = 'non_repeatable' },
                    [ordered]@{ id = 's_clean'; type = 'guest.exec'; depends_on = @('s_run'); command_ref = 'clean'; capability = 'guest_exec' }
                )
            }
            [System.IO.File]::WriteAllText($wfPath, ($wf | ConvertTo-Json -Depth 10))

            Mock Start-VmLabMachine { return [pscustomobject]@{ status = 'started' } }
            Mock Wait-VmLabGuestReady { return [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'guest_ready' } }
            $script:execCalls = @()
            Mock Invoke-VmLabGuestCommand {
                $script:execCalls += $ExecutablePath
                if ($ExecutablePath -match 'fail\.exe') {
                    return [pscustomobject]@{ status = 'FAILED'; reason_code = 'guest_command_nonzero_exit'; exit_code = 2 }
                }
                return [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'guest_command_ok'; exit_code = 0 }
            }

            $wfRes = Invoke-VmLabWorkflow -WorkflowPath $wfPath -OperationId 'op-onfail-01' -OperationRoot $opRoot -Credential $cred -Apply -AuthorizeHostMutation -AuthorizeVmLifecycle -AuthorizeGuestExec
            $wfRes.status | Should Be 'FAILED'
            $wfRes.stage_states.s_run | Should Be 'FAILED'
            $wfRes.stage_states.s_clean | Should Be 'SUCCEEDED'
            ($script:execCalls -join ',') | Should Match 'clean\.exe'
        }
        Remove-Item Env:VMLAB_P36_SCRIPT, Env:VMLAB_P36_SHA, Env:VMLAB_P36_ROOT -ErrorAction SilentlyContinue
    }
}

Describe 'vm_lab Invoke-VmLabGuestScript real Invoke-VmLabGuestCommand dispatch' {
    $tmpRoot = Join-Path $moduleRoot '.pytest_tmp_root\pester_phase3_6_dispatch'
    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

    It 'exercises Invoke-VmLabGuestScript through real Invoke-VmLabGuestCommand dispatch (missing pwsh, ok, nonzero, bad sha, timeout, 3010)' {
        $scriptFile = Join-Path $tmpRoot 'real_dispatch.ps1'
        [System.IO.File]::WriteAllText($scriptFile, 'Write-Output "ok"')
        $scriptSha = (Get-FileHash -LiteralPath $scriptFile -Algorithm SHA256).Hash.ToLowerInvariant()
        $env:VMLAB_RD_SCRIPT = $scriptFile
        $env:VMLAB_RD_SHA = $scriptSha

        InModuleScope vm_lab {
            $secPwd = ConvertTo-SecureString 'DummyPass123!' -AsPlainText -Force
            $cred = [pscredential]::new('Administrator', $secPwd)

            Mock Get-VM { return @([pscustomobject]@{ Name = 'Disp-RD-01'; Id = [guid]'56565656-5656-5656-5656-565656565656'; State = 'Running'; CheckpointType = 'Standard' }) }
            Mock Test-VmLabOwnership { return [pscustomobject]@{ owned = $true; reason = 'ok' } }
            Mock Copy-VmLabGuestItem { return [pscustomobject]@{ status = 'copied' } }
            Mock Invoke-VmLabGuestSession {
                param($VmId, $VmName, $Credential, $MaxConnectAttempts, $OpenTimeoutSeconds, $ScriptBlock)
                return & $ScriptBlock 'mock-session'
            }

            # 1. Invalid digest fails closed before touching guest
            $threwBadSha = $false
            try {
                Invoke-VmLabGuestScript -Name 'Disp-RD-01' -ScriptPath $env:VMLAB_RD_SCRIPT -ExpectedSha256 ('f' * 64) -Credential $cred -Apply -AuthorizeGuestExec
            } catch {
                $threwBadSha = $_.Exception.Message -match 'Script SHA-256 mismatch'
            }
            $threwBadSha | Should Be $true

            # 2. Missing PowerShell in guest
            Mock Invoke-VmLabPSSessionCommand { return $null }
            $missRes = Invoke-VmLabGuestScript -Name 'Disp-RD-01' -ScriptPath $env:VMLAB_RD_SCRIPT -ExpectedSha256 $env:VMLAB_RD_SHA -Credential $cred -Apply -AuthorizeGuestExec
            $missRes.status | Should Be 'FAILED'
            $missRes.reason_code | Should Be 'guest_powershell_not_found'

            # 3. Valid script execution (resolves C:\Program Files\PowerShell\7\pwsh.exe and passes through real Invoke-VmLabGuestCommand)
            $script:rdMode = 'ok'
            Mock Invoke-VmLabPSSessionCommand {
                param($Session, $ScriptBlock, $ArgumentList)
                if (-not $ArgumentList -or $ArgumentList.Count -eq 0) {
                    return 'C:\Program Files\PowerShell\7\pwsh.exe'
                }
                if ($script:rdMode -eq 'ok') {
                    return [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'guest_command_ok'; actual_sha256 = 'a' * 64; exit_code = 0; timed_out = $false; stdout = 'ok'; stderr = '' }
                } elseif ($script:rdMode -eq 'nonzero') {
                    return [pscustomobject]@{ status = 'FAILED'; reason_code = 'guest_command_nonzero_exit'; actual_sha256 = 'a' * 64; exit_code = 2; timed_out = $false; stdout = ''; stderr = 'boom' }
                } elseif ($script:rdMode -eq 'timeout') {
                    return [pscustomobject]@{ status = 'FAILED'; reason_code = 'guest_command_timeout'; actual_sha256 = 'a' * 64; exit_code = $null; timed_out = $true; stdout = ''; stderr = 'Timed out' }
                } else {
                    return [pscustomobject]@{ status = 'FAILED'; reason_code = 'guest_command_nonzero_exit'; actual_sha256 = 'a' * 64; exit_code = 3010; timed_out = $false; stdout = ''; stderr = '' }
                }
            }
            $okRes = Invoke-VmLabGuestScript -Name 'Disp-RD-01' -ScriptPath $env:VMLAB_RD_SCRIPT -ExpectedSha256 $env:VMLAB_RD_SHA -ArgumentList @('--flag', 'with space') -Credential $cred -Apply -AuthorizeGuestExec
            $okRes.status | Should Be 'SUCCEEDED'
            $okRes.executable | Should Be 'C:\Program Files\PowerShell\7\pwsh.exe'
            $okRes.exit_code | Should Be 0

            # 4. Nonzero exit
            $script:rdMode = 'nonzero'
            $nzRes = Invoke-VmLabGuestScript -Name 'Disp-RD-01' -ScriptPath $env:VMLAB_RD_SCRIPT -Credential $cred -Apply -AuthorizeGuestExec
            $nzRes.status | Should Be 'FAILED'
            $nzRes.exit_code | Should Be 2

            # 5. Timeout
            $script:rdMode = 'timeout'
            $toRes = Invoke-VmLabGuestScript -Name 'Disp-RD-01' -ScriptPath $env:VMLAB_RD_SCRIPT -TimeoutSeconds 5 -Credential $cred -Apply -AuthorizeGuestExec
            $toRes.status | Should Be 'FAILED'
            $toRes.reason_code | Should Be 'guest_command_timeout'
            $toRes.timed_out | Should Be $true

            # 6. Exit code 3010 -> REBOOT_REQUIRED
            $script:rdMode = '3010'
            $rebRes = Invoke-VmLabGuestScript -Name 'Disp-RD-01' -ScriptPath $env:VMLAB_RD_SCRIPT -Reboot3010AsRebootRequired -Credential $cred -Apply -AuthorizeGuestExec
            $rebRes.status | Should Be 'REBOOT_REQUIRED'
            $rebRes.reason_code | Should Be 'installer_reboot_required_3010'
            $rebRes.exit_code | Should Be 3010
        }
        Remove-Item Env:VMLAB_RD_SCRIPT, Env:VMLAB_RD_SHA -ErrorAction SilentlyContinue
    }
}
