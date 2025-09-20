#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import subprocess
from pathlib import Path
import re
import time

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
_IS_VERBOSE = ("--verbose" in sys.argv) or ("-v" in sys.argv)

def _needs_ascii_ui() -> bool:
    if os.environ.get("FORCE_ASCII_UI") == "1":
        return True
    enc = (getattr(sys.stdout, "encoding", "") or "").upper()
    return os.name == "nt" and "UTF-8" not in enc

_ASCII_UI = _needs_ascii_ui()

def _fb_info(msg):
    if _IS_VERBOSE: print(f"[INFO] {msg}")
def _fb_success(msg): print(f"[SUCCESS] {msg}")
def _fb_warn(msg): print(f"[WARNING] {msg}")
def _fb_err(msg): print(f"[ERROR] {msg}")

class _FBSection:
    def __init__(self, title): self.title, self._t = title, None
    def __enter__(self):
        self._t = time.time()
        print(f"\n──────── {self.title} ────────")
        return self
    def __exit__(self, *_):
        if _IS_VERBOSE:
            print(f"──────── elapsed {time.time() - self._t:.2f}s ────────")

def _fb_status(label: str, state: str | None = None, detail: str | None = None):
    prefix = {"unchanged": "-", "ok": "OK", "warn": "!", "fail": "X"} if _ASCII_UI else \
             {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}
    tail = (f" - {detail}" if _ASCII_UI else f" — {detail}") if detail else ""
    print(f"[{prefix.get(state or '', prefix['unchanged'])}] {label}{tail}")

log_info, log_success, log_warning, log_error, section = _fb_info, _fb_success, _fb_warn, _fb_err, _FBSection
_status_impl = _fb_status

try:
    if not _ASCII_UI:
        from standard_ui.standard_ui import (
            log_info as _s_info, log_success as _s_ok, log_warning as _s_warn,
            log_error as _s_err, section as _s_section, status_line as _s_status
        )
        log_info, log_success, log_warning, log_error, section = _s_info, _s_ok, _s_warn, _s_err, _s_section
        _status_impl = _s_status
    else:
        if _IS_VERBOSE: print("[WARNING] Non-UTF-8 console detected; using ASCII UI.")
except Exception:
    if _IS_VERBOSE: print("[WARNING] standard_ui not available in modules/setup.py; using fallback logging.")

def status_line(label: str, state: str | None = None, detail: str | None = None):
    impl = _status_impl
    if impl is _fb_status: return impl(label, state, detail)
    try:
        return impl(label, state, detail)
    except TypeError:
        pass
    try:
        return impl(label, state)
    except TypeError:
        pass
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
                lf.write(line.encode("utf-8","ignore"))
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
                    sys.stdout.write("."); sys.stdout.flush()
                    next_tick = time.time() + heartbeat_every
                time.sleep(0.25)

# ─────────────────────────────────────────────────────────
# Requirements handling
# ─────────────────────────────────────────────────────────
def _parse_requirements(req_file: Path) -> list[str]:
    reqs: list[str] = []
    try:
        for raw in req_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"): continue
            if " #" in line: line = line.split(" #", 1)[0].strip()
            reqs.append(line)
    except Exception:
        pass
    return reqs

def _install_requirements(module_name: str, module_dir: Path, reqs: list[str], logs_dir: Path, verbose: bool):
    results = []
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
        sys.stdout.write(f"\r{module_name}: {i}/{total} …"); sys.stdout.flush()
        cmd = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", req]
        if not verbose: cmd.insert(4, "-q")
        rc = _run_with_log(cmd, log_file, verbose=verbose)
        ok = (rc == 0)
        results.append((req, ok, rc))
        if not ok: num_fail += 1
    sys.stdout.write("\n"); sys.stdout.flush()
    return num_fail, results

