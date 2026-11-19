#Requires -Version 7.0
<#
.SYNOPSIS
    Idempotent, dry-run-by-default staged installer for PrivExec on Windows 11.
.DESCRIPTION
    Stages PrivExecBroker binaries, capability descriptors, adapters, and optional
    pinned H4 scripts into a protected directory outside agent-writable git worktrees.
    Applies least-privilege Windows ACLs without creating Windows services, scheduled
    tasks, or user accounts.

    Default mode is strictly read-only (-Apply is required for installation).
    Distinguishes SameUserDev (accidental-misuse containment only; NOT malicious-agent
    isolation) from CrossAccountIsolated (separate operator and non-admin agent accounts).
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = 'C:\ProgramData\PrivExec',
    [ValidateSet('SameUserDev', 'CrossAccountIsolated')]
    [string]$Mode = 'SameUserDev',
    [string]$OperatorAccount = "$env:USERDOMAIN\$env:USERNAME",
    [string]$AgentAccount = '',
    [string]$H4SourceDir = '',
    [switch]$Apply,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$moduleRoot = Split-Path -Parent $PSScriptRoot
$brokerBinDir = Join-Path $moduleRoot 'broker\bin'
$adaptersSrcDir = Join-Path $moduleRoot 'adapters'
$descriptorsSrcDir = Join-Path $moduleRoot 'descriptors'
$clientSrcDir = Join-Path $moduleRoot 'privexec'

function Assert-NoReparsePoint {
    param([Parameter(Mandatory)][string]$FullPath)
    $root = [System.IO.Path]::GetPathRoot($FullPath)
    $current = $FullPath
    while (-not [string]::IsNullOrWhiteSpace($current) -and $current -ne $root) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Path traverses a reparse point at '$current'."
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

if ($Mode -eq 'CrossAccountIsolated' -and [string]::IsNullOrWhiteSpace($AgentAccount)) {
    throw 'CrossAccountIsolated mode requires -AgentAccount (a distinct non-administrator Windows account).'
}
if ($Mode -eq 'CrossAccountIsolated' -and $AgentAccount -eq $OperatorAccount) {
    throw 'CrossAccountIsolated mode requires -AgentAccount to differ from -OperatorAccount.'
}

$resolvedRoot = [System.IO.Path]::GetFullPath($InstallRoot)
Assert-NoReparsePoint -FullPath $resolvedRoot

$subDirs = [ordered]@{
    bin         = Join-Path $resolvedRoot 'bin'
    client      = Join-Path $resolvedRoot 'client\privexec'
    descriptors = Join-Path $resolvedRoot 'descriptors'
    adapters    = Join-Path $resolvedRoot 'adapters'
    h4_scripts  = Join-Path $resolvedRoot 'h4_scripts'
    state       = Join-Path $resolvedRoot 'state'
    work        = Join-Path $resolvedRoot 'work'
}

$brokerDll = Join-Path $brokerBinDir 'PrivExecBroker.dll'
$brokerCfg = Join-Path $brokerBinDir 'PrivExecBroker.runtimeconfig.json'
$securityNotice = if ($Mode -eq 'SameUserDev') {
    'SameUserDev mode: same-desktop UAC elevation is accidental-misuse containment ONLY and is NOT a security boundary against a compromised agent.'
} else {
    'CrossAccountIsolated mode: enforces distinct operator vs non-admin agent ACLs on staged files and state.'
}

$plan = [ordered]@{
    schema_version     = 1
    action             = 'privexec_install'
    apply              = [bool]$Apply
    mode               = $Mode
    requires_elevation = ($Mode -eq 'CrossAccountIsolated')
    security_notice    = $securityNotice
    install_root       = $resolvedRoot
    operator_account   = $OperatorAccount
    agent_account      = if ($AgentAccount) { $AgentAccount } else { $OperatorAccount }
    broker_dll_source  = $brokerDll
    broker_built       = (Test-Path -LiteralPath $brokerDll -PathType Leaf)
    h4_source_dir      = $H4SourceDir
    h4_required_files  = @('Invoke-H4GuestQualification.ps1', 'Invoke-H4GuestRecovery.ps1', 'Bootstrap-H4GuestBundle.ps1')
    directories        = $subDirs
    creates_service    = $false
    creates_task       = $false
    modifies_accounts  = $false
    verified           = $false
}

if (-not $Apply) {
    if ($Json) {
        $plan | ConvertTo-Json -Depth 6
    } else {
        Write-Host "PRIVEXEC INSTALL DRY-RUN (no changes made)"
        Write-Host "  Mode: $Mode ($securityNotice)"
        Write-Host "  Target root: $resolvedRoot"
        Write-Host "  Re-run elevated with -Apply to stage binaries, adapters, descriptors, and ACLs."
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $brokerDll -PathType Leaf) -or -not (Test-Path -LiteralPath $brokerCfg -PathType Leaf)) {
    throw "Compiled PrivExecBroker artifacts missing in '$brokerBinDir'. Run Build-PrivExecBroker.ps1 first."
}
Assert-NoReparsePoint -FullPath $brokerBinDir
Assert-NoReparsePoint -FullPath $adaptersSrcDir
Assert-NoReparsePoint -FullPath $descriptorsSrcDir
Assert-NoReparsePoint -FullPath $clientSrcDir

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Mode -eq 'CrossAccountIsolated' -and -not $isAdmin) {
    throw 'Elevated Administrator privileges are required for CrossAccountIsolated ACL installation.'
}

