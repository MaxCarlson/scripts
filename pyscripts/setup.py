#!/usr/bin/env python3
import argparse
from pathlib import Path
from scripts_setup.alias_utils import parse_alias_file, write_aliases
from scripts_setup.setup_utils import process_symlinks

def ensure_symlinks(scripts_dir: Path, bin_dir: Path, verbose: bool) -> None:
    print("========== Starting PY SCRIPTS SYMLINKS ==========")
    pyscripts_dir = scripts_dir / "pyscripts"
    if not pyscripts_dir.exists():
        print(f"⚠️ No pyscripts directory found at {pyscripts_dir}. Skipping symlink creation.")
    else:
        created, existing = process_symlinks(pyscripts_dir, "*.py", bin_dir, verbose=verbose, skip_names=["setup.py"])
        if not verbose:
            print(f"Python scripts: {created} created, {existing} already existed.")
    print("========== Finished PY SCRIPTS SYMLINKS ==========\n")

def main(scripts_dir: Path, dotfiles_dir: Path, bin_dir: Path, verbose: bool) -> None:
    print("\n========== Starting PY SCRIPTS SETUP ==========")
    alias_file = scripts_dir / "pyscripts/alias_names.txt"
    alias_config = dotfiles_dir / "dynamic/setup_pyscripts.zsh"

    if not bin_dir.exists():
        bin_dir.mkdir(parents=True, exist_ok=True)

    ensure_symlinks(scripts_dir, bin_dir, verbose=verbose)
    print("---------- Aliases for Python scripts ----------")
    aliases = parse_alias_file(alias_file)
    write_aliases(aliases, bin_dir, alias_config, ext=".py", verbose=verbose)
    print("========== Finished PY SCRIPTS SETUP ==========\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup pyscripts and manage aliases.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Path to the scripts directory")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Path to the dotfiles directory")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Path to the bin directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()
    main(args.scripts_dir, args.dotfiles_dir, args.bin_dir, verbose=args.verbose)