def _install_module(module_name: str, module_dir: Path, *, editable: bool, logs_dir: Path, verbose: bool) -> int:
    log_file = logs_dir / f"{module_name}-pip.log"
    cmd = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check"]
    if not verbose: cmd.insert(4, "-q")
    if editable: cmd.append("-e")
    cmd.append(str(module_dir.resolve()))
    return _run_with_log(cmd, log_file, verbose=verbose)

# ─────────────────────────────────────────────────────────
# Console-script proxy generation (run-anywhere behavior)
# ─────────────────────────────────────────────────────────
def _write_text_if_changed(path: Path, content: str, verbose: bool, crlf: bool = False) -> bool:
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == content:
                if verbose: log_info(f"No change for {path.name}")
                return False
        except Exception:
            pass
    path.write_text(content, encoding="utf-8", newline="\r\n" if crlf else "\n")
    if verbose: log_success(f"Wrote {path}")
    return True

def generate_console_proxies(installed_pkg_names: list[str]) -> None:
    """
    Create/refresh tiny shims in ~/scripts/bin that delegate to the repo venv entry-points.
    Only proxies console scripts for distributions we just installed/checked.
    """
    try:
        from importlib import metadata
    except Exception:
        log_warning("importlib.metadata not available; skipping console proxy generation.")
        return

    scripts_dir = Path(__file__).resolve().parents[1]
    bin_dir = scripts_dir / "bin"
    venv_dir = scripts_dir / ".venv"
    vbin = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir(parents=True, exist_ok=True)

    desired = set(n.strip().lower() for n in installed_pkg_names if n.strip())
    console_map = {}  # script_name -> dist_name

    for dist in metadata.distributions():
        dname = (getattr(dist, "metadata", {}) or {}).get("Name") if hasattr(dist, "metadata") else None
        if not dname:
            try:
                dname = dist.metadata["Name"]
            except Exception:
                dname = ""
        dname = (dname or "").lower()
        if dname not in desired:
            continue
        for ep in getattr(dist, "entry_points", []) or []:
            if getattr(ep, "group", "") == "console_scripts" and getattr(ep, "name", ""):
                console_map[ep.name] = dname

    if not console_map:
        status_line("No console_scripts discovered for installed packages", "unchanged")
        return

    created = 0; unchanged = 0
    for script_name in sorted(console_map):
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
            changed = _write_text_if_changed(wrapper, content, verbose=_IS_VERBOSE, crlf=True)
            created += int(changed); unchanged += int(not changed)
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
            changed = _write_text_if_changed(wrapper, content, verbose=_IS_VERBOSE, crlf=False)
            try: wrapper.chmod(0o755)
            except Exception: pass
            created += int(changed); unchanged += int(not changed)

    status_line(f"Console proxies: {created} created/updated, {unchanged} unchanged", "ok")

