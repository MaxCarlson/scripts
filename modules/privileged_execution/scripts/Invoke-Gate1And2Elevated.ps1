#Requires -Version 7.0
<#
.SYNOPSIS
    Operator-run elevated validation harness for PrivExec Gates 1 and 2.
.DESCRIPTION
    Must be run from an elevated Administrator PowerShell 7 session after explicit
    operator authorization. Performs:
      - Gate 1: Install-PrivExec.ps1 -Apply -Mode CrossAccountIsolated + ACL/hash verification
      - Gate 2: Real cross-account isolation tests with a separate standard Windows user
                (either operator-supplied credentials or temporary standard test accounts)
                using synthetic non-H4 operations only.
    Does NOT execute any H4 capabilities or Hyper-V VM commands.
    Never logs or persists passwords.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\ProgramData\PrivExec',
    [string]$OperatorAccount = "$env:USERDOMAIN\$env:USERNAME",
    [string]$AgentAccount = '',
    [pscredential]$AgentCredential,
    [pscredential]$UnauthorizedCredential,
    [switch]$CreateTempTestAccounts,
    [string]$H4SourceDir = 'C:\Users\mcarls\src\scripts\.worktrees\rc-h4-task-discovery-20261115\modules\resource_coordinator\tools\h4_qualification',
    [string]$EvidenceOut = 'C:\ProgramData\PrivExec\gate1-2-evidence.json'
)

$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw 'Invoke-Gate1And2Elevated.ps1 requires an elevated Administrator PowerShell 7 session.'
}

$createdUsers = [System.Collections.Generic.List[string]]::new()

function New-TransientTestUser {
    param([Parameter(Mandatory)][string]$Username)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 24
    $rng.GetBytes($bytes)
    $raw = 'Px!' + [Convert]::ToBase64String($bytes) + '9a'
    $sec = ConvertTo-SecureString -String $raw -AsPlainText -Force
    $raw = $null
    New-LocalUser -Name $Username -Password $sec -AccountNeverExpires -Description 'Temporary PrivExec Gate 2 standard test account' | Out-Null
    Add-LocalGroupMember -Group 'Users' -Member $Username | Out-Null
    $createdUsers.Add($Username)
    return [pscredential]::new("$env:COMPUTERNAME\$Username", $sec)
}

$brokerProc = $null
$tempGrant = $null
$tempOutDir = Join-Path $env:TEMP ('privexec-g2-' + [guid]::NewGuid().ToString('N').Substring(0, 8))

