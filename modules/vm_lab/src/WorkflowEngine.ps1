#Requires -Version 7.0

function Write-VmLabJsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][object]$Data
    )
    $safe = Test-VmLabSafePath -Path $Path -Label 'atomic_json' -CheckReparsePoints
    $dir = Split-Path -Parent $safe
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $tmp = "$safe.tmp.$PID.$([guid]::NewGuid().ToString('N'))"
    try {
        $json = $Data | ConvertTo-Json -Depth 20
        [System.IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::Move($tmp, $safe, $true)
    } catch {
        if (Test-Path -LiteralPath $tmp -PathType Leaf) {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

function Enter-VmLabOperationLock {
    param([Parameter(Mandatory)][string]$OpDir, [Parameter(Mandatory)][string]$OperationId)
    $lockPath = Test-VmLabSafePath -Path (Join-Path $OpDir 'operation.lock') -Label 'operation.lock' -WithinRoot $OpDir -CheckReparsePoints
    $throwLockError = {
        $existing = $null
        try { $existing = Get-Content -LiteralPath $lockPath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop } catch {}
        $pidAlive = $false
        if ($existing -and $existing.pid) {
            try { $null = Get-Process -Id ([int]$existing.pid) -ErrorAction Stop; $pidAlive = $true } catch {}
        }
        $kind = if ($pidAlive) { 'active_operation_lock' } else { 'stale_operation_lock' }
        throw "${kind}: Operation lock exists at '$lockPath' (pid=$($existing.pid), host=$($existing.host)). Inspect with workflow-doctor; do not auto-delete."
    }
    if (Test-Path -LiteralPath $lockPath -PathType Leaf) {
        & $throwLockError
    }
    $lockObj = [ordered]@{
        operation_id = $OperationId
        pid          = $PID
        host         = $env:COMPUTERNAME
        acquired_at  = [DateTimeOffset]::UtcNow.ToString('o')
    }
    try {
        $fs = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    } catch [System.IO.IOException] {
        & $throwLockError
    }
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(($lockObj | ConvertTo-Json -Depth 5))
        $fs.Write($bytes, 0, $bytes.Length)
    } finally {
        $fs.Dispose()
    }
    return $lockPath
}

function Exit-VmLabOperationLock {
    param([string]$LockPath)
    if (-not [string]::IsNullOrWhiteSpace($LockPath) -and (Test-Path -LiteralPath $LockPath -PathType Leaf)) {
        Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
    }
}

function ConvertTo-VmLabNormalizedCheckpoint {
    param([Parameter(Mandatory)][object]$Checkpoint)
    if ([string]::IsNullOrWhiteSpace([string]$Checkpoint.name) -or
        [string]::IsNullOrWhiteSpace([string]$Checkpoint.id) -or
        [string]::IsNullOrWhiteSpace([string]$Checkpoint.snapshot_type)) {
        throw "checkpoint_contract_invalid: Get-VmLabCheckpoint entry missing required fields (name, id, snapshot_type)."
    }
    return [pscustomobject]@{
        vm_name       = [string]$Checkpoint.vm_name
        name          = [string]$Checkpoint.name
        id            = [string]$Checkpoint.id
        snapshot_type = [string]$Checkpoint.snapshot_type
        created_at    = $Checkpoint.created_at
    }
}

function Read-VmLabValidatedWorkflowPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WorkflowPath
    )
    $wfFile = Test-VmLabSafePath -Path $WorkflowPath -Label 'WorkflowPath' -CheckReparsePoints
    if (-not (Test-Path -LiteralPath $wfFile -PathType Leaf)) {
        throw "Workflow definition file not found: '$wfFile'."
    }
    $raw = [System.IO.File]::ReadAllText($wfFile, [System.Text.UTF8Encoding]::new($false))
    $def = $raw | ConvertFrom-Json -ErrorAction Stop
    $schema = Test-VmLabWorkflowSchema -Definition $def
    $capPolicy = Get-VmLabOperationCapabilityPolicy
    $caps = @($def.stages | ForEach-Object { [string]$capPolicy[[string]$_.type] } | Select-Object -Unique)
    $plan = [pscustomobject]@{
        status                = 'PLANNED'
        reason_code           = 'workflow_plan_valid'
        workflow_id           = $schema.workflow_id
        workflow_digest       = $schema.workflow_digest
        workflow_path         = $wfFile
        operation_root        = [string]$def.operation_root
        vm_name               = [string]$def.vm.name
        vm_root               = [string]$def.vm.root
        stage_order           = @($schema.stage_order)
        required_capabilities = @($caps)
    }
    return [pscustomobject]@{
        plan       = $plan
        definition = $def
    }
}

function Test-VmLabWorkflowPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WorkflowPath
    )
    return (Read-VmLabValidatedWorkflowPlan -WorkflowPath $WorkflowPath).plan
}

