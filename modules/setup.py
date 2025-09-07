#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from pathlib import Path
import re
from typing import List, Tuple

# --- Ensure tomllib (via tomli) is available ---
try:
    import tomllib  # Py3.11+
except ImportError:
    try:
        import tomli as tomllib  # Py<=3.10
    except ImportError:
        print("[ERROR] 'tomli' (for TOML parsing) is not installed.", file=sys.stderr)
        print("[ERROR] Run project root setup.py, or: pip install tomli", file=sys.stderr)
        sys.exit(1)

# --- Fallback logging & section wrappers (compatible with standard_ui) ---
_is_verbose = ("--verbose" in sys.argv) or ("-v" in sys.argv)

def _fb_info(msg):    print(f"[INFO] {msg}")      if _is_verbose else None
def _fb_success(msg): print(f"[SUCCESS] {msg}")
def _fb_warn(msg):    print(f"[WARNING] {msg}")
def _fb_err(msg):     print(f"[ERROR] {msg}")

class _FBSection:
    def __init__(self, title): self.title = title
    def __enter__(self):
        if _is_verbose: print(f"\n--- {self.title} ---")
        return self
    def __exit__(self, et, ev, tb):
        if _is_verbose: print(f"--- End {self.title} ---\n")

log_info, log_success, log_warning, log_error, section = _fb_info, _fb_success, _fb_warn, _fb_err, _FBSection

try:
    from standard_ui.standard_ui import (
        log_info as real_info,
        log_success as real_success,
        log_warning as real_warning,
        log_error as real_error,
        section as real_section,
    )
    log_info, log_success, log_warning, log_error, section = real_info, real_success, real_warning, real_error, real_section
except Exception:
    if _is_verbose:
        print("[WARNING] standard_ui not found in modules/setup.py. Using basic print for logging.")

# -------------------- Log file (always append) --------------------
LOG_FILE: Path | None = None

def _ensure_log_file(p: Path):
    global LOG_FILE
    LOG_FILE = p
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def _append_log(header: str, body: str = ""):
    if not LOG_FILE:
        return
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"=== {header} ===\n")
            if body:
                f.write(body.rstrip() + "\n")
            f.write("\n")
    except Exception:
        pass

# -------------------- Subprocess helpers --------------------
def _make_env_with_pip_sane(env: dict) -> dict:
    env = dict(env)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PIP_NO_INPUT", "1")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PIP_PROGRESS_BAR", "off")
    return env

def _stream_run(cmd, cwd: Path | None = None) -> Tuple[int, str, str]:
    """
    VERBOSE: Stream stdout/stderr live + collect buffers.
    NON-VERBOSE: Do NOT use this (it would spam). Use _run_quiet_to_log.
    """
    env = _make_env_with_pip_sane(os.environ.copy())
    proc = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="ignore", bufsize=1, env=env
    )
    out_buf, err_buf = [], []
    import threading

    def _reader(stream, collector, is_err=False):
        for line in iter(stream.readline, ''):
            collector.append(line)
            try:
                if is_err: print(line, end='', file=sys.stderr, flush=True)
                else:      print(line, end='', flush=True)
            except Exception:
                pass

    t_out = threading.Thread(target=_reader, args=(proc.stdout, out_buf, False), daemon=True)
    t_err = threading.Thread(target=_reader, args=(proc.stderr, err_buf, True), daemon=True)
    t_out.start(); t_err.start()
    rc = proc.wait()
    t_out.join(); t_err.join()
    return rc, ''.join(out_buf), ''.join(err_buf)

def _run_quiet_to_log(cmd, module_name: str, step: str) -> int:
    """
    NON-VERBOSE: capture stdout/err and append to setup.log, keep console clean.
    """
    env = _make_env_with_pip_sane(os.environ.copy())
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="ignore", bufsize=1, env=env
    )
    out, err = proc.communicate()
    _append_log(f"{module_name} :: {step} :: CMD", " ".join(cmd))
    if out: _append_log(f"{module_name} :: {step} :: STDOUT", out)
    if err: _append_log(f"{module_name} :: {step} :: STDERR", err)
    return proc.returncode

