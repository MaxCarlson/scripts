#!/usr/bin/env python3
import os
import sys
import argparse
import platform
import importlib
import subprocess
from pathlib import Path
import time

# --- Bootstrap tomli if not available ---
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("[INFO] 'tomli' (for TOML parsing) not found. Attempting to install it...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "tomli"])
            importlib.invalidate_caches() # Ensure new import can be found
            import tomli as tomllib
            print("[SUCCESS] Successfully installed 'tomli'.")
        except Exception as e_tomli:
            print(f"[ERROR] Failed to install 'tomli': {e_tomli}", file=sys.stderr)
            print("[ERROR] This script requires 'tomli' for TOML parsing (e.g., pyproject.toml). Please install it manually ('pip install tomli') and try again.", file=sys.stderr)
            sys.exit(1)


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
    def fb_log_info(message):
        if _is_verbose: _fb_log_prefix("INFO", message)
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
        sui_section = imported_section

        STANDARD_UI_AVAILABLE = True
        if callable(sui_log_success):
            sui_log_success("Successfully switched to standard_ui logging dynamically.")
    except ImportError as e:
        if callable(warning_logger_before_reload):
            warning_logger_before_reload(f"standard_ui was installed, but failed to import dynamically for global update (Error: {type(e).__name__}: {e}). Previous logging functions remain active.")

SCRIPTS_DIR = Path(__file__).resolve().parent
MODULES_DIR = SCRIPTS_DIR / "modules"
STANDARD_UI_SETUP_DIR = MODULES_DIR / "standard_ui"
CROSS_PLATFORM_DIR = MODULES_DIR / "cross_platform"
SCRIPTS_SETUP_PACKAGE_DIR = SCRIPTS_DIR / "scripts_setup"

DOTFILES_DIR = Path(os.environ.get("DOTFILES", SCRIPTS_DIR.parent / "dotfiles"))
BIN_DIR = SCRIPTS_DIR / "bin"

ERROR_LOG = SCRIPTS_DIR / "setup_errors.log"
errors = []

def write_error_log_detail(title: str, proc: subprocess.CompletedProcess):
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e_mkdir:
        (sui_log_warning if STANDARD_UI_AVAILABLE else fb_log_warning)(
            f"Could not create parent directory for error log {ERROR_LOG.parent}: {e_mkdir}"
        )

    msg_lines = [f"=== {title} ===",
                 f"Return code: {proc.returncode}",
                 "--- STDOUT ---", proc.stdout or "<none>",
                 "--- STDERR ---", proc.stderr or "<none>", ""]
    log_content = "\n".join(msg_lines) + "\n"

    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(log_content)
    except Exception as e:
        (sui_log_error if STANDARD_UI_AVAILABLE else fb_log_error)(
            f"Critical error: Could not write detailed error to log {ERROR_LOG}. Reason: {e}\n"
            f"Error details: {log_content}"
        )

def _get_canonical_package_name_from_source(module_source_path: Path, verbose: bool) -> str:
    pyproject_file = module_source_path / "pyproject.toml"
    package_name_from_dir = module_source_path.name

    logger = sui_log_info if STANDARD_UI_AVAILABLE else fb_log_info
    warn_logger = sui_log_warning if STANDARD_UI_AVAILABLE else fb_log_warning

    if pyproject_file.is_file():
        try:
            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)
            if "project" in data and "name" in data["project"]:
                name = data["project"]["name"]
                if verbose: logger(f"Found package name '{name}' in {pyproject_file}")
                return name
            if "tool" in data and "poetry" in data and "name" in data["tool"]["poetry"]:
                name = data["tool"]["poetry"]["name"]
                if verbose: logger(f"Found poetry package name '{name}' in {pyproject_file}")
                return name
            if verbose: logger(f"{pyproject_file} found but 'project.name' or 'tool.poetry.name' not found. Falling back to dir name '{package_name_from_dir}'.")
        except tomllib.TOMLDecodeError as e:
            warn_logger(f"Could not parse {pyproject_file}: {e}. Falling back to dir name '{package_name_from_dir}'.")
        except Exception as e:
            warn_logger(f"Error reading/parsing {pyproject_file}: {type(e).__name__}: {e}. Falling back to dir name '{package_name_from_dir}'.")
    else:
        if verbose: logger(f"No pyproject.toml found in {module_source_path}. Using dir name '{package_name_from_dir}' as package name.")
    return package_name_from_dir

