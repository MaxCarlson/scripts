#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from pathlib import Path
import re
import importlib

# --- Ensure tomllib (via tomli) is available ---
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("[ERROR] 'tomli' (for TOML parsing) is not installed.", file=sys.stderr)
        print(
            "[ERROR] Please run the main 'setup.py' script from the project root, or install 'tomli' manually ('pip install tomli').",
            file=sys.stderr,
        )
        sys.exit(1)

# -----------------------------------------------------------------------------
# Fallback logging + status/section wrappers (compatible with standard_ui or not)
# -----------------------------------------------------------------------------
_is_verbose_modules = ("--verbose" in sys.argv) or ("-v" in sys.argv)
STANDARD_UI_LOADED_MODULES = False

def _fb_info(msg): 
    if _is_verbose_modules:
        print(f"[INFO] {msg}")
def _fb_success(msg): print(f"[SUCCESS] {msg}")
def _fb_warn(msg): print(f"[WARNING] {msg}")
def _fb_err(msg): print(f"[ERROR] {msg}")

class _FBSection:
    def __init__(self, title): self.title = title
    def __enter__(self):
        if _is_verbose_modules: print(f"\n--- Section: {self.title} ---")
        return self
    def __exit__(self, et, ev, tb):
        if _is_verbose_modules: print(f"--- End Section: {self.title} ---\n")

def _fb_status(label: str, state: str | None = None, detail: str | None = None):
    # one-liner, always printed
    prefix = {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}.get(state or "", "•")
    tail = f" — {detail}" if detail else ""
    print(f"[{prefix}] {label}{tail}")

# defaults (maybe overridden by standard_ui)
log_info, log_success, log_warning, log_error, section = _fb_info, _fb_success, _fb_warn, _fb_err, _FBSection
_status_impl = _fb_status

try:
    import standard_ui.standard_ui as _sui

    log_info = getattr(_sui, "log_info", log_info)
    log_success = getattr(_sui, "log_success", log_success)
    log_warning = getattr(_sui, "log_warning", log_warning)
    log_error = getattr(_sui, "log_error", log_error)
    section = getattr(_sui, "section", section)
    _status_impl = getattr(_sui, "status_line", _status_impl)
    STANDARD_UI_LOADED_MODULES = True
except Exception:
    if _is_verbose_modules:
        print("[WARNING] standard_ui not found in modules/setup.py. Using basic print for logging.")

def status_line(label: str, state: str | None = None, detail: str | None = None):
    """
    Always prints a single status line. Compatible with standard_ui.status_line
    even if its signature differs; falls back to our formatter if needed.
    """
    impl = _status_impl
    if impl is _fb_status:
        return impl(label, state, detail)
    try:
        return impl(label, state, detail)  # 3-arg
    except TypeError:
        pass
    try:
        return impl(label, state)  # 2-arg
    except TypeError:
        pass
    try:
        # compose a single string for 1-arg
        prefix = {"unchanged": "•", "ok": "OK", "warn": "!", "fail": "X"}.get(state or "", "•")
        tail = f" — {detail}" if detail else ""
        return impl(f"[{prefix}] {label}{tail}")
    except TypeError:
        return _fb_status(label, state, detail)

# -----------------------------------------------------------------------------
# Helpers for module discovery/installation
# -----------------------------------------------------------------------------
_GREEN_FB = "\033[92m"
_RED_FB = "\033[91m"
_RESET_FB = "\033[0m"

def _get_canonical_package_name_from_source_for_modules(module_source_path: Path, verbose: bool) -> str:
    pyproject_file = module_source_path / "pyproject.toml"
    package_name_from_dir = module_source_path.name
    if pyproject_file.is_file():
        try:
            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)
            if "project" in data and "name" in data["project"]:
                name = data["project"]["name"]
                if verbose: log_info(f"Found package name '{name}' in {pyproject_file}")
                return name
            if "tool" in data and "poetry" in data and "name" in data["tool"]["poetry"]:
                name = data["tool"]["poetry"]["name"]
                if verbose: log_info(f"Found poetry package name '{name}' in {pyproject_file}")
                return name
            if verbose:
                log_info(
                    f"{pyproject_file} found but 'project.name' or 'tool.poetry.name' not found. "
                    f"Falling back to dir name '{package_name_from_dir}'."
                )
        except tomllib.TOMLDecodeError as e:
            log_warning(f"Could not parse {pyproject_file}: {e}. Falling back to dir name '{package_name_from_dir}'.")
        except Exception as e:
            log_warning(f"Error reading/parsing {pyproject_file}: {type(e).__name__}: {e}. Falling back to '{package_name_from_dir}'.")
    else:
        if verbose: log_info(f"No pyproject.toml in {module_source_path}. Using dir name '{package_name_from_dir}'.")
    return package_name_from_dir

