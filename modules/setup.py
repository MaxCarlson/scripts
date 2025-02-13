#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from pathlib import Path
from scripts_setup import setup_utils  # existing utilities
from standard_ui.standard_ui import log_info, log_warning, log_error, log_success, section

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def get_module_install_mode(module_path: Path) -> str:
    module_name = module_path.name
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=freeze"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if " @ " in line:
            name = line.split(" @ ")[0].strip()
            if name.lower() == module_name.lower():
                return "editable"
        elif "==" in line:
            name = line.split("==")[0].strip()
            if name.lower() == module_name.lower():
                return "normal"
    return None

def is_module_installed(module_path: Path) -> bool:
    return get_module_install_mode(module_path) is not None

def install_python_modules(modules_dir: Path, skip_reinstall: bool, production: bool, verbose: bool) -> None:
    if not modules_dir.exists():
        log_warning(f"No 'modules' directory found at {modules_dir}. Skipping installation.")
        return

    log_info(f"Scanning for modules inside: {modules_dir}")
    found_any = False

    for module in modules_dir.iterdir():
        if not module.is_dir():
            log_warning(f"Skipping {module}, not a directory.")
            continue

        setup_py = module / "setup.py"
        pyproject_toml = module / "pyproject.toml"
        if not setup_py.exists() and not pyproject_toml.exists():
            log_warning(f"Skipping {module.name}, no setup.py or pyproject.toml found.")
            continue

        found_any = True

        install_cmd = [sys.executable, "-m", "pip", "install"]
        if not production:
            install_cmd.append("-e")  # Editable mode
        install_cmd.append(str(module))

        if skip_reinstall:
            installed_mode = get_module_install_mode(module)
            desired_mode = "editable" if not production else "normal"
            if installed_mode == desired_mode:
                log_info(f"⏭ Module already installed ({installed_mode}): {module.name}. Skipping.")
                continue

        mode_text = "(production mode)" if production else "(development mode)"
        if verbose:
            log_info(f"Installing: {module.name} {mode_text}")
        else:
            sys.stdout.write(f"Installing: {module.name} {mode_text}... ")
            sys.stdout.flush()

        try:
            if verbose:
                subprocess.run(install_cmd, check=True)
                log_success("✅")
            else:
                result = subprocess.run(install_cmd, check=True,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE,
                                          text=True)
                sys.stdout.write(f"{GREEN}✅{RESET}\n")
        except subprocess.CalledProcessError as e:
            if verbose:
                log_error(f"Failed to install {module.name}:")
                log_error(e.stderr)
            else:
                sys.stdout.write(f"{RED}❌{RESET}\n")
                sys.stdout.write(e.stderr + "\n")
    if not found_any:
        log_error(f"No valid modules found in {modules_dir}. Check if they have setup.py or pyproject.toml.")

def ensure_pythonpath(modules_dir: Path, dotfiles_dir: Path) -> None:
    pythonpath_dynamic = dotfiles_dir / "dynamic/setup_modules.zsh"
    pythonpath_dynamic.parent.mkdir(parents=True, exist_ok=True)
    pythonpath_entry = f'export PYTHONPATH="{modules_dir}:$PYTHONPATH"\n'
    current_pythonpath = os.environ.get("PYTHONPATH", "").split(":")
    if str(modules_dir) in current_pythonpath:
        log_success(f"PYTHONPATH already includes {modules_dir}. No changes needed.")
        return
    log_info(f"Updating PYTHONPATH to include {modules_dir}...")
    with open(pythonpath_dynamic, "w", encoding="utf-8") as f:
        f.write(pythonpath_entry)
    log_success(f"Updated PYTHONPATH in {pythonpath_dynamic}")
    try:
        subprocess.run(["zsh", "-c", f"source {pythonpath_dynamic}"], check=True)
        log_success(f"Sourced {pythonpath_dynamic}. Python path changes applied immediately.")
    except Exception as e:
        log_error(f"Failed to source {pythonpath_dynamic}: {e}")

def main(scripts_dir: Path, dotfiles_dir: Path, bin_dir: Path, skip_reinstall: bool, production: bool, verbose: bool) -> None:
    with section("Starting MODULES SETUP"):
        modules_dir = scripts_dir / "modules"
        install_python_modules(modules_dir, skip_reinstall, production, verbose)
        ensure_pythonpath(modules_dir, dotfiles_dir)
    log_info("Finished MODULES SETUP.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Python modules and PYTHONPATH.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Path to the scripts directory")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Path to the dotfiles directory")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Path to the bin directory")
    parser.add_argument("--skip-reinstall", action="store_true", help="Skip reinstallation of already installed modules")
    parser.add_argument("--production", action="store_true", help="Install modules in production mode (without -e)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()
    main(args.scripts_dir, args.dotfiles_dir, args.bin_dir,
         args.skip_reinstall, args.production, args.verbose)
