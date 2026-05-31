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
import shutil
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


def report_or_repair_invalid_aebndl_dists(*, repair: bool = False) -> int:
    leftovers: list[Path] = []
    for site_packages in _venv_site_packages_candidates():
        leftovers.extend(find_invalid_aebndl_dist_leftovers(site_packages))
    if not leftovers:
        return 0
    action = "Removing" if repair else "Detected"
    message = f"[BOOTSTRAP] {action} {len(leftovers)} invalid aebndl pip leftover(s)"
    _log_append(message)
    if _is_verbose:
        print(message + ":")
    for path in leftovers:
        _log_append(f"  - {path}")
        if _is_verbose:
            print(f"  - {path}")
        if repair:
            try:
                if path.is_dir():
                    import shutil

                    shutil.rmtree(path)
                else:
                    path.unlink()
            except Exception as exc:
                _log_append(f"    [WARN] Could not remove: {exc}")
                if _is_verbose:
                    print(f"    [WARN] Could not remove: {exc}")
    if not repair:
        guidance = "[BOOTSTRAP] Re-run with --repair-invalid-aebndl-dists to remove these leftovers."
        _log_append(guidance)
        if _is_verbose:
            print(guidance)
    return len(leftovers)

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
GLOBAL_LOG = SCRIPTS_DIR / "setup_log.log"

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
_setup_started_at = time.time()
_active_group = None


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _supports_color() else text


def _format_elapsed(seconds: float) -> str:
    return f"{seconds:.2f}s"


class CompactGroup:
    """Two-line non-verbose group renderer with optional per-module accounting."""

    def __init__(self, title: str, total: int | None = None, *, modules: bool = False):
        self.title = title
        self.total = total
        self.modules = modules
        self.started = 0.0
        self.states: dict[str, str] = {}
        self.failures: list[str] = []
        self.summary_fields: list[tuple[str, str | None]] = []
        self._line_open = False

    def __enter__(self):
        global _active_group
        self.started = time.time()
        _active_group = self
        count = f" ({self.total} items)" if self.total is not None else ""
        print(_color(f"{self.title}{count}", "1;36"))
        self.progress("starting")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        global _active_group
        if exc_value is not None:
            self.failures.append(str(exc_value))
        self.finish()
        _active_group = None
        return False

    def progress(self, item: str) -> None:
        line = f"  Processing: {item}"
        print(f"\r\033[2K{line}", end="", flush=True)
        self._line_open = True

    def observe_status(self, label: str, state: str | None, detail: str | None) -> None:
        if not self.modules:
            if state in {"fail", "warn"}:
                self.failures.append(label)
            self.progress(label)

    def observe_child_line(self, line: str) -> None:
        if not self.modules:
            return
        plain = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        found = re.search(r"Found\s+(\d+)\s+module\(s\)\s+to process", plain)
        if found:
            self.total = int(found.group(1))
            return
        match = re.match(r"^\[[^\]]+\]\s+([^:]+):\s+(.*)$", plain)
        if not match:
            return
        name, detail = match.groups()
        if name in {"ERROR", "WARNING", "SUCCESS", "INFO"}:
            return
        lowered = detail.lower()
        if "install failed" in lowered or "failure" in lowered:
            state = "failed"
        elif "installed" in lowered and "requirements" not in lowered:
            state = "installed"
        elif any(word in lowered for word in ("skip", "ignored", "not a directory", "no installer", "runtime ready")):
            state = "skipped"
        else:
            self.progress(name)
            return
        self.states[name] = state
        if state == "failed" and name not in self.failures:
            self.failures.append(name)
        self.progress(name)

    def mark_result(self, item: str, state: str) -> None:
        self.states[item] = state
        if state == "failed" and item not in self.failures:
            self.failures.append(item)
        self.progress(item)

    def add_summary_field(self, text: str, color: str | None = None) -> None:
        self.summary_fields.append((text, color))

    def end_progress_line(self) -> None:
        if self._line_open:
            print()
            self._line_open = False

    def finish(self) -> None:
        delta = time.time() - self.started
        total_delta = time.time() - _setup_started_at
        total = self.total if self.total is not None else max(len(self.states), 1)
        failed = sum(state == "failed" for state in self.states.values())
        done = max(total - failed, 0) if self.modules else (0 if self.failures else total)
        icon = "X" if self.failures or failed else ("OK" if _ASCII_UI else "✓")
        status_text = f"{icon} {done}/{total} processed"
        style = "1;31" if self.failures or failed else "1;32"
        fields = [_color(status_text, style)]
        if self.modules:
            installed = sum(state == "installed" for state in self.states.values())
            skipped = sum(state == "skipped" for state in self.states.values())
            fields.extend([_color(f"{installed} installed", "1;32"), _color(f"{skipped} skipped", "1;33"), f"{total} total"])
        fields.extend(_color(text, color) if color else text for text, color in self.summary_fields)
        final = f"[{_format_elapsed(total_delta)}][{_format_elapsed(delta)}] " + ", ".join(fields)
        print(f"\r\033[2K{final}")
        for failure in self.failures[:3]:
            print(_color(f"    - {failure}", "31"))
        if len(self.failures) > 3:
            print(_color("    - ...", "31"))


