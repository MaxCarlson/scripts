<#
.SYNOPSIS
Records one validation target through the repository development ledger.

.DESCRIPTION
Imports DevelopmentLedgerBridge.psm1 and invokes the manifest-driven ledger
recording operation. Writes only when -Write is supplied.

.PARAMETER ManifestPath
Path to validation-targets.json.

.PARAMETER TargetName
Validation target whose ledger configuration should be used.

.PARAMETER RepoRoot
Repository root used for Git provenance.

.PARAMETER TargetRoot
Validation target working directory.

.PARAMETER TempRoot
Current isolated validation directory.

.PARAMETER ReportPath
Current raw validation transcript.

.PARAMETER PythonExecutable
Python executable containing development_ledger.

.PARAMETER Write
Append the event and regenerate projections.

.EXAMPLE
./validation/Invoke-DevelopmentLedger.ps1 -ManifestPath ./validation-targets.json -TargetName repository-workflow -RepoRoot . -TargetRoot . -TempRoot ./tmp -ReportPath ./LATEST.txt -PythonExecutable ./python.exe -Write
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory)] [string]$ManifestPath,
    [Parameter(Mandatory)] [string]$TargetName,
    [Parameter(Mandatory)] [string]$RepoRoot,
    [Parameter(Mandatory)] [string]$TargetRoot,
    [Parameter(Mandatory)] [string]$TempRoot,
    [Parameter(Mandatory)] [string]$ReportPath,
    [Parameter(Mandatory)] [string]$PythonExecutable,
    [Parameter()] [switch]$Write
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$ModulePath = Join-Path $PSScriptRoot 'DevelopmentLedgerBridge.psm1'
if (-not (Test-Path -LiteralPath $ModulePath -PathType Leaf)) {
    throw "Development-ledger bridge module is missing: $ModulePath"
}

foreach ($Path in @($ManifestPath, $RepoRoot, $TargetRoot, $TempRoot, $ReportPath, $PythonExecutable)) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'Required path parameters cannot be empty.'
    }
}

$Resolved = @{
    ManifestPath = [System.IO.Path]::GetFullPath($ManifestPath)
    RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
    TargetRoot = [System.IO.Path]::GetFullPath($TargetRoot)
    TempRoot = [System.IO.Path]::GetFullPath($TempRoot)
    ReportPath = [System.IO.Path]::GetFullPath($ReportPath)
    PythonExecutable = [System.IO.Path]::GetFullPath($PythonExecutable)
}

foreach ($Name in @('ManifestPath', 'ReportPath', 'PythonExecutable')) {
    if (-not (Test-Path -LiteralPath $Resolved[$Name] -PathType Leaf)) {
        throw "$Name does not exist: $($Resolved[$Name])"
    }
}
foreach ($Name in @('RepoRoot', 'TargetRoot', 'TempRoot')) {
    if (-not (Test-Path -LiteralPath $Resolved[$Name] -PathType Container)) {
        throw "$Name does not exist: $($Resolved[$Name])"
    }
}

if ($Write -and -not $PSCmdlet.ShouldProcess($TargetName, 'Record development-ledger validation event')) {
    Write-Output "Development-ledger write cancelled for target '$TargetName'."
    exit 0
}

Import-Module -Name $ModulePath -Force
$Parameters = @{
    ManifestPath = $Resolved.ManifestPath
    TargetName = $TargetName
    RepoRoot = $Resolved.RepoRoot
    TargetRoot = $Resolved.TargetRoot
    TempRoot = $Resolved.TempRoot
    ReportPath = $Resolved.ReportPath
    PythonExecutable = $Resolved.PythonExecutable
    Write = [bool]$Write
}
Invoke-TargetDevelopmentLedger @Parameters
exit 0
