#Requires -Version 7.0

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Split-Path -Parent $here
Import-Module (Join-Path $moduleRoot 'vm_lab.psd1') -Force

Describe 'vm_lab Phase 2 transactional lifecycle and checkpoints' {
    InModuleScope vm_lab {
        $secPwd = ConvertTo-SecureString 'DummyPass123!' -AsPlainText -Force
        $script:p2Cred = [pscredential]::new('Administrator', $secPwd)
        $script:p2Vm = [pscustomobject]@{
            Name                  = 'Disp-Phase2-VM'
            Id                    = [guid]'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
            State                 = 'Running'
            CheckpointType        = 'Standard'
            ConfigurationLocation = 'C:\VMs\Disp-Phase2-VM'
        }
        Mock Get-VM { return @($script:p2Vm) }
        Mock Test-VmLabOwnership { return [pscustomobject]@{ owned = $true; reason = 'ok' } }
        Mock Get-VmLabCheckpoint { return @() }
    }

    It 'enforces dry-run and vm_lifecycle authorization, and rejects non-Standard or duplicate checkpoints' {
        InModuleScope vm_lab {
            $plan = Invoke-VmLabCheckpointTransaction -Name 'Disp-Phase2-VM' -CheckpointName 'cp-tx-1'
            $plan.status | Should Be 'PLANNED'

            $blk = Invoke-VmLabCheckpointTransaction -Name 'Disp-Phase2-VM' -CheckpointName 'cp-tx-1' -Apply
            $blk.status | Should Be 'BLOCKED'
            $blk.reason_code | Should Be 'vm_lifecycle_authorization_required'

            $script:p2Vm.CheckpointType = 'Production'
            $nonStd = Invoke-VmLabCheckpointTransaction -Name 'Disp-Phase2-VM' -CheckpointName 'cp-tx-1' -Apply -AuthorizeVmLifecycle
            $nonStd.status | Should Be 'FAILED'
            $nonStd.reason_code | Should Be 'checkpoint_type_not_standard'
            $script:p2Vm.CheckpointType = 'Standard'

            Mock Get-VmLabCheckpoint { return @([pscustomobject]@{ checkpoint_name = 'cp-tx-1' }) }
            $dup = Invoke-VmLabCheckpointTransaction -Name 'Disp-Phase2-VM' -CheckpointName 'cp-tx-1' -Apply -AuthorizeVmLifecycle
            $dup.status | Should Be 'FAILED'
            $dup.reason_code | Should Be 'duplicate_checkpoint_name'
        }
    }

    It 'returns PARTIAL without checkpointing when graceful shutdown is not confirmed' {
        InModuleScope vm_lab {
            Mock Get-VmLabCheckpoint { return @() }
            Mock Stop-VmLabMachine { return [pscustomobject]@{ status = 'shutdown_requested'; state = 'Running' } }
            Mock New-VmLabCheckpoint { throw 'MUST_NOT_CHECKPOINT_ON_UNCONFIRMED_OFF' }

            $part = Invoke-VmLabCheckpointTransaction -Name 'Disp-Phase2-VM' -CheckpointName 'cp-tx-2' -Apply -AuthorizeVmLifecycle
            $part.status | Should Be 'PARTIAL'
            $part.reason_code | Should Be 'shutdown_not_confirmed'
        }
    }

    It 'completes Off -> Standard checkpoint -> Start -> Wait-VmLabGuestReady transaction and classifies auth/timeout failures' {
        InModuleScope vm_lab {
            Mock Get-VmLabCheckpoint { return @() }
            Mock Stop-VmLabMachine { return [pscustomobject]@{ status = 'stopped'; state = 'Off' } }
            Mock New-VmLabCheckpoint { return [pscustomobject]@{ status = 'created'; checkpoint_id = 'cp-guid-1'; checkpoint_name = 'cp-tx-3'; checkpoint_type = 'Standard' } }
            Mock Start-VmLabMachine { return [pscustomobject]@{ status = 'started'; state = 'Running' } }
            Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'guest_ready'; ps_direct_available = $true } }

            $ok = Invoke-VmLabCheckpointTransaction -Name 'Disp-Phase2-VM' -CheckpointName 'cp-tx-3' -RestartAfter -Credential $script:p2Cred -Apply -AuthorizeVmLifecycle
            $ok.status | Should Be 'SUCCEEDED'
            $ok.reason_code | Should Be 'lifecycle_transaction_complete'
            $ok.checkpoint_id | Should Be 'cp-guid-1'

            # Auth failure on restart readiness -> FAILED
            Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'ps_direct_auth_failed'; ps_direct_available = $false } }
            $authFail = Invoke-VmLabCheckpointTransaction -Name 'Disp-Phase2-VM' -CheckpointName 'cp-tx-4' -RestartAfter -Credential $script:p2Cred -Apply -AuthorizeVmLifecycle
            $authFail.status | Should Be 'FAILED'
            $authFail.reason_code | Should Be 'ps_direct_auth_failed'

            # Timeout on readiness -> PARTIAL
            Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'guest_booting'; ps_direct_available = $false; detail = 'still booting' } }
            $timeoutRes = Wait-VmLabGuestReady -Name 'Disp-Phase2-VM' -Credential $script:p2Cred -TimeoutSeconds 1 -PollIntervalMs 50
            $timeoutRes.status | Should Be 'PARTIAL'
            $timeoutRes.reason_code | Should Be 'guest_readiness_timeout'
        }
    }
}
