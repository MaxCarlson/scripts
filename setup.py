#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import platform
import importlib
import subprocess
from pathlib import Path
import time
import re

# ─────────────────────────────────────────────────────────
# Bootstrap tomllib/tomli for TOML parsing
# ─────────────────────────────────────────────────────────
try:
    import tomllib  # Py3.11+
except Exception:
    try:
        import tomli as tomllib  # Py<=3.10
    except Exception:
        print("[ERROR] 'tomli' (for TOML parsing) is not installed.", file=sys.stderr)
        print("[ERROR] Please install it:  pip install tomli", file=sys.stderr)
        sys.exit(1)

# ─────────────────────────────────────────────────────────
# Fallback UI + wrappers (compatible with or without standard_ui)
# ─────────────────────────────────────────────────────────
_is_verbose = ("--verbose" in sys.argv) or ("-v" in sys.argv)

def _fb_log(level: str, message: str):
    print(f"[{level}] {message}")

def _fb_log_info(message: str):
    if _is_verbose:
        _fb_log("INFO", message)

def _fb_log_success(message: str): _fb_log("SUCCESS", message)
def _fb_log_warning(message: str): _fb_log("WARNING", message)
def _fb_log_error(message: str): _fb_log("ERROR", message)

class _FBSection:
    def __init__(self, title: str):
        self.title = title
        self._start = None
    def __enter__(self):
        self._start = time.time()
        if _is_verbose:
            print(f"\n──── {self.title} - START ────")
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if _is_verbose:
            elapsed = time.time() - (self._start or time.time())
            print(f"──── {self.title} - END (Elapsed: {elapsed:.2f}s) ────")

def _fb_status_line(label: str, state: str | None = None, detail: str | None = None):
    prefix = {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}.get(state or "", "•")
    tail = f" — {detail}" if detail else ""
    print(f"[{prefix}] {label}{tail}")

# defaults (overridden if standard_ui imports)
init_timer = lambda: None
print_global_elapsed = lambda: None
log_info, log_success, log_warning, log_error = _fb_log_info, _fb_log_success, _fb_log_warning, _fb_log_error
_section_impl = _FBSection
_status_impl = _fb_status_line

try:
    import standard_ui.standard_ui as _sui
    init_timer           = getattr(_sui, "init_timer", init_timer)
    print_global_elapsed = getattr(_sui, "print_global_elapsed", print_global_elapsed)
    log_info             = getattr(_sui, "log_info", log_info)
    log_success          = getattr(_sui, "log_success", log_success)
    log_warning          = getattr(_sui, "log_warning", log_warning)
    log_error            = getattr(_sui, "log_error", log_error)
    _section_impl        = getattr(_sui, "section", _section_impl)
    _status_impl         = getattr(_sui, "status_line", _status_impl)  # may differ in signature
except Exception:
    if _is_verbose:
        _fb_log_warning("standard_ui not available. Using fallback logging.")

def sui_section(title: str, **kwargs):
    """Context-manager wrapper: tolerate unknown kwargs (e.g. level=...)."""
    try:
        return _section_impl(title, **kwargs)
    except TypeError:
        return _section_impl(title)

def status_line(label: str, state: str | None = None, detail: str | None = None):
    """Wrapper for status_line — safely supports 1/2/3-arg variants."""
    impl = _status_impl
    if impl is _fb_status_line:
        return impl(label, state, detail)
    try:
        return impl(label, state, detail)      # try 3-arg
    except TypeError:
        pass
    try:
        return impl(label, state)              # try 2-arg
    except TypeError:
        pass
    prefix = {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}.get(state or "", "•")
    tail = f" — {detail}" if detail else ""
    try:
        return impl(f"[{prefix}] {label}{tail}")  # try 1-arg
    except TypeError:
        return _fb_status_line(label, state, detail)

def _try_reload_standard_ui_globally():
    """If standard_ui gets installed during this run, adopt its functions."""
    global init_timer, print_global_elapsed, log_info, log_success, log_warning, log_error, _section_impl, _status_impl
    try:
        importlib.invalidate_caches()
        import standard_ui.standard_ui as _sui2
        init_timer           = getattr(_sui2, "init_timer", init_timer)
        print_global_elapsed = getattr(_sui2, "print_global_elapsed", print_global_elapsed)
        log_info             = getattr(_sui2, "log_info", log_info)
        log_success          = getattr(_sui2, "log_success", log_success)
        log_warning          = getattr(_sui2, "log_warning", log_warning)
        log_error            = getattr(_sui2, "log_error", log_error)
        _section_impl        = getattr(_sui2, "section", _section_impl)
        _status_impl         = getattr(_sui2, "status_line", _status_impl)
        log_success("Switched to standard_ui logging dynamically.")
    except Exception as e:
        log_warning(f"standard_ui installed but could not switch logging: {type(e).__name__}: {e}")

