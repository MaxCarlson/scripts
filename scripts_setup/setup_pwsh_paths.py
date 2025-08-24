#!/usr/bin/env python3
"""
setup_pwsh_paths.py

Thin orchestrator to ensure Windows PowerShell can find your scripts by adding
<scripts>/pyscripts (and optionally <scripts>/bin) to the *User* PATH.

This delegates the actual PATH manipulation to scripts_setup/setup_path.py so we
reuse one source of truth for PATH edits. On non-Windows OS, this script exits
cleanly after a short info message.

Usage examples:
    python scripts_setup/setup_pwsh_paths.py --scripts-dir <abs path to repo> --dotfiles-dir <abs path> -v
    python scripts_setup/setup_pwsh_paths.py --scripts-dir . --dotfiles-dir ~/dotfiles --include-bin
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Basic print logging (aligned with scripts_setup/setup_path.py style)
def log_print(level: str, message: str, verbose_flag: bool = False):
    if level.upper() == "INFO" and not verbose_flag:
        return
    if level.upper() == "IMPORTANT":
        print(f"[{level.upper()}] {message}")
        return
    print(f"[{level.upper()}] {message}")

def run_setup_path(bin_dir: Path, dotfiles_dir: Path, verbose: bool) -> int:
    """
    Call scripts_setup/setup_path.py to add 'bin_dir' to PATH.
    Returns the subprocess return code.
    """
    setup_path_script = Path(__file__).resolve().parent / "setup_path.py"
    if not setup_path_script.exists():
        log_print("ERROR", f"Expected helper script not found: {setup_path_script}", True)
        return 1

    args = [
        sys.executable,
        str(setup_path_script),
        "--bin-dir", str(bin_dir.resolve()),
        "--dotfiles-dir", str(dotfiles_dir.resolve())
    ]
    if verbose:
        args.append("--verbose")

    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    # Forward output in a friendly way (setup.py will capture our stdout/stderr)
    if proc.stdout and proc.stdout.strip():
        log_print("INFO", f"setup_path.py stdout:\n{proc.stdout.strip()}", verbose)
    if proc.stderr and proc.stderr.strip():
        # These may be informational warnings; surface them
        log_print("WARNING", f"setup_path.py stderr:\n{proc.stderr.strip()}", True)
    if proc.returncode != 0:
        log_print("ERROR", f"setup_path.py failed (rc: {proc.returncode})", True)
    return proc.returncode

def main():
    parser = argparse.ArgumentParser(
        description="Windows-only helper to add <scripts>/pyscripts (and optionally <scripts>/bin) to User PATH using setup_path.py."
    )
    parser.add_argument("--scripts-dir", type=Path, required=True,
                        help="Root of the scripts repo (containing 'pyscripts' and 'bin').")
    parser.add_argument("--dotfiles-dir", type=Path, required=True,
                        help="Dotfiles root (for parity with setup_path.py; unused on Windows beyond logging).")
    parser.add_argument("--include-bin", action="store_true",
                        help="Also add <scripts>/bin to PATH (optional; usually already handled elsewhere).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable detailed output.")
    args = parser.parse_args()

    verbose = args.verbose
    scripts_dir = args.scripts_dir.resolve()

    if os.name != "nt":
        log_print("INFO", "Non-Windows OS detected. This step is only relevant for Windows PowerShell; skipping.", verbose)
        return 0

    # Validate directories
    pyscripts_dir = scripts_dir / "pyscripts"
    if not pyscripts_dir.is_dir():
        log_print("WARNING", f"Missing directory: {pyscripts_dir}. Nothing to add.", True)
        return 0

    # 1) Ensure <scripts>/pyscripts is in PATH
    log_print("INFO", f"Adding to PATH (User): {pyscripts_dir}", verbose)
    rc = run_setup_path(pyscripts_dir, args.dotfiles_dir, verbose)
    if rc != 0:
        return rc

    # 2) Optionally ensure <scripts>/bin is in PATH (nice to have, but may already be handled)
    if args.include_bin:
        bin_dir = scripts_dir / "bin"
        if bin_dir.is_dir():
            log_print("INFO", f"Adding to PATH (User): {bin_dir}", verbose)
            rc2 = run_setup_path(bin_dir, args.dotfiles_dir, verbose)
            if rc2 != 0:
                return rc2
        else:
            log_print("WARNING", f"Requested --include-bin but directory not found: {bin_dir}", True)

    # Friendly reminder
    log_print("IMPORTANT", "PATH change applies to NEW terminal sessions. Restart your terminal (or pwsh) to pick it up.", True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
