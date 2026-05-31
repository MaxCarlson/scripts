#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import subprocess
from pathlib import Path
import re
import shutil
import sysconfig
import time
from importlib import metadata

# ─────────────────────────────────────────────────────────
# TOML support (tomllib on 3.11+, tomli otherwise)
# ─────────────────────────────────────────────────────────
try:
    import tomllib  # Py3.11+
except Exception:
    try:
        import tomli as tomllib  # Py<=3.10
    except Exception:
        print("[ERROR] 'tomli' (for TOML parsing) is not installed.", file=sys.stderr)
        print("[ERROR] Please run the root setup.py or: pip install tomli", file=sys.stderr)
        sys.exit(1)

# ─────────────────────────────────────────────────────────
# standard_ui fallbacks + ASCII/Unicode handling
# ─────────────────────────────────────────────────────────
_is_verbose = ("--verbose" in sys.argv) or ("-v" in sys.argv)

def _needs_ascii_ui() -> bool:
    if os.environ.get("FORCE_ASCII_UI") == "1":
        return True
    enc = (getattr(sys.stdout, "encoding", "") or "").upper()
    return os.name == "nt" and "UTF-8" not in enc

_ASCII_UI = _needs_ascii_ui()

def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(sys.stderr, "isatty", lambda: False)())

def _red(text: str) -> str:
    if not _supports_color():
        return text
    return f"\033[31m{text}\033[0m"

def _print_dependency_failure_group(module_name: str, failed_items: list[str], detail: str | None = None) -> None:
    print(_red(f"[ERROR] {module_name}: dependency install failed"), file=sys.stderr)
    if detail:
        print(_red(f"    {detail}"), file=sys.stderr)
    for item in failed_items:
        print(_red(f"    - {item}"), file=sys.stderr)

def _fb_info(msg):
    if _is_verbose:
        print(f"[INFO] {msg}")
def _fb_success(msg): print(f"[SUCCESS] {msg}")
def _fb_warn(msg): print(f"[WARNING] {msg}")
def _fb_err(msg): print(f"[ERROR] {msg}")

class _FBSection:
    def __init__(self, title):
        self.title = title
        self._t = None
    def __enter__(self):
        self._t = time.time()
        banner = f"---- {self.title} - START ----" if _ASCII_UI else f"\n──────── {self.title} - START ────────"
        print(banner)
        return self
    def __exit__(self, *_):
        elapsed = time.time() - (self._t or time.time())
        banner = f"---- {self.title} - END (Elapsed: {elapsed:.2f}s) ----" if _ASCII_UI else f"──────── {self.title} - END (Elapsed: {elapsed:.2f}s) ────────"
        if _is_verbose:
            print(banner)

def _fb_status(label: str, state: str | None = None, detail: str | None = None):
    prefix = {"unchanged": "-", "ok": "OK", "warn": "!", "fail": "X"} if _ASCII_UI else \
             {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}
    tail = (f" - {detail}" if _ASCII_UI else f" — {detail}") if detail else ""
    print(f"[{prefix.get(state or '', prefix['unchanged'])}] {label}{tail}")

log_info, log_success, log_warning, log_error, section = _fb_info, _fb_success, _fb_warn, _fb_err, _FBSection
_status_impl = _fb_status

try:
    if not _ASCII_UI:
        try:
            from standard_ui.standard_ui import (
                log_info as _s_log_info,
                log_success as _s_log_success,
                log_warning as _s_log_warning,
                log_error as _s_log_error,
                section as _s_section,
                status_line as _s_status_line,
            )
        except ModuleNotFoundError:
            from standard_ui import (
                log_info as _s_log_info,
                log_success as _s_log_success,
                log_warning as _s_log_warning,
                log_error as _s_log_error,
                section as _s_section,
                status_line as _s_status_line,
            )
        log_info, log_success, log_warning, log_error, section = (
            _s_log_info, _s_log_success, _s_log_warning, _s_log_error, _s_section
        )
        _status_impl = _s_status_line
    else:
        if _is_verbose:
            print("[WARNING] Non-UTF-8 console detected; using ASCII UI.")
except Exception:
    if _is_verbose:
        print("[WARNING] standard_ui not available in modules/setup.py; using fallback logging.")

def status_line(label: str, state: str | None = None, detail: str | None = None):
    impl = _status_impl
    if impl is _fb_status:
        return impl(label, state, detail)
    try:
        return impl(label, state, detail)      # 3-arg
    except TypeError:
        pass
    try:
        return impl(label, state)              # 2-arg
    except TypeError:
        pass
    prefix = {"unchanged": "-", "ok": "OK", "warn": "!", "fail": "X"} if _ASCII_UI else \
             {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}
    tail = (f" - {detail}" if _ASCII_UI else f" — {detail}") if detail else ""
    try:
        return impl(f"[{prefix.get(state or '', prefix['unchanged'])}] {label}{tail}")
    except TypeError:
        return _fb_status(label, state, detail)

