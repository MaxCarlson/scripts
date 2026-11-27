#Requires -Version 7.0
<#
.SYNOPSIS
    Operator-run elevated Gate 3 runner for PrivExec read-only H4 preflight (`h4.preflight`).
.DESCRIPTION
    Must be run from an elevated Administrator PowerShell 7 session after explicit
    operator approval for:
      1. Creating/using dedicated standard-user XERES\PrivExecAgent (Users group only).
      2. Rebinding C:\ProgramData\PrivExec ACLs to XERES\PrivExecAgent.
      3. Starting a h4.preflight-only broker via C:\Program Files\dotnet\dotnet.exe
         with interactive guest credential entry (--prompt-guest-credential).
      4. Executing one read-only h4.preflight (dry_run) under XERES\PrivExecAgent.
    Never executes Gate 4, qualification, recovery, or VM/checkpoint mutations.
    Never logs or persists passwords.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\ProgramData\PrivExec',
    [string]$OperatorAccount = "$env:USERDOMAIN\$env:USERNAME",
    [string]$AgentUsername = 'PrivExecAgent',
    [pscredential]$AgentCredential,
    [switch]$CreateAgentAccount,
    [string]$H4SourceDir = ([IO.Path]::Combine($env:USERPROFILE, 'src\llm-agent-toolkit\modules\resource_coordinator\tools\h4_qualification')),
    [string]$VmId = 'd8483f98-8884-4758-abd1-cd6107c83c03',
    [string]$VmName = 'RC-H4-Windows-Acceptance',
    [string]$CheckpointId = '9f45b469-382c-4be0-a50e-7a71384c7922',
    [string]$ExpectedGuestHost = 'DESKTOP-1ITSJV0',
    [string]$EvidenceOut = 'C:\ProgramData\PrivExec\state\gate3-evidence.json',
    [string]$DotnetExe = 'C:\Program Files\dotnet\dotnet.exe',
    [int]$BrokerReadyTimeoutSeconds = 120,
    [switch]$SkipElevationCheck,
    [switch]$SkipGitProvenanceCheck
)

$ErrorActionPreference = 'Stop'

if (-not $SkipElevationCheck) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        throw 'Invoke-Gate3Elevated.ps1 requires an elevated Administrator PowerShell 7 session.'
    }
}

function Assert-NoReparsePoint {
    param([Parameter(Mandatory)][string]$FullPath, [string]$Label = 'Path')
    $root = [System.IO.Path]::GetPathRoot($FullPath)
    $current = $FullPath
    while (-not [string]::IsNullOrWhiteSpace($current) -and $current -ne $root) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label traverses a reparse point at '$current'."
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

$moduleRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $moduleRoot)
$runId = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
$opIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isolatedRunRoot = "C:\ProgramData\PrivExec-Gate3Run\$runId"
$brokerProc = $null
$tempGrant = $null
$pipeName = 'privexec-gate3-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$createdAccountInThisRun = $false

$evidence = [ordered]@{
    run_id                    = $runId
    started_at_utc            = (Get-Date).ToUniversalTime().ToString('o')
    completed_at_utc          = $null
    status                    = 'started'
    current_step              = 'init'
    failing_step              = $null
    error                     = $null
    git_head                  = $null
    operator_account          = $opIdentity.Name
    operator_sid              = $opIdentity.User.Value
    agent_account             = "$env:COMPUTERNAME\$AgentUsername"
    agent_sid                 = $null
    agent_groups              = @()
    created_account_preserved = $false
    pre_rebind_acls           = $null
    gate3_install             = $null
    post_rebind_acl_state     = $null
    post_rebind_acl_desc      = $null
    broker_dll_sha256         = $null
    broker_pid                = $null
    broker_exit_code          = $null
    broker_startup_stage      = $null
    pipe_ready                = $false
    timeout_category          = $null
    vm_before                 = $null
    checkpoint_before         = $null
    gate3_preflight           = $null
    vm_after                  = $null
    checkpoint_after          = $null
    pipe_closed_verified      = $false
    temp_dir_created          = $false
    broker_killed_on_cleanup  = $false
    cleanup                   = [ordered]@{ temp_dir_removed = $false; grant_removed = $false; errors = @() }
    h4_mutations_executed     = $false
}

