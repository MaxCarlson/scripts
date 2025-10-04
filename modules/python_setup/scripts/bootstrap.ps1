param(
  [switch]$Verbose
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PkgDir = Split-Path -Parent $ScriptDir
$Root = Resolve-Path (Join-Path $PkgDir '..\..\..')

$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path $VenvPy) {
  & $VenvPy -m python_setup.cli @args
  exit $LASTEXITCODE
}

python -m python_setup.cli @args
exit $LASTEXITCODE

