#Requires -Version 7.0
<#
.SYNOPSIS
    Operator-run elevated PrivExec session broker launcher for normal coding-agent workflows.
.DESCRIPTION
    Starts a time-limited, capability-scoped PrivExecBroker session from the protected
    installation directory using C:\Program Files\dotnet\dotnet.exe (zero Python in the
    elevated launch chain). Verifies that protected directories do not grant write
    access to non-administrator principals before starting.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\ProgramData\PrivExec',
    [string]$PipeName = 'privexec-broker-v1',
    [string]$GrantFile = '',
    [string[]]$AllowedClientAccounts = @(),
    [string[]]$AllowedCapabilities = @(),
    [string[]]$AllowedTargets = @(),
    [int]$TtlSeconds = 1800,
    [switch]$AllowSameUser,
    [switch]$AllowMutation,
    [string[]]$AllowedMutationCapabilities = @(),
    [string[]]$AllowedH4Stages = @(),
    [switch]$PromptGuestCredential,
    [string]$DotnetExe = 'C:\Program Files\dotnet\dotnet.exe',
    [switch]$DryRun,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

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

function Test-ProtectedInstallAcls {
    param([Parameter(Mandatory)][string]$RootPath)
    $allowedWriteSids = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $allowedWriteSids.Add('S-1-5-18')      # NT AUTHORITY\SYSTEM
    $allowedWriteSids.Add('S-1-5-32-544')  # BUILTIN\Administrators

    $writeMask = (
        [System.Security.AccessControl.FileSystemRights]::Write -bor
        [System.Security.AccessControl.FileSystemRights]::Modify -bor
        [System.Security.AccessControl.FileSystemRights]::FullControl -bor
        [System.Security.AccessControl.FileSystemRights]::Delete -bor
        [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [System.Security.AccessControl.FileSystemRights]::TakeOwnership
    )

    $violations = [System.Collections.Generic.List[string]]::new()
    foreach ($sub in @('', 'bin', 'client', 'descriptors', 'adapters', 'h4_scripts', 'state', 'work')) {
        $dirPath = if ([string]::IsNullOrEmpty($sub)) { $RootPath } else { Join-Path $RootPath $sub }
        if (-not (Test-Path -LiteralPath $dirPath -PathType Container)) { continue }
        $acl = Get-Acl -LiteralPath $dirPath
        foreach ($rule in $acl.Access) {
            if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) { continue }
            $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            if ($allowedWriteSids.Contains($sid)) { continue }
            if (($rule.FileSystemRights -band $writeMask) -ne 0) {
                $violations.Add("$dirPath grants '$($rule.IdentityReference)' ($sid) write rights '$($rule.FileSystemRights)'")
            }
        }
    }
    return $violations
}

$resolvedRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$brokerDll = Join-Path $resolvedRoot 'bin\PrivExecBroker.dll'
$descriptorsDir = Join-Path $resolvedRoot 'descriptors'
$stateDir = Join-Path $resolvedRoot 'state'

$resolvedClientSids = [System.Collections.Generic.List[string]]::new()
foreach ($acct in $AllowedClientAccounts) {
    if ([string]::IsNullOrWhiteSpace($acct)) { continue }
    $sid = ([System.Security.Principal.NTAccount]$acct).Translate([System.Security.Principal.SecurityIdentifier]).Value
    $resolvedClientSids.Add($sid)
}
if ($AllowSameUser) {
    $opSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if (-not $resolvedClientSids.Contains($opSid)) {
        $resolvedClientSids.Add($opSid)
    }
}

$plan = [ordered]@{
    schema_version         = 1
    action                 = 'privexec_session_start'
    dry_run                = [bool]$DryRun
    install_root           = $resolvedRoot
    broker_dll             = $brokerDll
    dotnet_exe             = $DotnetExe
    pipe_name              = $PipeName
    ttl_seconds            = [Math]::Clamp($TtlSeconds, 1, 86400)
    grant_file             = if ($GrantFile) { [System.IO.Path]::GetFullPath($GrantFile) } else { $null }
    allowed_client_sids    = $resolvedClientSids.ToArray()
    allowed_capabilities   = @($AllowedCapabilities)
    allowed_targets        = @($AllowedTargets)
    allow_mutation         = [bool]$AllowMutation
    prompt_guest_credential = [bool]$PromptGuestCredential
}