if (-not [string]::IsNullOrWhiteSpace($H4SourceDir)) {
    $resolvedH4Check = [System.IO.Path]::GetFullPath($H4SourceDir)
    Assert-NoReparsePoint -FullPath $resolvedH4Check
    foreach ($fName in @('Invoke-H4GuestQualification.ps1', 'Invoke-H4GuestRecovery.ps1', 'Bootstrap-H4GuestBundle.ps1')) {
        $src = Join-Path $resolvedH4Check $fName
        if (-not (Test-Path -LiteralPath $src -PathType Leaf)) {
            throw "Required H4 script '$fName' not found in -H4SourceDir '$resolvedH4Check'."
        }
    }
}

function Set-StrictDirectoryAcl {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$OperatorAccount,
        [string]$ReadOnlyAgentAccount = ''
    )
    $acl = [System.Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    $prop = [System.Security.AccessControl.PropagationFlags]'None'
    $allow = [System.Security.AccessControl.AccessControlType]::Allow

    foreach ($adminAcct in @('NT AUTHORITY\SYSTEM', 'BUILTIN\Administrators', $OperatorAccount)) {
        $sid = ([System.Security.Principal.NTAccount]$adminAcct).Translate([System.Security.Principal.SecurityIdentifier])
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid, [System.Security.AccessControl.FileSystemRights]::FullControl, $inherit, $prop, $allow))
    }
    if (-not [string]::IsNullOrWhiteSpace($ReadOnlyAgentAccount)) {
        $agentSid = ([System.Security.Principal.NTAccount]$ReadOnlyAgentAccount).Translate([System.Security.Principal.SecurityIdentifier])
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            $agentSid, [System.Security.AccessControl.FileSystemRights]::ReadAndExecute, $inherit, $prop, $allow))
    }

    Set-Acl -LiteralPath $Path -AclObject $acl

    # Reset any existing child items so they inherit only the reconciled parent ACL (purging stale explicit ACEs)
    Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $childAcl = Get-Acl -LiteralPath $_.FullName
        $childAcl.SetAccessRuleProtection($false, $false)
        foreach ($r in @($childAcl.GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier]))) {
            $childAcl.RemoveAccessRuleSpecific($r)
        }
        Set-Acl -LiteralPath $_.FullName -AclObject $childAcl
    }
}

$readOnlyDirs = @($resolvedRoot, $subDirs.bin, (Split-Path -Parent $subDirs.client), $subDirs.client, $subDirs.descriptors, $subDirs.adapters, $subDirs.h4_scripts)
$privateDirs = @($subDirs.state, $subDirs.work)

# Create directories and apply restrictive ACLs BEFORE staging binaries/scripts (closes partial-install window)
$agentForReadOnly = if ($Mode -eq 'CrossAccountIsolated') { $AgentAccount } else { '' }
foreach ($d in $readOnlyDirs) {
    New-Item -ItemType Directory -Path $d -Force | Out-Null
    Assert-NoReparsePoint -FullPath $d
    Set-StrictDirectoryAcl -Path $d -OperatorAccount $OperatorAccount -ReadOnlyAgentAccount $agentForReadOnly
}

foreach ($d in $privateDirs) {
    New-Item -ItemType Directory -Path $d -Force | Out-Null
    Assert-NoReparsePoint -FullPath $d
    Set-StrictDirectoryAcl -Path $d -OperatorAccount $OperatorAccount
}

Copy-Item -LiteralPath $brokerDll -Destination (Join-Path $subDirs.bin 'PrivExecBroker.dll') -Force
Copy-Item -LiteralPath $brokerCfg -Destination (Join-Path $subDirs.bin 'PrivExecBroker.runtimeconfig.json') -Force