# ─────────────────────────────────────────────────────────
# Paths & global state
# ─────────────────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).resolve().parent
MODULES_DIR = SCRIPTS_DIR / "modules"
STANDARD_UI_SETUP_DIR = MODULES_DIR / "standard_ui"
CROSS_PLATFORM_DIR = MODULES_DIR / "cross_platform"
SCRIPTS_SETUP_PACKAGE_DIR = SCRIPTS_DIR / "scripts_setup"

ERROR_LOG = SCRIPTS_DIR / "setup_errors.log"
SETUP_LOG = SCRIPTS_DIR / "setup.log"
errors: list[str] = []
warnings: list[str] = []

def _append_unique(bucket: list[str], item: str):
    if item not in bucket:
        bucket.append(item)

def _append_setup_log(text: str):
    try:
        SETUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SETUP_LOG, "a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    except Exception:
        pass

def write_error_log_detail(title: str, proc: subprocess.CompletedProcess):
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e_mkdir:
        log_warning(f"Could not create parent directory for error log {ERROR_LOG.parent}: {e_mkdir}")
    msg_lines = [
        f"=== {title} ===",
        f"Return code: {proc.returncode}",
        "--- STDOUT ---",
        proc.stdout or "<none>",
        "--- STDERR ---",
        proc.stderr or "<none>",
        "",
    ]
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(msg_lines) + "\n")
    except Exception as e:
        log_error(f"Critical error: could not write detailed error to {ERROR_LOG}: {e}")

# ─────────────────────────────────────────────────────────
# Install helper — check editable vs normal current state and install
# ─────────────────────────────────────────────────────────
def _get_pkg_name_from_source(module_dir: Path, verbose: bool) -> str:
    pyproject_file = module_dir / "pyproject.toml"
    fallback = module_dir.name
    if pyproject_file.is_file():
        try:
            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)
            if "project" in data and "name" in data["project"]:
                return data["project"]["name"]
            if "tool" in data and "poetry" in data["tool"] and "name" in data["tool"]["poetry"]:
                return data["tool"]["poetry"]["name"]
        except Exception as e:
            if verbose:
                log_warning(f"[{fallback}] pyproject.toml parse problem: {type(e).__name__}: {e}")
    return fallback

def _get_current_install_mode(module_dir: Path, verbose: bool) -> str | None:
    pkg = _get_pkg_name_from_source(module_dir, verbose)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg],
            capture_output=True, text=True, check=False, encoding="utf-8", errors="ignore"
        )
        if result.returncode != 0:
            return None
        editable_here = False
        for line in result.stdout.splitlines():
            if line.lower().startswith("editable project location:"):
                loc = line.split(":", 1)[1].strip()
                if loc and loc.lower() != "none":
                    try:
                        if Path(loc).resolve() == module_dir.resolve():
                            editable_here = True
                    except Exception:
                        pass
                break
        return "editable" if editable_here else "normal"
    except Exception as e:
        if verbose:
            log_warning(f"pip show error for '{pkg}': {type(e).__name__}: {e}")
        return None

