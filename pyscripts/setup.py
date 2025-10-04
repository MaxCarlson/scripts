#!/usr/bin/env python3
import argparse
import sys
import os
from pathlib import Path

from scripts_setup.definition_utils import (
    parse_definitions_file,
    write_definitions,
    write_definitions_powershell,  # NEW: emit PS1 aliases/functions too
)
from scripts_setup.setup_utils import (
    process_symlinks,  # kept for reference, not used for final wrappers
)
from standard_ui.standard_ui import (
    log_info,
    log_success,
    log_warning,
    log_error,
    section,
)


def _write_text_if_changed(path: Path, content: str, verbose: bool) -> bool:
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                if verbose:
                    log_info(f"No changes for wrapper: {path}")
                return False
    except Exception:
        pass
    path.write_text(content, encoding="utf-8", newline="\n")
    try:
        path.chmod(0o755)
    except Exception:
        pass
    if verbose:
        log_success(f"Wrote wrapper: {path}")
    return True


def _make_posix_wrapper(bin_dir: Path, script_path: Path, verbose: bool) -> None:
    name = script_path.stem
    wrapper = bin_dir / name
    # Replace symlink if it exists to ensure we control interpreter
    if wrapper.exists() or wrapper.is_symlink():
        try:
            wrapper.unlink()
        except Exception:
            pass
    content = f"""#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
VENV_PY="$DIR/../.venv/bin/python"
TARGET="{script_path.resolve()}"
if [ -x "$VENV_PY" ]; then
  if "$VENV_PY" - <<'PY'
import sys
try:
    import rich  # sanity check common dependency
except Exception:
    sys.exit(1)
sys.exit(0)
PY
  then
    exec "$VENV_PY" "$TARGET" "$@"
  fi
fi
exec python3 "$TARGET" "$@"
"""
    _write_text_if_changed(wrapper, content, verbose)


def _make_windows_wrapper(bin_dir: Path, script_path: Path, verbose: bool) -> None:
    name = script_path.stem
    wrapper = bin_dir / f"{name}.cmd"
    # Best-effort overwrite
    if wrapper.exists() or wrapper.is_symlink():
        try:
            wrapper.unlink()
        except Exception:
            pass
    py_abs = (bin_dir.parent / ".venv" / "Scripts" / "python.exe").resolve()
    script_abs = script_path.resolve()
    content = (
        "@echo off\r\n"
        "setlocal\r\n"
        f"set \"_VENV_PY={str(py_abs).replace('/', '\\')}\"\r\n"
        f"set \"_SCRIPT={str(script_abs).replace('/', '\\')}\"\r\n"
        "if exist \"%_VENV_PY%\" ( \r\n"
        "  \"%_VENV_PY%\" \"%_SCRIPT%\" %*\r\n"
        "  exit /b %ERRORLEVEL%\r\n"
        ")\r\n"
        "python \"%_SCRIPT%\" %*\r\n"
    )
    wrapper.write_text(content, encoding="utf-8", newline="\r\n")
    if verbose:
        log_success(f"Wrote wrapper: {wrapper}")


def ensure_symlinks(scripts_dir: Path, bin_dir: Path, verbose: bool) -> None:
    """Ensure Python scripts are invocable via repo venv by writing wrappers in bin/."""
    with section("PY SCRIPTS SYMLINKS"):
        pyscripts_dir_to_scan = scripts_dir / "pyscripts"
        log_info(
            f"Ensuring Python script wrappers exist in '{bin_dir}' for scripts in '{pyscripts_dir_to_scan}'"
        )

        if not pyscripts_dir_to_scan.exists():
            log_warning(
                f"Source pyscripts directory not found at '{pyscripts_dir_to_scan}'. Skipping wrapper creation."
            )
            return

        created = 0
        unchanged = 0
        for file_path in sorted(pyscripts_dir_to_scan.glob("*.py")):
            if file_path.name == "setup.py":
                continue
            if os.name == "nt":
                _make_windows_wrapper(bin_dir, file_path, verbose)
                created += 1
            else:
                # Ensure we replace any existing symlink with a file wrapper
                _make_posix_wrapper(bin_dir, file_path, verbose)
                created += 1
        log_info(f"Python script wrappers: {created} created/updated, {unchanged} unchanged.")