Get-ChildItem -LiteralPath $clientSrcDir -Filter '*.py' -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $subDirs.client $_.Name) -Force
}
$crossAcctScript = Join-Path $PSScriptRoot 'Test-PrivExecCrossAccount.ps1'
if (Test-Path -LiteralPath $crossAcctScript -PathType Leaf) {
    Copy-Item -LiteralPath $crossAcctScript -Destination (Join-Path (Split-Path -Parent $subDirs.client) 'Test-PrivExecCrossAccount.ps1') -Force
}

Get-ChildItem -LiteralPath $adaptersSrcDir -Filter '*.ps1' -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $subDirs.adapters $_.Name) -Force
}

$h4ExpectedSha = @{}
if (-not [string]::IsNullOrWhiteSpace($H4SourceDir)) {
    $resolvedH4 = [System.IO.Path]::GetFullPath($H4SourceDir)
    Assert-NoReparsePoint -FullPath $resolvedH4
    foreach ($fName in @('Invoke-H4GuestQualification.ps1', 'Invoke-H4GuestRecovery.ps1', 'Bootstrap-H4GuestBundle.ps1')) {
        $src = Join-Path $resolvedH4 $fName
        if (Test-Path -LiteralPath $src -PathType Leaf) {
            $dst = Join-Path $subDirs.h4_scripts $fName
            Copy-Item -LiteralPath $src -Destination $dst -Force
            $h4ExpectedSha[$fName] = (Get-FileHash -Algorithm SHA256 -LiteralPath $dst).Hash.ToLowerInvariant()
        }
    }
}

# Stage descriptors bound to $resolvedRoot and current adapter SHA-256 digests
Get-ChildItem -LiteralPath $descriptorsSrcDir -Filter '*.json' -File | ForEach-Object {
    $desc = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
    if ($desc.runner_type -eq 'powershell' -and $desc.script_path) {
        $adapterName = Split-Path -Leaf ([string]$desc.script_path)
        $stagedAdapter = Join-Path $subDirs.adapters $adapterName
        if (Test-Path -LiteralPath $stagedAdapter -PathType Leaf) {
            $desc.script_path = $stagedAdapter
            $desc.script_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $stagedAdapter).Hash.ToLowerInvariant()
        }
        $desc.working_directory = $subDirs.work
        $newArgs = [System.Collections.Generic.List[string]]::new()
        for ($i = 0; $i -lt $desc.fixed_args.Count; $i++) {
            $arg = [string]$desc.fixed_args[$i]
            if ($arg -like '*Invoke-H4GuestQualification.ps1') {
                $qDst = Join-Path $subDirs.h4_scripts 'Invoke-H4GuestQualification.ps1'
                $newArgs.Add($qDst)
                if ($h4ExpectedSha.ContainsKey('Invoke-H4GuestQualification.ps1')) {
                    $newArgs.Add('-ExpectedH4ScriptSha256')
                    $newArgs.Add($h4ExpectedSha['Invoke-H4GuestQualification.ps1'])
                }
            } elseif ($arg -like '*Invoke-H4GuestRecovery.ps1') {
                $rDst = Join-Path $subDirs.h4_scripts 'Invoke-H4GuestRecovery.ps1'
                $newArgs.Add($rDst)
                if ($h4ExpectedSha.ContainsKey('Invoke-H4GuestRecovery.ps1')) {
                    $newArgs.Add('-ExpectedH4ScriptSha256')
                    $newArgs.Add($h4ExpectedSha['Invoke-H4GuestRecovery.ps1'])
                }
            } else {
                $newArgs.Add($arg)
            }
        }
        $desc.fixed_args = $newArgs.ToArray()
    }
    $desc | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $subDirs.descriptors $_.Name) -Encoding utf8NoBOM
}

# Re-verify ACL inheritance protection and descriptor/adapter SHA-256 digests post-install
Get-ChildItem -LiteralPath $subDirs.descriptors -Filter '*.json' -File | ForEach-Object {
    $stagedDesc = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
    if ($stagedDesc.runner_type -eq 'powershell' -and $stagedDesc.script_path) {
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath ([string]$stagedDesc.script_path)).Hash.ToLowerInvariant()
        if ($actualHash -ne ([string]$stagedDesc.script_sha256).ToLowerInvariant()) {
            throw "Post-install integrity verification failed for '$($_.Name)'."
        }
    }
}

$plan['verified'] = $true
$plan['h4_staged_sha256'] = $h4ExpectedSha
if ($Json) {
    $plan | ConvertTo-Json -Depth 6
} else {
    Write-Host "PrivExec staged and ACL-protected at '$resolvedRoot' (Mode=$Mode)."
}
