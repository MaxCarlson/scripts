#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Root setup.py — self-bootstrapping

Adds a venv bootstrap step before running the original setup workflow:
- ensures ./.venv exists (prefers `uv venv --seed` if available, otherwise `python -m venv`)
- ensures pip/setuptools/wheel are installed/updated in ./.venv
- re-execs this script with ./.venv/bin/python
- then proceeds with the existing install/sub-setup orchestration
"""

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
# VENV BOOTSTRAP (new)
# ─────────────────────────────────────────────────────────

SCRIPTS_DIR = Path(__file__).resolve().parent
VENV_DIR = SCRIPTS_DIR / ".venv"
IS_WINDOWS = os.name == "nt"

def _which(cmd: str) -> str | None:
    return shutil.which(cmd) if (shutil := __import__("shutil")) else None

def _run_quiet(cmd: list[str]) -> int:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore")
        return p.returncode
    except Exception:
        return 1

def _ensure_pip_in_venv(py_exe: Path):
    # make sure pip exists, then upgrade basics
    rc = _run_quiet([str(py_exe), "-m", "ensurepip", "--upgrade"])

    # On Termux, ensurepip may not be available, use system pip to bootstrap
    if rc != 0:
        # Try using system pip to install pip into the venv
        _run_quiet([sys.executable, "-m", "pip", "install", "--target",
                   str(py_exe.parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"),
                   "pip", "setuptools", "wheel"])

    # Even if ensurepip is a no-op, upgrade tooling
    _run_quiet([str(py_exe), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])


def find_invalid_aebndl_dist_leftovers(site_packages_dir: Path) -> list[Path]:
    """Return pip leftover paths that look like broken aebndl distributions."""
    if not site_packages_dir.exists():
        return []
    leftovers: list[Path] = []
    for child in site_packages_dir.iterdir():
        name = child.name.lower()
        if not name.startswith("~"):
            continue
        if "bndl" in name or name in {"~", "~.dist-info"}:
            leftovers.append(child)
    return sorted(leftovers, key=lambda p: p.name.lower())


def _venv_site_packages_candidates() -> list[Path]:
    if IS_WINDOWS:
        return [VENV_DIR / "Lib" / "site-packages"]
    return sorted((VENV_DIR / "lib").glob("python*/site-packages")) if (VENV_DIR / "lib").exists() else []


def report_or_repair_invalid_aebndl_dists(*, repair: bool = False) -> None:
    leftovers: list[Path] = []
    for site_packages in _venv_site_packages_candidates():
        leftovers.extend(find_invalid_aebndl_dist_leftovers(site_packages))
    if not leftovers:
        return
    action = "Removing" if repair else "Detected"
    print(f"[BOOTSTRAP] {action} invalid aebndl pip leftover(s):")
    for path in leftovers:
        print(f"  - {path}")
        if repair:
            try:
                if path.is_dir():
                    import shutil

                    shutil.rmtree(path)
                else:
                    path.unlink()
            except Exception as exc:
                print(f"    [WARN] Could not remove: {exc}")
    if not repair:
        print("[BOOTSTRAP] Re-run with --repair-invalid-aebndl-dists to remove these leftovers.")

def _venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")

def _venv_site_packages_pyver() -> str | None:
    """Return the pythonX.Y version string found in .venv/lib/, or None."""
    lib_dir = VENV_DIR / "lib"
    if not lib_dir.exists():
        return None
    for entry in lib_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("python"):
            return entry.name[len("python"):]
    return None

def _create_venv():
    """Create (or recreate) the venv from scratch."""
    VENV_DIR.mkdir(parents=True, exist_ok=True)
    uv = _which("uv")
    if uv:
        env = os.environ.copy()
        env["UV_LINK_MODE"] = "copy"
        subprocess.check_call([uv, "venv", "--python", sys.executable, "--seed", str(VENV_DIR)], env=env)
    else:
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
    _ensure_pip_in_venv(_venv_python())

def _bootstrap_venv_if_needed():
    # Allow skipping (for legacy/advanced scenarios)
    if os.environ.get("SKIP_VENV_BOOTSTRAP") == "1":
        return

    # If we're already using the repo venv python, nothing to do
    vpy = _venv_python()
    if vpy.exists() and Path(sys.executable).resolve() == vpy.resolve():
        return

    current_ver = f"{sys.version_info.major}.{sys.version_info.minor}"

    if not vpy.exists():
        # Venv doesn't exist — create it
        _create_venv()
    else:
        # Venv exists — check for Python version mismatch (e.g. Termux upgraded 3.12→3.13)
        sp_ver = _venv_site_packages_pyver()
        if sp_ver and sp_ver != current_ver:
            print(f"[BOOTSTRAP] Python version changed ({sp_ver} → {current_ver}). Recreating venv...")
            import shutil as _shutil
            _shutil.rmtree(str(VENV_DIR))
            _create_venv()
        else:
            # venv exists and version matches — ensure pip is present
            _ensure_pip_in_venv(vpy)

    # Re-exec this script under the venv python so all downstream pip installs
    # use the venv and never hit system PEP 668.
    if Path(sys.executable).resolve() != vpy.resolve():
        os.execv(str(vpy), [str(vpy), *sys.argv])

# Run the bootstrap ASAP (before any pip installs or sub-setups)
_bootstrap_venv_if_needed()

# From this point on, we are guaranteed to be running under ./.venv/bin/python

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
MODULES_DIR = SCRIPTS_DIR / "modules"
STANDARD_UI_SETUP_DIR = MODULES_DIR / "standard_ui"
CROSS_PLATFORM_DIR = MODULES_DIR / "cross_platform"
PYTHON_SETUP_DIR = MODULES_DIR / "python_setup"
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
# Child process runner with stall detection (unchanged)
# ─────────────────────────────────────────────────────────
STALL_NOTICE_AFTER = int(os.environ.get("SETUP_STALL_NOTICE_SEC", "10"))
STALL_AUTO_CONFIRM_AFTER = int(os.environ.get("SETUP_STALL_AUTOCONFIRM_SEC", "15"))
AUTO_CONFIRM = os.environ.get("SETUP_AUTO_CONFIRM", "1") not in ("0", "false", "False")

def _popen_stream_and_log(cmd, cwd=None, env=None, tag: str = ""):
    if env is None:
        env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    header = f"=== RUN {tag or 'subprocess'}: {' '.join(cmd)} ==="
    _log_append(header)

    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
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
                try:
                    sys.stdout.write(line)
                except Exception:
                    pass
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

            if rc is None and not notice_printed and silent_for >= STALL_NOTICE_AFTER:
                hint = (
                    "\n[HINT] No output from child process for a while. "
                    "If you're on PowerShell, a hidden confirmation prompt may be waiting (Y/N).\n"
                    "      We'll try to auto-confirm shortly. To disable this behavior, set SETUP_AUTO_CONFIRM=0.\n"
                )
                print(hint, end="")
                _log_append(hint.rstrip("\n"))
                notice_printed = True

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
                    autoyes_sent = True

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
    setup_file = module_dir / "setup.py"
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
    if setup_file.is_file():
        try:
            text = setup_file.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", text)
            if match:
                return match.group(1)
        except Exception as e:
            if verbose:
                log_warning(f"[{fallback}] setup.py parse problem: {type(e).__name__}: {e}")
    return fallback

def _get_source_version(module_dir: Path, verbose: bool) -> tuple[int, int, int] | None:
    """Read MAJOR.MINOR.PATCH from pyproject.toml or setup.py."""
    pyproject_file = module_dir / "pyproject.toml"
    setup_file = module_dir / "setup.py"

    def _parse_version(raw: str) -> tuple[int, int, int] | None:
        core = raw.strip().split("+", 1)[0].split("-", 1)[0]
        parts = core.split(".")
        if len(parts) >= 3:
            return int(parts[0]), int(parts[1]), int(parts[2])
        if len(parts) == 2:
            return int(parts[0]), int(parts[1]), 0
        if len(parts) == 1 and parts[0]:
            return int(parts[0]), 0, 0
        return None

    if pyproject_file.is_file():
        try:
            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)
            raw = data.get("project", {}).get("version", "")
            parsed = _parse_version(raw)
            if parsed is not None:
                return parsed
        except Exception as e:
            if verbose:
                log_warning(f"[{module_dir.name}] pyproject.toml version parse error: {e}")

    if setup_file.is_file():
        try:
            text = setup_file.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"\bversion\s*=\s*['\"]([^'\"]+)['\"]", text)
            if match:
                return _parse_version(match.group(1))
        except Exception as e:
            if verbose:
                log_warning(f"[{module_dir.name}] setup.py version parse error: {e}")
    return None


def _get_installed_version(module_dir: Path, verbose: bool) -> tuple[int, int, int] | None:
    """Read the installed version via importlib.metadata or pip show."""
    pkg = _get_pkg_name_from_source(module_dir, verbose)
    try:
        import importlib.metadata as _im
        raw = _im.version(pkg)
        parts = raw.split(".")
        if len(parts) >= 3:
            return int(parts[0]), int(parts[1]), int(parts[2])
        if len(parts) == 2:
            return int(parts[0]), int(parts[1]), 0
        if len(parts) == 1 and parts[0]:
            return int(parts[0]), 0, 0
    except Exception:
        pass
    # Fallback: pip show
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg],
            capture_output=True, text=True, check=False, encoding="utf-8", errors="ignore"
        )
        for line in result.stdout.splitlines():
            if line.lower().startswith("version:"):
                raw = line.split(":", 1)[1].strip()
                parts = raw.split(".")
                if len(parts) >= 3:
                    return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception as e:
        if verbose:
            log_warning(f"[{pkg}] installed version check error: {e}")
    return None


def _check_version_action(module_dir: Path, verbose: bool) -> str:
    """
    Compare source vs installed version and return the required action.

    Returns one of:
      "reinstall_full"  — MAJOR changed: entry points changed, must recreate .cmd files.
                          Action: pip uninstall + pip install -e .
      "reinstall_soft"  — MINOR changed: deps/metadata changed, .cmd files stay valid.
                          Action: pip install -e .
      "skip"            — PATCH only or equal: editable install already up to date.
                          Action: nothing needed.
      "unknown"         — Cannot determine versions; caller decides.
    """
    src = _get_source_version(module_dir, verbose)
    installed = _get_installed_version(module_dir, verbose)

    if src is None or installed is None:
        return "unknown"

    src_major, src_minor, _ = src
    ins_major, ins_minor, _ = installed

    if src_major > ins_major:
        # Entry points likely changed → must regenerate .cmd files
        return "reinstall_full"
    if src_minor > ins_minor:
        # Only deps/metadata changed → reinstall without .cmd recreation
        return "reinstall_soft"
    # Patch-only or equal → editable install picks up source changes automatically
    return "skip"


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

    # Version-aware skip / reinstall decision (MODULE_STANDARDS.md §1)
    if skip_reinstall:
        version_action = _check_version_action(install_path, verbose)
        if version_action == "skip":
            # Patch-only: editable install already has the latest source
            current_mode = _get_current_install_mode(install_path, verbose)
            if current_mode == desired_mode:
                status_line(f"{module_display_name}: already installed ({current_mode})", "unchanged", "skip")
                if module_display_name == "standard_ui":
                    _try_reload_standard_ui_globally()
                return
        elif version_action == "reinstall_full":
            # MAJOR version bump: entry points changed → uninstall first to recreate .cmd files
            pkg = _get_pkg_name_from_source(install_path, verbose)
            status_line(f"{module_display_name}: MAJOR version bump — uninstalling to regenerate .cmd", "warn")
            _run_quiet([sys.executable, "-m", "pip", "uninstall", "-y", pkg])
        elif version_action == "reinstall_soft":
            # MINOR version bump: deps/metadata changed → reinstall (keep .cmd files)
            status_line(f"{module_display_name}: MINOR version bump — reinstalling", "warn")
        # "unknown": fall through to normal install
    else:
        current_mode = _get_current_install_mode(install_path, verbose) if skip_reinstall else None
        if skip_reinstall and current_mode == desired_mode:
            status_line(f"{module_display_name}: already installed ({current_mode})", "unchanged", "skip")
            if module_display_name == "standard_ui":
                _try_reload_standard_ui_globally()
            return

    install_cmd = [sys.executable, "-m", "pip", "install"]
    if not verbose:
        install_cmd.extend(["-q", "--no-input", "--disable-pip-version-check"])
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
# Sub-setup runner
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
                        help="Base directory for the project scripts. Defaults to $SCRIPTS or ~/scripts.")
    parser.add_argument("-D", "--dotfiles-dir", type=Path, required=False,
                        help="Root directory of dotfiles. Defaults to $DOTFILES or ~/dotfiles.")
    parser.add_argument("-B", "--bin-dir", type=Path, required=False,
                        help="Target directory for symlinked executables. Defaults to <scripts-dir>/bin.")
    parser.add_argument(
        "-f", "--force-reinstall",
        action="store_true",
        default=False,
        help="Force re-installation even when modules already match the desired install mode.",
    )
    parser.add_argument(
        "-s",
        "--skip-reinstall",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Skip reinstall when modules already match the desired install mode.",
    )
    parser.add_argument("-p", "--production", action="store_true",
                        help="Install Python modules in production mode (non-editable).")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable detailed output.")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress some fallback INFO logs.")
    parser.add_argument("-E", "--no-venv", dest="no_venv", action="store_true", help="(Advanced) Skip venv bootstrap even if not in ./.venv.")
    parser.add_argument(
        "-F", "--fail-fast",
        action="store_true",
        default=False,
        help="Halt immediately when modules/setup.py fails (default is to continue and warn).",
    )
    parser.add_argument(
        "-I", "--repair-invalid-aebndl-dists",
        action="store_true",
        default=False,
        help="Remove invalid ~*aebndl* pip distribution leftovers from the repo venv before setup continues.",
    )

    args = parser.parse_args()
    _is_verbose = args.verbose
    report_or_repair_invalid_aebndl_dists(repair=args.repair_invalid_aebndl_dists)

    if args.force_reinstall and args.skip_reinstall is True:
        parser.error("--force-reinstall conflicts with --skip-reinstall")

    if args.no_venv:
        os.environ["SKIP_VENV_BOOTSTRAP"] = "1"

    # Resolve directories with fallback defaults
    env_scripts = os.environ.get("SCRIPTS", "").strip()
    env_dotfiles = os.environ.get("DOTFILES", "").strip()

    if args.scripts_dir:
        scripts_dir = args.scripts_dir
    elif env_scripts:
        scripts_dir = Path(env_scripts)
    else:
        # Default to the directory containing this setup.py script
        scripts_dir = SCRIPTS_DIR

    if args.dotfiles_dir:
        dotfiles_dir = args.dotfiles_dir
    elif env_dotfiles:
        dotfiles_dir = Path(env_dotfiles)
    else:
        dotfiles_dir = Path.home() / "dotfiles"

    bin_dir = args.bin_dir if args.bin_dir else scripts_dir / "bin"

    if args.skip_reinstall is None:
        skip_reinstall = not args.force_reinstall
    else:
        skip_reinstall = args.skip_reinstall
    # soft_fail_modules is True by default, fail_fast inverts it
    soft_fail_modules = not args.fail_fast

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

    # Core modules — now safe because we're under ./.venv
    # Order matters: cross_platform must be installed before python_setup (dependency)
    with sui_section("Core Module Installation", level="major"):
        for name, path in [
            ("standard_ui", STANDARD_UI_SETUP_DIR),
            ("cross_platform", CROSS_PLATFORM_DIR),
            ("python_setup", PYTHON_SETUP_DIR),
            ("scripts_setup", SCRIPTS_SETUP_PACKAGE_DIR),
        ]:
            if path.is_dir() and ((path / "setup.py").exists() or (path / "pyproject.toml").exists()):
                ensure_module_installed(
                    name, path,
                    skip_reinstall=skip_reinstall,
                    editable=not args.production,
                    verbose=args.verbose,
                    soft_fail=soft_fail_modules,
                )
            else:
                log_warning(f"{name} setup files not found in {path} or it's not a directory.")

    # WSL2 helper
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
    if skip_reinstall:
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
            run_setup(full_script_path, *(common_setup_args + extra_args), soft_fail_modules=soft_fail_modules)

    with sui_section("Shell PATH Configuration (setup_path.py)", level="major"):
        setup_path_script = SCRIPTS_SETUP_PACKAGE_DIR / "setup_path.py"
        path_args = ["--bin-dir", str(bin_dir), "--dotfiles-dir", str(dotfiles_dir)]
        if args.verbose: path_args.append("--verbose")
        run_setup(setup_path_script, *path_args)

    # Optional: wire PowerShell profile if on Windows/WSL
    with sui_section("PowerShell profile wiring", level="major"):
        run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_pwsh_profile.py",
                  "--scripts-dir", str(scripts_dir),
                  "--dotfiles-dir", str(dotfiles_dir))

    # Discover and symlink SKILL.md-based skills to CLI directories
    with sui_section("Agent skill symlinks (setup_skills.py)", level="major"):
        skill_args = []
        if args.verbose:
            skill_args.append("--verbose")
        run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_skills.py", *skill_args)

    # Setup automatic venv activation
    with sui_section("Virtual environment auto-activation setup", level="major"):
        try:
            from python_setup.venv_activation import setup_auto_activation
            ps_changed, bash_changed = setup_auto_activation(dotfiles_dir, verbose=args.verbose)
            if ps_changed or bash_changed:
                log_success("Auto-activation configured for Python venvs")
                if ps_changed:
                    log_info(f"PowerShell: source {dotfiles_dir / 'dynamic' / 'venv_auto_activation.ps1'} in your profile")
                if bash_changed:
                    log_info(f"Bash/Zsh: source {dotfiles_dir / 'dynamic' / 'venv_auto_activation.sh'} in your rc file")
            else:
                status_line("Auto-activation already configured", "unchanged")
        except Exception as e:
            log_warning(f"Could not setup venv auto-activation: {e}")
            log_info("You can manually run: setup-venv-activation -D /path/to/dotfiles")

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
