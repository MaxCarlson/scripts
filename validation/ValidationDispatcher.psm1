Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module -Name (Join-Path $PSScriptRoot 'ValidationCommon.psm1') -Force
Import-Module -Name (Join-Path $PSScriptRoot 'ValidationTarget.psm1') -Force

function Invoke-RepositoryValidation {
    [CmdletBinding()]
    [OutputType([object[]])]
    param(
        [Parameter(Mandatory)]
        [string]$RepoRoot,

        [Parameter()]
        [string[]]$Target,

        [Parameter()]
        [switch]$ListTargets,

        [Parameter()]
        [switch]$SkipBootstrap,

        [Parameter()]
        [switch]$IncludeProductionReadOnly,

        [Parameter(Mandatory)]
        [int]$MaxHistoryPerTarget,

        [Parameter(Mandatory)]
        [int]$MaxHistoryAgeDays
    )

    $ResolvedRepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
    $ManifestPath = Join-Path $ResolvedRepoRoot 'validation-targets.json'
    $ResultsRoot = Join-Path $ResolvedRepoRoot 'docs\test-results'
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Validation manifest not found: $ManifestPath"
    }
    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json -AsHashtable
    if (-not $Manifest.Contains('targets')) {
        throw "Validation manifest does not define a 'targets' object: $ManifestPath"
    }

    $AvailableTargets = @($Manifest['targets'].Keys | Sort-Object)
    if ($ListTargets) {
        foreach ($Name in $AvailableTargets) {
            $Description = if ($Manifest['targets'][$Name].Contains('description')) {
                [string]$Manifest['targets'][$Name]['description']
            }
            else {
                ''
            }
            Write-Output ("{0,-24} {1}" -f $Name, $Description)
        }
        Write-Output 0
        return
    }

    $SelectedTargets = if ($Target -and $Target.Count -gt 0) {
        @($Target)
    }
    elseif ($Manifest.Contains('default_targets')) {
        @($Manifest['default_targets'])
    }
    else {
        @()
    }
    if ($SelectedTargets -contains 'all') {
        $SelectedTargets = $AvailableTargets
    }
    $SelectedTargets = @($SelectedTargets | Select-Object -Unique)
    if ($SelectedTargets.Count -eq 0) {
        throw 'No validation targets were selected.'
    }
    foreach ($Name in $SelectedTargets) {
        if (-not $Manifest['targets'].Contains($Name)) {
            throw "Unknown validation target '$Name'. Run ./Invoke-Tests.ps1 -ListTargets to list available targets."
        }
    }

    $Python = Resolve-ValidationPythonExecutable -RepoRoot $ResolvedRepoRoot
    New-Item -ItemType Directory -Path $ResultsRoot -Force | Out-Null
    $Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $OverallFailures = [System.Collections.Generic.List[string]]::new()
    $Results = [System.Collections.Generic.List[hashtable]]::new()

    foreach ($TargetName in $SelectedTargets) {
        try {
            $TargetResult = $null
            Invoke-ValidationTarget `
                -RepoRoot $ResolvedRepoRoot `
                -ManifestPath $ManifestPath `
                -ResultsRoot $ResultsRoot `
                -Timestamp $Timestamp `
                -TargetName $TargetName `
                -TargetSpec $Manifest['targets'][$TargetName] `
                -PythonExecutable $Python `
                -SkipBootstrap ([bool]$SkipBootstrap) `
                -IncludeProductionReadOnly ([bool]$IncludeProductionReadOnly) `
                -MaxHistoryPerTarget $MaxHistoryPerTarget `
                -MaxHistoryAgeDays $MaxHistoryAgeDays `
                -OverallFailures $OverallFailures |
                ForEach-Object {
                    if ($_ -is [hashtable] -and $_.Contains('ReportPath')) {
                        $TargetResult = $_
                    }
                    else {
                        Write-Output $_
                    }
                }
            if ($null -eq $TargetResult) {
                throw "Target '$TargetName' did not return a validation result."
            }
            $Results.Add($TargetResult)
        }
        catch {
            $Failure = "$TargetName - dispatcher failure: $($_.Exception.Message)"
            $OverallFailures.Add($Failure)
            [Console]::Error.WriteLine("ERROR: $Failure")
        }
    }

    Write-Output ''
    Write-Output ('=' * 100)
    Write-Output 'REPOSITORY VALIDATION SUMMARY'
    Write-Output ('=' * 100)
    foreach ($Result in $Results) {
        Write-Output "Latest report: $($Result.ReportPath)"
        Write-Output "Context snapshot: $($Result.ContextPath)"
        Write-Output "Progress diff: $($Result.ProgressPath)"
    }
    if ($OverallFailures.Count -eq 0) {
        Write-Output 'OVERALL RESULT: PASS'
        Write-Output 0
        return
    }

    Write-Output 'OVERALL RESULT: FAIL'
    Write-Output "Failure count: $($OverallFailures.Count)"
    foreach ($Failure in $OverallFailures) {
        Write-Output "- $Failure"
    }
    Write-Output 1
}

Export-ModuleMember -Function 'Invoke-RepositoryValidation'
