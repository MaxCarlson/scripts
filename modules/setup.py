#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from pathlib import Path
import re
import importlib  # For invalidate_caches

# --- Ensure tomlib (via tomli) is available ---
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        # This script relies on the main setup.py to bootstrap tomli.
        # If run standalone and tomli is missing, it's a fatal error for this script.
        print("[ERROR] 'tomli' (for TOML parsing) is not installed.", file=sys.stderr)
        print("[ERROR] Please run the main 'setup.py' script from the project root, or install 'tomli' manually ('pip install tomli').", file=sys.stderr)
        sys.exit(1)


# --- Fallback Logging & Globals ---
_sui_log_info_fb = lambda msg: None
_sui_log_success_fb = lambda msg: print(f"[SUCCESS] {msg}")
_sui_log_warning_fb = lambda msg: print(f"[WARNING] {msg}")
_sui_log_error_fb = lambda msg: print(f"[ERROR] {msg}")
_sui_section_fb = None
_is_verbose_modules = "--verbose" in sys.argv or "-v" in sys.argv

class _FallbackSectionModulesClass:
    def __init__(self, title): self.title = title
    def __enter__(self):
        if _is_verbose_modules: print(f"\n--- Section: {self.title} ---")
    def __exit__(self,et,ev,tb):
        if _is_verbose_modules: print(f"--- End Section: {self.title} ---\n")

_sui_section_fb = _FallbackSectionModulesClass

log_info, log_success, log_warning, log_error, section = \
    _sui_log_info_fb, _sui_log_success_fb, _sui_log_warning_fb, _sui_log_error_fb, _sui_section_fb
STANDARD_UI_LOADED_MODULES = False

try:
    from standard_ui.standard_ui import (
        log_info as real_log_info,
        log_success as real_log_success,
        log_warning as real_log_warning,
        log_error as real_log_error,
        section as real_section
    )
    log_info, log_success, log_warning, log_error, section = \
        real_log_info, real_log_success, real_log_warning, real_log_error, real_section
    STANDARD_UI_LOADED_MODULES = True
except ImportError:
    if '--quiet' not in sys.argv and _is_verbose_modules:
        print("[WARNING] standard_ui not found in modules/setup.py. Using basic print for logging.")
    def _verbose_log_info_fb(msg):
        if _is_verbose_modules: print(f"[INFO] {msg}")
    log_info = _verbose_log_info_fb


_GREEN_FB = "\033[92m"
_RED_FB = "\033[91m"
_RESET_FB = "\033[0m"


def _get_canonical_package_name_from_source_for_modules(module_source_path: Path, verbose: bool) -> str:
    pyproject_file = module_source_path / "pyproject.toml"
    package_name_from_dir = module_source_path.name

    logger = log_info
    warn_logger = log_warning

    if pyproject_file.is_file():
        try:
            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)  # tomllib is now expected to be available
            if "project" in data and "name" in data["project"]:
                name = data["project"]["name"]
                if verbose: logger(f"Found package name '{name}' in {pyproject_file}")
                return name
            if "tool" in data and "poetry" in data and "name" in data["tool"]["poetry"]:
                name = data["tool"]["poetry"]["name"]
                if verbose: logger(f"Found poetry package name '{name}' in {pyproject_file}")
                return name
            if verbose: logger(f"{pyproject_file} found but 'project.name' or 'tool.poetry.name' not found. Falling back to dir name '{package_name_from_dir}'.")
        except tomllib.TOMLDecodeError as e:
            warn_logger(f"Could not parse {pyproject_file}: {e}. Falling back to dir name '{package_name_from_dir}'.")
        except Exception as e:
            warn_logger(f"Error reading/parsing {pyproject_file}: {type(e).__name__}: {e}. Falling back to dir name '{package_name_from_dir}'.")
    else:
        if verbose: logger(f"No pyproject.toml found in {module_source_path}. Using dir name '{package_name_from_dir}' as package name.")
    return package_name_from_dir

