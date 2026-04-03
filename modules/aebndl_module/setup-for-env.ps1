# This script sets up the development environment by installing the main repository
# and its submodules (termdash and procparsers) in editable mode.

# Get the absolute path of the script's directory (which should be the repo root)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

Write-Host "Installing main repository in editable mode..."
Set-Location -Path $scriptDir
pip install -e .

Write-Host "Installing termdash submodule in editable mode..."
Set-Location -Path (Join-Path $scriptDir "termdash")
pip install -e .

Write-Host "Installing procparsers submodule in editable mode..."
Set-Location -Path (Join-Path $scriptDir "procparsers")
pip install -e .

Write-Host "Setup complete."
