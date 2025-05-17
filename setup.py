#!/usr/bin/env python3
import os
import sys
import argparse
import platform
import importlib
import subprocess
from pathlib import Path

# Attempt to import standard_ui, but don't fail if it's not there yet.
try:
    from standard_ui.standard_ui import (
        init_timer,
        print_global_elapsed,
        log_info as sui_log_info,
        log_success as sui_log_success,
        log_warning as sui_log_warning,
        log_error as sui_log_error,
        section as sui_section,
    )
    STANDARD_UI_AVAILABLE = True
except ImportError:
    STANDARD_UI_AVAILABLE = False
    # Define basic fallbacks
    import time
    _start_time = None
    _is_verbose = "--verbose" in sys.argv or "-v" in sys.argv # Basic check for verbosity

    def init_timer():
        global _start_time
        _start_time = time.time()

    def print_global_elapsed():
        if _start_time is not None:
            elapsed = time.time() - _start_time
            print(f"[INFO] Total execution time: {elapsed:.2f} seconds")

    def _log_prefix(level, message):
        print(f"[{level}] {message}")

    def sui_log_info(message): _log_prefix("INFO", message)
    def sui_log_success(message): _log_prefix("SUCCESS", message)
    def sui_log_warning(message): _log_prefix("WARNING", message)
    def sui_log_error(message): _log_prefix("ERROR", message)

    # A simple context manager for fallback section
    class FallbackSection:
        def __init__(self, title):
            self.title = title
        def __enter__(self):
            if _is_verbose: # Only print section headers if verbose when UI is not available
                print(f"\n--- Starting Section: {self.title} ---")
            return self # Ensure it can be used with 'with ... as ...'
        def __exit__(self, exc_type, exc_val, exc_tb):
            if _is_verbose:
                print(f"--- Finished Section: {self.title} ---\n")
    
    sui_section = FallbackSection
    
    print("[WARNING] standard_ui module not found. Using basic print for logging.")
    print("[INFO] Attempting to install standard_ui as part of the setup...")


