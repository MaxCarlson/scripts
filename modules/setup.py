#!/usr/bin/env python3
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
# standard_ui fallbacks + wrappers
# ─────────────────────────────────────────────────────────
_is_verbose = ("--verbose" in sys.argv) or ("-v" in sys.argv)

def _fb_info(msg):
    if _is_verbose:
        print(f"[INFO] {msg}")
def _fb_success(msg): print(f"[SUCCESS] {msg}")
def _fb_warn(msg):    print(f"[WARNING] {msg}")
def _fb_err(msg):     print(f"[ERROR] {msg}")

class _FBSection:
    def __init__(self, title): self.title = title; self._t = None
    def __enter__(self):
        self._t = time.time()
        if _is_verbose: print(f"\n──────── {self.title} - START ────────")
        return self
    def __exit__(self, *_):
        if _is_verbose:
            print(f"──────── {self.title} - END (Elapsed: {time.time()-self._t:.2f}s) ────────")

def _fb_status(label: str, state: str | None = None, detail: str | None = None):
    prefix = {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}.get(state or "", "•")
    tail = f" — {detail}" if detail else ""
    print(f"[{prefix}] {label}{tail}")

log_info, log_success, log_warning, log_error, section = _fb_info, _fb_success, _fb_warn, _fb_err, _FBSection
_status_impl = _fb_status

try:
    from standard_ui.standard_ui import (
        log_info as _s_log_info,
        log_success as _s_log_success,
        log_warning as _s_log_warning,
        log_error as _s_log_error,
        section as _s_section,
        status_line as _s_status_line
    )
    log_info, log_success, log_warning, log_error, section = (
        _s_log_info, _s_log_success, _s_log_warning, _s_log_error, _s_section
    )
    _status_impl = _s_status_line
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
    # 1-arg fallback
    prefix = {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}.get(state or "", "•")
    tail = f" — {detail}" if detail else ""
    try:
        return impl(f"[{prefix}] {label}{tail}")
    except TypeError:
        return _fb_status(label, state, detail)

# ─────────────────────────────────────────────────────────
# Global log (shared with parent) — optional but used if provided
# ─────────────────────────────────────────────────────────
GLOBAL_LOG = Path(os.environ.get("SETUP_LOG_PATH", "")).resolve() if os.environ.get("SETUP_LOG_PATH") else None

def _glog(line: str):
    if not GLOBAL_LOG:
        return
    try:
        GLOBAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(GLOBAL_LOG, "a", encoding="utf-8") as f:
            f.write(line)
            if not line.endswith("\n"):
                f.write("\n")
    except Exception:
        pass

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
# Runner with tee into module log + global log
# ─────────────────────────────────────────────────────────
def _run_with_log(cmd: list[str], log_path: Path, *, verbose: bool) -> int:
    """
    If verbose=True: stream combined output to console and logs.
    Else: keep console quiet (single-line per module), but tee all output to logs.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _glog(f"$ {' '.join(cmd)}")

    if verbose:
        with open(log_path, "ab") as lf:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="ignore"
            )
            try:
                for line in iter(proc.stdout.readline, ""):
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    lf.write(line.encode("utf-8", "ignore"))
                    _glog(line.rstrip("\n"))
            finally:
                if proc.stdout:
                    proc.stdout.close()
            return proc.wait()
    else:
        # quiet console, tee to logs
        with open(log_path, "ab") as lf:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="ignore"
            )
            try:
                for line in iter(proc.stdout.readline, ""):
                    lf.write(line.encode("utf-8", "ignore"))
                    _glog(line.rstrip("\n"))
            finally:
                if proc.stdout:
                    proc.stdout.close()
            return proc.wait()

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

def _install_requirements(module_name: str, module_dir: Path, reqs: list[str], logs_dir: Path, verbose: bool) -> tuple[int, list[tuple[str, bool, int]]]:
    """
    Installs each requirement separately so we can show partial failures.
    In non-verbose mode, we keep console silent; all details go to logs.
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
    for req in reqs:
        cmd = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", req]
        if not verbose:
            cmd.insert(4, "-q")
        rc = _run_with_log(cmd, log_file, verbose=verbose)
        ok = (rc == 0)
        results.append((req, ok, rc))
        if not ok:
            num_fail += 1

    return num_fail, results