def ensure_module_installed(module_display_name: str, install_path: Path,
                            skip_reinstall: bool, editable: bool, verbose: bool,
                            soft_fail: bool = False):
    desired_mode = "editable" if editable else "normal"
    current_mode = _get_current_install_mode(install_path, verbose) if skip_reinstall else None

    if skip_reinstall and current_mode == desired_mode:
        status_line(f"{module_display_name}: already installed ({current_mode})", "unchanged", "skip")
        # If we just confirmed standard_ui exists but wrappers are still fallback, try switching.
        if module_display_name == "standard_ui":
            _try_reload_standard_ui_globally()
        return

    install_cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        install_cmd.append("-e")
    install_cmd.append(str(install_path.resolve()))
    proc = subprocess.run(install_cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")

    if proc.returncode == 0:
        status_line(f"{module_display_name}: installed", "ok", "editable" if editable else "normal")
        if module_display_name == "standard_ui":
            _try_reload_standard_ui_globally()
    else:
        write_error_log_detail(f"Install {module_display_name}", proc)
        if soft_fail:
            status_line(f"{module_display_name}: install failed; continuing", "warn", f"see {ERROR_LOG}")
            _append_unique(warnings, f"Installation of {module_display_name} failed (rc: {proc.returncode})")
        else:
            status_line(f"{module_display_name}: install failed", "fail", f"see {ERROR_LOG}")
            _append_unique(errors, f"Installation of {module_display_name} failed (rc: {proc.returncode})")

# ─────────────────────────────────────────────────────────
# Sub-setup runner (streams live output into console + setup.log)
# ─────────────────────────────────────────────────────────
def run_setup(script_path: Path, *args, soft_fail_modules: bool = False, passthrough: bool = False):
    resolved = script_path.resolve()
    if not resolved.exists():
        msg = f"Missing setup script: {resolved.name} at {resolved}"
        log_warning(msg + "; skipping.")
        _append_unique(warnings, msg)
        return

    cmd = [sys.executable, str(resolved), *args]

    env = os.environ.copy()
    python_path_parts = [str(SCRIPTS_DIR.resolve()), str((SCRIPTS_DIR / "modules").resolve())]
    existing_pp = env.get("PYTHONPATH")
    if existing_pp:
        python_path_parts.extend(existing_pp.split(os.pathsep))
    env["PYTHONPATH"] = os.pathsep.join(list(dict.fromkeys(p for p in python_path_parts if p)))
    env["PYTHONIOENCODING"] = "utf-8"
    env["SETUP_LOG_PATH"] = str(SETUP_LOG)  # let children tee into the global log

    _append_setup_log(f"\n=== RUN {resolved} ===")

    if passthrough:
        # Stream live
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        try:
            for line in iter(proc.stdout.readline, ""):
                sys.stdout.write(line)
                sys.stdout.flush()
                _append_setup_log(line.rstrip("\n"))
        finally:
            if proc.stdout:
                proc.stdout.close()
        rc = proc.wait()
        stdout, stderr = "", ""
    else:
        # Buffer but still log
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="ignore")
        rc, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
        if stdout:
            _append_setup_log(stdout.rstrip("\n"))
        if stderr:
            _append_setup_log(stderr.rstrip("\n"))

    if rc == 0:
        status_line(f"{resolved.name} completed.", "ok")
        if _is_verbose and stdout.strip(): log_info(stdout.strip())
        if _is_verbose and stderr.strip(): log_warning(stderr.strip())
    else:
        failed = re.findall(r"FAILED_MODULE:\s*([A-Za-z0-9_.\-]+)", stdout or "")
        hint = f"failed (rc: {rc})" if not failed else f"failed for {', '.join(sorted(set(failed)))} (rc: {rc})"
        write_error_log_detail(f"Setup {resolved.name}", subprocess.CompletedProcess(cmd, rc, stdout, stderr))
        if soft_fail_modules:
            status_line(f"{resolved.name} {hint}; continuing", "warn", f"see {ERROR_LOG}")
            _append_unique(warnings, f"{resolved.name} {hint}")
        else:
            status_line(f"{resolved.name} {hint}", "fail", f"see {ERROR_LOG}")
            _append_unique(errors, f"{resolved.name} {hint}")

# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────
def main():
    global _is_verbose

    parser = argparse.ArgumentParser(description="Master setup script for managing project components.")
    # Short + long for all args
    parser.add_argument("-R", "--scripts-dir", type=Path, required=False,
                        help="Base directory for the project scripts. Defaults to $SCRIPTS.")
    parser.add_argument("-D", "--dotfiles-dir", type=Path, required=False,
                        help="Root directory of dotfiles. Defaults to $DOTFILES.")
    parser.add_argument("-B", "--bin-dir", type=Path, required=False,
                        help="Target directory for symlinked executables. Defaults to <scripts-dir>/bin.")

    parser.add_argument("-s", "--skip-reinstall", action="store_true",
                        help="Skip re-installation if modules already match the desired install mode and path.")
    parser.add_argument("-p", "--production", action="store_true",
                        help="Install Python modules in production mode (non-editable).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable detailed output.")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress some fallback INFO logs.")
    parser.add_argument("-m", "--soft-fail-modules", action="store_true",
                        help="Do not halt when modules/setup.py fails; continue and record as a warning.")

    # Pass-through flag ONLY for modules/setup.py to skip requirements.txt
    parser.add_argument("-I", "--ignore-requirements", action="store_true",
                        help="Pass to modules/setup.py to skip installing requirements.txt for each module.")

    args = parser.parse_args()
    _is_verbose = args.verbose

    # Resolve directories from args or environment; error fast if missing
    env_scripts = os.environ.get("SCRIPTS", "").strip()
    env_dotfiles = os.environ.get("DOTFILES", "").strip()

    if args.scripts_dir:
        scripts_dir = args.scripts_dir
    elif env_scripts:
        scripts_dir = Path(env_scripts)
    else:
        status_line("scripts-dir not provided and $SCRIPTS is not set", "fail")
        print("Hint: use -R/--scripts-dir or export SCRIPTS=/path/to/scripts", file=sys.stderr)
        sys.exit(2)

    if args.dotfiles_dir:
        dotfiles_dir = args.dotfiles_dir
    elif env_dotfiles:
        dotfiles_dir = Path(env_dotfiles)
    else:
        status_line("dotfiles-dir not provided and $DOTFILES is not set", "fail")
        print("Hint: use -D/--dotfiles-dir or export DOTFILES=/path/to/dotfiles", file=sys.stderr)
        sys.exit(2)

    if args.bin_dir:
        bin_dir = args.bin_dir
    else:
        # default derived from scripts_dir
        bin_dir = scripts_dir / ("bin" if os.name != "nt" else "bin")

    # Initialize timer if standard_ui provides it
    try:
        init_timer()
    except Exception:
        pass

    # Clear previous logs
    for p in (ERROR_LOG, SETUP_LOG):
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    _append_setup_log(f"=== Setup started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===")

    # Core modules (standard_ui, scripts_setup, cross_platform)
    with sui_section("Core Module Installation", level="major"):
        for name, path in [
            ("standard_ui", STANDARD_UI_SETUP_DIR),
            ("scripts_setup", SCRIPTS_SETUP_PACKAGE_DIR),
            ("cross_platform", CROSS_PLATFORM_DIR),
        ]:
            if path.is_dir() and ((path / "setup.py").exists() or (path / "pyproject.toml").exists()):
                ensure_module_installed(
                    name, path,
                    skip_reinstall=args.skip_reinstall,
                    editable=not args.production,
                    verbose=args.verbose,
                    soft_fail=args.soft_fail_modules,
                )
            else:
                log_warning(f"{name} setup files not found in {path} or it's not a directory.")

    # WSL2? (win32yank helper)
    try:
        rel = platform.uname().release
    except Exception:
        rel = ""
    if "microsoft" in rel.lower() and "WSL" in rel.upper():
        with sui_section("WSL2 Specific Setup", level="medium"):
            run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_wsl2.py", *([] if not args.verbose else ["--verbose"]))
    else:
        status_line("Not WSL2; skipping win32yank setup.", "unchanged")

    # Common args for sub-setup scripts
    common_setup_args = [
        "--scripts-dir", str(scripts_dir),
        "--dotfiles-dir", str(dotfiles_dir),
        "--bin-dir", str(bin_dir),
    ]
    if args.verbose:        common_setup_args.append("--verbose")
    if args.skip_reinstall: common_setup_args.append("--skip-reinstall")
    if args.production:     common_setup_args.append("--production")

    # Run sub-setups (only modules/setup.py receives -I/--ignore-requirements)
    sub_setups = [
        (SCRIPTS_DIR / "pyscripts" / "setup.py", []),
        (SCRIPTS_DIR / "shell-scripts" / "setup.py", []),
        (MODULES_DIR / "setup.py", (["-I"] if args.ignore_requirements else [])),
    ]
    for full_script_path, extra_args in sub_setups:
        try:
            title_rel_path = full_script_path.relative_to(SCRIPTS_DIR)
        except ValueError:
            title_rel_path = full_script_path.name
        with sui_section(f"Running sub-setup: {title_rel_path}", level="medium"):
            run_setup(
                full_script_path,
                *(common_setup_args + extra_args),
                soft_fail_modules=args.soft_fail_modules,
                passthrough=(full_script_path == MODULES_DIR / "setup.py"),  # stream modules live
            )

    with sui_section("Shell PATH Configuration (setup_path.py)", level="major"):
        setup_path_script = SCRIPTS_SETUP_PACKAGE_DIR / "setup_path.py"
        path_args = ["--bin-dir", str(bin_dir), "--dotfiles-dir", str(dotfiles_dir)]
        if args.verbose: path_args.append("--verbose")
        run_setup(setup_path_script, *path_args)

    try:
        print_global_elapsed()
    except Exception:
        pass

    if errors:
        if not ERROR_LOG.exists():
            try:
                ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
                with open(ERROR_LOG, "w", encoding="utf-8") as f:
                    f.write("=== Summary of Errors Encountered During Setup ===\n")
                    for i, err_msg in enumerate(errors):
                        f.write(f"{i+1}. {err_msg}\n")
            except Exception as e_log_write:
                log_error(f"Failed to write error summary to '{ERROR_LOG}': {e_log_write}")
        if warnings:
            log_warning(f"Setup completed with {len(errors)} error(s) and {len(warnings)} warning(s). See {ERROR_LOG}.")
        else:
            log_error(f"Setup completed with {len(errors)} error(s). See {ERROR_LOG}.")
        sys.exit(1)
    elif warnings:
        log_warning(f"Setup completed with {len(warnings)} warning(s). See {ERROR_LOG}.")
        sys.exit(0)
    else:
        log_success("All setup steps completed successfully.")
        sys.exit(0)

if __name__ == "__main__":
    main()