# ─────────────────────────────────────────────────────────
# Helpers: package name detection & install status
# ─────────────────────────────────────────────────────────
def _pkg_name_from_source(module_dir: Path, verbose: bool) -> str:
    pyproject = module_dir / "pyproject.toml"
    fallback = module_dir.name
    if pyproject.is_file():
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            if "project" in data and "name" in data["project"]:
                return data["project"]["name"]
            if "tool" in data and "poetry" in data["tool"] and "name" in data["tool"]["poetry"]:
                return data["tool"]["poetry"]["name"]
        except Exception as e:
            if verbose:
                log_warning(f"[{fallback}] pyproject.toml parse issue: {type(e).__name__}: {e}")
    return fallback

def _project_version_from_source(module_dir: Path, verbose: bool) -> str | None:
    pyproject = module_dir / "pyproject.toml"
    try:
        if pyproject.is_file():
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            if "project" in data and "version" in data["project"]:
                return str(data["project"]["version"])
            if "tool" in data and "poetry" in data["tool"] and "version" in data["tool"]["poetry"]:
                return str(data["tool"]["poetry"]["version"])
    except Exception as e:
        if verbose:
            log_warning(f"[{module_dir.name}] pyproject.toml version parse issue: {type(e).__name__}: {e}")
    setup_py = module_dir / "setup.py"
    if setup_py.is_file():
        try:
            text = setup_py.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"\bversion\s*=\s*['\"]([^'\"]+)['\"]", text)
            if match:
                return match.group(1)
        except Exception as e:
            if verbose:
                log_warning(f"[{module_dir.name}] setup.py version parse issue: {type(e).__name__}: {e}")
    return None

def _installed_pkg_version(pkg_name: str, verbose: bool) -> str | None:
    try:
        return metadata.version(pkg_name)
    except metadata.PackageNotFoundError:
        return None
    except Exception as e:
        if verbose:
            log_warning(f"metadata.version error for '{pkg_name}': {type(e).__name__}: {e}")
        return None


def _normalize_dist_token(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _remove_stale_metadata_path(path: Path, *, verbose: bool) -> bool:
    try:
        shutil.rmtree(path) if path.is_dir() else path.unlink()
        if verbose:
            log_info(f"Removed stale editable metadata: {path}")
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:
        if verbose:
            log_warning(f"Could not remove stale editable metadata {path}: {exc}")
        return False


def _prune_stale_editable_metadata(pkg_name: str, keep_version: str | None, verbose: bool) -> int:
    if not keep_version:
        return 0

    normalized_pkg = _normalize_dist_token(pkg_name)
    keep_finder_marker = "_" + keep_version.replace(".", "_").replace("-", "_") + "_finder_py"
    removed = 0
    site_roots = {
        Path(path).resolve()
        for path in (sysconfig.get_path("purelib"), sysconfig.get_path("platlib"))
        if path and Path(path).exists()
    }

    for site_packages in site_roots:
        patterns = ("*.dist-info", "__editable__.*.pth", "__editable__*_finder.py")
        for path in (candidate for pattern in patterns for candidate in site_packages.glob(pattern)):
            normalized_name = _normalize_dist_token(path.name)
            if normalized_pkg not in normalized_name or keep_version in path.name or keep_finder_marker in normalized_name:
                continue
            removed += int(_remove_stale_metadata_path(path, verbose=verbose))

    if removed:
        log_info(f"Removed {removed} stale editable metadata file(s) for {pkg_name}")
    return removed


def _determine_install_status(module_dir: Path, verbose: bool) -> str | None:
    pkg = _pkg_name_from_source(module_dir, verbose)
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg],
            capture_output=True, text=True, check=False, encoding="utf-8", errors="ignore"
        )
        if out.returncode != 0:
            return None
        editable_here = False
        for line in out.stdout.splitlines():
            if line.lower().startswith("editable project location:"):
                loc = line.split(":", 1)[1].strip()
                if loc and loc.lower() != "none":
                    try:
                        editable_here = (Path(loc).resolve() == module_dir.resolve())
                    except Exception:
                        pass
                break
        return "editable" if editable_here else "normal"
    except Exception as e:
        if verbose:
            log_warning(f"pip show error for '{pkg}': {type(e).__name__}: {e}")
        return None

