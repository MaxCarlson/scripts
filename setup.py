#!/usr/bin/env python3
import os
import sys
import argparse
import platform
import importlib
import subprocess
from pathlib import Path
import time
import re

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
status_line = None
blank = None
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
        section as real_sui_section,
        status_line as real_status_line,
        blank as real_blank,
    )
    init_timer = real_init_timer
    print_global_elapsed = real_print_global_elapsed
    sui_log_info = real_sui_log_info
    sui_log_success = real_sui_log_success
    sui_log_warning = real_sui_log_warning
    sui_log_error = real_sui_log_error
    sui_section = real_sui_section
    status_line = real_status_line
    blank = real_blank
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
        def __init__(self, title, level="major"): self.title = title
        def __enter__(self):
            if _is_verbose: print(f"\n--- {self.title} - START ---")
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            if _is_verbose: print(f"--- {self.title} - END ---\n")

    def fb_blank(lines: int = 1):
        print("\n" * max(1, lines), end="")

    def fb_status_line(label: str, state: str, detail: str | None = None):
        prefix = {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}.get(state, "•")
        tail = f" — {detail}" if detail else ""
        print(f"[{prefix}] {label}{tail}")

    init_timer, print_global_elapsed = fb_init_timer, fb_print_global_elapsed
    sui_log_info, sui_log_success = fb_log_info, fb_log_success
    sui_log_warning, sui_log_error = fb_log_warning, fb_log_error
    sui_section = FallbackSectionClass
    status_line = fb_status_line
    blank = fb_blank
    if '--quiet' not in sys.argv:
        fb_log_warning("standard_ui module not found initially. Using basic print for logging.")

# --- Helper function to dynamically reload standard_ui functions globally ---
def _try_reload_standard_ui_globally():
    global init_timer, print_global_elapsed, sui_log_info, sui_log_success
    global sui_log_warning, sui_log_error, sui_section, status_line, blank, STANDARD_UI_AVAILABLE
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
            status_line as imported_status_line,
            blank as imported_blank,
        )
        init_timer = imported_init_timer
        print_global_elapsed = imported_print_global_elapsed
        sui_log_info = imported_log_info
        sui_log_success = imported_log_success
        sui_log_warning = imported_log_warning
        sui_log_error = imported_log_error
        sui_section = imported_section
        status_line = imported_status_line
        blank = imported_blank
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
errors: list[str] = []
warnings: list[str] = []

def _append_unique(bucket: list[str], item: str):
    if item not in bucket:
        bucket.append(item)

def write_error_log_detail(title: str, proc: subprocess.CompletedProcess):
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e_mkdir:
        (sui_log_warning)(f"Could not create parent directory for error log {ERROR_LOG.parent}: {e_mkdir}")
    msg_lines = [
        f"=== {title} ===",
        f"Return code: {proc.returncode}",
        "--- STDOUT ---",
        proc.stdout or "<none>",
        "--- STDERR ---",
        proc.stderr or "<none>",
        "",
    ]
    log_content = "\n".join(msg_lines) + "\n"
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(log_content)
    except Exception as e:
        sui_log_error(
            f"Critical error: Could not write detailed error to log {ERROR_LOG}. Reason: {e}\n"
            f"Error details: {log_content}"
        )

def _get_canonical_package_name_from_source(module_source_path: Path, verbose: bool) -> str:
    pyproject_file = module_source_path / "pyproject.toml"
    package_name_from_dir = module_source_path.name
    if pyproject_file.is_file():
        try:
            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)
            if "project" in data and "name" in data["project"]:
                return data["project"]["name"]
            if "tool" in data and "poetry" in data and "name" in data["tool"]["poetry"]:
                return data["tool"]["poetry"]["name"]
        except Exception:
            pass
    return package_name_from_dir

