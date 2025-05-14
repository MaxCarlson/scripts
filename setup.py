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
BIN_DIR = SCRIPTS_DIR / "bin" # Note: This might be overridden by args in sub-setups
MODULES_DIR = SCRIPTS_DIR / "modules"
SCRIPTS_SETUP_DIR = SCRIPTS_DIR / "scripts_setup"
CROSS_PLATFORM_DIR = MODULES_DIR / "cross_platform"
STANDARD_UI_SETUP_DIR = MODULES_DIR / "standard_ui"

ERROR_LOG = SCRIPTS_DIR / "setup_errors.log"
errors = []

def write_error_log(title: str, proc: subprocess.CompletedProcess):
    msg_lines = [f"=== {title} ===",
                 f"Return code: {proc.returncode}",
                 "--- STDOUT ---", proc.stdout or "<none>",
                 "--- STDERR ---", proc.stderr or "<none>", ""]
    log_content = "\n".join(msg_lines) + "\n" # Ensure a newline at the end of the entry
    
    # Use open() with mode 'a' for appending, which is universally compatible
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(log_content)
    except Exception as e:
        # Fallback print if logging to file fails
        print(f"Critical error: Could not write to error log {ERROR_LOG}. Reason: {e}")
        print("Error details that were to be logged:")
        print(log_content)


