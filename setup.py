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
from datetime import datetime
from threading import Thread, Lock

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
# Paths & global log
# ─────────────────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).resolve().parent
MODULES_DIR = SCRIPTS_DIR / "modules"
STANDARD_UI_SETUP_DIR = MODULES_DIR / "standard_ui"
CROSS_PLATFORM_DIR = MODULES_DIR / "cross_platform"
SCRIPTS_SETUP_PACKAGE_DIR = SCRIPTS_DIR / "scripts_setup"

ERROR_LOG = SCRIPTS_DIR / "setup_errors.log"
GLOBAL_LOG = SCRIPTS_DIR / "setup.log"

def _log_init():
    try:
        GLOBAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(GLOBAL_LOG, "w", encoding="utf-8") as f:
            f.write(f"=== setup.py run @ {datetime.now().isoformat()} ===\n")
    except Exception:
        pass

def _log_append(text: str):
    try:
        with open(GLOBAL_LOG, "a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
    except Exception:
        pass

# ─────────────────────────────────────────────────────────
# Fallback UI + ASCII/Unicode handling
# ─────────────────────────────────────────────────────────
_is_verbose = ("--verbose" in sys.argv) or ("-v" in sys.argv)

def _needs_ascii_ui() -> bool:
    if os.environ.get("FORCE_ASCII_UI") == "1":
        return True
    enc = (getattr(sys.stdout, "encoding", "") or "").upper()
    return os.name == "nt" and "UTF-8" not in enc

_ASCII_UI = _needs_ascii_ui()

def _fb_log(level: str, message: str):
    msg = f"[{level}] {message}"
    print(msg)
    _log_append(msg)

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
        banner = f"---- {self.title} - START ----" if _ASCII_UI else f"──── {self.title} - START ────"
        if _is_verbose:
            print("\n" + banner)
        _log_append(banner)
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.time() - (self._start or time.time())
        banner = f"---- {self.title} - END (Elapsed: {elapsed:.2f}s) ----" if _ASCII_UI else f"──── {self.title} - END (Elapsed: {elapsed:.2f}s) ────"
        if _is_verbose:
            print(banner)
        _log_append(banner)

def _fb_status_line(label: str, state: str | None = None, detail: str | None = None):
    prefix = {"unchanged": "-", "ok": "OK", "warn": "!", "fail": "X"} if _ASCII_UI else \
             {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}
    lead = prefix.get(state or "", prefix["unchanged"])
    tail = f" — {detail}" if (detail and not _ASCII_UI) else (f" - {detail}" if detail else "")
    line = f"[{lead}] {label}{tail}"
    print(line)
    _log_append(line)

# defaults (may be overridden by standard_ui)
init_timer = lambda: None
print_global_elapsed = lambda: None
log_info, log_success, log_warning, log_error = _fb_log_info, _fb_log_success, _fb_log_warning, _fb_log_error
_section_impl = _FBSection
_status_impl = _fb_status_line

try:
    if not _ASCII_UI:
        import standard_ui.standard_ui as _sui
        init_timer           = getattr(_sui, "init_timer", init_timer)
        print_global_elapsed = getattr(_sui, "print_global_elapsed", print_global_elapsed)
        log_info             = getattr(_sui, "log_info", log_info)
        log_success          = getattr(_sui, "log_success", log_success)
        log_warning          = getattr(_sui, "log_warning", log_warning)
        log_error            = getattr(_sui, "log_error", log_error)
        _section_impl        = getattr(_sui, "section", _section_impl)
        _status_impl         = getattr(_sui, "status_line", _status_impl)
    else:
        if _is_verbose:
            print("[WARNING] Non-UTF-8 console detected; using ASCII UI.")
            _log_append("[WARNING] Non-UTF-8 console detected; using ASCII UI.")
except Exception:
    if _is_verbose:
        _fb_log_warning("standard_ui not available. Using fallback logging.")

def sui_section(title: str, **kwargs):
    """Context-manager wrapper: tolerate unknown kwargs (e.g. level=...). Also logs to GLOBAL_LOG."""
    try:
        ctx = _section_impl(title, **kwargs)
    except TypeError:
        ctx = _section_impl(title)
    return ctx

def status_line(label: str, state: str | None = None, detail: str | None = None):
    """Wrapper for status_line — safely supports 1/2/3-arg variants, and logs to GLOBAL_LOG."""
    impl = _status_impl
    prefix_map = {"unchanged": "-", "ok": "OK", "warn": "!", "fail": "X"} if _ASCII_UI else \
                 {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}
    line_for_log = f"[{prefix_map.get(state or '', prefix_map['unchanged'])}] {label}"
    if detail:
        line_for_log += (" - " if _ASCII_UI else " — ") + detail
    _log_append(line_for_log)

    if impl is _fb_status_line:
        return impl(label, state, detail)
    try:
        return impl(label, state, detail)
    except TypeError:
        pass
    try:
        return impl(label, state)
    except TypeError:
        pass
    try:
        return impl(line_for_log)
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

errors: list[str] = []
warnings: list[str] = []

def _append_unique(bucket: list[str], item: str):
    if item not in bucket:
        bucket.append(item)

def write_error_log_detail(title: str, proc: subprocess.CompletedProcess | None, stdout: str = "", stderr: str = ""):
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e_mkdir:
        log_warning(f"Could not create parent directory for error log {ERROR_LOG.parent}: {e_mkdir}")
    msg_lines = [f"=== {title} ==="]
    if proc is not None:
        msg_lines += [
            f"Return code: {proc.returncode}",
            "--- STDOUT ---",
            proc.stdout or "<none>",
            "--- STDERR ---",
            proc.stderr or "<none>",
            "",
        ]
    else:
        msg_lines += ["--- STDOUT ---", stdout or "<none>", "--- STDERR ---", stderr or "<none>", ""]
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(msg_lines) + "\n")
    except Exception as e:
        log_error(f"Critical error: could not write detailed error to {ERROR_LOG}: {e}")

