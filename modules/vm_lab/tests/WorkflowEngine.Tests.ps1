#Requires -Version 7.0

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Split-Path -Parent $here
Import-Module (Join-Path $moduleRoot 'vm_lab.psd1') -Force

Describe 'vm_lab Phase 3 durable workflow engine, receipts, and resumable execution' {
    $tmpRoot = Join-Path $moduleRoot '.pytest_tmp_root\pester_workflow'
    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

    It 'validates the example H4-like workflow definition via CLI workflow-plan -Json' {
        $cliScript = Join-Path $moduleRoot 'Invoke-VmLab.ps1'
        $exPath = Join-Path $moduleRoot 'examples\h4-like-acceptance.workflow.json'
        $out = & pwsh -NoProfile -File $cliScript -o workflow-plan -f $exPath -j
        $LASTEXITCODE | Should Be 0
        $parsed = ($out -join "`n") | ConvertFrom-Json
        $parsed.status | Should Be 'PLANNED'
        $parsed.workflow_id | Should Be 'h4-like-windows-acceptance'
        $parsed.stage_order.Count | Should Be 11
    }

    It 'executes synthetic H4-like workflow across AWAITING_INTERACTION, capability gate BLOCKED, and idempotent resume to SUCCEEDED' {
        $opRoot = Join-Path $tmpRoot 'ops'
        $stageDir = Join-Path $tmpRoot 'stage'
        $vmDir = Join-Path $tmpRoot 'vm_disp'
        New-Item -ItemType Directory -Path $stageDir -Force | Out-Null
        New-Item -ItemType Directory -Path $vmDir -Force | Out-Null
        $payloadFile = Join-Path $stageDir 'runner.exe'
        [System.IO.File]::WriteAllText($payloadFile, 'synthetic-runner-bytes')
        $manObj = New-VmLabArtifactManifest -SourceRoot $stageDir -DestinationRoot 'C:\GuestWork\accept'
        $manPath = Join-Path $stageDir 'artifacts.json'
        [System.IO.File]::WriteAllText($manPath, ($manObj | ConvertTo-Json -Depth 10))

        $wfObj = [ordered]@{
            schema_version = 1
            workflow_id    = 'synth-h4-e2e'
            operation_root = $opRoot
            vm             = [ordered]@{
                template = 'windows11-dev'
                name     = 'Disp-WF-01'
                root     = $vmDir
            }
            commands       = [ordered]@{
                accept = [ordered]@{
                    executable = 'C:\GuestWork\accept\runner.exe'
                    args       = @('--profile', 'full')
                }
            }
            stages         = @(
                [ordered]@{ id = 'pre'; type = 'host.preflight'; depends_on = @() },
                [ordered]@{ id = 'create'; type = 'vm.create'; depends_on = @('pre'); capability = 'host_mutation' },
                [ordered]@{ id = 'handoff'; type = 'windows.install_handoff'; depends_on = @('create') },
                [ordered]@{ id = 'start'; type = 'vm.start'; depends_on = @('handoff'); capability = 'vm_lifecycle' },
                [ordered]@{ id = 'wait1'; type = 'guest.wait'; depends_on = @('start') },
                [ordered]@{ id = 'deploy'; type = 'artifact.deploy'; depends_on = @('wait1'); manifest = $manPath; capability = 'guest_mutation' },
                [ordered]@{ id = 'cp'; type = 'vm.checkpoint_transaction'; depends_on = @('deploy'); checkpoint_name = 'cp-base'; require_off = $true; restart_after = $true; capability = 'vm_lifecycle' },
                [ordered]@{ id = 'wait2'; type = 'guest.wait'; depends_on = @('cp') },
                [ordered]@{ id = 'exec'; type = 'guest.exec'; depends_on = @('wait2'); command_ref = 'accept'; expected_status = 'passed'; capability = 'guest_exec' },
                [ordered]@{ id = 'ev'; type = 'evidence.collect'; depends_on = @('exec'); sources = @('C:\GuestWork\ev'); capability = 'host_mutation' },
                [ordered]@{ id = 'assert'; type = 'workflow.assert'; depends_on = @('ev'); assertions = @('all_passed') }
            )
        }
        $wfPath = Join-Path $tmpRoot 'synth.workflow.json'
        [System.IO.File]::WriteAllText($wfPath, ($wfObj | ConvertTo-Json -Depth 10))

        $env:VMLAB_WF_PATH = $wfPath
        $env:VMLAB_OP_ROOT = $opRoot
        InModuleScope vm_lab {
            $secPwd = ConvertTo-SecureString 'DummyPass123!' -AsPlainText -Force
            $cred = [pscredential]::new('Administrator', $secPwd)
            $script:wfVmId = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
            $script:wfVmExists = $false
            $script:createCalls = 0
            $script:cpCalls = 0

            Mock Get-VM {
                if ($script:wfVmExists) {
                    return @([pscustomobject]@{ Name = 'Disp-WF-01'; Id = [guid]$script:wfVmId; State = 'Running'; CheckpointType = 'Standard'; ConfigurationLocation = 'C:\VMs\Disp-WF-01' })
                }
                return @()
            }
            Mock Test-VmLabPlan { return [pscustomobject]@{ ready = $true } }
            Mock Test-VmLabOwnership { return [pscustomobject]@{ owned = $true; reason = 'ok' } }
            Mock New-VmLabMachine {
                $script:createCalls++
                $script:wfVmExists = $true
                return [pscustomobject]@{ status = 'created'; vm_id = $script:wfVmId; vm_name = 'Disp-WF-01' }
            }
            Mock Start-VmLabMachine { return [pscustomobject]@{ status = 'started'; state = 'Running' } }
            Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'guest_ready'; ps_direct_available = $true } }
            Mock Wait-VmLabGuestReady { return [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'guest_ready' } }
            Mock Publish-VmLabArtifactBundle { return [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'artifacts_deployed_verified' } }
            Mock Get-VmLabCheckpoint { return @() }
            Mock Invoke-VmLabCheckpointTransaction {
                $script:cpCalls++
                return [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'lifecycle_transaction_complete'; checkpoint_id = 'cp-1' }
            }
            Mock Invoke-VmLabGuestCommand {
                return [pscustomobject]@{
                    status      = 'SUCCEEDED'
                    reason_code = 'guest_command_ok'
                    exit_code   = 0
                    stdout      = '{"status":"passed"}'
                    stderr      = ''
                    parsed_json = [pscustomobject]@{ status = 'passed' }
                }
            }
            Mock Receive-VmLabGuestEvidence { return [pscustomobject]@{ status = 'EVIDENCE_COMPLETE'; reason_code = 'evidence_complete'; collected_count = 1 } }

            # Run 1: pauses at windows.install_handoff (AWAITING_INTERACTION) because no Credential supplied
            $r1 = Invoke-VmLabWorkflow -WorkflowPath $env:VMLAB_WF_PATH -OperationId 'op-synth-01' -OperationRoot $env:VMLAB_OP_ROOT -Apply -AuthorizeHostMutation
            $r1.status | Should Be 'AWAITING_INTERACTION'
            $script:createCalls | Should Be 1

            # Run 2: resume with Credential + vm_lifecycle + guest_mutation, WITHOUT guest_exec -> blocks at exec
            $r2 = Invoke-VmLabWorkflow -OperationId 'op-synth-01' -OperationRoot $env:VMLAB_OP_ROOT -Credential $cred -Resume -Apply -AuthorizeVmLifecycle -AuthorizeGuestMutation
            $r2.status | Should Be 'BLOCKED'
            $r2.reason_code | Should Be 'capability_required_guest_exec'
            $script:createCalls | Should Be 1
            $script:cpCalls | Should Be 1

            # Run 3: resume with -AuthorizeGuestExec + -AuthorizeHostMutation -> completes without re-creating VM or re-checkpointing
            $r3 = Invoke-VmLabWorkflow -OperationId 'op-synth-01' -OperationRoot $env:VMLAB_OP_ROOT -Credential $cred -Resume -Apply -AuthorizeGuestExec -AuthorizeHostMutation
            $r3.status | Should Be 'SUCCEEDED'
            $script:createCalls | Should Be 1
            $script:cpCalls | Should Be 1

            $st = Get-VmLabWorkflowStatus -OperationId 'op-synth-01' -OperationRoot $env:VMLAB_OP_ROOT
            $st.status | Should Be 'SUCCEEDED'
            $doc = Get-VmLabWorkflowDoctor -OperationId 'op-synth-01' -OperationRoot $env:VMLAB_OP_ROOT
            $doc.status | Should Be 'SUCCEEDED'
        }
    }

    It 'detects stale operation locks and corrupt journals via workflow-doctor' {
        $opRoot = Join-Path $tmpRoot 'ops_doctor'
        $opDir = Join-Path $opRoot 'op-bad-01'
        New-Item -ItemType Directory -Path $opDir -Force | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $opDir 'operation.lock'), '{"operation_id":"op-bad-01","pid":999999,"host":"TEST"}')
        [System.IO.File]::WriteAllText((Join-Path $opDir 'operation.json'), '{not-valid-json')

        $doc = Get-VmLabWorkflowDoctor -OperationId 'op-bad-01' -OperationRoot $opRoot
        $doc.status | Should Be 'INVALIDATED'
        $doc.reason_code | Should Be 'journal_corrupt'
        $doc.findings.Count | Should Be 2
    }

    It 'rejects operation_id collision, digest/vm_id mismatch, missing expected_json status, and reconciles crash-before-receipt on resume' {
        $opRoot = Join-Path $tmpRoot 'ops_crash_reconcile'
        $wfPath = Join-Path $tmpRoot 'crash_reconcile.workflow.json'
        $wfDef = [ordered]@{
            schema_version = 1
            workflow_id    = 'crash-reconcile-test'
            operation_root = $opRoot
            vm             = [ordered]@{
                name     = 'Disp-Reconcile-01'
                template = 'windows11-dev'
                root     = (Join-Path $tmpRoot 'vm_reconcile')
            }
            stages         = @(
                [ordered]@{ id = 's_create'; type = 'vm.create'; depends_on = @(); capability = 'host_mutation' },
                [ordered]@{ id = 's_cp'; type = 'vm.checkpoint_transaction'; depends_on = @('s_create'); capability = 'vm_lifecycle'; checkpoint_name = 'cp-baseline'; require_off = $true; restart_after = $false },
                [ordered]@{ id = 's_verify'; type = 'workflow.assert'; depends_on = @('s_cp'); capability = 'none'; assertions = @('all_prior_stages_succeeded') }
            )
        }
        [System.IO.File]::WriteAllText($wfPath, ($wfDef | ConvertTo-Json -Depth 10))
        $plan = Test-VmLabWorkflowPlan -WorkflowPath $wfPath

        # ExpectedWorkflowDigest mismatch fails closed
        $threwDigest = $false
        try {
            Invoke-VmLabWorkflow -WorkflowPath $wfPath -OperationId 'op-digest-bad' -OperationRoot $opRoot -ExpectedWorkflowDigest ('0' * 64) -Apply -AuthorizeHostMutation
        } catch {
            $threwDigest = $_.Exception.Message -match 'workflow_digest_mismatch'
        }
        $threwDigest | Should Be $true

        # Pre-seed journal as if host crashed AFTER vm.create and cp-baseline were created, BEFORE receipts/journal were marked SUCCEEDED
        $opDir = Join-Path $opRoot 'op-crash-01'
        New-Item -ItemType Directory -Path $opDir -Force | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $opDir 'workflow.json'), ($wfDef | ConvertTo-Json -Depth 10))
        $seedJournal = [ordered]@{
            schema_version  = 1
            operation_id    = 'op-crash-01'
            workflow_id     = 'crash-reconcile-test'
            workflow_digest = $plan.workflow_digest
            host_identity   = $env:COMPUTERNAME
            vm_id           = 'aaaaaaaa-1111-2222-3333-444444444444'
            vm_name         = 'Disp-Reconcile-01'
            vm_config_path  = $wfDef.vm.root
            created_at      = [DateTimeOffset]::UtcNow.ToString('o')
            updated_at      = [DateTimeOffset]::UtcNow.ToString('o')
            overall_state   = 'RUNNING'
            stage_states    = [ordered]@{ s_create = 'PLANNED'; s_cp = 'PLANNED'; s_verify = 'PLANNED' }
            evidence_index  = @()
            last_error      = $null
        }
        [System.IO.File]::WriteAllText((Join-Path $opDir 'operation.json'), ($seedJournal | ConvertTo-Json -Depth 10))

        # Non-resume apply with colliding OperationId must fail
        $threwCollision = $false
        try {
            Invoke-VmLabWorkflow -WorkflowPath $wfPath -OperationId 'op-crash-01' -OperationRoot $opRoot -Apply -AuthorizeHostMutation
        } catch {
            $threwCollision = $_.Exception.Message -match 'operation_id_collision'
        }
        $threwCollision | Should Be $true

        # ExpectedVmId mismatch on resume fails closed
        $threwVmId = $false
        try {
            Invoke-VmLabWorkflow -OperationId 'op-crash-01' -OperationRoot $opRoot -ExpectedVmId 'bbbbbbbb-1111-2222-3333-444444444444' -Resume -Apply -AuthorizeHostMutation -AuthorizeVmLifecycle
        } catch {
            $threwVmId = $_.Exception.Message -match 'vm_id_mismatch'
        }
        $threwVmId | Should Be $true

        # Resume with mocked existing owned VM + existing Standard checkpoint reconciles without creating duplicates
        $env:VMLAB_TEST_ROOT = $tmpRoot
        InModuleScope vm_lab {
            Mock Get-VM { return @([pscustomobject]@{ Name = 'Disp-Reconcile-01'; Id = 'aaaaaaaa-1111-2222-3333-444444444444'; State = 'Off'; CheckpointType = 'Standard' }) }
            Mock Test-VmLabOwnership { return [pscustomobject]@{ owned = $true; reason = 'ok' } }
            Mock New-VmLabMachine { throw 'New-VmLabMachine should not be called during reconciliation' }
            Mock Get-VmLabCheckpoint { return @([pscustomobject]@{ vm_name = 'Disp-Reconcile-01'; name = 'cp-baseline'; id = 'cp-1111'; snapshot_type = 'Standard'; created_at = [datetime]::UtcNow }) }
            Mock Invoke-VmLabCheckpointTransaction { throw 'Invoke-VmLabCheckpointTransaction should not be called during reconciliation' }

            $res = Invoke-VmLabWorkflow -OperationId 'op-crash-01' -OperationRoot (Join-Path $env:VMLAB_TEST_ROOT 'ops_crash_reconcile') -ExpectedVmId 'aaaaaaaa-1111-2222-3333-444444444444' -Resume -Apply -AuthorizeHostMutation -AuthorizeVmLifecycle
            $res.status | Should Be 'SUCCEEDED'
            $res.stage_states.s_create | Should Be 'SUCCEEDED'
            $res.stage_states.s_cp | Should Be 'SUCCEEDED'
            $res.stage_states.s_verify | Should Be 'SUCCEEDED'
        }
        Remove-Item Env:VMLAB_TEST_ROOT -ErrorAction SilentlyContinue
    }

    It 'blocks every mutating operation when its mandatory capability is missing or substituted, and performs zero mutations in dry-run/-WhatIf' {
        $env:VMLAB_CAP_ROOT = Join-Path $tmpRoot 'ops_cap_matrix'
        New-Item -ItemType Directory -Path $env:VMLAB_CAP_ROOT -Force | Out-Null
        $manFile = Join-Path $env:VMLAB_CAP_ROOT 'm.json'
        [System.IO.File]::WriteAllText($manFile, '{"schema_version":1,"manifest_id":"m1","destination_root":"C:\\Guest","artifacts":[]}')
        $env:VMLAB_CAP_MANIFEST = $manFile

        InModuleScope vm_lab {
            Mock New-VmLabMachine { throw 'MUST_NOT_CALL_New-VmLabMachine' }
            Mock Start-VmLabMachine { throw 'MUST_NOT_CALL_Start-VmLabMachine' }
            Mock Stop-VmLabMachine { throw 'MUST_NOT_CALL_Stop-VmLabMachine' }
            Mock Invoke-VmLabCheckpointTransaction { throw 'MUST_NOT_CALL_Invoke-VmLabCheckpointTransaction' }
            Mock Publish-VmLabArtifactBundle { throw 'MUST_NOT_CALL_Publish-VmLabArtifactBundle' }
            Mock Invoke-VmLabGuestBootstrap { throw 'MUST_NOT_CALL_Invoke-VmLabGuestBootstrap' }
            Mock Invoke-VmLabGuestCommand { throw 'MUST_NOT_CALL_Invoke-VmLabGuestCommand' }
            Mock Receive-VmLabGuestEvidence { throw 'MUST_NOT_CALL_Receive-VmLabGuestEvidence' }

            $cases = @(
                @{ op = 'vm.create'; cap = 'host_mutation'; extra = @{}; pre = @() },
                @{ op = 'vm.start'; cap = 'vm_lifecycle'; extra = @{}; pre = @([ordered]@{ id = 'p_create'; type = 'vm.create'; depends_on = @(); capability = 'host_mutation' }) },
                @{ op = 'vm.shutdown'; cap = 'vm_lifecycle'; extra = @{}; pre = @([ordered]@{ id = 'p_create'; type = 'vm.create'; depends_on = @(); capability = 'host_mutation' }, [ordered]@{ id = 'p_start'; type = 'vm.start'; depends_on = @('p_create'); capability = 'vm_lifecycle' }) },
                @{ op = 'vm.checkpoint_transaction'; cap = 'vm_lifecycle'; extra = @{ checkpoint_name = 'cp1' }; pre = @([ordered]@{ id = 'p_create'; type = 'vm.create'; depends_on = @(); capability = 'host_mutation' }) },
                @{ op = 'artifact.deploy'; cap = 'guest_mutation'; extra = @{ manifest = $env:VMLAB_CAP_MANIFEST }; pre = @([ordered]@{ id = 'p_create'; type = 'vm.create'; depends_on = @(); capability = 'host_mutation' }, [ordered]@{ id = 'p_start'; type = 'vm.start'; depends_on = @('p_create'); capability = 'vm_lifecycle' }, [ordered]@{ id = 'p_wait'; type = 'guest.wait'; depends_on = @('p_start') }) },
                @{ op = 'guest.bootstrap'; cap = 'guest_mutation'; extra = @{ profile = 'windows-minimal' }; pre = @([ordered]@{ id = 'p_create'; type = 'vm.create'; depends_on = @(); capability = 'host_mutation' }, [ordered]@{ id = 'p_start'; type = 'vm.start'; depends_on = @('p_create'); capability = 'vm_lifecycle' }, [ordered]@{ id = 'p_wait'; type = 'guest.wait'; depends_on = @('p_start') }) },
                @{ op = 'guest.exec'; cap = 'guest_exec'; extra = @{ command_ref = 'run' }; pre = @([ordered]@{ id = 'p_create'; type = 'vm.create'; depends_on = @(); capability = 'host_mutation' }, [ordered]@{ id = 'p_start'; type = 'vm.start'; depends_on = @('p_create'); capability = 'vm_lifecycle' }, [ordered]@{ id = 'p_wait'; type = 'guest.wait'; depends_on = @('p_start') }) },
                @{ op = 'evidence.collect'; cap = 'host_mutation'; extra = @{ sources = @('C:\Guest\ev') }; pre = @([ordered]@{ id = 'p_create'; type = 'vm.create'; depends_on = @(); capability = 'host_mutation' }, [ordered]@{ id = 'p_start'; type = 'vm.start'; depends_on = @('p_create'); capability = 'vm_lifecycle' }, [ordered]@{ id = 'p_wait'; type = 'guest.wait'; depends_on = @('p_start') }) }
            )
            foreach ($c in $cases) {
                $wfFile = Join-Path $env:VMLAB_CAP_ROOT "cap_$($c.op).workflow.json"
                $deps = [System.Collections.Generic.List[string]]::new()
                if ($c.pre -and $c.pre.Count -gt 0) { $deps.Add([string]$c.pre[$c.pre.Count - 1]['id']) }
                $stage = [ordered]@{ id = 's1'; type = $c.op; depends_on = $deps; capability = $c.cap }
                foreach ($ek in $c.extra.Keys) { $stage[$ek] = $c.extra[$ek] }
                $allStages = [System.Collections.Generic.List[object]]::new()
                foreach ($ps in @($c.pre)) { $allStages.Add($ps) }
                $allStages.Add($stage)
                $wf = [ordered]@{
                    schema_version = 1
                    workflow_id    = "cap-test-$($c.op -replace '\.','-')"
                    operation_root = $env:VMLAB_CAP_ROOT
                    vm             = [ordered]@{ name = 'Disp-Cap-01'; template = 'windows11-dev'; root = (Join-Path $env:VMLAB_CAP_ROOT 'vm') }
                    commands       = [ordered]@{ run = [ordered]@{ executable = 'C:\Guest\app.exe' } }
                    stages         = $allStages
                }
                [System.IO.File]::WriteAllText($wfFile, ($wf | ConvertTo-Json -Depth 10))

                # Dry-run and -WhatIf must never invoke mutating mocks
                $dry = Invoke-VmLabWorkflow -WorkflowPath $wfFile -OperationId "dry-$($c.op)" -OperationRoot $env:VMLAB_CAP_ROOT
                $dry.status | Should Be 'PLANNED'
                $wi = Invoke-VmLabWorkflow -WorkflowPath $wfFile -OperationId "wi-$($c.op)" -OperationRoot $env:VMLAB_CAP_ROOT -Apply -AuthorizeHostMutation -AuthorizeVmLifecycle -AuthorizeGuestMutation -AuthorizeGuestExec -WhatIf
                $wi.status | Should Be 'PLANNED'

                # Pre-seed prior stages as SUCCEEDED so we isolate the target stage s1's authorization gate
                $blkOpId = "blk-$($c.op)"
                $blkDir = Join-Path $env:VMLAB_CAP_ROOT $blkOpId
                New-Item -ItemType Directory -Path (Join-Path $blkDir 'receipts') -Force | Out-Null
                [System.IO.File]::WriteAllText((Join-Path $blkDir 'workflow.json'), ($wf | ConvertTo-Json -Depth 10))
                $planObj = Test-VmLabWorkflowPlan -WorkflowPath $wfFile
                $stMap = [ordered]@{}
                foreach ($ps in $c.pre) {
                    $stMap[$ps.id] = 'SUCCEEDED'
                    $pRecDir = Join-Path $blkDir "receipts\$($ps.id)"
                    New-Item -ItemType Directory -Path $pRecDir -Force | Out-Null
                    $pRec = [ordered]@{ schema_version = 1; operation_id = $blkOpId; stage_id = $ps.id; stage_type = $ps.type; attempt = 1; vm_id = '11111111-1111-1111-1111-111111111111'; result_status = 'SUCCEEDED'; reason_code = 'ok' }
                    [System.IO.File]::WriteAllText((Join-Path $pRecDir '1.json'), ($pRec | ConvertTo-Json -Depth 5))
                }
                $stMap['s1'] = 'PLANNED'
                $blkJournal = [ordered]@{
                    schema_version = 1; operation_id = $blkOpId; workflow_id = $planObj.workflow_id; workflow_digest = $planObj.workflow_digest
                    vm_id = '11111111-1111-1111-1111-111111111111'; vm_name = 'Disp-Cap-01'; vm_config_path = $wf.vm.root
                    created_at = [DateTimeOffset]::UtcNow.ToString('o'); updated_at = [DateTimeOffset]::UtcNow.ToString('o')
                    overall_state = 'RUNNING'; stage_states = $stMap; evidence_index = @(); last_error = $null
                }
                [System.IO.File]::WriteAllText((Join-Path $blkDir 'operation.json'), ($blkJournal | ConvertTo-Json -Depth 10))
                Mock Get-VM { return @([pscustomobject]@{ Name = 'Disp-Cap-01'; Id = '11111111-1111-1111-1111-111111111111'; State = 'Running'; CheckpointType = 'Standard' }) }

                # Grant every capability EXCEPT the required one -> must BLOCK without calling mock
                $authArgs = @{
                    OperationId            = $blkOpId
                    OperationRoot          = $env:VMLAB_CAP_ROOT
                    Resume                 = $true
                    Apply                  = $true
                    AuthorizeHostMutation  = ($c.cap -ne 'host_mutation')
                    AuthorizeVmLifecycle   = ($c.cap -ne 'vm_lifecycle')
                    AuthorizeGuestMutation = ($c.cap -ne 'guest_mutation')
                    AuthorizeGuestExec     = ($c.cap -ne 'guest_exec')
                }
                $blk = Invoke-VmLabWorkflow @authArgs
                $blk.status | Should Be 'BLOCKED'
                $blk.reason_code | Should Be "capability_required_$($c.cap)"
            }
        }
        Remove-Item Env:VMLAB_CAP_ROOT, Env:VMLAB_CAP_MANIFEST -ErrorAction SilentlyContinue
    }

    It 'reconciles checkpoints using real Get-VmLabCheckpoint output and fails closed on wrong type, duplicates, id conflict, restart failure, and readiness timeout' {
        $env:VMLAB_P1_ROOT = Join-Path $tmpRoot 'ops_p1_cp'
        New-Item -ItemType Directory -Path $env:VMLAB_P1_ROOT -Force | Out-Null

        InModuleScope vm_lab {
            $opRoot = $env:VMLAB_P1_ROOT
            $secPwd = ConvertTo-SecureString 'DummyPass123!' -AsPlainText -Force
            $cred = [pscredential]::new('Administrator', $secPwd)

            function New-P1SeedOp {
                param([string]$OpId, [bool]$RestartAfter = $false, [string]$PriorCpId = '', [string]$CpState = 'PLANNED')
                $wfPath = Join-Path $opRoot "$OpId.workflow.json"
                $wfDef = [ordered]@{
                    schema_version = 1
                    workflow_id    = 'p1-cp-reconcile'
                    operation_root = $opRoot
                    vm             = [ordered]@{ name = 'Disp-P1-01'; template = 'windows11-dev'; root = (Join-Path $opRoot 'vm') }
                    stages         = @(
                        [ordered]@{ id = 's_cp'; type = 'vm.checkpoint_transaction'; depends_on = @(); capability = 'vm_lifecycle'; checkpoint_name = 'cp-p1'; require_off = $true; restart_after = $RestartAfter }
                    )
                }
                [System.IO.File]::WriteAllText($wfPath, ($wfDef | ConvertTo-Json -Depth 10))
                $plan = Test-VmLabWorkflowPlan -WorkflowPath $wfPath
                $opDir = Join-Path $opRoot $OpId
                $recDir = Join-Path $opDir 'receipts\s_cp'
                New-Item -ItemType Directory -Path $recDir -Force | Out-Null
                [System.IO.File]::WriteAllText((Join-Path $opDir 'workflow.json'), ($wfDef | ConvertTo-Json -Depth 10))
                $j = [ordered]@{
                    schema_version  = 1
                    operation_id    = $OpId
                    workflow_id     = 'p1-cp-reconcile'
                    workflow_digest = $plan.workflow_digest
                    host_identity   = $env:COMPUTERNAME
                    vm_id           = 'eeeeeeee-1111-2222-3333-444444444444'
                    vm_name         = 'Disp-P1-01'
                    vm_config_path  = $wfDef.vm.root
                    created_at      = [DateTimeOffset]::UtcNow.ToString('o')
                    updated_at      = [DateTimeOffset]::UtcNow.ToString('o')
                    overall_state   = 'RUNNING'
                    stage_states    = [ordered]@{ s_cp = $CpState }
                    evidence_index  = @()
                    last_error      = $null
                }
                [System.IO.File]::WriteAllText((Join-Path $opDir 'operation.json'), ($j | ConvertTo-Json -Depth 10))
                if ($PriorCpId) {
                    $pr = [ordered]@{
                        schema_version = 1; operation_id = $OpId; stage_id = 's_cp'; stage_type = 'vm.checkpoint_transaction'; attempt = 1
                        vm_id = 'eeeeeeee-1111-2222-3333-444444444444'; result_status = $CpState; reason_code = 'prior'
                        detail = [ordered]@{ checkpoint_id = $PriorCpId }
                    }
                    [System.IO.File]::WriteAllText((Join-Path $recDir '1.json'), ($pr | ConvertTo-Json -Depth 10))
                }
            }

            Mock Get-VM { return @([pscustomobject]@{ Name = 'Disp-P1-01'; Id = [guid]'eeeeeeee-1111-2222-3333-444444444444'; State = 'Off'; CheckpointType = 'Standard' }) }
            Mock Test-VmLabOwnership { return [pscustomobject]@{ owned = $true; reason = 'ok' } }

            # 1. No matching checkpoint -> invokes Invoke-VmLabCheckpointTransaction
            New-P1SeedOp -OpId 'op-p1-none'
            Mock Get-VmLabCheckpoint { return @([pscustomobject]@{ vm_name = 'Disp-P1-01'; name = 'other-cp'; id = 'cp-other'; snapshot_type = 'Standard'; created_at = [datetime]::UtcNow }) }
            Mock Invoke-VmLabCheckpointTransaction { return [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'lifecycle_transaction_complete'; checkpoint_id = 'cp-new' } }
            $rNone = Invoke-VmLabWorkflow -OperationId 'op-p1-none' -OperationRoot $opRoot -Resume -Apply -AuthorizeVmLifecycle
            $rNone.status | Should Be 'SUCCEEDED'

            # All remaining subcases must NEVER call Invoke-VmLabCheckpointTransaction
            Mock Invoke-VmLabCheckpointTransaction { throw 'MUST_NOT_RECREATE_CHECKPOINT' }

            # 2. Wrong snapshot_type -> FAILED
            New-P1SeedOp -OpId 'op-p1-wrongtype'
            Mock Get-VmLabCheckpoint { return @([pscustomobject]@{ vm_name = 'Disp-P1-01'; name = 'cp-p1'; id = 'cp-1'; snapshot_type = 'Production'; created_at = [datetime]::UtcNow }) }
            $rType = Invoke-VmLabWorkflow -OperationId 'op-p1-wrongtype' -OperationRoot $opRoot -Resume -Apply -AuthorizeVmLifecycle
            $rType.status | Should Be 'FAILED'

            # 3. Duplicate checkpoint matches -> FAILED
            New-P1SeedOp -OpId 'op-p1-dup'
            Mock Get-VmLabCheckpoint { return @(
                [pscustomobject]@{ vm_name = 'Disp-P1-01'; name = 'cp-p1'; id = 'cp-1'; snapshot_type = 'Standard'; created_at = [datetime]::UtcNow },
                [pscustomobject]@{ vm_name = 'Disp-P1-01'; name = 'cp-p1'; id = 'cp-2'; snapshot_type = 'Standard'; created_at = [datetime]::UtcNow }
            ) }
            $rDup = Invoke-VmLabWorkflow -OperationId 'op-p1-dup' -OperationRoot $opRoot -Resume -Apply -AuthorizeVmLifecycle
            $rDup.status | Should Be 'FAILED'

            # 4. Checkpoint ID conflict with prior receipt -> FAILED
            New-P1SeedOp -OpId 'op-p1-idconflict' -PriorCpId 'cp-old-999'
            Mock Get-VmLabCheckpoint { return @([pscustomobject]@{ vm_name = 'Disp-P1-01'; name = 'cp-p1'; id = 'cp-different'; snapshot_type = 'Standard'; created_at = [datetime]::UtcNow }) }
            $rIdConf = Invoke-VmLabWorkflow -OperationId 'op-p1-idconflict' -OperationRoot $opRoot -Resume -Apply -AuthorizeVmLifecycle
            $rIdConf.status | Should Be 'FAILED'

            # 5. Restart requested -> Start failure => PARTIAL
            New-P1SeedOp -OpId 'op-p1-startfail' -RestartAfter $true
            Mock Get-VmLabCheckpoint { return @([pscustomobject]@{ vm_name = 'Disp-P1-01'; name = 'cp-p1'; id = 'cp-1'; snapshot_type = 'Standard'; created_at = [datetime]::UtcNow }) }
            Mock Start-VmLabMachine { return [pscustomobject]@{ status = 'blocked_insufficient_ram' } }
            $rStartFail = Invoke-VmLabWorkflow -OperationId 'op-p1-startfail' -OperationRoot $opRoot -Credential $cred -Resume -Apply -AuthorizeVmLifecycle
            $rStartFail.status | Should Be 'PARTIAL'
            $rStartFail.reason_code | Should Be 'restart_failed_after_reconciled_checkpoint'

            # 6. Restart requested -> Readiness timeout => PARTIAL
            New-P1SeedOp -OpId 'op-p1-timeout' -RestartAfter $true
            Mock Start-VmLabMachine { return [pscustomobject]@{ status = 'started' } }
            Mock Wait-VmLabGuestReady { return [pscustomobject]@{ status = 'PARTIAL'; reason_code = 'guest_readiness_timeout' } }
            $rTimeout = Invoke-VmLabWorkflow -OperationId 'op-p1-timeout' -OperationRoot $opRoot -Credential $cred -Resume -Apply -AuthorizeVmLifecycle
            $rTimeout.status | Should Be 'PARTIAL'
            $rTimeout.reason_code | Should Be 'guest_readiness_timeout'

            # 7. Restart requested -> Start + Ready => SUCCEEDED, and subsequent resume skips without re-checkpointing
            New-P1SeedOp -OpId 'op-p1-ok' -RestartAfter $true
            Mock Wait-VmLabGuestReady { return [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'guest_ready' } }
            $rOk = Invoke-VmLabWorkflow -OperationId 'op-p1-ok' -OperationRoot $opRoot -Credential $cred -Resume -Apply -AuthorizeVmLifecycle
            $rOk.status | Should Be 'SUCCEEDED'
            $rOk2 = Invoke-VmLabWorkflow -OperationId 'op-p1-ok' -OperationRoot $opRoot -Credential $cred -Resume -Apply -AuthorizeVmLifecycle
            $rOk2.status | Should Be 'SUCCEEDED'
        }
        Remove-Item Env:VMLAB_P1_ROOT -ErrorAction SilentlyContinue
    }
}
