#!/usr/bin/env python3
import argparse
import sys # Import sys for sys.exit
from pathlib import Path
from scripts_setup.alias_utils import parse_alias_file, write_aliases, write_pwsh_aliases # Added write_pwsh_aliases
from scripts_setup.setup_utils import process_symlinks 
from standard_ui.standard_ui import log_info, log_success, log_warning, log_error, section # Added log_error

def ensure_symlinks(scripts_dir: Path, bin_dir: Path, verbose: bool) -> None:
    """Ensures Python scripts from pyscripts_dir are symlinked into bin_dir."""
    with section("PY SCRIPTS SYMLINKS"):
        pyscripts_dir_to_scan = scripts_dir / "pyscripts" 
        log_info(f"Ensuring Python scripts are symlinked from '{pyscripts_dir_to_scan}' to '{bin_dir}' and executable...")
        
        if not pyscripts_dir_to_scan.exists():
            log_warning(f"Source pyscripts directory not found at '{pyscripts_dir_to_scan}'. Skipping symlink creation.")
            return

        try:
            # Corrected call to process_symlinks:
            # - Use 'glob_pattern' argument.
            # - Use 'bin_dir' as the keyword for the target directory.
            # - Expect two return values.
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
            raise # Re-raise to stop this sub-script's execution
        except Exception as e:
            log_error(f"Unexpected error during symlink processing for Python scripts: {e}")
            log_warning("Symlink creation may be incomplete.")
            # Depending on severity, you might want to raise e here too.


def main(scripts_dir: Path, dotfiles_dir: Path, bin_dir: Path, verbose: bool) -> None:
    """Main setup routine for pyscripts."""
    with section("PY SCRIPTS SETUP"):
        alias_definitions_file = scripts_dir / "pyscripts/alias_names.txt"
        
        if not bin_dir.exists():
            log_info(f"Creating bin directory at: {bin_dir}")
            try:
                bin_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                log_error(f"Could not create bin directory {bin_dir}: {e}. Symlinks might fail.")
                return # Stop if bin_dir cannot be created

        try:
            ensure_symlinks(scripts_dir, bin_dir, verbose=verbose)
        except SystemExit: 
            log_error("Halting pyscripts setup due to critical symlink error from ensure_symlinks.")
            return 
        except Exception: # Catch any other exception from ensure_symlinks
            log_error("Halting pyscripts setup due to an unexpected error in ensure_symlinks.")
            return

        parsed_alias_definitions = parse_alias_file(alias_definitions_file)
        if not parsed_alias_definitions:
            log_warning(f"No alias definitions found or parsed from '{alias_definitions_file}'. Skipping alias generation.")
        else:
            log_info(f"Found {len(parsed_alias_definitions)} alias definitions to process from '{alias_definitions_file}'.")

            # --- Zsh/Bash Aliases ---
            with section("Aliases for Python scripts (Zsh/Bash)"):
                alias_config_output_file_zsh = dotfiles_dir / "dynamic/setup_pyscripts_aliases.zsh"
                log_info(f"Zsh/Bash aliases will be written to: {alias_config_output_file_zsh}")
                try:
                    write_aliases(
                        parsed_alias_definitions=parsed_alias_definitions,
                        bin_dir=bin_dir, 
                        alias_config=alias_config_output_file_zsh,
                        alias_file_path_for_header=str(alias_definitions_file),
                        verbose=verbose
                    )
                except Exception as e:
                    log_error(f"Error writing Zsh/Bash aliases for Python scripts: {e}")

            # --- PowerShell Aliases ---
            with section("Aliases for Python scripts (PowerShell)"):
                alias_config_output_file_ps1 = dotfiles_dir / "dynamic/setup_pyscripts_aliases.ps1"
                log_info(f"PowerShell aliases will be written to: {alias_config_output_file_ps1}")
                try:
                    write_pwsh_aliases(
                        parsed_alias_definitions=parsed_alias_definitions,
                        bin_dir=bin_dir,
                        alias_config_ps1=alias_config_output_file_ps1,
                        alias_file_path_for_header=str(alias_definitions_file),
                        verbose=verbose
                    )
                except Exception as e:
                    log_error(f"Error writing PowerShell aliases for Python scripts: {e}")

        log_success("Finished PY SCRIPTS SETUP.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup for Python scripts: symlinks and aliases.")
    parser.add_argument("--scripts-dir", type=Path, required=True, 
                        help="Base directory where all scripts (including pyscripts/) are located.")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, 
                        help="Root directory of dotfiles, for placing generated alias configurations.")
    parser.add_argument("--bin-dir", type=Path, required=True, 
                        help="Target directory for creating symlinks to scripts.")
    parser.add_argument("--verbose", "-v", action="store_true", 
                        help="Enable detailed output during the setup.")
    
    args = parser.parse_args()
    try:
        main(args.scripts_dir, args.dotfiles_dir, args.bin_dir, verbose=args.verbose)
    except Exception as e:
        # This top-level catch ensures the script exits with an error if `main` itself raises an unhandled one.
        # The master setup.py will log this based on return code.
        # Using standard_ui.log_error if it's available and configured.
        # For simplicity, just print to stderr which master setup should capture.
        print(f"FATAL ERROR in pyscripts/setup.py: {e}", file=sys.stderr)
        sys.exit(1)