# ─────────────────────────────────────────────────────────
# Popen runner with logging; heartbeat optional
# ─────────────────────────────────────────────────────────
def _run_with_log(cmd: list[str], log_path: Path, *, verbose: bool, heartbeat_every: float = 5.0) -> int:
    """
    If verbose=True: stream combined output to console and log.
    Else: write to log only and print a heartbeat dot every few seconds.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if verbose:
        with open(log_path, "ab") as lf:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="ignore", bufsize=1
            )
            for line in iter(proc.stdout.readline, ""):
                sys.stdout.write(line)
                sys.stdout.flush()
                lf.write(line.encode("utf-8", "ignore"))
            proc.stdout.close()
            return proc.wait()
    else:
        with open(log_path, "ab") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf, text=False)
            next_tick = time.time() + heartbeat_every
            while True:
                rc = proc.poll()
                if rc is not None:
                    return rc
                if time.time() >= next_tick:
                    sys.stdout.write(".")
                    sys.stdout.flush()
                    next_tick = time.time() + heartbeat_every
                time.sleep(0.25)


WINERROR32_RE = re.compile(r"\[WinError 32\].*?: '([^']+)'")


def _extract_locked_console_script(log_path: Path) -> Path | None:
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = WINERROR32_RE.search(text)
    if not match:
        return None
    path = Path(match.group(1))
    if path.name.lower().endswith((".exe", ".cmd", ".ps1")):
        return path
    return None


def _find_likely_locking_processes(path: Path) -> list[str]:
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    wanted = str(path).lower()
    matches: list[str] = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            open_files = proc.open_files() or []
            for opened in open_files:
                if str(opened.path).lower() == wanted:
                    info = proc.info
                    matches.append(f"{info.get('name') or '?'} pid={info.get('pid')}")
                    break
        except Exception:
            continue
    return matches


def _locked_console_script_diagnostic(log_path: Path) -> list[str]:
    locked = _extract_locked_console_script(log_path)
    if locked is None:
        return []
    lines = [
        f"locked console script: {locked}",
        "Close any running command using this executable, then rerun bootstrap.",
    ]
    owners = _find_likely_locking_processes(locked)
    if owners:
        lines.append("likely owner(s): " + ", ".join(owners))
    else:
        lines.append("owning process not discoverable without psutil/open-file access")
    return lines

# ─────────────────────────────────────────────────────────
# Requirements handling
# ─────────────────────────────────────────────────────────
def _parse_requirements(req_file: Path) -> list[str]:
    reqs: list[str] = []
    try:
        for raw in req_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if " #" in line:
                line = line.split(" #", 1)[0].strip()
            reqs.append(line)
    except Exception:
        pass
    return reqs

def _project_dependencies_from_source(module_dir: Path) -> list[str]:
    pyproject = module_dir / "pyproject.toml"
    if not pyproject.is_file():
        return []
    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        dependencies = data.get("project", {}).get("dependencies", [])
    except Exception:
        return []
    if not isinstance(dependencies, list):
        return []
    return [str(dep) for dep in dependencies if dep]

def _extract_failed_dependency_names(log_file: Path) -> list[str]:
    try:
        text = log_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    patterns = [
        r"Failed building wheel for\s+([A-Za-z0-9_.\-]+)",
        r"Could not build wheels for\s+([A-Za-z0-9_.\-]+)",
        r"No matching distribution found for\s+([A-Za-z0-9_.\-\[\]<>=!~,\"]+)",
        r"Could not find a version that satisfies the requirement\s+([A-Za-z0-9_.\-\[\]<>=!~,\"]+)",
        r"ERROR:\s+Could not install packages due to an OSError:\s+(.+)",
    ]
    failed: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = match.group(1).strip()
            if value and value not in failed:
                failed.append(value)
    return failed

def _install_requirements(module_name: str, module_dir: Path, reqs: list[str], logs_dir: Path, verbose: bool) -> tuple[int, list[tuple[str, bool, int]]]:
    """
    Installs each requirement separately so we can show progress and partial failures.
    Returns (num_failures, [(req, ok, rc), ...]).
    """
    results: list[tuple[str, bool, int]] = []
    total = len(reqs)
    if total == 0:
        return 0, results

    log_file = logs_dir / f"{module_name}-pip.log"
    try:
        with open(log_file, "a", encoding="utf-8") as lf:
            lf.write(f"\n=== Requirements for {module_name} ===\n")
    except Exception:
        pass

    num_fail = 0
    for i, req in enumerate(reqs, start=1):
        sys.stdout.write(f"\r{module_name}: {i}/{total} …")
        sys.stdout.flush()

        cmd = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", req]
        if not verbose:
            cmd.insert(4, "-q")
        rc = _run_with_log(cmd, log_file, verbose=verbose)
        ok = (rc == 0)
        results.append((req, ok, rc))
        if not ok:
            num_fail += 1

    sys.stdout.write("\n")
    sys.stdout.flush()
    return num_fail, results

def _package_installed(package_name: str) -> bool:
    return _installed_pkg_version(package_name, verbose=False) is not None

def _torch_cuda_build_installed() -> bool:
    code = (
        "import torch; "
        "raise SystemExit(0 if torch.version.cuda else 1)"
    )
    result = subprocess.run([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0

def _vdedup_gpu_requirements_installed() -> bool:
    return _torch_cuda_build_installed() and _package_installed("PyNvVideoCodec")

def _install_vdedup_gpu_requirements(module_dir: Path, logs_dir: Path, verbose: bool) -> int:
    if _vdedup_gpu_requirements_installed():
        return 0
    req_file = module_dir / "requirements-gpu.txt"
    if not req_file.exists():
        return 0
    status_line("vdedup: GPU requirements missing or CPU-only torch", "warn", "installing GPU requirements")
    log_file = logs_dir / "vdedup-gpu-requirements-pip.log"
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-input",
        "--disable-pip-version-check",
        "--force-reinstall",
        "-r",
        str(req_file),
    ]
    if not verbose:
        cmd.insert(4, "-q")
    return _run_with_log(cmd, log_file, verbose=verbose, heartbeat_every=15.0)

def _web_docs_processor_runtime_ready() -> tuple[bool, str]:
    code = (
        "from pathlib import Path\n"
        "import reportlab\n"
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    path = Path(p.chromium.executable_path)\n"
        "    raise SystemExit(0 if path.exists() else 2)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="ignore",
    )
    if result.returncode == 0:
        return True, "runtime ready"
    detail = (result.stderr or result.stdout or f"check exited {result.returncode}").strip()
    return False, detail.splitlines()[-1] if detail else f"check exited {result.returncode}"

def _install_web_docs_processor_browsers(logs_dir: Path, verbose: bool) -> int:
    log_file = logs_dir / "web_docs_processor-browser-install.log"
    cmd = [
        sys.executable,
        "-m",
        "web_docs_processor.docs_source_builder",
        "setup-browsers",
        "-b",
        "chromium",
    ]
    if not verbose:
        status_line("web_docs_processor: Chromium runtime missing", "warn", "installing browser runtime")
    return _run_with_log(cmd, log_file, verbose=verbose, heartbeat_every=15.0)

def _ensure_web_docs_processor_runtime(module_dir: Path, logs_dir: Path, *, editable: bool, verbose: bool) -> int:
    ready, detail = _web_docs_processor_runtime_ready()
    if ready:
        return 0

    log_info(f"web_docs_processor: runtime check failed ({detail})")
    rc = _install_web_docs_processor_browsers(logs_dir, verbose)
    if rc != 0:
        return rc

    ready, detail = _web_docs_processor_runtime_ready()
    if ready:
        return 0

    log_info(f"web_docs_processor: browser install did not fix runtime check ({detail}); reinstalling module.")
    return _install_module("web_docs_processor", module_dir, editable=editable, logs_dir=logs_dir, verbose=verbose)

# ─────────────────────────────────────────────────────────
# Install a module (editable/non-editable), quiet with log
# ─────────────────────────────────────────────────────────
def _install_module(module_name: str, module_dir: Path, *, editable: bool, logs_dir: Path, verbose: bool) -> int:
    log_file = logs_dir / f"{module_name}-pip.log"
    cmd = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check"]
    if not verbose:
        cmd.insert(4, "-q")
    if editable:
        cmd.append("-e")
    cmd.append(str(module_dir.resolve()))
    rc = _run_with_log(cmd, log_file, verbose=verbose)
    if rc == 0:
        _prune_stale_editable_metadata(_pkg_name_from_source(module_dir, verbose), _project_version_from_source(module_dir, verbose), verbose)
    return rc

# ─────────────────────────────────────────────────────────
# Scan + install modules (and remember names for proxy generation)
# ─────────────────────────────────────────────────────────
def install_python_modules(modules_dir: Path, logs_dir: Path, *, skip_reinstall: bool, production: bool, verbose: bool, include_hidden: bool) -> list[str]:
    errors_encountered: list[str] = []
    hidden_skipped: list[str] = []
    touched_pkgs: list[str] = []  # keep distribution names we installed/checked
    locked_failed_pkgs: set[str] = set()
    seen_pkg_sources: dict[str, Path] = {}

    if not modules_dir.exists() or not modules_dir.is_dir():
        status_line(f"{modules_dir}: not found — skipped", "warn")
        return errors_encountered, touched_pkgs

    with section("Python Modules Installation"):
        # Try to use dependency-aware ordering
        try:
            setup_utils_dir = modules_dir.parent / "setup_utils"
            if (setup_utils_dir / "dependency_resolver.py").exists():
                sys.path.insert(0, str(setup_utils_dir))
                from dependency_resolver import resolve_module_order
                ordered_names = resolve_module_order(modules_dir)
                entries = [modules_dir / name for name in ordered_names if (modules_dir / name).exists()]
                if verbose:
                    log_info(f"Using dependency-aware installation order: {', '.join(ordered_names)}")
            else:
                entries = sorted(modules_dir.iterdir(), key=lambda p: p.name.lower())
        except Exception as e:
            if verbose:
                log_warning(f"Dependency resolver failed ({e}), using alphabetical order")
            entries = sorted(modules_dir.iterdir(), key=lambda p: p.name.lower())

        print(f"[•] Found {len(entries)} module(s) to process") if not _ASCII_UI else print(f"[-] Found {len(entries)} module(s) to process")

        for entry in entries:
            name = entry.name

            if entry.resolve() == Path(__file__).resolve().parent:
                status_line(f"{name}: internal setup folder — skipped", "unchanged")
                continue

            if not entry.is_dir():
                status_line(f"{name}: not a directory — skipped", "unchanged")
                continue

            if name.startswith(".") and not include_hidden:
                status_line(f"{name}: ignored (hidden)", "unchanged")
                hidden_skipped.append(name)
                continue

            has_setup_py = (entry / "setup.py").exists()
            has_pyproject = (entry / "pyproject.toml").exists()
            req_file = entry / "requirements.txt"

            if not has_setup_py and not has_pyproject:
                status_line(f"{name}: no installer (no setup.py/pyproject.toml) — skipped", "unchanged")
                continue

            if not has_pyproject:
                log_warning(f"{name}: pyproject.toml not found — continuing, but modern metadata is recommended.")

            pkg_name_for_entry = _pkg_name_from_source(entry, verbose)
            previous_source = seen_pkg_sources.get(pkg_name_for_entry)
            if previous_source is not None and previous_source.resolve() != entry.resolve():
                status_line(
                    f"{name}: duplicate package '{pkg_name_for_entry}' — skipped",
                    "warn",
                    f"already handled by {previous_source.name}",
                )
                continue
            seen_pkg_sources[pkg_name_for_entry] = entry
            if pkg_name_for_entry in locked_failed_pkgs:
                status_line(
                    f"{name}: skipped after locked console-script failure",
                    "warn",
                    "close the running executable and rerun bootstrap",
                )
                errors_encountered.append(name)
                continue

            desired = "normal" if production else "editable"
            if skip_reinstall:
                current = _determine_install_status(entry, verbose)
                if current == desired:
                    pkg_name = pkg_name_for_entry
                    source_version = _project_version_from_source(entry, verbose)
                    installed_version = _installed_pkg_version(pkg_name, verbose)
                    if pkg_name == "vdedup" and not _vdedup_gpu_requirements_installed():
                        log_info(f"{name}: GPU requirements missing or CPU-only torch → reinstalling.")
                    elif source_version and installed_version and source_version != installed_version:
                        log_info(
                            f"{name}: installed version {installed_version}, source version {source_version} "
                            "→ reinstalling."
                        )
                    elif pkg_name == "web-docs-processor":
                        runtime_rc = _ensure_web_docs_processor_runtime(
                            entry,
                            logs_dir,
                            editable=not production,
                            verbose=verbose,
                        )
                        if runtime_rc == 0:
                            status_line(f"{name}: already ({current})", "unchanged", "runtime ready")
                            touched_pkgs.append(pkg_name)
                            continue
                        status_line(
                            f"{name}: runtime setup failed",
                            "fail",
                            f"log: {logs_dir / 'web_docs_processor-browser-install.log'}",
                        )
                        errors_encountered.append(name)
                        continue
                    else:
                        status_line(f"{name}: already ({current})", "unchanged", "skip")
                        # even if we skip, track package name so proxies can be refreshed
                        touched_pkgs.append(pkg_name)
                        continue
                elif current:
                    log_info(f"{name}: installed as '{current}', but '{desired}' requested → reinstalling.")
                else:
                    log_info(f"{name}: not installed or unknown status → installing.")

            # 1) requirements (optional) - skip if pyproject.toml exists (dependencies declared there)
            if req_file.exists() and not has_pyproject:
                reqs = _parse_requirements(req_file)
                if reqs:
                    num_fail, results = _install_requirements(name, entry, reqs, logs_dir, verbose)
                    if num_fail == 0:
                        status_line(f"{name}: requirements {len(reqs)}/{len(reqs)} installed", "ok")
                    else:
                        status_line(f"{name}: requirements installed with {num_fail} failure(s)", "warn", f"log: {logs_dir / (name + '-pip.log')}")
                        failed_reqs = [r for r, ok, _rc in results if not ok]
                        _print_dependency_failure_group(name, failed_reqs, "requirements.txt entries that failed:")
                else:
                    status_line(f"{name}: requirements.txt empty — skipped", "unchanged")
            elif req_file.exists() and has_pyproject:
                status_line(f"{name}: has pyproject.toml (dependencies declared there) — skipping requirements.txt", "unchanged")
            elif not req_file.exists() and not has_pyproject:
                status_line(f"{name}: no requirements.txt — skipped", "unchanged")

            # 2) module install (one line per module in non-verbose)
            if pkg_name_for_entry == "vdedup":
                gpu_rc = _install_vdedup_gpu_requirements(entry, logs_dir, verbose)
                if gpu_rc != 0:
                    status_line(
                        f"{name}: GPU requirements install failed",
                        "fail",
                        f"log: {logs_dir / 'vdedup-gpu-requirements-pip.log'}",
                    )
                    errors_encountered.append(name)
                    continue

            mode = "editable" if not production else "normal"
            print(f"[•] {name}: pip installing ({mode})" if not _ASCII_UI else f"[-] {name}: pip installing ({mode})")
            rc = _install_module(name, entry, editable=not production, logs_dir=logs_dir, verbose=verbose)
            if rc == 0:
                status_line(f"{name}: installed", "ok", "editable" if not production else "normal")
                touched_pkgs.append(pkg_name_for_entry)
            else:
                pip_log = logs_dir / f"{name}-pip.log"
                status_line(f"{name}: install failed", "fail", f"log: {pip_log}")
                locked_diagnostic = _locked_console_script_diagnostic(pip_log)
                if locked_diagnostic:
                    locked_failed_pkgs.add(pkg_name_for_entry)
                    _print_dependency_failure_group(name, locked_diagnostic, "locked executable diagnostic:")
                failed_deps = _extract_failed_dependency_names(pip_log)
                if failed_deps:
                    _print_dependency_failure_group(name, failed_deps, "pip-reported failed dependency/install items:")
                elif has_pyproject:
                    dependency_candidates = _project_dependencies_from_source(entry)
                    if dependency_candidates:
                        _print_dependency_failure_group(
                            name,
                            dependency_candidates,
                            "declared pyproject dependencies; see pip log for the exact failure:",
                        )
                errors_encountered.append(name)

    if hidden_skipped:
        print("\nHidden modules not processed:")
        for h in hidden_skipped:
            print(f"  - {h} (dot-prefixed; ignored)")
    return errors_encountered, touched_pkgs

# ─────────────────────────────────────────────────────────
# Editable-finder priority patch
# ─────────────────────────────────────────────────────────
def patch_editable_finders(verbose: bool = False) -> None:
    """Rewrite all __editable__*_finder.py files so the finder inserts at
    position 0 in sys.meta_path instead of appending.

    Without this, PathFinder finds a module's wrapper directory (e.g.
    modules/filter_prune/) as a namespace package when 'modules/' is on
    PYTHONPATH, and the editable finder never gets a chance to map it to the
    real inner package (modules/filter_prune/filter_prune/).
    """
    try:
        import site as _site
        site_pkgs = [Path(p) for p in _site.getsitepackages() if Path(p).is_dir()]
        user_site = Path(_site.getusersitepackages()) if hasattr(_site, "getusersitepackages") else None
        if user_site and user_site.is_dir():
            site_pkgs.append(user_site)
    except Exception:
        site_pkgs = []

    patched = 0
    for sp in site_pkgs:
        for finder_file in sp.glob("__editable__*_finder.py"):
            try:
                text = finder_file.read_text(encoding="utf-8")
                if "sys.meta_path.append(_EditableFinder)" in text:
                    new_text = text.replace(
                        "sys.meta_path.append(_EditableFinder)",
                        "sys.meta_path.insert(0, _EditableFinder)",
                    )
                    finder_file.write_text(new_text, encoding="utf-8")
                    patched += 1
                    if verbose:
                        log_info(f"Patched editable finder: {finder_file.name}")
            except Exception as exc:
                log_warning(f"Could not patch {finder_file.name}: {exc}")

    if patched:
        status_line(f"Patched {patched} editable finder(s) for meta_path priority", "ok")
    elif verbose:
        log_info("All editable finders already use insert(0, ...) or none found")


# ─────────────────────────────────────────────────────────
# PYTHONPATH configuration
# ─────────────────────────────────────────────────────────
def ensure_pythonpath(modules_dir: Path, dotfiles_dir: Path, verbose: bool = False):
    modules_dir_abs = str(modules_dir.resolve())
    path_separator = os.pathsep

    with section("PYTHONPATH Configuration"):
        if os.name == "nt":
            with section("Windows PYTHONPATH Update"):
                log_info("Windows OS detected for PYTHONPATH setup.")
                try:
                    completed_process = subprocess.run(
                        ['reg', 'query', r'HKCU\Environment', '/v', 'PYTHONPATH'],
                        capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore'
                    )
                    current_user_pythonpath = ""
                    if completed_process.returncode == 0 and completed_process.stdout:
                        regex_pattern = r"^\s*PYTHONPATH\s+REG_(?:EXPAND_)?SZ\s+(.*)$"
                        for line in completed_process.stdout.splitlines():
                            match = re.search(regex_pattern, line.strip(), re.IGNORECASE)
                            if match:
                                current_user_pythonpath = match.group(1).strip()
                                break

                    if verbose:
                        log_info(f"Current User PYTHONPATH from registry: '{current_user_pythonpath}'")

                    current_paths_list = list(dict.fromkeys([p for p in current_user_pythonpath.split(path_separator) if p]))

                    if modules_dir_abs in current_paths_list:
                        log_success(f"{modules_dir_abs} is already in the User PYTHONPATH.")
                    else:
                        log_info(f"Adding {modules_dir_abs} to User PYTHONPATH.")
                        new_pythonpath_list = current_paths_list + [modules_dir_abs]
                        new_pythonpath_value = path_separator.join(list(dict.fromkeys(new_pythonpath_list)))

                        # Prefer PowerShell if available
                        pwsh = subprocess.run(["where", "pwsh"], capture_output=True, shell=True)
                        pwshell = subprocess.run(["where", "powershell"], capture_output=True, shell=True)
                        have_ps = bool(pwsh.stdout or pwshell.stdout)
                        if have_ps:
                            if verbose:
                                log_info("Using PowerShell to update User PYTHONPATH.")
                            ps_cmd = " ".join(
                                [
                                    '$envName = "User";',
                                    '$varName = "PYTHONPATH";',
                                    f'$valueToAdd = "{modules_dir_abs}";',
                                    "$currentValue = [System.Environment]::GetEnvironmentVariable($varName, $envName);",
                                    "$elements = @($currentValue -split [System.IO.Path]::PathSeparator | Where-Object { $_ -ne \"\" });",
                                    "if ($elements -notcontains $valueToAdd) {",
                                    "  $newElements = $elements + $valueToAdd;",
                                    "  $newValue = $newElements -join [System.IO.Path]::PathSeparator;",
                                    "  [System.Environment]::SetEnvironmentVariable($varName, $newValue, $envName);",
                                    '  Write-Host "Successfully updated User PYTHONPATH via PowerShell.";',
                                    "} else { Write-Host ($valueToAdd + \" already in User PYTHONPATH (PowerShell check).\" ); }",
                                ]
                            )
                            pwsh_exe = "pwsh" if pwsh.stdout else "powershell"
                            ps_proc = subprocess.run(
                                [pwsh_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                                check=True, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                            )
                            if verbose and ps_proc.stdout.strip():
                                log_info(f"PowerShell output: {ps_proc.stdout.strip()}")
                            if verbose and ps_proc.stderr.strip():
                                log_warning(f"PowerShell stderr: {ps_proc.stderr.strip()}")
                        else:
                            if verbose:
                                log_info("PowerShell not found, attempting 'setx' for PYTHONPATH.")
                            subprocess.run(['setx', 'PYTHONPATH', new_pythonpath_value], check=True)
                            log_success("Requested update for User PYTHONPATH using 'setx'.")
                        log_warning("PYTHONPATH change will apply to new terminal sessions or after a restart/re-login.")
                except Exception as e:
                    log_error(f"Failed to update User PYTHONPATH: {type(e).__name__}: {e}")
                    log_info(f"Please add '{modules_dir_abs}' to your User PYTHONPATH environment variable manually.")
        else:
            with section("Zsh PYTHONPATH Update"):
                pythonpath_config_file = dotfiles_dir / "dynamic/setup_modules_pythonpath.zsh"
                pythonpath_config_file.parent.mkdir(parents=True, exist_ok=True)
                export_line = f'export PYTHONPATH="{modules_dir_abs}{path_separator}${{PYTHONPATH}}"\n'

                current_config_content = ""
                if pythonpath_config_file.exists():
                    try:
                        current_config_content = pythonpath_config_file.read_text(encoding="utf-8")
                    except Exception as e_read:
                        log_warning(f"Could not read {pythonpath_config_file}: {e_read}")

                is_already_configured = False
                for line_in_file in current_config_content.splitlines():
                    if line_in_file.strip().startswith(f'export PYTHONPATH="{modules_dir_abs}') or \
                       f'{path_separator}{modules_dir_abs}{path_separator}' in line_in_file or \
                       line_in_file.strip().endswith(f'{path_separator}{modules_dir_abs}"'):
                        is_already_configured = True
                        break

                if is_already_configured and f'export PYTHONPATH="{modules_dir_abs}{path_separator}${{PYTHONPATH}}"' in current_config_content :
                    log_success(f"PYTHONPATH configuration for '{modules_dir_abs}' already correctly exists in {pythonpath_config_file}")
                else:
                    try:
                        with open(pythonpath_config_file, "w", encoding="utf-8") as f:
                            f.write("# Added/Updated by modules/setup.py to include project modules\n")
                            f.write("# This file is (re)generated to ensure correctness.\n")
                            f.write(export_line)
                        log_success(f"PYTHONPATH configuration (re)generated in {pythonpath_config_file}")

                        try:
                            source_cmd = f"source '{pythonpath_config_file.resolve()}' && echo $PYTHONPATH"
                            if _is_verbose:
                                log_info(f"Attempting to have Zsh sub-shell source: {source_cmd}")
                            result = subprocess.run(
                                ["zsh", "-c", source_cmd], timeout=5,
                                check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore'
                            )
                            if _is_verbose and result.stdout.strip():
                                log_success(f"Sourced {pythonpath_config_file} in a zsh sub-shell. New PYTHONPATH (in sub-shell): {result.stdout.strip()}")
                            if _is_verbose and result.stderr.strip():
                                log_warning(f"Zsh source stderr: {result.stderr.strip()}")
                        except FileNotFoundError:
                            log_warning("zsh not found. Cannot source the Zsh config file automatically.")
                        except subprocess.TimeoutExpired:
                            log_warning(f"Zsh sourcing timed out for {pythonpath_config_file}.")
                        except subprocess.CalledProcessError as e_source:
                            log_error(f"Failed to source {pythonpath_config_file} in a zsh sub-shell.")
                            zsh_err = e_source.stderr.strip() if e_source.stderr else (e_source.stdout.strip() if e_source.stdout else "No output.")
                            log_error(f"Zsh error: {zsh_err}")

                    except IOError as e:
                        log_error(f"Could not write PYTHONPATH configuration to {pythonpath_config_file}: {e}")
                        log_info(f"Please add the following line to your Zsh startup file manually:\n{export_line.strip()}")

# ─────────────────────────────────────────────────────────
# Console-script proxy generation (for run-anywhere behavior)
# ─────────────────────────────────────────────────────────
def _write_text_if_changed(path: Path, content: str, verbose: bool, crlf: bool = False) -> bool:
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                if verbose:
                    print(f"[INFO] No change for {path.name}")
                return False
        except Exception:
            pass
    newline = "\r\n" if crlf else "\n"
    path.write_text(content, encoding="utf-8", newline=newline)
    if verbose:
        print(f"[SUCCESS] Wrote {path}")
    return True

def generate_console_proxies(installed_pkg_names: list[str]) -> None:
    """
    Create/refresh tiny shims in <scripts>/bin that delegate to this repo's venv entry points.
    Generates proxies for all console scripts from packages in the modules directory,
    not just the ones we touched in this run.
    """
    try:
        from importlib import metadata
    except Exception:
        log_warning("Could not import importlib.metadata; skipping console proxy generation.")
        return

    scripts_dir = Path(__file__).resolve().parents[1]
    bin_dir = scripts_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # If no packages were explicitly provided, generate for all installed packages
    # Otherwise, use the provided list
    if not installed_pkg_names:
        desired = None  # None means "all packages"
    else:
        desired = set(n.strip().lower() for n in installed_pkg_names if n.strip())

    console_map: dict[str, str] = {}

    for dist in metadata.distributions():
        dist_name = (dist.metadata.get("Name") or "").lower()
        if not dist_name:
            continue
        # If desired is None, include all; otherwise only include if in desired set
        if desired is not None and dist_name not in desired:
            continue
        for ep in dist.entry_points or []:
            if ep.group == "console_scripts" and ep.name:
                console_map[ep.name] = dist_name

    if not console_map:
        status_line("No console_scripts discovered for installed packages", "unchanged")
        return

    created = 0
    unchanged = 0
    for script_name in sorted(console_map.keys()):
        if os.name == "nt":
            wrapper = bin_dir / f"{script_name}.cmd"
            content = (
                "@echo off\r\n"
                "setlocal\r\n"
                "set \"_B=%~dp0\"\r\n"
                "set \"_V=%_B%..\\.venv\\Scripts\"\r\n"
                f"set \"_T=%_V%\\{script_name}.exe\"\r\n"
                "if exist \"%_T%\" (\r\n"
                "  \"%_T%\" %*\r\n"
                "  exit /b %ERRORLEVEL%\r\n"
                ")\r\n"
                f"echo [WARN] {script_name} not found in repo venv. Falling back to PATH.\r\n"
                f"{script_name} %*\r\n"
            )
            changed = _write_text_if_changed(wrapper, content=content, verbose=_is_verbose, crlf=True)
            if changed:
                created += 1
            else:
                unchanged += 1
        else:
            wrapper = bin_dir / script_name
            content = f"""#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")" && pwd)"