def setup_group(title: str, total: int | None = None, *, modules: bool = False):
    if _is_verbose:
        return sui_section(title, level="major")
    return CompactGroup(title, total, modules=modules)

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
def init_timer():
    return None


def print_global_elapsed():
    return None


log_info, log_success, log_warning, log_error = _fb_log_info, _fb_log_success, _fb_log_warning, _fb_log_error
_section_impl = _FBSection
_status_impl = _fb_status_line

try:
    if not _ASCII_UI:
        try:
            import standard_ui.standard_ui as _sui
        except ModuleNotFoundError:
            import standard_ui as _sui
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


_raw_log_info = log_info
_raw_log_success = log_success
_raw_log_warning = log_warning
_raw_log_error = log_error


def log_info(message: str):
    _log_append(f"[INFO] {message}")
    if _is_verbose:
        _raw_log_info(message)


def log_success(message: str):
    _log_append(f"[SUCCESS] {message}")
    if _is_verbose or _active_group is None:
        _raw_log_success(message)
    elif _active_group is not None:
        _active_group.progress(message)


def log_warning(message: str):
    _log_append(f"[WARNING] {message}")
    if _is_verbose or _active_group is None:
        _raw_log_warning(message)
    elif _active_group is not None:
        _active_group.progress(message)


def log_error(message: str):
    _log_append(f"[ERROR] {message}")
    if _is_verbose or _active_group is None:
        _raw_log_error(message)
    elif _active_group is not None:
        if message not in _active_group.failures:
            _active_group.failures.append(message)
        _active_group.progress(message)


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

    if not _is_verbose and _active_group is not None:
        _active_group.observe_status(label, state, detail)
        return None

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
    global init_timer, print_global_elapsed, _raw_log_info, _raw_log_success, _raw_log_warning, _raw_log_error, _section_impl, _status_impl
    try:
        importlib.invalidate_caches()
        try:
            import standard_ui.standard_ui as _sui2
        except ModuleNotFoundError:
            import standard_ui as _sui2
        init_timer           = getattr(_sui2, "init_timer", init_timer)
        print_global_elapsed = getattr(_sui2, "print_global_elapsed", print_global_elapsed)
        _raw_log_info        = getattr(_sui2, "log_info", _raw_log_info)
        _raw_log_success     = getattr(_sui2, "log_success", _raw_log_success)
        _raw_log_warning     = getattr(_sui2, "log_warning", _raw_log_warning)
        _raw_log_error       = getattr(_sui2, "log_error", _raw_log_error)
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
    _log_append("\n".join(msg_lines))

# ─────────────────────────────────────────────────────────
# Child process runner with stall detection
# ─────────────────────────────────────────────────────────
STALL_NOTICE_AFTER = int(os.environ.get("SETUP_STALL_NOTICE_SEC", "30"))
STALL_AUTO_CONFIRM_AFTER = int(os.environ.get("SETUP_STALL_AUTOCONFIRM_SEC", "45"))
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
                _log_append(line.rstrip("\n"))
                if _is_verbose:
                    try:
                        sys.stdout.write(line)
                    except Exception:
                        pass
                elif _active_group is not None:
                    _active_group.observe_child_line(line)
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
                _log_append(hint.rstrip("\n"))
                if _is_verbose:
                    print(hint, end="")
                elif _active_group is not None:
                    _active_group.progress("waiting for child output")
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
                    _log_append(msg)
                    if _is_verbose:
                        print(msg)
                    elif _active_group is not None:
                        _active_group.progress("confirming stalled child prompt")
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
        if not _is_verbose and _active_group is not None:
            _active_group.mark_result(resolved.name, "failed")
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
        if not _is_verbose and _active_group is not None and _active_group.modules and not failed:
            _active_group.mark_result(resolved.name, "failed")
        write_error_log_detail(f"Setup {resolved.name}", None, out, "")

# ─────────────────────────────────────────────────────────
# Post-install help registry drift check
# ─────────────────────────────────────────────────────────