def main(scripts_dir: Path, dotfiles_dir: Path, bin_dir: Path, verbose: bool) -> None:
    """Main setup routine for pyscripts, handling symlinks, aliases, and functions."""
    with section("PY SCRIPTS SETUP"):
        if not bin_dir.exists():
            log_info(f"Creating bin directory at: {bin_dir}")
            try:
                bin_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                log_error(
                    f"Could not create bin directory {bin_dir}: {e}. Sub-tasks might fail."
                )
                return

        try:
            ensure_symlinks(scripts_dir, bin_dir, verbose=verbose)
        except SystemExit:
            log_error("Halting pyscripts setup due to critical symlink error.")
            return
        except Exception as e:
            log_error(
                f"Halting pyscripts setup due to an unexpected error in ensure_symlinks: {e}"
            )
            return

        # --- Process Definitions ---
        definitions_file = scripts_dir / "pyscripts/alias_and_func_defs.txt"
        aliases, functions = parse_definitions_file(definitions_file)

        if not aliases and not functions:
            log_warning(
                f"No definitions found or parsed from '{definitions_file}'. Skipping generation."
            )
        else:
            log_info(
                f"Found {len(aliases)} alias and {len(functions)} function definitions to process."
            )

            # Zsh/Bash aliases
            if aliases:
                with section("ALIASES FOR PYTHON SCRIPTS (ZSH/BASH)"):
                    alias_config_zsh = dotfiles_dir / "dynamic" / "setup_pyscripts_aliases.zsh"
                    log_info(f"Zsh/Bash aliases will be written to: {alias_config_zsh}")
                    try:
                        write_definitions(
                            aliases,
                            bin_dir,
                            alias_config_zsh,
                            str(definitions_file),
                            "alias",
                            verbose,
                        )
                    except Exception as e:
                        log_error(f"Error writing Zsh/Bash aliases: {e}")

                # PowerShell aliases (NEW)
                with section("ALIASES FOR PYTHON SCRIPTS (POWERSHELL)"):
                    alias_config_ps1 = dotfiles_dir / "dynamic" / "setup_pyscripts_aliases.ps1"
                    log_info(f"PowerShell aliases will be written to: {alias_config_ps1}")
                    try:
                        write_definitions_powershell(
                            aliases,
                            bin_dir,
                            alias_config_ps1,
                            str(definitions_file),
                            "alias",
                            verbose,
                        )
                    except Exception as e:
                        log_error(f"Error writing PowerShell aliases: {e}")

            # Zsh/Bash functions
            if functions:
                with section("SHELL FUNCTIONS (ZSH/BASH)"):
                    functions_output_file = dotfiles_dir / "dynamic" / "setup_pyscripts_functions.zsh"
                    log_info(
                        f"Shell functions will be written to: {functions_output_file}"
                    )
                    try:
                        write_definitions(
                            functions,
                            bin_dir,
                            functions_output_file,
                            str(definitions_file),
                            "func",
                            verbose,
                        )
                    except Exception as e:
                        log_error(f"Error writing shell functions: {e}")

                # PowerShell functions (NEW)
                with section("SHELL FUNCTIONS (POWERSHELL)"):
                    functions_output_ps1 = dotfiles_dir / "dynamic" / "setup_pyscripts_functions.ps1"
                    log_info(
                        f"PowerShell functions will be written to: {functions_output_ps1}"
                    )
                    try:
                        write_definitions_powershell(
                            functions,
                            bin_dir,
                            functions_output_ps1,
                            str(definitions_file),
                            "func",
                            verbose,
                        )
                    except Exception as e:
                        log_error(f"Error writing PowerShell functions: {e}")

        log_success("Finished PY SCRIPTS SETUP.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Setup for Python scripts: symlinks, aliases, and functions."
    )
    parser.add_argument(
        "--scripts-dir",
        type=Path,
        required=True,
        help="Base directory where all scripts (including pyscripts/) are located.",
    )
    parser.add_argument(
        "--dotfiles-dir",
        type=Path,
        required=True,
        help="Root directory of dotfiles, for placing generated alias/function configurations.",
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        required=True,
        help="Target directory for creating symlinks to scripts.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed output during the setup.",
    )
    # Add these arguments to avoid 'unrecognized arguments' error from master setup.py
    parser.add_argument(
        "--skip-reinstall", action="store_true", help=argparse.SUPPRESS
    )  # Suppress from help output as it's not directly used here
    parser.add_argument(
        "--production", action="store_true", help=argparse.SUPPRESS
    )  # Suppress from help output

    args = parser.parse_args()
    try:
        main(args.scripts_dir, args.dotfiles_dir, args.bin_dir, verbose=args.verbose)
    except Exception as e:
        print(f"FATAL ERROR in pyscripts/setup.py: {e}", file=sys.stderr)
        sys.exit(1)
