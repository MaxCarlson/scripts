<#
.SYNOPSIS
Validates the repository-wide hybrid workflow and ledger bridge.

.DESCRIPTION
Checks instruction routing, branch-policy documentation, active-plan validity,
manifest-driven ledger preview/write behavior, projection generation, and
required-evidence failure handling. Writes one development-ledger generic
script-result JSON file even when one or more checks fail.

.PARAMETER RepoRoot
Scripts repository root.

.PARAMETER PythonExecutable
Python executable containing the installed development_ledger package.

.PARAMETER ResultPath
Destination for the generic script-result JSON artifact.

.PARAMETER TempRoot
Isolated directory for synthetic manifest, transcript, evidence, and ledger
output.

.EXAMPLE
./validation/tests/repository_workflow_test.ps1 `
    -RepoRoot . `
    -PythonExecutable ./.venv/Scripts/python.exe `
    -ResultPath ./.pytest_tmp_root/repository-workflow.json `
    -TempRoot ./.pytest_tmp_root/repository-workflow
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot,

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [Parameter(Mandatory)]
    [string]$ResultPath,

    [Parameter(Mandatory)]
    [string]$TempRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$ResolvedRepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$ResolvedPython = [System.IO.Path]::GetFullPath($PythonExecutable)
$ResolvedResultPath = [System.IO.Path]::GetFullPath($ResultPath)
$ResolvedTempRoot = [System.IO.Path]::GetFullPath($TempRoot)
$Results = [System.Collections.Generic.List[hashtable]]::new()

function Add-CheckResult {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Id,

        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string[]]$ItemIds,

        [Parameter(Mandatory)]
        [scriptblock]$Action
    )

    $Started = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $Action
        $Started.Stop()
        $Results.Add(@{
            id = $Id
            name = $Name
            status = 'passed'
            duration_seconds = [Math]::Round($Started.Elapsed.TotalSeconds, 6)
            message = ''
            item_ids = @($ItemIds)
        })
    }
    catch {
        $Started.Stop()
        $Results.Add(@{
            id = $Id
            name = $Name
            status = 'failed'
            duration_seconds = [Math]::Round($Started.Elapsed.TotalSeconds, 6)
            message = $_.Exception.Message
            item_ids = @($ItemIds)
        })
    }
}

function Assert-True {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [bool]$Condition,

        [Parameter(Mandatory)]
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Assert-ContainsText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string[]]$Patterns
    )

    Assert-True -Condition (Test-Path -LiteralPath $Path -PathType Leaf) -Message "Required file is missing: $Path"
    $Text = Get-Content -LiteralPath $Path -Raw
    foreach ($Pattern in $Patterns) {
        Assert-True -Condition ($Text.Contains($Pattern)) -Message "Expected '$Pattern' in $Path