# ─────────────────────────────────────────────────────────
# Child process runner with stall detection (fix for pwsh Y/N)
# ─────────────────────────────────────────────────────────
STALL_NOTICE_AFTER = int(os.environ.get("SETUP_STALL_NOTICE_SEC", "10"))
STALL_AUTO_CONFIRM_AFTER = int(os.environ.get("SETUP_STALL_AUTOCONFIRM_SEC", "15"))
AUTO_CONFIRM = os.environ.get("SETUP_AUTO_CONFIRM", "1") not in ("0", "false", "False")

def _popen_stream_and_log(cmd, cwd=None, env=None, tag: str = ""):
    """
    Start a child process, stream stdout (merged with stderr) to console
    and append to GLOBAL_LOG in real time.

    On Windows PowerShell stalls (hidden Y/N), we print a visible hint after
    STALL_NOTICE_AFTER seconds, and (if enabled) auto-send 'Y\\n' after
    STALL_AUTO_CONFIRM_AFTER seconds.
    """
    if env is None:
        env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    header = f"=== RUN {tag or 'subprocess'}: {' '.join(cmd)} ==="
    _log_append(header)

    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,  # allow us to inject Y/Enter if stuck
        text=True, encoding="utf-8", errors="ignore", bufsize=1
    )

    last_out = time.time()
    out_lock = Lock()
    collected_lines: list[str] = []
    notice_printed = False
    autoyes_sent = False

    def reader():
        nonlocal last_out
        try:
            for line in iter(proc.stdout.readline, ""):
                with out_lock:
                    collected_lines.append(line)
                    last_out = time.time()
                # live to console
                try:
                    sys.stdout.write(line)
                except Exception:
                    pass
                # and to log
                _log_append(line.rstrip("\n"))
        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

    t = Thread(target=reader, daemon=True)
    t.start()

    try:
        while True:
            rc = proc.poll()
            now = time.time()
            silent_for = now - last_out

            # Stall hint
            if rc is None and not notice_printed and silent_for >= STALL_NOTICE_AFTER:
                hint = (
                    "\n[HINT] No output from child process for a while. "
                    "If you're on PowerShell, a hidden confirmation prompt may be waiting (Y/N).\n"
                    "      We'll try to auto-confirm shortly. To disable this behavior, set SETUP_AUTO_CONFIRM=0.\n"
                )
                print(hint, end="")
                _log_append(hint.rstrip("\n"))
                notice_printed = True

            # Auto-confirm for PowerShell stalls
            if (
                rc is None
                and os.name == "nt"
                and AUTO_CONFIRM
                and not autoyes_sent
                and silent_for >= STALL_AUTO_CONFIRM_AFTER
            ):
                try:
                    msg = "[ACTION] Auto-sending 'Y<Enter>' to child process (Windows stall heuristic)."
                    print(msg)
                    _log_append(msg)
                    proc.stdin.write("Y\n")
                    proc.stdin.flush()
                    autoyes_sent = True
                except Exception as e:
                    _log_append(f"[WARN] Failed to auto-send input: {e}")
                    autoyes_sent = True  # avoid retry loop

            if rc is not None:
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        proc.kill()
        rc = proc.wait()
    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        t.join(timeout=5)

    footer = f"=== END {tag or 'subprocess'} (rc={rc}) ==="
    _log_append(footer)
    return rc, "".join(collected_lines), ""  # stderr merged into stdout

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
        if module_display_name == "standard_ui":
            _try_reload_standard_ui_globally()
        return

    install_cmd = [sys.executable, "-m", "pip", "install"]
    if editable:
        install_cmd.append("-e")
    install_cmd.append(str(install_path.resolve()))
    rc, out, err = _popen_stream_and_log(install_cmd, cwd=None, tag=f"pip-install:{module_display_name}")
    if rc == 0:
        status_line(f"{module_display_name}: installed", "ok", "editable" if editable else "normal")
        if module_display_name == "standard_ui":
            _try_reload_standard_ui_globally()
    else:
        write_error_log_detail(f"Install {module_display_name}", None, out, err)
        if soft_fail:
            status_line(f"{module_display_name}: install failed; continuing", "warn", f"see {ERROR_LOG}")
            _append_unique(warnings, f"Installation of {module_display_name} failed (rc: {rc})")
        else:
            status_line(f"{module_display_name}: install failed", "fail", f"see {ERROR_LOG}")
            _append_unique(errors, f"Installation of {module_display_name} failed (rc: {rc})")