# -------------------- Console one-line updater --------------------
class OneLine:
    def __init__(self):
        self.last_len = 0
        self.active = False
    def write(self, s: str):
        self.active = True
        pad = max(0, self.last_len - len(s))
        sys.stdout.write("\r" + s + (" " * pad))
        sys.stdout.flush()
        self.last_len = len(s)
    def done(self, newline=True):
        if self.active and newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
        self.last_len = 0
        self.active = False

# -------------------- Module helpers --------------------
def _pkg_name_from_dir(module_source_path: Path, verbose: bool) -> str:
    pyproject_file = module_source_path / "pyproject.toml"
    package_name_from_dir = module_source_path.name
    if pyproject_file.is_file():
        try:
            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)
            if "project" in data and "name" in data["project"]:
                if verbose: log_info(f"[{package_name_from_dir}] project.name = {data['project']['name']}")
                return data["project"]["name"]
            if "tool" in data and "poetry" in data["tool"] and "name" in data["tool"]["poetry"]:
                if verbose: log_info(f"[{package_name_from_dir}] tool.poetry.name = {data['tool']['poetry']['name']}")
                return data["tool"]["poetry"]["name"]
        except Exception as e:
            if verbose: log_warning(f"[{package_name_from_dir}] Could not parse pyproject.toml: {type(e).__name__}: {e}")
    return package_name_from_dir

def _determine_install_status(module_source_path: Path, verbose: bool) -> str | None:
    package_name_to_query = _pkg_name_from_dir(module_source_path, verbose)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package_name_to_query],
            capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore'
        )
        if result.returncode != 0:
            if verbose: log_info(f"'{package_name_to_query}' not found by 'pip show' (rc: {result.returncode}).")
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
                            if verbose: log_info(f"'{package_name_to_query}' is editable from expected source: {source_loc}")
                            is_our_editable_install = True
                        else:
                            if verbose: log_warning(f"'{package_name_to_query}' is editable at {editable_loc}, expected {source_loc}")
                        break
                    except Exception as e_path:
                        if verbose: log_warning(f"Path comparison error for '{package_name_to_query}': {e_path}")
                        break
        if is_our_editable_install:
            return "editable"
        if verbose: log_info(f"'{package_name_to_query}' appears installed non-editable.")
        return "normal"
    except Exception as e:
        if verbose: log_warning(f"Could not query 'pip show' for '{package_name_to_query}': {type(e).__name__}: {e}")
        return None

# -------------------- Requirements then module install --------------------
def _read_requirements(req_path: Path) -> List[str]:
    lines = []
    try:
        for raw in req_path.read_text(encoding="utf-8").splitlines():
            s = raw.strip()
            if not s or s.startswith("#"): continue
            if s.startswith("-"):  # ignore options like -r another.txt, -f, --extra-index-url etc
                continue
            lines.append(s)
    except Exception:
        pass
    return lines

def _install_requirements_progress(module_path: Path, module_name: str, verbose: bool, progress: OneLine) -> Tuple[bool, List[Tuple[str, bool]]]:
    req_file = module_path / "requirements.txt"
    if not req_file.is_file():
        return True, []

    reqs = _read_requirements(req_file)
    total = len(reqs)
    results: List[Tuple[str, bool]] = []
    if total == 0:
        return True, results

    # Live progress (single line) in non-verbose
    if not verbose:
        progress.write(f"{module_name}: 0/{total}")

    for i, req in enumerate(reqs, 1):
        cmd = [sys.executable, "-m", "pip", "install", req]
        step = f"pip install {req}"
        if verbose:
            log_info(f"[{module_name}] Installing requirement: {req}")
            rc, out, err = _stream_run(cmd)
            _append_log(f"{module_name} :: {step} :: CMD", " ".join(cmd))
            if out: _append_log(f"{module_name} :: {step} :: STDOUT", out)
            if err: _append_log(f"{module_name} :: {step} :: STDERR", err)
        else:
            rc = _run_quiet_to_log(cmd, module_name, step)
            progress.write(f"{module_name}: {i}/{total}")

        ok = (rc == 0)
        results.append((req, ok))
        if not ok and verbose:
            log_error(f"[{module_name}] requirement failed: {req} (rc={rc})")

    if not verbose:
        # leave the last count on the line; final decision will replace it once module install completes
        pass
    all_ok = all(ok for _, ok in results)
    return all_ok, results