# ─────────────────────────────────────────────────────────
# Scan + install modules
# ─────────────────────────────────────────────────────────
def install_python_modules(modules_dir: Path, logs_dir: Path, *, skip_reinstall: bool, production: bool, verbose: bool, include_hidden: bool, ignore_requirements: bool) -> list[str]:
    errors = []
    hidden_skipped = []
    installed_pkg_names = []

    if not modules_dir.exists() or not modules_dir.is_dir():
        status_line(f"{modules_dir}: not found — skipped", "warn")
        return errors

    with section("Python Modules Installation"):
        entries = sorted(modules_dir.iterdir(), key=lambda p: p.name.lower())
        print(f"[•] Found {len(entries)} module(s) to process")
        for entry in entries:
            name = entry.name
            if entry.resolve() == Path(__file__).resolve().parent:
                status_line(f"{name}: internal setup folder — skipped", "unchanged"); continue
            if not entry.is_dir():
                status_line(f"{name}: not a directory — skipped", "unchanged"); continue
            if name.startswith(".") and not include_hidden:
                status_line(f"{name}: ignored (hidden)", "unchanged"); hidden_skipped.append(name); continue

            has_setup_py = (entry / "setup.py").exists()
            has_pyproject = (entry / "pyproject.toml").exists()
            req_file = entry / "requirements.txt"
            if not has_setup_py and not has_pyproject:
                status_line(f"{name}: no installer (no setup.py/pyproject.toml) — skipped", "unchanged"); continue
            if not has_pyproject:
                log_warning(f"{name}: pyproject.toml not found — continuing (modern metadata recommended).")

            desired = "normal" if production else "editable"
            if skip_reinstall:
                current = _determine_install_status(entry, verbose)
                if current == desired:
                    status_line(f"{name}: already ({current})", "unchanged", "skip")
                    installed_pkg_names.append(_pkg_name_from_source(entry, verbose))
                    continue
                elif current:
                    log_info(f"{name}: installed as '{current}', but '{desired}' requested → reinstalling.")
                else:
                    log_info(f"{name}: not installed or unknown status → installing.")

            # requirements
            if not ignore_requirements and req_file.exists():
                reqs = _parse_requirements(req_file)
                if reqs:
                    num_fail, results = _install_requirements(name, entry, reqs, logs_dir, verbose)
                    if num_fail == 0:
                        status_line(f"{name}: requirements {len(reqs)}/{len(reqs)} installed", "ok")
                    else:
                        status_line(f"{name}: requirements installed with {num_fail} failure(s)", "warn", f"log: {logs_dir / (name + '-pip.log')}")
                        for r, ok, _ in results:
                            print(("✅ " if ok else "❌ ") + r)
                else:
                    status_line(f"{name}: requirements.txt empty — skipped", "unchanged")
            elif ignore_requirements:
                status_line(f"{name}: requirements skipped by flag", "unchanged")
            else:
                status_line(f"{name}: no requirements.txt — skipped", "unchanged")

            # install
            mode = "editable" if not production else "normal"
            print(f"[•] {name}: pip installing ({mode})")
            rc = _install_module(name, entry, editable=not production, logs_dir=logs_dir, verbose=verbose)
            if rc == 0:
                status_line(f"{name}: installed", "ok", "editable" if not production else "normal")
                installed_pkg_names.append(_pkg_name_from_source(entry, verbose))
            else:
                status_line(f"{name}: install failed", "fail", f"log: {logs_dir / (name + '-pip.log')}")
                errors.append(name)

    if hidden_skipped:
        print("\nHidden modules not processed:")
        for h in hidden_skipped: print(f"  - {h} (dot-prefixed; ignored)")

    # ensure console proxies exist for the dists we just touched
    try:
        generate_console_proxies(installed_pkg_names)
    except Exception as e:
        log_warning(f"Console proxy generation encountered an issue: {e}")

    return errors

