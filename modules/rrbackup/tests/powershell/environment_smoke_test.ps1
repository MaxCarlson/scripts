[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepoRoot,

    [Parameter(Mandatory)]
    [string]$PythonExecutable,

    [Parameter()]
    [switch]$IncludeProductionReadOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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

Write-Output "RepoRoot=$RepoRoot"
Write-Output "PythonExecutable=$PythonExecutable"
Write-Output "PowerShellVersion=$($PSVersionTable.PSVersion)"
Write-Output "IncludeProductionReadOnly=$([bool]$IncludeProductionReadOnly)"

Assert-True -Condition (Test-Path -LiteralPath $RepoRoot -PathType Container) -Message 'Repository root does not exist.'
Assert-True -Condition (Test-Path -LiteralPath $PythonExecutable -PathType Leaf) -Message 'Python executable does not exist.'

$ModuleRoot = Join-Path $RepoRoot 'modules\rrbackup'
Assert-True -Condition (Test-Path -LiteralPath $ModuleRoot -PathType Container) -Message 'RRBackup module root does not exist.'
Assert-True -Condition (Test-Path -LiteralPath (Join-Path $ModuleRoot 'pyproject.toml') -PathType Leaf) -Message 'RRBackup pyproject.toml is missing.'

$VersionOutput = & $PythonExecutable --version 2>&1
Assert-True -Condition ($LASTEXITCODE -eq 0) -Message 'Python --version failed.'
Write-Output $VersionOutput

$PreviousPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
$OriginalLocation = Get-Location
try {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process')
    Set-Location -LiteralPath $RepoRoot

    $ImportOutput = & $PythonExecutable -c "import rrbackup; print(rrbackup.__file__); print(rrbackup.__version__)" 2>&1
    Assert-True -Condition ($LASTEXITCODE -eq 0) -Message "Unable to import rrbackup without injected PYTHONPATH: $($ImportOutput -join ' ')"
    Assert-True -Condition (($ImportOutput -join "`n") -match '0\.3\.0') -Message 'RRBackup package version was not 0.3.0.'
    Write-Output "rrbackup import without PYTHONPATH: $($ImportOutput -join ' | ')"

    $ScriptsRoot = Split-Path -Parent $PythonExecutable
    foreach ($EntryPointName in @('rrb', 'rrbackup')) {
        $Candidate = Join-Path $ScriptsRoot "$EntryPointName.exe"
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            $Candidate = Join-Path $ScriptsRoot $EntryPointName
        }

        Assert-True -Condition (Test-Path -LiteralPath $Candidate -PathType Leaf) -Message "Installed entry point is missing: $Candidate"
        $HelpOutput = & $Candidate --help 2>&1
        Assert-True -Condition ($LASTEXITCODE -eq 0) -Message "$EntryPointName --help failed: $($HelpOutput -join ' ')"
        Assert-True -Condition (($HelpOutput -join "`n") -match '(?i)usage') -Message "$EntryPointName --help did not contain a usage line."
        Write-Output "$EntryPointName installed entry point: PASS ($Candidate)"
    }
}
finally {
    Set-Location -LiteralPath $OriginalLocation
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $PreviousPythonPath, 'Process')
}

$ResticCommand = Get-Command restic -ErrorAction SilentlyContinue
if ($ResticCommand) {
    $ResticVersion = & $ResticCommand.Source version 2>&1
    Assert-True -Condition ($LASTEXITCODE -eq 0) -Message "restic version failed: $($ResticVersion -join ' ')"
    Write-Output "restic: $($ResticCommand.Source)"
    Write-Output ($ResticVersion -join "`n")
}
else {
    Write-Output 'restic: NOT FOUND (allowed for unit-only validation; integration tests may fail or skip)'
}

Write-Output 'Environment smoke test completed successfully.'
