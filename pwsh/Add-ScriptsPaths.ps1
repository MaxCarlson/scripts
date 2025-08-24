# pwsh/Add-ScriptsPaths.ps1 (hardened)
<#
Ensures scripts\pyscripts (and optionally scripts\bin) are on the *User* PATH on Windows,
without ever overwriting existing entries. Creates timestamped backups and verifies writes.
#>

[CmdletBinding()]
param(
  [string]$ScriptsDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path,
  [switch]$IncludeBin
)

# --- Constants & helpers ---
$TargetScope = [System.EnvironmentVariableTarget]::User
$MaxChars    = 32767   # practical Windows env limit for a single variable

function Get-UserPath {
  [System.Environment]::GetEnvironmentVariable('Path', $TargetScope)
}

function Save-UserPathBackup {
  param([string]$current)
  $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
  $bkKey = "Path_Backup_$stamp"
  # Save alongside Path in HKCU:\Environment so recovery is easy
  New-Item -Path HKCU:\Environment -Force | Out-Null
  New-ItemProperty -Path HKCU:\Environment -Name $bkKey -Value $current -PropertyType ExpandString -Force | Out-Null
  # Also write a .reg file in case registry editing is easier
  $regFile = Join-Path $env:USERPROFILE "PATH-backup-$stamp.reg"
  @"
Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\Environment]
"Path"="$($current -replace '\\','\\' -replace '"','\"')"
"@ | Set-Content -LiteralPath $regFile -Encoding ASCII
  Write-Verbose "Backed up PATH to HKCU:\Environment\$bkKey and $regFile"
}

function Normalize-PathList {
  param([string[]]$items)
  # trim, drop blanks, de-dup case-insensitively, keep order
  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  $out = New-Object System.Collections.Generic.List[string]
  foreach ($i in $items) {
    $p = ($i -replace '^\s+|\s+$','')
    if (-not [string]::IsNullOrWhiteSpace($p)) {
      if ($seen.Add($p)) { [void]$out.Add($p) }
    }
  }
  $out
}

function Safe-AppendToUserPath {
  param([Parameter(Mandatory)][string[]]$AbsolutePathsToAdd)

  $current = Get-UserPath
  if ([string]::IsNullOrEmpty($current)) {
    throw "Current User PATH is null/empty. Refusing to proceed to avoid overwriting."
  }

  Save-UserPathBackup -current $current

  $currentParts = $current -split ';'
  $nextParts    = $currentParts + $AbsolutePathsToAdd
  $finalParts   = Normalize-PathList $nextParts
  $finalStr     = ($finalParts -join ';')

  if ($finalStr.Length -gt $MaxChars) {
    throw "Refusing to write: resulting User PATH would be $($finalStr.Length) chars (limit ~$MaxChars)."
  }

  # Write and verify
  [System.Environment]::SetEnvironmentVariable('Path', $finalStr, $TargetScope)
  $roundTrip = Get-UserPath
  if ($roundTrip -ne $finalStr) {
    throw "Verification failed: read-back PATH did not match what was written."
  }

  # Also update current session so it's immediately available
  $env:Path = ($env:Path + ';' + ($AbsolutePathsToAdd -join ';'))

  Write-Host "User PATH updated safely. Open a new terminal for other apps to see it." -ForegroundColor Green
}

# --- Build targets from repo layout ---
$targets = New-Object System.Collections.Generic.List[string]

$py = Join-Path $ScriptsDir 'pyscripts'
if (Test-Path $py -PathType Container) { $targets.Add((Resolve-Path $py).Path) } else { Write-Warning "Missing directory: $py" }

if ($IncludeBin) {
  $bin = Join-Path $ScriptsDir 'bin'
  if (Test-Path $bin -PathType Container) { $targets.Add((Resolve-Path $bin).Path) } else { Write-Warning "Missing directory: $bin" }
}

if ($targets.Count -eq 0) {
  Write-Error "No valid directories to add. Exiting."
  exit 1
}

# --- Apply (no external helpers—ever) ---
Safe-AppendToUserPath -AbsolutePathsToAdd $targets
Write-Verbose "Added to current session PATH: $($targets -join ';')"
Write-Host "Done." -ForegroundColor Green
