#Requires -Version 7.0
<#
.SYNOPSIS
    Foreground, explicitly authorized elevated runner for a bounded vm_lab workflow request.
.DESCRIPTION
    Validates a typed plan request created by New-VmLabApprovedPlanRequest, checks single-use
    consumption, expiration, workflow digest integrity, and explicit -OperatorConsent, then
    dispatches only compiled vm_lab workflow operations and writes a durable receipt.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory)][string]$RequestPath,
    [string]$ExpectedRequestDigest,
    [switch]$OperatorConsent,
    [switch]$DryRun,
    [pscredential]$Credential
)

$ErrorActionPreference = 'Stop'
if (-not (Get-Module -Name vm_lab)) {
    Import-Module (Join-Path $PSScriptRoot 'vm_lab.psd1') -Force -WarningAction SilentlyContinue
}

$verified = Test-VmLabApprovedPlanRequest -RequestPath $RequestPath -ExpectedRequestDigest $ExpectedRequestDigest
$req = $verified.request
$opRoot = Test-VmLabSafePath -Path ([string]$req.operation_root) -Label 'operation_root' -CheckReparsePoints
$opDir = Test-VmLabSafePath -Path (Join-Path $opRoot ([string]$req.operation_id)) -Label 'op_dir' -WithinRoot $opRoot -CheckReparsePoints
$receiptPath = Join-Path $opDir "approved-plan-receipt-$($req.request_id).json"

if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
    throw "approval_already_consumed: Request '$($req.request_id)' already has receipt '$receiptPath'."
}

if (-not $OperatorConsent -or $DryRun -or $WhatIfPreference -or -not $PSCmdlet.ShouldProcess([string]$req.vm_name, "Execute approved plan request '$($req.request_id)'")) {
    $out = [pscustomobject]@{
        status         = if ($OperatorConsent) { 'PLANNED' } else { 'BLOCKED' }
        reason_code    = if ($OperatorConsent) { 'dry_run_not_applied' } else { 'operator_consent_required' }
        request_id     = $req.request_id
        request_digest = $verified.request_digest
        operation_id   = $req.operation_id
        receipt_path   = $receiptPath
    }
    $out | ConvertTo-Json -Depth 10
    if ($OperatorConsent) { exit 0 } else { exit 1 }
}

if (-not (Test-Path -LiteralPath $opDir -PathType Container)) {
    New-Item -ItemType Directory -Path $opDir -Force | Out-Null
}

# Atomically claim the single-use receipt before executing to eliminate TOCTOU replay races
$claimReceipt = [ordered]@{
    schema_version  = 1
    request_id      = $req.request_id
    request_digest  = $verified.request_digest
    operation_id    = $req.operation_id
    workflow_digest = $req.workflow_digest
    executed_by     = "$env:USERDOMAIN\$env:USERNAME"
    started_at      = [DateTimeOffset]::UtcNow.ToString('o')
    result_status   = 'IN_PROGRESS'
    reason_code     = 'approval_claimed'
    vm_id           = [string]$req.expected_vm_id
}
try {
    $claimFs = [System.IO.File]::Open($receiptPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $claimBytes = [System.Text.Encoding]::UTF8.GetBytes(($claimReceipt | ConvertTo-Json -Depth 10))
        $claimFs.Write($claimBytes, 0, $claimBytes.Length)
    } finally {
        $claimFs.Dispose()
    }
} catch [System.IO.IOException] {
    throw "approval_already_consumed: Request '$($req.request_id)' was already claimed or executed at '$receiptPath'."
}

$caps = @($req.allowed_capabilities)
$wfArgs = @{
    WorkflowPath           = [string]$req.workflow_path
    OperationId            = [string]$req.operation_id
    OperationRoot          = [string]$req.operation_root
    ExpectedWorkflowDigest = [string]$req.workflow_digest
    Apply                  = $true
    AuthorizeHostMutation  = ($caps -contains 'host_mutation')
    AuthorizeVmLifecycle   = ($caps -contains 'vm_lifecycle')
    AuthorizeGuestMutation = ($caps -contains 'guest_mutation')
    AuthorizeGuestExec     = ($caps -contains 'guest_exec')
    AuthorizeElevation     = $true
}
if (-not [string]::IsNullOrWhiteSpace([string]$req.expected_vm_id)) {
    $wfArgs.ExpectedVmId = [string]$req.expected_vm_id
}
if ($null -ne $Credential) { $wfArgs.Credential = $Credential }

$wfResult = $null
$execError = $null
try {
    $wfResult = Invoke-VmLabWorkflow @wfArgs
} catch {
    $execError = $_.Exception.Message
}

$receipt = [ordered]@{
    schema_version  = 1
    request_id      = $req.request_id
    request_digest  = $verified.request_digest
    operation_id    = $req.operation_id
    workflow_digest = $req.workflow_digest
    executed_by     = "$env:USERDOMAIN\$env:USERNAME"
    started_at      = $claimReceipt.started_at
    executed_at     = [DateTimeOffset]::UtcNow.ToString('o')
    result_status   = if ($null -ne $execError) { 'FAIL' } else { $wfResult.status }
    reason_code     = if ($null -ne $execError) { 'approved_plan_execution_exception' } else { $wfResult.reason_code }
    vm_id           = if ($null -ne $wfResult) { $wfResult.vm_id } else { [string]$req.expected_vm_id }
    error           = $execError
}
$tmp = "$receiptPath.tmp.$PID"
[System.IO.File]::WriteAllText($tmp, ($receipt | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::Move($tmp, $receiptPath, $true)

if ($null -ne $execError) {
    throw "Approved plan execution failed: $execError"
}

$wfResult | ConvertTo-Json -Depth 10
if ($wfResult.status -in @('SUCCEEDED', 'AWAITING_INTERACTION')) { exit 0 } else { exit 1 }
