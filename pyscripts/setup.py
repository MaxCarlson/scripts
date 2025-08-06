#!/usr/bin/env python3
import argparse
import sys 
from pathlib import Path
from scripts_setup.alias_utils import parse_alias_file, write_aliases, write_pwsh_aliases
from scripts_setup.function_utils import parse_functions_file, write_functions
from scripts_setup.setup_utils import process_symlinks 
from standard_ui.standard_ui import log_info, log_success, log_warning, log_error, section

def ensure_symlinks(scripts_dir: Path, bin_dir: Path, verbose: bool) -> None:
    """Ensures Python scripts from pyscripts_dir are symlinked into bin_dir."""
    with section("PY SCRIPTS SYMLINKS"):
        pyscripts_dir_to_scan = scripts_dir / "pyscripts" 
        log_info(f"Ensuring Python scripts are symlinked from '{pyscripts_dir_to_scan}' to '{bin_dir}' and executable...")
        
        if not pyscripts_dir_to_scan.exists():
            log_warning(f"Source pyscripts directory not found at '{pyscripts_dir_to_scan}'. Skipping symlink creation.")
            return

        try:
            created_count, existing_count = process_symlinks(
                source_dir=pyscripts_dir_to_scan,
                glob_pattern="*.py", 
                bin_dir=bin_dir,     
                verbose=verbose,
                skip_names=["setup.py"] 
            )
            log_info(f"Python script symlinks: {created_count} created/updated, {existing_count} already correct.")

        except SystemExit: 
            log_error("Critical error during symlink processing for Python scripts (aborted by symlink utility).")
            raise 
        except Exception as e:
            log_error(f"Unexpected error during symlink processing for Python scripts: {e}")
            log_warning("Symlink creation may be incomplete.")


def main(scripts_dir: Path, dotfiles_dir: Path, bin_dir: Path, verbose: bool) -> None:
    """Main setup routine for pyscripts, handling symlinks, aliases, and functions."""
    with section("PY SCRIPTS SETUP"):
        if not bin_dir.exists():
            log_info(f"Creating bin directory at: {bin_dir}")
            try:
                bin_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                log_error(f"Could not create bin directory {bin_dir}: {e}. Sub-tasks might fail.")
                return 

        try:
            ensure_symlinks(scripts_dir, bin_dir, verbose=verbose)
        except SystemExit: 
            log_error("Halting pyscripts setup due to critical symlink error.")
            return 
        except Exception: 
            log_error("Halting pyscripts setup due to an unexpected error in ensure_symlinks.")
            return

        # --- Process Aliases ---
        alias_definitions_file = scripts_dir / "pyscripts/alias_names.txt"
        parsed_alias_definitions = parse_alias_file(alias_definitions_file)
        if not parsed_alias_definitions:
            log_warning(f"No alias definitions found or parsed from '{alias_definitions_file}'. Skipping alias generation.")
        else:
            log_info(f"Found {len(parsed_alias_definitions)} alias definitions to process.")
            with section("ALIASES FOR PYTHON SCRIPTS (ZSH/BASH)"):
                alias_config_zsh = dotfiles_dir / "dynamic/setup_pyscripts_aliases.zsh"
                log_info(f"Zsh/Bash aliases will be written to: {alias_config_zsh}")
                try:
                    write_aliases(parsed_alias_definitions, bin_dir, alias_config_zsh, str(alias_definitions_file), verbose)
                except Exception as e:
                    log_error(f"Error writing Zsh/Bash aliases: {e}")

            with section("ALIASES FOR PYTHON SCRIPTS (POWERSHELL)"):
                alias_config_ps1 = dotfiles_dir / "dynamic/setup_pyscripts_aliases.ps1"
                log_info(f"PowerShell aliases will be written to: {alias_config_ps1}")
                try:
                    write_pwsh_aliases(parsed_alias_definitions, bin_dir, alias_config_ps1, str(alias_definitions_file), verbose)
                except Exception as e:
                    log_error(f"Error writing PowerShell aliases: {e}")

        # --- Process Functions ---
        function_definitions_file = scripts_dir / "pyscripts/function_names.txt"
        parsed_functions = parse_functions_file(function_definitions_file)
        if not parsed_functions:
            log_warning(f"No function definitions found or parsed from '{function_definitions_file}'. Skipping function generation.")
        else:
            log_info(f"Found {len(parsed_functions)} function definitions to process.")
            with section("SHELL FUNCTIONS (ZSH/BASH)"):
                functions_output_file = dotfiles_dir / "dynamic/setup_pyscripts_functions.zsh"
                log_info(f"Shell functions will be written to: {functions_output_file}")
                try:
                    write_functions(parsed_functions, bin_dir, functions_output_file, str(function_definitions_file), verbose)
                except Exception as e:
                    log_error(f"Error writing shell functions: {e}")

        log_success("Finished PY SCRIPTS SETUP.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup for Python scripts: symlinks, aliases, and functions.")
    parser.add_argument("--scripts-dir", type=Path, required=True, 
                        help="Base directory where all scripts (including pyscripts/) are located.")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, 
                        help="Root directory of dotfiles, for placing generated alias/function configurations.")
    parser.add_argument("--bin-dir", type=Path, required=True, 
                        help="Target directory for creating symlinks to scripts.")
    parser.add_argument("--verbose", "-v", action="store_true", 
                        help="Enable detailed output during the setup.")
    # Add these arguments to avoid 'unrecognized arguments' error from master setup.py
    parser.add_argument("--skip-reinstall", action="store_true", 
                        help=argparse.SUPPRESS) # Suppress from help output as it's not directly used here
    parser.add_argument("--production", action="store_true", 
                        help=argparse.SUPPRESS) # Suppress from help output
    
    args = parser.parse_args()
    try:
        main(args.scripts_dir, args.dotfiles_dir, args.bin_dir, verbose=args.verbose)
    except Exception as e:
        print(f"FATAL ERROR in pyscripts/setup.py: {e}", file=sys.stderr)
        sys.exit(1)
