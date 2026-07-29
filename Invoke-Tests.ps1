[CmdletBinding()]
param(
    [Parameter()]
    [Alias('Module')]
    [string[]]$Target,

    [Parameter()]
    [switch]$ListTargets,

    [Parameter()]
    [switch]$SkipBootstrap,

    [Parameter()]
    [switch]$IncludeProductionReadOnly,

    [Parameter()]
    [ValidateRange(1, 100)]
    [int]$MaxHistoryPerTarget = 3,

    [Parameter()]
    [ValidateRange(1, 3650)]
    [int]$MaxHistoryAgeDays = 14
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$RepoRoot = $PSScriptRoot
$ManifestPath = Join-Path $RepoRoot 'validation-targets.json'
$ResultsRoot = Join-Path $RepoRoot 'docs\test-results'
$Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OverallFailures = [System.Collections.Generic.List[string]]::new()
$ReportPaths = [System.Collections.Generic.List[string]]::new()
$ContextPaths = [System.Collections.Generic.List[string]]::new()
$ProgressPaths = [System.Collections.Generic.List[string]]::new()

function Resolve-PythonExecutable {
    [CmdletBinding()]
    [OutputType([string])]
    param()

    $Candidates = @(
        (Join-Path $RepoRoot '.venv\Scripts\python.exe'),
        (Join-Path $RepoRoot '.venv\bin\python'),
        'python'
    )

    foreach ($Candidate in $Candidates) {
        if ([System.IO.Path]::IsPathRooted($Candidate)) {
            if (Test-Path -LiteralPath $Candidate) {
                return $Candidate
            }

            continue
        }

        $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
        if ($Command) {
            return $Command.Source
        }
    }

    throw 'Unable to resolve a Python executable. Create the repository virtual environment or install Python.'
}

function Convert-TokenText {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
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

function Get-ManifestItems {
    [CmdletBinding()]
    [OutputType([object[]])]
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

function Get-ArtifactArchiveStamp {
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

function Get-UniqueArchivePath {
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

function Limit-HistoryFiles {
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
        $RemainingFiles |
            Select-Object -Skip $MaxCount |
            Remove-Item -Force
    }
}

function Initialize-TargetReportStore {
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
    $PreviousArchiveStamp = $null

    New-Item -ItemType Directory -Path $TargetResultsRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $HistoryRoot -Force | Out-Null

    $LegacyReports = @(
        Get-ChildItem -LiteralPath $TargetResultsRoot -File -Filter "*_$SafeTargetName.txt" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ne 'LATEST.txt' }
    )
    foreach ($LegacyReport in $LegacyReports) {
        Move-Item -LiteralPath $LegacyReport.FullName -Destination (Join-Path $HistoryRoot $LegacyReport.Name) -Force
    }

    if (Test-Path -LiteralPath $LatestReportPath -PathType Leaf) {
        $PreviousArchiveStamp = Get-ArtifactArchiveStamp -Path $LatestReportPath
        $ArchivePath = Get-UniqueArchivePath `
            -HistoryRoot $HistoryRoot `
            -ArchiveStamp $PreviousArchiveStamp `
            -Suffix ("{0}.txt" -f $SafeTargetName)
        Move-Item -LiteralPath $LatestReportPath -Destination $ArchivePath
    }

    Limit-HistoryFiles `
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

function Initialize-TargetContextStore {
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
    $LatestContextPath = Join-Path $TargetResultsRoot 'LATEST_CONTEXT.md'
    $LatestProgressPath = Join-Path $TargetResultsRoot 'LATEST_PROGRESS.diff'
    $PreviousContextPath = $null
    $ArchiveStamp = $PreferredArchiveStamp

    New-Item -ItemType Directory -Path $TargetResultsRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $HistoryRoot -Force | Out-Null

    if (Test-Path -LiteralPath $LatestContextPath -PathType Leaf) {
        if ([string]::IsNullOrWhiteSpace($ArchiveStamp)) {
            $ArchiveStamp = Get-ArtifactArchiveStamp -Path $LatestContextPath
        }

        $PreviousContextPath = Get-UniqueArchivePath `
            -HistoryRoot $HistoryRoot `
            -ArchiveStamp $ArchiveStamp `
            -Suffix ("{0}_context.md" -f $SafeTargetName)
        Move-Item -LiteralPath $LatestContextPath -Destination $PreviousContextPath
    }

    if (Test-Path -LiteralPath $LatestProgressPath -PathType Leaf) {
        if ([string]::IsNullOrWhiteSpace($ArchiveStamp)) {
            $ArchiveStamp = Get-ArtifactArchiveStamp -Path $LatestProgressPath
        }

        $ProgressArchivePath = Get-UniqueArchivePath `
            -HistoryRoot $HistoryRoot `
            -ArchiveStamp $ArchiveStamp `
            -Suffix ("{0}_progress.diff" -f $SafeTargetName)
        Move-Item -LiteralPath $LatestProgressPath -Destination $ProgressArchivePath
    }

    Limit-HistoryFiles `
        -HistoryRoot $HistoryRoot `
        -Filter ("*_{0}_context.md" -f $SafeTargetName) `
        -MaxCount $MaxHistoryCount `
        -MaxAgeDays $MaxHistoryDays
    Limit-HistoryFiles `
        -HistoryRoot $HistoryRoot `
        -Filter ("*_{0}_progress.diff" -f $SafeTargetName) `
        -MaxCount $MaxHistoryCount `
        -MaxAgeDays $MaxHistoryDays

    return @{
        ContextPath = $LatestContextPath
        ProgressPath = $LatestProgressPath
        PreviousContextPath = $PreviousContextPath
    }
}

function Write-ReportLine {
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

function Write-ReportSection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$ReportPath,

        [Parameter(Mandatory)]
        [string]$Title
    )

    Write-ReportLine -ReportPath $ReportPath
    Write-ReportLine -ReportPath $ReportPath -Text ('=' * 100)
    Write-ReportLine -ReportPath $ReportPath -Text $Title
    Write-ReportLine -ReportPath $ReportPath -Text ('=' * 100)
}

function Invoke-ManifestCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$TargetName,

        [Parameter(Mandatory)]
        [string]$ReportPath,

        [Parameter(Mandatory)]
        [string]$WorkingDirectory,

        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$CommandSpec,

        [Parameter(Mandatory)]
        [hashtable]$Tokens,

        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$TargetFailures
    )

    foreach ($RequiredName in @('name', 'executable')) {
        if (-not $CommandSpec.Contains($RequiredName)) {
            throw "Validation command for target '$TargetName' is missing '$RequiredName'."
        }
    }

    $Name = Convert-TokenText -Text ([string]$CommandSpec['name']) -Tokens $Tokens
    $Executable = Convert-TokenText -Text ([string]$CommandSpec['executable']) -Tokens $Tokens
    $Arguments = @(
        foreach ($Argument in (Get-ManifestItems -Container $CommandSpec -Name 'arguments')) {
            Convert-TokenText -Text ([string]$Argument) -Tokens $Tokens
        }
    )

    Write-ReportSection -ReportPath $ReportPath -Title $Name
    Write-ReportLine -ReportPath $ReportPath -Text ('Working directory: {0}' -f $WorkingDirectory)
    Write-ReportLine -ReportPath $ReportPath -Text ('Command: {0} {1}' -f $Executable, ($Arguments -join ' '))

    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Executable @Arguments 2>&1 | ForEach-Object {
            Write-ReportLine -ReportPath $ReportPath -Text ([string]$_)
        }

        $ExitCode = $LASTEXITCODE
        if ($null -eq $ExitCode) {
            $ExitCode = 0
        }

        if ($ExitCode -ne 0) {
            throw "Command returned exit code $ExitCode."
        }

        Write-ReportLine -ReportPath $ReportPath -Text "RESULT: PASS - $Name"
    }
    catch {
        $Message = $_.Exception.Message
        $Failure = "$Name`: $Message"
        $TargetFailures.Add($Failure)
        $OverallFailures.Add("$TargetName - $Failure")
        Write-ReportLine -ReportPath $ReportPath -Text "RESULT: FAIL - $Name"
        Write-ReportLine -ReportPath $ReportPath -Text "ERROR: $Message"
    }
    finally {
        Pop-Location
    }
}

function Write-TargetContextSnapshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$TargetName,

        [Parameter(Mandatory)]
        [string]$WorkingDirectory,

        [Parameter(Mandatory)]
        [System.Collections.IDictionary]$TargetSpec,

        [Parameter(Mandatory)]
        [string]$ReportPath,

        [Parameter(Mandatory)]
        [string]$ContextPath
    )

    $Lines = [System.Collections.Generic.List[string]]::new()
    $Lines.Add("# Validation Context: $TargetName") | Out-Null
    $Lines.Add('') | Out-Null
    $Lines.Add("Generated: $(Get-Date -Format o)") | Out-Null
    $Lines.Add("Branch: $(& git -C $RepoRoot branch --show-current 2>$null)") | Out-Null
    $Lines.Add("Commit: $(& git -C $RepoRoot rev-parse HEAD 2>$null)") | Out-Null
    $Lines.Add("Validation report: $([System.IO.Path]::GetRelativePath($RepoRoot, $ReportPath))") | Out-Null
    $Lines.Add('') | Out-Null
    $Lines.Add('## Validation Highlights') | Out-Null
    $Lines.Add('') | Out-Null

    $HighlightLines = @(
        Get-Content -LiteralPath $ReportPath -ErrorAction SilentlyContinue |
            Where-Object {
                $_ -match '^(?:TARGET RESULT|OVERALL RESULT|Failure count|RESULT: (?:PASS|FAIL))' -or
                $_ -match '(?i)\b(?:passed|failed|skipped|errors?)\b.*\bin\s+[0-9.]+s\b'
            } |
            Select-Object -Last 30
    )
    if ($HighlightLines.Count -eq 0) {
        $Lines.Add('- No summary lines were detected in the validation report.') | Out-Null
    }
    else {
        foreach ($HighlightLine in $HighlightLines) {
            $Lines.Add("- $HighlightLine") | Out-Null
        }
    }

    $Lines.Add('') | Out-Null
    $Lines.Add('## Working Tree') | Out-Null
    $Lines.Add('') | Out-Null
    $GitStatus = @(& git -C $RepoRoot status --short 2>$null)
    if ($GitStatus.Count -eq 0) {
        $Lines.Add('```text') | Out-Null
        $Lines.Add('(clean)') | Out-Null
        $Lines.Add('```') | Out-Null
    }
    else {
        $Lines.Add('```text') | Out-Null
        foreach ($StatusLine in $GitStatus) {
            $Lines.Add([string]$StatusLine) | Out-Null
        }
        $Lines.Add('```') | Out-Null
    }

    $Lines.Add('') | Out-Null
    $Lines.Add('## Project Status Sources') | Out-Null
    $Lines.Add('') | Out-Null
    $ContextFiles = @(Get-ManifestItems -Container $TargetSpec -Name 'context_files')
    if ($ContextFiles.Count -eq 0) {
        $Lines.Add('No context files are configured for this target.') | Out-Null
    }
    else {
        foreach ($RelativePathObject in $ContextFiles) {
            $RelativePath = [string]$RelativePathObject
            $SourcePath = Join-Path $WorkingDirectory $RelativePath
            $Lines.Add(('### `{0}`' -f $RelativePath)) | Out-Null
            $Lines.Add('') | Out-Null

            if (Test-Path -LiteralPath $SourcePath -PathType Leaf) {
                $SourceText = Get-Content -LiteralPath $SourcePath -Raw
                $Lines.Add($SourceText.TrimEnd()) | Out-Null
            }
            else {
                $Lines.Add(('_Missing at validation time: `{0}`_' -f $SourcePath)) | Out-Null
            }

            $Lines.Add('') | Out-Null
        }
    }

    Set-Content -LiteralPath $ContextPath -Value $Lines -Encoding utf8
}