function Get-VmLabWorkflowStatus {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$OperationId,
        [string]$OperationRoot = 'C:\VM-Lab-Operations'
    )
    $rootFull = Test-VmLabSafePath -Path $OperationRoot -Label 'OperationRoot' -CheckReparsePoints
    $opDir = Test-VmLabSafePath -Path (Join-Path $rootFull $OperationId) -Label 'OperationDir' -WithinRoot $rootFull -CheckReparsePoints
    $journalPath = Join-Path $opDir 'operation.json'
    if (-not (Test-Path -LiteralPath $journalPath -PathType Leaf)) {
        throw "Operation journal not found at '$journalPath'."
    }
    $journal = Get-Content -LiteralPath $journalPath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop
    $null = Test-VmLabOperationJournalSchema -Journal $journal -ExpectedOperationId $OperationId
    return [pscustomobject]@{
        status          = $journal.overall_state
        reason_code     = 'workflow_status_ok'
        operation_id    = $journal.operation_id
        workflow_id     = $journal.workflow_id
        workflow_digest = $journal.workflow_digest
        vm_id           = $journal.vm_id
        vm_name         = $journal.vm_name
        operation_dir   = $opDir
        stage_states    = $journal.stage_states
        last_error      = $journal.last_error
        evidence_index  = $journal.evidence_index
    }
}

function Get-VmLabWorkflowDoctor {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$OperationId,
        [string]$OperationRoot = 'C:\VM-Lab-Operations'
    )
    $rootFull = Test-VmLabSafePath -Path $OperationRoot -Label 'OperationRoot' -CheckReparsePoints
    $opDir = Test-VmLabSafePath -Path (Join-Path $rootFull $OperationId) -Label 'OperationDir' -WithinRoot $rootFull -CheckReparsePoints
    $findings = @()
    $lockPath = Join-Path $opDir 'operation.lock'
    if (Test-Path -LiteralPath $lockPath -PathType Leaf) {
        $lockObj = $null
        try { $lockObj = Get-Content -LiteralPath $lockPath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop } catch {}
        $findings += "Operation lock present at '$lockPath' (pid=$($lockObj.pid), host=$($lockObj.host))."
    }
    $journalPath = Join-Path $opDir 'operation.json'
    if (-not (Test-Path -LiteralPath $journalPath -PathType Leaf)) {
        $findings += "Missing operation.json at '$journalPath'."
        return [pscustomobject]@{ status = 'FAILED'; reason_code = 'journal_missing'; operation_id = $OperationId; findings = @($findings) }
    }
    try {
        $journal = Get-Content -LiteralPath $journalPath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop
        $null = Test-VmLabOperationJournalSchema -Journal $journal -ExpectedOperationId $OperationId
    } catch {
        $findings += "Corrupt or invalid operation.json: $($_.Exception.Message)"
        return [pscustomobject]@{ status = 'INVALIDATED'; reason_code = 'journal_corrupt'; operation_id = $OperationId; findings = @($findings) }
    }
    return [pscustomobject]@{
        status        = if ($findings.Count -eq 0) { 'SUCCEEDED' } else { 'PARTIAL' }
        reason_code   = if ($findings.Count -eq 0) { 'doctor_healthy' } else { 'doctor_findings_present' }
        operation_id  = $OperationId
        overall_state = $journal.overall_state
        findings      = @($findings)
        next_action   = if ($journal.overall_state -eq 'AWAITING_INTERACTION') { 'Complete manual interaction and resume with workflow-resume.' } elseif ($journal.overall_state -in @('PARTIAL', 'FAILED', 'BLOCKED')) { 'Resolve reported finding and resume with workflow-resume.' } else { 'No action required.' }
    }
}

