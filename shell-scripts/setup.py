#!/usr/bin/env python3
import argparse
import sys 
from pathlib import Path
from scripts_setup.definition_utils import parse_definitions_file, write_definitions
from scripts_setup.setup_utils import process_symlinks 
from standard_ui.standard_ui import log_info, log_warning, log_success, log_error, section

def ensure_shell_script_symlinks(scripts_dir: Path, bin_dir: Path, verbose: bool) -> None:
    """Ensures shell scripts from shell-scripts/ are symlinked into bin_dir."""
    with section("SHELL SCRIPTS SYMLINKS"):
        shell_scripts_source_dir = scripts_dir / "shell-scripts"
        log_info(f"Ensuring shell scripts are symlinked from '{shell_scripts_source_dir}' to '{bin_dir}' and executable...")

        if not shell_scripts_source_dir.exists():
            log_warning(f"Source shell-scripts directory not found at '{shell_scripts_source_dir}'. Skipping symlink creation.")
            return
        
        try:
            created_count, existing_count = process_symlinks(
                source_dir=shell_scripts_source_dir,
                glob_pattern="*.sh", 
                bin_dir=bin_dir,
                verbose=verbose,
                skip_names=["setup.py"] 
            )
            log_info(f"Shell script symlinks: {created_count} created/updated, {existing_count} already correct.")
        except SystemExit:
            log_error("Critical error during symlink processing for shell scripts (aborted by symlink utility).")
            raise
        except Exception as e:
            log_error(f"Unexpected error during symlink processing for shell scripts: {e}")
            log_warning("Symlink creation may be incomplete.")


def main(scripts_dir: Path, dotfiles_dir: Path, bin_dir: Path, verbose: bool) -> None:
    """Main setup routine for shell scripts."""
    with section("SHELL SCRIPTS SETUP"):
        definitions_file = scripts_dir / "pyscripts/alias_and_func_defs.txt"
        alias_config_output_file = dotfiles_dir / "dynamic/setup_shell_scripts_aliases.zsh" 

        if not bin_dir.exists():
            log_info(f"Creating bin directory at: {bin_dir}")
            try:
                bin_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                log_error(f"Could not create bin directory {bin_dir}: {e}.")
                return

        try:
            ensure_shell_script_symlinks(scripts_dir, bin_dir, verbose=verbose)
        except SystemExit:
            log_error("Halting shell-scripts setup due to critical symlink error from ensure_shell_script_symlinks.")
            return
        except Exception:
            log_error("Halting shell-scripts setup due to an unexpected error in ensure_shell_script_symlinks.")
            return


        with section("Aliases for Shell Scripts"):
            log_info(f"Processing alias definitions from: {definitions_file}")
            log_info(f"Aliases will be written to: {alias_config_output_file}")

            aliases, _ = parse_definitions_file(definitions_file)
            shell_aliases = [d for d in aliases if d['script'].endswith('.sh')]

            if not shell_aliases:
                log_warning(f"No shell script alias definitions found or parsed from '{definitions_file}'.")
            else:
                log_info(f"Found {len(shell_aliases)} shell alias definitions to process.")
            
            try:
                write_definitions(
                    definitions=shell_aliases,
                    bin_dir=bin_dir,
                    output_file=alias_config_output_file, 
                    source_file_path=str(definitions_file),
                    def_type='alias',
                    verbose=verbose 
                )
            except Exception as e:
                log_error(f"Error writing aliases for shell scripts: {e}")

        log_success("Finished SHELL SCRIPTS SETUP.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup for shell scripts: symlinks and aliases.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Path to the scripts directory")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Path to the dotfiles directory")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Path to the bin directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    # Add these arguments to avoid 'unrecognized arguments' error from master setup.py
    parser.add_argument("--skip-reinstall", action="store_true", 
                        help=argparse.SUPPRESS) # Suppress from help output as it's not directly used here
    parser.add_argument("--production", action="store_true", 
                        help=argparse.SUPPRESS) # Suppress from help output
    
    args = parser.parse_args()
    try:
        main(args.scripts_dir, args.dotfiles_dir, args.bin_dir, verbose=args.verbose)
    except Exception as e:
        print(f"FATAL ERROR in shell-scripts/setup.py: {e}", file=sys.stderr)
        sys.exit(1)
