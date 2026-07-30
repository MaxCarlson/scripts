Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module -Name (Join-Path $PSScriptRoot 'ValidationCommon.psm1') -Force
Import-Module -Name (Join-Path $PSScriptRoot 'ValidationArtifacts.psm1') -Force
Import-Module -Name (Join-Path $PSScriptRoot 'ValidationContext.psm1') -Force
Import-Module -Name (Join-Path $PSScriptRoot 'ValidationExecution.psm1') -Force

function Invoke-ValidationTarget {
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [Parameter(Mandatory)] [string]$RepoRoot,
        [Parameter(Mandatory)] [string]$ManifestPath,
        [Parameter(Mandatory)] [string]$ResultsRoot,
        [Parameter(Mandatory)] [string]$Timestamp,
        [Parameter(Mandatory)] [string]$TargetName,
        [Parameter(Mandatory)] [System.Collections.IDictionary]$TargetSpec,
        [Parameter(Mandatory)] [string]$PythonExecutable,
        [Parameter(Mandatory)] [bool]$SkipBootstrap,
        [Parameter(Mandatory)] [bool]$IncludeProductionReadOnly,
        [Parameter(Mandatory)] [int]$MaxHistoryPerTarget,
        [Parameter(Mandatory)] [int]$MaxHistoryAgeDays,
        [Parameter(Mandatory)] [System.Collections.Generic.List[string]]$OverallFailures
    )

    if (-not $TargetSpec.Contains('working_directory')) {
        throw "Validation target '$TargetName' does not define a working_directory."
    }
    $WorkingDirectory = [System.IO.Path]::GetFullPath(
        (Join-Path $RepoRoot ([string]$TargetSpec['working_directory']))
    )
    if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
        throw "Working directory for target '$TargetName' does not exist: $WorkingDirectory"
    }

    $InitialStatus = @(& git -C $RepoRoot status --short 2>$null)
    $SafeTargetName = $TargetName -replace '[^A-Za-z0-9._-]', '_'
    $TargetResultsRoot = Join-Path $ResultsRoot $SafeTargetName
    $ReportStore = Initialize-ValidationReportStore `
        -TargetResultsRoot $TargetResultsRoot `
        -SafeTargetName $SafeTargetName `
        -MaxHistoryCount $MaxHistoryPerTarget `
        -MaxHistoryDays $MaxHistoryAgeDays
    $ContextStore = Initialize-ValidationContextStore `
        -TargetResultsRoot $TargetResultsRoot `
        -SafeTargetName $SafeTargetName `
        -PreferredArchiveStamp $ReportStore.PreviousArchiveStamp `
        -MaxHistoryCount $MaxHistoryPerTarget `
        -MaxHistoryDays $MaxHistoryAgeDays

    $ReportPath = [string]$ReportStore.ReportPath
    $ContextPath = [string]$ContextStore.ContextPath
    $ProgressPath = [string]$ContextStore.ProgressPath
    $TargetFailures = [System.Collections.Generic.List[string]]::new()
    $Tokens = @{
        '{repo_root}' = $RepoRoot
        '{target_root}' = $WorkingDirectory
        '{python}' = $PythonExecutable
        '{target_name}' = $TargetName
        '{include_production_read_only}' = if ($IncludeProductionReadOnly) { '1' } else { '0' }
        '{include_production_read_only_bool}' = if ($IncludeProductionReadOnly) { 'True' } else { 'False' }
    }
    $TempRoot = Resolve-ValidationTempRoot `
        -TargetSpec $TargetSpec `
        -WorkingDirectory $WorkingDirectory `
        -Tokens $Tokens `
        -Timestamp $Timestamp
    $Tokens['{temp_root}'] = $TempRoot

    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $TargetResultsRoot -Force | Out-Null
    Set-Content -LiteralPath $ReportPath -Value '' -Encoding utf8

    $PreviousEnvironment = @{}
    try {
        if ($TargetSpec.Contains('environment')) {
            foreach ($Entry in $TargetSpec['environment'].GetEnumerator()) {
                $VariableName = [string]$Entry.Key
                $PreviousEnvironment[$VariableName] = [Environment]::GetEnvironmentVariable($VariableName, 'Process')
                $ResolvedValue = Convert-ValidationTokenText -Text ([string]$Entry.Value) -Tokens $Tokens
                [Environment]::SetEnvironmentVariable($VariableName, $ResolvedValue, 'Process')
            }
        }

        $Description = if ($TargetSpec.Contains('description')) { [string]$TargetSpec['description'] } else { '' }
        Write-ValidationReportSection -ReportPath $ReportPath -Title ("VALIDATION TARGET: {0}" -f $TargetName)
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Timestamp: $(Get-Date -Format o)"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Description: $Description"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Repository root: $RepoRoot"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Working directory: $WorkingDirectory"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Temporary root: $TempRoot"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Python: $PythonExecutable"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "PowerShell: $($PSVersionTable.PSVersion)"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Platform: $([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Bootstrap enabled: $(-not $SkipBootstrap)"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Production read-only checks: $IncludeProductionReadOnly"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "History retention: $MaxHistoryPerTarget prior runs, maximum age $MaxHistoryAgeDays days"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Git branch: $(& git -C $RepoRoot branch --show-current 2>$null)"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Git commit: $(& git -C $RepoRoot rev-parse HEAD 2>$null)"
        Write-ValidationReportLine -ReportPath $ReportPath -Text 'Git status before validation:'
        if ($InitialStatus.Count -eq 0) {
            Write-ValidationReportLine -ReportPath $ReportPath -Text '(clean)'
        }
        else {
            foreach ($Line in $InitialStatus) {
                Write-ValidationReportLine -ReportPath $ReportPath -Text ([string]$Line)
            }
        }

        if (-not $SkipBootstrap) {
            foreach ($CommandSpec in (Get-ValidationManifestItems -Container $TargetSpec -Name 'bootstrap')) {
                Invoke-ValidationCommand `
                    -TargetName $TargetName `
                    -ReportPath $ReportPath `
                    -WorkingDirectory $WorkingDirectory `
                    -CommandSpec $CommandSpec `
                    -Tokens $Tokens `
                    -TargetFailures $TargetFailures `
                    -OverallFailures $OverallFailures
            }
        }
        foreach ($CommandSpec in (Get-ValidationManifestItems -Container $TargetSpec -Name 'commands')) {
            Invoke-ValidationCommand `
                -TargetName $TargetName `
                -ReportPath $ReportPath `
                -WorkingDirectory $WorkingDirectory `
                -CommandSpec $CommandSpec `
                -Tokens $Tokens `
                -TargetFailures $TargetFailures `
                -OverallFailures $OverallFailures
        }
        Invoke-ValidationPowerShellGroups `
            -TargetName $TargetName `
            -ReportPath $ReportPath `
            -WorkingDirectory $WorkingDirectory `
            -TargetSpec $TargetSpec `
            -Tokens $Tokens `
            -TargetFailures $TargetFailures `
            -OverallFailures $OverallFailures
        Invoke-ValidationLedgerPhase `
            -ManifestPath $ManifestPath `
            -TargetName $TargetName `
            -RepoRoot $RepoRoot `
            -WorkingDirectory $WorkingDirectory `
            -TempRoot $TempRoot `
            -ReportPath $ReportPath `
            -PythonExecutable $PythonExecutable `
            -TargetSpec $TargetSpec `
            -TargetFailures $TargetFailures `
            -OverallFailures $OverallFailures

        Write-ValidationReportSection -ReportPath $ReportPath -Title 'TARGET SUMMARY'
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Latest report: $ReportPath"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Context snapshot: $ContextPath"
        Write-ValidationReportLine -ReportPath $ReportPath -Text "Progress diff: $ProgressPath"
        if ($TargetSpec.Contains('ledger')) {
            Write-ValidationReportLine -ReportPath $ReportPath -Text 'Ledger phase: configured as final target phase'
        }
        if ($TargetFailures.Count -eq 0) {
            Write-ValidationReportLine -ReportPath $ReportPath -Text 'TARGET RESULT: PASS'
            Write-ValidationReportLine -ReportPath $ReportPath -Text 'All requested validation sections passed.'
        }
        else {
            Write-ValidationReportLine -ReportPath $ReportPath -Text 'TARGET RESULT: FAIL'
            Write-ValidationReportLine -ReportPath $ReportPath -Text "Failure count: $($TargetFailures.Count)"
            foreach ($Failure in $TargetFailures) {
                Write-ValidationReportLine -ReportPath $ReportPath -Text "- $Failure"
            }
        }

        Write-ValidationReportLine -ReportPath $ReportPath
        Write-ValidationReportLine -ReportPath $ReportPath -Text 'Git status after validation:'
        $FinalStatus = @(& git -C $RepoRoot status --short 2>$null)
        if ($FinalStatus.Count -eq 0) {
            Write-ValidationReportLine -ReportPath $ReportPath -Text '(clean)'
        }
        else {
            foreach ($Line in $FinalStatus) {
                Write-ValidationReportLine -ReportPath $ReportPath -Text ([string]$Line)
            }
        }

        Write-ValidationTargetContextSnapshot `
            -RepoRoot $RepoRoot `
            -TargetName $TargetName `
            -WorkingDirectory $WorkingDirectory `
            -TargetSpec $TargetSpec `
            -ReportPath $ReportPath `
            -ContextPath $ContextPath
        Write-ValidationContextProgressDiff `
            -PreviousContextPath $ContextStore.PreviousContextPath `
            -CurrentContextPath $ContextPath `
            -ProgressPath $ProgressPath
    }
    finally {
        foreach ($Entry in $PreviousEnvironment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable([string]$Entry.Key, $Entry.Value, 'Process')
        }
    }

    return @{
        ReportPath = $ReportPath
        ContextPath = $ContextPath
        ProgressPath = $ProgressPath
        FailureCount = $TargetFailures.Count
    }
}

Export-ModuleMember -Function 'Invoke-ValidationTarget'
