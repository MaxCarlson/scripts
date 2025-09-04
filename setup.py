#!/usr/bin/env python3
import os
import sys
import argparse
import platform
import importlib
import subprocess
from pathlib import Path
import time
from typing import Iterable

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
            importlib.invalidate_caches()
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
        set_verbose as real_set_verbose,
        log_info as real_sui_log_info,
        log_success as real_sui_log_success,
        log_warning as real_sui_log_warning,
        log_error as real_sui_log_error,
        section as real_sui_section,
        print_table as real_print_table,
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
            print(f"[INFO] Overall Elapsed Time: {elapsed:.2f} sec")
    def _fb_log_prefix(level, message): print(f"[{level}] {message}")
    def fb_log_info(message):
        if _is_verbose: _fb_log_prefix("INFO", message)
    def fb_log_success(message): _fb_log_prefix("SUCCESS", message)
    def fb_log_warning(message): _fb_log_prefix("WARNING", message)
    def fb_log_error(message): _fb_log_prefix("ERROR", message)
    class FallbackSectionClass:
        def __init__(self, title): self.title = title
        def __enter__(self):
            if _is_verbose: print(f"\n--- {self.title} - START ---")
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            if _is_verbose: print(f"--- {self.title} - END ---\n")
    init_timer, print_global_elapsed = fb_init_timer, fb_print_global_elapsed
    sui_log_info, sui_log_success = fb_log_info, fb_log_success
    sui_log_warning, sui_log_error = fb_log_warning, fb_log_error
    sui_section = FallbackSectionClass
    def real_set_verbose(_: bool): pass

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
            set_verbose as imported_set_verbose,
            log_info as imported_log_info,
            log_success as imported_log_success,
            log_warning as imported_log_warning,
            log_error as imported_log_error,
            section as imported_section,
        )
        init_timer = imported_init_timer
        print_global_elapsed = imported_print_global_elapsed
        imported_set_verbose(_is_verbose)
        sui_log_info = imported_log_info
        sui_log_success = imported_log_success
        sui_log_warning = imported_log_warning
        sui_log_error = imported_log_error
        sui_section = imported_section
        STANDARD_UI_AVAILABLE = True
        if callable(sui_log_success):
            sui_log_success("standard_ui activated.")
    except ImportError as e:
        if callable(warning_logger_before_reload):
            warning_logger_before_reload(f"standard_ui was installed, but failed to import dynamically (Error: {type(e).__name__}: {e}). Continuing with fallback logging.")

SCRIPTS_DIR = Path(__file__).resolve().parent
MODULES_DIR = SCRIPTS_DIR / "modules"
STANDARD_UI_SETUP_DIR = MODULES_DIR / "standard_ui"
CROSS_PLATFORM_DIR = MODULES_DIR / "cross_platform"
SCRIPTS_SETUP_PACKAGE_DIR = SCRIPTS_DIR / "scripts_setup"

DOTFILES_DIR = Path(os.environ.get("DOTFILES", SCRIPTS_DIR.parent / "dotfiles"))
BIN_DIR = SCRIPTS_DIR / "bin"

ERROR_LOG = SCRIPTS_DIR / "setup_errors.log"
errors = []
warnings = []

def _append_unique(lst: list, item: str):
    if item not in lst:
        lst.append(item)

def _write_error_block(title: str, stdout: str | None, stderr: str | None, rc: int | None = None):
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"=== {title} ==="]
    if rc is not None:
        lines.append(f"Return code: {rc}")
    lines.extend(["--- STDOUT ---", stdout or "<none>", "--- STDERR ---", stderr or "<none>", ""])
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))