def _determine_install_status(module_source_path: Path, verbose: bool) -> str | None:
    package_name_to_query = _get_canonical_package_name_from_source_for_modules(module_source_path, verbose)
    
    logger = log_info
    warn_logger = log_warning

    try:
        pip_show_cmd = [sys.executable, "-m", "pip", "show", package_name_to_query]
        if verbose: logger(f"Running: {' '.join(pip_show_cmd)}")
        result = subprocess.run(pip_show_cmd, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')

        if result.returncode != 0:
            if verbose: logger(f"'{package_name_to_query}' not found by 'pip show' (rc: {result.returncode}). Assuming not installed.")
            return None

        output_lines = result.stdout.splitlines()
        is_our_editable_install = False
        for line in output_lines:
            if line.lower().startswith("editable project location:"):
                location_path_str = line.split(":", 1)[1].strip()
                if location_path_str and location_path_str.lower() != "none":
                    try:
                        editable_loc = Path(location_path_str).resolve()
                        source_loc = module_source_path.resolve()
                        if editable_loc == source_loc:
                            if verbose: logger(f"'{package_name_to_query}' is editable from expected source: {source_loc}")
                            is_our_editable_install = True
                        else:
                            if verbose: warn_logger(f"'{package_name_to_query}' is editable, but from different location: {editable_loc} (expected {source_loc})")
                        break 
                    except Exception as e_path:
                        if verbose: warn_logger(f"Path resolution/comparison error for '{package_name_to_query}': {e_path}")
                        break
        
        if is_our_editable_install:
            return "editable"
        
        if verbose: logger(f"'{package_name_to_query}' found by 'pip show', but not (or not our) editable install. Treating as 'normal'.")
        return "normal"

    except Exception as e:
        warn_logger(f"Could not query 'pip show' for '{package_name_to_query}': {type(e).__name__}: {e}")
        return None


def install_python_modules(modules_dir: Path, skip_reinstall: bool, production: bool, verbose: bool) -> list:
    errors_encountered = []
    if not modules_dir.exists() or not modules_dir.is_dir():
        log_warning(f"Modules directory '{modules_dir}' not found. Skipping module installation.")
        return errors_encountered

    log_info(f"Scanning for Python modules in: {modules_dir}")
    found_module_to_install = False

    for potential_module_path in modules_dir.iterdir():
        if not potential_module_path.is_dir():
            if verbose: log_info(f"Skipping '{potential_module_path.name}', as it's not a directory.")
            continue

        # NEW: allow skipping unfinished / WIP modules via dot-prefix
        name = potential_module_path.name
        if name.startswith('.'):
            if verbose: log_info(f"Skipping '{name}' (dot-prefixed; marked as WIP).")
            continue

        has_setup_py = (potential_module_path / "setup.py").exists()
        has_pyproject_toml = (potential_module_path / "pyproject.toml").exists()

        if not has_setup_py and not has_pyproject_toml:
            if verbose: log_info(f"Skipping '{potential_module_path.name}', no setup.py or pyproject.toml found.")
            continue
        
        if potential_module_path.name == "setup.py" and potential_module_path.is_file():
             if verbose: log_info(f"Skipping '{potential_module_path.name}' as it is a file, not a module directory.")
             continue
        if potential_module_path.resolve() == Path(__file__).resolve().parent:
            if verbose: log_info(f"Skipping '{potential_module_path.name}' as it's the directory of this setup script.")
            continue

        found_module_to_install = True
        module_name_for_display = potential_module_path.name
        
        section_context = section(f"Module: {module_name_for_display}")
        with section_context:
            log_info(f"Processing module: {module_name_for_display}")
            desired_install_mode = "normal" if production else "editable"
            
            if skip_reinstall:
                current_install_mode = _determine_install_status(potential_module_path, verbose)
                if current_install_mode:
                    if current_install_mode == desired_install_mode:
                        log_success(f"Module '{module_name_for_display}' is already installed in the desired '{current_install_mode}' mode from {potential_module_path}. Skipping.")
                        continue
                    else:
                        log_info(f"Module '{module_name_for_display}' is installed in '{current_install_mode}' mode from {potential_module_path}, but '{desired_install_mode}' mode is desired. Re-installing.")
                else:
                    log_info(f"Module '{module_name_for_display}' (from {potential_module_path}) not found or status unknown. Proceeding with installation.")
            else:
                log_info(f"Explicit installation requested for '{module_name_for_display}' (skip-reinstall is OFF).")

            install_cmd = [sys.executable, "-m", "pip", "install"]
            if not production:
                install_cmd.append("-e")
            
            resolved_module_path_str = str(potential_module_path.resolve())
            install_cmd.append(resolved_module_path_str)

            mode_text = "production (non-editable)" if production else "development (editable)"
            log_info(f"Installing '{module_name_for_display}' in {mode_text} mode from {resolved_module_path_str}...")
            
            try:
                if verbose:
                    process = subprocess.Popen(install_cmd, text=True, encoding='utf-8', errors='ignore',
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    stdout, stderr = process.communicate()
                    if process.returncode == 0:
                        log_success(f"Successfully installed/updated '{module_name_for_display}'.")
                        if stdout and stdout.strip(): log_info(f"Install output for {module_name_for_display}:\n{stdout.strip()}")
                        if stderr and stderr.strip(): log_warning(f"Install stderr for {module_name_for_display} (may be informational):\n{stderr.strip()}")
                    else:
                        raise subprocess.CalledProcessError(process.returncode, install_cmd, output=stdout, stderr=stderr)
                else:
                    sys.stdout.write(f"Installing: {module_name_for_display} {mode_text}... ")
                    sys.stdout.flush()
                    result = subprocess.run(install_cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    sys.stdout.write(f"{_GREEN_FB}✅{_RESET_FB}\n")
                    sys.stdout.flush()
                    if STANDARD_UI_LOADED_MODULES: # Only log full output if sui is available (implies richer logging)
                         if result.stdout and result.stdout.strip(): log_info(f"Install output for {module_name_for_display}:\n{result.stdout.strip()}")
                         if result.stderr and result.stderr.strip(): log_warning(f"Install stderr for {module_name_for_display} (may be informational):\n{result.stderr.strip()}")

            except subprocess.CalledProcessError as e:
                if not verbose: sys.stdout.write(f"{_RED_FB}❌{_RESET_FB}\n"); sys.stdout.flush()
                log_error(f"Error installing module '{module_name_for_display}'.")
                log_error(f"Command: {' '.join(e.cmd)}")
                stdout_str = e.output if isinstance(e.output, str) else (e.output.decode('utf-8', 'ignore') if hasattr(e.output, 'decode') else str(e.output))
                stderr_str = e.stderr if isinstance(e.stderr, str) else (e.stderr.decode('utf-8', 'ignore') if hasattr(e.stderr, 'decode') else str(e.stderr))
                if stdout_str: log_error(f"Stdout:\n{stdout_str}")
                if stderr_str: log_error(f"Stderr:\n{stderr_str}")
                errors_encountered.append(f"Installation of {module_name_for_display} from {resolved_module_path_str} failed (rc: {e.returncode})")
            except Exception as e:
                if not verbose: sys.stdout.write(f"{_RED_FB}❌{_RESET_FB}\n"); sys.stdout.flush()
                log_error(f"An unexpected error occurred while trying to install '{module_name_for_display}': {type(e).__name__}: {e}")
                errors_encountered.append(f"Unexpected error installing {module_name_for_display} from {resolved_module_path_str}")

    if not found_module_to_install:
        log_info("No installable Python modules found in the modules directory.")
    return errors_encountered

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
                            if match: current_user_pythonpath = match.group(1).strip(); break
                    
                    if verbose: log_info(f"Current User PYTHONPATH from registry: '{current_user_pythonpath}'")

                    current_paths_list = list(dict.fromkeys([p for p in current_user_pythonpath.split(path_separator) if p]))
                    
                    if modules_dir_abs in current_paths_list:
                        log_success(f"{modules_dir_abs} is already in the User PYTHONPATH.")
                    else:
                        log_info(f"Adding {modules_dir_abs} to User PYTHONPATH.")
                        new_pythonpath_list = current_paths_list + [modules_dir_abs]
                        new_pythonpath_value = path_separator.join(list(dict.fromkeys(new_pythonpath_list)))

                        is_pwsh_available = bool(subprocess.run(["where", "pwsh"], capture_output=True, shell=True).stdout or \
                                              subprocess.run(["where", "powershell"], capture_output=True, shell=True).stdout)
                        if is_pwsh_available:
                            if verbose: log_info("Using PowerShell to update User PYTHONPATH.")
                            ps_command_parts = [
                                '$envName = "User";', '$varName = "PYTHONPATH";', f'$valueToAdd = "{modules_dir_abs}";',
                                '$currentValue = [System.Environment]::GetEnvironmentVariable($varName, $envName);',
                                '$elements = @($currentValue -split [System.IO.Path]::PathSeparator | Where-Object { $_ -ne "" });',
                                'if ($elements -notcontains $valueToAdd) {',
                                '  $newElements = $elements + $valueToAdd;',
                                '  $newValue = $newElements -join [System.IO.Path]::PathSeparator;',
                                '  [System.Environment]::SetEnvironmentVariable($varName, $newValue, $envName);',
                                '  Write-Host "Successfully updated User PYTHONPATH via PowerShell.";',
                                '} else { Write-Host ($valueToAdd + " already in User PYTHONPATH (PowerShell check)."); }'
                            ]
                            ps_command = " ".join(ps_command_parts)
                            pwsh_exe = "pwsh" if subprocess.run(["where", "pwsh"], capture_output=True, shell=True).stdout else "powershell"
                            ps_proc = subprocess.run([pwsh_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command], 
                                                     check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                            if verbose: log_info(f"PowerShell output: {ps_proc.stdout.strip()}")
                            if ps_proc.stderr.strip() and verbose: log_warning(f"PowerShell stderr: {ps_proc.stderr.strip()}")
                        else:
                            if verbose: log_info("PowerShell not found, attempting 'setx' for PYTHONPATH.")
                            subprocess.run(['setx', 'PYTHONPATH', new_pythonpath_value], check=True)
                            log_success("Successfully requested update for User PYTHONPATH using 'setx'.")
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
                            f.write(f"# Added/Updated by modules/setup.py to include project modules\n")
                            f.write(f"# This file is (re)generated to ensure correctness.\n")
                            f.write(export_line)
                        log_success(f"PYTHONPATH configuration (re)generated in {pythonpath_config_file}")
                        
                        try:
                            source_cmd = f"source '{pythonpath_config_file.resolve()}' && echo $PYTHONPATH"
                            if verbose: log_info(f"Attempting to have Zsh sub-shell source: {source_cmd}")
                            result = subprocess.run(
                                ["zsh", "-c", source_cmd], timeout=5, 
                                check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore'
                            )
                            if verbose: log_success(f"Sourced {pythonpath_config_file} in a zsh sub-shell. New PYTHONPATH (in sub-shell): {result.stdout.strip()}")
                            if result.stderr.strip() and verbose: log_warning(f"Zsh source stderr: {result.stderr.strip()}")
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


def main_modules_setup(scripts_dir_arg: Path, dotfiles_dir_arg: Path, bin_dir_arg: Path, skip_reinstall_arg: bool, production_arg: bool, verbose_arg: bool):
    global _is_verbose_modules
    _is_verbose_modules = verbose_arg

    if not STANDARD_UI_LOADED_MODULES and log_info == _sui_log_info_fb:
        def _verbose_log_info_fb_updated(msg):
            if _is_verbose_modules: print(f"[INFO] {msg}")
        globals()['log_info'] = _verbose_log_info_fb_updated

    all_errors = []
    
    with section("Python Modules Installation"):
        current_modules_dir = scripts_dir_arg / "modules"
        install_errors = install_python_modules(current_modules_dir, skip_reinstall_arg, production_arg, verbose_arg)
        all_errors.extend(install_errors)

    ensure_pythonpath(scripts_dir_arg / "modules", dotfiles_dir_arg, verbose_arg)
    
    if not all_errors:
        log_success("Modules setup completed successfully.")
    else:
        log_error(f"Modules setup completed with {len(all_errors)} error(s):")
        for err in all_errors:
            log_error(f"  - {err}")
    
    if all_errors:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Python modules from the 'modules' directory and configure PYTHONPATH.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Base project scripts directory.")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Root directory of dotfiles.")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Target directory for binaries.")
    parser.add_argument("--skip-reinstall", action="store_true", help="Skip reinstallation if already installed correctly.")
    parser.add_argument("--production", action="store_true", help="Install modules in production mode.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed output.")
    
    args = parser.parse_args()
    
    main_modules_setup(
        args.scripts_dir,
        args.dotfiles_dir,
        args.bin_dir,
        args.skip_reinstall,
        args.production,
        args.verbose
    )