function Write-ContextProgressDiff {
    [CmdletBinding()]
    param(
        [Parameter()]
        [AllowNull()]
        [string]$PreviousContextPath,

        [Parameter(Mandatory)]
        [string]$CurrentContextPath,

        [Parameter(Mandatory)]
        [string]$ProgressPath
    )

    if ([string]::IsNullOrWhiteSpace($PreviousContextPath) -or -not (Test-Path -LiteralPath $PreviousContextPath)) {
        Set-Content `
            -LiteralPath $ProgressPath `
            -Value 'No previous context snapshot is available. This validation establishes the baseline.' `
            -Encoding utf8
        return
    }

    $DiffOutput = @(
        & git -c core.quotepath=false diff --no-index --no-ext-diff --unified=3 -- $PreviousContextPath $CurrentContextPath 2>&1
    )
    $DiffExitCode = $LASTEXITCODE

    if ($DiffExitCode -eq 0) {
        Set-Content `
            -LiteralPath $ProgressPath `
            -Value 'No project-status changes were detected since the previous validation context.' `
            -Encoding utf8
        return
    }

    if ($DiffExitCode -eq 1) {
        Set-Content -LiteralPath $ProgressPath -Value $DiffOutput -Encoding utf8
        return
    }

    Set-Content `
        -LiteralPath $ProgressPath `
        -Value @(
            "Unable to generate context diff. git diff --no-index exited with code $DiffExitCode.",
            $DiffOutput
        ) `
        -Encoding utf8
}

if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Validation manifest not found: $ManifestPath"
}

$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json -AsHashtable
if (-not $Manifest.Contains('targets')) {
    throw "Validation manifest does not define a 'targets' object: $ManifestPath"
}

$AvailableTargets = @($Manifest['targets'].Keys | Sort-Object)
if ($ListTargets) {
    foreach ($Name in $AvailableTargets) {
        $Description = [string]$Manifest['targets'][$Name]['description']
        Write-Output ("{0,-24} {1}" -f $Name, $Description)
    }

    exit 0
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

$Python = Resolve-PythonExecutable
New-Item -ItemType Directory -Path $ResultsRoot -Force | Out-Null

foreach ($TargetName in $SelectedTargets) {
    $TargetSpec = $Manifest['targets'][$TargetName]
    if (-not $TargetSpec.Contains('working_directory')) {
        throw "Validation target '$TargetName' does not define a working_directory."
    }

    $WorkingDirectory = Join-Path $RepoRoot ([string]$TargetSpec['working_directory'])
    if (-not (Test-Path -LiteralPath $WorkingDirectory)) {
        throw "Working directory for target '$TargetName' does not exist: $WorkingDirectory"
    }

    $InitialStatus = @(& git -C $RepoRoot status --short 2>$null)
    $SafeTargetName = $TargetName -replace '[^A-Za-z0-9._-]', '_'
    $TargetResultsRoot = Join-Path $ResultsRoot $SafeTargetName
    $ReportStore = Initialize-TargetReportStore `
        -TargetResultsRoot $TargetResultsRoot `
        -SafeTargetName $SafeTargetName `
        -MaxHistoryCount $MaxHistoryPerTarget `
        -MaxHistoryDays $MaxHistoryAgeDays
    $ContextStore = Initialize-TargetContextStore `
        -TargetResultsRoot $TargetResultsRoot `
        -SafeTargetName $SafeTargetName `
        -PreferredArchiveStamp $ReportStore.PreviousArchiveStamp `
        -MaxHistoryCount $MaxHistoryPerTarget `
        -MaxHistoryDays $MaxHistoryAgeDays

    $ReportPath = [string]$ReportStore.ReportPath
    $ContextPath = [string]$ContextStore.ContextPath
    $ProgressPath = [string]$ContextStore.ProgressPath
    $PreviousContextPath = $ContextStore.PreviousContextPath
    $TempRoot = Join-Path $WorkingDirectory ('.pytest_tmp_root\validation-{0}' -f $Timestamp)
    $TargetFailures = [System.Collections.Generic.List[string]]::new()

    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    Set-Content -LiteralPath $ReportPath -Value '' -Encoding utf8
    $ReportPaths.Add($ReportPath)
    $ContextPaths.Add($ContextPath)
    $ProgressPaths.Add($ProgressPath)

    $Tokens = @{
        '{repo_root}' = $RepoRoot
        '{target_root}' = $WorkingDirectory
        '{temp_root}' = $TempRoot
        '{python}' = $Python
        '{include_production_read_only}' = if ($IncludeProductionReadOnly) { '1' } else { '0' }
        '{include_production_read_only_bool}' = if ($IncludeProductionReadOnly) { 'True' } else { 'False' }
    }

    $PreviousEnvironment = @{}
    try {
        if ($TargetSpec.Contains('environment')) {
            foreach ($Entry in $TargetSpec['environment'].GetEnumerator()) {
                $VariableName = [string]$Entry.Key
                $PreviousEnvironment[$VariableName] = [Environment]::GetEnvironmentVariable($VariableName, 'Process')
                $ResolvedValue = Convert-TokenText -Text ([string]$Entry.Value) -Tokens $Tokens
                [Environment]::SetEnvironmentVariable($VariableName, $ResolvedValue, 'Process')
            }
        }

        $Description = if ($TargetSpec.Contains('description')) {
            [string]$TargetSpec['description']
        }
        else {
            ''
        }

        Write-ReportSection -ReportPath $ReportPath -Title ("VALIDATION TARGET: {0}" -f $TargetName)
        Write-ReportLine -ReportPath $ReportPath -Text "Timestamp: $(Get-Date -Format o)"
        Write-ReportLine -ReportPath $ReportPath -Text "Description: $Description"
        Write-ReportLine -ReportPath $ReportPath -Text "Repository root: $RepoRoot"
        Write-ReportLine -ReportPath $ReportPath -Text "Working directory: $WorkingDirectory"
        Write-ReportLine -ReportPath $ReportPath -Text "Python: $Python"
        Write-ReportLine -ReportPath $ReportPath -Text "PowerShell: $($PSVersionTable.PSVersion)"
        Write-ReportLine -ReportPath $ReportPath -Text "Platform: $([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)"
        Write-ReportLine -ReportPath $ReportPath -Text "Bootstrap enabled: $(-not $SkipBootstrap)"
        Write-ReportLine -ReportPath $ReportPath -Text "Production read-only checks: $([bool]$IncludeProductionReadOnly)"
        Write-ReportLine -ReportPath $ReportPath -Text "History retention: $MaxHistoryPerTarget prior runs, maximum age $MaxHistoryAgeDays days"
        Write-ReportLine -ReportPath $ReportPath -Text "Git branch: $(& git -C $RepoRoot branch --show-current 2>$null)"
        Write-ReportLine -ReportPath $ReportPath -Text "Git commit: $(& git -C $RepoRoot rev-parse HEAD 2>$null)"
        Write-ReportLine -ReportPath $ReportPath -Text 'Git status before validation:'

        if ($InitialStatus.Count -eq 0) {
            Write-ReportLine -ReportPath $ReportPath -Text '(clean)'
        }
        else {
            foreach ($Line in $InitialStatus) {
                Write-ReportLine -ReportPath $ReportPath -Text ([string]$Line)
            }
        }

        if (-not $SkipBootstrap) {
            foreach ($CommandSpec in (Get-ManifestItems -Container $TargetSpec -Name 'bootstrap')) {
                $InvokeParameters = @{
                    TargetName = $TargetName
                    ReportPath = $ReportPath
                    WorkingDirectory = $WorkingDirectory
                    CommandSpec = $CommandSpec
                    Tokens = $Tokens
                    TargetFailures = $TargetFailures
                }
                Invoke-ManifestCommand @InvokeParameters
            }
        }

        foreach ($CommandSpec in (Get-ManifestItems -Container $TargetSpec -Name 'commands')) {
            $InvokeParameters = @{
                TargetName = $TargetName
                ReportPath = $ReportPath
                WorkingDirectory = $WorkingDirectory
                CommandSpec = $CommandSpec
                Tokens = $Tokens
                TargetFailures = $TargetFailures
            }
            Invoke-ManifestCommand @InvokeParameters
        }

        foreach ($ScriptGroup in (Get-ManifestItems -Container $TargetSpec -Name 'powershell_tests')) {
            if (-not $ScriptGroup.Contains('glob')) {
                throw "A PowerShell test group for '$TargetName' does not define a glob."
            }

            $Pattern = Join-Path $WorkingDirectory ([string]$ScriptGroup['glob'])
            $Scripts = @(Get-ChildItem -Path $Pattern -File -ErrorAction SilentlyContinue | Sort-Object FullName)

            if ($Scripts.Count -eq 0) {
                $Message = "No PowerShell tests matched: $Pattern"
                $TargetFailures.Add($Message)
                $OverallFailures.Add("$TargetName - $Message")
                Write-ReportSection -ReportPath $ReportPath -Title 'POWERSHELL TEST DISCOVERY'
                Write-ReportLine -ReportPath $ReportPath -Text "RESULT: FAIL - $Message"
                continue
            }

            foreach ($Script in $Scripts) {
                $ScriptArguments = @(
                    foreach ($Argument in (Get-ManifestItems -Container $ScriptGroup -Name 'arguments')) {
                        Convert-TokenText -Text ([string]$Argument) -Tokens $Tokens
                    }
                )

                $CommandSpec = @{
                    name = "PowerShell test: $([System.IO.Path]::GetRelativePath($WorkingDirectory, $Script.FullName))"
                    executable = 'pwsh'
                    arguments = @('-NoLogo', '-NoProfile', '-File', $Script.FullName) + $ScriptArguments
                }
                $InvokeParameters = @{
                    TargetName = $TargetName
                    ReportPath = $ReportPath
                    WorkingDirectory = $WorkingDirectory
                    CommandSpec = $CommandSpec
                    Tokens = $Tokens
                    TargetFailures = $TargetFailures
                }
                Invoke-ManifestCommand @InvokeParameters
            }
        }

        Write-ReportSection -ReportPath $ReportPath -Title 'TARGET SUMMARY'
        Write-ReportLine -ReportPath $ReportPath -Text "Latest report: $ReportPath"
        Write-ReportLine -ReportPath $ReportPath -Text "Context snapshot: $ContextPath"
        Write-ReportLine -ReportPath $ReportPath -Text "Progress diff: $ProgressPath"
        if ($TargetFailures.Count -eq 0) {
            Write-ReportLine -ReportPath $ReportPath -Text 'TARGET RESULT: PASS'
            Write-ReportLine -ReportPath $ReportPath -Text 'All requested validation sections passed.'
        }
        else {
            Write-ReportLine -ReportPath $ReportPath -Text 'TARGET RESULT: FAIL'
            Write-ReportLine -ReportPath $ReportPath -Text "Failure count: $($TargetFailures.Count)"
            foreach ($Failure in $TargetFailures) {
                Write-ReportLine -ReportPath $ReportPath -Text "- $Failure"
            }
        }

        Write-ReportLine -ReportPath $ReportPath
        Write-ReportLine -ReportPath $ReportPath -Text 'Git status after validation:'
        $FinalStatus = @(& git -C $RepoRoot status --short 2>$null)
        if ($FinalStatus.Count -eq 0) {
            Write-ReportLine -ReportPath $ReportPath -Text '(clean)'
        }
        else {
            foreach ($Line in $FinalStatus) {
                Write-ReportLine -ReportPath $ReportPath -Text ([string]$Line)
            }
        }

        Write-TargetContextSnapshot `
            -TargetName $TargetName `
            -WorkingDirectory $WorkingDirectory `
            -TargetSpec $TargetSpec `
            -ReportPath $ReportPath `
            -ContextPath $ContextPath
        Write-ContextProgressDiff `
            -PreviousContextPath $PreviousContextPath `
            -CurrentContextPath $ContextPath `
            -ProgressPath $ProgressPath
    }
    finally {
        foreach ($Entry in $PreviousEnvironment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable([string]$Entry.Key, $Entry.Value, 'Process')
        }
    }
}

Write-Output ''
Write-Output ('=' * 100)
Write-Output 'REPOSITORY VALIDATION SUMMARY'
Write-Output ('=' * 100)
for ($Index = 0; $Index -lt $ReportPaths.Count; $Index++) {
    Write-Output "Latest report: $($ReportPaths[$Index])"
    Write-Output "Context snapshot: $($ContextPaths[$Index])"
    Write-Output "Progress diff: $($ProgressPaths[$Index])"
}

if ($OverallFailures.Count -eq 0) {
    Write-Output 'OVERALL RESULT: PASS'
    exit 0
}

Write-Output 'OVERALL RESULT: FAIL'
Write-Output "Failure count: $($OverallFailures.Count)"
foreach ($Failure in $OverallFailures) {
    Write-Output "- $Failure"
}

exit 1
