#!/usr/bin/env python
import os
import subprocess
from pathlib import Path
import argparse
import sys

# Basic print logging for this script
def log_print(level, message, verbose_flag=False):
    # For this script, let's print ERROR and WARNING always, INFO if verbose_flag
    if level.upper() == "INFO" and not verbose_flag:
        return
    # IMPORTANT messages should always be printed.
    if level.upper() == "IMPORTANT":
        print(f"[{level.upper()}] {message}")
        return
    print(f"[{level.upper()}] {message}")

def _scripts_root() -> Path:
    # This file lives at <scripts>/scripts_setup/setup_path.py
    # scripts root is the parent of scripts_setup
    return Path(__file__).resolve().parents[1]

def _safe_add_with_manager(bin_path_to_add: Path, verbose: bool) -> None:
    """
    Delegate PATH modification to pwsh/pwsh_pathmgr.py with NON-shrinking args.
    This guarantees:
      - backup is created automatically
      - no cleanup/dedupe that could shrink existing PATH
      - registry writes are done via winreg (no setx truncation risks)
    """
    scripts_dir = _scripts_root()
    mgr = scripts_dir / "pwsh" / "pwsh_pathmgr.py"

    if not mgr.is_file():
        log_print("ERROR", f"Safe PATH manager not found at {mgr}. Aborting PATH update to avoid any risk.", verbose_flag=True)
        log_print("INFO", f"Please run manually later: python {scripts_dir / 'pwsh' / 'pwsh_pathmgr.py'} --scope User add \"{bin_path_to_add}\" --no-dedupe", verbose_flag=True)
        return

    cmd = [sys.executable, str(mgr), "--scope", "User", "add", str(bin_path_to_add), "--no-dedupe"]
    if verbose:
        log_print("INFO", f"Running safe PATH add via manager: {' '.join(cmd)}", verbose)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", check=False)
        if proc.stdout and proc.stdout.strip():
            log_print("INFO", f"pwsh_pathmgr output:\n{proc.stdout.strip()}", verbose)
        if proc.stderr and proc.stderr.strip():
            # manager prints warnings/errors to stdout/stderr; surface them
            log_print("WARNING", f"pwsh_pathmgr stderr:\n{proc.stderr.strip()}", verbose)

        if proc.returncode != 0:
            log_print("ERROR", f"pwsh_pathmgr exited with code {proc.returncode}. Not modifying PATH.", verbose_flag=True)
            return

        # Manager prints its own “[ok]”, backups, and diff. We still add an IMPORTANT note.
        log_print("IMPORTANT", "PATH change applies to NEW terminal sessions. Restart your terminal (or pwsh) to pick it up.", verbose_flag=True)
    except Exception as e:
        log_print("ERROR", f"Failed to run pwsh_pathmgr.py safely: {type(e).__name__}: {e}", verbose_flag=True)
        log_print("INFO", f"Please run manually later: python {mgr} --scope User add \"{bin_path_to_add}\" --no-dedupe", verbose_flag=True)

def main():
    parser = argparse.ArgumentParser(
        description="Ensure bin/ directory is in PATH for the appropriate shell."
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        required=True,
        help="Path to the bin/ directory to be added to PATH."
    )
    parser.add_argument(
        "--dotfiles-dir",
        type=Path,
        required=True,
        help="Path to the dotfiles/ directory, used for Zsh configuration."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed output during PATH setup."
    )
    args = parser.parse_args()

    verbose = args.verbose
    bin_path_to_add = args.bin_dir.resolve()
    log_print("INFO", f"Target bin directory: {bin_path_to_add}", verbose)
    log_print("INFO", f"Dotfiles directory: {args.dotfiles_dir}", verbose)

    if os.name == "nt":
        # Windows: delegate to safe PATH manager and DO NOT touch the registry here.
        log_print("INFO", "Windows OS detected. Delegating to safe PATH manager (no direct registry writes).", verbose)
        _safe_add_with_manager(bin_path_to_add, verbose)
        return

    # POSIX-like path update (unchanged, Zsh-focused)
    log_print("INFO", "POSIX-like OS detected for PATH update.", verbose)
    shell_name = os.environ.get("SHELL", "").split("/")[-1]
    log_print("INFO", f"Detected SHELL: {shell_name}", verbose)

    path_separator = os.pathsep
    if "zsh" in shell_name.lower():
        # 1) Ensure <bin_dir> is on PATH via a dedicated dynamic file
        config_file_path = args.dotfiles_dir.resolve() / "dynamic/setup_path.zsh"
        config_file_path.parent.mkdir(parents=True, exist_ok=True)
        path_export_line = f'export PATH="{bin_path_to_add}{path_separator}$PATH"\n'
        write_changes = True
        if config_file_path.exists():
            try:
                if path_export_line in config_file_path.read_text(encoding="utf-8"):
                    log_print("SUCCESS", f"PATH export line for '{bin_path_to_add}' already in {config_file_path}.", verbose)
                    write_changes = False
            except Exception as e_read:
                log_print("WARNING", f"Could not read {config_file_path} to check for existing line: {e_read}", verbose)

        if write_changes:
            try:
                with open(config_file_path, "w", encoding="utf-8") as f:
                    f.write(f"# Added by scripts_setup/setup_path.py\n{path_export_line}")
                log_print("SUCCESS", f"Updated Zsh PATH configuration in: {config_file_path}", verbose)
                log_print("IMPORTANT", f"To apply in current Zsh session, run: source '{config_file_path}'", verbose_flag=True)
            except IOError as e:
                log_print("ERROR", f"Could not write to {config_file_path}: {e}", verbose_flag=True)
                log_print("INFO", f"Please add manually: {path_export_line.strip()}", verbose_flag=True)

        # 2) Ensure the repo-local .venv/bin is also on PATH (idempotent)
        scripts_dir = args.bin_dir.resolve().parent  # bin_dir == <scripts>/bin
        venv_bin = (scripts_dir / ".venv" / "bin").resolve()
        pyenv_zsh_file = args.dotfiles_dir.resolve() / "dynamic" / "python_env.zsh"
        try:
            pyenv_zsh_file.parent.mkdir(parents=True, exist_ok=True)
            line = f'export PATH="{venv_bin}{path_separator}$PATH"\n'
            existing = pyenv_zsh_file.read_text(encoding="utf-8") if pyenv_zsh_file.exists() else ""
            if line not in existing:
                with open(pyenv_zsh_file, "a", encoding="utf-8") as f:
                    if not existing:
                        f.write("# Added by scripts_setup/setup_path.py (repo .venv on PATH)\n")
                    f.write(line)
                log_print("SUCCESS", f"Ensured repo .venv on PATH via {pyenv_zsh_file}", verbose)
            else:
                log_print("SUCCESS", f"Repo .venv already on PATH via {pyenv_zsh_file}", verbose)
            log_print("IMPORTANT", f"To apply now: source '{pyenv_zsh_file}'", verbose_flag=True)
        except Exception as e:
            log_print("WARNING", f"Could not update python_env.zsh: {e}", verbose)

    else:
        log_print("WARNING", f"Unsupported shell '{shell_name}' for automatic PATH config. This script primarily handles Zsh for POSIX.", verbose_flag=True)
        log_print("INFO", f"Please add '{str(bin_path_to_add)}' and the repo '.venv/bin' to your PATH manually for shell '{shell_name}'.", verbose_flag=True)

if __name__ == "__main__":
    main()

