Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ListValue {
    param(
        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$Container,

        [Parameter(Mandatory)]
        [string]$Name
    )

    if (-not $Container.Contains($Name) -or $null -eq $Container[$Name]) {
        return @()
    }

    return @($Container[$Name])
}

function Expand-BridgeToken {
    param(
        [Parameter(Mandatory)]
        [string]$Text,

        [Parameter(Mandatory)]
        [hashtable]$Tokens
    )

    $Result = $Text
    foreach ($Token in $Tokens.GetEnumerator()) {
        $Result = $Result.Replace([string]$Token.Key, [string]$Token.Value)
    }

    return $Result
}

function Resolve-BridgePath {
    param(
        [Parameter(Mandatory)]
        [string]$Value,

        [Parameter(Mandatory)]
        [string]$BasePath,

        [Parameter(Mandatory)]
        [hashtable]$Tokens
    )

    $Expanded = Expand-BridgeToken -Text $Value -Tokens $Tokens
    if ([string]::IsNullOrWhiteSpace($Expanded)) {
        throw 'Ledger paths cannot be empty.'
    }

    if ([System.IO.Path]::IsPathRooted($Expanded)) {
        return [System.IO.Path]::GetFullPath($Expanded)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Expanded))
}

function Add-EvidencePath {
    param(
        [Parameter(Mandatory)]
        [System.Collections.Generic.List[string]]$Arguments,

        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$Ledger,

        [Parameter(Mandatory)]
        [string]$Field,

        [Parameter(Mandatory)]
        [string]$Flag,

        [Parameter(Mandatory)]
        [string]$BasePath,

        [Parameter(Mandatory)]
        [hashtable]$Tokens,

        [Parameter(Mandatory)]
        [bool]$Required
    )

    foreach ($Configured in (Get-ListValue -Container $Ledger -Name $Field)) {
        $Path = Resolve-BridgePath -Value ([string]$Configured) -BasePath $BasePath -Tokens $Tokens
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            if ($Required) {
                throw "Required ledger evidence is missing for '$Field': $Path"
            }

            Write-Warning "Optional ledger evidence is missing for '$Field': $Path"
            continue
        }

        $Arguments.Add($Flag)
        $Arguments.Add($Path)
    }
}

function Invoke-TargetDevelopmentLedger {
    <#
    .SYNOPSIS
    Records one manifest target through development_ledger.dispatcher_record.
    #>
    [CmdletBinding()]
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

    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json -AsHashtable
    if (-not $Manifest.Contains('targets') -or -not $Manifest.targets.Contains($TargetName)) {
        throw "Validation target '$TargetName' was not found in $ManifestPath"
    }

    $Target = $Manifest.targets[$TargetName]
    if (-not $Target.Contains('ledger')) {
        throw "Validation target '$TargetName' does not define a ledger object."
    }

    $Ledger = $Target.ledger
    if ($Ledger.Contains('enabled') -and -not [bool]$Ledger.enabled) {
        Write-Output "Development ledger is disabled for target '$TargetName'."
        return
    }

    foreach ($Name in @('active_plan', 'output_directory')) {
        if (-not $Ledger.Contains($Name) -or [string]::IsNullOrWhiteSpace([string]$Ledger[$Name])) {
            throw "Ledger configuration for '$TargetName' is missing '$Name'."
        }
    }

    $Tokens = @{
        '{repo_root}' = $RepoRoot
        '{target_root}' = $TargetRoot
        '{temp_root}' = $TempRoot
        '{report_path}' = $ReportPath
        '{target_name}' = $TargetName
    }
    $Required = $Ledger.Contains('required') -and [bool]$Ledger.required
    $Plan = Resolve-BridgePath -Value ([string]$Ledger.active_plan) -BasePath $TargetRoot -Tokens $Tokens
    $Output = Resolve-BridgePath -Value ([string]$Ledger.output_directory) -BasePath $TargetRoot -Tokens $Tokens
    if (-not (Test-Path -LiteralPath $Plan -PathType Leaf)) {
        throw "Active ledger plan does not exist: $Plan"
    }

    $CommandArguments = [System.Collections.Generic.List[string]]::new()
    @('-m', 'development_ledger.dispatcher_record', '-p', $Plan, '-o', $Output, '-r', $RepoRoot) |
        ForEach-Object { $CommandArguments.Add($_) }
    Add-EvidencePath $CommandArguments $Ledger 'junit_outputs' '-j' $TargetRoot $Tokens $Required
    Add-EvidencePath $CommandArguments $Ledger 'script_result_outputs' '-s' $TargetRoot $Tokens $Required

    $Transcripts = @(Get-ListValue $Ledger 'transcript_outputs')
    if ($Transcripts.Count -eq 0) {
        $Transcripts = @('{report_path}')
    }
    Add-EvidencePath $CommandArguments @{ transcript_outputs = $Transcripts } 'transcript_outputs' '-t' $TargetRoot $Tokens $true

    foreach ($Pair in @(@('actor', '-a'), @('mode', '-m'))) {
        if ($Ledger.Contains($Pair[0]) -and -not [string]::IsNullOrWhiteSpace([string]$Ledger[$Pair[0]])) {
            $CommandArguments.Add($Pair[1])
            $CommandArguments.Add([string]$Ledger[$Pair[0]])
        }
    }
    if ($Write) {
        $CommandArguments.Add('-w')
    }

    Write-Output "Development ledger: $(if ($Write) { 'WRITE' } else { 'PREVIEW' })"
    Write-Output "Plan: $Plan"
    Write-Output "Output: $Output"
    & $PythonExecutable @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Development-ledger recording failed with exit code $LASTEXITCODE."
    }

    if ($Write) {
        foreach ($Name in @('RUNS.jsonl', 'LATEST.json', 'PROGRESS.md', 'TRACEABILITY.md', 'MANUAL_CHECKS.md')) {
            $Path = Join-Path $Output $Name
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
                throw "Development-ledger projection is missing: $Path"
            }
        }
        Write-Output "Progress: $(Join-Path $Output 'PROGRESS.md')"
        Write-Output "Manual checks: $(Join-Path $Output 'MANUAL_CHECKS.md')"
    }
}

Export-ModuleMember -Function Invoke-TargetDevelopmentLedger
