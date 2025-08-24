<#
.SYNOPSIS
Ensures scripts\pyscripts (and optionally scripts\bin) are on the User PATH on Windows.

.DESCRIPTION
- Idempotently appends absolute paths to the User PATH (persistent) and to the current session.
- Uses Set-PathVariable from your w11-powershell modules when available,
  otherwise falls back to a local safe implementation.

.EXAMPLE
pwsh -NoProfile -ExecutionPolicy Bypass -File .\pwsh\Add-ScriptsPaths.ps1 -ScriptsDir C:\path\to\scripts -Verbose
#>

[CmdletBinding()]
param(
    # Root of THIS scripts repo. Defaults to parent of this script folder.
    [string]$ScriptsDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path,

    # Also add scripts\bin (optional - useful once Windows shims/symlinks or .cmd wrappers are finalized)
    [switch]$IncludeBin
)

Write-Verbose "ScriptsDir resolved to: $ScriptsDir"

# --- Fallback if Set-PathVariable isn't available ---
function Add-PathIfMissing {
    param([Parameter(Mandatory)][string]$PathToAdd)

    $scope = 'User'
    $current = [System.Environment]::GetEnvironmentVariable('Path', $scope)

    if (-not $current) {
        Write-Error "Current $scope PATH is null/empty. Aborting to avoid corruption."
        exit 1
    }

    if ($current -match "(^|;)$([regex]::Escape($PathToAdd))(;|$)") {
        Write-Verbose "'$PathToAdd' already present in $scope PATH."
        return
    }

    $new = "$current;$PathToAdd"
    [System.Environment]::SetEnvironmentVariable('Path', $new, $scope)
    Write-Host "Added '$PathToAdd' to $scope PATH (persisted). Open a new terminal to pick it up." -ForegroundColor Green
}

# Pick helper: prefer your module's Set-PathVariable if present
$helper = Get-Command Set-PathVariable -ErrorAction SilentlyContinue
if ($null -eq $helper) {
    Write-Verbose "Set-PathVariable not found; using local Add-PathIfMissing."
    $AddPath = { param($p) Add-PathIfMissing -PathToAdd $p }
} else {
    Write-Verbose "Using Set-PathVariable from your PowerShell modules."
    $AddPath = { param($p) Set-PathVariable -PathToAdd $p }  # from your repo  
}

# Build targets
$targets = @()

$py = Join-Path $ScriptsDir 'pyscripts'
if (Test-Path $py -PathType Container) { $targets += (Resolve-Path $py).Path } else { Write-Warning "Missing directory: $py" }

if ($IncludeBin) {
    $bin = Join-Path $ScriptsDir 'bin'
    if (Test-Path $bin -PathType Container) { $targets += (Resolve-Path $bin).Path } else { Write-Warning "Missing directory: $bin" }
}

# Apply
foreach ($t in $targets) {
    & $AddPath.Invoke($t)

    # Also make current session immediately aware
    if ($env:Path -notmatch "(^|;)$([regex]::Escape($t))(;|$)") {
        $env:Path = "$env:Path;$t"
        Write-Verbose "Added '$t' to current session PATH."
    } else {
        Write-Verbose "'$t' already in current session PATH."
    }
}

Write-Host "Done." -ForegroundColor Green
