#!/usr/bin/env python3
import argparse
from pathlib import Path
from scripts_setup.alias_utils import parse_alias_file, write_aliases
from scripts_setup.setup_utils import process_symlinks
from standard_ui.standard_ui import log_info, log_warning, log_success, section

def main(scripts_dir: Path, dotfiles_dir: Path, bin_dir: Path, verbose: bool) -> None:
    with section("Starting SHELL SCRIPTS SETUP"):
        # Derive shell-scripts directory from provided scripts_dir.
        shell_scripts_dir = scripts_dir / "shell-scripts"
        alias_file = shell_scripts_dir / "alias_names.txt"
        alias_config = dotfiles_dir / "dynamic/setup_shell_scripts.zsh"

        with section("Processing Shell Script Symlinks"):
            if not shell_scripts_dir.exists():
                log_warning(f"No shell scripts directory found at {shell_scripts_dir}. Skipping symlink creation.")
            else:
                created, existing = process_symlinks(shell_scripts_dir, "*.sh", bin_dir, verbose=verbose)
                if not verbose:
                    log_info(f"Shell scripts: {created} created, {existing} already existed.")

        with section("Aliases for Shell Scripts"):
            log_info("Processing aliases for shell scripts...")
            aliases = parse_alias_file(alias_file)
            write_aliases(aliases, bin_dir, alias_config, ext=".sh", verbose=verbose)
        log_success("Finished SHELL SCRIPTS SETUP.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup shell scripts and manage aliases.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Path to the scripts directory")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Path to the dotfiles directory")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Path to the bin directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()
    main(args.scripts_dir, args.dotfiles_dir, args.bin_dir, verbose=args.verbose)
