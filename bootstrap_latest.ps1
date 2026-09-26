[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$VerboseOutput
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$helper = Join-Path $repoRoot 'bootstrap_latest.py'

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($DryRun) {
        Write-Host "[DRY RUN] Would create .venv; package inventory unavailable until it exists."
        exit 0
    }
    Write-Host '[BOOTSTRAP LATEST] Creating missing .venv...'
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) { & uv venv --seed (Join-Path $repoRoot '.venv') }
    else { & python -m venv (Join-Path $repoRoot '.venv') }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$savedPythonPath = $env:PYTHONPATH
$savedNoUserSite = $env:PYTHONNOUSERSITE
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = '1'
    $pipAvailable = $false
    try {
        & $venvPython -m pip --version *> $null
        $pipAvailable = $LASTEXITCODE -eq 0
    } catch {
        $pipAvailable = $false
    }
    if (-not $pipAvailable) {
        if ($DryRun) {
            Write-Host '[DRY RUN] pip is missing; would run ensurepip.'
            exit 0
        }
        & $venvPython -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    $helperArgs = @($helper)
    if ($DryRun) { $helperArgs += '--dry-run' }
    if ($VerboseOutput -or $PSBoundParameters.ContainsKey('Verbose')) { $helperArgs += '--verbose' }
    & $venvPython @helperArgs
    exit $LASTEXITCODE
}
finally {
    if ($null -eq $savedPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $savedPythonPath }
    if ($null -eq $savedNoUserSite) { Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue }
    else { $env:PYTHONNOUSERSITE = $savedNoUserSite }
}
