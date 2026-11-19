#Requires -Version 7.0
<#
.SYNOPSIS
    Operator-run elevated validation harness for PrivExec Gates 1 and 2.
.DESCRIPTION
    Must be run from an elevated Administrator PowerShell 7 session after explicit
    operator authorization. Performs:
      - Gate 1: Install-PrivExec.ps1 -Apply -Mode CrossAccountIsolated + ACL/hash verification
      - Gate 2: Real cross-account isolation tests with a separate standard Windows user
                using isolated per-user temp directories (never exposing operator profile
                directories) and synthetic non-H4 operations only.
    Always preserves structured non-secret evidence at every checkpoint (including failures).
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

$runId = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
$opIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$createdUsers = [System.Collections.Generic.List[object]]::new()
$agentAccountTag = "PE2:agent:$runId"
$unauthAccountTag = "PE2:unauth:$runId"

$evidence = [ordered]@{
    run_id               = $runId
    started_at_utc       = (Get-Date).ToUniversalTime().ToString('o')
    completed_at_utc     = $null
    status               = 'started'
    current_step         = 'init'
    failing_step              = $null
    error                     = $null
    error_details             = $null
    operator_account          = $opIdentity.Name
    operator_sid              = $opIdentity.User.Value
    agent_account             = $null
    agent_sid                 = $null
    created_accounts          = @()
    prior_install_found       = (Test-Path -LiteralPath $InstallRoot)
    gate1_install             = $null
    gate1_install_diagnostics = $null
    acl_state                 = $null
    acl_descriptors           = $null
    broker_stdout             = $null
    broker_stderr             = $null
    gate2_agent               = $null
    gate2_unauthorized        = $null
    gate2_expiry_check        = $null
    cleanup                   = [ordered]@{
        temp_dir_created       = $false
        temp_dir_removed       = $false
        temp_agent_acl_cleaned = $false
        accounts_removed       = @()
        errors                 = @()
    }
    services_or_tasks         = 0
    h4_executed               = $false
}

$fallbackEvidencePath = Join-Path $env:TEMP "privexec-gate12-$runId.json"

function Save-GateEvidence {
    $evidence['created_accounts'] = @($createdUsers)
    $json = $evidence | ConvertTo-Json -Depth 10
    $targetDir = Split-Path -Parent $EvidenceOut
    if ($targetDir -and (Test-Path -LiteralPath $targetDir)) {
        $tmpPath = "$EvidenceOut.tmp"
        Set-Content -LiteralPath $tmpPath -Value $json -Encoding utf8NoBOM
        Move-Item -LiteralPath $tmpPath -Destination $EvidenceOut -Force
    } else {
        Set-Content -LiteralPath $fallbackEvidencePath -Value $json -Encoding utf8NoBOM
    }
}

function New-TransientTestUser {
    param(
        [Parameter(Mandatory)][string]$Username,
        [Parameter(Mandatory)][string]$Description
    )
    if ($Username.Length -gt 20) {
        throw "Cannot validate argument on parameter 'Username'. The character length of the '$Username' argument is $($Username.Length), which exceeds the Windows 20-character limit."
    }
    if ($Description.Length -gt 48) {
        throw "Cannot validate argument on parameter 'Description'. The character length of the '$Description' argument is $($Description.Length), which exceeds the Windows 48-character limit."
    }
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 24
    $rng.GetBytes($bytes)
    $raw = 'Px!' + [Convert]::ToBase64String($bytes) + '9a'
    $sec = ConvertTo-SecureString -String $raw -AsPlainText -Force
    $raw = $null
    New-LocalUser -Name $Username -Password $sec -AccountNeverExpires -Description $Description | Out-Null
    Add-LocalGroupMember -Group 'Users' -Member $Username | Out-Null
    $sid = ([System.Security.Principal.NTAccount]"$env:COMPUTERNAME\$Username").Translate([System.Security.Principal.SecurityIdentifier]).Value
    $createdUsers.Add([pscustomobject]@{ username = $Username; sid = $sid; tag = $Description; description = $Description })
    return [pscredential]::new("$env:COMPUTERNAME\$Username", $sec)
}