function Save-Gate3Evidence {
    $json = $evidence | ConvertTo-Json -Depth 10
    $dir = Split-Path -Parent $EvidenceOut
    if ($dir -and (Test-Path -LiteralPath $dir)) {
        $tmp = "$EvidenceOut.tmp"
        Set-Content -LiteralPath $tmp -Value $json -Encoding utf8NoBOM
        Move-Item -LiteralPath $tmp -Destination $EvidenceOut -Force
    }
}

function New-IsolatedAgentEnv {
    param([Parameter(Mandatory)][string]$TempDir, [Parameter(Mandatory)][string]$ProfileDir, [Parameter(Mandatory)][string]$Account)
    foreach ($d in @($ProfileDir, $TempDir)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        $acl = [System.Security.AccessControl.DirectorySecurity]::new()
        $acl.SetAccessRuleProtection($true, $false)
        $inh = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
        $prp = [System.Security.AccessControl.PropagationFlags]'None'
        $alw = [System.Security.AccessControl.AccessControlType]::Allow
        foreach ($acct in @('NT AUTHORITY\SYSTEM', 'BUILTIN\Administrators', $OperatorAccount, $Account)) {
            $sid = ([System.Security.Principal.NTAccount]$acct).Translate([System.Security.Principal.SecurityIdentifier])
            $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
                $sid, [System.Security.AccessControl.FileSystemRights]::FullControl, $inh, $prp, $alw))
        }
        [System.IO.FileSystemAclExtensions]::SetAccessControl([System.IO.DirectoryInfo]::new($d), $acl)
    }
    return @{
        SystemRoot   = $env:SystemRoot
        ComSpec      = $env:ComSpec
        WINDIR       = $env:WINDIR
        PATH         = "$env:SystemRoot\System32;$env:SystemRoot;C:\Program Files\PowerShell\7"
        TEMP         = $TempDir
        TMP          = $TempDir
        TMPDIR       = $TempDir
        USERPROFILE  = $ProfileDir
        LOCALAPPDATA = $ProfileDir
        APPDATA      = $ProfileDir
        HOME         = $ProfileDir
        HOMEDRIVE    = [System.IO.Path]::GetPathRoot($ProfileDir).TrimEnd('\')
        HOMEPATH     = $ProfileDir.Substring([System.IO.Path]::GetPathRoot($ProfileDir).Length - 1)
    }
}

function Stop-BrokerOverPipe {
    param([Parameter(Mandatory)][string]$Pipe, $Proc)
    try {
        $req = @{ protocol_version = 1; action = 'shutdown' } | ConvertTo-Json -Compress
        $b = [System.Text.Encoding]::UTF8.GetBytes($req)
        $len = [System.BitConverter]::GetBytes([uint32]$b.Length)
        $p = [System.IO.Pipes.NamedPipeClientStream]::new('.', $Pipe, [System.IO.Pipes.PipeDirection]::InOut, [System.IO.Pipes.PipeOptions]::None, [System.Security.Principal.TokenImpersonationLevel]::Impersonation)
        try {
            $p.Connect(5000)
            $p.Write($len, 0, 4)
            $p.Write($b, 0, $b.Length)
            $p.Flush()
        } finally {
            $p.Dispose()
        }
        if ($Proc) { $Proc.WaitForExit(5000) | Out-Null }
    } catch {
        if ($Proc -and -not $Proc.HasExited) {
            $Proc.Kill()
            $Proc.WaitForExit(5000) | Out-Null
        }
    }
}