# ─────────────────────────────────────────────────────────
# Sub-setup runner (streams live output + logs; with stall fix)
# ─────────────────────────────────────────────────────────
def run_setup(script_path: Path, *args, soft_fail_modules: bool = False):
    resolved = script_path.resolve()
    if not resolved.exists():
        msg = f"Missing setup script: {resolved.name} at {resolved}"
        log_warning(msg + "; skipping.")
        _log_append("WARN: " + msg)
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

    rc, out, _ = _popen_stream_and_log(cmd, env=env, tag=f"sub-setup:{resolved.name}")

    if rc == 0:
        status_line(f"{resolved.name} completed.", "ok")
    else:
        failed = re.findall(r"FAILED_MODULE:\s*([A-Za-z0-9_.\-]+)", out or "")
        hint = f"failed (rc: {rc})"
        if failed:
            hint = f"failed for {', '.join(sorted(set(failed)))} (rc: {rc})"
        if soft_fail_modules:
            status_line(f"{resolved.name} {hint}; continuing", "warn", f"see {ERROR_LOG}")
            _append_unique(warnings, f"{resolved.name} {hint}")
        else:
            status_line(f"{resolved.name} {hint}", "fail", f"see {ERROR_LOG}")
            _append_unique(errors, f"{resolved.name} {hint}")
        write_error_log_detail(f"Setup {resolved.name}", None, out, "")

# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────
def main():
    global _is_verbose
    _log_init()

    parser = argparse.ArgumentParser(description="Master setup script for managing project components.")
    parser.add_argument("-R", "--scripts-dir", type=Path, required=False,
                        help="Base directory for the project scripts. Defaults to $SCRIPTS.")
    parser.add_argument("-D", "--dotfiles-dir", type=Path, required=False,
                        help="Root directory of dotfiles. Defaults to $DOTFILES.")
    parser.add_argument("-B", "--bin-dir", type=Path, required=False,
                        help="Target directory for symlinked executables. Defaults to <scripts-dir>/bin.")
    parser.add_argument(
        "-s", "--skip-reinstall",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip re-installation when modules already match the desired install mode and path.",
    )
    parser.add_argument("-p", "--production", action="store_true",
                        help="Install Python modules in production mode (non-editable).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable detailed output.")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress some fallback INFO logs.")
    parser.add_argument(
        "-m", "--soft-fail-modules",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Do not halt when modules/setup.py fails; continue and record as a warning.",
    )

    args = parser.parse_args()
    _is_verbose = args.verbose

    # Resolve directories
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

    bin_dir = args.bin_dir if args.bin_dir else scripts_dir / "bin"

    try:
        init_timer()
    except Exception:
        pass

    # Clear previous error log
    if ERROR_LOG.exists():
        try:
            ERROR_LOG.unlink()
            if _is_verbose:
                log_info(f"Cleared previous error log: {ERROR_LOG}")
        except OSError as e:
            log_warning(f"Could not clear previous error log {ERROR_LOG}: {e}")

    # Core modules
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

    # WSL2?
    try:
        rel = platform.uname().release
    except Exception:
        rel = ""
    if "microsoft" in rel.lower() and "WSL" in rel.upper():
        with sui_section("WSL2 Specific Setup", level="medium"):
            run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_wsl2.py", *([] if not args.verbose else ["--verbose"]))
    else:
        status_line("Not WSL2; skipping win32yank setup.", "unchanged")

    # Sub-setups
    common_setup_args = [
        "--scripts-dir", str(scripts_dir),
        "--dotfiles-dir", str(dotfiles_dir),
        "--bin-dir", str(bin_dir),
    ]
    if args.verbose:        common_setup_args.append("--verbose")
    if args.skip_reinstall:
        common_setup_args.append("--skip-reinstall")
    else:
        common_setup_args.append("--no-skip-reinstall")
    if args.production:     common_setup_args.append("--production")

    sub_setups = [
        (SCRIPTS_DIR / "pyscripts" / "setup.py", []),
        (SCRIPTS_DIR / "pscripts" / "setup.py", []),
        (SCRIPTS_DIR / "shell-scripts" / "setup.py", []),
        (MODULES_DIR / "setup.py", []),
    ]
    for full_script_path, extra_args in sub_setups:
        try:
            title_rel_path = full_script_path.relative_to(SCRIPTS_DIR)
        except ValueError:
            title_rel_path = full_script_path.name
        with sui_section(f"Running sub-setup: {title_rel_path}", level="medium"):
            run_setup(full_script_path, *(common_setup_args + extra_args), soft_fail_modules=args.soft_fail_modules)

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
