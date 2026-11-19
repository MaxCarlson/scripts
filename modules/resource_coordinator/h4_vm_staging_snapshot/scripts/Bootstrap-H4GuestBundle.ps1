#Requires -Version 7.0
<#
.SYNOPSIS
    Trusted external bootstrap for H4 Windows acceptance bundles.
.DESCRIPTION
    Implements the H4 trusted guest-bootstrap sequence:
      1. Requires the operator to supply -ExpectedSha256 from separately trusted
         release evidence (NEVER copy or trust an unauthenticated .sha256 file
         transferred alongside an untrusted archive).
      2. Verifies Python 3.12+ availability (production resource-coordinator
         supports >=3.10, while H4 release/acceptance tooling requires >=3.12)
         and validates the archive SHA-256 via Get-FileHash BEFORE creating the
         destination directory or calling Expand-Archive.
      3. Expand-Archive runs only after the external SHA-256 digest matches; this
         external digest check is the trust assumption underlying extraction.
      4. Invokes bundled Verify-H4GuestBundle.ps1 for component manifest checking,
         source tree verification, and read-only preflight (or -IntegrityOnly when
         staging a verified bundle on a guest awaiting failed-install recovery).
#>
param(
    [Parameter(Mandatory)][string]$ArchivePath,
    [Parameter(Mandatory)][string]$ExpectedSha256,
    [string]$DestinationRoot = (Join-Path $env:TEMP ("h4-bundle-" + [guid]::NewGuid().ToString("N"))),
    [string]$Python = "python",
    [switch]$IntegrityOnly
)

$ErrorActionPreference = "Stop"

function Test-AncestorReparsePoint {
    param([Parameter(Mandatory)][string]$FullPath)
    $candidate = $FullPath
    while (-not [string]::IsNullOrEmpty($candidate)) {
        if (Test-Path -LiteralPath $candidate) {
            $item = Get-Item -LiteralPath $candidate -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                return $true
            }
        }
        $parent = Split-Path -Path $candidate -Parent
        if ($parent -eq $candidate) { break }
        $candidate = $parent
    }
    return $false
}

if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw "ExpectedSha256 must be a 64-character hexadecimal SHA-256 digest obtained from separately trusted release evidence."
}
if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    throw "DestinationRoot cannot be empty."
}
if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
    throw "ArchivePath does not exist or is not a file: $ArchivePath"
}
$resolvedArchive = (Resolve-Path -LiteralPath $ArchivePath).Path
if (Test-AncestorReparsePoint -FullPath $resolvedArchive) {
    throw "ArchivePath traverses or references an unsafe reparse point: $resolvedArchive"
}

$resolvedDest = [IO.Path]::GetFullPath($DestinationRoot)
if (Test-Path -LiteralPath $resolvedDest -PathType Leaf) {
    throw "DestinationRoot must be a directory path, not an existing file: $resolvedDest"
}
if (Test-AncestorReparsePoint -FullPath $resolvedDest) {
    throw "DestinationRoot traverses or references an unsafe reparse point: $resolvedDest"
}
if ((Test-Path -LiteralPath $resolvedDest) -and (Get-ChildItem -LiteralPath $resolvedDest -Force | Measure-Object).Count -gt 0) {
    throw "DestinationRoot must be empty: $resolvedDest"
}

try {
    $pyInfo = & $Python -B -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'); raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 2)"
    $pyExit = $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine("Failed to execute Python interpreter '$Python'. H4 guest acceptance tooling requires Python 3.12+ (production resource-coordinator package remains >=3.10).")
    exit 2
}
if ($pyExit -ne 0) {
    [Console]::Error.WriteLine("H4 guest acceptance tooling requires Python 3.12+ (detected '$($pyInfo -join '')' from '$Python'; exit=$pyExit). Production resource-coordinator package remains >=3.10.")
    exit 2
}

$actualHash = (Get-FileHash -LiteralPath $resolvedArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $ExpectedSha256.ToLowerInvariant()) {
    throw "Archive SHA-256 mismatch! Expected $($ExpectedSha256.ToLowerInvariant()), got $actualHash. Aborting before extraction."
}

$createdDest = -not (Test-Path -LiteralPath $resolvedDest)
try {
    New-Item -ItemType Directory -Force -Path $resolvedDest | Out-Null
    # Trust assumption: Expand-Archive is reached only after $actualHash matched -ExpectedSha256 above.
    Expand-Archive -LiteralPath $resolvedArchive -DestinationPath $resolvedDest -Force
    $verifyScript = Join-Path $resolvedDest "scripts\Verify-H4GuestBundle.ps1"
    if (-not (Test-Path -LiteralPath $verifyScript -PathType Leaf)) {
        throw "Extracted bundle is missing scripts\Verify-H4GuestBundle.ps1"
    }
} catch {
    if ($createdDest -and (Test-Path -LiteralPath $resolvedDest)) {
        Remove-Item -LiteralPath $resolvedDest -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}

$verifyArgs = @('-NoProfile', '-NonInteractive', '-File', $verifyScript, '-BundleRoot', $resolvedDest, '-Python', $Python)
if ($IntegrityOnly) {
    $verifyArgs += '-IntegrityOnly'
}
& pwsh @verifyArgs
$verifyExit = $LASTEXITCODE
exit $verifyExit