def _get_current_install_mode(module_source_path: Path, verbose: bool) -> str | None:
    package_name_to_query = _get_canonical_package_name_from_source(module_source_path, verbose)
    try:
        pip_show_cmd = [sys.executable, "-m", "pip", "show", package_name_to_query]
        result = subprocess.run(pip_show_cmd, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode != 0:
            return None
        is_our_editable_install = False
        for line in result.stdout.splitlines():
            if line.lower().startswith("editable project location:"):
                location_path_str = line.split(":", 1)[1].strip()
                if location_path_str and location_path_str.lower() != "none":
                    try:
                        editable_loc = Path(location_path_str).resolve()
                        source_loc = module_source_path.resolve()
                        if editable_loc == source_loc:
                            is_our_editable_install = True
                        break
                    except Exception:
                        break
        if is_our_editable_install:
            return "editable"
        return "normal"
    except Exception:
        return None

def ensure_module_installed(module_display_name: str, install_path: Path,
                            skip_reinstall: bool, editable: bool, verbose: bool,
                            soft_fail: bool = False):
    desired_install_mode = "editable" if editable else "normal"

    if skip_reinstall:
        current_install_mode = _get_current_install_mode(install_path, verbose)
        if current_install_mode:
            if current_install_mode == desired_install_mode:
                # one-liner for unchanged
                status_line(f"{module_display_name}: already installed ({current_install_mode})", "unchanged", "skip")
                if module_display_name == "standard_ui" and not STANDARD_UI_AVAILABLE:
                    _try_reload_standard_ui_globally()
                return
            else:
                sui_log_info(
                    f"{module_display_name} is installed in '{current_install_mode}' mode, but '{desired_install_mode}' is desired (from {install_path}). Re-installing."
                )
        else:
            sui_log_info(f"{module_display_name} (from {install_path}) not found or status unknown. Proceeding with installation.")
    else:
        sui_log_info(f"{module_display_name} installation requested (skip-reinstall not active). Proceeding.")

    install_cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        install_cmd.append("-e")
    resolved_install_path = install_path.resolve()
    install_cmd.append(str(resolved_install_path))
    proc = subprocess.run(install_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')

    if proc.returncode == 0:
        status_line(f"{module_display_name}: installed", "ok", "editable" if editable else None)
        if module_display_name == "standard_ui":
            _try_reload_standard_ui_globally()
    else:
        # log full details to file
        write_error_log_detail(f"Install {module_display_name}", proc)
        if soft_fail:
            status_line(f"{module_display_name}: install failed; continuing", "warn", f"see {ERROR_LOG}")
            _append_unique(warnings, f"Installation of {module_display_name} failed (rc: {proc.returncode})")
        else:
            status_line(f"{module_display_name}: install failed", "fail", f"see {ERROR_LOG}")
            _append_unique(errors, f"Installation of {module_display_name} failed (rc: {proc.returncode})")

def run_setup(script_path: Path, *args, soft_fail_modules: bool = False):
    resolved_script_path = script_path.resolve()
    if not resolved_script_path.exists():
        msg = f"Missing setup script: {resolved_script_path.name} at {resolved_script_path}"
        sui_log_warning(msg + "; skipping.")
        _append_unique(warnings, msg)
        return

    # invoke the sub-setup
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

    if proc.returncode == 0:
        status_line(f"{resolved_script_path.name} completed.", "ok")
        if _is_verbose and proc.stdout and proc.stdout.strip():
            sui_log_info(proc.stdout.strip())
        if _is_verbose and proc.stderr and proc.stderr.strip():
            sui_log_warning(proc.stderr.strip())
    else:
        # Try to parse FAILED_MODULE: <name> tokens from stdout for a quick hint
        failed = re.findall(r"FAILED_MODULE:\s*([A-Za-z0-9_.\-]+)", proc.stdout or "")
        hint = f"failed (rc: {proc.returncode})"
        if failed:
            hint = f"failed for {', '.join(sorted(set(failed)))} (rc: {proc.returncode})"
        if soft_fail_modules:
            status_line(f"{resolved_script_path.name} {hint}; continuing", "warn", f"see {ERROR_LOG}")
            _append_unique(warnings, f"{resolved_script_path.name} {hint}")
        else:
            status_line(f"{resolved_script_path.name} {hint}", "fail", f"see {ERROR_LOG}")
            _append_unique(errors, f"{resolved_script_path.name} {hint}")
        write_error_log_detail(f"Setup {resolved_script_path.name}", proc)

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
    parser.add_argument("--soft-fail-modules", action="store_true",
                        help="Do not halt when a sub-setup (modules/setup.py) fails; continue and record as a warning.")
    args = parser.parse_args()

    _is_verbose = args.verbose
    if callable(init_timer): init_timer()

    if ERROR_LOG.exists():
        try:
            ERROR_LOG.unlink()
            if _is_verbose: sui_log_info(f"Cleared previous error log: {ERROR_LOG}")
        except OSError as e:
            sui_log_warning(f"Could not clear previous error log {ERROR_LOG}: {e}")

    with sui_section("Core Module Installation", level="major"):
        # standard_ui
        module_path_standard_ui = STANDARD_UI_SETUP_DIR
        if module_path_standard_ui.is_dir() and ((module_path_standard_ui / "setup.py").exists() or (module_path_standard_ui / "pyproject.toml").exists()):
            ensure_module_installed(
                "standard_ui", module_path_standard_ui,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production,
                verbose=args.verbose,
                soft_fail=args.soft_fail_modules,
            )
        else:
            sui_log_warning(f"standard_ui setup files not found in {module_path_standard_ui} or it's not a directory.")

        # scripts_setup
        module_path_scripts_setup = SCRIPTS_SETUP_PACKAGE_DIR
        if module_path_scripts_setup.is_dir() and ((module_path_scripts_setup / "setup.py").exists() or (module_path_scripts_setup / "pyproject.toml").exists()):
            ensure_module_installed(
                "scripts_setup", module_path_scripts_setup,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production,
                verbose=args.verbose,
                soft_fail=args.soft_fail_modules,
            )
        else:
            sui_log_warning(f"scripts_setup package files not found in {module_path_scripts_setup} or it's not a directory.")

        # cross_platform
        module_path_cross_platform = CROSS_PLATFORM_DIR
        if module_path_cross_platform.is_dir() and ((module_path_cross_platform / "setup.py").exists() or (module_path_cross_platform / "pyproject.toml").exists()):
            ensure_module_installed(
                "cross_platform", module_path_cross_platform,
                skip_reinstall=args.skip_reinstall,
                editable=not args.production,
                verbose=args.verbose,
                soft_fail=args.soft_fail_modules,
            )
        else:
            sui_log_warning(f"cross_platform setup files not found in {module_path_cross_platform} or it's not a directory.")

    # WSL2?
    if "microsoft" in platform.uname().release.lower() and "WSL" in platform.uname().release.upper():
        with sui_section("WSL2 Specific Setup", level="medium"):
            run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_wsl2.py", *([] if not args.verbose else ["--verbose"]))
    else:
        status_line("Not WSL2; skipping win32yank setup.", "unchanged")

    # common args for sub-setups
    common_setup_args = [
        "--scripts-dir", str(SCRIPTS_DIR),
        "--dotfiles-dir", str(DOTFILES_DIR),
        "--bin-dir", str(BIN_DIR)
    ]
    if args.verbose: common_setup_args.append("--verbose")
    if args.skip_reinstall: common_setup_args.append("--skip-reinstall")
    if args.production: common_setup_args.append("--production")

    # sub-setup runners
    sub_setup_scripts_to_run = [
        SCRIPTS_DIR / "pyscripts" / "setup.py",
        SCRIPTS_DIR / "shell-scripts" / "setup.py",
        MODULES_DIR / "setup.py",
    ]
    for full_script_path in sub_setup_scripts_to_run:
        try:
            title_rel_path = full_script_path.relative_to(SCRIPTS_DIR)
        except ValueError:
            title_rel_path = full_script_path.name
        with sui_section(f"Running sub-setup: {title_rel_path}", level="medium"):
            run_setup(full_script_path, *common_setup_args, soft_fail_modules=args.soft_fail_modules)

    with sui_section("Shell PATH Configuration (setup_path.py)", level="major"):
        setup_path_script = SCRIPTS_SETUP_PACKAGE_DIR / "setup_path.py"
        path_args = ["--bin-dir", str(BIN_DIR), "--dotfiles-dir", str(DOTFILES_DIR)]
        if args.verbose: path_args.append("--verbose")
        run_setup(setup_path_script, *path_args)

    print_global_elapsed()

    if errors:
        if not ERROR_LOG.exists():
            try:
                ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
                with open(ERROR_LOG, "w", encoding="utf-8") as f:
                    f.write("=== Summary of Errors Encountered During Setup ===\n")
                    for i, err_msg in enumerate(errors):
                        f.write(f"{i+1}. {err_msg}\n")
            except Exception as e_log_write:
                sui_log_error(f"Failed to write error summary to '{ERROR_LOG}': {e_log_write}")
        if warnings:
            sui_log_warning(f"Setup completed with {len(errors)} error(s) and {len(warnings)} warning(s). See {ERROR_LOG}.")
        else:
            sui_log_error(f"Setup completed with {len(errors)} error(s). See {ERROR_LOG}.")
        sys.exit(1 if not warnings else 1)
    elif warnings:
        sui_log_warning(f"Setup completed with {len(warnings)} warning(s). See {ERROR_LOG}.")
        sys.exit(0)
    else:
        sui_log_success("All setup steps completed successfully.")
        sys.exit(0)

if __name__ == "__main__":
    main()