T="$DIR/../.venv/bin/{script_name}"
if [ -x "$T" ]; then exec "$T" "$@"; fi
echo "[WARN] {script_name} not found in repo venv. Falling back to PATH." 1>&2
exec "{script_name}" "$@"
"""
            changed = _write_text_if_changed(wrapper, content=content, verbose=_is_verbose, crlf=False)
            try:
                wrapper.chmod(0o755)
            except Exception:
                pass
            if changed:
                created += 1
            else:
                unchanged += 1

    status_line(f"Console proxies: {created} created/updated, {unchanged} unchanged", "ok")

# ─────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Setup Python modules from the 'modules' directory and configure PYTHONPATH.")
    parser.add_argument("-R", "--scripts-dir", type=Path, required=True, help="Base project scripts directory.")
    parser.add_argument("-D", "--dotfiles-dir", type=Path, required=True, help="Root directory of dotfiles.")
    parser.add_argument("-B", "--bin-dir", type=Path, required=True, help="Target directory for binaries.")
    parser.add_argument(
        "-s", "--skip-reinstall",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip reinstall when already correct.",
    )
    parser.add_argument("-p", "--production", action="store_true", help="Install modules in production (non-editable).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed output.")
    parser.add_argument("-a", "--include-hidden", action="store_true", help="Include dot-prefixed (hidden) module folders.")
    args = parser.parse_args()

    global _is_verbose
    _is_verbose = args.verbose

    logs_dir = args.scripts_dir / "setup_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    all_errors, touched_pkgs = install_python_modules(
        args.scripts_dir / "modules", logs_dir,
        skip_reinstall=args.skip_reinstall,
        production=args.production,
        verbose=args.verbose,
        include_hidden=args.include_hidden,
    )

    # Always refresh console proxies for all packages (pass empty list to mean "all")
    try:
        generate_console_proxies([])
    except Exception as e:
        log_warning(f"Console proxy generation encountered an issue: {e}")

    ensure_pythonpath(args.scripts_dir / "modules", args.dotfiles_dir, args.verbose)
    patch_editable_finders(verbose=args.verbose)

    if all_errors:
        log_warning(f"Completed with {len(all_errors)} error(s) in module installation.")
        for mod in all_errors:
            print(f"FAILED_MODULE: {mod}")
        sys.exit(1)
    else:
        print("[OK] modules/setup.py completed.")

if __name__ == "__main__":
    main()