# ─────────────────────────────────────────────────────────
# PYTHONPATH configuration
# ─────────────────────────────────────────────────────────
def ensure_pythonpath(modules_dir: Path, dotfiles_dir: Path, verbose: bool = False):
    modules_dir_abs = str(modules_dir.resolve())
    pathsep = os.pathsep

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
                        regex = r"^\s*PYTHONPATH\s+REG_(?:EXPAND_)?SZ\s+(.*)$"
                        for line in completed_process.stdout.splitlines():
                            m = re.search(regex, line.strip(), re.IGNORECASE)
                            if m: current_user_pythonpath = m.group(1).strip(); break

                    if verbose: log_info(f"User PYTHONPATH from registry: '{current_user_pythonpath}'")
                    parts = list(dict.fromkeys([p for p in current_user_pythonpath.split(pathsep) if p]))
                    if modules_dir_abs in parts:
                        log_success(f"{modules_dir_abs} already in User PYTHONPATH.")
                    else:
                        newval = pathsep.join(parts + [modules_dir_abs])
                        # Prefer PowerShell if available
                        have_pwsh = bool(subprocess.run(["where", "pwsh"], capture_output=True, shell=True).stdout or
                                         subprocess.run(["where", "powershell"], capture_output=True, shell=True).stdout)
                        if have_pwsh:
                            pwsh_exe = "pwsh" if subprocess.run(["where","pwsh"], capture_output=True, shell=True).stdout else "powershell"
                            ps_cmd = " ".join([
                                '$envName = "User";',
                                '$varName = "PYTHONPATH";',
                                f'$valueToAdd = "{modules_dir_abs}";',
                                "$cv = [System.Environment]::GetEnvironmentVariable($varName,$envName);",
                                "$els = @($cv -split [System.IO.Path]::PathSeparator | ? { $_ -ne \"\" });",
                                "if ($els -notcontains $valueToAdd) {",
                                "  $new = ($els + $valueToAdd) -join [System.IO.Path]::PathSeparator;",
                                "  [System.Environment]::SetEnvironmentVariable($varName,$new,$envName);",
                                '  Write-Host "Updated PYTHONPATH";',
                                "} else { Write-Host 'Already present' }",
                            ])
                            subprocess.run([pwsh_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], check=True)
                            log_success("Requested User PYTHONPATH update via PowerShell.")
                        else:
                            subprocess.run(['setx', 'PYTHONPATH', newval], check=True)
                            log_success("Requested User PYTHONPATH update via setx.")
                        log_warning("PYTHONPATH change applies to NEW terminals.")
                except Exception as e:
                    log_error(f"Failed to update User PYTHONPATH: {type(e).__name__}: {e}")
        else:
            with section("Zsh PYTHONPATH Update"):
                cfg = dotfiles_dir / "dynamic/setup_modules_pythonpath.zsh"
                cfg.parent.mkdir(parents=True, exist_ok=True)
                export_line = f'export PYTHONPATH="{modules_dir_abs}{pathsep}${{PYTHONPATH}}"\n'
                content = ""
                if cfg.exists():
                    try: content = cfg.read_text(encoding="utf-8")
                    except Exception as e: log_warning(f"Could not read {cfg}: {e}")
                if export_line in content:
                    log_success(f"PYTHONPATH already configured in {cfg}")
                else:
                    cfg.write_text("# Generated by modules/setup.py\n" + export_line, encoding="utf-8")
                    log_success(f"Wrote {cfg}")
                    try:
                        subprocess.run(["zsh","-c", f"source '{cfg}' && echo $PYTHONPATH"], capture_output=True, text=True, check=True)
                    except Exception:
                        pass

# ─────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Install ~/scripts/modules packages and environment wiring.")
    ap.add_argument("-R","--scripts-dir", type=Path, required=True)
    ap.add_argument("-D","--dotfiles-dir", type=Path, required=True)
    ap.add_argument("-B","--bin-dir", type=Path, required=True)
    ap.add_argument("-s","--skip-reinstall", action="store_true")
    ap.add_argument("-p","--production", action="store_true")
    ap.add_argument("-v","--verbose", action="store_true")
    ap.add_argument("-a","--include-hidden", action="store_true")
    ap.add_argument("-I","--ignore-requirements", action="store_true")
    args = ap.parse_args()

    global _IS_VERBOSE
    _IS_VERBOSE = args.verbose or _IS_VERBOSE

    logs_dir = args.scripts_dir / "setup_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    errors = install_python_modules(
        args.scripts_dir / "modules", logs_dir,
        skip_reinstall=args.skip_reinstall,
        production=args.production,
        verbose=args.verbose,
        include_hidden=args.include_hidden,
        ignore_requirements=args.ignore_requirements,
    )

    ensure_pythonpath(args.scripts_dir / "modules", args.dotfiles_dir, args.verbose)

    if errors:
        log_warning(f"Completed with {len(errors)} error(s) in module installation.")
        for mod in errors: print(f"FAILED_MODULE: {mod}")
        sys.exit(1)
    print("[OK] modules/setup.py completed.")

if __name__ == "__main__":
    main()

