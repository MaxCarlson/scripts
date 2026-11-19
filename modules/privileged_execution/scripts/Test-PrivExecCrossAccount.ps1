#Requires -Version 7.0
<#
.SYNOPSIS
    Gate 2 cross-account client verification script (runs under the non-admin Agent or Unauthorized account).
.DESCRIPTION
    Connects to a running PrivExecBroker over the local named pipe using .NET NamedPipeClientStream
    (works on any Windows 11 account without requiring per-user Python) and verifies filesystem write
    denials against C:\ProgramData\PrivExec. Uses synthetic non-H4 operations only.
#>
[CmdletBinding()]
param(
    [string]$PipeName = 'privexec-broker-v1',
    [string]$InstallRoot = 'C:\ProgramData\PrivExec',
    [ValidateSet('AuthorizedAgent', 'UnauthorizedAccount')]
    [string]$Role = 'AuthorizedAgent',
    [string]$TargetId = 'synth-target-1',
    [switch]$ExpectSameUserOperator
)

$ErrorActionPreference = 'Stop'

function Invoke-PrivExecPipeJson {
    param([Parameter(Mandatory)][string]$Pipe, [Parameter(Mandatory)][hashtable]$Payload)
    $json = $Payload | ConvertTo-Json -Depth 8 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $lenBytes = [System.BitConverter]::GetBytes([uint32]$bytes.Length)

    $client = [System.IO.Pipes.NamedPipeClientStream]::new('.', $Pipe, [System.IO.Pipes.PipeDirection]::InOut)
    try {
        $client.Connect(5000)
        $client.Write($lenBytes, 0, 4)
        $client.Write($bytes, 0, $bytes.Length)
        $client.Flush()

        $inLenBuf = New-Object byte[] 4
        $read = 0
        while ($read -lt 4) {
            $n = $client.Read($inLenBuf, $read, 4 - $read)
            if ($n -eq 0) { throw 'Unexpected EOF reading pipe response header.' }
            $read += $n
        }
        $respLen = [System.BitConverter]::ToUInt32($inLenBuf, 0)
        $respBuf = New-Object byte[] $respLen
        $offset = 0
        while ($offset -lt $respLen) {
            $n = $client.Read($respBuf, $offset, $respLen - $offset)
            if ($n -eq 0) { throw 'Unexpected EOF reading pipe response body.' }
            $offset += $n
        }
        return ([System.Text.Encoding]::UTF8.GetString($respBuf) | ConvertFrom-Json)
    } finally {
        $client.Dispose()
    }
}

$whoami = [Security.Principal.WindowsIdentity]::GetCurrent()
$results = [System.Collections.Generic.List[object]]::new()

if ($Role -eq 'UnauthorizedAccount') {
    $denied = $false
    $detail = ''
    try {
        $resp = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{ protocol_version = 1; action = 'status' }
        if ($resp.ok -eq $false -or $resp.diagnostic_category -eq 'unauthorized_identity') {
            $denied = $true
            $detail = $resp.diagnostic_category
        }
    } catch {
        $denied = $true
        $detail = $_.Exception.Message
    }
    if (-not $denied) {
        throw "UnauthorizedAccount '$($whoami.Name)' was NOT denied access to pipe '$PipeName'."
    }
    [pscustomobject]@{
        role    = $Role
        account = $whoami.Name
        sid     = $whoami.User.Value
        passed  = $true
        detail  = $detail
    } | ConvertTo-Json -Depth 4
    exit 0
}

# 1. Verify status succeeds under authorized non-admin account
$st = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{ protocol_version = 1; action = 'status' }
if (-not $st.ok -or $st.status -ne 'active') {
    throw "AuthorizedAgent status failed: $($st | ConvertTo-Json -Compress)"
}
$results.Add(@{ check = 'status'; passed = $true; session_id = $st.session_id })

# 2. Verify synthetic read-only capability succeeds
$reqRead = "gate2-read-" + [guid]::NewGuid().ToString('N').Substring(0, 8)
$rRead = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{
    protocol_version = 1
    action           = 'run'
    request_id       = $reqRead
    capability       = 'synthetic.echo'
    target           = @{ type = 'synthetic'; id = $TargetId }
    mode             = 'dry_run'
    parameters       = @{ message = 'gate2-read-ok' }
}
if ($rRead.state -ne 'succeeded') {
    throw "synthetic.echo failed: $($rRead | ConvertTo-Json -Compress)"
}
$results.Add(@{ check = 'synthetic_read_only'; passed = $true; operation_id = $rRead.operation_id })

# 3. Verify synthetic.mutate dry-run succeeds without mutating, then apply mutates, and result retrieves
$reqDryMut = "gate2-drymut-" + [guid]::NewGuid().ToString('N').Substring(0, 8)
$rDryMut = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{
    protocol_version = 1
    action           = 'run'
    request_id       = $reqDryMut
    capability       = 'synthetic.mutate'
    target           = @{ type = 'synthetic'; id = $TargetId }
    mode             = 'dry_run'
    parameters       = @{ marker = 'gate2-dry' }
}
if ($rDryMut.state -ne 'succeeded' -or $rDryMut.result.mode -ne 'dry_run') {
    throw "synthetic.mutate dry_run failed: $($rDryMut | ConvertTo-Json -Compress)"
}
$results.Add(@{ check = 'synthetic_mutate_dry_run'; passed = $true; operation_id = $rDryMut.operation_id })

