#Requires -Version 7.0

function New-VmLabApprovedPlanRequest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WorkflowPath,
        [Parameter(Mandatory)][string]$OutputPath,
        [Parameter(Mandatory)][string[]]$AllowedCapabilities,
        [string]$OperationId = ([DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)),
        [string]$ExpectedVmId = '',
        [int]$ExpiresInMinutes = 30
    )
    $plan = Test-VmLabWorkflowPlan -WorkflowPath $WorkflowPath
    Assert-VmLabTargetNotProtected -VmName $plan.vm_name -VmId $ExpectedVmId
    $outFull = Test-VmLabSafePath -Path $OutputPath -Label 'OutputPath' -CheckReparsePoints

    $validCaps = Get-VmLabWorkflowCapabilities
    foreach ($c in $AllowedCapabilities) {
        if ($validCaps -notcontains $c) {
            throw "Unknown capability '$c' in AllowedCapabilities."
        }
    }
    foreach ($rc in @($plan.required_capabilities)) {
        if ($rc -ne 'none' -and ($AllowedCapabilities -notcontains $rc)) {
            throw "Approved plan request does not authorize required workflow capability '$rc'."
        }
    }

    $reqBody = [ordered]@{
        schema_version       = 1
        request_id           = ('req-' + [guid]::NewGuid().ToString('N').Substring(0, 12))
        operation_id         = $OperationId
        workflow_path        = $plan.workflow_path
        workflow_id          = $plan.workflow_id
        workflow_digest      = $plan.workflow_digest
        operation_root       = $plan.operation_root
        vm_name              = $plan.vm_name
        expected_vm_id       = $ExpectedVmId
        allowed_capabilities = @($AllowedCapabilities | Select-Object -Unique)
        created_at           = [DateTimeOffset]::UtcNow.ToString('o')
        expires_at           = [DateTimeOffset]::UtcNow.AddMinutes([Math]::Max(1, $ExpiresInMinutes)).ToString('o')
    }
    $reqDigest = Get-VmLabCanonicalSha256 -InputObject $reqBody
    $reqObj = [ordered]@{}
    foreach ($k in $reqBody.Keys) { $reqObj[$k] = $reqBody[$k] }
    $reqObj['request_digest'] = $reqDigest

    Write-VmLabJsonAtomic -Path $outFull -Data $reqObj
    return [pscustomobject]@{
        status         = 'PLANNED'
        reason_code    = 'approved_plan_request_created'
        request_path   = $outFull
        request_id     = $reqObj.request_id
        request_digest = $reqDigest
        operation_id   = $OperationId
        expires_at     = $reqObj.expires_at
    }
}

function Test-VmLabApprovedPlanRequest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RequestPath,
        [string]$ExpectedRequestDigest
    )
    $reqFull = Test-VmLabSafePath -Path $RequestPath -Label 'RequestPath' -CheckReparsePoints
    if (-not (Test-Path -LiteralPath $reqFull -PathType Leaf)) {
        throw "Approved plan request not found: '$reqFull'."
    }
    $rawJson = Get-Content -LiteralPath $reqFull -Raw -Encoding utf8
    $req = $rawJson | ConvertFrom-Json -ErrorAction Stop
    if ($req.schema_version -ne 1) {
        throw "Unsupported approved plan request schema_version '$($req.schema_version)'."
    }
    Assert-VmLabTargetNotProtected -VmName ([string]$req.vm_name) -VmId ([string]$req.expected_vm_id)

    $jsonDoc = [System.Text.Json.JsonDocument]::Parse($rawJson)
    try {
        $createdAtRaw = $jsonDoc.RootElement.GetProperty('created_at').GetString()
        $expiresAtRaw = $jsonDoc.RootElement.GetProperty('expires_at').GetString()
    }
    finally {
        $jsonDoc.Dispose()
    }

    $body = [ordered]@{
        schema_version       = $req.schema_version
        request_id           = $req.request_id
        operation_id         = $req.operation_id
        workflow_path        = $req.workflow_path
        workflow_id          = $req.workflow_id
        workflow_digest      = $req.workflow_digest
        operation_root       = $req.operation_root
        vm_name              = $req.vm_name
        expected_vm_id       = $req.expected_vm_id
        allowed_capabilities = @($req.allowed_capabilities)
        created_at           = $createdAtRaw
        expires_at           = $expiresAtRaw
    }
    $computed = Get-VmLabCanonicalSha256 -InputObject $body
    if ($computed -ne [string]$req.request_digest) {
        throw "Approved plan request digest mismatch (expected '$($req.request_digest)', computed '$computed')."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedRequestDigest) -and $computed -ne $ExpectedRequestDigest.ToLowerInvariant()) {
        throw "Approved plan request digest does not match operator-supplied -ExpectedRequestDigest."
    }

    $expTime = [DateTimeOffset]::Parse($expiresAtRaw)
    if ([DateTimeOffset]::UtcNow -gt $expTime) {
        throw "Approved plan request '$($req.request_id)' expired at '$expiresAtRaw'."
    }

    $plan = Test-VmLabWorkflowPlan -WorkflowPath ([string]$req.workflow_path)
    if ($plan.workflow_digest -ne [string]$req.workflow_digest) {
        throw "Workflow file digest changed since request creation (expected '$($req.workflow_digest)', actual '$($plan.workflow_digest)')."
    }
    foreach ($rc in @($plan.required_capabilities)) {
        if ($rc -ne 'none' -and (@($req.allowed_capabilities) -notcontains $rc)) {
            throw "Approved plan request does not authorize required workflow capability '$rc'."
        }
    }

    return [pscustomobject]@{
        valid          = $true
        request        = $req
        request_path   = $reqFull
        request_digest = $computed
        workflow_plan  = $plan
    }
}
