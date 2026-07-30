Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ValidationArtifactStamp {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    foreach ($Line in @(Get-Content -LiteralPath $Path -TotalCount 50 -ErrorAction SilentlyContinue)) {
        if ($Line -match '^(?:Timestamp|Generated):\s*(.+)$') {
            $ParsedTimestamp = [DateTimeOffset]::MinValue
            if ([DateTimeOffset]::TryParse($Matches[1], [ref]$ParsedTimestamp)) {
                return $ParsedTimestamp.ToString('yyyyMMdd-HHmmss')
            }
        }
    }
    return (Get-Item -LiteralPath $Path).LastWriteTime.ToString('yyyyMMdd-HHmmss')
}

function Get-UniqueValidationArchivePath {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [string]$HistoryRoot,

        [Parameter(Mandatory)]
        [string]$ArchiveStamp,

        [Parameter(Mandatory)]
        [string]$Suffix
    )

    $ArchivePath = Join-Path $HistoryRoot ("{0}_{1}" -f $ArchiveStamp, $Suffix)
    $Counter = 1
    while (Test-Path -LiteralPath $ArchivePath) {
        $ArchivePath = Join-Path $HistoryRoot ("{0}-{1}_{2}" -f $ArchiveStamp, $Counter, $Suffix)
        $Counter++
    }
    return $ArchivePath
}

function Limit-ValidationHistoryFiles {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$HistoryRoot,

        [Parameter(Mandatory)]
        [string]$Filter,

        [Parameter(Mandatory)]
        [int]$MaxCount,

        [Parameter(Mandatory)]
        [int]$MaxAgeDays
    )

    $Cutoff = (Get-Date).AddDays(-$MaxAgeDays)
    Get-ChildItem -LiteralPath $HistoryRoot -File -Filter $Filter -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $Cutoff } |
        Remove-Item -Force
    $RemainingFiles = @(
        Get-ChildItem -LiteralPath $HistoryRoot -File -Filter $Filter -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime, Name -Descending
    )
    if ($RemainingFiles.Count -gt $MaxCount) {
        $RemainingFiles | Select-Object -Skip $MaxCount | Remove-Item -Force
    }
}

