param(
  [Alias('s')]
  [switch]$SkipReinstall,
  [switch]$NoSkipReinstall,
  [Alias('U')]
  [switch]$NoUpdateHelp,
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]]$Args
)

$ErrorActionPreference = 'Stop'

# Force UTF-8 encoding for Windows
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$VerboseSetup = ($Args -contains '--verbose') -or ($Args -contains '-v')

function Write-BootstrapDetail([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::DarkGray) {
    if ($VerboseSetup) {
        Write-Host $Message -ForegroundColor $Color
    }
}

if ($SkipReinstall -and $NoSkipReinstall) {
    Write-Host "[ERROR] Use either --skip-reinstall or --no-skip-reinstall, not both." -ForegroundColor Red
    exit 2
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $Root '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$repoHelperPath = Join-Path $Root "pwsh\ResolveRepoPaths.ps1"
if (Test-Path $repoHelperPath) {
    try {
        . $repoHelperPath
        if ($VerboseSetup) {
            $repoEnv = Initialize-RepoEnvironment -AnchorPath $Root -AnchorRepoName 'scripts' -PersistScopes @('User')
        } else {
            $repoEnv = Initialize-RepoEnvironment -AnchorPath $Root -AnchorRepoName 'scripts' -PersistScopes @('User') 6>$null
        }
        if ($repoEnv.SCRIPTS) { $global:SCRIPTS_REPO = $repoEnv.SCRIPTS }
        $summary = @()
        foreach ($key in 'PWSH_REPO','SCRIPTS','DOTFILES') {
            $value = if ($repoEnv[$key]) { $repoEnv[$key] } else { '<missing>' }
            $summary += "${key}=$value"
        }
        Write-BootstrapDetail "[BOOTSTRAP] Repo env synchronized: $($summary -join ' | ')"
    } catch {
        Write-Warning "[BOOTSTRAP] Repo env initialization failed: $_"
    }
} else {
    Write-Warning "[BOOTSTRAP] Repo resolver missing at $repoHelperPath"
}


Write-BootstrapDetail "[BOOTSTRAP] Ensuring Python virtual environment..." Cyan

# 1) Create .venv if it doesn't exist
if (-not (Test-Path $VenvPython)) {
    Write-BootstrapDetail "[BOOTSTRAP] Creating .venv using system Python..." Yellow

    # Try uv first (faster), fallback to python -m venv
    $UvPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($UvPath) {
        Write-BootstrapDetail "[BOOTSTRAP] Using uv to create venv..." Green
        if ($VerboseSetup) { & uv venv --seed $VenvDir } else { & uv venv --seed $VenvDir *> $null }
    } else {
        Write-BootstrapDetail "[BOOTSTRAP] Using python -m venv..." Yellow
        if ($VerboseSetup) { & python -m venv $VenvDir } else { & python -m venv $VenvDir *> $null }
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
}

# Ensure pipx is installed (user scope) and on PATH for global CLIs
if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
    $systemPy = Get-Command "C:\Users\mcarls\AppData\Local\Programs\Python\Python312\python.exe" -ErrorAction SilentlyContinue
    if (-not $systemPy) { $systemPy = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $systemPy) { $systemPy = Get-Command python -ErrorAction SilentlyContinue }
    if ($systemPy) {
        Write-BootstrapDetail "[BOOTSTRAP] Installing pipx (user) via $($systemPy.Source)..." Yellow
        if ($VerboseSetup) { & $systemPy.Source -m pip install --user pipx } else { & $systemPy.Source -m pip install --quiet --user pipx *> $null }
    } else {
        Write-Warning "[BOOTSTRAP] Could not find a system Python to install pipx."
    }
}

# 2) Ensure pip is available in venv
Write-BootstrapDetail "[BOOTSTRAP] Ensuring pip is available in venv..." Cyan
if ($VerboseSetup) {
    & $VenvPython -m ensurepip --upgrade 2>$null
    & $VenvPython -m pip install --quiet --upgrade pip setuptools wheel
} else {
    & $VenvPython -m ensurepip --upgrade *> $null
    & $VenvPython -m pip install --quiet --upgrade pip setuptools wheel *> $null
}

# 3) Install tomli if needed (for setup.py TOML parsing on Python < 3.11)
$PythonVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([float]$PythonVersion -lt 3.11) {
    Write-BootstrapDetail "[BOOTSTRAP] Installing tomli for Python $PythonVersion..." Yellow
    if ($VerboseSetup) { & $VenvPython -m pip install --quiet tomli } else { & $VenvPython -m pip install --quiet tomli *> $null }
}

# 4) Execute repo setup (installs core modules, wires bin wrappers)
Write-BootstrapDetail "[BOOTSTRAP] Running setup.py with venv Python..." Cyan
$SetupArgs = @()
if ($SkipReinstall) {
    $SetupArgs += "--skip-reinstall"
}
if ($NoSkipReinstall) {
    $SetupArgs += "--no-skip-reinstall"
}
if ($NoUpdateHelp) {
    $SetupArgs += "--no-update-help"
}
$SetupArgs += $Args
& $VenvPython (Join-Path $Root 'setup.py') @SetupArgs
exit $LASTEXITCODE