def _install_module_package(module_path: Path, *, production: bool, module_name: str, verbose: bool, progress: OneLine) -> bool:
    cmd = [sys.executable, "-m", "pip", "install"]
    if not production: cmd.append("-e")
    cmd.append(str(module_path.resolve()))
    step = f"pip install {'-e ' if not production else ''}{module_path.name}"

    if verbose:
        log_info(f"[{module_name}] Installing package in {'editable' if not production else 'production'} mode …")
        rc, out, err = _stream_run(cmd)
        _append_log(f"{module_name} :: {step} :: CMD", " ".join(cmd))
        if out: _append_log(f"{module_name} :: {step} :: STDOUT", out)
        if err: _append_log(f"{module_name} :: {step} :: STDERR", err)
    else:
        rc = _run_quiet_to_log(cmd, module_name, step)

    return rc == 0

def _install_module(module_path: Path, *, production: bool, skip_reinstall: bool, verbose: bool, scripts_dir: Path) -> Tuple[bool, str]:
    module_name = module_path.name
    desired = "normal" if production else "editable"
    current = _determine_install_status(module_path, verbose) if skip_reinstall else None
    if current == desired:
        print(f"[•] {module_name}: already ({current}) — skip")
        return True, f"already ({current})"

    # log file target
    _ensure_log_file(scripts_dir / "setup.log")

    progress = OneLine()

    # 1) requirements (if any), with progress
    ok_reqs, req_results = _install_requirements_progress(module_path, module_name, verbose, progress)

    # 2) package install (only if reqs OK)
    pkg_ok = False
    if ok_reqs:
        pkg_ok = _install_module_package(module_path, production=production, module_name=module_name, verbose=verbose, progress=progress)

    # Finalize the single-line status (non-verbose)
    if not verbose:
        req_count = len(req_results)
        if ok_reqs and pkg_ok:
            progress.write(f"{module_name}: {req_count}/{req_count} installed! ✓")
            progress.done(True)
        elif not ok_reqs:
            failed = sum(1 for _, ok in req_results if not ok)
            progress.write(f"{module_name}: {req_count - failed}/{req_count} installed, {failed} failed ✗ (see setup.log)")
            progress.done(True)
            # Only expand detail if there was a requirement failure.
            print(f"{module_name}:")
            for req, ok in req_results:
                mark = "✓" if ok else "✗"
                tail = "" if ok else "  (see setup.log)"
                print(f"  {mark} {req}{tail}")
        else:
            # reqs ok but package failed
            progress.write(f"{module_name}: {req_count}/{req_count} requirements ok, package install failed ✗ (see setup.log)")
            progress.done(True)

    if ok_reqs and pkg_ok:
        return True, "installed"
    if not ok_reqs:
        return False, "failed (requirements)"
    return False, "failed (package)"

# -------------------- Scanner/installer --------------------
def install_python_modules(modules_dir: Path, skip_reinstall: bool, production: bool, verbose: bool, include_hidden: bool, scripts_dir: Path) -> list[str]:
    errors_encountered: list[str] = []
    if not modules_dir.exists() or not modules_dir.is_dir():
        log_warning(f"Modules directory '{modules_dir}' not found. Skipping module installation.")
        return errors_encountered

    log_info(f"Scanning for Python modules in: {modules_dir}")
    skipped_hidden: list[str] = []

    for entry in sorted(modules_dir.iterdir(), key=lambda p: p.name.lower()):
        name = entry.name

        # ignore our own folder if any
        try:
            if entry.resolve() == Path(__file__).resolve().parent:
                print(f"[•] {name}: internal setup folder — skipped")
                continue
        except Exception:
            pass

        if not entry.is_dir():
            print(f"[•] {name}: not a directory — skipped")
            continue

        if name.startswith(".") and not include_hidden:
            skipped_hidden.append(name)
            print(f"[•] {name}: ignored (hidden)")
            continue

        has_setup_py = (entry / "setup.py").exists()
        has_pyproject = (entry / "pyproject.toml").exists()
        if not has_setup_py and not has_pyproject:
            print(f"[•] {name}: no installer (no setup.py/pyproject.toml) — skipped")
            continue

        if not has_pyproject:
            log_warning(f"[{name}] pyproject.toml not found — installing anyway (legacy setup)")

        ok, what = _install_module(entry, production=production, skip_reinstall=skip_reinstall, verbose=verbose, scripts_dir=scripts_dir)
        if not ok:
            errors_encountered.append(name)

    if skipped_hidden:
        print("\nHidden modules not processed:")
        for n in skipped_hidden:
            print(f"  - {n} (dot-prefixed; ignored)")

    return errors_encountered