try {
    # 0. Git/source provenance check
    if (-not $SkipGitProvenanceCheck) {
        $evidence['current_step'] = 'git_provenance'
        $gitStatus = (& git -C $repoRoot status --porcelain) -join "`n"
        if (-not [string]::IsNullOrWhiteSpace($gitStatus)) {
            throw "Refusing Gate 3 run on dirty repository '$repoRoot'."
        }
        $evidence['git_head'] = (& git -C $repoRoot rev-parse HEAD).Trim()
    }

    # 1. Account verification / provisioning
    $evidence['current_step'] = 'verify_agent_account'
    $existing = Get-LocalUser -Name $AgentUsername -ErrorAction SilentlyContinue
    if ($CreateAgentAccount) {
        if ($existing) {
            throw "Account '$AgentUsername' already exists; refusing to overwrite or reset an existing account."
        }
        if (-not $AgentCredential) {
            $pw = Read-Host -Prompt "Enter password for new standard user '$env:COMPUTERNAME\$AgentUsername'" -AsSecureString
            $AgentCredential = [pscredential]::new("$env:COMPUTERNAME\$AgentUsername", $pw)
        }
        New-LocalUser -Name $AgentUsername -Password $AgentCredential.Password -AccountNeverExpires -Description 'PrivExec dedicated standard-user agent' | Out-Null
        Add-LocalGroupMember -Group 'Users' -Member $AgentUsername | Out-Null
        $createdAccountInThisRun = $true
        $evidence['created_account_preserved'] = $true
    } elseif (-not $existing) {
        throw "Account '$AgentUsername' does not exist. Pass -CreateAgentAccount after operator approval."
    } elseif (-not $AgentCredential) {
        $pw = Read-Host -Prompt "Enter password for existing standard user '$env:COMPUTERNAME\$AgentUsername'" -AsSecureString
        $AgentCredential = [pscredential]::new("$env:COMPUTERNAME\$AgentUsername", $pw)
    }

    $agentSid = ([System.Security.Principal.NTAccount]"$env:COMPUTERNAME\$AgentUsername").Translate([System.Security.Principal.SecurityIdentifier]).Value
    $evidence['agent_sid'] = $agentSid
    $groups = @(Get-LocalGroup | ForEach-Object {
        $g = $_.Name
        if ((Get-LocalGroupMember -Group $g -ErrorAction SilentlyContinue).Name -contains "$env:COMPUTERNAME\$AgentUsername") { $g }
    })
    $evidence['agent_groups'] = $groups
    foreach ($privGroup in @('Administrators', 'Hyper-V Administrators', 'Remote Desktop Users', 'Power Users')) {
        if ($groups -contains $privGroup) {
            throw "SECURITY FAILURE: '$AgentUsername' is a member of privileged group '$privGroup'."
        }
    }
    Save-Gate3Evidence

    # 2. Protected installation rebind
    $evidence['current_step'] = 'rebind_acls'
    $evidence['pre_rebind_acls'] = (& icacls (Join-Path $InstallRoot 'descriptors')) -join "`n"
    $installScript = Join-Path $PSScriptRoot 'Install-PrivExec.ps1'
    $installOut = & pwsh -NoProfile -NonInteractive -File $installScript -Apply -Mode CrossAccountIsolated `
        -InstallRoot $InstallRoot -OperatorAccount $OperatorAccount -AgentAccount "$env:COMPUTERNAME\$AgentUsername" `
        -H4SourceDir $H4SourceDir -Json
    if ($LASTEXITCODE -ne 0) { throw "Install-PrivExec.ps1 failed ($LASTEXITCODE)." }
    $evidence['gate3_install'] = ($installOut | ConvertFrom-Json)
    $evidence['post_rebind_acl_state'] = (& icacls (Join-Path $InstallRoot 'state')) -join "`n"
    $evidence['post_rebind_acl_desc'] = (& icacls (Join-Path $InstallRoot 'descriptors')) -join "`n"
    if ($evidence['post_rebind_acl_state'] -match [regex]::Escape($AgentUsername)) {
        throw "SECURITY FAILURE: '$AgentUsername' appears in state directory ACL."
    }
    Save-Gate3Evidence

    # 3. Hyper-V VM & checkpoint pre-check
    $evidence['current_step'] = 'hyperv_precheck'
    Import-Module Hyper-V -ErrorAction Stop
    $vmBefore = Get-VM -Id ([guid]$VmId) -ErrorAction Stop
    if ($vmBefore.Name -ne $VmName) { throw "Unexpected VM name '$($vmBefore.Name)'." }
    if ($vmBefore.State -ne 'Running') { throw "VM '$VmName' is '$($vmBefore.State)', expected 'Running'." }
    $cpBefore = @(Get-VMSnapshot -VM $vmBefore -ErrorAction Stop | Where-Object { $_.Id -eq [guid]$CheckpointId })
    if ($cpBefore.Count -ne 1) { throw "Protected checkpoint '$CheckpointId' missing or ambiguous." }
    $evidence['vm_before'] = @{ name = $vmBefore.Name; id = [string]$vmBefore.Id; state = [string]$vmBefore.State }
    $evidence['checkpoint_before'] = @{ name = $cpBefore[0].Name; id = [string]$cpBefore[0].Id; creation_time = $cpBefore[0].CreationTime.ToUniversalTime().ToString('o') }
    Save-Gate3Evidence

    # 4. Trusted .NET runtime & broker launch-chain integrity + startup
    $evidence['current_step'] = 'broker_start'
    Assert-NoReparsePoint -FullPath $DotnetExe -Label 'Dotnet executable'
    if (-not (Test-Path -LiteralPath $DotnetExe -PathType Leaf)) {
        throw "Trusted dotnet executable not found: '$DotnetExe'."
    }
    $brokerDll = Join-Path $InstallRoot 'bin\PrivExecBroker.dll'
    Assert-NoReparsePoint -FullPath $brokerDll -Label 'Staged PrivExecBroker.dll'
    $evidence['broker_dll_sha256'] = (Get-FileHash -Algorithm SHA256 -LiteralPath $brokerDll).Hash.ToLowerInvariant()

    $tempGrant = Join-Path $InstallRoot "state\gate3-grant-$runId.json"
    @{
        allowed_client_sids           = @($agentSid)
        allowed_capabilities          = @('h4.preflight')
        allowed_targets               = @($VmId)
        allow_mutation                = $false
        allowed_mutation_capabilities = @()
        ttl_seconds                   = 300
    } | ConvertTo-Json | Set-Content -LiteralPath $tempGrant -Encoding utf8NoBOM

    # Clear potentially dangerous .NET startup hook / deps env vars before launching elevated broker
    foreach ($dotnetEnvVar in @('DOTNET_STARTUP_HOOKS', 'DOTNET_ADDITIONAL_DEPS', 'DOTNET_SHARED_STORE', 'COREHOST_TRACE')) {
        Remove-Item "Env:$dotnetEnvVar" -ErrorAction SilentlyContinue
    }

    Write-Host "Starting PrivExecBroker via '$DotnetExe'. Enter DESKTOP-1ITSJV0 guest credentials when prompted..."
    $brokerProc = Start-Process -FilePath $DotnetExe -WorkingDirectory (Join-Path $InstallRoot 'bin') -ArgumentList @(
        $brokerDll,
        '--pipe', $pipeName,
        '--descriptors-dir', (Join-Path $InstallRoot 'descriptors'),
        '--state-dir', (Join-Path $InstallRoot 'state'),
        '--grant-file', $tempGrant,
        '--ttl-seconds', '300',
        '--prompt-guest-credential'
    ) -NoNewWindow -PassThru
    $evidence['broker_pid'] = $brokerProc.Id
    $evidence['broker_startup_stage'] = 'awaiting_guest_credential_and_pipe'
    Save-Gate3Evidence

    $pipeDeadline = (Get-Date).AddSeconds($BrokerReadyTimeoutSeconds)
    $pipeReady = $false
    while ((Get-Date) -lt $pipeDeadline) {
        if ($brokerProc.HasExited) {
            $evidence['broker_exit_code'] = $brokerProc.ExitCode
            $evidence['broker_startup_stage'] = 'exited_before_pipe_ready'
            throw "PrivExecBroker exited early (exit_code=$($brokerProc.ExitCode))."
        }
        if (Test-Path "\\.\pipe\$pipeName") {
            $pipeReady = $true
            $evidence['pipe_ready'] = $true
            $evidence['broker_startup_stage'] = 'pipe_ready'
            Save-Gate3Evidence
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $pipeReady) {
        $evidence['timeout_category'] = 'broker_pipe_ready_timeout'
        $evidence['broker_startup_stage'] = 'pipe_wait_timed_out'
        throw "Timed out waiting ${BrokerReadyTimeoutSeconds}s for PrivExecBroker named pipe '$pipeName'."
    }

    # 5. Execute single read-only h4.preflight under XERES\PrivExecAgent
    $evidence['current_step'] = 'gate3_preflight'
    New-Item -ItemType Directory -Path $isolatedRunRoot -Force | Out-Null
    $evidence['temp_dir_created'] = $true
    $agProfile = Join-Path $isolatedRunRoot 'agent_profile'
    $agTemp = Join-Path $isolatedRunRoot 'agent_temp'
    $agEnv = New-IsolatedAgentEnv -TempDir $agTemp -ProfileDir $agProfile -Account "$env:COMPUTERNAME\$AgentUsername"

    $agentScript = Join-Path $agProfile 'Invoke-Gate3AgentClient.ps1'
    @'
param([string]$PipeName, [string]$VmId, [string]$VmName, [string]$ExpectedGuestHost, [string]$InstallRoot, [string]$ExpectedAgentSid)
$ErrorActionPreference = 'Stop'
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if ($ExpectedAgentSid -and $id.User.Value -ne $ExpectedAgentSid) {
    throw "Agent SID mismatch: expected '$ExpectedAgentSid', got '$($id.User.Value)'."
}
function Send-Pipe([hashtable]$Payload) {
    $json = $Payload | ConvertTo-Json -Depth 8 -Compress
    $b = [Text.Encoding]::UTF8.GetBytes($json)
    $l = [BitConverter]::GetBytes([uint32]$b.Length)
    $c = [IO.Pipes.NamedPipeClientStream]::new('.', $PipeName, [IO.Pipes.PipeDirection]::InOut, [IO.Pipes.PipeOptions]::None, [Security.Principal.TokenImpersonationLevel]::Impersonation)
    try {
        $c.Connect(5000)
        $c.Write($l, 0, 4); $c.Write($b, 0, $b.Length); $c.Flush()
        $rl = New-Object byte[] 4; $r = 0
        while ($r -lt 4) { $n = $c.Read($rl, $r, 4 - $r); if ($n -eq 0) { throw 'EOF' }; $r += $n }
        $nBytes = [BitConverter]::ToUInt32($rl, 0)
        $rb = New-Object byte[] $nBytes; $off = 0
        while ($off -lt $nBytes) { $n = $c.Read($rb, $off, $nBytes - $off); if ($n -eq 0) { throw 'EOF' }; $off += $n }
        return ([Text.Encoding]::UTF8.GetString($rb) | ConvertFrom-Json)
    } finally { $c.Dispose() }
}
$st = Send-Pipe @{ protocol_version = 1; action = 'status' }
$reqId = 'gate3-pf-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$runResp = Send-Pipe @{
    protocol_version = 1; action = 'run'; request_id = $reqId
    capability = 'h4.preflight'; target = @{ type = 'hyperv_vm'; id = $VmId }; mode = 'dry_run'
    parameters = @{ vm_name = $VmName; expected_guest_host = $ExpectedGuestHost }
}
if (-not $runResp.ok -or $runResp.state -ne 'succeeded') {
    throw "h4.preflight failed (state=$($runResp.state), category=$($runResp.diagnostic_category)): $($runResp.error)"
}
$resResp = Send-Pipe @{ protocol_version = 1; action = 'result'; operation_id = $runResp.operation_id }
if (-not $resResp.ok -or $resResp.state -ne 'succeeded' -or $resResp.result.stage_results.Preflight -ne 'PASS' -or $resResp.result.apply_requested -ne $false -or $resResp.result.guest_authorized -ne $false) {
    throw "h4.preflight result verification failed: $($resResp | ConvertTo-Json -Compress)"
}
foreach ($pt in @(
    (Join-Path $InstallRoot 'bin\PrivExecBroker.dll'),
    (Join-Path $InstallRoot 'descriptors\h4.preflight.json'),
    (Join-Path $InstallRoot 'adapters\Invoke-H4PreflightAdapter.ps1'),
    (Join-Path $InstallRoot 'state\privexec.db')
)) {
    $blocked = $false
    try { [IO.File]::OpenWrite($pt).Dispose() } catch { $blocked = $true }
    if (-not $blocked) { throw "SECURITY FAILURE: Agent could open '$pt' for write." }
}
[pscustomobject]@{ account = $id.Name; sid = $id.User.Value; status = $st; run = $runResp; result = $resResp; write_denials_checked = 4 } | ConvertTo-Json -Depth 10
'@ | Set-Content -LiteralPath $agentScript -Encoding utf8NoBOM

    $agOut = Join-Path $agProfile 'agent-out.json'
    $agErr = Join-Path $agProfile 'agent-err.txt'
    $pAg = Start-Process -FilePath 'C:\Program Files\PowerShell\7\pwsh.exe' `
        -Credential $AgentCredential -WorkingDirectory $agProfile -Environment $agEnv `
        -ArgumentList @('-NoProfile', '-NonInteractive', '-File', $agentScript, '-PipeName', $pipeName, '-VmId', $VmId, '-VmName', $VmName, '-ExpectedGuestHost', $ExpectedGuestHost, '-InstallRoot', $InstallRoot, '-ExpectedAgentSid', $agentSid) `
        -RedirectStandardOutput $agOut -RedirectStandardError $agErr -Wait -PassThru -WindowStyle Hidden
    if ($pAg.ExitCode -ne 0) {
        $errTxt = Get-Content -LiteralPath $agErr -Raw -ErrorAction SilentlyContinue
        throw "Gate 3 agent client failed ($($pAg.ExitCode)): $errTxt"
    }
    $evidence['gate3_preflight'] = (Get-Content -LiteralPath $agOut -Raw | ConvertFrom-Json)

    # 6. Postflight VM & checkpoint check + shutdown
    $evidence['current_step'] = 'postflight_verify'
    Stop-BrokerOverPipe -Pipe $pipeName -Proc $brokerProc
    $brokerProc = $null
    $evidence['pipe_closed_verified'] = -not (Test-Path "\\.\pipe\$pipeName")

    $vmAfter = Get-VM -Id ([guid]$VmId) -ErrorAction Stop
    $cpAfter = @(Get-VMSnapshot -VM $vmAfter -ErrorAction Stop | Where-Object { $_.Id -eq [guid]$CheckpointId })
    if ($cpAfter.Count -ne 1) { throw "Postflight checkpoint '$CheckpointId' missing." }
    $evidence['vm_after'] = @{ name = $vmAfter.Name; id = [string]$vmAfter.Id; state = [string]$vmAfter.State }
    $evidence['checkpoint_after'] = @{ name = $cpAfter[0].Name; id = [string]$cpAfter[0].Id; creation_time = $cpAfter[0].CreationTime.ToUniversalTime().ToString('o') }
    if ($evidence['vm_after'].id -ne $evidence['vm_before'].id -or $evidence['vm_after'].state -ne $evidence['vm_before'].state -or $evidence['checkpoint_after'].id -ne $evidence['checkpoint_before'].id) {
        throw 'VM or checkpoint state changed unexpectedly during Gate 3 preflight.'
    }

    $evidence['status'] = 'passed'
    $evidence['current_step'] = 'completed'
    $evidence['completed_at_utc'] = (Get-Date).ToUniversalTime().ToString('o')
}
catch {
    $evidence['status'] = 'failed'
    $evidence['failing_step'] = $evidence['current_step']
    $evidence['error'] = $_.Exception.Message
    $evidence['completed_at_utc'] = (Get-Date).ToUniversalTime().ToString('o')
    Save-Gate3Evidence
    throw
}
finally {
    if ($brokerProc) {
        if (-not $brokerProc.HasExited) {
            Stop-BrokerOverPipe -Pipe $pipeName -Proc $brokerProc
            $evidence['broker_killed_on_cleanup'] = $true
        }
        if ($brokerProc.HasExited -and $null -eq $evidence['broker_exit_code']) {
            $evidence['broker_exit_code'] = $brokerProc.ExitCode
        }
    }
    if ($tempGrant -and (Test-Path -LiteralPath $tempGrant)) {
        Remove-Item -LiteralPath $tempGrant -Force -ErrorAction SilentlyContinue
        $evidence['cleanup']['grant_removed'] = $true
    }
    if (Test-Path -LiteralPath $isolatedRunRoot) {
        Remove-Item -LiteralPath $isolatedRunRoot -Recurse -Force -ErrorAction SilentlyContinue
        $evidence['cleanup']['temp_dir_removed'] = $true
    }
    $g3Parent = Split-Path -Parent $isolatedRunRoot
    if ($g3Parent -and (Test-Path -LiteralPath $g3Parent) -and @(Get-ChildItem -LiteralPath $g3Parent -Force -ErrorAction SilentlyContinue).Count -eq 0) {
        Remove-Item -LiteralPath $g3Parent -Force -ErrorAction SilentlyContinue
    }
    Save-Gate3Evidence
}

Write-Output ($evidence | ConvertTo-Json -Depth 10)
