param(
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]]$Args
)

$ErrorActionPreference = 'Stop'

# Force UTF-8 encoding for Windows
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $Root '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

Write-Host "[BOOTSTRAP] Ensuring Python virtual environment..." -ForegroundColor Cyan

# 1) Create .venv if it doesn't exist
if (-not (Test-Path $VenvPython)) {
    Write-Host "[BOOTSTRAP] Creating .venv using system Python..." -ForegroundColor Yellow

    # Try uv first (faster), fallback to python -m venv
    $UvPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($UvPath) {
        Write-Host "[BOOTSTRAP] Using uv to create venv..." -ForegroundColor Green
        & uv venv --seed $VenvDir
    } else {
        Write-Host "[BOOTSTRAP] Using python -m venv..." -ForegroundColor Yellow
        & python -m venv $VenvDir
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
}

# 2) Ensure pip is available in venv
Write-Host "[BOOTSTRAP] Ensuring pip is available in venv..." -ForegroundColor Cyan
& $VenvPython -m ensurepip --upgrade 2>$null
& $VenvPython -m pip install --quiet --upgrade pip setuptools wheel

# 3) Install tomli if needed (for setup.py TOML parsing on Python < 3.11)
$PythonVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([float]$PythonVersion -lt 3.11) {
    Write-Host "[BOOTSTRAP] Installing tomli for Python $PythonVersion..." -ForegroundColor Yellow
    & $VenvPython -m pip install --quiet tomli
}

# 4) Execute repo setup (installs core modules, wires bin wrappers)
Write-Host "[BOOTSTRAP] Running setup.py with venv Python..." -ForegroundColor Cyan
& $VenvPython (Join-Path $Root 'setup.py') @Args
exit $LASTEXITCODE

