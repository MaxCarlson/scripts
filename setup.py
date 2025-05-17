#!/usr/bin/env python3
import os
import sys
import argparse
import platform
import importlib
import subprocess
from pathlib import Path
import time # Import time for fallbacks

# --- Global UI Function Placeholders ---
# These will be populated by standard_ui or fallbacks
init_timer = None
print_global_elapsed = None
sui_log_info = None
sui_log_success = None
sui_log_warning = None
sui_log_error = None
sui_section = None
STANDARD_UI_AVAILABLE = False
_is_verbose = "--verbose" in sys.argv or "-v" in sys.argv # Basic verbosity check for early fallback logs

# --- Attempt to load standard_ui functions initially ---
try:
    from standard_ui.standard_ui import (
        init_timer as real_init_timer,
        print_global_elapsed as real_print_global_elapsed,
        log_info as real_sui_log_info,
        log_success as real_sui_log_success,
        log_warning as real_sui_log_warning,
        log_error as real_sui_log_error,
        section as real_sui_section
    )
    init_timer = real_init_timer
    print_global_elapsed = real_print_global_elapsed
    sui_log_info = real_sui_log_info
    sui_log_success = real_sui_log_success
    sui_log_warning = real_sui_log_warning
    sui_log_error = real_sui_log_error
    sui_section = real_sui_section
    STANDARD_UI_AVAILABLE = True
except ImportError:
    _start_time_fb = None # Fallback start time

    def fb_init_timer():
        global _start_time_fb
        _start_time_fb = time.time()

    def fb_print_global_elapsed():
        if _start_time_fb is not None:
            elapsed = time.time() - _start_time_fb
            print(f"[INFO] Total execution time: {elapsed:.2f} seconds")

    def _fb_log_prefix(level, message): print(f"[{level}] {message}")
    def fb_log_info(message): _fb_log_prefix("INFO", message)
    def fb_log_success(message): _fb_log_prefix("SUCCESS", message)
    def fb_log_warning(message): _fb_log_prefix("WARNING", message)
    def fb_log_error(message): _fb_log_prefix("ERROR", message)

    class FallbackSectionClass: # Renamed to avoid conflict if sui_section was already a class
        def __init__(self, title): self.title = title
        def __enter__(self):
            if _is_verbose: print(f"\n--- Starting Section: {self.title} ---")
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            if _is_verbose: print(f"--- Finished Section: {self.title} ---\n")

    init_timer, print_global_elapsed = fb_init_timer, fb_print_global_elapsed
    sui_log_info, sui_log_success = fb_log_info, fb_log_success
    sui_log_warning, sui_log_error = fb_log_warning, fb_log_error
    sui_section = FallbackSectionClass # Assign the class itself
    
    if '--quiet' not in sys.argv: # Avoid printing warning if user wants quiet
        fb_log_warning("standard_ui module not found initially. Using basic print for logging.")
        fb_log_info("Attempting to install standard_ui as part of the setup...")

# --- Helper function to dynamically reload standard_ui functions globally ---
def _try_reload_standard_ui_globally():
    global init_timer, print_global_elapsed, sui_log_info, sui_log_success
    global sui_log_warning, sui_log_error, sui_section, STANDARD_UI_AVAILABLE

    warning_logger_before_reload = sui_log_warning  # Could be fallback or already loaded real one

    try:
        from standard_ui.standard_ui import (
            init_timer as imported_init_timer,
            print_global_elapsed as imported_print_global_elapsed,
            log_info as imported_log_info,
            log_success as imported_log_success,
            log_warning as imported_log_warning,
            log_error as imported_log_error,
            section as imported_section,
        )
        init_timer = imported_init_timer
        print_global_elapsed = imported_print_global_elapsed
        sui_log_info = imported_log_info
        sui_log_success = imported_log_success
        sui_log_warning = imported_log_warning
        sui_log_error = imported_log_error
        sui_section = imported_section # Assign the imported class/function directly
        
        STANDARD_UI_AVAILABLE = True
        if callable(sui_log_success):
            sui_log_success("Successfully switched to standard_ui logging dynamically.")
        if callable(init_timer): 
            init_timer() 
    except ImportError:
        if callable(warning_logger_before_reload):
            warning_logger_before_reload("standard_ui was installed, but failed to import dynamically for global update. Previous logging functions remain active.")

SCRIPTS_DIR = Path(__file__).resolve().parent
DOTFILES_DIR = Path(os.environ.get("DOTFILES", SCRIPTS_DIR.parent / "dotfiles"))
BIN_DIR = SCRIPTS_DIR / "bin"
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
        # Use fallback print if logging to file fails, ensuring it's defined
        print_func = fb_log_error if not callable(sui_log_error) else sui_log_error
        print_func(f"Critical error: Could not write to error log {ERROR_LOG}. Reason: {e}")
        print_func("Error details that were to be logged:")
        print_func(log_content)