def _offer_registry_update_via_ai(drift: dict, build_prompt) -> None:
    import shutil as _shutil
    ai_tools = []
    if _shutil.which("claude"):
        ai_tools.append(("Claude Code", "claude"))
    if _shutil.which("codex"):
        ai_tools.append(("Codex", "codex"))

    if not ai_tools:
        log_warning("Neither 'claude' nor 'codex' found on PATH. Update registry manually with: scripts-help")
        return

    print()
    print("  An AI assistant can update the help registry automatically.")
    print("  Options:\n")
    for i, (label, _) in enumerate(ai_tools, 1):
        print(f"    {i}. Launch {label}")
    print(f"    {len(ai_tools) + 1}. Skip — I'll update the registry later")

    while True:
        try:
            raw = input(f"\n  [1-{len(ai_tools) + 1}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            choice = int(raw)
        except ValueError:
            continue
        if 1 <= choice <= len(ai_tools):
            cmd = ai_tools[choice - 1][1]
            prompt = build_prompt(drift)
            log_info(f"Launching {cmd} with registry update instructions...")
            try:
                os.chdir(str(SCRIPTS_DIR))
                subprocess.run([cmd, prompt])
            except Exception as exc:
                log_warning(f"Failed to launch {cmd}: {exc}")
            return
        if choice == len(ai_tools) + 1:
            return


def _help_update_counts(drift: dict, registered_items: list[dict]) -> tuple[int, int, int, int]:
    registered_paths = {item["path"] for item in registered_items}
    known_paths = registered_paths | set(drift["new"])
    readme_issues = [item for item in drift.get("readme", []) if item["issue"] != "missing"]
    update_paths = (
        {item["path"] for item in readme_issues}
        | set(drift["new"])
        | {item["path"] for item in drift["stale"]}
        | {item["path"] for item in drift["deleted"]}
    )
    module_total = sum(path.startswith("modules/") for path in known_paths)
    script_total = sum(path.startswith("pyscripts/") for path in known_paths)
    module_updates = sum(path.startswith("modules/") for path in update_paths)
    script_updates = sum(path.startswith("pyscripts/") for path in update_paths)
    return module_updates, module_total, script_updates, script_total


def _run_post_install_drift_check(no_update_help: bool) -> None:
    if no_update_help:
        status_line("Help registry drift check skipped (--no-update-help)", "unchanged")
        return
    try:
        import importlib as _il
        _il.invalidate_caches()
        # Ensure the module directory is importable even before pip installs it
        _sh_path = str(MODULES_DIR / "scripts_help")
        if _sh_path not in sys.path:
            sys.path.insert(0, _sh_path)
        from scripts_help.cli import _build_update_prompt, _collect_registered_items, collect_drift  # type: ignore
    except ImportError:
        status_line("scripts_help not installed; skipping drift check", "unchanged")
        return
    except Exception as exc:
        log_warning(f"Help registry import failed: {exc}")
        return

    try:
        drift = collect_drift()
    except Exception as exc:
        log_warning(f"Help registry drift check failed: {exc}")
        return

    readme_issues = [r for r in drift.get("readme", []) if r["issue"] != "missing"]
    has_registry_drift = bool(drift["new"] or drift["stale"] or drift["deleted"])
    has_readme_drift   = bool(readme_issues)
    module_updates, module_total, script_updates, script_total = _help_update_counts(drift, _collect_registered_items())
    help_counts = f"modules {module_updates}/{module_total} need help updates, scripts {script_updates}/{script_total} need help updates"
    log_info(f"Help sync: {help_counts}")
    if not _is_verbose and _active_group is not None:
        _active_group.add_summary_field(
            f"modules {module_updates}/{module_total} help updates",
            "1;31" if module_updates else "1;32",
        )
        _active_group.add_summary_field(
            f"scripts {script_updates}/{script_total} help updates",
            "1;31" if script_updates else "1;32",
        )

    if not has_registry_drift and not has_readme_drift:
        status_line("Help registry and READMEs are up to date", "ok")
        return

    if has_registry_drift:
        parts = []
        if drift["new"]:
            parts.append(f"{len(drift['new'])} new")
        if drift["stale"]:
            parts.append(f"{len(drift['stale'])} stale")
        if drift["deleted"]:
            parts.append(f"{len(drift['deleted'])} deleted")
        log_warning(f"Registry drift: {', '.join(parts)}")

    if has_readme_drift:
        rd: dict[str, int] = {}
        for r in readme_issues:
            rd[r["issue"]] = rd.get(r["issue"], 0) + 1
        readme_summary = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in rd.items())
        log_warning(f"README drift: {readme_summary}")

    missing_count = sum(1 for r in drift.get("readme", []) if r["issue"] == "missing")
    if missing_count:
        log_info(f"  ({missing_count} programs have no README yet — run: scripts-help sync -r)")

    if not _is_verbose and _active_group is not None:
        _active_group.end_progress_line()
    _offer_registry_update_via_ai(drift, _build_update_prompt)


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
    parser.add_argument(
        "-U", "--no-update-help",
        action="store_true",
        default=False,
        help="Skip the post-install help registry drift check and AI update offer.",
    )

    args = parser.parse_args()
    _is_verbose = args.verbose
    with setup_group("Environment Checks", 1):
        leftover_count = report_or_repair_invalid_aebndl_dists(repair=args.repair_invalid_aebndl_dists)
        detail = "clean" if not leftover_count else f"{leftover_count} pip leftover(s) noted in setup_log.log"
        status_line("aebndl pip distribution health", "unchanged", detail)

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

    # Core modules — now safe because we're under ./.venv
    # Order matters: cross_platform must be installed before python_setup (dependency)
    with setup_group("Core Modules", 4):
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
        with setup_group("WSL2 Integration", 1):
            run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_wsl2.py", "--verbose")
    else:
        with setup_group("WSL2 Integration", 1):
            status_line("win32yank setup skipped: not WSL2", "unchanged")

    # Sub-setups
    common_setup_args = [
        "--scripts-dir", str(scripts_dir),
        "--dotfiles-dir", str(dotfiles_dir),
        "--bin-dir", str(bin_dir),
    ]
    # Child output is always verbose in setup_log.log; compact terminal mode hides the stream.
    common_setup_args.append("--verbose")
    if skip_reinstall:
        common_setup_args.append("--skip-reinstall")
    else:
        common_setup_args.append("--no-skip-reinstall")
    if args.production:
        common_setup_args.append("--production")

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
        is_modules = full_script_path == MODULES_DIR / "setup.py"
        total = len(list(MODULES_DIR.iterdir())) if is_modules and MODULES_DIR.exists() else 1
        title = "Python Modules" if is_modules else f"Sub-setup: {title_rel_path}"
        with setup_group(title, total, modules=is_modules):
            run_setup(full_script_path, *(common_setup_args + extra_args), soft_fail_modules=soft_fail_modules)

    with setup_group("Shell PATH Configuration", 1):
        setup_path_script = SCRIPTS_SETUP_PACKAGE_DIR / "setup_path.py"
        path_args = ["--bin-dir", str(bin_dir), "--dotfiles-dir", str(dotfiles_dir)]
        path_args.append("--verbose")
        run_setup(setup_path_script, *path_args)

    # Optional: wire PowerShell profile if on Windows/WSL
    with setup_group("PowerShell Profile Wiring", 1):
        run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_pwsh_profile.py",
                  "--scripts-dir", str(scripts_dir),
                  "--dotfiles-dir", str(dotfiles_dir),
                  "--verbose")

    # Discover and symlink SKILL.md-based skills to CLI directories
    with setup_group("Agent Skill Symlinks", 1):
        skill_args = ["--verbose"]
        run_setup(SCRIPTS_SETUP_PACKAGE_DIR / "setup_skills.py", *skill_args)

    # Setup automatic venv activation
    with setup_group("Virtual Environment Auto-Activation", 1):
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

    if args.verbose:
        try:
            print_global_elapsed()
        except Exception:
            pass

    with setup_group("Help Registry Drift Check", 1):
        _run_post_install_drift_check(args.no_update_help)

    failure_messages = [message for message in warnings if "failed" in message.lower()]
    run_failed = bool(errors or failure_messages)
    if errors:
        if warnings:
            log_warning(f"Setup completed with {len(errors)} error(s) and {len(warnings)} warning(s). See {ERROR_LOG}.")
        else:
            log_error(f"Setup completed with {len(errors)} error(s). See {ERROR_LOG}.")
    elif warnings:
        suffix = f" See {ERROR_LOG}." if run_failed else ""
        log_warning(f"Setup completed with {len(warnings)} warning(s).{suffix}")
    else:
        log_success("All setup steps completed successfully.")
    if run_failed:
        try:
            shutil.copyfile(GLOBAL_LOG, ERROR_LOG)
        except OSError as exc:
            log_error(f"Failed to copy verbose setup log to '{ERROR_LOG}': {exc}")
    sys.exit(1 if errors else 0)

if __name__ == "__main__":
    main()
