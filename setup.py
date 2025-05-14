#!/usr/bin/env python3
import os
import sys
import argparse
import platform
import importlib
import subprocess
from pathlib import Path

# Import our unified UI functions
from standard_ui.standard_ui import (
    init_timer,
    print_global_elapsed,
    log_info,
    log_success,
    log_warning,
    log_error,
    section,
)

SCRIPTS_DIR = Path(__file__).resolve().parent
DOTFILES_DIR = Path(os.environ.get("DOTFILES", SCRIPTS_DIR.parent / "dotfiles"))
BIN_DIR = SCRIPTS_DIR / "bin"
MODULES_DIR = SCRIPTS_DIR / "modules"
SCRIPTS_SETUP_DIR = SCRIPTS_DIR / "scripts_setup"
CROSS_PLATFORM_DIR = MODULES_DIR / "cross_platform"
STANDARD_UI_SETUP_DIR = MODULES_DIR / "standard_ui"

def ensure_module_installed(module_import: str, install_path: Path):
    try:
        importlib.import_module(module_import)
        log_success(f"{module_import} is installed.")
    except ImportError:
        log_info(f"{module_import} not found. Installing from {install_path} ...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(install_path)],
            check=True
        )
        try:
            importlib.import_module(module_import)
            log_success(f"Successfully installed {module_import}.")
        except ImportError:
            log_error(f"Failed to import {module_import} even after installation.")
            sys.exit(1)

required_modules = {
    "standard_ui": STANDARD_UI_SETUP_DIR,
    "scripts_setup": SCRIPTS_SETUP_DIR,
    "cross_platform": CROSS_PLATFORM_DIR,
    # Add other required modules here.
}

for mod, path in required_modules.items():
    ensure_module_installed(mod, path)

def run_setup(script_path, *args):
    if script_path.exists():
        log_info(f"Running {script_path} ...")
        subprocess.run([sys.executable, str(script_path)] + list(args), check=True)
    else:
        log_warning(f"Setup script {script_path} not found. Skipping.")

def main():
    parser = argparse.ArgumentParser(description="Master setup script.")
    parser.add_argument("--skip-reinstall", action="store_true",
                        help="Skip reinstallation of already installed modules")
    parser.add_argument("--production", action="store_true",
                        help="Install modules in production mode (without -e)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    # Start the global timer.
    init_timer()

    log_info("=== Running Master Setup Script ===")

    if "microsoft" in platform.uname().release.lower():
        log_info("Detected WSL2 environment. Running win32yank setup...")
        wsl2_setup = SCRIPTS_DIR / "scripts_setup/setup_wsl2.py"
        subprocess.run([sys.executable, str(wsl2_setup)], check=True)
    else:
        log_success("Not running on WSL2. Skipping win32yank setup.")

    common_args = [
        "--scripts-dir", str(SCRIPTS_DIR),
        "--dotfiles-dir", str(DOTFILES_DIR),
        "--bin-dir", str(BIN_DIR)
    ]
    if args.verbose:
        common_args.append("--verbose")

    setup_scripts = [
        "pyscripts/setup.py",
        "shell-scripts/setup.py",
        "modules/setup.py",
    ]

    for script in setup_scripts:
        extra_args = []
        if "modules" in script:
            if args.skip_reinstall:
                extra_args.append("--skip-reinstall")
            if args.production:
                extra_args.append("--production")
        with section(f"Running {script}"):
            run_setup(SCRIPTS_DIR / script, *common_args, *extra_args)

    with section("Running scripts_setup/setup_path.py"):
        path_setup_args = [
            "--bin-dir", str(BIN_DIR),
            "--dotfiles-dir", str(DOTFILES_DIR)
        ]
        if args.verbose:
            path_setup_args.append("--verbose")
        run_setup(SCRIPTS_DIR / "scripts_setup/setup_path.py", *path_setup_args)

    print_global_elapsed()
    log_info("Master setup script complete.")

if __name__ == "__main__":
    main()
