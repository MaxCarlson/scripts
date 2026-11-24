# Python Environment Setup Guide

## Overview

This repository provides a comprehensive, cross-platform Python environment setup that:

1. **Auto-creates and manages a `.venv`** in the repository root
2. **Auto-activates the venv** when you `cd` into the directory
3. **Makes module CLIs globally available** via wrapper scripts in `bin/`
4. **Works seamlessly** across Windows (PowerShell), WSL2, Cygwin/Git Bash, Termux

## Quick Start

### Initial Setup

```bash
# PowerShell (Windows)
.\bootstrap.ps1 -v

# Bash/Zsh (Linux, WSL, Cygwin, Termux)
./bootstrap.sh -v
```

This will:
- Create `.venv` if it doesn't exist
- Install all core modules (`standard_ui`, `cross_platform`, `python_setup`, `scripts_setup`)
- Install all modules from `modules/` directory
- Create console script wrappers in `bin/`
- Configure auto-activation for your shell
- Add `bin/` to your PATH

### Manual Setup (Alternative)

```bash
python setup.py -v 
# With proper args
python setup.py -R ~/scripts/ -D ~/dotfiles/ -B ~/src/scripts/bin/
```

### Repository-Only Setup

Use repository-only mode when you need the project environment and local `bin/`
launchers without wiring the current user or system:

```powershell
python setup.py --repository-only
# Short form:
python setup.py -r
```

This mode still installs the public modules and, when the pinned `pscripts`
submodule is available, its modules. It refreshes managed launchers and the
manifest, including standalone Python scripts under `pscripts/pyscripts/`. It
skips user PATH/PYTHONPATH registration, shell and PowerShell profile snippets,
agent-skill links, venv auto-activation, WSL system setup, and interactive help
registry updates. The mode is carried into setup subprocesses through the
`SCRIPTS_REPOSITORY_ONLY` environment marker.

Normal setup retains those integrations. Skill links can be directed to one or
more explicit destinations instead of the default CLI skill folders:

```powershell
python setup.py --skills-dir C:\tools\codex-skills --skills-dir D:\shared\skills
```

Repository-only setup ignores inherited `SCRIPTS` and bootstrap-skip settings,
uses the invoked checkout's `.venv`, and clears common Python and pip install
destination overrides before child installers run. It resolves managed output
paths before writing. This limits setup-owned destinations and integration
hooks; package build scripts still execute with the current user's normal
filesystem and network access, so this mode is not a general-purpose security
sandbox.

## How It Works

### 1. Virtual Environment Bootstrap

**setup.py**:
- Checks `sys.prefix` against the repository `.venv` to identify the active environment. This works when POSIX venv Python executables resolve through symlinks to the base interpreter.
- If not, creates `.venv` (preferring `uv venv --seed` if available)
- Re-execs itself under the venv Python
- All subsequent operations use the venv

### 2. Module Installation and Ownership Boundary

**modules/setup.py** and **scripts_setup/transferred_modules.py**:
- Scans `modules/` directory while excluding the 23 modules transferred to `MaxCarlson/llm-agent-toolkit` (`TRANSFERRED_MODULE_DIRS` / `TRANSFERRED_NORMALIZED_DISTRIBUTIONS` in `scripts_setup/transferred_modules.py`).
- Historical source directories for transferred modules remain untouched on disk in `scripts/modules/`, but are never installed into `scripts/.venv` or exposed via `scripts/bin`.
- Installs each `scripts`-owned module in editable mode (`pip install -e`).
- Tracks package names for proxy generation and handles dependencies via `dependency_resolver.py`.
- `scripts/bin` wrappers delegate invocation logging to `script_logging.launcher` using the sibling `llm-agent-toolkit/.venv` interpreter (or `LLM_AGENT_TOOLKIT_ROOT`) with `-I` and `--target-python` pointing to `scripts/.venv`.

### 3. Console Script Proxies

**Why needed?**
- Module CLIs are entry points in the venv
- We want them available globally, even when not in venv
- Solution: Create tiny wrapper scripts in `bin/` that delegate to venv

**How it works** (modules/setup.py lines 507-578):
- Scans all installed packages for console_scripts entry points
- For each script, creates:
  - **Windows**: `bin/script-name.cmd` that calls `.venv\Scripts\script-name.exe`
  - **Linux/Mac**: `bin/script-name` bash script that calls `.venv/bin/script-name`