def _get_canonical_package_name_from_source(module_source_path: Path, verbose: bool) -> str:
    pyproject_file = module_source_path / "pyproject.toml"
    package_name_from_dir = module_source_path.name
    logger = sui_log_info
    warn_logger = sui_log_warning
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
            if verbose: logger(f"{pyproject_file} found but 'project.name' or 'tool.poetry.name' not found. Using '{package_name_from_dir}'.")
        except tomllib.TOMLDecodeError as e:
            warn_logger(f"Could not parse {pyproject_file}: {e}. Using '{package_name_from_dir}'.")
        except Exception as e:
            warn_logger(f"Error reading {pyproject_file}: {type(e).__name__}: {e}. Using '{package_name_from_dir}'.")
    else:
        if verbose: logger(f"No pyproject.toml in {module_source_path}. Using '{package_name_from_dir}'.")
    return package_name_from_dir

def _get_current_install_mode(module_source_path: Path, verbose: bool) -> str | None:
    package_name_to_query = _get_canonical_package_name_from_source(module_source_path, verbose)
    logger = sui_log_info
    warn_logger = sui_log_warning
    try:
        pip_show_cmd = [sys.executable, "-m", "pip", "show", package_name_to_query]
        if verbose: logger(f"Running: {' '.join(pip_show_cmd)}")
        result = subprocess.run(pip_show_cmd, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode != 0:
            if verbose: logger(f"'{package_name_to_query}' not found by 'pip show' (rc: {result.returncode}).")
            return None
        output_lines = result.stdout.splitlines()
        for line in output_lines:
            if line.lower().startswith("editable project location:"):
                location_path_str = line.split(":", 1)[1].strip()
                if location_path_str and location_path_str.lower() != "none":
                    try:
                        if Path(location_path_str).resolve() == module_source_path.resolve():
                            if verbose: logger(f"'{package_name_to_query}' editable from expected source.")
                            return "editable"
                        else:
                            if verbose: warn_logger(f"'{package_name_to_query}' editable from different location.")
                    except Exception as e_path:
                        if verbose: warn_logger(f"Path comparison error for '{package_name_to_query}': {e_path}")
        if verbose: logger(f"'{package_name_to_query}' installed (non-editable).")
        return "normal"
    except Exception as e:
        warn_logger(f"Could not query 'pip show' for '{package_name_to_query}': {type(e).__name__}: {e}")
        return None

def ensure_module_installed(module_display_name: str, install_path: Path,
                            skip_reinstall: bool, editable: bool, verbose: bool,
                            soft_fail: bool = False):
    logger_info = sui_log_info
    logger_success = sui_log_success
    logger_warning = sui_log_warning
    logger_error = sui_log_error
    desired_install_mode = "editable" if editable else "normal"

    if skip_reinstall:
        current_install_mode = _get_current_install_mode(install_path, verbose)
        if current_install_mode:
            if current_install_mode == desired_install_mode:
                # Compact one-liner in non-verbose
                if verbose:
                    logger_success(
                        f"'{module_display_name}' is already installed in the desired '{current_install_mode}' mode from {install_path}. Skipping."
                    )
                else:
                    logger_success(f"{module_display_name}: already installed ({current_install_mode}). Skipping.")
                if module_display_name == "standard_ui" and not STANDARD_UI_AVAILABLE:
                    logger_info("standard_ui detected as installed but not active; attempting to activate...")
                    _try_reload_standard_ui_globally()
                return
            else:
                logger_info(
                    f"'{module_display_name}' is installed in '{current_install_mode}' mode, but '{desired_install_mode}' is desired (from {install_path}). Re-installing."
                )
        else:
            logger_info(f"{module_display_name}: not installed or status unknown. Installing.")
    else:
        logger_info(f"{module_display_name}: install requested.")
    install_cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        install_cmd.append("-e")
    resolved_install_path = install_path.resolve()
    install_cmd.append(str(resolved_install_path))
    if verbose:
        logger_info(f"Installing {module_display_name} from {resolved_install_path} {'(editable)' if editable else ''}...")
    proc = subprocess.run(install_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    if proc.returncode == 0:
        if verbose:
            logger_success(f"Successfully installed/updated {module_display_name}.")
        else:
            logger_success(f"{module_display_name}: installed.")
        if module_display_name == "standard_ui":
            _try_reload_standard_ui_globally()
    else:
        summary = f"Install {module_display_name} failed (rc: {proc.returncode})"
        _write_error_block(summary, proc.stdout, proc.stderr, proc.returncode)
        if soft_fail:
            logger_warning(f"{module_display_name}: install failed; continuing (see {ERROR_LOG}).")
            _append_unique(warnings, summary)
        else:
            logger_error(f"{module_display_name}: install failed (see {ERROR_LOG}).")
            _append_unique(errors, summary)

def run_setup(script_path: Path, *args, soft_fail_modules: bool = False):
    """
    Run a sub-setup script.
    - In non-verbose: only print a compact success line, or a compact error line with log path.
    - In verbose: include the sub-setup stdout as info and stderr as warning.
    - If soft_fail_modules=True and this is the modules/setup.py, downgrade failure to warning.
    """
    resolved_script_path = script_path.resolve()
    name_for_log = resolved_script_path.name
    if not resolved_script_path.exists():
        summary = f"Missing setup script: {name_for_log} at {resolved_script_path}"
        sui_log_warning(summary + "; skipping.")
        _append_unique(warnings, summary)
        return
    sui_log_info(f"Running {name_for_log} with args: {' '.join(args)}...")
    cmd = [sys.executable, str(resolved_script_path)]
    cmd.extend(args)
    env = os.environ.copy()
    python_path_to_add = [str(SCRIPTS_DIR.resolve()), str(MODULES_DIR.resolve())]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        python_path_to_add.extend(existing_pythonpath.split(os.pathsep))
    env["PYTHONPATH"] = os.pathsep.join(list(dict.fromkeys(filter(None, python_path_to_add))))
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding='utf-8', errors='ignore')
    target_is_modules = str(resolved_script_path).endswith(str(Path("modules") / "setup.py"))
    if proc.returncode == 0:
        # Compact success
        sui_log_success(f"{name_for_log} completed.")
        if _is_verbose:
            if proc.stdout and proc.stdout.strip():
                sui_log_info(proc.stdout.strip())
            if proc.stderr and proc.stderr.strip():
                sui_log_warning(proc.stderr.strip())
    else:
        title = f"Setup {name_for_log}"
        _write_error_block(title, proc.stdout, proc.stderr, proc.returncode)
        if soft_fail_modules and target_is_modules:
            sui_log_warning(f"{name_for_log} failed (rc: {proc.returncode}); continuing. See {ERROR_LOG}.")
            _append_unique(warnings, f"{name_for_log} failed (rc: {proc.returncode})")
        else:
            sui_log_error(f"{name_for_log} failed (rc: {proc.returncode}). See {ERROR_LOG}.")
            _append_unique(errors, f"{name_for_log} failed (rc: {proc.returncode})")

def main():
    global _is_verbose
    parser = argparse.ArgumentParser(description="Master setup script for managing project components.")
    parser.add_argument("--skip-reinstall", action="store_true",
                        help="Skip re-installation of Python modules if they are already present in the desired mode from the correct path.")
    parser.add_argument("--production", action="store_true",
                        help="Install Python modules in production mode (not editable).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable detailed output during the setup process.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress informational messages from fallback logger.")
    parser.add_argument("--soft-fail-modules", action="store_true",
                        help="Do not fail the master setup if modules/setup.py reports errors; warn and continue.")
    args = parser.parse_args()

    _is_verbose = args.verbose
    # Wire verbosity into standard_ui if available
    try:
        from standard_ui.standard_ui import set_verbose as _sui_set_verbose
        _sui_set_verbose(bool(args.verbose))
    except Exception:
        pass

    if callable(init_timer): init_timer()

    # Clean previous error log quietly in verbose; silent in compact mode
    if ERROR_LOG.exists():
        try:
            ERROR_LOG.unlink()
            if _is_verbose:
                sui_log_info(f"Cleared previous error log: {ERROR_LOG}")
        except OSError as e:
            sui_log_warning(f"Could not clear previous error log {ERROR_LOG}: {e}")

    # Context: short header info only in verbose to keep compact mode tidy
    if _is_verbose:
        sui_log_info("=== Running Master Setup Script ===")
        sui_log_info(f"Operating System: {platform.system()} ({os.name}), Release: {platform.release()}")
        sui_log_info(f"Python Version: {sys.version.split()[0]}")
        sui_log_info(f"Python Executable: {sys.executable}")
        sui_log_info(f"SCRIPTS_DIR: {SCRIPTS_DIR}")
        sui_log_info(f"MODULES_DIR: {MODULES_DIR}")
        sui_log_info(f"STANDARD_UI_SETUP_DIR: {STANDARD_UI_SETUP_DIR}")
        sui_log_info(f"SCRIPTS_SETUP_PACKAGE_DIR: {SCRIPTS_SETUP_PACKAGE_DIR}")
        sui_log_info(f"DOTFILES_DIR: {DOTFILES_DIR}")
        sui_log_info(f"Target BIN_DIR: {BIN_DIR}")

    # Ensure bin dir exists
    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        if _is_verbose:
            sui_log_info(f"Ensured bin directory exists: {BIN_DIR}")
    except OSError as e:
        _append_unique(errors, f"Bin directory creation failed for {BIN_DIR}: {e}")
        sui_log_error(f"Bin directory creation failed for {BIN_DIR}: {e}")

    active_section_mgr_class = sui_section

    # Core modules (compact per-module lines unless -v)
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
            sui_log_warning(f"standard_ui setup files not found in {module_path_standard_ui}.")

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
            sui_log_warning(f"scripts_setup package files not found in {module_path_scripts_setup}.")

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
            sui_log_warning(f"cross_platform setup files not found in {module_path_cross_platform}.")

    # WSL2 step
    if "microsoft" in platform.uname().release.lower() and "WSL" in platform.uname().release.upper():
        with active_section_mgr_class("WSL2 Specific Setup"):
            sui_log_info("Detected WSL2; running win32yank setup...")
            wsl_setup_args = []
            if args.verbose: wsl_setup_args.append("--verbose")
            run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_wsl2.py", *wsl_setup_args)
    else:
        sui_log_success("Not WSL2; skipping win32yank setup.")

    # Common args to sub-setups
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
            run_setup(full_script_path, *common_setup_args, soft_fail_modules=args.soft_fail_modules)

    # PATH (POSIX/Windows handler delegated)
    with active_section_mgr_class("Shell PATH Configuration (setup_path.py)"):
        setup_path_script = SCRIPTS_SETUP_PACKAGE_DIR / "setup_path.py"
        path_args = [
            "--bin-dir", str(BIN_DIR),
            "--dotfiles-dir", str(DOTFILES_DIR)
        ]
        if args.verbose: path_args.append("--verbose")
        run_setup(setup_path_script, *path_args)

    # Final elapsed + summary
    if callable(print_global_elapsed): print_global_elapsed()

    if errors:
        sui_log_error(f"Setup completed with {len(errors)} error(s). See {ERROR_LOG}.")
        # Ensure at least a summary exists in the log
        if not ERROR_LOG.exists():
            try:
                ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
                with open(ERROR_LOG, "w", encoding="utf-8") as f:
                    f.write("=== Summary of Errors Encountered During Setup ===\n")
                    for i, err_msg in enumerate(errors):
                        f.write(f"{i+1}. {err_msg}\n")
            except Exception as e_log_write:
                sui_log_warning(f"Failed to write error summary to '{ERROR_LOG}': {e_log_write}")
        sys.exit(1)
    elif warnings:
        sui_log_warning(f"Setup completed with {len(warnings)} warning(s). See {ERROR_LOG} for details.")
        sys.exit(0)
    else:
        sui_log_success("All setup steps completed successfully.")
        sys.exit(0)

if __name__ == "__main__":
    main()
