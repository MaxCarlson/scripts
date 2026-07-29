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

$ModuleRoot = $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ModuleRoot)
$TestsRoot = Join-Path $ModuleRoot 'tests'
$OutputPath = Join-Path $ModuleRoot 'TEST_RESULTS.txt'
$TempRoot = Join-Path $ModuleRoot '.pytest_tmp_root\validation'
$Failures = [System.Collections.Generic.List[string]]::new()

New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
Set-Content -LiteralPath $OutputPath -Value '' -Encoding utf8

function Write-ResultLine {
    [CmdletBinding()]
    param(
        [Parameter()]
        [AllowEmptyString()]
        [string]$Text = ''
    )

    Write-Output $Text
    Add-Content -LiteralPath $OutputPath -Value $Text -Encoding utf8
}

function Write-TestSection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Title
    )

    Write-ResultLine
    Write-ResultLine ('=' * 96)
    Write-ResultLine $Title
    Write-ResultLine ('=' * 96)
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

function Invoke-CapturedCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$FilePath,

        [Parameter()]
        [string[]]$ArgumentList = @()
    )

    Write-TestSection $Name
    Write-ResultLine ('Command: {0} {1}' -f $FilePath, ($ArgumentList -join ' '))

    try {
        & $FilePath @ArgumentList 2>&1 | ForEach-Object {
            Write-ResultLine ([string]$_)
        }

        $ExitCode = $LASTEXITCODE
        if ($null -eq $ExitCode) {
            $ExitCode = 0
        }

        if ($ExitCode -ne 0) {
            throw "Command returned exit code $ExitCode."
        }

        Write-ResultLine "RESULT: PASS - $Name"
    }
    catch {
        $Message = $_.Exception.Message
        $Failures.Add("$Name`: $Message")
        Write-ResultLine "RESULT: FAIL - $Name"
        Write-ResultLine "ERROR: $Message"
    }
}

$Python = Resolve-PythonExecutable
$env:RRBACKUP_INCLUDE_PRODUCTION_READ_ONLY = if ($IncludeProductionReadOnly) { '1' } else { '0' }
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$env:TMP = $TempRoot
$env:TEMP = $TempRoot
$env:TMPDIR = $TempRoot
$env:COVERAGE_FILE = Join-Path $TempRoot '.coverage'

Write-TestSection 'RRBACKUP TEST CONTEXT'
Write-ResultLine "Timestamp: $(Get-Date -Format o)"
Write-ResultLine "Repository root: $RepoRoot"
Write-ResultLine "Module root: $ModuleRoot"
Write-ResultLine "Python: $Python"
Write-ResultLine "PowerShell: $($PSVersionTable.PSVersion)"
Write-ResultLine "Platform: $([System.Runtime.InteropServices.RuntimeInformation]::OSDescription)"
Write-ResultLine "Production read-only checks: $([bool]$IncludeProductionReadOnly)"

$Branch = & git -C $RepoRoot branch --show-current 2>$null
$Commit = & git -C $RepoRoot rev-parse HEAD 2>$null
$Status = @(& git -C $RepoRoot status --short 2>$null)
Write-ResultLine "Git branch: $Branch"
Write-ResultLine "Git commit: $Commit"
Write-ResultLine 'Git status before tests:'
if ($Status.Count -eq 0) {
    Write-ResultLine '(clean)'
}
else {
    foreach ($Line in $Status) {
        Write-ResultLine ([string]$Line)
    }
}

if ($Bootstrap) {
    Invoke-CapturedCommand -Name 'Install RRBackup editable development dependencies' -FilePath $Python -ArgumentList @(
        '-m',
        'pip',
        'install',
        '--disable-pip-version-check',
        '-e',
        "$ModuleRoot[dev]"
    )
}

if (-not $SkipPytest) {
    Invoke-CapturedCommand -Name 'RRBackup pytest and coverage suite' -FilePath $Python -ArgumentList @(
        '-m',
        'pytest',
        $TestsRoot,
        '-vv',
        '-ra',
        '--tb=short',
        '--durations=25',
        '--strict-config',
        '--strict-markers',
        '--basetemp',
        $TempRoot,
        '--cov=rrbackup',
        '--cov-branch',
        '--cov-report=term-missing'
    )
}

if (-not $SkipPowerShellTests) {
    $PowerShellTests = @(
        Get-ChildItem -LiteralPath $TestsRoot -Recurse -File -Filter '*_test.ps1' |
            Sort-Object FullName
    )

    if ($PowerShellTests.Count -eq 0) {
        $Message = 'No *_test.ps1 scripts were found.'
        $Failures.Add("PowerShell tests: $Message")
        Write-TestSection 'POWERSHELL TEST DISCOVERY'
        Write-ResultLine "RESULT: FAIL - $Message"
    }

    foreach ($TestScript in $PowerShellTests) {
        $RelativePath = [System.IO.Path]::GetRelativePath($ModuleRoot, $TestScript.FullName)
        Invoke-CapturedCommand -Name "PowerShell test: $RelativePath" -FilePath 'pwsh' -ArgumentList @(
            '-NoLogo',
            '-NoProfile',
            '-File',
            $TestScript.FullName,
            '-RepoRoot',
            $RepoRoot,
            '-PythonExecutable',
            $Python,
            "-IncludeProductionReadOnly:$([bool]$IncludeProductionReadOnly)"
        )
    }
}

Write-TestSection 'TEST SUMMARY'
Write-ResultLine "Result file: $OutputPath"

if ($Failures.Count -eq 0) {
    Write-ResultLine 'OVERALL RESULT: PASS'
    Write-ResultLine 'All requested test sections passed.'
}
else {
    Write-ResultLine 'OVERALL RESULT: FAIL'
    Write-ResultLine "Failure count: $($Failures.Count)"
    foreach ($Failure in $Failures) {
        Write-ResultLine "- $Failure"
    }
}

Write-ResultLine
Write-ResultLine 'Git status after tests:'
$FinalStatus = @(& git -C $RepoRoot status --short 2>$null)
if ($FinalStatus.Count -eq 0) {
    Write-ResultLine '(clean)'
}
else {
    foreach ($Line in $FinalStatus) {
        Write-ResultLine ([string]$Line)
    }
}

Write-Output ''
Write-Output "Tracked test output written to: $OutputPath"

if ($Failures.Count -gt 0) {
    exit 1
}

exit 0
