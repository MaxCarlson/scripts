[CmdletBinding()]
param(
    [Parameter()]
    [switch]$Bootstrap,

    [Parameter()]
    [switch]$IncludeProductionReadOnly,

    [Parameter()]
    [switch]$SkipPytest,

    [Parameter()]
    [switch]$SkipPowerShellTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot
$ModuleRoot = Join-Path $RepoRoot 'modules\rrbackup'
$TestsRoot = Join-Path $ModuleRoot 'tests'
$ResultsRoot = Join-Path $ModuleRoot 'test-results'
$Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$TranscriptPath = Join-Path $ResultsRoot "rrbackup-validation-$Timestamp.txt"
$CoverageXmlPath = Join-Path $ResultsRoot "coverage-$Timestamp.xml"
$Failures = [System.Collections.Generic.List[string]]::new()

New-Item -ItemType Directory -Path $ResultsRoot -Force | Out-Null

function Write-ValidationSection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Title
    )

    Write-Output ''
    Write-Output ('=' * 88)
    Write-Output $Title
    Write-Output ('=' * 88)
}

function Invoke-ValidationCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    Write-ValidationSection $Name
    try {
        & $Command
        $ExitCode = $LASTEXITCODE
        if ($null -eq $ExitCode) {
            $ExitCode = 0
        }
        if ($ExitCode -ne 0) {
            throw "Command returned exit code $ExitCode."
        }
        Write-Output "RESULT: PASS - $Name"
    }
    catch {
        $Message = $_.Exception.Message
        $Failures.Add("$Name`: $Message")
        Write-Output "RESULT: FAIL - $Name"
        Write-Output "ERROR: $Message"
    }
}

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

    throw 'Unable to resolve a Python executable.'
}

$Python = Resolve-PythonExecutable
$env:RRBACKUP_TEST_RESULTS_DIR = $ResultsRoot
$env:RRBACKUP_INCLUDE_PRODUCTION_READ_ONLY = if ($IncludeProductionReadOnly) { '1' } else { '0' }
$env:PYTHONUTF8 = '1'

Start-Transcript -LiteralPath $TranscriptPath -Force | Out-Null
try {
    Write-ValidationSection 'RRBACKUP VALIDATION CONTEXT'
    Write-Output "Timestamp: $(Get-Date -Format o)"
    Write-Output "Repository root: $RepoRoot"
    Write-Output "Module root: $ModuleRoot"
    Write-Output "Python: $Python"
    Write-Output "PowerShell: $($PSVersionTable.PSVersion)"
    Write-Output "Platform: $([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)"
    Write-Output "Production read-only checks: $([bool]$IncludeProductionReadOnly)"
    Write-Output "Git branch: $(& git -C $RepoRoot branch --show-current 2>$null)"
    Write-Output "Git commit: $(& git -C $RepoRoot rev-parse HEAD 2>$null)"
    Write-Output 'Git status:'
    & git -C $RepoRoot status --short

    Invoke-ValidationCommand -Name 'Python version' -Command {
        & $Python --version
    }

    if ($Bootstrap) {
        Invoke-ValidationCommand -Name 'Install RRBackup editable development dependencies' -Command {
            & $Python -m pip install --disable-pip-version-check -e "$ModuleRoot[dev]"
        }
    }

    if (-not $SkipPytest) {
        Invoke-ValidationCommand -Name 'RRBackup pytest and coverage suite' -Command {
            & $Python -m pytest $TestsRoot `
                -vv `
                -ra `
                --tb=short `
                --durations=25 `
                --strict-config `
                --strict-markers `
                --cov=rrbackup `
                --cov-report=term-missing `
                "--cov-report=xml:$CoverageXmlPath"
        }
    }

    if (-not $SkipPowerShellTests) {
        $PowerShellTests = Get-ChildItem -LiteralPath $TestsRoot -Recurse -File -Filter '*_test.ps1' |
            Sort-Object FullName

        if (-not $PowerShellTests) {
            $Failures.Add('PowerShell tests: no *_test.ps1 scripts were found.')
            Write-ValidationSection 'POWERSHELL TEST DISCOVERY'
            Write-Output 'RESULT: FAIL - No *_test.ps1 scripts were found.'
        }

        foreach ($TestScript in $PowerShellTests) {
            $RelativePath = [System.IO.Path]::GetRelativePath($RepoRoot, $TestScript.FullName)
            Invoke-ValidationCommand -Name "PowerShell test: $RelativePath" -Command {
                & pwsh -NoLogo -NoProfile -File $TestScript.FullName `
                    -RepoRoot $RepoRoot `
                    -PythonExecutable $Python `
                    -IncludeProductionReadOnly:$IncludeProductionReadOnly
            }
        }
    }

    Write-ValidationSection 'VALIDATION SUMMARY'
    Write-Output "Transcript: $TranscriptPath"
    if (Test-Path -LiteralPath $CoverageXmlPath) {
        Write-Output "Coverage XML: $CoverageXmlPath"
    }

    if ($Failures.Count -eq 0) {
        Write-Output 'OVERALL RESULT: PASS'
        Write-Output 'All requested validation sections passed.'
    }
    else {
        Write-Output 'OVERALL RESULT: FAIL'
        Write-Output "Failure count: $($Failures.Count)"
        foreach ($Failure in $Failures) {
            Write-Output "- $Failure"
        }
    }
}
finally {
    Stop-Transcript | Out-Null
}

Write-Output ''
Write-Output "Paste-ready transcript written to: $TranscriptPath"

if ($Failures.Count -gt 0) {
    exit 1
}

exit 0