$reqAppMut = "gate2-appmut-" + [guid]::NewGuid().ToString('N').Substring(0, 8)
$rAppMut = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{
    protocol_version = 1
    action           = 'run'
    request_id       = $reqAppMut
    capability       = 'synthetic.mutate'
    target           = @{ type = 'synthetic'; id = $TargetId }
    mode             = 'apply'
    parameters       = @{ marker = 'gate2-apply' }
}
if ($rAppMut.state -ne 'succeeded' -or $rAppMut.result.mode -ne 'apply') {
    throw "synthetic.mutate apply failed: $($rAppMut | ConvertTo-Json -Compress)"
}
$rLookup = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{
    protocol_version = 1
    action           = 'result'
    operation_id     = $rAppMut.operation_id
}
if ($rLookup.operation_id -ne $rAppMut.operation_id -or $rLookup.state -ne 'succeeded') {
    throw "result lookup failed: $($rLookup | ConvertTo-Json -Compress)"
}
$results.Add(@{ check = 'synthetic_mutate_apply_and_result'; passed = $true; operation_id = $rAppMut.operation_id })

# 4. Negative: duplicate request_id with altered payload rejected
$rMismatch = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{
    protocol_version = 1
    action           = 'run'
    request_id       = $reqAppMut
    capability       = 'synthetic.mutate'
    target           = @{ type = 'synthetic'; id = $TargetId }
    mode             = 'apply'
    parameters       = @{ marker = 'tampered' }
}
if ($rMismatch.diagnostic_category -ne 'request_id_payload_mismatch') {
    throw "Expected request_id_payload_mismatch, got: $($rMismatch | ConvertTo-Json -Compress)"
}
$results.Add(@{ check = 'idempotency_mismatch_denied'; passed = $true })

# 5. Negative: SID / authorization forgery rejected
$rForge = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{
    protocol_version = 1
    action           = 'run'
    request_id       = ("gate2-forge-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    capability       = 'synthetic.echo'
    target           = @{ type = 'synthetic'; id = $TargetId }
    mode             = 'dry_run'
    authorized       = $true
    parameters       = @{}
}
if ($rForge.diagnostic_category -ne 'forbidden_property') {
    throw "Expected forbidden_property, got: $($rForge | ConvertTo-Json -Compress)"
}
$results.Add(@{ check = 'forgery_denied'; passed = $true })

# 6. Negative: non-operator agent cannot shut down broker (unless smoke-tested in same-user mode)
if (-not $ExpectSameUserOperator) {
    $rStop = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{ protocol_version = 1; action = 'shutdown' }
    if ($rStop.diagnostic_category -ne 'operator_only_action') {
        throw "Expected operator_only_action, got: $($rStop | ConvertTo-Json -Compress)"
    }
    $results.Add(@{ check = 'agent_shutdown_denied'; passed = $true })
}

# 7. Negative: wrong target and unknown capability denied
$rTarget = Invoke-PrivExecPipeJson -Pipe $PipeName -Payload @{
    protocol_version = 1
    action           = 'run'
    request_id       = ("gate2-badt-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    capability       = 'synthetic.echo'
    target           = @{ type = 'synthetic'; id = 'synth-target-2' }
    mode             = 'dry_run'
    parameters       = @{}
}
if ($rTarget.diagnostic_category -ne 'unauthorized_target') {
    throw "Expected unauthorized_target, got: $($rTarget | ConvertTo-Json -Compress)"
}
$results.Add(@{ check = 'wrong_target_denied'; passed = $true })

# 8. Negative: agent cannot modify protected installed binaries, descriptors, adapters, or state
$protectedTargets = @(
    (Join-Path $InstallRoot 'bin\PrivExecBroker.dll'),
    (Join-Path $InstallRoot 'descriptors\synthetic.echo.json'),
    (Join-Path $InstallRoot 'adapters\Invoke-SyntheticMutationAdapter.ps1'),
    (Join-Path $InstallRoot 'state\privexec.db')
)
foreach ($pt in $protectedTargets) {
    $blocked = $false
    try {
        [System.IO.File]::OpenWrite($pt).Dispose()
    } catch [System.UnauthorizedAccessException] {
        $blocked = $true
    } catch {
        $blocked = $true
    }
    if (-not $blocked) {
        throw "SECURITY FAILURE: Agent account '$($whoami.Name)' was able to open '$pt' for write!"
    }
}
$results.Add(@{ check = 'filesystem_write_and_state_denied'; passed = $true; checked = $protectedTargets.Count })

[pscustomobject]@{
    role    = $Role
    account = $whoami.Name
    sid     = $whoami.User.Value
    passed  = $true
    checks  = $results
} | ConvertTo-Json -Depth 6
exit 0
