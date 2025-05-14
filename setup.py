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

ERROR_LOG = SCRIPTS_DIR / "setup_errors.log"
errors = []

def write_error_log(title: str, proc: subprocess.CompletedProcess):
    msg = [f"=== {title} ===",
           f"Return code: {proc.returncode}",
           "--- STDOUT ---", proc.stdout or "<none>",
           "--- STDERR ---", proc.stderr or "<none>", ""]
    ERROR_LOG.write_text(("\n".join(msg) + "\n"), append=True)

def ensure_module_installed(module_import: str, install_path: Path,
                            skip_reinstall: bool, editable: bool):
    try:
        importlib.import_module(module_import)
        log_success(f"{module_import} is already installed.")
        if skip_reinstall:
            return
        # otherwise fall through to reinstall if desired
    except ImportError:
        if skip_reinstall:
            log_warning(f"Skipping installation of missing module '{module_import}'.")
            return

    install_cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        install_cmd.append("-e")
    install_cmd.append(str(install_path))

    log_info(f"Installing {module_import} from {install_path}...")
    proc = subprocess.run(install_cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        log_success(f"Successfully installed {module_import}.")
    else:
        log_error(f"Error installing {module_import}; see log for details.")
        write_error_log(f"Install {module_import}", proc)
        errors.append(f"{module_import}")

def run_setup(script_path: Path, *args):
    if not script_path.exists():
        log_warning(f"{script_path.name} not found; skipping.")
        return

    log_info(f"Running {script_path.name}...")
    cmd = [sys.executable, str(script_path), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        log_success(f"{script_path.name} completed.")
    else:
        log_error(f"Error in {script_path.name}; see log for details.")
        write_error_log(f"Setup {script_path.name}", proc)
        errors.append(script_path.name)

def main():
    parser = argparse.ArgumentParser(description="Master setup script.")
    parser.add_argument("--skip-reinstall", action="store_true",
                        help="Skip (re)installation of modules if already present")
    parser.add_argument("--production", action="store_true",
                        help="Install modules in production mode (no -e)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed output")
    args = parser.parse_args()

    # clear previous error log
    if ERROR_LOG.exists():
        ERROR_LOG.unlink()

    init_timer()
    log_info("=== Running Master Setup Script ===")

    # 1) core modules
    for mod, path in {
        "standard_ui": STANDARD_UI_SETUP_DIR,
        "scripts_setup": SCRIPTS_SETUP_DIR,
        "cross_platform": CROSS_PLATFORM_DIR,
    }.items():
        ensure_module_installed(
            mod,
            path,
            skip_reinstall=args.skip_reinstall,
            editable=not args.production
        )

    # 2) optional WSL2 helper
    if "microsoft" in platform.uname().release.lower():
        log_info("Detected WSL2; running win32yank setup")
        run_setup(SCRIPTS_DIR / "scripts_setup" / "setup_wsl2.py")
    else:
        log_success("Not WSL2; skipping win32yank")

    # common args for setup scripts
    common = [
        "--scripts-dir", str(SCRIPTS_DIR),
        "--dotfiles-dir", str(DOTFILES_DIR),
        "--bin-dir", str(BIN_DIR)
    ]
    if args.verbose:
        common.append("--verbose")
    if args.skip_reinstall:
        common.append("--skip-reinstall")
    if args.production:
        common.append("--production")

    # 3) run sub-setup scripts
    for sub in ["pyscripts/setup.py", "shell-scripts/setup.py", "modules/setup.py"]:
        with section(f"{sub}"):
            run_setup(SCRIPTS_DIR / sub, *common)

    # 4) path integrator
    with section("setup_path.py"):
        run_setup(
            SCRIPTS_DIR / "scripts_setup" / "setup_path.py",
            "--bin-dir", str(BIN_DIR),
            "--dotfiles-dir", str(DOTFILES_DIR),
            *(["--verbose"] if args.verbose else [])
        )

    # final timing & error summary
    print_global_elapsed()
    if errors:
        log_error(f"{len(errors)} error(s) occurred; details in '{ERROR_LOG}'.")
    else:
        log_success("All steps completed successfully.")

if __name__ == "__main__":
    main()