# -------------------- PYTHONPATH configuration (unchanged) --------------------
import re as _re
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
                            match = _re.search(regex_pattern, line.strip(), _re.IGNORECASE)
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
                                check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore'
                            )
                            if verbose and ps_proc.stdout.strip(): log_info(f"PowerShell output: {ps_proc.stdout.strip()}")
                            if verbose and ps_proc.stderr.strip(): log_warning(f"PowerShell stderr: {ps_proc.stderr.strip()}")
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
                    try: current_config_content = pythonpath_config_file.read_text(encoding="utf-8")
                    except Exception as e_read: log_warning(f"Could not read {pythonpath_config_file}: {e_read}")

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

# -------------------- Orchestrator --------------------
def main_modules_setup(scripts_dir_arg: Path, dotfiles_dir_arg: Path, bin_dir_arg: Path,
                       skip_reinstall_arg: bool, production_arg: bool, verbose_arg: bool, include_hidden_arg: bool):
    global _is_verbose
    _is_verbose = verbose_arg

    with section("Python Modules Installation"):
        current_modules_dir = scripts_dir_arg / "modules"
        install_errors = install_python_modules(
            current_modules_dir,
            skip_reinstall_arg,
            production_arg,
            verbose_arg,
            include_hidden_arg,
            scripts_dir=scripts_dir_arg,
        )

    ensure_pythonpath(scripts_dir_arg / "modules", dotfiles_dir_arg, verbose_arg)

    if install_errors:
        log_warning(f"Completed with {len(install_errors)} error(s) in module installation.")
        for name in install_errors:
            print(f"FAILED_MODULE: {name}")
        sys.exit(1)
    else:
        print("[OK] setup.py completed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Python modules from the 'modules' directory and configure PYTHONPATH.")
    # Defaults from env; error only if missing.
    default_scripts = os.environ.get("SCRIPTS")
    default_dotfiles = os.environ.get("DOTFILES")
    default_bin = str(Path(default_scripts).joinpath("bin")) if default_scripts else None

    parser.add_argument("-R", "--scripts-dir", type=Path, required=False, default=Path(default_scripts) if default_scripts else None,
                        help="Base project scripts directory. Defaults to $SCRIPTS.")
    parser.add_argument("-D", "--dotfiles-dir", type=Path, required=False, default=Path(default_dotfiles) if default_dotfiles else None,
                        help="Root directory of dotfiles. Defaults to $DOTFILES.")
    parser.add_argument("-B", "--bin-dir", type=Path, required=False, default=Path(default_bin) if default_bin else None,
                        help="Target directory for binaries. Defaults to <scripts-dir>/bin.")
    parser.add_argument("-s", "--skip-reinstall", action="store_true", help="Skip reinstall when already correct.")
    parser.add_argument("-p", "--production", action="store_true", help="Install modules in production (non-editable) mode.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed output.")
    parser.add_argument("-q", "--quiet", action="store_true", help="(Ignored; reserved).")
    parser.add_argument("-a", "--include-hidden", action="store_true", help="Include dot-prefixed (hidden) module folders.")
    args = parser.parse_args()

    # Validate required roots
    if not args.scripts_dir:
        print("[ERROR] --scripts-dir not provided and $SCRIPTS is not set.", file=sys.stderr)
        sys.exit(2)
    if not args.dotfiles_dir:
        print("[ERROR] --dotfiles-dir not provided and $DOTFILES is not set.", file=sys.stderr)
        sys.exit(2)
    bin_dir = args.bin_dir if args.bin_dir else args.scripts_dir / "bin"

    # ensure log path
    _ensure_log_file(args.scripts_dir / "setup.log")

    main_modules_setup(
        args.scripts_dir,
        args.dotfiles_dir,
        bin_dir,
        args.skip_reinstall,
        args.production,
        args.verbose,
        args.include_hidden,
    )
