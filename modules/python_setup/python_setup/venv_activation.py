#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
venv_activation.py

Sets up automatic virtual environment activation when entering directories with .venv folders.
Supports PowerShell, Bash, and Zsh.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from cross_platform.system_utils import SystemUtils
except Exception:
    # Minimal fallback if cross_platform not available
    class SystemUtils:  # type: ignore
        @staticmethod
        def is_windows() -> bool:
            return os.name == "nt"

        @staticmethod
        def is_linux() -> bool:
            return sys.platform.startswith("linux")


POWERSHELL_AUTO_VENV = r'''# Auto-activate Python venv when entering directories with .venv
# Added by python_setup/venv_activation.py

# Store the currently active venv path for comparison
$global:_PREV_VENV = $null

function _Auto_Activate_Venv {
    $venvPath = Join-Path $PWD ".venv"
    $activateScript = if ($IsWindows -or ($PSVersionTable.PSVersion.Major -lt 6)) {
        Join-Path $venvPath "Scripts\Activate.ps1"
    } else {
        Join-Path $venvPath "bin\Activate.ps1"
    }

    # Check if we're in a directory with .venv
    if (Test-Path $venvPath -PathType Container) {
        if (Test-Path $activateScript) {
            # Only activate if not already active or if it's a different venv
            if ($global:_PREV_VENV -ne $venvPath) {
                # Deactivate current venv if any
                if ($null -ne $env:VIRTUAL_ENV -and (Get-Command deactivate -ErrorAction SilentlyContinue)) {
                    deactivate
                }
                # Activate the new venv
                & $activateScript
                $global:_PREV_VENV = $venvPath
            }
        }
    } else {
        # Not in a venv directory - deactivate if we have an active one from auto-activation
        if ($null -ne $global:_PREV_VENV -and $null -ne $env:VIRTUAL_ENV) {
            if ((Get-Command deactivate -ErrorAction SilentlyContinue)) {
                deactivate
            }
            $global:_PREV_VENV = $null
        }
    }
}

# Hook into prompt to check on every directory change
# Preserve existing prompt if it exists
if (Get-Command prompt -ErrorAction SilentlyContinue) {
    $global:_Original_Prompt = ${function:prompt}
    function global:prompt {
        _Auto_Activate_Venv
        & $global:_Original_Prompt
    }
} else {
    function global:prompt {
        _Auto_Activate_Venv
        "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) "
    }
}
'''


BASH_ZSH_AUTO_VENV = '''# Auto-activate Python venv when entering directories with .venv
# Added by python_setup/venv_activation.py

# Store currently active venv path
_PREV_VENV=""

_auto_activate_venv() {
    local venv_path="$PWD/.venv"
    local activate_script="$venv_path/bin/activate"

    # Check if we're in a directory with .venv
    if [[ -d "$venv_path" ]] && [[ -f "$activate_script" ]]; then
        # Only activate if not already active or if it's a different venv
        if [[ "$_PREV_VENV" != "$venv_path" ]]; then
            # Deactivate current venv if any
            if [[ -n "$VIRTUAL_ENV" ]] && type deactivate &>/dev/null; then
                deactivate
            fi
            # Activate the new venv
            source "$activate_script"
            _PREV_VENV="$venv_path"
        fi
    else
        # Not in a venv directory - deactivate if we have an active one from auto-activation
        if [[ -n "$_PREV_VENV" ]] && [[ -n "$VIRTUAL_ENV" ]]; then
            if type deactivate &>/dev/null; then
                deactivate
            fi
            _PREV_VENV=""
        fi
    fi
}

# Hook into cd command
cd() {
    builtin cd "$@" || return
    _auto_activate_venv
}

# Also run on shell startup
_auto_activate_venv
'''


def setup_powershell_auto_activation(dotfiles_dir: Path, verbose: bool = False) -> bool:
    """
    Write PowerShell auto-activation snippet to dotfiles/dynamic/venv_auto_activation.ps1
    Returns True if file was written/updated, False otherwise.
    """
    output_dir = dotfiles_dir / "dynamic"
    output_file = output_dir / "venv_auto_activation.ps1"

    output_dir.mkdir(parents=True, exist_ok=True)

    if output_file.exists():
        existing = output_file.read_text(encoding="utf-8")
        if existing.strip() == POWERSHELL_AUTO_VENV.strip():
            if verbose:
                print(f"[INFO] PowerShell auto-activation already configured in {output_file}")
            return False

    output_file.write_text(POWERSHELL_AUTO_VENV, encoding="utf-8")
    if verbose:
        print(f"[SUCCESS] Wrote PowerShell auto-activation to {output_file}")

    return True


def setup_bash_zsh_auto_activation(dotfiles_dir: Path, verbose: bool = False) -> bool:
    """
    Write Bash/Zsh auto-activation snippet to dotfiles/dynamic/venv_auto_activation.sh
    Returns True if file was written/updated, False otherwise.
    """
    output_dir = dotfiles_dir / "dynamic"
    output_file = output_dir / "venv_auto_activation.sh"

    output_dir.mkdir(parents=True, exist_ok=True)

    if output_file.exists():
        existing = output_file.read_text(encoding="utf-8")
        if existing.strip() == BASH_ZSH_AUTO_VENV.strip():
            if verbose:
                print(f"[INFO] Bash/Zsh auto-activation already configured in {output_file}")
            return False

    output_file.write_text(BASH_ZSH_AUTO_VENV, encoding="utf-8")
    if verbose:
        print(f"[SUCCESS] Wrote Bash/Zsh auto-activation to {output_file}")

    return True


def setup_auto_activation(dotfiles_dir: Path | str, verbose: bool = False) -> tuple[bool, bool]:
    """
    Setup automatic venv activation for all supported shells.
    Returns (powershell_changed, bash_zsh_changed)
    """
    dotfiles_path = Path(dotfiles_dir) if isinstance(dotfiles_dir, str) else dotfiles_dir
    su = SystemUtils()

    ps_changed = False
    bash_changed = False

    if su.is_windows():
        ps_changed = setup_powershell_auto_activation(dotfiles_path, verbose)
        if verbose:
            print("[INFO] To enable PowerShell auto-activation, ensure your profile sources:")
            print(f"       . {dotfiles_path / 'dynamic' / 'venv_auto_activation.ps1'}")

    # On Windows with WSL or Cygwin, or on pure Linux, setup bash/zsh
    if su.is_linux() or su.is_windows():  # Windows users might use bash via WSL/Git Bash/Cygwin
        bash_changed = setup_bash_zsh_auto_activation(dotfiles_path, verbose)
        if verbose:
            print("[INFO] To enable Bash/Zsh auto-activation, ensure your shell rc sources:")
            print(f"       source {dotfiles_path / 'dynamic' / 'venv_auto_activation.sh'}")

    return ps_changed, bash_changed


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for venv auto-activation setup."""
    import argparse

    try:
        from argparse_enforcer.enforcer import EnforcedArgumentParser as Parser
    except Exception:
        Parser = argparse.ArgumentParser  # type: ignore

    p = Parser(description="Setup automatic Python venv activation for directories with .venv")
    p.add_argument(
        "-D", "--dotfiles-dir",
        type=Path,
        required=True,
        help="Root directory of dotfiles (where dynamic/ configs are stored)"
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = p.parse_args(argv)

    ps_changed, bash_changed = setup_auto_activation(args.dotfiles_dir, args.verbose)

    if ps_changed or bash_changed:
        print("[SUCCESS] Auto-activation configured. Restart your shell or source the config files.")
    else:
        print("[OK] Auto-activation already configured.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