def _determine_install_status(module_source_path: Path, verbose: bool) -> str | None:
    """
    Returns: 'editable', 'normal', or None if not installed
    """
    pkg = _get_canonical_package_name_from_source_for_modules(module_source_path, verbose)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="ignore",
        )
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
    except Exception as e:
        if verbose:
            log_warning(f"pip show error for '{pkg}': {type(e).__name__}: {e}")
        return None

def _install_one_module(module_path: Path, *, production: bool, skip_reinstall: bool, verbose: bool) -> tuple[bool, str]:
    """
    Attempt to install a module (setup.py or pyproject.toml present).
    Returns (ok, status_text) where status_text is one of:
    - 'already (editable)'
    - 'already (normal)'
    - 'installed (editable)'
    - 'installed (normal)'
    - 'reinstalled (editable|normal)'
    - 'failed'
    """
    desired = "normal" if production else "editable"

    current = _determine_install_status(module_path, verbose) if skip_reinstall else None
    if current == desired:
        return True, f"already ({current})"

    # decide if we need to (re)install
    install_cmd = [sys.executable, "-m", "pip", "install"]
    if not production:
        install_cmd.append("-e")
    install_cmd.append(str(module_path.resolve()))

    if verbose:
        log_info(f"Installing '{module_path.name}' in {'production' if production else 'editable'} mode...")
        process = subprocess.Popen(
            install_cmd,
            text=True,
            encoding="utf-8",
            errors="ignore",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate()
        if process.returncode == 0:
            status = "reinstalled" if current else "installed"
            if verbose:
                if stdout and stdout.strip():
                    log_info(f"Install output:\n{stdout.strip()}")
                if stderr and stderr.strip():
                    log_warning(f"Install stderr (may be informational):\n{stderr.strip()}")
            return True, f"{status} ({desired})"
        else:
            if verbose:
                log_error(f"Install failed for '{module_path.name}'.")
                if stdout and stdout.strip():
                    log_error(f"Stdout:\n{stdout.strip()}")
                if stderr and stderr.strip():
                    log_error(f"Stderr:\n{stderr.strip()}")
            return False, "failed"
    else:
        # quiet run, but still show a one-liner outcome
        result = subprocess.run(
            install_cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if result.returncode == 0:
            return True, f"{'reinstalled' if current else 'installed'} ({desired})"
        else:
            return False, "failed"

# -----------------------------------------------------------------------------
# Main installation routine scanning modules/
# -----------------------------------------------------------------------------

def install_python_modules(
    modules_dir: Path,
    skip_reinstall: bool,
    production: bool,
    verbose: bool,
    include_hidden: bool,
) -> list[str]:
    errors_encountered: list[str] = []
    if not modules_dir.exists() or not modules_dir.is_dir():
        status_line(f"{modules_dir}: not found — skipped", "warn")
        return errors_encountered

    log_info(f"Scanning for Python modules in: {modules_dir}")

    # iterate and print a status line for EVERYTHING we consider
    for entry in sorted(modules_dir.iterdir(), key=lambda p: p.name.lower()):
        name = entry.name

        # ignore our own file
        if entry.resolve() == Path(__file__).resolve().parent:
            status_line(f"{name}: internal setup folder — skipped", "unchanged")
            continue

        # Ignore files
        if not entry.is_dir():
            status_line(f"{name}: not a directory — skipped", "unchanged")
            continue

        # Ignore hidden/dot folders unless explicitly included
        if name.startswith(".") and not include_hidden:
            status_line(f"{name}: ignored (hidden)", "unchanged")
            continue

        has_setup_py = (entry / "setup.py").exists()
        has_pyproject = (entry / "pyproject.toml").exists()

        if not has_setup_py and not has_pyproject:
            status_line(f"{name}: no installer (no setup.py/pyproject) — skipped", "unchanged")
            continue

        # Attempt install
        ok, what = _install_one_module(
            entry,
            production=production,
            skip_reinstall=skip_reinstall,
            verbose=verbose,
        )
        if ok:
            if what.startswith("already"):
                status_line(f"{name}: {what}", "unchanged", "skip")
            elif what.startswith("reinstalled"):
                status_line(f"{name}: {what}", "ok")
            else:
                status_line(f"{name}: {what}", "ok")
        else:
            status_line(f"{name}: install failed", "fail")
            errors_encountered.append(f"Installation of {name} from {entry} failed")

    return errors_encountered

# -----------------------------------------------------------------------------
# PYTHONPATH configuration (unchanged logic, with mild tidy)
# -----------------------------------------------------------------------------

def ensure_pythonpath(modules_dir: Path, dotfiles_dir: Path, verbose: bool = False):
    modules_dir_abs = str(modules_dir.resolve())
    path_separator = os.pathsep

    with section("PYTHONPATH Configuration"):
        if os.name == "nt":
            with section("Windows PYTHONPATH Update"):
                log_info("Windows OS detected for PYTHONPATH setup.")
                try:
                    completed_process = subprocess.run(
                        ["reg", "query", r"HKCU\Environment", "/v", "PYTHONPATH"],
                        capture_output=True,
                        text=True,
                        check=False,
                        encoding="utf-8",
                        errors="ignore",
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

                    current_paths_list = list(
                        dict.fromkeys([p for p in current_user_pythonpath.split(path_separator) if p])
                    )

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
                                check=True,
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                                errors="ignore",
                            )
                            if verbose and ps_proc.stdout.strip():
                                log_info(f"PowerShell output: {ps_proc.stdout.strip()}")
                            if verbose and ps_proc.stderr.strip():
                                log_warning(f"PowerShell stderr: {ps_proc.stderr.strip()}")
                        else:
                            if verbose:
                                log_info("PowerShell not found, attempting 'setx' for PYTHONPATH.")
                            subprocess.run(["setx", "PYTHONPATH", new_pythonpath_value], check=True)
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

                current = ""
                if pythonpath_config_file.exists():
                    try:
                        current = pythonpath_config_file.read_text(encoding="utf-8")
                    except Exception as e_read:
                        log_warning(f"Could not read {pythonpath_config_file}: {e_read}")

                already = False
                for line in current.splitlines():
                    if line.strip().startswith(f'export PYTHONPATH="{modules_dir_abs}') or \
                       f'{path_separator}{modules_dir_abs}{path_separator}' in line or \
                       line.strip().endswith(f'{path_separator}{modules_dir_abs}"'):
                        already = True
                        break

                if already and f'export PYTHONPATH="{modules_dir_abs}{path_separator}${{PYTHONPATH}}"' in current:
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
                            if verbose:
                                log_info(f"Attempting to have Zsh sub-shell source: {source_cmd}")
                            result = subprocess.run(
                                ["zsh", "-c", source_cmd],
                                timeout=5,
                                check=True,
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                                errors="ignore",
                            )
                            if verbose:
                                if result.stdout.strip():
                                    log_success(
                                        f"Sourced {pythonpath_config_file} in a zsh sub-shell. New PYTHONPATH (in sub-shell): {result.stdout.strip()}"
                                    )
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

# -----------------------------------------------------------------------------
# Orchestrator
# -----------------------------------------------------------------------------

def main_modules_setup(
    scripts_dir_arg: Path,
    dotfiles_dir_arg: Path,
    bin_dir_arg: Path,
    skip_reinstall_arg: bool,
    production_arg: bool,
    verbose_arg: bool,
    include_hidden_arg: bool,
):
    global _is_verbose_modules
    _is_verbose_modules = verbose_arg

    with section("Python Modules Installation"):
        current_modules_dir = scripts_dir_arg / "modules"
        install_errors = install_python_modules(
            current_modules_dir,
            skip_reinstall_arg,
            production_arg,
            verbose_arg,
            include_hidden_arg,
        )

    ensure_pythonpath(scripts_dir_arg / "modules", dotfiles_dir_arg, verbose_arg)

    if install_errors:
        # Let the caller (top-level setup.py) decide whether to fail/continue.
        # We print a single warning here so something visible shows up in the sub-setup block.
        log_warning(f"Completed with {len(install_errors)} error(s) in module installation.")
        # Emit a token for the caller to parse if they want
        for e in install_errors:
            print(f"FAILED_MODULE: {e}")
        sys.exit(1)
    else:
        print("[OK] setup.py completed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Setup Python modules from the 'modules' directory and configure PYTHONPATH."
    )
    parser.add_argument("-R", "--scripts-dir", type=Path, required=True, help="Base project scripts directory.")
    parser.add_argument("-D", "--dotfiles-dir", type=Path, required=True, help="Root directory of dotfiles.")
    parser.add_argument("-B", "--bin-dir", type=Path, required=True, help="Target directory for binaries.")
    parser.add_argument("-s", "--skip-reinstall", action="store_true", help="Skip reinstall when already correct.")
    parser.add_argument("-p", "--production", action="store_true", help="Install modules in production (non-editable) mode.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed output.")
    parser.add_argument("-q", "--quiet", action="store_true", help="(Ignored; kept for compatibility).")
    parser.add_argument(
        "-a", "--include-hidden", action="store_true",
        help="Include dot-prefixed (hidden) module folders. Default is to ignore them."
    )

    args = parser.parse_args()
    # Note: --quiet is accepted but not used (compatibility with caller)
    main_modules_setup(
        args.scripts_dir,
        args.dotfiles_dir,
        args.bin_dir,
        args.skip_reinstall,
        args.production,
        args.verbose,
        args.include_hidden,
    )