- If venv script exists, uses it; otherwise falls back to PATH

**Example** - for `python-setup` command:

```cmd
@REM bin/python-setup.cmd (Windows)
@echo off
set "_V=%~dp0..\.venv\Scripts\"
if exist "%_V%\python-setup.exe" (
  "%_V%\python-setup.exe" %*
) else (
  python-setup %*
)
```

```bash
#!/usr/bin/env bash
# bin/python-setup (Linux/Mac)
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
T="$DIR/../.venv/bin/python-setup"
if [ -x "$T" ]; then exec "$T" "$@"; fi
exec "python-setup" "$@"
```

### 4. Auto-Activation

**PowerShell** - hooks into prompt function:
- Detects `.venv` in current directory
- Activates if present and not already active
- Deactivates when leaving directory
- Config: `~/dotfiles/dynamic/venv_auto_activation.ps1`

**Bash/Zsh** - wraps `cd` command:
- Same logic as PowerShell
- Config: `~/dotfiles/dynamic/venv_auto_activation.sh`

### 5. PATH Configuration

**Windows**:
- Uses PowerShell or `setx` to add `bin/` to User PATH
- Requires new terminal session to take effect

**Linux/Zsh**:
- Creates `~/dotfiles/dynamic/setup_path.zsh`
- Must be sourced in `.zshrc`

## Shell Configuration

### PowerShell

Your PowerShell profile should contain:

```powershell
# Add to: ~/Documents/PowerShell/Microsoft.PowerShell_profile.ps1

$dotfiles = "C:\Users\YourName\dotfiles"
$dynamic = "$dotfiles\dynamic"

# Source auto-activation (added automatically by setup)
if (Test-Path "$dynamic\venv_auto_activation.ps1") {
    . "$dynamic\venv_auto_activation.ps1"
}

# Source other dynamic configs
if (Test-Path "$dynamic\setup_pyscripts_aliases.ps1") {
    . "$dynamic\setup_pyscripts_aliases.ps1"
}
```

**Note**: `setup_pwsh_profile.py` adds this automatically!

### Bash/Zsh (Linux, WSL, Cygwin, Termux)

Add to your `.bashrc` or `.zshrc`:

```bash
# Add to: ~/.bashrc or ~/.zshrc

DOTFILES="$HOME/dotfiles"

# Source auto-activation
[[ -f "$DOTFILES/dynamic/venv_auto_activation.sh" ]] && source "$DOTFILES/dynamic/venv_auto_activation.sh"

# Source other dynamic configs
[[ -f "$DOTFILES/dynamic/setup_modules_pythonpath.zsh" ]] && source "$DOTFILES/dynamic/setup_modules_pythonpath.zsh"
[[ -f "$DOTFILES/dynamic/setup_path.zsh" ]] && source "$DOTFILES/dynamic/setup_path.zsh"
```

## Testing the Setup

### 1. Test Auto-Activation

```bash
# Navigate away and back
cd ~
cd ~/src/scripts  # Should auto-activate .venv

# Verify
which python  # Should point to ~/src/scripts/.venv/Scripts/python (or bin/python)
```

### 2. Test Global CLI Access

```bash
# From anywhere (not in scripts dir)
cd ~

# Should work without activating venv
python-setup --help
setup-venv-activation --help

# Check which is being used
which python-setup  # Should point to ~/src/scripts/bin/python-setup
```

### 3. Test Module Import

```bash
# From anywhere
python -c "from cross_platform import SystemUtils; print(SystemUtils.is_windows())"
```

## Troubleshooting

### "Command not found" for module CLIs

**Cause**: `bin/` not on PATH or proxies not generated

**Fix**:
```bash
# Re-run setup
python setup.py -v -f

# Verify bin/ on PATH
echo $PATH  # (Bash/Zsh)
$env:PATH   # (PowerShell)

# Should include: /path/to/scripts/bin
```

### Auto-activation not working

**PowerShell**:
```powershell
# Check if profile has the snippet
cat ~/Documents/PowerShell/Microsoft.PowerShell_profile.ps1

# Manually source for testing
. ~/dotfiles/dynamic/venv_auto_activation.ps1
```

