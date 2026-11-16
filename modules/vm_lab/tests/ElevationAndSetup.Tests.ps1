#Requires -Version 7.0

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$moduleRoot = Split-Path -Parent $here
Import-Module (Join-Path $moduleRoot 'vm_lab.psd1') -Force

Describe 'vm_lab Phase 4 elevated runner and Phase 5 Windows setup assistance' {
    $tmpRoot = Join-Path $moduleRoot '.pytest_tmp_root\pester_elev_setup'
    if (Test-Path -LiteralPath $tmpRoot) {
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null

    It 'validates bounded approved plan requests and fails closed on tamper, workflow drift, expiry, missing consent, and reuse' {
        $opRoot = Join-Path $tmpRoot 'ops'
        $wfPath = Join-Path $tmpRoot 'wf.json'
        $reqPath = Join-Path $tmpRoot 'req.json'
        $wfObj = [ordered]@{
            schema_version = 1
            workflow_id    = 'elev-test'
            operation_root = $opRoot
            vm             = [ordered]@{ template = 'windows11-dev'; name = 'Disp-Elev-01'; root = (Join-Path $tmpRoot 'vm1') }
            stages         = @(
                [ordered]@{ id = 'pre'; type = 'host.preflight'; depends_on = @() },
                [ordered]@{ id = 'create'; type = 'vm.create'; depends_on = @('pre'); capability = 'host_mutation' }
            )
        }
        [System.IO.File]::WriteAllText($wfPath, ($wfObj | ConvertTo-Json -Depth 10))

        $created = New-VmLabApprovedPlanRequest -WorkflowPath $wfPath -OutputPath $reqPath -AllowedCapabilities @('host_mutation') -OperationId 'op-elev-01'
        $created.status | Should Be 'PLANNED'

        $verified = Test-VmLabApprovedPlanRequest -RequestPath $reqPath -ExpectedRequestDigest $created.request_digest
        $verified.valid | Should Be $true

        # Runner without -OperatorConsent -> exit 1 BLOCKED
        $runner = Join-Path $moduleRoot 'Invoke-VmLabApprovedPlan.ps1'
        $noConsentOut = & pwsh -NoProfile -File $runner -RequestPath $reqPath
        $LASTEXITCODE | Should Be 1
        (($noConsentOut -join "`n") | ConvertFrom-Json).reason_code | Should Be 'operator_consent_required'

        # Runner with -OperatorConsent -DryRun -> exit 0 PLANNED
        $dryOut = & pwsh -NoProfile -File $runner -RequestPath $reqPath -OperatorConsent -DryRun
        $LASTEXITCODE | Should Be 0
        (($dryOut -join "`n") | ConvertFrom-Json).reason_code | Should Be 'dry_run_not_applied'

        # Consumed receipt blocks reuse
        $opDir = Join-Path $opRoot 'op-elev-01'
        New-Item -ItemType Directory -Path $opDir -Force | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $opDir "approved-plan-receipt-$($created.request_id).json"), '{"consumed":true}')
        $reuseOut = & pwsh -NoProfile -File $runner -RequestPath $reqPath -OperatorConsent 2>&1
        $LASTEXITCODE | Should Be 1
        ($reuseOut -join "`n") | Should Match 'approval_already_consumed'

        # Tampered workflow.json fails digest check
        $wfObj.workflow_id = 'elev-test-tampered'
        [System.IO.File]::WriteAllText($wfPath, ($wfObj | ConvertTo-Json -Depth 10))
        $threwDrift = $false
        try { Test-VmLabApprovedPlanRequest -RequestPath $reqPath } catch { $threwDrift = $true }
        $threwDrift | Should Be $true

        # Expired request fails
        $expReqPath = Join-Path $tmpRoot 'req_exp.json'
        $null = New-VmLabApprovedPlanRequest -WorkflowPath $wfPath -OutputPath $expReqPath -AllowedCapabilities @('host_mutation') -ExpiresInMinutes 1
        $expObj = Get-Content -LiteralPath $expReqPath -Raw | ConvertFrom-Json
        $expObj.expires_at = [DateTimeOffset]::UtcNow.AddMinutes(-5).ToString('o')
        # Re-sign digest with expired timestamp to test expiration check specifically
        $body = [ordered]@{
            schema_version       = $expObj.schema_version
            request_id           = $expObj.request_id
            operation_id         = $expObj.operation_id
            workflow_path        = $expObj.workflow_path
            workflow_id          = $expObj.workflow_id
            workflow_digest      = $expObj.workflow_digest
            operation_root       = $expObj.operation_root
            vm_name              = $expObj.vm_name
            expected_vm_id       = $expObj.expected_vm_id
            allowed_capabilities = @($expObj.allowed_capabilities)
            created_at           = $expObj.created_at
            expires_at           = $expObj.expires_at
        }
        $expObj.request_digest = Get-VmLabCanonicalSha256 -InputObject $body
        [System.IO.File]::WriteAllText($expReqPath, ($expObj | ConvertTo-Json -Depth 10))
        $threwExp = $false
        try { Test-VmLabApprovedPlanRequest -RequestPath $expReqPath } catch { $threwExp = $true }
        $threwExp | Should Be $true
    }

    It 'stages password-free answer media, produces setup/OOBE guidance, and enforces Sysprep policy for prepared images' {
        $stageDir = Join-Path $tmpRoot 'answer_media'
        $plan = New-VmLabAnswerMediaStaging -StagingDirectory $stageDir
        $plan.status | Should Be 'PLANNED'
        (Test-Path -LiteralPath (Join-Path $stageDir 'Autounattend.xml')) | Should Be $false

        $staged = New-VmLabAnswerMediaStaging -StagingDirectory $stageDir -Apply
        $staged.status | Should Be 'SUCCEEDED'
        (Test-Path -LiteralPath $staged.xml_path) | Should Be $true
        (Test-Path -LiteralPath $staged.meta_path) | Should Be $true

        InModuleScope vm_lab {
            Mock Get-VmLabBootDiagnostics { return [pscustomobject]@{ dvd_first_in_boot_order = $false } }
            Mock Get-VmLabGuestStatus { return [pscustomobject]@{ guest_state = 'windows_booted_account_unavailable' } }
            $rep = Get-VmLabSetupProgressReport -Name 'Disp-Setup-01'
            $rep.status | Should Be 'AWAITING_INTERACTION'
            $rep.guidance.Count | Should Be 2
        }

        $threwSysprep = $false
        try { Test-VmLabPreparedImagePolicy -VhdxPath 'C:\Images\win11-base.vhdx' -LicensingAcknowledged } catch { $threwSysprep = $true }
        $threwSysprep | Should Be $true

        $pol = Test-VmLabPreparedImagePolicy -VhdxPath 'C:\Images\win11-base.vhdx' -SysprepGeneralized -LicensingAcknowledged
        $pol.valid | Should Be $true
    }

    It 'records durable FAIL receipt on execution exception and blocks replay' {
        $wfPath = Join-Path $tmpRoot 'fail_elev.workflow.json'
        $opRoot = Join-Path $tmpRoot 'ops_fail_elev'
        $reqPath = Join-Path $tmpRoot 'fail_req.json'
        $wfDef = [ordered]@{
            schema_version = 1
            workflow_id    = 'fail-elev-test'
            operation_root = $opRoot
            vm             = [ordered]@{ name = 'Disp-Elev-Fail-01'; template = 'windows11-dev'; root = (Join-Path $tmpRoot 'vm_elev_fail') }
            stages         = @([ordered]@{ id = 's1'; type = 'host.preflight'; depends_on = @(); capability = 'none' })
        }
        [System.IO.File]::WriteAllText($wfPath, ($wfDef | ConvertTo-Json -Depth 10))
        $req = New-VmLabApprovedPlanRequest -WorkflowPath $wfPath -OutputPath $reqPath -AllowedCapabilities @('host_mutation') -OperationId 'op-elev-fail-01' -ExpectedVmId 'cccccccc-1111-2222-3333-444444444444'

        # Pre-seed journal with a DIFFERENT vm_id so Invoke-VmLabWorkflow throws vm_id_mismatch
        $opDir = Join-Path $opRoot 'op-elev-fail-01'
        New-Item -ItemType Directory -Path $opDir -Force | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $opDir 'workflow.json'), ($wfDef | ConvertTo-Json -Depth 10))
        $plan = Test-VmLabWorkflowPlan -WorkflowPath $wfPath
        $badJournal = [ordered]@{
            schema_version  = 1
            operation_id    = 'op-elev-fail-01'
            workflow_id     = 'fail-elev-test'
            workflow_digest = $plan.workflow_digest
            host_identity   = $env:COMPUTERNAME
            vm_id           = 'dddddddd-1111-2222-3333-444444444444'
            vm_name         = 'Disp-Elev-Fail-01'
            vm_config_path  = $wfDef.vm.root
            created_at      = [DateTimeOffset]::UtcNow.ToString('o')
            updated_at      = [DateTimeOffset]::UtcNow.ToString('o')
            overall_state   = 'RUNNING'
            stage_states    = [ordered]@{ s1 = 'PLANNED' }
            evidence_index  = @()
            last_error      = $null
        }
        [System.IO.File]::WriteAllText((Join-Path $opDir 'operation.json'), ($badJournal | ConvertTo-Json -Depth 10))

        $runner = Join-Path $moduleRoot 'Invoke-VmLabApprovedPlan.ps1'
        $null = & pwsh -NoProfile -File $runner -RequestPath $reqPath -ExpectedRequestDigest $req.request_digest -OperatorConsent 2>&1
        $LASTEXITCODE | Should Not Be 0

        $receiptPath = Join-Path $opDir "approved-plan-receipt-$($req.request_id).json"
        (Test-Path -LiteralPath $receiptPath -PathType Leaf) | Should Be $true
        $recObj = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
        $recObj.result_status | Should Be 'FAIL'
        $recObj.reason_code | Should Be 'approved_plan_execution_exception'

        # Replay must be blocked
        $replayOut = & pwsh -NoProfile -File $runner -RequestPath $reqPath -ExpectedRequestDigest $req.request_digest -OperatorConsent 2>&1 | Out-String
        $LASTEXITCODE | Should Not Be 0
        ($replayOut -match 'approval_already_consumed') | Should Be $true
    }
}
