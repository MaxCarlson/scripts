#Requires -Version 7.0
<#
.SYNOPSIS
    Trusted external bootstrap for H4 Windows acceptance bundles.
.DESCRIPTION
    Verifies the transferred ZIP archive against an independently published
    SHA-256 digest using PowerShell Get-FileHash BEFORE extracting or executing
    any bundled script. Runs read-only preflight only (never --apply).
#>
param(
    [Parameter(Mandatory)][string]$ArchivePath,
    [Parameter(Mandatory)][string]$ExpectedSha256,
    [string]$DestinationRoot = (Join-Path $env:TEMP ("h4-bundle-" + [guid]::NewGuid().ToString("N"))),
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw "ExpectedSha256 must be a 64-character hexadecimal SHA-256 digest."
}
$resolvedArchive = (Resolve-Path -LiteralPath $ArchivePath).Path
$actualHash = (Get-FileHash -LiteralPath $resolvedArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $ExpectedSha256.ToLowerInvariant()) {
    throw "Archive SHA-256 mismatch! Expected $($ExpectedSha256.ToLowerInvariant()), got $actualHash. Aborting before extraction."
}
if ((Test-Path -LiteralPath $DestinationRoot) -and (Get-ChildItem -LiteralPath $DestinationRoot -Force | Measure-Object).Count -gt 0) {
    throw "DestinationRoot must be empty: $DestinationRoot"
}
New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
Expand-Archive -LiteralPath $resolvedArchive -DestinationPath $DestinationRoot -Force

$verifyScript = Join-Path $DestinationRoot "scripts\Verify-H4GuestBundle.ps1"
if (-not (Test-Path -LiteralPath $verifyScript)) {
    throw "Extracted bundle is missing scripts\Verify-H4GuestBundle.ps1"
}
& pwsh -NoProfile -NonInteractive -File $verifyScript -BundleRoot $DestinationRoot -Python $Python
exit $LASTEXITCODE
