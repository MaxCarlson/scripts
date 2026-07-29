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
    [switch]$IncludeProductionReadOnly
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
    $ReportPath = Join-Path $TargetResultsRoot ("{0}_{1}.txt" -f $Timestamp, $SafeTargetName)
    $TempRoot = Join-Path $WorkingDirectory ('.pytest_tmp_root\validation-{0}' -f $Timestamp)
    $TargetFailures = [System.Collections.Generic.List[string]]::new()

    New-Item -ItemType Directory -Path $TargetResultsRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    Set-Content -LiteralPath $ReportPath -Value '' -Encoding utf8
    $ReportPaths.Add($ReportPath)

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
        Write-ReportLine -ReportPath $ReportPath -Text "Report: $ReportPath"
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
foreach ($ReportPath in $ReportPaths) {
    Write-Output "Report: $ReportPath"
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