def ensure_module_installed(module_import: str, install_path: Path,
                            skip_reinstall: bool, editable: bool):
    # `global STANDARD_UI_AVAILABLE` is not needed here anymore as we call the helper.
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
        if module_import == "standard_ui" and not STANDARD_UI_AVAILABLE:
            _try_reload_standard_ui_globally() # Attempt to update global UI functions
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
    global _is_verbose # Allow main to update this based on args for fallback logger
    parser = argparse.ArgumentParser(description="Master setup script for managing project components.")
    parser.add_argument("--skip-reinstall", action="store_true",
                        help="Skip re-installation of Python modules if they are already present.")
    parser.add_argument("--production", action="store_true",
                        help="Install Python modules in production mode (not editable, i.e., no '-e').")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable detailed output during the setup process.")
    parser.add_argument("--quiet", action="store_true", # Added for completeness if needed
                        help="Suppress informational messages (mainly for fallback logger).")
    args = parser.parse_args()

    # Update _is_verbose based on parsed args, especially for the fallback section context manager
    _is_verbose = args.verbose

    # If standard_ui was not available, its fallback logger has already printed.
    # If it *was* available, then we use its functions.
    # init_timer() will call the appropriate version.
    if callable(init_timer):
        init_timer()
    else: # Should not happen if logic is correct, but as a safeguard
        fb_init_timer()
        fb_log_error("Critical error: init_timer not callable.")


    if ERROR_LOG.exists():
        try:
            ERROR_LOG.unlink()
        except OSError as e:
            sui_log_warning(f"Could not clear previous error log {ERROR_LOG}: {e}")

    sui_log_info("=== Running Master Setup Script ===")
    sui_log_info(f"Operating System: {platform.system()} ({os.name})")
    sui_log_info(f"Scripts base directory: {SCRIPTS_DIR}")
    sui_log_info(f"Dotfiles directory: {DOTFILES_DIR}")
    sui_log_info(f"Target bin directory for symlinks/executables: {BIN_DIR}")

    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        sui_log_info(f"Ensured bin directory exists: {BIN_DIR}")
    except OSError as e:
        sui_log_error(f"Could not create bin directory {BIN_DIR}: {e}. Symlink creation will likely fail.")
        errors.append(f"Bin directory creation failed: {BIN_DIR}")

    # Use the sui_section context manager (could be real or fallback)
    # Need to ensure sui_section is the class itself if it's the fallback
    active_section_mgr = sui_section if STANDARD_UI_AVAILABLE else sui_section # sui_section is FallbackSectionClass

    with active_section_mgr("Core Module Installation"):
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
        with active_section_mgr("WSL2 Specific Setup"):
            sui_log_info("Detected WSL2; attempting to run win32yank setup...")
            run_setup(SCRIPTS_SETUP_DIR / "setup_wsl2.py")
    else:
        sui_log_success("Not WSL2 or win32yank setup not applicable; skipping win32yank setup.")

    common_setup_args = [
        "--scripts-dir", str(SCRIPTS_DIR),
        "--dotfiles-dir", str(DOTFILES_DIR),
        "--bin-dir", str(BIN_DIR)
    ]
    if args.verbose: common_setup_args.append("--verbose")
    if args.skip_reinstall: common_setup_args.append("--skip-reinstall")
    if args.production: common_setup_args.append("--production")

    sub_setup_scripts_relative_paths = [
        Path("pyscripts/setup.py"),
        Path("shell-scripts/setup.py"),
        Path("modules/setup.py")
    ]

    for rel_script_path in sub_setup_scripts_relative_paths:
        full_script_path = SCRIPTS_DIR / rel_script_path
        with active_section_mgr(f"Running sub-setup: {rel_script_path.name}"):
            run_setup(full_script_path, *common_setup_args)
            
    with active_section_mgr("Shell PATH Configuration (setup_path.py)"):
        setup_path_script = SCRIPTS_SETUP_DIR / "setup_path.py"
        path_args = [
            "--bin-dir", str(BIN_DIR),
            "--dotfiles-dir", str(DOTFILES_DIR)
        ]
        # Pass verbose to setup_path.py if it accepts it
        if args.verbose: path_args.append("--verbose")
        run_setup(setup_path_script, *path_args)

    if callable(print_global_elapsed):
        print_global_elapsed()
    else: # Safeguard
        fb_print_global_elapsed()

    if errors:
        sui_log_error(f"{len(errors)} error(s) occurred during setup. Details have been logged to '{ERROR_LOG}'.")
        sys.exit(1)
    else:
        sui_log_success("All setup steps completed successfully.")

if __name__ == "__main__":
    main()
