param(
  [Parameter(ValueFromRemainingArguments=$true)]
  [string[]]$Args
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1) Bootstrap Python tooling (uv/pipx/micromamba) best-effort
$Bootstrap = Join-Path $Root 'modules\python_setup\scripts\bootstrap.ps1'
if (Test-Path $Bootstrap) {
  try { & $Bootstrap @Args } catch { Write-Host "Bootstrap warnings: $_" -ForegroundColor Yellow }
}

# 2) Execute repo setup (creates .venv, installs core modules, wires bin wrappers)
& (Join-Path $Root 'setup.py') @Args
exit $LASTEXITCODE