def ensure_module_installed(module_import: str, install_path: Path,
                            skip_reinstall: bool, editable: bool):
    try:
        importlib.import_module(module_import)
        log_success(f"{module_import} is already installed.")
        if skip_reinstall:
            return
        log_info(f"Attempting to reinstall {module_import} as per options...")
    except ImportError:
        log_info(f"{module_import} not found. Proceeding with installation.")
        # If skip_reinstall was true and module was missing, it means we should install it.
        # The original logic was:
        # if skip_reinstall: log_warning(f"Skipping installation of missing module '{module_import}'."); return
        # This seems counter-intuitive if the goal is to ensure it's there.
        # Assuming ensure_module_installed means it should be installed if missing, regardless of skip_reinstall.
        # If skip_reinstall is strictly "don't touch if present, don't install if absent", then original logic was fine.
        # For now, assuming "install if absent or if reinstall is requested".

    install_cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        install_cmd.append("-e")
    install_cmd.append(str(install_path))

    log_info(f"Installing {module_import} from {install_path} {'(editable)' if editable else ''}...")
    proc = subprocess.run(install_cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        log_success(f"Successfully installed/updated {module_import}.")
    else:
        log_error(f"Error installing {module_import}; see log for details.")
        write_error_log(f"Install {module_import}", proc)
        errors.append(f"Installation of {module_import}")

def run_setup(script_path: Path, *args):
    if not script_path.exists():
        log_warning(f"Setup script {script_path.name} not found at {script_path}; skipping.")
        errors.append(f"Missing setup script: {script_path.name}")
        return

    log_info(f"Running {script_path.name} with args: {' '.join(args)}...")
    cmd = [sys.executable, str(script_path)]
    cmd.extend(args) # Add other arguments correctly
    
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        log_success(f"{script_path.name} completed.")
        if proc.stdout:
            log_info(f"Output from {script_path.name}:\n{proc.stdout.strip()}")
        if proc.stderr: # Some scripts might output informational messages to stderr
            log_warning(f"Stderr from {script_path.name} (may be informational):\n{proc.stderr.strip()}")
    else:
        log_error(f"Error in {script_path.name}; see log for details.")
        write_error_log(f"Setup {script_path.name}", proc)
        errors.append(f"Execution of {script_path.name}")

def main():
    parser = argparse.ArgumentParser(description="Master setup script for managing project components.")
    parser.add_argument("--skip-reinstall", action="store_true",
                        help="Skip re-installation of Python modules if they are already present.")
    parser.add_argument("--production", action="store_true",
                        help="Install Python modules in production mode (not editable, i.e., no '-e').")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable detailed output during the setup process.")
    args = parser.parse_args()

    # Clear previous error log at the beginning of a new run
    if ERROR_LOG.exists():
        try:
            ERROR_LOG.unlink()
        except OSError as e:
            log_warning(f"Could not clear previous error log {ERROR_LOG}: {e}")


    init_timer()
    log_info("=== Running Master Setup Script ===")
    log_info(f"Scripts base directory: {SCRIPTS_DIR}")
    log_info(f"Dotfiles directory: {DOTFILES_DIR}")
    log_info(f"Target bin directory for symlinks: {BIN_DIR}") # Default BIN_DIR

    # 1) Core local Python modules (standard_ui, scripts_setup, cross_platform)
    # These are often part of the same project structure and might not need 'pip install -e'
    # if they are correctly added to PYTHONPATH or structured as a package.
    # For simplicity, if they have setup.py, installing them editably is a common pattern.
    
    # Assuming standard_ui is already available due to direct import.
    # For scripts_setup and cross_platform, if they are actual packages meant to be installed:
    # Path to the directory containing setup.py for 'scripts_setup'
    # (Adjust if scripts_setup is not a full package but a collection of utils)

    # For modules like 'standard_ui', 'cross_platform' that are in `MODULES_DIR`
    # and 'scripts_setup' which is in `SCRIPTS_SETUP_DIR`.
    # The ensure_module_installed expects a path to the package to install.
    
    # Let's assume standard_ui is installable from STANDARD_UI_SETUP_DIR
    # (which is SCRIPTS_DIR/modules/standard_ui)
    # And cross_platform from CROSS_PLATFORM_DIR (SCRIPTS_DIR/modules/cross_platform)
    # And scripts_setup from SCRIPTS_SETUP_DIR (SCRIPTS_DIR/scripts_setup)
    
    # The original code had hardcoded module names and paths. This is fine if paths are stable.
    # standard_ui, scripts_setup, cross_platform
    # The paths are defined above like STANDARD_UI_SETUP_DIR
    
    # Ensure standard_ui (if it's an installable package)
    if (STANDARD_UI_SETUP_DIR / "setup.py").exists() or (STANDARD_UI_SETUP_DIR / "pyproject.toml").exists():
         ensure_module_installed(
             "standard_ui", # Import name
             STANDARD_UI_SETUP_DIR, # Path to package directory
             skip_reinstall=args.skip_reinstall,
             editable=not args.production
         )
    else:
        log_info("standard_ui is used directly, not via package installation, or setup files not found.")

    # Ensure scripts_setup (if it's an installable package)
    if (SCRIPTS_SETUP_DIR / "setup.py").exists() or (SCRIPTS_SETUP_DIR / "pyproject.toml").exists():
        ensure_module_installed(
            "scripts_setup",
            SCRIPTS_SETUP_DIR,
            skip_reinstall=args.skip_reinstall,
            editable=not args.production
        )
    else:
        log_info("scripts_setup is used directly, not via package installation, or setup files not found.")

    # Ensure cross_platform (if it's an installable package)
    if (CROSS_PLATFORM_DIR / "setup.py").exists() or (CROSS_PLATFORM_DIR / "pyproject.toml").exists():
        ensure_module_installed(
            "cross_platform",
            CROSS_PLATFORM_DIR,
            skip_reinstall=args.skip_reinstall,
            editable=not args.production
        )
    else:
        log_info("cross_platform is used directly, not via package installation, or setup files not found.")


    # 2) Optional WSL2 helper
    if "microsoft" in platform.uname().release.lower():
        log_info("Detected WSL2; attempting to run win32yank setup...")
        # Assuming setup_wsl2.py is in SCRIPTS_SETUP_DIR
        run_setup(SCRIPTS_SETUP_DIR / "setup_wsl2.py")
    else:
        log_success("Not WSL2; skipping win32yank setup.")

    # Common arguments for sub-setup scripts
    common_setup_args = [
        "--scripts-dir", str(SCRIPTS_DIR),
        "--dotfiles-dir", str(DOTFILES_DIR),
        "--bin-dir", str(BIN_DIR) # Pass the default BIN_DIR
    ]
    if args.verbose:
        common_setup_args.append("--verbose")
    if args.skip_reinstall: # If sub-setups also handle module installs
        common_setup_args.append("--skip-reinstall")
    if args.production: # If sub-setups also handle module installs
        common_setup_args.append("--production")

    # 3) Run sub-setup scripts from various locations
    # Original: "pyscripts/setup.py", "shell-scripts/setup.py", "modules/setup.py"
    # These paths are relative to SCRIPTS_DIR
    sub_setup_scripts_relative_paths = [
        Path("pyscripts/setup.py"),
        Path("shell-scripts/setup.py"), # Ensure this one also takes Python args if run via run_setup
        Path("modules/setup.py") # This might be a general setup for all modules within MODULES_DIR
    ]

    for rel_script_path in sub_setup_scripts_relative_paths:
        full_script_path = SCRIPTS_DIR / rel_script_path
        with section(f"Running sub-setup: {rel_script_path}"):
            run_setup(full_script_path, *common_setup_args)

    # 4) Path integrator
    with section("Setting up shell PATH configuration (setup_path.py)"):
        setup_path_script = SCRIPTS_SETUP_DIR / "setup_path.py"
        path_args = [
            "--bin-dir", str(BIN_DIR), # BIN_DIR where symlinks are created
            "--dotfiles-dir", str(DOTFILES_DIR)
        ]
        if args.verbose:
            path_args.append("--verbose")
        run_setup(setup_path_script, *path_args)

    # Final timing & error summary
    print_global_elapsed()
    if errors:
        log_error(f"{len(errors)} error(s) occurred during setup. Details have been logged to '{ERROR_LOG}'.")
        sys.exit(1) # Exit with error code if there were problems
    else:
        log_success("All setup steps completed successfully.")

if __name__ == "__main__":
    main()