function New-IsolatedUserEnvironment {
    param(
        [Parameter(Mandatory)][string]$UserTempDir,
        [Parameter(Mandatory)][string]$UserProfileDir,
        [Parameter(Mandatory)][string]$AccountName
    )
    $icacls = "$env:SystemRoot\System32\icacls.exe"
    foreach ($d in @($UserProfileDir, $UserTempDir)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
        & $icacls $d /inheritance:r /grant:r "NT AUTHORITY\SYSTEM:(OI)(CI)F" "BUILTIN\Administrators:(OI)(CI)F" "${OperatorAccount}:(OI)(CI)F" "${AccountName}:(OI)(CI)F" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to ACL isolated child directory '$d' for '$AccountName'." }
    }
    return @{
        SystemRoot   = $env:SystemRoot
        ComSpec      = $env:ComSpec
        WINDIR       = $env:WINDIR
        PATH         = "$env:SystemRoot\System32;$env:SystemRoot;C:\Program Files\PowerShell\7;C:\Program Files\dotnet"
        TEMP         = $UserTempDir
        TMP          = $UserTempDir
        TMPDIR       = $UserTempDir
        USERPROFILE  = $UserProfileDir
        LOCALAPPDATA = $UserProfileDir
        APPDATA      = $UserProfileDir
        HOME         = $UserProfileDir
        HOMEDRIVE    = [System.IO.Path]::GetPathRoot($UserProfileDir).TrimEnd('\')
        HOMEPATH     = $UserProfileDir.Substring([System.IO.Path]::GetPathRoot($UserProfileDir).Length - 1)
    }
}

function Stop-BrokerCleanlyOverPipe {
    param([Parameter(Mandatory)][string]$PipeName, $Proc)
    try {
        $shutdownJson = @{ protocol_version = 1; action = 'shutdown' } | ConvertTo-Json -Compress
        $sBytes = [System.Text.Encoding]::UTF8.GetBytes($shutdownJson)
        $sLen = [System.BitConverter]::GetBytes([uint32]$sBytes.Length)
        $opPipe = [System.IO.Pipes.NamedPipeClientStream]::new(
            '.', $PipeName, [System.IO.Pipes.PipeDirection]::InOut,
            [System.IO.Pipes.PipeOptions]::None, [System.Security.Principal.TokenImpersonationLevel]::Impersonation)
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
        if ($Proc) { $Proc.WaitForExit(5000) | Out-Null }
    } catch {
        if ($Proc -and -not $Proc.HasExited) {
            $Proc.Kill()
            $Proc.WaitForExit(5000) | Out-Null
        }
    }
}

$brokerProc = $null
$tempGrant = $null
$isolatedRunRoot = "C:\ProgramData\PrivExec-Gate2Run\$runId"

Save-GateEvidence

try {
    $evidence['current_step'] = 'prepare_accounts'
    if ($agentAccountTag.Length -gt 48 -or $unauthAccountTag.Length -gt 48) {
        throw "Generated account description exceeds 48-character limit: agent='$agentAccountTag', unauth='$unauthAccountTag'."
    }
    if ($CreateTempTestAccounts) {
        $agentUser = 'PrivExecAg_' + [guid]::NewGuid().ToString('N').Substring(0, 6)
        $unauthUser = 'PrivExecUn_' + [guid]::NewGuid().ToString('N').Substring(0, 6)
        $AgentCredential = New-TransientTestUser -Username $agentUser -Description $agentAccountTag
        $UnauthorizedCredential = New-TransientTestUser -Username $unauthUser -Description $unauthAccountTag
        $AgentAccount = $AgentCredential.UserName
    } elseif ([string]::IsNullOrWhiteSpace($AgentAccount) -or -not $AgentCredential) {
        throw 'Supply -AgentAccount and -AgentCredential, or pass -CreateTempTestAccounts.'
    }
    $agentSid = ([System.Security.Principal.NTAccount]$AgentAccount).Translate([System.Security.Principal.SecurityIdentifier]).Value
    $evidence['agent_account'] = $AgentAccount
    $evidence['agent_sid'] = $agentSid
    Save-GateEvidence

    # Gate 1: Elevated staged installation
    $evidence['current_step'] = 'gate1_install'
    $installScript = Join-Path $PSScriptRoot 'Install-PrivExec.ps1'
    $installArgs = @(
        '-NoProfile',
        '-NonInteractive',
        '-File', $installScript,
        '-Apply',
        '-Mode', 'CrossAccountIsolated',
        '-InstallRoot', $InstallRoot,
        '-OperatorAccount', $OperatorAccount,
        '-AgentAccount', $AgentAccount,
        '-H4SourceDir', $H4SourceDir,
        '-Json'
    )
    $instOutFile = Join-Path $env:TEMP "privexec-gate1-install-$runId.stdout.log"
    $instErrFile = Join-Path $env:TEMP "privexec-gate1-install-$runId.stderr.log"
    try {
        $pInstall = Start-Process -FilePath 'C:\Program Files\PowerShell\7\pwsh.exe' `
            -ArgumentList $installArgs `
            -RedirectStandardOutput $instOutFile `
            -RedirectStandardError $instErrFile `
            -Wait -PassThru -WindowStyle Hidden
        $instOutText = if (Test-Path -LiteralPath $instOutFile) { Get-Content -LiteralPath $instOutFile -Raw -ErrorAction SilentlyContinue } else { '' }
        $instErrText = if (Test-Path -LiteralPath $instErrFile) { Get-Content -LiteralPath $instErrFile -Raw -ErrorAction SilentlyContinue } else { '' }
    } finally {
        if (Test-Path -LiteralPath $instOutFile) { Remove-Item -LiteralPath $instOutFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $instErrFile) { Remove-Item -LiteralPath $instErrFile -Force -ErrorAction SilentlyContinue }
    }

    $parsedInstall = $null
    if (-not [string]::IsNullOrWhiteSpace($instOutText)) {
        try { $parsedInstall = $instOutText | ConvertFrom-Json -ErrorAction Stop } catch {}
    }
    $parsedInstallErr = $null
    if (-not [string]::IsNullOrWhiteSpace($instErrText)) {
        try { $parsedInstallErr = $instErrText | ConvertFrom-Json -ErrorAction Stop } catch {}
    }

    $evidence['gate1_install_diagnostics'] = [ordered]@{
        executable             = 'C:\Program Files\PowerShell\7\pwsh.exe'
        arguments              = $installArgs
        exit_code              = $pInstall.ExitCode
        stdout                 = $instOutText
        stderr                 = $instErrText
        error_payload          = $parsedInstallErr
        partial_install_status = [ordered]@{
            root_exists       = (Test-Path -LiteralPath $InstallRoot)
            broker_dll_staged = (Test-Path -LiteralPath (Join-Path $InstallRoot 'bin\PrivExecBroker.dll'))
            descriptors_count = @(Get-ChildItem -LiteralPath (Join-Path $InstallRoot 'descriptors') -Filter '*.json' -File -ErrorAction SilentlyContinue).Count
            adapters_count    = @(Get-ChildItem -LiteralPath (Join-Path $InstallRoot 'adapters') -Filter '*.ps1' -File -ErrorAction SilentlyContinue).Count
            state_exists      = (Test-Path -LiteralPath (Join-Path $InstallRoot 'state'))
        }
    }
    if ($parsedInstall) {
        $evidence['gate1_install'] = $parsedInstall
    }
    Save-GateEvidence

    if ($pInstall.ExitCode -ne 0 -or -not $parsedInstall -or ($parsedInstall.PSObject.Properties['ok'] -and -not $parsedInstall.ok)) {
        $stageMsg = if ($parsedInstallErr -and $parsedInstallErr.failed_stage) { "stage='$($parsedInstallErr.failed_stage)' " } else { '' }
        $errDetail = if ($parsedInstallErr -and $parsedInstallErr.error_message) {
            "$($parsedInstallErr.exception_type): $($parsedInstallErr.error_message)"
        } elseif (-not [string]::IsNullOrWhiteSpace($instErrText)) {
            $instErrText.Trim()
        } else {
            "exit_code=$($pInstall.ExitCode)"
        }
        throw "Install-PrivExec.ps1 failed (${stageMsg}exit=$($pInstall.ExitCode)): $errDetail"
    }

    $aclState = (& icacls (Join-Path $InstallRoot 'state')) -join "`n"
    $aclDesc = (& icacls (Join-Path $InstallRoot 'descriptors')) -join "`n"
    $evidence['acl_state'] = $aclState
    $evidence['acl_descriptors'] = $aclDesc
    if ($aclState -match [regex]::Escape($AgentAccount.Split('\')[-1])) {
        throw "SECURITY FAILURE: Agent account appears in state directory ACL!"
    }
    $privServices = @(Get-Service -Name '*PrivExec*' -ErrorAction SilentlyContinue)
    $privTasks = @(Get-ScheduledTask -TaskName '*PrivExec*' -ErrorAction SilentlyContinue)
    if ($privServices.Count -gt 0 -or $privTasks.Count -gt 0) {
        throw 'Unexpected PrivExec Windows service or scheduled task found.'
    }
    Save-GateEvidence

    # Gate 2: Start installed broker from C:\ProgramData\PrivExec with synthetic-only grant
    $evidence['current_step'] = 'gate2_broker_start'
    $pipeName = 'privexec-gate2-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $tempGrant = Join-Path $InstallRoot "state\gate2-grant-$runId.json"
    @{
        allowed_client_sids           = @($agentSid)
        allowed_capabilities          = @('synthetic.echo', 'synthetic.mutate')
        allowed_targets               = @('synth-target-1')
        allow_mutation                = $true
        allowed_mutation_capabilities = @('synthetic.mutate')
        ttl_seconds                   = 300
    } | ConvertTo-Json | Set-Content -LiteralPath $tempGrant -Encoding utf8NoBOM

    $brokerOut = Join-Path $InstallRoot "state\gate2-broker-$runId.stdout.log"
    $brokerErr = Join-Path $InstallRoot "state\gate2-broker-$runId.stderr.log"
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
            $bErr = Get-Content -LiteralPath $brokerErr -Raw -ErrorAction SilentlyContinue
            throw "Installed broker exited early ($($brokerProc.ExitCode)): $bErr"
        }
        if ((Test-Path -LiteralPath $brokerOut) -and ((Get-Content -LiteralPath $brokerOut -Raw) -match 'PRIVEXEC_BROKER_READY')) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 150
    }
    if (-not $ready) { throw 'Timed out waiting for installed broker readiness.' }
    Save-GateEvidence

    # Prepare isolated per-user working/temp directories (never inheriting operator profile TEMP)
    $evidence['current_step'] = 'gate2_agent'
    New-Item -ItemType Directory -Path $isolatedRunRoot -Force | Out-Null
    $evidence['cleanup']['temp_dir_created'] = $true
    $agentProfile = Join-Path $isolatedRunRoot 'agent_profile'
    $agentTemp = Join-Path $isolatedRunRoot 'agent_temp'
    $agentEnv = New-IsolatedUserEnvironment -UserTempDir $agentTemp -UserProfileDir $agentProfile -AccountName $AgentAccount

    $clientScript = Join-Path $InstallRoot 'client\Test-PrivExecCrossAccount.ps1'
    $agentOut = Join-Path $agentProfile 'agent-out.json'
    $agentErr = Join-Path $agentProfile 'agent-err.txt'

    $pAgent = Start-Process -FilePath 'C:\Program Files\PowerShell\7\pwsh.exe' `
        -Credential $AgentCredential `
        -WorkingDirectory $agentProfile `
        -Environment $agentEnv `
        -ArgumentList @('-NoProfile', '-NonInteractive', '-File', $clientScript, '-PipeName', $pipeName, '-InstallRoot', $InstallRoot, '-Role', 'AuthorizedAgent', '-ExpectedTempDir', $agentTemp) `
        -RedirectStandardOutput $agentOut -RedirectStandardError $agentErr -Wait -PassThru -WindowStyle Hidden

    $agentOutText = if (Test-Path -LiteralPath $agentOut) { Get-Content -LiteralPath $agentOut -Raw -ErrorAction SilentlyContinue } else { '' }
    $agentErrText = if (Test-Path -LiteralPath $agentErr) { Get-Content -LiteralPath $agentErr -Raw -ErrorAction SilentlyContinue } else { '' }
    if (-not [string]::IsNullOrWhiteSpace($agentOutText)) {
        try { $evidence['gate2_agent'] = ($agentOutText | ConvertFrom-Json -ErrorAction Stop) } catch {}
    }
    Save-GateEvidence
    if ($pAgent.ExitCode -ne 0) {
        throw "AuthorizedAgent cross-account check failed ($($pAgent.ExitCode)): $agentErrText"
    }

    if ($UnauthorizedCredential) {
        $evidence['current_step'] = 'gate2_unauthorized'
        $unProfile = Join-Path $isolatedRunRoot 'unauth_profile'
        $unTemp = Join-Path $isolatedRunRoot 'unauth_temp'
        $unEnv = New-IsolatedUserEnvironment -UserTempDir $unTemp -UserProfileDir $unProfile -AccountName $UnauthorizedCredential.UserName
        $unOut = Join-Path $unProfile 'unauth-out.json'
        $unErr = Join-Path $unProfile 'unauth-err.txt'

        $pUnauth = Start-Process -FilePath 'C:\Program Files\PowerShell\7\pwsh.exe' `
            -Credential $UnauthorizedCredential `
            -WorkingDirectory $unProfile `
            -Environment $unEnv `
            -ArgumentList @('-NoProfile', '-NonInteractive', '-File', $clientScript, '-PipeName', $pipeName, '-InstallRoot', $InstallRoot, '-Role', 'UnauthorizedAccount', '-ExpectedTempDir', $unTemp) `
            -RedirectStandardOutput $unOut -RedirectStandardError $unErr -Wait -PassThru -WindowStyle Hidden

        $unOutText = if (Test-Path -LiteralPath $unOut) { Get-Content -LiteralPath $unOut -Raw -ErrorAction SilentlyContinue } else { '' }
        $unErrText = if (Test-Path -LiteralPath $unErr) { Get-Content -LiteralPath $unErr -Raw -ErrorAction SilentlyContinue } else { '' }
        if (-not [string]::IsNullOrWhiteSpace($unOutText)) {
            try { $evidence['gate2_unauthorized'] = ($unOutText | ConvertFrom-Json -ErrorAction Stop) } catch {}
        }
        Save-GateEvidence
        if ($pUnauth.ExitCode -ne 0) {
            throw "UnauthorizedAccount cross-account check failed ($($pUnauth.ExitCode)): $unErrText"
        }
    }

    $evidence['current_step'] = 'gate2_broker_stop'
    Stop-BrokerCleanlyOverPipe -PipeName $pipeName -Proc $brokerProc
    $brokerProc = $null

    $evidence['status'] = 'passed'
    $evidence['current_step'] = 'completed'
    $evidence['completed_at_utc'] = (Get-Date).ToUniversalTime().ToString('o')
}
catch {
    $evidence['status'] = 'failed'
    $evidence['failing_step'] = $evidence['current_step']
    $evidence['error'] = $_.Exception.Message
    $evidence['error_details'] = [ordered]@{
        exception_type     = $_.Exception.GetType().FullName
        message            = $_.Exception.Message
        position           = if ($_.InvocationInfo) { $_.InvocationInfo.PositionMessage } else { $null }
        script_stack_trace = $_.ScriptStackTrace
    }
    $evidence['completed_at_utc'] = (Get-Date).ToUniversalTime().ToString('o')
    if ($brokerOut -and (Test-Path -LiteralPath $brokerOut)) {
        $evidence['broker_stdout'] = Get-Content -LiteralPath $brokerOut -Raw -ErrorAction SilentlyContinue
    }
    if ($brokerErr -and (Test-Path -LiteralPath $brokerErr)) {
        $evidence['broker_stderr'] = Get-Content -LiteralPath $brokerErr -Raw -ErrorAction SilentlyContinue
    }
    Save-GateEvidence
    throw
}
finally {
    if ($brokerProc -and -not $brokerProc.HasExited) {
        Stop-BrokerCleanlyOverPipe -PipeName $pipeName -Proc $brokerProc
    }
    if ($brokerOut -and (Test-Path -LiteralPath $brokerOut) -and -not $evidence['broker_stdout']) {
        $evidence['broker_stdout'] = Get-Content -LiteralPath $brokerOut -Raw -ErrorAction SilentlyContinue
    }
    if ($brokerErr -and (Test-Path -LiteralPath $brokerErr) -and -not $evidence['broker_stderr']) {
        $evidence['broker_stderr'] = Get-Content -LiteralPath $brokerErr -Raw -ErrorAction SilentlyContinue
    }
    if ($tempGrant -and (Test-Path -LiteralPath $tempGrant)) {
        Remove-Item -LiteralPath $tempGrant -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $isolatedRunRoot) {
        try {
            Remove-Item -LiteralPath $isolatedRunRoot -Recurse -Force -ErrorAction Stop
            $evidence['cleanup']['temp_dir_removed'] = $true
        } catch {
            $evidence['cleanup']['errors'] += "Failed to remove '$isolatedRunRoot': $($_.Exception.Message)"
        }
    } else {
        $evidence['cleanup']['temp_dir_removed'] = $true
    }
    $isolatedParent = Split-Path -Parent $isolatedRunRoot
    if ($isolatedParent -and (Test-Path -LiteralPath $isolatedParent)) {
        $remainingRuns = @(Get-ChildItem -LiteralPath $isolatedParent -Force -ErrorAction SilentlyContinue)
        if ($remainingRuns.Count -eq 0) {
            Remove-Item -LiteralPath $isolatedParent -Force -ErrorAction SilentlyContinue
        }
    }
    if ($CreateTempTestAccounts -and $agentSid -and (Test-Path -LiteralPath $InstallRoot)) {
        try {
            $cleanAcl = [System.Security.AccessControl.DirectorySecurity]::new()
            $cleanAcl.SetAccessRuleProtection($true, $false)
            $inh = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
            $prp = [System.Security.AccessControl.PropagationFlags]'None'
            $alw = [System.Security.AccessControl.AccessControlType]::Allow
            foreach ($adm in @('NT AUTHORITY\SYSTEM', 'BUILTIN\Administrators', $OperatorAccount)) {
                $admSid = ([System.Security.Principal.NTAccount]$adm).Translate([System.Security.Principal.SecurityIdentifier])
                $cleanAcl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
                    $admSid, [System.Security.AccessControl.FileSystemRights]::FullControl, $inh, $prp, $alw))
            }
            $roTargets = @(
                $InstallRoot,
                (Join-Path $InstallRoot 'bin'),
                (Join-Path $InstallRoot 'client'),
                (Join-Path $InstallRoot 'client\privexec'),
                (Join-Path $InstallRoot 'descriptors'),
                (Join-Path $InstallRoot 'adapters'),
                (Join-Path $InstallRoot 'h4_scripts')
            )
            foreach ($roDir in $roTargets) {
                if (Test-Path -LiteralPath $roDir) {
                    [System.IO.FileSystemAclExtensions]::SetAccessControl([System.IO.DirectoryInfo]::new($roDir), $cleanAcl)
                }
            }
            $evidence['cleanup']['temp_agent_acl_cleaned'] = $true
        } catch {
            $evidence['cleanup']['errors'] += "Failed to purge temporary agent SID '$agentSid' from ACLs: $($_.Exception.Message)"
        }
    }
    foreach ($u in $createdUsers) {
        try {
            $acct = Get-LocalUser -Name $u.username -ErrorAction SilentlyContinue
            if ($acct) {
                if ($acct.Description -eq $u.description -or $acct.Description -eq $u.tag -or $acct.Description -like "PE2:*:$runId") {
                    Remove-LocalUser -Name $u.username -ErrorAction Stop
                    $evidence['cleanup']['accounts_removed'] += $u.username
                } else {
                    $evidence['cleanup']['errors'] += "Refusing to remove '$($u.username)': description '$($acct.Description)' does not match run ownership tag for run '$runId'."
                }
            }
        } catch {
            $evidence['cleanup']['errors'] += "Failed to remove '$($u.username)': $($_.Exception.Message)"
        }
    }
    if ($CreateTempTestAccounts) {
        try {
            $orphans = Get-LocalUser -ErrorAction SilentlyContinue | Where-Object { $_.Description -like "PE2:*:$runId" }
            foreach ($orphan in $orphans) {
                if ($evidence['cleanup']['accounts_removed'] -notcontains $orphan.Name) {
                    try {
                        Remove-LocalUser -Name $orphan.Name -ErrorAction Stop
                        $evidence['cleanup']['accounts_removed'] += $orphan.Name
                    } catch {
                        $evidence['cleanup']['errors'] += "Failed to remove orphaned account '$($orphan.Name)': $($_.Exception.Message)"
                    }
                }
            }
        } catch {
            $evidence['cleanup']['errors'] += "Failed during orphan account cleanup check: $($_.Exception.Message)"
        }
    }
    Save-GateEvidence
}

Write-Output ($evidence | ConvertTo-Json -Depth 10)