function Invoke-VmLabWorkflow {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [string]$WorkflowPath,
        [string]$OperationId,
        [string]$OperationRoot = 'C:\VM-Lab-Operations',
        [string]$ExpectedWorkflowDigest,
        [string]$ExpectedVmId,
        [pscredential]$Credential,
        [switch]$PromptCredential,
        [switch]$Apply,
        [switch]$AuthorizeHostMutation,
        [switch]$AuthorizeVmLifecycle,
        [switch]$AuthorizeGuestMutation,
        [switch]$AuthorizeGuestExec,
        [switch]$AuthorizeElevation,
        [switch]$Resume,
        [string]$ManifestRoot = (Get-VmLabDefaultManifestRoot)
    )

    if (-not $Resume -and [string]::IsNullOrWhiteSpace($WorkflowPath)) {
        throw '-WorkflowPath (-f) is required for workflow-apply.'
    }
    if ($Resume -and [string]::IsNullOrWhiteSpace($OperationId)) {
        throw '-OperationId (-op) is required for workflow-resume.'
    }

    if (-not [string]::IsNullOrWhiteSpace($WorkflowPath)) {
        $loaded = Read-VmLabValidatedWorkflowPlan -WorkflowPath $WorkflowPath
        $planCheck = $loaded.plan
        $def = $loaded.definition
        $opRoot = if ($PSBoundParameters.ContainsKey('OperationRoot')) { $OperationRoot } else { [string]$def.operation_root }
        $opRootFull = Test-VmLabSafePath -Path $opRoot -Label 'OperationRoot' -CheckReparsePoints
        if ([string]::IsNullOrWhiteSpace($OperationId)) {
            $OperationId = ([DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        }
    } else {
        $opRootFull = Test-VmLabSafePath -Path $OperationRoot -Label 'OperationRoot' -CheckReparsePoints
        $opDirLookup = Test-VmLabSafePath -Path (Join-Path $opRootFull $OperationId) -Label 'OperationDir' -WithinRoot $opRootFull -CheckReparsePoints
        $wfSavedPath = Join-Path $opDirLookup 'workflow.json'
        if (-not (Test-Path -LiteralPath $wfSavedPath -PathType Leaf)) {
            throw "Saved workflow.json not found for operation '$OperationId' at '$wfSavedPath'."
        }
        $loaded = Read-VmLabValidatedWorkflowPlan -WorkflowPath $wfSavedPath
        $planCheck = $loaded.plan
        $def = $loaded.definition
    }

    if (-not [string]::IsNullOrWhiteSpace($ExpectedWorkflowDigest) -and $planCheck.workflow_digest -ne $ExpectedWorkflowDigest.ToLowerInvariant()) {
        throw "workflow_digest_mismatch: Expected workflow digest '$ExpectedWorkflowDigest', actual '$($planCheck.workflow_digest)'."
    }

    if (-not $Apply -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess($def.vm.name, "Execute workflow '$($def.workflow_id)'")) {
        return $planCheck
    }

    $opDir = Test-VmLabSafePath -Path (Join-Path $opRootFull $OperationId) -Label 'OperationDir' -WithinRoot $opRootFull -CheckReparsePoints
    if (-not $Resume -and (Test-Path -LiteralPath (Join-Path $opDir 'operation.json') -PathType Leaf)) {
        throw "operation_id_collision: Operation '$OperationId' already exists at '$opDir'. Use -Resume (workflow-resume) to continue it."
    }
    if (-not (Test-Path -LiteralPath $opDir -PathType Container)) {
        New-Item -ItemType Directory -Path $opDir -Force | Out-Null
    }

    $lockPath = Enter-VmLabOperationLock -OpDir $opDir -OperationId $OperationId
    try {
        $wfDest = Join-Path $opDir 'workflow.json'
        $journalPath = Join-Path $opDir 'operation.json'
        $receiptsDir = Join-Path $opDir 'receipts'
        $logsDir = Join-Path $opDir 'logs'
        $evDir = Join-Path $opDir 'evidence'
        foreach ($d in @($receiptsDir, $logsDir, $evDir)) {
            if (-not (Test-Path -LiteralPath $d -PathType Container)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
        }

        $journal = $null
        if (Test-Path -LiteralPath $journalPath -PathType Leaf) {
            $journal = Get-Content -LiteralPath $journalPath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop
            $null = Test-VmLabOperationJournalSchema -Journal $journal -ExpectedOperationId $OperationId -ExpectedWorkflowDigest $planCheck.workflow_digest
            if (-not [string]::IsNullOrWhiteSpace($ExpectedVmId) -and -not [string]::IsNullOrWhiteSpace([string]$journal.vm_id) -and ([string]$journal.vm_id).ToLowerInvariant() -ne $ExpectedVmId.ToLowerInvariant()) {
                throw "vm_id_mismatch: Journal vm_id '$($journal.vm_id)' does not match ExpectedVmId '$ExpectedVmId'."
            }
        } else {
            Write-VmLabJsonAtomic -Path $wfDest -Data $def
            $stageStatesInit = [ordered]@{}
            foreach ($sid in $planCheck.stage_order) { $stageStatesInit[$sid] = 'PLANNED' }
            $journal = [pscustomobject]@{
                schema_version  = 1
                operation_id    = $OperationId
                workflow_id     = $planCheck.workflow_id
                workflow_digest = $planCheck.workflow_digest
                host_identity   = $env:COMPUTERNAME
                vm_id           = ''
                vm_name         = [string]$def.vm.name
                vm_config_path  = [string]$def.vm.root
                created_at      = [DateTimeOffset]::UtcNow.ToString('o')
                updated_at      = [DateTimeOffset]::UtcNow.ToString('o')
                overall_state   = 'RUNNING'
                stage_states    = [pscustomobject]$stageStatesInit
                evidence_index  = @()
                last_error      = $null
            }
            Write-VmLabJsonAtomic -Path $journalPath -Data $journal
        }

        $stageMap = @{}
        foreach ($s in @($def.stages)) { $stageMap[[string]$s.id] = $s }

        $guestIdPolicy = $null
        if ($def.vm.guest_identity) {
            $guestIdPolicy = @{}
            if ($null -ne $def.vm.guest_identity.require_local_admin) { $guestIdPolicy.require_local_admin = [bool]$def.vm.guest_identity.require_local_admin }
            if ($def.vm.guest_identity.os) { $guestIdPolicy.os_caption_match = [string]$def.vm.guest_identity.os }
            if ($def.vm.guest_identity.architecture) { $guestIdPolicy.architecture = [string]$def.vm.guest_identity.architecture }
            if ($def.vm.guest_identity.expected_hostname) { $guestIdPolicy.expected_hostname = [string]$def.vm.guest_identity.expected_hostname }
            if ($def.vm.guest_identity.forbidden_processes) { $guestIdPolicy.forbidden_processes = @($def.vm.guest_identity.forbidden_processes) }
        }

        $finalStatus = 'SUCCEEDED'
        $finalReason = 'workflow_completed'
        $deferredCleanupStages = [System.Collections.Generic.HashSet[string]]::new()

        foreach ($sid in $planCheck.stage_order) {
            if ($deferredCleanupStages.Contains($sid)) { continue }
            $s = $stageMap[$sid]
            $curState = [string]$journal.stage_states.$sid

            if ($Resume -and $curState -eq 'PARTIAL' -and [string]$s.idempotency_class -eq 'non_repeatable') {
                $journal.overall_state = 'PARTIAL'
                $journal.last_error = "Stage '$sid' is non_repeatable and previously ended in PARTIAL; manual reconciliation required."
                $journal.updated_at = [DateTimeOffset]::UtcNow.ToString('o')
                Write-VmLabJsonAtomic -Path $journalPath -Data $journal
                $finalStatus = 'PARTIAL'
                $finalReason = 'non_repeatable_requires_reconciliation'
                break
            }

            # Reconcile completed stages before skipping
            if ($curState -eq 'SUCCEEDED') {
                $stageRecDir = Join-Path $receiptsDir $sid
                $latestRec = @(Get-ChildItem -LiteralPath $stageRecDir -Filter '*.json' -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1)
                if ($latestRec.Count -eq 0) {
                    throw "Stage '$sid' marked SUCCEEDED in journal but has no receipt in '$stageRecDir'."
                }
                $recObj = Get-Content -LiteralPath $latestRec[0].FullName -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop
                $expectedRecVmId = if ($s.type -eq 'host.preflight' -and [string]::IsNullOrWhiteSpace([string]$recObj.vm_id)) { '' } else { [string]$journal.vm_id }
                $null = Test-VmLabStageReceiptSchema -Receipt $recObj -ExpectedOperationId $OperationId -ExpectedStageId $sid -ExpectedVmId $expectedRecVmId
                if ($recObj.result_status -ne 'SUCCEEDED') {
                    throw "Stage '$sid' receipt status '$($recObj.result_status)' disagrees with journal SUCCEEDED."
                }
                if ($s.type -eq 'vm.create') {
                    $existingVm = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq $def.vm.name } | Select-Object -First 1
                    if (-not $existingVm -or ([string]$existingVm.Id).ToLowerInvariant() -ne ([string]$journal.vm_id).ToLowerInvariant()) {
                        throw "Stage '$sid' reconciliation failed: VM '$($def.vm.name)' (expected id '$($journal.vm_id)') not found."
                    }
                }
                continue
            }

            $capPolicy = Get-VmLabOperationCapabilityPolicy
            $cap = [string]$capPolicy[[string]$s.type]
            $capOk = Test-VmLabCapabilityAuthorized -Capability $cap -Apply:$Apply -AuthorizeHostMutation:$AuthorizeHostMutation -AuthorizeVmLifecycle:$AuthorizeVmLifecycle -AuthorizeGuestMutation:$AuthorizeGuestMutation -AuthorizeGuestExec:$AuthorizeGuestExec -AuthorizeElevation:$AuthorizeElevation
            if (-not $capOk) {
                $journal.stage_states.$sid = 'BLOCKED'
                $journal.overall_state = 'BLOCKED'
                $journal.last_error = "Stage '$sid' requires capability '$cap'."
                $journal.updated_at = [DateTimeOffset]::UtcNow.ToString('o')
                Write-VmLabJsonAtomic -Path $journalPath -Data $journal
                $finalStatus = 'BLOCKED'
                $finalReason = "capability_required_$cap"
                break
            }

            $stageRecDir = Join-Path $receiptsDir $sid
            if (-not (Test-Path -LiteralPath $stageRecDir -PathType Container)) { New-Item -ItemType Directory -Path $stageRecDir -Force | Out-Null }
            $attempt = @(Get-ChildItem -LiteralPath $stageRecDir -Filter '*.json' -ErrorAction SilentlyContinue).Count + 1
            $startedAt = [DateTimeOffset]::UtcNow.ToString('o')
            $stageOut = $null
            $stageStatus = 'FAILED'
            $stageReason = 'unknown'
            $exitCodeVal = $null

            try {
                switch ([string]$s.type) {
                    'host.preflight' {
                        $cfg = Get-VmLabTemplate -TemplateName ([string]$def.vm.template)
                        $cfg.vm_name = [string]$def.vm.name
                        $cfg.vm_root = [string]$def.vm.root
                        if ($def.vm.iso) { $cfg.iso_path = [string]$def.vm.iso }
                        $stageOut = Test-VmLabPlan -Config $cfg -ManifestRoot $ManifestRoot
                        $stageStatus = 'SUCCEEDED'
                        $stageReason = 'preflight_ok'
                    }
                    'vm.create' {
                        $existingVm = Get-VM -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq [string]$def.vm.name } | Select-Object -First 1
                        if ($existingVm) {
                            Assert-VmLabTargetNotProtected -VmName $existingVm.Name -VmId ([string]$existingVm.Id)
                            $own = Test-VmLabOwnership -Vm $existingVm -ManifestRoot $ManifestRoot
                            if (-not $own.owned) {
                                throw "vm_create_unmanaged_collision: VM '$($def.vm.name)' already exists and is not owned by vm_lab ($($own.reason))."
                            }
                            if (-not [string]::IsNullOrWhiteSpace($ExpectedVmId) -and ([string]$existingVm.Id).ToLowerInvariant() -ne $ExpectedVmId.ToLowerInvariant()) {
                                throw "vm_id_mismatch: Existing VM '$($def.vm.name)' has id '$($existingVm.Id)', expected '$ExpectedVmId'."
                            }
                            $journal.vm_id = [string]$existingVm.Id
                            $stageOut = [pscustomobject]@{ status = 'reconciled_existing'; vm_id = [string]$existingVm.Id; vm_name = $existingVm.Name }
                            $stageStatus = 'SUCCEEDED'
                            $stageReason = 'vm_create_reconciled_existing'
                        } else {
                            $cfg = Get-VmLabTemplate -TemplateName ([string]$def.vm.template)
                            $cfg.vm_name = [string]$def.vm.name
                            $cfg.vm_root = [string]$def.vm.root
                            if ($def.vm.iso) { $cfg.iso_path = [string]$def.vm.iso }
                            $stageOut = New-VmLabMachine -Config $cfg -Apply -ManifestRoot $ManifestRoot
                            if ($stageOut.vm_id) {
                                if (-not [string]::IsNullOrWhiteSpace($ExpectedVmId) -and ([string]$stageOut.vm_id).ToLowerInvariant() -ne $ExpectedVmId.ToLowerInvariant()) {
                                    throw "vm_id_mismatch: Created VM has id '$($stageOut.vm_id)', expected '$ExpectedVmId'."
                                }
                                $journal.vm_id = [string]$stageOut.vm_id
                            }
                            $stageStatus = if ($stageOut.status -eq 'created') { 'SUCCEEDED' } else { 'FAILED' }
                            $stageReason = [string]$stageOut.status
                        }
                    }
                    'vm.start' {
                        $stageOut = Start-VmLabMachine -Name ([string]$def.vm.name) -Apply -ManifestRoot $ManifestRoot
                        $stageStatus = if ($stageOut.status -in @('started', 'already_running')) { 'SUCCEEDED' } else { 'FAILED' }
                        $stageReason = [string]$stageOut.status
                    }
                    'vm.connect' {
                        $stageOut = Open-VmLabConnect -Name ([string]$def.vm.name) -Apply -ManifestRoot $ManifestRoot
                        $stageStatus = if ($stageOut.status -in @('connected', 'started_and_connected')) { 'SUCCEEDED' } else { 'FAILED' }
                        $stageReason = [string]$stageOut.status
                    }
                    'vm.shutdown' {
                        $sdArgs = @{ Name = [string]$def.vm.name; Apply = $true; ManifestRoot = $ManifestRoot }
                        if ($null -ne $s.timeout_seconds) { $sdArgs.ShutdownTimeoutSeconds = [int]$s.timeout_seconds }
                        $stageOut = Stop-VmLabMachine @sdArgs
                        $stageStatus = if ($stageOut.status -in @('stopped', 'already_stopped')) { 'SUCCEEDED' } else { 'PARTIAL' }
                        $stageReason = [string]$stageOut.status
                    }
                    'windows.install_handoff' {
                        # If guest is already ready, handoff is satisfied; otherwise pause at AWAITING_INTERACTION
                        if ($null -ne $Credential) {
                            $gs = Get-VmLabGuestStatus -Name ([string]$def.vm.name) -Credential $Credential -ManifestRoot $ManifestRoot
                            if ($gs.guest_state -eq 'guest_ready') {
                                $stageOut = $gs
                                $stageStatus = 'SUCCEEDED'
                                $stageReason = 'guest_already_ready'
                            } else {
                                $stageOut = $gs
                                $stageStatus = 'AWAITING_INTERACTION'
                                $stageReason = 'windows_install_or_oobe_pending'
                            }
                        } else {
                            $stageOut = [pscustomobject]@{ status = 'AWAITING_INTERACTION'; reason_code = 'windows_install_handoff' }
                            $stageStatus = 'AWAITING_INTERACTION'
                            $stageReason = 'windows_install_handoff'
                        }
                    }
                    'guest.wait' {
                        $gwArgs = @{ Name = [string]$def.vm.name; Credential = $Credential; PromptCredential = [bool]$PromptCredential; ManifestRoot = $ManifestRoot }
                        if ($null -ne $s.timeout_seconds) { $gwArgs.TimeoutSeconds = [int]$s.timeout_seconds }
                        if ($guestIdPolicy) { $gwArgs.IdentityPolicy = $guestIdPolicy }
                        $stageOut = Wait-VmLabGuestReady @gwArgs
                        $stageStatus = [string]$stageOut.status
                        $stageReason = [string]$stageOut.reason_code
                    }
                    'artifact.deploy' {
                        $mPath = Test-VmLabSafePath -Path ([string]$s.manifest) -Label 'artifact.deploy.manifest' -CheckReparsePoints
                        $mObj = Get-Content -LiteralPath $mPath -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop
                        $srcRoot = Split-Path -Parent $mPath
                        $stageOut = Publish-VmLabArtifactBundle -Name ([string]$def.vm.name) -SourceRoot $srcRoot -Manifest $mObj -OperationId $OperationId -Credential $Credential -Apply -AuthorizeGuestMutation -ManifestRoot $ManifestRoot
                        $stageStatus = [string]$stageOut.status
                        $stageReason = [string]$stageOut.reason_code
                    }
                    'guest.bootstrap' {
                        $prof = if ($s.profile) { [string]$s.profile } else { 'windows-minimal' }
                        $stageOut = Invoke-VmLabGuestBootstrap -Name ([string]$def.vm.name) -Profile $prof -Credential $Credential -Apply -ManifestRoot $ManifestRoot
                        $stageStatus = if ($stageOut.status -eq 'bootstrapped') { 'SUCCEEDED' } else { 'FAILED' }
                        $stageReason = [string]$stageOut.status
                    }
                    'guest.exec' {
                        $cmdSpec = $def.commands.($s.command_ref)
                        $argsArr = if ($s.args) { @($s.args) } elseif ($cmdSpec.args) { @($cmdSpec.args) } else { @() }
                        $cwd = if ($s.working_directory) { [string]$s.working_directory } elseif ($cmdSpec.working_directory) { [string]$cmdSpec.working_directory } else { 'C:\Windows\Temp' }
                        $envHt = @{}
                        if ($s.environment) {
                            foreach ($p in $s.environment.PSObject.Properties) { $envHt[$p.Name] = [string]$p.Value }
                        }
                        $geTimeout = if ($null -ne $s.timeout_seconds) { [int]$s.timeout_seconds } else { 300 }
                        $geIdem = if ($s.idempotency_class) { [string]$s.idempotency_class } else { 'replayable' }
                        $stageOut = Invoke-VmLabGuestCommand -Name ([string]$def.vm.name) -ExecutablePath ([string]$cmdSpec.executable) -ArgumentList $argsArr -WorkingDirectory $cwd -Environment $envHt -ExpectedSha256 ([string]$cmdSpec.sha256) -IdempotencyClass $geIdem -TimeoutSeconds $geTimeout -OperationId $OperationId -StageId $sid -Credential $Credential -Apply -AuthorizeGuestExec -ManifestRoot $ManifestRoot
                        $exitCodeVal = $stageOut.exit_code
                        if ($stageOut.stdout) { [System.IO.File]::WriteAllText((Join-Path $logsDir "$sid-$attempt.stdout.log"), [string]$stageOut.stdout) }
                        if ($stageOut.stderr) { [System.IO.File]::WriteAllText((Join-Path $logsDir "$sid-$attempt.stderr.log"), [string]$stageOut.stderr) }
                        $stageStatus = [string]$stageOut.status
                        $stageReason = [string]$stageOut.reason_code
                        if ($stageStatus -eq 'SUCCEEDED' -and $s.expected_status) {
                            if (-not $stageOut.parsed_json -or [string]$stageOut.parsed_json.status -ne [string]$s.expected_status) {
                                $stageStatus = 'FAILED'
                                $stageReason = 'expected_json_status_missing_or_mismatch'
                            }
                        }
                    }
                    'vm.checkpoint_transaction' {
                        $cpName = if ($s.checkpoint_name) { [string]$s.checkpoint_name } else { "$OperationId-$sid" }
                        $reqOff = if ($null -ne $s.require_off) { [bool]$s.require_off } else { $true }
                        $rest = if ($null -ne $s.restart_after) { [bool]$s.restart_after } else { $false }
                        $matchedRaw = @()
                        $vmObj = $null
                        if ($Resume) {
                            $vmObj = Get-VM -ErrorAction Stop | Where-Object { $_.Name -eq [string]$def.vm.name } | Select-Object -First 1
                            if (-not $vmObj) {
                                throw "vm_not_found: VM '$($def.vm.name)' not found during checkpoint resume."
                            }
                            Assert-VmLabTargetNotProtected -VmName $vmObj.Name -VmId ([string]$vmObj.Id)
                            $own = Test-VmLabOwnership -Vm $vmObj -ManifestRoot $ManifestRoot
                            if (-not $own.owned) {
                                throw "vm_not_owned: VM '$($def.vm.name)' is not owned by vm_lab ($($own.reason))."
                            }
                            if (-not [string]::IsNullOrWhiteSpace([string]$journal.vm_id) -and ([string]$vmObj.Id).ToLowerInvariant() -ne ([string]$journal.vm_id).ToLowerInvariant()) {
                                throw "vm_id_mismatch: Live VM id '$($vmObj.Id)' does not match journal vm_id '$($journal.vm_id)'."
                            }
                            if (-not [string]::IsNullOrWhiteSpace($ExpectedVmId) -and ([string]$vmObj.Id).ToLowerInvariant() -ne $ExpectedVmId.ToLowerInvariant()) {
                                throw "vm_id_mismatch: Live VM id '$($vmObj.Id)' does not match ExpectedVmId '$ExpectedVmId'."
                            }
                            $existingCps = @(Get-VmLabCheckpoint -Name ([string]$def.vm.name) -ManifestRoot $ManifestRoot)
                            $matchedRaw = @($existingCps | Where-Object { [string]$_.name -eq $cpName })
                        }
                        if ($matchedRaw.Count -gt 1) {
                            throw "duplicate_checkpoint_matches: Found $($matchedRaw.Count) checkpoints named '$cpName' on VM '$($def.vm.name)'."
                        } elseif ($matchedRaw.Count -eq 1) {
                            $normCp = ConvertTo-VmLabNormalizedCheckpoint -Checkpoint $matchedRaw[0]
                            if (-not [string]::IsNullOrWhiteSpace($normCp.vm_name) -and $normCp.vm_name -ne [string]$def.vm.name) {
                                throw "checkpoint_vm_mismatch: Checkpoint '$($normCp.name)' belongs to '$($normCp.vm_name)', expected '$($def.vm.name)'."
                            }
                            if ($normCp.snapshot_type -ne 'Standard') {
                                throw "checkpoint_reconcile_invalid_type: Existing checkpoint '$cpName' has snapshot_type '$($normCp.snapshot_type)', expected 'Standard'."
                            }
                            $priorRecs = @(Get-ChildItem -LiteralPath $stageRecDir -Filter '*.json' -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
                            foreach ($pr in $priorRecs) {
                                $prObj = Get-Content -LiteralPath $pr.FullName -Raw -Encoding utf8 | ConvertFrom-Json -ErrorAction Stop
                                $recCpId = if ($prObj.detail.checkpoint_id) { [string]$prObj.detail.checkpoint_id } elseif ($prObj.detail.checkpoint.id) { [string]$prObj.detail.checkpoint.id } else { '' }
                                if (-not [string]::IsNullOrWhiteSpace($recCpId) -and $recCpId -ne $normCp.id) {
                                    throw "checkpoint_id_conflict: Prior receipt recorded checkpoint id '$recCpId', live checkpoint '$cpName' has id '$($normCp.id)'."
                                }
                            }
                            if ($rest) {
                                $startRes = Start-VmLabMachine -Name ([string]$def.vm.name) -Apply -ManifestRoot $ManifestRoot
                                if ($startRes.status -notin @('started', 'already_running')) {
                                    $stageOut = [pscustomobject]@{ status = 'PARTIAL'; reason_code = 'restart_failed_after_reconciled_checkpoint'; checkpoint_id = $normCp.id; checkpoint_name = $normCp.name; snapshot_type = $normCp.snapshot_type; checkpoint = $normCp; start = $startRes }
                                    $stageStatus = 'PARTIAL'
                                    $stageReason = 'restart_failed_after_reconciled_checkpoint'
                                } else {
                                    $readyRes = Wait-VmLabGuestReady -Name ([string]$def.vm.name) -Credential $Credential -PromptCredential:$PromptCredential -ManifestRoot $ManifestRoot
                                    $stageOut = [pscustomobject]@{ status = $readyRes.status; reason_code = if ($readyRes.status -eq 'SUCCEEDED') { 'checkpoint_reconciled_existing' } else { [string]$readyRes.reason_code }; checkpoint_id = $normCp.id; checkpoint_name = $normCp.name; snapshot_type = $normCp.snapshot_type; checkpoint = $normCp; start = $startRes; readiness = $readyRes }
                                    $stageStatus = [string]$readyRes.status
                                    $stageReason = if ($stageStatus -eq 'SUCCEEDED') { 'checkpoint_reconciled_existing' } else { [string]$readyRes.reason_code }
                                }
                            } elseif ($reqOff -and [string]$vmObj.State -ne 'Off') {
                                $stageOut = [pscustomobject]@{ status = 'PARTIAL'; reason_code = 'vm_not_off_for_reconciled_checkpoint'; vm_state = [string]$vmObj.State; checkpoint_id = $normCp.id; checkpoint_name = $normCp.name; snapshot_type = $normCp.snapshot_type; checkpoint = $normCp }
                                $stageStatus = 'PARTIAL'
                                $stageReason = 'vm_not_off_for_reconciled_checkpoint'
                            } else {
                                $stageOut = [pscustomobject]@{ status = 'SUCCEEDED'; reason_code = 'checkpoint_reconciled_existing'; checkpoint_id = $normCp.id; checkpoint_name = $normCp.name; snapshot_type = $normCp.snapshot_type; checkpoint = $normCp }
                                $stageStatus = 'SUCCEEDED'
                                $stageReason = 'checkpoint_reconciled_existing'
                            }
                        } else {
                            $stageOut = Invoke-VmLabCheckpointTransaction -Name ([string]$def.vm.name) -CheckpointName $cpName -RequireOff:$reqOff -RestartAfter:$rest -Credential $Credential -Apply -AuthorizeVmLifecycle -ManifestRoot $ManifestRoot
                            $stageStatus = [string]$stageOut.status
                            $stageReason = [string]$stageOut.reason_code
                        }
                    }
                    'evidence.collect' {
                        $stageEvDir = Join-Path $evDir $sid
                        $roots = @($s.sources)
                        $stageOut = Receive-VmLabGuestEvidence -Name ([string]$def.vm.name) -GuestRoots $roots -HostDestination $stageEvDir -OperationId $OperationId -Credential $Credential -Apply -ManifestRoot $ManifestRoot
                        $stageStatus = if ($stageOut.status -eq 'EVIDENCE_COMPLETE') { 'SUCCEEDED' } elseif ($stageOut.status -eq 'EVIDENCE_PARTIAL') { 'PARTIAL' } else { 'FAILED' }
                        $stageReason = [string]$stageOut.reason_code
                        $journal.evidence_index += $stageEvDir
                    }
                    'workflow.assert' {
                        $failedPrior = @()
                        foreach ($priorSid in $planCheck.stage_order) {
                            if ($priorSid -eq $sid) { break }
                            if ([string]$journal.stage_states.$priorSid -ne 'SUCCEEDED') {
                                $failedPrior += "$priorSid=$([string]$journal.stage_states.$priorSid)"
                            }
                        }
                        if ($failedPrior.Count -gt 0) {
                            $stageOut = [pscustomobject]@{ status = 'FAILED'; failed_prior_stages = @($failedPrior) }
                            $stageStatus = 'FAILED'
                            $stageReason = 'prior_stage_not_succeeded'
                        } else {
                            $stageOut = [pscustomobject]@{ status = 'SUCCEEDED'; checked = @($s.assertions) }
                            $stageStatus = 'SUCCEEDED'
                            $stageReason = 'assertions_passed'
                        }
                    }
                }
            } catch {
                $stageStatus = 'FAILED'
                $stageReason = 'stage_exception'
                $stageOut = [pscustomobject]@{ error = $_.Exception.Message }
                $journal.last_error = $_.Exception.Message
            }

            $receipt = [ordered]@{
                schema_version           = 1
                operation_id             = $OperationId
                stage_id                 = $sid
                stage_type               = [string]$s.type
                attempt                  = $attempt
                vm_id                    = [string]$journal.vm_id
                started_at               = $startedAt
                finished_at              = [DateTimeOffset]::UtcNow.ToString('o')
                authorization_capability = $cap
                result_status            = $stageStatus
                reason_code              = $stageReason
                exit_code                = $exitCodeVal
                detail                   = $stageOut
            }
            $recPath = Join-Path $stageRecDir "$attempt.json"
            Write-VmLabJsonAtomic -Path $recPath -Data $receipt

            $journal.stage_states.$sid = $stageStatus
            $journal.updated_at = [DateTimeOffset]::UtcNow.ToString('o')
            if ($stageStatus -ne 'SUCCEEDED') {
                if ($stageStatus -eq 'FAILED' -and $s.on_failure -and ([string]$s.on_failure).StartsWith('cleanup_stage:')) {
                    $cleanupId = ([string]$s.on_failure).Substring('cleanup_stage:'.Length)
                    $null = $deferredCleanupStages.Add($cleanupId)
                    $cs = $stageMap[$cleanupId]
                    $cCap = [string]$capPolicy[[string]$cs.type]
                    $cCapOk = Test-VmLabCapabilityAuthorized -Capability $cCap -Apply:$Apply -AuthorizeHostMutation:$AuthorizeHostMutation -AuthorizeVmLifecycle:$AuthorizeVmLifecycle -AuthorizeGuestMutation:$AuthorizeGuestMutation -AuthorizeGuestExec:$AuthorizeGuestExec -AuthorizeElevation:$AuthorizeElevation
                    if ($cCapOk -and $cs.type -eq 'guest.exec') {
                        $cSpec = $def.commands.($cs.command_ref)
                        $cArgs = if ($cs.args) { @($cs.args) } elseif ($cSpec.args) { @($cSpec.args) } else { @() }
                        $cCwd = if ($cs.working_directory) { [string]$cs.working_directory } elseif ($cSpec.working_directory) { [string]$cSpec.working_directory } else { 'C:\Windows\Temp' }
                        $cOut = Invoke-VmLabGuestCommand -Name ([string]$def.vm.name) -ExecutablePath ([string]$cSpec.executable) -ArgumentList $cArgs -WorkingDirectory $cCwd -OperationId $OperationId -StageId $cleanupId -Credential $Credential -Apply -AuthorizeGuestExec -ManifestRoot $ManifestRoot
                        $journal.stage_states.$cleanupId = [string]$cOut.status
                    } elseif (-not $cCapOk) {
                        $journal.stage_states.$cleanupId = 'BLOCKED'
                    }
                }
                if ($stageStatus -eq 'FAILED' -and [string]$s.on_failure -eq 'continue') {
                    Write-VmLabJsonAtomic -Path $journalPath -Data $journal
                    continue
                }
                $journal.overall_state = $stageStatus
                Write-VmLabJsonAtomic -Path $journalPath -Data $journal
                $finalStatus = $stageStatus
                $finalReason = $stageReason
                break
            }
            Write-VmLabJsonAtomic -Path $journalPath -Data $journal
        }

        if ($finalStatus -eq 'SUCCEEDED') {
            $journal.overall_state = 'SUCCEEDED'
            $journal.updated_at = [DateTimeOffset]::UtcNow.ToString('o')
            Write-VmLabJsonAtomic -Path $journalPath -Data $journal
        }

        return [pscustomobject]@{
            status          = $finalStatus
            reason_code     = $finalReason
            operation_id    = $OperationId
            workflow_id     = $planCheck.workflow_id
            workflow_digest = $planCheck.workflow_digest
            vm_id           = $journal.vm_id
            vm_name         = $journal.vm_name
            operation_dir   = $opDir
            stage_states    = $journal.stage_states
        }
    } finally {
        Exit-VmLabOperationLock -LockPath $lockPath
    }
}
