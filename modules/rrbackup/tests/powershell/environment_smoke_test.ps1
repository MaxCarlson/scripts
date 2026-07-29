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

$ImportOutput = & $PythonExecutable -c "import rrbackup; print(rrbackup.__file__)" 2>&1
Assert-True -Condition ($LASTEXITCODE -eq 0) -Message "Unable to import rrbackup: $($ImportOutput -join ' ')"
Write-Output "rrbackup import: $($ImportOutput -join ' ')"

$RrbHelp = & $PythonExecutable -m rrbackup.cli --help 2>&1
Assert-True -Condition ($LASTEXITCODE -eq 0) -Message "RRBackup CLI help failed: $($RrbHelp -join ' ')"
Assert-True -Condition (($RrbHelp -join "`n") -match '(?i)usage') -Message 'RRBackup CLI help did not contain a usage line.'
Write-Output 'rrbackup CLI help: PASS'

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