**Bash/Zsh**:
```bash
# Check if rc file sources the script
cat ~/.bashrc  # or ~/.zshrc

# Manually source for testing
source ~/dotfiles/dynamic/venv_auto_activation.sh
```

### "python" still points to system Python

**Windows**:
- Close and reopen terminal (PATH changes require new session)
- Verify venv is activated: `$env:VIRTUAL_ENV` should be set

**Linux/Termux**:
- Reload shell: `exec $SHELL` or `source ~/.bashrc`
- Verify: `echo $VIRTUAL_ENV`

### Module import fails with "No module named 'xyz'"

**Cause**: PYTHONPATH not configured or module not installed

**Fix**:
```bash
# Check PYTHONPATH includes modules/
echo $PYTHONPATH  # (Bash/Zsh)
$env:PYTHONPATH   # (PowerShell)

# Should include: /path/to/scripts/modules

# Verify module installed
pip show python_setup
pip show cross_platform

# Reinstall if needed
python setup.py -f  # Force reinstall
```

### Termux-Specific Issues

**uv installation fails**:
```bash
pkg install uv  # Use Termux package, not pip/cargo
```

**Hardlink warnings**:
```bash
# Expected on Android filesystem, can ignore
# Or suppress:
export UV_LINK_MODE=copy
```

**patchelf failures**:
```bash
pkg install patchelf
# Or skip modules that need it
```

## Advanced Usage

### Force Reinstall All Modules

```bash
python setup.py -f -v
```

### Production Mode (Non-Editable Installs)

```bash
python setup.py -p
```

### Fail-Fast Mode (Stop on First Error)

```bash
python setup.py -F
```

### Manual Venv Re-creation

```bash
# Remove existing venv
rm -rf .venv  # (Bash/Zsh)
Remove-Item -Recurse -Force .venv  # (PowerShell)

# Re-run bootstrap
./bootstrap.sh -v
```

### Manually Setup Auto-Activation Only

```bash
setup-venv-activation -D ~/dotfiles -v
```

## Architecture Summary

```
scripts/
├── .venv/                  # Virtual environment (auto-created)
│   ├── Scripts/            # (Windows) or bin/ (Linux)
│   └── Lib/site-packages/  # Installed modules
├── bin/                    # Console script proxies (auto-generated)
│   ├── python-setup.cmd    # (Windows)
│   ├── python-setup        # (Linux/Mac)
│   └── ...
├── modules/                # Python modules (installed in editable mode)
│   ├── python_setup/
│   ├── cross_platform/
│   ├── standard_ui/
│   └── ...
├── setup.py                # Main setup orchestrator
├── bootstrap.sh/.ps1       # Bootstrap script
└── dotfiles/ (separate repo, typically)
    └── dynamic/
        ├── venv_auto_activation.ps1   # PowerShell auto-activation
        ├── venv_auto_activation.sh    # Bash/Zsh auto-activation
        ├── setup_path.zsh             # PATH configuration
        └── setup_modules_pythonpath.zsh  # PYTHONPATH configuration
```

## Best Practices

1. **Always use the venv Python** - the auto-activation ensures this
2. **Run `python setup.py` after cloning** - sets up everything
3. **Re-run setup after adding new modules** - creates proxies
4. **Use `uv` for faster installs** - auto-installed by `python-setup bootstrap`
5. **Keep dotfiles separate** - configure `$DOTFILES` or `$SCRIPTS` env vars
6. **Commit lockfiles** - for reproducible environments (if using Poetry/uv)

## Environment Variables

- `SCRIPTS` - Override default scripts directory (default: `~/scripts` or script location)
- `DOTFILES` - Override default dotfiles directory (default: `~/dotfiles`)
- `SKIP_VENV_BOOTSTRAP` - Set to `1` to skip venv bootstrap (advanced)
- `UV_LINK_MODE=copy` - Suppress hardlink warnings (Termux)
- `SETUP_AUTO_CONFIRM=0` - Disable auto-confirmation on stalls (PowerShell)

## Related Documentation

- `.claude/AGENTS.md` - Claude Code behavior specification
- `CLAUDE.md` - Project memory bank for Claude
- `modules/python_setup/setup.md` - Python setup utilities documentation