function Initialize-ValidationReportStore {
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [Parameter(Mandatory)]
        [string]$TargetResultsRoot,

        [Parameter(Mandatory)]
        [string]$SafeTargetName,

        [Parameter(Mandatory)]
        [int]$MaxHistoryCount,

        [Parameter(Mandatory)]
        [int]$MaxHistoryDays
    )

    $HistoryRoot = Join-Path $TargetResultsRoot 'history'
    $LatestReportPath = Join-Path $TargetResultsRoot 'LATEST.txt'
    New-Item -ItemType Directory -Path $HistoryRoot -Force | Out-Null
    $LegacyReports = @(
        Get-ChildItem -LiteralPath $TargetResultsRoot -File -Filter "*_$SafeTargetName.txt" -ErrorAction SilentlyContinue |
            Where-Object Name -ne 'LATEST.txt'
    )
    foreach ($LegacyReport in $LegacyReports) {
        Move-Item -LiteralPath $LegacyReport.FullName -Destination (Join-Path $HistoryRoot $LegacyReport.Name) -Force
    }

    $PreviousArchiveStamp = $null
    if (Test-Path -LiteralPath $LatestReportPath -PathType Leaf) {
        $PreviousArchiveStamp = Get-ValidationArtifactStamp -Path $LatestReportPath
        $ArchivePath = Get-UniqueValidationArchivePath `
            -HistoryRoot $HistoryRoot `
            -ArchiveStamp $PreviousArchiveStamp `
            -Suffix ("{0}.txt" -f $SafeTargetName)
        Move-Item -LiteralPath $LatestReportPath -Destination $ArchivePath
    }
    Limit-ValidationHistoryFiles `
        -HistoryRoot $HistoryRoot `
        -Filter ("*_{0}.txt" -f $SafeTargetName) `
        -MaxCount $MaxHistoryCount `
        -MaxAgeDays $MaxHistoryDays
    return @{
        ReportPath = $LatestReportPath
        HistoryRoot = $HistoryRoot
        PreviousArchiveStamp = $PreviousArchiveStamp
    }
}

function Initialize-ValidationContextStore {
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [Parameter(Mandatory)]
        [string]$TargetResultsRoot,

        [Parameter(Mandatory)]
        [string]$SafeTargetName,

        [Parameter()]
        [AllowNull()]
        [string]$PreferredArchiveStamp,

        [Parameter(Mandatory)]
        [int]$MaxHistoryCount,

        [Parameter(Mandatory)]
        [int]$MaxHistoryDays
    )

    $HistoryRoot = Join-Path $TargetResultsRoot 'history'
    $ContextPath = Join-Path $TargetResultsRoot 'LATEST_CONTEXT.md'
    $ProgressPath = Join-Path $TargetResultsRoot 'LATEST_PROGRESS.diff'
    New-Item -ItemType Directory -Path $HistoryRoot -Force | Out-Null
    $ArchiveStamp = $PreferredArchiveStamp
    $PreviousContextPath = $null

    if (Test-Path -LiteralPath $ContextPath -PathType Leaf) {
        if ([string]::IsNullOrWhiteSpace($ArchiveStamp)) {
            $ArchiveStamp = Get-ValidationArtifactStamp -Path $ContextPath
        }
        $PreviousContextPath = Get-UniqueValidationArchivePath `
            -HistoryRoot $HistoryRoot `
            -ArchiveStamp $ArchiveStamp `
            -Suffix ("{0}_context.md" -f $SafeTargetName)
        Move-Item -LiteralPath $ContextPath -Destination $PreviousContextPath
    }
    if (Test-Path -LiteralPath $ProgressPath -PathType Leaf) {
        if ([string]::IsNullOrWhiteSpace($ArchiveStamp)) {
            $ArchiveStamp = Get-ValidationArtifactStamp -Path $ProgressPath
        }
        $ProgressArchivePath = Get-UniqueValidationArchivePath `
            -HistoryRoot $HistoryRoot `
            -ArchiveStamp $ArchiveStamp `
            -Suffix ("{0}_progress.diff" -f $SafeTargetName)
        Move-Item -LiteralPath $ProgressPath -Destination $ProgressArchivePath
    }
    Limit-ValidationHistoryFiles -HistoryRoot $HistoryRoot -Filter ("*_{0}_context.md" -f $SafeTargetName) -MaxCount $MaxHistoryCount -MaxAgeDays $MaxHistoryDays
    Limit-ValidationHistoryFiles -HistoryRoot $HistoryRoot -Filter ("*_{0}_progress.diff" -f $SafeTargetName) -MaxCount $MaxHistoryCount -MaxAgeDays $MaxHistoryDays
    return @{
        ContextPath = $ContextPath
        ProgressPath = $ProgressPath
        PreviousContextPath = $PreviousContextPath
    }
}

function Write-ValidationReportLine {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ReportPath,

        [Parameter()]
        [AllowEmptyString()]
        [string]$Text = ''
    )

    Write-Output $Text
    Add-Content -LiteralPath $ReportPath -Value $Text -Encoding utf8
}

function Write-ValidationReportSection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ReportPath,

        [Parameter(Mandatory)]
        [string]$Title
    )

    Write-ValidationReportLine -ReportPath $ReportPath
    Write-ValidationReportLine -ReportPath $ReportPath -Text ('=' * 100)
    Write-ValidationReportLine -ReportPath $ReportPath -Text $Title
    Write-ValidationReportLine -ReportPath $ReportPath -Text ('=' * 100)
}

Export-ModuleMember -Function @(
    'Initialize-ValidationReportStore',
    'Initialize-ValidationContextStore',
    'Write-ValidationReportLine',
    'Write-ValidationReportSection'
)
