#!/usr/bin/env python3
import os
import sys
import argparse
import platform
import importlib 
import subprocess
from pathlib import Path
import time 

# --- Global UI Function Placeholders ---
init_timer = None
print_global_elapsed = None
sui_log_info = None
sui_log_success = None
sui_log_warning = None
sui_log_error = None
sui_section = None
STANDARD_UI_AVAILABLE = False
_is_verbose = "--verbose" in sys.argv or "-v" in sys.argv

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
    _start_time_fb = None 

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

    class FallbackSectionClass:
        def __init__(self, title): self.title = title
        def __enter__(self):
            if _is_verbose: print(f"\n--- Starting Section: {self.title} ---")
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            if _is_verbose: print(f"--- Finished Section: {self.title} ---\n")

    init_timer, print_global_elapsed = fb_init_timer, fb_print_global_elapsed
    sui_log_info, sui_log_success = fb_log_info, fb_log_success
    sui_log_warning, sui_log_error = fb_log_warning, fb_log_error
    sui_section = FallbackSectionClass
    
    if '--quiet' not in sys.argv:
        fb_log_warning("standard_ui module not found initially. Using basic print for logging.")

# --- Helper function to dynamically reload standard_ui functions globally ---
def _try_reload_standard_ui_globally():
    global init_timer, print_global_elapsed, sui_log_info, sui_log_success
    global sui_log_warning, sui_log_error, sui_section, STANDARD_UI_AVAILABLE

    warning_logger_before_reload = sui_log_warning

    try:
        importlib.invalidate_caches() 
        from standard_ui.standard_ui import ( # This is the import that was failing
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
        sui_section = imported_section
        
        STANDARD_UI_AVAILABLE = True
        if callable(sui_log_success):
            sui_log_success("Successfully switched to standard_ui logging dynamically.")
        if callable(init_timer): 
            init_timer() 
    except ImportError as e:
        if callable(warning_logger_before_reload):
            # Provide more detail from the import error
            warning_logger_before_reload(f"standard_ui was installed, but failed to import dynamically for global update (Error: {type(e).__name__}: {e}). Previous logging functions remain active.")

SCRIPTS_DIR = Path(__file__).resolve().parent
# Determine actual on-disk casing for 'Modules' or 'modules'
# This assumes 'modules' (lowercase) is the intended logical name but respects on-disk reality.
MODULES_DIR_NAME_ON_DISK = "Modules" if (SCRIPTS_DIR / "Modules").exists() else "modules"
MODULES_DIR = SCRIPTS_DIR / MODULES_DIR_NAME_ON_DISK # e.g., C:\...\scripts\Modules
STANDARD_UI_SETUP_DIR = MODULES_DIR / "standard_ui" # e.g., C:\...\scripts\Modules\standard_ui
CROSS_PLATFORM_DIR = MODULES_DIR / "cross_platform" # e.g., C:\...\scripts\Modules\cross_platform

DOTFILES_DIR = Path(os.environ.get("DOTFILES", SCRIPTS_DIR.parent / "dotfiles"))
BIN_DIR = SCRIPTS_DIR / "bin"
SCRIPTS_SETUP_DIR = SCRIPTS_DIR / "scripts_setup"


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
        current_error_logger = sui_log_error if STANDARD_UI_AVAILABLE and callable(sui_log_error) else fb_log_error
        current_error_logger(f"Critical error: Could not write to error log {ERROR_LOG}. Reason: {e}")
        current_error_logger("Error details that were to be logged:")
        current_error_logger(log_content)


def ensure_module_installed(module_import: str, install_path: Path,
                            skip_reinstall: bool, editable: bool):
    try:
        importlib.invalidate_caches() 
        importlib.import_module(module_import)
        sui_log_success(f"{module_import} is already installed.")
        if skip_reinstall:
            if module_import == "standard_ui" and not STANDARD_UI_AVAILABLE:
                 sui_log_info("standard_ui detected as installed but not active; attempting to activate...")
                 _try_reload_standard_ui_globally()
            return
        sui_log_info(f"Attempting to reinstall {module_import} as per options...")
    except ImportError:
        sui_log_info(f"{module_import} not found. Proceeding with installation.")

    install_cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        install_cmd.append("-e")
    # Ensure install_path is resolved to an absolute path for pip
    resolved_install_path = install_path.resolve()
    install_cmd.append(str(resolved_install_path))

    sui_log_info(f"Installing {module_import} from {resolved_install_path} {'(editable)' if editable else ''}...")
    # For pip install, it should generally operate within the current Python environment's context
    # without needing explicit PYTHONPATH modification for the pip command itself.
    proc = subprocess.run(install_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    if proc.returncode == 0:
        sui_log_success(f"Successfully installed/updated {module_import}.")
        if module_import == "standard_ui": 
            _try_reload_standard_ui_globally()
    else:
        sui_log_error(f"Error installing {module_import} (rc: {proc.returncode}); see log for details.")
        sui_log_error(f"Pip stdout: {proc.stdout.strip() if proc.stdout else '<empty>'}")
        sui_log_error(f"Pip stderr: {proc.stderr.strip() if proc.stderr else '<empty>'}")
        write_error_log(f"Install {module_import}", proc)
        errors.append(f"Installation of {module_import}")

def run_setup(script_path: Path, *args):
    resolved_script_path = script_path.resolve() # Resolve once
    sui_log_info(f"Debug run_setup: Checking script '{resolved_script_path}', Exists: {resolved_script_path.exists()}")
    if not resolved_script_path.exists():
        sui_log_warning(f"Setup script {resolved_script_path.name} not found at {resolved_script_path}; skipping.")
        errors.append(f"Missing setup script: {resolved_script_path.name}")
        return

    sui_log_info(f"Running {resolved_script_path.name} with args: {' '.join(args)}...")
    cmd = [sys.executable, str(resolved_script_path)]
    cmd.extend(args)

    env = os.environ.copy()
    # `scripts_setup` is directly under SCRIPTS_DIR.
    # `standard_ui`, `cross_platform` are under MODULES_DIR (e.g., SCRIPTS_DIR/"Modules").
    # Add both SCRIPTS_DIR and MODULES_DIR to PYTHONPATH for subprocesses.
    # This makes `import scripts_setup` and `import standard_ui` work if they are packages.
    python_path_to_add = [str(SCRIPTS_DIR.resolve()), str(MODULES_DIR.resolve())]
    
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        python_path_to_add.extend(existing_pythonpath.split(os.pathsep))
    
    # Remove duplicates while preserving order (from Python 3.7+, dict preserves insertion order)
    env["PYTHONPATH"] = os.pathsep.join(list(dict.fromkeys(python_path_to_add)))
    env["PYTHONIOENCODING"] = "utf-8" # For better Unicode handling in subprocesses

    if _is_verbose: 
        sui_log_info(f"Subprocess PYTHONPATH for {resolved_script_path.name}: {env['PYTHONPATH']}")
        sui_log_info(f"Subprocess PYTHONIOENCODING for {resolved_script_path.name}: {env['PYTHONIOENCODING']}")


    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding='utf-8', errors='ignore')
    if proc.returncode == 0:
        sui_log_success(f"{resolved_script_path.name} completed.")
        if proc.stdout and proc.stdout.strip():
            sui_log_info(f"Output from {resolved_script_path.name}:\n{proc.stdout.strip()}")
        if proc.stderr and proc.stderr.strip(): 
            sui_log_warning(f"Stderr from {resolved_script_path.name} (may be informational):\n{proc.stderr.strip()}")
    else:
        sui_log_error(f"Error in {resolved_script_path.name} (rc: {proc.returncode}); see log for details.")
        sui_log_error(f"Subprocess stdout for {resolved_script_path.name}:\n{proc.stdout.strip() or '<empty>'}")
        sui_log_error(f"Subprocess stderr for {resolved_script_path.name}:\n{proc.stderr.strip() or '<empty>'}")
        write_error_log(f"Setup {resolved_script_path.name}", proc)
        errors.append(f"Execution of {resolved_script_path.name}")

def main():
    global _is_verbose 
    parser = argparse.ArgumentParser(description="Master setup script for managing project components.")
    parser.add_argument("--skip-reinstall", action="store_true",
                        help="Skip re-installation of Python modules if they are already present.")
    parser.add_argument("--production", action="store_true",
                        help="Install Python modules in production mode (not editable, i.e., no '-e').")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable detailed output during the setup process.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress informational messages (mainly for fallback logger).")
    args = parser.parse_args()

    _is_verbose = args.verbose 

    if callable(init_timer): init_timer()
    else: print("[ERROR] init_timer is not callable.") 

    if not STANDARD_UI_AVAILABLE and not args.quiet: 
        sui_log_info("Attempting to install standard_ui as part of the setup...")

    if ERROR_LOG.exists():
        try:
            ERROR_LOG.unlink()
        except OSError as e:
            sui_log_warning(f"Could not clear previous error log {ERROR_LOG}: {e}")

    sui_log_info("=== Running Master Setup Script ===")
    sui_log_info(f"Operating System: {platform.system()} ({os.name}), Release: {platform.release()}")
    sui_log_info(f"Python Version: {sys.version.split()[0]}")
    sui_log_info(f"Python Executable: {sys.executable}")
    sui_log_info(f"SCRIPTS_DIR: {SCRIPTS_DIR}")
    sui_log_info(f"MODULES_DIR (resolved on-disk name '{MODULES_DIR_NAME_ON_DISK}'): {MODULES_DIR}")
    sui_log_info(f"STANDARD_UI_SETUP_DIR: {STANDARD_UI_SETUP_DIR}")
    sui_log_info(f"DOTFILES_DIR: {DOTFILES_DIR}")
    sui_log_info(f"Target BIN_DIR: {BIN_DIR}")

    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        sui_log_info(f"Ensured bin directory exists: {BIN_DIR}")
    except OSError as e:
        sui_log_error(f"Could not create bin directory {BIN_DIR}: {e}. Symlink creation will likely fail.")
        errors.append(f"Bin directory creation failed: {BIN_DIR}")

    active_section_mgr_class = sui_section 

    with active_section_mgr_class("Core Module Installation"):
        # STANDARD_UI_SETUP_DIR should now correctly point to .../scripts/Modules/standard_ui or .../scripts/modules/standard_ui
        if (STANDARD_UI_SETUP_DIR / "setup.py").exists() or \
           (STANDARD_UI_SETUP_DIR / "pyproject.toml").exists():
            ensure_module_installed(
                "standard_ui", # The name of the package to import
                STANDARD_UI_SETUP_DIR, # The path to the package source for pip install -e
                skip_reinstall=args.skip_reinstall,
                editable=not args.production
            )
        else:
            sui_log_warning(f"standard_ui setup files (setup.py or pyproject.toml) not found in {STANDARD_UI_SETUP_DIR}.")

        if (SCRIPTS_SETUP_DIR / "setup.py").exists() or \
           (SCRIPTS_SETUP_DIR / "pyproject.toml").exists():
            ensure_module_installed(
                "scripts_setup", 
                SCRIPTS_SETUP_DIR, 
                skip_reinstall=args.skip_reinstall,
                editable=not args.production
            )
        else:
            sui_log_warning(f"scripts_setup setup files not found in {SCRIPTS_SETUP_DIR}.")

        if (CROSS_PLATFORM_DIR / "setup.py").exists() or \
           (CROSS_PLATFORM_DIR / "pyproject.toml").exists():
            ensure_module_installed(
                "cross_platform",
                CROSS_PLATFORM_DIR,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production
            )
        else:
            sui_log_warning(f"cross_platform setup files not found in {CROSS_PLATFORM_DIR}.")

    if "microsoft" in platform.uname().release.lower() and "WSL" in platform.uname().release.upper():
        with active_section_mgr_class("WSL2 Specific Setup"):
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

    # These paths are relative to SCRIPTS_DIR
    sub_setup_scripts_relative_paths = [
        Path("pyscripts/setup.py"),       # SCRIPTS_DIR/pyscripts/setup.py
        Path("shell-scripts/setup.py"), # SCRIPTS_DIR/shell-scripts/setup.py
        MODULES_DIR.name + "/setup.py"    # e.g. "Modules/setup.py" or "modules/setup.py" relative to SCRIPTS_DIR
                                          # This should be SCRIPTS_DIR / MODULES_DIR.name / "setup.py"
                                          # Or simply MODULES_DIR / "setup.py"
    ]
    
    # Correcting the path for modules/setup.py
    # The script `modules/setup.py` is directly within the MODULES_DIR (e.g. scripts/Modules/setup.py)
    # NOT scripts/Modules/Modules/setup.py
    # And it's not relative to SCRIPTS_DIR in the same way as pyscripts is.
    # It should be MODULES_DIR / "setup.py" for the full path.

    # The list should be paths to setup scripts.
    # modules/setup.py is at SCRIPTS_DIR/modules/setup.py or SCRIPTS_DIR/Modules/setup.py
    # So, MODULES_DIR / "setup.py" is the full path.
    # The loop constructs SCRIPTS_DIR / rel_script_path.
    # So rel_script_path for modules/setup.py should be MODULES_DIR.relative_to(SCRIPTS_DIR) / "setup.py"

    sub_setup_scripts_to_run = [
        SCRIPTS_DIR / "pyscripts" / "setup.py",
        SCRIPTS_DIR / "shell-scripts" / "setup.py",
        MODULES_DIR / "setup.py" # This is C:\...\scripts\Modules\setup.py
    ]


    for full_script_path in sub_setup_scripts_to_run:
        # Use a title that makes sense, e.g., its name or relative path from SCRIPTS_DIR
        try:
            title_rel_path = full_script_path.relative_to(SCRIPTS_DIR)
        except ValueError: # Not under SCRIPTS_DIR (should not happen with current construction)
            title_rel_path = full_script_path.name
            
        with active_section_mgr_class(f"Running sub-setup: {title_rel_path}"):
            run_setup(full_script_path, *common_setup_args)
            
    with active_section_mgr_class("Shell PATH Configuration (setup_path.py)"):
        setup_path_script = SCRIPTS_SETUP_DIR / "setup_path.py"
        path_args = [
            "--bin-dir", str(BIN_DIR),
            "--dotfiles-dir", str(DOTFILES_DIR)
        ]
        if args.verbose: path_args.append("--verbose")
        run_setup(setup_path_script, *path_args)

    if callable(print_global_elapsed): print_global_elapsed()
    else: print("[ERROR] print_global_elapsed not callable.") 


    if errors:
        sui_log_error(f"{len(errors)} error(s) occurred during setup. Details have been logged to '{ERROR_LOG}'.")
        sys.exit(1)
    else:
        sui_log_success("All setup steps completed successfully.")

if __name__ == "__main__":
    main()