# ─────────────────────────────────────────────────────────
# Install a module (editable/non-editable), quiet with log
# ─────────────────────────────────────────────────────────
def _install_module(module_name: str, module_dir: Path, *, editable: bool, logs_dir: Path, verbose: bool, no_deps: bool = False) -> int:
    log_file = logs_dir / f"{module_name}-pip.log"
    cmd = [sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check"]
    if not verbose:
        cmd.insert(4, "-q")
    if no_deps:
        cmd.append("--no-deps")
    if editable:
        cmd.append("-e")
    cmd.append(str(module_dir.resolve()))
    return _run_with_log(cmd, log_file, verbose=verbose)

# ─────────────────────────────────────────────────────────
# Scan + install modules (one line per module in non-verbose)
# ─────────────────────────────────────────────────────────
def install_python_modules(modules_dir: Path, logs_dir: Path, *, skip_reinstall: bool, production: bool, verbose: bool, include_hidden: bool, ignore_requirements: bool) -> list[str]:
    errors_encountered: list[str] = []
    hidden_skipped: list[str] = []

    if not modules_dir.exists() or not modules_dir.is_dir():
        status_line(f"{modules_dir}: not found — skipped", "warn")
        return errors_encountered

    log_info(f"Scanning modules in: {modules_dir}")

    # Build the candidate list first so we can at least show we made progress
    entries = []
    for entry in sorted(modules_dir.iterdir(), key=lambda p: p.name.lower()):
        name = entry.name

        # Skip our own folder if this script lives under modules/
        if entry.resolve() == Path(__file__).resolve().parent:
            continue
        if not entry.is_dir():
            continue
        if name.startswith(".") and not include_hidden:
            hidden_skipped.append(name)
            continue
        if not ((entry / "setup.py").exists() or (entry / "pyproject.toml").exists()):
            continue
        entries.append(entry)

    if not verbose:
        status_line(f"Found {len(entries)} module(s) to process", "unchanged")

    for entry in entries:
        name = entry.name

        # Show current install state if skipping reinstalls
        desired = "normal" if production else "editable"
        if skip_reinstall:
            current = _determine_install_status(entry, verbose)
            if current == desired:
                status_line(f"{name}: already ({current})", "unchanged", "skip")
                continue
            elif current:
                log_info(f"{name}: installed as '{current}', but '{desired}' requested → reinstalling.")
            else:
                log_info(f"{name}: not installed or unknown status → installing.")

        # Requirements (only surface failures in non-verbose)
        req_file = entry / "requirements.txt"
        if not ignore_requirements and req_file.exists():
            reqs = _parse_requirements(req_file)
            if reqs:
                num_fail, results = _install_requirements(name, entry, reqs, logs_dir, verbose)
                if verbose:
                    if num_fail == 0:
                        status_line(f"{name}: requirements {len(reqs)}/{len(reqs)} installed", "ok")
                    else:
                        status_line(f"{name}: requirements installed with {num_fail} failure(s)", "warn", f"log: {logs_dir / (name + '-pip.log')}")
                        for r, ok, _rc in results:
                            mark = "✅" if ok else "❌"
                            print(f"  {mark} {r}")
                else:
                    if num_fail > 0:
                        status_line(f"{name}: some requirements failed", "warn", f"log: {logs_dir / (name + '-pip.log')}")
                        for r, ok, _rc in results:
                            if not ok:
                                print(f"  ❌ {r}")
        elif ignore_requirements:
            if verbose:
                status_line(f"{name}: requirements skipped by flag", "unchanged")

        # ONE-LINE NON-VERBOSE PROGRESS PER MODULE
        if not verbose:
            print(f"[•] {name}: pip installing ({'editable' if not production else 'normal'}) …")

        # Module install (editable unless production)
        rc = _install_module(
            name, entry,
            editable=not production,
            logs_dir=logs_dir,
            verbose=verbose,
            no_deps=ignore_requirements,  # --no-deps when -I is used
        )

        if rc == 0:
            status_line(f"{name}: installed", "ok", "editable" if not production else "normal")
        else:
            status_line(f"{name}: install failed", "fail", f"log: {logs_dir / (name + '-pip.log')}")
            errors_encountered.append(name)

    if hidden_skipped:
        print("\nHidden modules not processed:")
        for h in hidden_skipped:
            print(f"  - {h} (dot-prefixed; ignored)")
    return errors_encountered

# ─────────────────────────────────────────────────────────
# PYTHONPATH configuration (same behavior as before)
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

                    if verbose: log_info(f"Current User PYTHONPATH from registry: '{current_user_pythonpath}'")

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
                            if verbose: log_info("Using PowerShell to update User PYTHONPATH.")
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
                            if verbose: log_info("PowerShell not found, attempting 'setx' for PYTHONPATH.")
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

                if is_already_configured and f'export PYTHONPATH="{modules_dir_abs}{path_separator}${{PYTHONPATH}}"' in current_config_content:
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
                            if verbose: log_info(f"Attempting to have Zsh sub-shell source: {source_cmd}")
                            result = subprocess.run(
                                ["zsh", "-c", source_cmd], timeout=5,
                                check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore'
                            )
                            if verbose and result.stdout.strip():
                                log_success(f"Sourced {pythonpath_config_file} in a zsh sub-shell. New PYTHONPATH (in sub-shell): {result.stdout.strip()}")
                            if verbose and result.stderr.strip():
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
# Orchestrator
# ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Setup Python modules from the 'modules' directory and configure PYTHONPATH.")
    parser.add_argument("-R", "--scripts-dir", type=Path, required=True, help="Base project scripts directory.")
    parser.add_argument("-D", "--dotfiles-dir", type=Path, required=True, help="Root directory of dotfiles.")
    parser.add_argument("-B", "--bin-dir", type=Path, required=True, help="Target directory for binaries.")
    parser.add_argument("-s", "--skip-reinstall", action="store_true", help="Skip reinstall when already correct.")
    parser.add_argument("-p", "--production", action="store_true", help="Install modules in production (non-editable).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed output.")
    parser.add_argument("-a", "--include-hidden", action="store_true", help="Include dot-prefixed (hidden) module folders.")
    parser.add_argument("-I", "--ignore-requirements", action="store_true", help="Do not install requirements.txt for each module.")
    args = parser.parse_args()

    global _is_verbose
    _is_verbose = args.verbose

    # log directory for per-module pip/stdout
    logs_dir = args.scripts_dir / "setup_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    all_errors = []
    with section("Python Modules Installation"):
        current_modules_dir = args.scripts_dir / "modules"
        all_errors.extend(
            install_python_modules(
                current_modules_dir, logs_dir,
                skip_reinstall=args.skip_reinstall,
                production=args.production,
                verbose=args.verbose,
                include_hidden=args.include_hidden,
                ignore_requirements=args.ignore_requirements,
            )
        )

    ensure_pythonpath(args.scripts_dir / "modules", args.dotfiles_dir, args.verbose)

    if all_errors:
        log_warning(f"Completed with {len(all_errors)} error(s) in module installation.")
        for mod in all_errors:
            print(f"FAILED_MODULE: {mod}")
        sys.exit(1)
    else:
        print("[OK] setup.py completed.")

if __name__ == "__main__":
    main()
