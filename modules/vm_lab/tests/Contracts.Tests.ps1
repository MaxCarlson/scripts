#Requires -Version 7.0

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Split-Path -Parent $here
Import-Module (Join-Path $moduleRoot 'vm_lab.psd1') -Force

Describe 'vm_lab Phase 0 contracts and schema validation' {
    $tmpRoot = Join-Path $moduleRoot '.pytest_tmp_root\pester_contracts'
    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

    function Assert-ThrowsMatch {
        param([scriptblock]$Block, [string]$Pattern)
        $threw = $false
        $msg = ''
        try {
            $null = & $Block
        } catch {
            $threw = $true
            $msg = $_.Exception.Message
        }
        $threw | Should Be $true
        if ($Pattern) {
            $msg | Should Match $Pattern
        }
    }

    It 'validates safe paths and rejects UNC, traversal, outside-root, and reparse points' {
        $inside = Join-Path $tmpRoot 'sub\file.json'
        (Test-VmLabSafePath -Path $inside -Label 'test' -WithinRoot $tmpRoot) | Should Be ([System.IO.Path]::GetFullPath($inside))

        Assert-ThrowsMatch { Test-VmLabSafePath -Path '\\server\share\file.json' -Label 'test' } 'UNC'
        Assert-ThrowsMatch { Test-VmLabSafePath -Path 'C:\VMs\..\Other\file.json' -Label 'test' } 'traversal'
        Assert-ThrowsMatch { Test-VmLabSafePath -Path 'relative\file.json' -Label 'test' } 'drive letter'
        Assert-ThrowsMatch { Test-VmLabSafePath -Path 'C:\Outside\file.json' -Label 'test' -WithinRoot $tmpRoot } 'must reside within'
    }

    It 'validates a well-formed workflow DAG and produces deterministic canonical SHA-256' {
        $wf = [pscustomobject]@{
            schema_version = 1
            workflow_id    = 'synthetic-h4-like'
            operation_root = 'C:\VM-Lab-Operations'
            vm             = [pscustomobject]@{
                template       = 'windows11-dev'
                name           = 'Disp-Workflow-01'
                root           = 'C:\VMs\Disp-Workflow-01'
                network_policy = 'disconnected'
            }
            commands       = [pscustomobject]@{
                accept = [pscustomobject]@{
                    executable = 'C:\TestRoot\runner.exe'
                }
            }
            stages         = @(
                [pscustomobject]@{ id = 'pre'; type = 'host.preflight'; depends_on = @() },
                [pscustomobject]@{ id = 'create'; type = 'vm.create'; depends_on = @('pre'); capability = 'host_mutation' },
                [pscustomobject]@{ id = 'start'; type = 'vm.start'; depends_on = @('create'); capability = 'vm_lifecycle' },
                [pscustomobject]@{ id = 'wait1'; type = 'guest.wait'; depends_on = @('start') },
                [pscustomobject]@{ id = 'deploy'; type = 'artifact.deploy'; depends_on = @('wait1'); manifest = 'artifacts.json'; capability = 'guest_mutation' },
                [pscustomobject]@{ id = 'cp'; type = 'vm.checkpoint_transaction'; depends_on = @('deploy'); require_off = $true; restart_after = $true; capability = 'vm_lifecycle' },
                [pscustomobject]@{ id = 'wait2'; type = 'guest.wait'; depends_on = @('cp') },
                [pscustomobject]@{ id = 'exec'; type = 'guest.exec'; depends_on = @('wait2'); command_ref = 'accept'; capability = 'guest_exec' },
                [pscustomobject]@{ id = 'ev'; type = 'evidence.collect'; depends_on = @('exec') }
            )
        }
        $res1 = Test-VmLabWorkflowSchema -Definition $wf
        $res2 = Test-VmLabWorkflowSchema -Definition $wf
        $res1.valid | Should Be $true
        $res1.workflow_digest | Should Be $res2.workflow_digest
        ($res1.stage_order -join ',') | Should Be 'pre,create,start,wait1,deploy,cp,wait2,exec,ev'
    }

    It 'rejects malformed workflow schemas, cycles, protected VMs, and invalid power-state edges' {
        $badKey = [pscustomobject]@{
            schema_version = 1
            workflow_id    = 'bad-key'
            operation_root = 'C:\VM-Lab-Operations'
            unexpected     = $true
            vm             = [pscustomobject]@{ name = 'Disp-01'; root = 'C:\VMs\Disp-01' }
            stages         = @([pscustomobject]@{ id = 'pre'; type = 'host.preflight'; depends_on = @() })
        }
        Assert-ThrowsMatch { Test-VmLabWorkflowSchema -Definition $badKey } 'Unknown workflow definition key'

        $badOp = [pscustomobject]@{
            schema_version = 1
            workflow_id    = 'bad-op'
            operation_root = 'C:\VM-Lab-Operations'
            vm             = [pscustomobject]@{ name = 'Disp-01'; root = 'C:\VMs\Disp-01' }
            stages         = @([pscustomobject]@{ id = 's1'; type = 'host.powershell_arbitrary'; depends_on = @() })
        }
        Assert-ThrowsMatch { Test-VmLabWorkflowSchema -Definition $badOp } 'Unknown workflow stage type'

        $protectedVm = [pscustomobject]@{
            schema_version = 1
            workflow_id    = 'prot-vm'
            operation_root = 'C:\VM-Lab-Operations'
            vm             = [pscustomobject]@{ name = 'RC-H4-Windows-Acceptance'; root = 'C:\VMs\H4' }
            stages         = @([pscustomobject]@{ id = 'pre'; type = 'host.preflight'; depends_on = @() })
        }
        Assert-ThrowsMatch { Test-VmLabWorkflowSchema -Definition $protectedVm } 'protected VM name'

        $cycle = [pscustomobject]@{
            schema_version = 1
            workflow_id    = 'cycle-wf'
            operation_root = 'C:\VM-Lab-Operations'
            vm             = [pscustomobject]@{ name = 'Disp-01'; root = 'C:\VMs\Disp-01' }
            stages         = @(
                [pscustomobject]@{ id = 'a'; type = 'host.preflight'; depends_on = @('b') },
                [pscustomobject]@{ id = 'b'; type = 'host.preflight'; depends_on = @('a') }
            )
        }
        Assert-ThrowsMatch { Test-VmLabWorkflowSchema -Definition $cycle } 'cycle'

        $badPower = [pscustomobject]@{
            schema_version = 1
            workflow_id    = 'bad-power'
            operation_root = 'C:\VM-Lab-Operations'
            vm             = [pscustomobject]@{ name = 'Disp-01'; root = 'C:\VMs\Disp-01' }
            commands       = [pscustomobject]@{ run = [pscustomobject]@{ executable = 'C:\Test\app.exe' } }
            stages         = @(
                [pscustomobject]@{ id = 'create'; type = 'vm.create'; depends_on = @() },
                [pscustomobject]@{ id = 'exec'; type = 'guest.exec'; depends_on = @('create'); command_ref = 'run' }
            )
        }
        Assert-ThrowsMatch { Test-VmLabWorkflowSchema -Definition $badPower } 'Invalid power-state edge'
    }

    It 'validates artifact manifests, operation journals, stage receipts, and capability boundaries' {
        $manifest = [pscustomobject]@{
            schema_version = 1
            manifest_id    = 'bundle-1'
            artifacts      = @(
                [pscustomobject]@{
                    relative_path = 'wheels/pkg.whl'
                    sha256        = ('a' * 64)
                    length        = 1024
                }
            )
        }
        $mRes = Test-VmLabArtifactManifestSchema -Manifest $manifest
        $mRes.valid | Should Be $true

        $badManifest = [pscustomobject]@{
            schema_version = 1
            artifacts      = @([pscustomobject]@{ relative_path = '..\escape.exe'; sha256 = ('b' * 64); length = 10 })
        }
        Assert-ThrowsMatch { Test-VmLabArtifactManifestSchema -Manifest $badManifest } 'Invalid artifact relative_path'

        $journal = [pscustomobject]@{
            schema_version  = 1
            operation_id    = 'op-001'
            workflow_id     = 'wf-001'
            workflow_digest = ('c' * 64)
            vm_id           = '11111111-1111-1111-1111-111111111111'
            vm_name         = 'Disp-01'
            vm_config_path  = 'C:\VMs\Disp-01'
            overall_state   = 'RUNNING'
            stage_states    = [pscustomobject]@{}
        }
        (Test-VmLabOperationJournalSchema -Journal $journal -ExpectedOperationId 'op-001' -ExpectedVmId '11111111-1111-1111-1111-111111111111' -ExpectedWorkflowDigest ('c' * 64)) | Should Be $true
        Assert-ThrowsMatch { Test-VmLabOperationJournalSchema -Journal $journal -ExpectedOperationId 'op-002' } 'does not match'
        Assert-ThrowsMatch { Test-VmLabOperationJournalSchema -Journal $journal -ExpectedVmId '22222222-2222-2222-2222-222222222222' } 'does not match'

        $receipt = [pscustomobject]@{
            schema_version = 1
            operation_id   = 'op-001'
            stage_id       = 's1'
            stage_type     = 'host.preflight'
            attempt        = 1
            vm_id          = '11111111-1111-1111-1111-111111111111'
            result_status  = 'SUCCEEDED'
            reason_code    = 'ok'
        }
        (Test-VmLabStageReceiptSchema -Receipt $receipt -ExpectedOperationId 'op-001' -ExpectedStageId 's1' -ExpectedVmId '11111111-1111-1111-1111-111111111111') | Should Be $true
        Assert-ThrowsMatch { Test-VmLabStageReceiptSchema -Receipt $receipt -ExpectedVmId '22222222-2222-2222-2222-222222222222' } 'does not match'

        # -Apply alone must not authorize guest_exec, vm_lifecycle, host_mutation, or elevation
        (Test-VmLabCapabilityAuthorized -Capability 'none') | Should Be $true
        (Test-VmLabCapabilityAuthorized -Capability 'guest_exec' -Apply) | Should Be $false
        (Test-VmLabCapabilityAuthorized -Capability 'guest_exec' -Apply -AuthorizeGuestExec) | Should Be $true
        (Test-VmLabCapabilityAuthorized -Capability 'vm_lifecycle' -Apply -AuthorizeHostMutation) | Should Be $false
        (Test-VmLabCapabilityAuthorized -Capability 'vm_lifecycle' -Apply -AuthorizeVmLifecycle) | Should Be $true
    }
}