try {
    if ($CreateTempTestAccounts) {
        $AgentCredential = New-TransientTestUser -Username ('PrivExecAg_' + [guid]::NewGuid().ToString('N').Substring(0, 6))
        $UnauthorizedCredential = New-TransientTestUser -Username ('PrivExecUn_' + [guid]::NewGuid().ToString('N').Substring(0, 6))
        $AgentAccount = $AgentCredential.UserName
    } elseif ([string]::IsNullOrWhiteSpace($AgentAccount) -or -not $AgentCredential) {
        throw 'Supply -AgentAccount and -AgentCredential, or pass -CreateTempTestAccounts.'
    }

    # Gate 1: Elevated staged installation
    $installScript = Join-Path $PSScriptRoot 'Install-PrivExec.ps1'
    $installJson = & $installScript -Apply -Mode CrossAccountIsolated `
        -InstallRoot $InstallRoot `
        -OperatorAccount $OperatorAccount `
        -AgentAccount $AgentAccount `
        -H4SourceDir $H4SourceDir `
        -Json
    if ($LASTEXITCODE -ne 0) { throw 'Install-PrivExec.ps1 failed.' }
    $installReport = $installJson | ConvertFrom-Json

    # Verify ACLs and zero unexpected services/tasks
    $aclState = (& icacls (Join-Path $InstallRoot 'state')) -join "`n"
    $aclDesc = (& icacls (Join-Path $InstallRoot 'descriptors')) -join "`n"
    if ($aclState -match [regex]::Escape($AgentAccount.Split('\')[-1])) {
        throw "SECURITY FAILURE: Agent account appears in state directory ACL!"
    }
    $privServices = @(Get-Service -Name '*PrivExec*' -ErrorAction SilentlyContinue)
    $privTasks = @(Get-ScheduledTask -TaskName '*PrivExec*' -ErrorAction SilentlyContinue)
    if ($privServices.Count -gt 0 -or $privTasks.Count -gt 0) {
        throw 'Unexpected PrivExec Windows service or scheduled task found.'
    }

    # Gate 2: Start installed broker from C:\ProgramData\PrivExec with synthetic-only grant
    $agentSid = ([System.Security.Principal.NTAccount]$AgentAccount).Translate([System.Security.Principal.SecurityIdentifier]).Value
    $pipeName = 'privexec-gate2-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $tempGrant = Join-Path $InstallRoot 'state\gate2-grant.json'
    @{
        allowed_client_sids           = @($agentSid)
        allowed_capabilities          = @('synthetic.echo', 'synthetic.mutate')
        allowed_targets               = @('synth-target-1')
        allow_mutation                = $true
        allowed_mutation_capabilities = @('synthetic.mutate')
        ttl_seconds                   = 300
    } | ConvertTo-Json | Set-Content -LiteralPath $tempGrant -Encoding utf8NoBOM

    $brokerOut = Join-Path $InstallRoot 'state\gate2-broker.stdout.log'
    $brokerErr = Join-Path $InstallRoot 'state\gate2-broker.stderr.log'
    Remove-Item -LiteralPath $brokerOut, $brokerErr -Force -ErrorAction SilentlyContinue
    $brokerProc = Start-Process -FilePath 'dotnet' -ArgumentList @(
        (Join-Path $InstallRoot 'bin\PrivExecBroker.dll'),
        '--pipe', $pipeName,
        '--descriptors-dir', (Join-Path $InstallRoot 'descriptors'),
        '--state-dir', (Join-Path $InstallRoot 'state'),
        '--grant-file', $tempGrant
    ) -RedirectStandardOutput $brokerOut -RedirectStandardError $brokerErr -PassThru -WindowStyle Hidden

    $deadline = (Get-Date).AddSeconds(15)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($brokerProc.HasExited) {
            throw "Installed broker exited early ($($brokerProc.ExitCode)): $(Get-Content -LiteralPath $brokerErr -Raw -ErrorAction SilentlyContinue)"
        }
        if ((Test-Path -LiteralPath $brokerOut) -and ((Get-Content -LiteralPath $brokerOut -Raw) -match 'PRIVEXEC_BROKER_READY')) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 150
    }
    if (-not $ready) { throw 'Timed out waiting for installed broker readiness.' }

    New-Item -ItemType Directory -Path $tempOutDir -Force | Out-Null
    & icacls $tempOutDir /grant "${AgentAccount}:(OI)(CI)F" | Out-Null

    $clientScript = Join-Path $InstallRoot 'client\Test-PrivExecCrossAccount.ps1'
    $agentOut = Join-Path $tempOutDir 'agent-out.json'
    $agentErr = Join-Path $tempOutDir 'agent-err.txt'
    $pAgent = Start-Process -FilePath 'C:\Program Files\PowerShell\7\pwsh.exe' `
        -Credential $AgentCredential `
        -WorkingDirectory $tempOutDir `
        -ArgumentList @('-NoProfile', '-NonInteractive', '-File', $clientScript, '-PipeName', $pipeName, '-InstallRoot', $InstallRoot, '-Role', 'AuthorizedAgent') `
        -RedirectStandardOutput $agentOut -RedirectStandardError $agentErr -Wait -PassThru -WindowStyle Hidden
    if ($pAgent.ExitCode -ne 0) {
        throw "AuthorizedAgent cross-account check failed ($($pAgent.ExitCode)): $(Get-Content -LiteralPath $agentErr -Raw -ErrorAction SilentlyContinue)"
    }
    $agentReport = Get-Content -LiteralPath $agentOut -Raw | ConvertFrom-Json

    $unauthReport = $null
    if ($UnauthorizedCredential) {
        & icacls $tempOutDir /grant "$($UnauthorizedCredential.UserName):(OI)(CI)F" | Out-Null
        $unOut = Join-Path $tempOutDir 'unauth-out.json'
        $unErr = Join-Path $tempOutDir 'unauth-err.txt'
        $pUnauth = Start-Process -FilePath 'C:\Program Files\PowerShell\7\pwsh.exe' `
            -Credential $UnauthorizedCredential `
            -WorkingDirectory $tempOutDir `
            -ArgumentList @('-NoProfile', '-NonInteractive', '-File', $clientScript, '-PipeName', $pipeName, '-InstallRoot', $InstallRoot, '-Role', 'UnauthorizedAccount') `
            -RedirectStandardOutput $unOut -RedirectStandardError $unErr -Wait -PassThru -WindowStyle Hidden
        if ($pUnauth.ExitCode -ne 0) {
            throw "UnauthorizedAccount cross-account check failed ($($pUnauth.ExitCode)): $(Get-Content -LiteralPath $unErr -Raw -ErrorAction SilentlyContinue)"
        }
        $unauthReport = Get-Content -LiteralPath $unOut -Raw | ConvertFrom-Json
    }

    # Clean operator shutdown via local operator identity over named pipe
    $shutdownJson = @{ protocol_version = 1; action = 'shutdown' } | ConvertTo-Json -Compress
    $sBytes = [System.Text.Encoding]::UTF8.GetBytes($shutdownJson)
    $sLen = [System.BitConverter]::GetBytes([uint32]$sBytes.Length)
    $opPipe = [System.IO.Pipes.NamedPipeClientStream]::new('.', $pipeName, [System.IO.Pipes.PipeDirection]::InOut)
    try {
        $opPipe.Connect(5000)
        $opPipe.Write($sLen, 0, 4)
        $opPipe.Write($sBytes, 0, $sBytes.Length)
        $opPipe.Flush()
        $inLenBuf = New-Object byte[] 4
        $r = 0
        while ($r -lt 4) { $n = $opPipe.Read($inLenBuf, $r, 4 - $r); if ($n -eq 0) { break }; $r += $n }
        if ($r -eq 4) {
            $rl = [System.BitConverter]::ToUInt32($inLenBuf, 0)
            $rb = New-Object byte[] $rl
            $off = 0
            while ($off -lt $rl) { $n = $opPipe.Read($rb, $off, $rl - $off); if ($n -eq 0) { break }; $off += $n }
        }
    } finally {
        $opPipe.Dispose()
    }
    $brokerProc.WaitForExit(5000) | Out-Null

    $opIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $evidence = [ordered]@{
        completed_at_utc    = (Get-Date).ToUniversalTime().ToString('o')
        operator_account    = $opIdentity.Name
        operator_sid        = $opIdentity.User.Value
        agent_account       = $AgentAccount
        agent_sid           = $agentSid
        gate1_install       = $installReport
        acl_state           = $aclState
        acl_descriptors     = $aclDesc
        gate2_agent         = $agentReport
        gate2_unauthorized  = $unauthReport
        services_or_tasks   = 0
        h4_executed         = $false
    }
    $evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $EvidenceOut -Encoding utf8NoBOM
    Write-Output ($evidence | ConvertTo-Json -Depth 8)
}
finally {
    if ($brokerProc -and -not $brokerProc.HasExited) {
        $brokerProc.Kill()
        $brokerProc.WaitForExit(5000) | Out-Null
    }
    if ($tempGrant -and (Test-Path -LiteralPath $tempGrant)) {
        Remove-Item -LiteralPath $tempGrant -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $tempOutDir) {
        Remove-Item -LiteralPath $tempOutDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    foreach ($u in $createdUsers) {
        Remove-LocalUser -Name $u -ErrorAction SilentlyContinue
    }
}