if ($DryRun) {
    if ($Json) {
        $plan | ConvertTo-Json -Depth 6
    } else {
        Write-Host "PRIVEXEC SESSION START DRY-RUN"
        $plan | ConvertTo-Json -Depth 6
    }
    exit 0
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    throw 'Start-PrivExecSession.ps1 requires an elevated Administrator PowerShell 7 session.'
}

Assert-NoReparsePoint -FullPath $resolvedRoot -Label 'InstallRoot'
Assert-NoReparsePoint -FullPath $DotnetExe -Label 'DotnetExe'
if (-not (Test-Path -LiteralPath $DotnetExe -PathType Leaf)) {
    throw "Trusted dotnet.exe not found at '$DotnetExe'."
}
if (-not (Test-Path -LiteralPath $brokerDll -PathType Leaf)) {
    throw "Installed PrivExecBroker.dll not found at '$brokerDll'. Run Install-PrivExec.ps1 -Apply first."
}

$aclViolations = Test-ProtectedInstallAcls -RootPath $resolvedRoot
if ($aclViolations.Count -gt 0) {
    $joined = $aclViolations -join '; '
    throw "SECURITY FAILURE: Protected installation has non-admin write ACLs: $joined. Re-run Install-PrivExec.ps1 -Apply -Mode CrossAccountIsolated."
}

$tempGrantPath = $null
$effectiveGrantFile = $GrantFile
try {
    if ([string]::IsNullOrWhiteSpace($effectiveGrantFile)) {
        if ($resolvedClientSids.Count -eq 0 -or $AllowedCapabilities.Count -eq 0 -or $AllowedTargets.Count -eq 0) {
            throw 'Provide -GrantFile or specify -AllowedClientAccounts (or -AllowSameUser), -AllowedCapabilities, and -AllowedTargets.'
        }
        $sessionTag = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
        $tempGrantPath = Join-Path $stateDir "session-grant-$sessionTag.json"
        $grantObj = [ordered]@{
            allowed_client_sids           = $resolvedClientSids.ToArray()
            allowed_capabilities          = @($AllowedCapabilities)
            allowed_targets               = @($AllowedTargets)
            allow_mutation                = [bool]$AllowMutation
            allowed_mutation_capabilities = @($AllowedMutationCapabilities)
            allowed_h4_stages             = @($AllowedH4Stages)
            ttl_seconds                   = [Math]::Clamp($TtlSeconds, 1, 86400)
        }
        $grantObj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $tempGrantPath -Encoding utf8NoBOM
        $effectiveGrantFile = $tempGrantPath
    } else {
        $effectiveGrantFile = [System.IO.Path]::GetFullPath($effectiveGrantFile)
        Assert-NoReparsePoint -FullPath $effectiveGrantFile -Label 'GrantFile'
        if (-not (Test-Path -LiteralPath $effectiveGrantFile -PathType Leaf)) {
            throw "Grant file not found: '$effectiveGrantFile'."
        }
    }

    $brokerArgs = [System.Collections.Generic.List[string]]@(
        $brokerDll,
        '--pipe', $PipeName,
        '--descriptors-dir', $descriptorsDir,
        '--state-dir', $stateDir,
        '--grant-file', $effectiveGrantFile,
        '--ttl-seconds', ([string][Math]::Clamp($TtlSeconds, 1, 86400))
    )
    if ($PromptGuestCredential) {
        $brokerArgs.Add('--prompt-guest-credential')
    }

    Write-Host "Starting PrivExecBroker on pipe '\\.\pipe\$PipeName' (TTL=${TtlSeconds}s). Press Ctrl+C or run 'privexec broker stop' to revoke."
    $proc = Start-Process -FilePath $DotnetExe -ArgumentList $brokerArgs.ToArray() -NoNewWindow -PassThru -Wait
    exit $proc.ExitCode
} finally {
    if ($tempGrantPath -and (Test-Path -LiteralPath $tempGrantPath)) {
        Remove-Item -LiteralPath $tempGrantPath -Force -ErrorAction SilentlyContinue
    }
}