def _get_current_install_mode(module_source_path: Path, verbose: bool) -> str | None:
    package_name_to_query = _get_canonical_package_name_from_source(module_source_path, verbose)
    logger = sui_log_info if STANDARD_UI_AVAILABLE else fb_log_info
    warn_logger = sui_log_warning if STANDARD_UI_AVAILABLE else fb_log_warning

    try:
        pip_show_cmd = [sys.executable, "-m", "pip", "show", package_name_to_query]
        if verbose: logger(f"Running: {' '.join(pip_show_cmd)}")
        result = subprocess.run(pip_show_cmd, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')

        if result.returncode != 0:
            if verbose: logger(f"'{package_name_to_query}' not found by 'pip show' (rc: {result.returncode}). Assuming not installed.")
            return None

        output_lines = result.stdout.splitlines()
        is_our_editable_install = False
        for line in output_lines:
            if line.lower().startswith("editable project location:"):
                location_path_str = line.split(":", 1)[1].strip()
                if location_path_str and location_path_str.lower() != "none":
                    try:
                        editable_loc = Path(location_path_str).resolve()
                        source_loc = module_source_path.resolve()
                        if editable_loc == source_loc:
                            if verbose: logger(f"'{package_name_to_query}' is editable from expected source: {source_loc}")
                            is_our_editable_install = True
                        else:
                            if verbose: warn_logger(f"'{package_name_to_query}' is editable, but from different location: {editable_loc} (expected {source_loc})")
                        break
                    except Exception as e_path:
                        if verbose: warn_logger(f"Path resolution/comparison error for '{package_name_to_query}': {e_path}")
                        break
        
        if is_our_editable_install:
            return "editable"
        
        if verbose: logger(f"'{package_name_to_query}' found by 'pip show', but not (or not our) editable install. Treating as 'normal'.")
        return "normal"

    except Exception as e:
        warn_logger(f"Could not query 'pip show' for '{package_name_to_query}': {type(e).__name__}: {e}")
        return None

def ensure_module_installed(module_display_name: str, install_path: Path,
                            skip_reinstall: bool, editable: bool, verbose: bool):
    logger_info = sui_log_info if STANDARD_UI_AVAILABLE else fb_log_info
    logger_success = sui_log_success if STANDARD_UI_AVAILABLE else fb_log_success
    logger_warning = sui_log_warning if STANDARD_UI_AVAILABLE else fb_log_warning
    logger_error = sui_log_error if STANDARD_UI_AVAILABLE else fb_log_error

    desired_install_mode = "editable" if editable else "normal"
    
    if skip_reinstall:
        current_install_mode = _get_current_install_mode(install_path, verbose)
        if current_install_mode:
            if current_install_mode == desired_install_mode:
                logger_success(
                    f"'{module_display_name}' is already installed in the desired '{current_install_mode}' mode from {install_path}. Skipping."
                )
                if module_display_name == "standard_ui" and not STANDARD_UI_AVAILABLE:
                    logger_info("standard_ui detected as installed but not active; attempting to activate...")
                    _try_reload_standard_ui_globally()
                return
            else:
                logger_info(
                    f"'{module_display_name}' is installed in '{current_install_mode}' mode, but '{desired_install_mode}' mode is desired (from {install_path}). Re-installing."
                )
        else:
            logger_info(f"'{module_display_name}' (from {install_path}) not found or status unknown. Proceeding with installation.")
    else:
        logger_info(f"'{module_display_name}' installation requested (skip-reinstall not active). Proceeding.")

    install_cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        install_cmd.append("-e")
    resolved_install_path = install_path.resolve()
    install_cmd.append(str(resolved_install_path))

    logger_info(f"Installing {module_display_name} from {resolved_install_path} {'(editable)' if editable else ''}...")
    
    proc = subprocess.run(install_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    if proc.returncode == 0:
        logger_success(f"Successfully installed/updated {module_display_name}.")
        if module_display_name == "standard_ui": # Always try to reload after standard_ui install/update
            _try_reload_standard_ui_globally()
    else:
        error_summary = f"Installation of {module_display_name} failed (rc: {proc.returncode})"
        logger_error(error_summary + "; see log and console for details.")
        logger_error(f"Pip stdout: {proc.stdout.strip() if proc.stdout else '<empty>'}")
        logger_error(f"Pip stderr: {proc.stderr.strip() if proc.stderr else '<empty>'}")
        write_error_log_detail(f"Install {module_display_name}", proc)
        if error_summary not in errors: errors.append(error_summary)


def run_setup(script_path: Path, *args):
    resolved_script_path = script_path.resolve()
    if not resolved_script_path.exists():
        error_summary = f"Missing setup script: {resolved_script_path.name} at {resolved_script_path}"
        sui_log_warning(error_summary + "; skipping.")
        if error_summary not in errors: errors.append(error_summary)
        return

    sui_log_info(f"Running {resolved_script_path.name} with args: {' '.join(args)}...")
    cmd = [sys.executable, str(resolved_script_path)]
    cmd.extend(args)

    env = os.environ.copy()
    python_path_to_add = [str(SCRIPTS_DIR.resolve()), str(MODULES_DIR.resolve())]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        python_path_to_add.extend(existing_pythonpath.split(os.pathsep))
    env["PYTHONPATH"] = os.pathsep.join(list(dict.fromkeys(filter(None, python_path_to_add))))
    env["PYTHONIOENCODING"] = "utf-8"

    if _is_verbose:
        sui_log_info(f"Subprocess PYTHONPATH for {resolved_script_path.name}: {env['PYTHONPATH']}")
        sui_log_info(f"Subprocess PYTHONIOENCODING for {resolved_script_path.name}: {env['PYTHONIOENCODING']}")

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding='utf-8', errors='ignore')
    if proc.returncode == 0:
        sui_log_success(f"{resolved_script_path.name} completed.")
        # MODIFICATION: Always print stdout from sub-scripts if it's not empty.
        # Sub-scripts should manage their own verbosity for debug logs.
        # Stdout here is assumed to be summary/important info.
        if proc.stdout and proc.stdout.strip():
            sui_log_info(f"Output from {resolved_script_path.name}:\n{proc.stdout.strip()}")
        if proc.stderr and proc.stderr.strip(): # Always show stderr as it might be important warnings
            sui_log_warning(f"Stderr from {resolved_script_path.name} (may be informational):\n{proc.stderr.strip()}")
    else:
        error_summary = f"Execution of {resolved_script_path.name} failed (rc: {proc.returncode})"
        sui_log_error(error_summary + "; see log and console for details.")
        sui_log_error(f"Subprocess stdout for {resolved_script_path.name}:\n{proc.stdout.strip() or '<empty>'}")
        sui_log_error(f"Subprocess stderr for {resolved_script_path.name}:\n{proc.stderr.strip() or '<empty>'}")
        write_error_log_detail(f"Setup {resolved_script_path.name}", proc)
        if error_summary not in errors: errors.append(error_summary)

def main():
    global _is_verbose
    parser = argparse.ArgumentParser(description="Master setup script for managing project components.")
    parser.add_argument("--skip-reinstall", action="store_true",
                        help="Skip re-installation of Python modules if they are already present AND in the desired installation mode from the correct source path.")
    parser.add_argument("--production", action="store_true",
                        help="Install Python modules in production mode (not editable, i.e., no '-e').")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable detailed output during the setup process.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress informational messages (mainly for fallback logger).")
    args = parser.parse_args()

    _is_verbose = args.verbose

    if callable(init_timer): init_timer()
    else: fb_log_error("init_timer is not callable at script start.")

    if not STANDARD_UI_AVAILABLE and not args.quiet:
        (sui_log_info if STANDARD_UI_AVAILABLE else fb_log_info)("Attempting to install standard_ui as part of the setup...")

    if ERROR_LOG.exists():
        try:
            ERROR_LOG.unlink()
            if _is_verbose: (sui_log_info if STANDARD_UI_AVAILABLE else fb_log_info)(f"Cleared previous error log: {ERROR_LOG}")
        except OSError as e:
            (sui_log_warning if STANDARD_UI_AVAILABLE else fb_log_warning)(f"Could not clear previous error log {ERROR_LOG}: {e}")

    sui_log_info("=== Running Master Setup Script ===")
    sui_log_info(f"Operating System: {platform.system()} ({os.name}), Release: {platform.release()}")
    sui_log_info(f"Python Version: {sys.version.split()[0]}")
    sui_log_info(f"Python Executable: {sys.executable}")
    sui_log_info(f"SCRIPTS_DIR: {SCRIPTS_DIR}")
    sui_log_info(f"MODULES_DIR (using 'modules' lowercase): {MODULES_DIR}")
    sui_log_info(f"STANDARD_UI_SETUP_DIR: {STANDARD_UI_SETUP_DIR}")
    sui_log_info(f"SCRIPTS_SETUP_PACKAGE_DIR: {SCRIPTS_SETUP_PACKAGE_DIR}")
    sui_log_info(f"DOTFILES_DIR: {DOTFILES_DIR}")
    sui_log_info(f"Target BIN_DIR: {BIN_DIR}")

    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        sui_log_info(f"Ensured bin directory exists: {BIN_DIR}")
    except OSError as e:
        error_summary = f"Bin directory creation failed for {BIN_DIR}: {e}"
        sui_log_error(error_summary)
        if error_summary not in errors: errors.append(error_summary)

    active_section_mgr_class = sui_section

    with active_section_mgr_class("Core Module Installation"):
        module_path_standard_ui = STANDARD_UI_SETUP_DIR
        if module_path_standard_ui.is_dir() and \
           ((module_path_standard_ui / "setup.py").exists() or (module_path_standard_ui / "pyproject.toml").exists()):
            ensure_module_installed(
                "standard_ui", module_path_standard_ui,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production,
                verbose=args.verbose
            )
        else:
            sui_log_warning(f"standard_ui setup files not found in {module_path_standard_ui} or it's not a directory.")

        module_path_scripts_setup = SCRIPTS_SETUP_PACKAGE_DIR
        if module_path_scripts_setup.is_dir() and \
           ((module_path_scripts_setup / "setup.py").exists() or (module_path_scripts_setup / "pyproject.toml").exists()):
            ensure_module_installed(
                "scripts_setup", module_path_scripts_setup,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production,
                verbose=args.verbose
            )
        else:
            sui_log_warning(f"scripts_setup package files not found in {module_path_scripts_setup} or it's not a directory.")

        module_path_cross_platform = CROSS_PLATFORM_DIR
        if module_path_cross_platform.is_dir() and \
           ((module_path_cross_platform / "setup.py").exists() or (module_path_cross_platform / "pyproject.toml").exists()):
            ensure_module_installed(
                "cross_platform", module_path_cross_platform,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production,
                verbose=args.verbose
            )
        else:
            sui_log_warning(f"cross_platform setup files not found in {module_path_cross_platform} or it's not a directory.")


    if "microsoft" in platform.uname().release.lower() and "WSL" in platform.uname().release.upper():
        with active_section_mgr_class("WSL2 Specific Setup"):
            sui_log_info("Detected WSL2; attempting to run win32yank setup...")
            wsl_setup_args = []
            if args.verbose: wsl_setup_args.append("--verbose")
            run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_wsl2.py", *wsl_setup_args)
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

    sub_setup_scripts_to_run = [
        SCRIPTS_DIR / "pyscripts" / "setup.py",
        SCRIPTS_DIR / "shell-scripts" / "setup.py",
        MODULES_DIR / "setup.py"
    ]

    for full_script_path in sub_setup_scripts_to_run:
        try:
            title_rel_path = full_script_path.relative_to(SCRIPTS_DIR)
        except ValueError:
            title_rel_path = full_script_path.name
        with active_section_mgr_class(f"Running sub-setup: {title_rel_path}"):
            run_setup(full_script_path, *common_setup_args)

    with active_section_mgr_class("Shell PATH Configuration (setup_path.py)"):
        setup_path_script = SCRIPTS_SETUP_PACKAGE_DIR / "setup_path.py"
        path_args = [
            "--bin-dir", str(BIN_DIR),
            "--dotfiles-dir", str(DOTFILES_DIR)
        ]
        if args.verbose: path_args.append("--verbose")
        run_setup(setup_path_script, *path_args)

    if callable(print_global_elapsed): print_global_elapsed()
    else: (sui_log_error if STANDARD_UI_AVAILABLE else fb_log_error)("print_global_elapsed not callable at script end.")

    if errors:
        sui_log_error(f"Setup completed with {len(errors)} error(s).")
        if not ERROR_LOG.exists() and errors:
            sui_log_warning(f"Error log file '{ERROR_LOG}' was not created by detailed writers, creating with summary.")
            try:
                ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
                with open(ERROR_LOG, "w", encoding="utf-8") as f:
                    f.write("=== Summary of Errors Encountered During Setup ===\n")
                    for i, err_msg in enumerate(errors):
                        f.write(f"{i+1}. {err_msg}\n")
                sui_log_info(f"Error summary written to '{ERROR_LOG}'.")
            except Exception as e_log_write:
                sui_log_error(f"Failed to write error summary to '{ERROR_LOG}': {e_log_write}")
        elif ERROR_LOG.exists():
             sui_log_info(f"Detailed errors have been logged to '{ERROR_LOG}'.")
        sys.exit(1)
    else:
        sui_log_success("All setup steps completed successfully.")

if __name__ == "__main__":
    main()
