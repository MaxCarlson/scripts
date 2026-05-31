param(
  [Alias('s')]
  [switch]$SkipReinstall,
  [switch]$NoSkipReinstall,
  [Alias('U')]
  [switch]$NoUpdateHelp,
  [switch]$NoPipUpgrade,
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]]$Args
)

$ErrorActionPreference = 'Stop'

# Force UTF-8 encoding for Windows
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$VerboseSetup = ($Args -contains '--verbose') -or ($Args -contains '-v')

Write-Host "[BOOTSTRAP] Starting..." -ForegroundColor Cyan

function Write-BootstrapDetail([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::DarkGray) {
    if ($VerboseSetup) {
        Write-Host $Message -ForegroundColor $Color
    }
}

function Write-BootstrapStep([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::DarkGray) {
    Write-Host $Message -ForegroundColor $Color
}

if ($SkipReinstall -and $NoSkipReinstall) {
    Write-Host "[ERROR] Use either --skip-reinstall or --no-skip-reinstall, not both." -ForegroundColor Red
    exit 2
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $Root '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPip = Join-Path $VenvDir 'Scripts\pip.exe'

function Ensure-PscriptsSubmodule {
    $pscriptsDir = Join-Path $Root 'pscripts'
    $pscriptsSetup = Join-Path $pscriptsDir 'setup.py'
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue

    if (-not $gitCommand) {
        if (-not (Test-Path $pscriptsSetup)) {
            Write-Host "[ERROR] pscripts submodule is missing, and git is not available to initialize it." -ForegroundColor Red
            exit 1
        }
        return
    }

    $expected = ''
    try {
        $treeLine = (& git -C $Root ls-tree HEAD pscripts 2>$null)
        if ($treeLine) {
            $parts = $treeLine -split '\s+'
            if ($parts.Count -ge 3) {
                $expected = $parts[2]
            }
        }
    } catch {
        $expected = ''
    }
    if (-not $expected) {
        return
    }

    $actual = ''
    $submoduleGitDir = Join-Path $pscriptsDir '.git'
    if (Test-Path $submoduleGitDir) {
        try {
            $actual = (& git -C $pscriptsDir rev-parse HEAD 2>$null)
        } catch {
            $actual = ''
        }
    }

    if ((Test-Path $pscriptsSetup) -and ($actual -eq $expected)) {
        return
    }

    Write-BootstrapStep "[BOOTSTRAP] Updating pscripts submodule..." Cyan
    & git -C $Root submodule sync -- pscripts *> $null
    & git -C $Root submodule update --init --recursive -- pscripts
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to initialize/update pscripts submodule." -ForegroundColor Red
        Write-Host "[ERROR] Check GitHub auth/network access, then rerun bootstrap." -ForegroundColor Red
        exit 1
    }

    if (-not (Test-Path $pscriptsSetup)) {
        Write-Host "[ERROR] pscripts submodule initialized, but pscripts/setup.py is still missing." -ForegroundColor Red
        exit 1
    }
}

# ── Pscripts submodule ────────────────────────────────────────────────────────
Write-BootstrapStep "[BOOTSTRAP] Checking pscripts submodule..." DarkGray
Ensure-PscriptsSubmodule

# ── Repo path environment ─────────────────────────────────────────────────────
$repoHelperPath = Join-Path $Root "pwsh\ResolveRepoPaths.ps1"
if (Test-Path $repoHelperPath) {
    Write-BootstrapStep "[BOOTSTRAP] Synchronizing repo paths..." DarkGray
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

# ── Virtual environment ───────────────────────────────────────────────────────
$venvWasCreated = $false
if (-not (Test-Path $VenvPython)) {
    Write-BootstrapStep "[BOOTSTRAP] Creating .venv..." Yellow
    $venvWasCreated = $true

    $UvPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($UvPath) {
        Write-BootstrapDetail "[BOOTSTRAP] Using uv to create venv..." Green
        if ($VerboseSetup) { & uv venv --seed $VenvDir } else { & uv venv --seed $VenvDir *> $null }
    } else {
        Write-BootstrapDetail "[BOOTSTRAP] Using python -m venv..." Yellow
        if ($VerboseSetup) { & python -m venv $VenvDir } else { & python -m venv $VenvDir *> $null }
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        exit 1
    }
} else {
    Write-BootstrapDetail "[BOOTSTRAP] Venv already exists, skipping creation." DarkGray
}

# ── Pipx ──────────────────────────────────────────────────────────────────────
if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
    Write-BootstrapStep "[BOOTSTRAP] Installing pipx (user)..." Yellow
    $systemPy = Get-Command "C:\Users\mcarls\AppData\Local\Programs\Python\Python312\python.exe" -ErrorAction SilentlyContinue
    if (-not $systemPy) { $systemPy = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $systemPy) { $systemPy = Get-Command python -ErrorAction SilentlyContinue }
    if ($systemPy) {
        if ($VerboseSetup) { & $systemPy.Source -m pip install --user pipx }
        else { & $systemPy.Source -m pip install --quiet --user pipx *> $null }
    } else {
        Write-Warning "[BOOTSTRAP] Could not find a system Python to install pipx."
    }
}

# ── Pip bootstrap (only needed for a fresh venv or missing pip) ───────────────
# We skip the upgrade network round-trip on every run — pip was already
# upgraded the last time the venv was created or explicitly re-bootstrapped.
# Pass -NoPipUpgrade to suppress even on a fresh venv.
$pipMissing = -not (Test-Path $VenvPip)
if ($pipMissing) {
    Write-BootstrapStep "[BOOTSTRAP] pip not found in venv — running ensurepip..." Yellow
    if ($VerboseSetup) { & $VenvPython -m ensurepip --upgrade 2>$null }
    else { & $VenvPython -m ensurepip --upgrade *> $null }
}

if (($venvWasCreated -or $pipMissing) -and -not $NoPipUpgrade) {
    Write-BootstrapStep "[BOOTSTRAP] Upgrading pip/setuptools/wheel in fresh venv..." Yellow
    if ($VerboseSetup) { & $VenvPython -m pip install --quiet --upgrade pip setuptools wheel }
    else { & $VenvPython -m pip install --quiet --upgrade pip setuptools wheel *> $null }
}

# ── Tomli (Python < 3.11 only) ────────────────────────────────────────────────
$PythonVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([float]$PythonVersion -lt 3.11) {
    Write-BootstrapDetail "[BOOTSTRAP] Installing tomli for Python $PythonVersion..." Yellow
    if ($VerboseSetup) { & $VenvPython -m pip install --quiet tomli }
    else { & $VenvPython -m pip install --quiet tomli *> $null }
}

# ── Setup ─────────────────────────────────────────────────────────────────────
Write-BootstrapDetail "[BOOTSTRAP] Launching setup.py..." Cyan
$SetupArgs = @()
if ($SkipReinstall)   { $SetupArgs += "--skip-reinstall" }
if ($NoSkipReinstall) { $SetupArgs += "--no-skip-reinstall" }
if ($NoUpdateHelp)    { $SetupArgs += "--no-update-help" }
$SetupArgs += $Args
& $VenvPython (Join-Path $Root 'setup.py') @SetupArgs
exit $LASTEXITCODE