SCRIPTS_DIR = Path(__file__).resolve().parent
DOTFILES_DIR = Path(os.environ.get("DOTFILES", SCRIPTS_DIR.parent / "dotfiles"))
BIN_DIR = SCRIPTS_DIR / "bin" # Note: This might be overridden by args in sub-setups.
                             # On Windows, directly executing scripts from a 'bin' via PATH
                             # often relies on file associations or wrapper scripts.
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
    log_content = "\n".join(msg_lines) + "\n"
    
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
    global STANDARD_UI_AVAILABLE # Allow modification if standard_ui is installed
    try:
        importlib.import_module(module_import)
        sui_log_success(f"{module_import} is already installed.")
        if skip_reinstall:
            return
        sui_log_info(f"Attempting to reinstall {module_import} as per options...")
    except ImportError:
        sui_log_info(f"{module_import} not found. Proceeding with installation.")

    install_cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        install_cmd.append("-e")
    install_cmd.append(str(install_path))

    sui_log_info(f"Installing {module_import} from {install_path} {'(editable)' if editable else ''}...")
    proc = subprocess.run(install_cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        sui_log_success(f"Successfully installed/updated {module_import}.")
        # If standard_ui was just installed, try to re-import its functions
        if module_import == "standard_ui" and not STANDARD_UI_AVAILABLE:
            try:
                # Re-assign global logging functions
                from standard_ui.standard_ui import (
                    init_timer as sui_init_timer_real,
                    print_global_elapsed as sui_print_global_elapsed_real,
                    log_info as sui_log_info_real,
                    log_success as sui_log_success_real,
                    log_warning as sui_log_warning_real,
                    log_error as sui_log_error_real,
                    section as sui_section_real,
                )
                global init_timer, print_global_elapsed, sui_log_info, sui_log_success
                global sui_log_warning, sui_log_error, sui_section

                init_timer = sui_init_timer_real
                print_global_elapsed = sui_print_global_elapsed_real
                sui_log_info = sui_log_info_real
                sui_log_success = sui_log_success_real
                sui_log_warning = sui_log_warning_real
                sui_log_error = sui_log_error_real
                sui_section = sui_section_real
                
                STANDARD_UI_AVAILABLE = True
                sui_log_success("Successfully switched to standard_ui logging.")
                # Re-initialize timer if standard_ui has its own timer logic
                if callable(init_timer): init_timer()

            except ImportError:
                sui_log_warning("standard_ui was installed, but failed to import dynamically. Basic logging remains.")

    else:
        sui_log_error(f"Error installing {module_import}; see log for details.")
        write_error_log(f"Install {module_import}", proc)
        errors.append(f"Installation of {module_import}")

def run_setup(script_path: Path, *args):
    if not script_path.exists():
        sui_log_warning(f"Setup script {script_path.name} not found at {script_path}; skipping.")
        errors.append(f"Missing setup script: {script_path.name}")
        return

    sui_log_info(f"Running {script_path.name} with args: {' '.join(args)}...")
    cmd = [sys.executable, str(script_path)]
    cmd.extend(args)
    
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        sui_log_success(f"{script_path.name} completed.")
        if proc.stdout:
            sui_log_info(f"Output from {script_path.name}:\n{proc.stdout.strip()}")
        if proc.stderr:
            sui_log_warning(f"Stderr from {script_path.name} (may be informational):\n{proc.stderr.strip()}")
    else:
        sui_log_error(f"Error in {script_path.name}; see log for details.")
        write_error_log(f"Setup {script_path.name}", proc)
        errors.append(f"Execution of {script_path.name}")

def main():
    parser = argparse.ArgumentParser(description="Master setup script for managing project components.")
    parser.add_argument("--skip-reinstall", action="store_true",
                        help="Skip re-installation of Python modules if they are already present.")
    parser.add_argument("--production", action="store_true",
                        help="Install Python modules in production mode (not editable, i.e., no '-e').")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable detailed output during the setup process.")
    args = parser.parse_args()

    global _is_verbose # For fallback logger
    if STANDARD_UI_AVAILABLE:
        _is_verbose = args.verbose # standard_ui might handle verbosity internally
    else:
        _is_verbose = args.verbose # Set for fallback logger


    if ERROR_LOG.exists():
        try:
            ERROR_LOG.unlink()
        except OSError as e:
            sui_log_warning(f"Could not clear previous error log {ERROR_LOG}: {e}")

    init_timer() # This will call the fallback or the real one
    sui_log_info("=== Running Master Setup Script ===")
    sui_log_info(f"Operating System: {platform.system()} ({os.name})")
    sui_log_info(f"Scripts base directory: {SCRIPTS_DIR}")
    sui_log_info(f"Dotfiles directory: {DOTFILES_DIR}")
    sui_log_info(f"Target bin directory for symlinks/executables: {BIN_DIR}")

    # Create BIN_DIR if it doesn't exist, critical for symlinks
    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        sui_log_info(f"Ensured bin directory exists: {BIN_DIR}")
    except OSError as e:
        sui_log_error(f"Could not create bin directory {BIN_DIR}: {e}. Symlink creation will likely fail.")
        errors.append(f"Bin directory creation failed: {BIN_DIR}")
        # Depending on how critical BIN_DIR is, you might choose to exit early.
        # For now, let's continue and let sub-scripts handle missing BIN_DIR if necessary.

    with sui_section("Core Module Installation"):
        # Install standard_ui first, as it enhances logging for subsequent steps.
        if (STANDARD_UI_SETUP_DIR / "setup.py").exists() or \
           (STANDARD_UI_SETUP_DIR / "pyproject.toml").exists():
            ensure_module_installed(
                "standard_ui",
                STANDARD_UI_SETUP_DIR,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production
            )
        else:
            sui_log_info("standard_ui setup files (setup.py or pyproject.toml) not found. Assuming direct usage or pre-installed.")

        # Ensure scripts_setup (if it's an installable package)
        if (SCRIPTS_SETUP_DIR / "setup.py").exists() or \
           (SCRIPTS_SETUP_DIR / "pyproject.toml").exists():
            ensure_module_installed(
                "scripts_setup",
                SCRIPTS_SETUP_DIR,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production
            )
        else:
            sui_log_info("scripts_setup is used directly, not via package installation, or setup files not found.")

        # Ensure cross_platform (if it's an installable package)
        if (CROSS_PLATFORM_DIR / "setup.py").exists() or \
           (CROSS_PLATFORM_DIR / "pyproject.toml").exists():
            ensure_module_installed(
                "cross_platform",
                CROSS_PLATFORM_DIR,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production
            )
        else:
            sui_log_info("cross_platform is used directly, not via package installation, or setup files not found.")


    if "microsoft" in platform.uname().release.lower() and "WSL" in platform.uname().release.upper():
        with sui_section("WSL2 Specific Setup"):
            sui_log_info("Detected WSL2; attempting to run win32yank setup...")
            run_setup(SCRIPTS_SETUP_DIR / "setup_wsl2.py")
    else:
        sui_log_success("Not WSL2 or win32yank setup not applicable; skipping win32yank setup.")

    common_setup_args = [
        "--scripts-dir", str(SCRIPTS_DIR),
        "--dotfiles-dir", str(DOTFILES_DIR),
        "--bin-dir", str(BIN_DIR)
    ]
    if args.verbose:
        common_setup_args.append("--verbose")
    if args.skip_reinstall:
        common_setup_args.append("--skip-reinstall")
    if args.production:
        common_setup_args.append("--production")

    sub_setup_scripts_relative_paths = [
        Path("pyscripts/setup.py"),
        Path("shell-scripts/setup.py"),
        Path("modules/setup.py")
    ]

    for rel_script_path in sub_setup_scripts_relative_paths:
        full_script_path = SCRIPTS_DIR / rel_script_path
        # Use sui_section for better output structure
        with sui_section(f"Running sub-setup: {rel_script_path.name}"):
            run_setup(full_script_path, *common_setup_args)
            
    with sui_section("Shell PATH Configuration (setup_path.py)"):
        setup_path_script = SCRIPTS_SETUP_DIR / "setup_path.py"
        path_args = [
            "--bin-dir", str(BIN_DIR),
            "--dotfiles-dir", str(DOTFILES_DIR)
        ]
        # No verbose argument for setup_path.py in its current form in the prompt
        # If setup_path.py is updated to accept --verbose, it can be added here.
        run_setup(setup_path_script, *path_args)

    print_global_elapsed()
    if errors:
        sui_log_error(f"{len(errors)} error(s) occurred during setup. Details have been logged to '{ERROR_LOG}'.")
        sys.exit(1)
    else:
        sui_log_success("All setup steps completed successfully.")

if __name__ == "__main__":
    main()
