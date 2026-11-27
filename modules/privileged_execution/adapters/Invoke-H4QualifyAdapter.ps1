#Requires -Version 7.0
<#
.SYNOPSIS
    PrivExec controlled adapter for Resource Coordinator H4 qualification (`h4.qualify`).
.DESCRIPTION
    Supports explicitly enumerated stages: Preflight, Setup, and Acceptance.
    Intentionally excludes `All` and `Checkpoint` from blanket grants.
    Defaults to read-only Preflight unless -Apply is explicitly supplied.
    Acceptance mutations require both -Apply and -AuthorizeGuestMutation.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$H4QualificationScript,
    [string]$ExpectedH4ScriptSha256 = '',
    [ValidateSet('Preflight', 'Setup', 'Acceptance')]
    [string]$Stage = 'Preflight',
    [switch]$Apply,
    [switch]$AuthorizeGuestMutation,
    [string]$OperationId = '',
    [string]$VmId = 'd8483f98-8884-4758-abd1-cd6107c83c03',
    [string]$VmName = 'RC-H4-Windows-Acceptance',
    [string]$ExpectedGuestHost = 'DESKTOP-1ITSJV0',
    [string]$EvidenceRoot = 'C:\H4-VM-Staging\evidence',
    [ValidatePattern('^[a-zA-Z0-9_-]*$')]
    [string]$RunSuffix = ''
)

$ErrorActionPreference = 'Stop'

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

function Read-BrokerStdinCredential {
    if ([Console]::IsInputRedirected) {
        $line = [Console]::In.ReadLine()
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            $parsed = $line | ConvertFrom-Json -ErrorAction Stop
            $line = $null
            if ($parsed.username -and $parsed.password) {
                $sec = ConvertTo-SecureString -String ([string]$parsed.password) -AsPlainText -Force
                $parsed.password = $null
                return [pscredential]::new([string]$parsed.username, $sec)
            }
        }
    }
    return $null
}

if ($Stage -eq 'Acceptance' -and $Apply -and -not $AuthorizeGuestMutation) {
    throw 'H4 Acceptance mutation requires both -Apply and -AuthorizeGuestMutation.'
}

$resolved = [System.IO.Path]::GetFullPath($H4QualificationScript)
Assert-NoReparsePoint -FullPath $resolved
if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    throw "Staged H4 qualification script not found: '$resolved'."
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedH4ScriptSha256)) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolved -ErrorAction Stop).Hash
    if ($actual.ToLowerInvariant() -ne $ExpectedH4ScriptSha256.ToLowerInvariant()) {
        throw "H4 qualification script SHA-256 mismatch: expected '$ExpectedH4ScriptSha256', got '$actual'."
    }
}

$cred = Read-BrokerStdinCredential
$effectiveStage = if ($Apply) { $Stage } else { 'Preflight' }
$invokeParams = @{
    Stage             = $effectiveStage
    Json              = $true
    VmId              = $VmId
    VmName            = $VmName
    ExpectedGuestHost = $ExpectedGuestHost
    EvidenceRoot      = $EvidenceRoot
}
if ($Apply) {
    $invokeParams['Apply'] = $true
    if ($AuthorizeGuestMutation) {
        $invokeParams['AuthorizeGuestMutation'] = $true
    }
}
if (-not [string]::IsNullOrWhiteSpace($OperationId)) {
    $invokeParams['OperationId'] = $OperationId
}
if (-not [string]::IsNullOrWhiteSpace($RunSuffix)) {
    $invokeParams['RunSuffix'] = $RunSuffix
}
if ($null -ne $cred) {
    $invokeParams['Credential'] = $cred
}

$out = & $resolved @invokeParams
$rc = $LASTEXITCODE
if ($out) {
    $out | ForEach-Object { Write-Output $_ }
}
exit $(if ($null -ne $rc) { $rc } else { 0 })
