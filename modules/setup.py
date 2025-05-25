#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from pathlib import Path

# Attempt to import standard_ui for logging.
try:
    from standard_ui.standard_ui import log_info, log_warning, log_error, log_success, section
except ImportError:
    # Basic fallback logging if standard_ui is not available
    _is_verbose_fb_modules = "--verbose" in sys.argv or "-v" in sys.argv # Basic check
    def log_info(msg): print(f"[INFO] {msg}") if _is_verbose_fb_modules else None
    def log_warning(msg): print(f"[WARNING] {msg}")
    def log_error(msg): print(f"[ERROR] {msg}")
    def log_success(msg): print(f"[SUCCESS] {msg}")
    class FallbackSectionModules:
        def __init__(self, title): self.title = title
        def __enter__(self): print(f"\n--- Section: {self.title} ---") if _is_verbose_fb_modules else None
        def __exit__(self,et,ev,tb): print(f"--- End Section: {self.title} ---\n") if _is_verbose_fb_modules else None
    section = FallbackSectionModules
    if _is_verbose_fb_modules : print("[WARNING] standard_ui not found in modules/setup.py. Using basic print for logging.")


# Constants for colored output (used if standard_ui fallback is active and doesn't color)
_GREEN_FB = "\033[92m"
_RED_FB = "\033[91m"
_RESET_FB = "\033[0m"

def get_module_install_mode(module_path: Path, verbose: bool = False) -> str | None:
    """Checks pip list for the module and determines if it's installed and in what mode."""
    module_name_to_check = module_path.name.lower().replace('_', '-')
    try:
        # Use absolute path to sys.executable to be certain
        pip_list_cmd = [sys.executable, "-m", "pip", "list", "--format=freeze"]
        if verbose: log_info(f"Running: {' '.join(pip_list_cmd)}")
        result = subprocess.run(
            pip_list_cmd,
            capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore'
        )
        installed_packages = result.stdout.splitlines()

        for line in installed_packages:
            name_part = ""
            is_editable = False
            
            if " @ " in line: 
                name_part = line.split(" @ ")[0].strip()
                is_editable = True
            elif "==" in line: 
                name_part = line.split("==")[0].strip()
            
            normalized_installed_name = name_part.lower().replace('_', '-')
            if normalized_installed_name == module_name_to_check:
                return "editable" if is_editable else "normal"
        return None
    except subprocess.CalledProcessError as e:
        log_warning(f"Could not query pip for installed modules: {e}")
        if verbose: log_error(f"Pip list stderr: {e.stderr}")
        return None
    except FileNotFoundError: # sys.executable might not be found in some edge cases
        log_error(f"Python executable '{sys.executable}' not found for pip list. Cannot determine module status.")
        return None


def install_python_modules(modules_dir: Path, skip_reinstall: bool, production: bool, verbose: bool) -> list:
    """Installs Python modules found in subdirectories of modules_dir."""
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

        has_setup_py = (potential_module_path / "setup.py").exists()
        has_pyproject_toml = (potential_module_path / "pyproject.toml").exists()

        if not has_setup_py and not has_pyproject_toml:
            if verbose: log_info(f"Skipping '{potential_module_path.name}', no setup.py or pyproject.toml found.")
            continue
        
        # Avoid trying to install 'setup.py' if it's a file directly in modules_dir
        if potential_module_path.name == "setup.py" and potential_module_path.is_file():
            if verbose: log_info(f"Skipping '{potential_module_path.name}' as it's likely this script itself or a non-package file.")
            continue


        found_module_to_install = True
        module_name = potential_module_path.name
        # Use a more descriptive section title for each module being processed
        with section(f"Module: {module_name}"):
            log_info(f"Processing module: {module_name}")
            install_mode_desired = "normal" if production else "editable"
            
            if skip_reinstall:
                current_install_mode = get_module_install_mode(potential_module_path, verbose)
                if current_install_mode:
                    log_success(f"Module '{module_name}' is already installed ({current_install_mode}).")
                    if current_install_mode == install_mode_desired:
                        log_info(f"Desired mode ('{install_mode_desired}') matches. Skipping re-installation.")
                        continue
                    else:
                        log_info(f"Desired mode is '{install_mode_desired}', but installed as '{current_install_mode}'. Proceeding with re-installation.")
                else:
                    log_info(f"Module '{module_name}' not found or status unknown. Proceeding with installation.")

            install_cmd = [sys.executable, "-m", "pip", "install"]
            if not production:
                install_cmd.append("-e")
            
            resolved_module_path = str(potential_module_path.resolve())
            install_cmd.append(resolved_module_path)

            mode_text = "production (non-editable)" if production else "development (editable)"
            log_info(f"Installing '{module_name}' in {mode_text} mode from {resolved_module_path}...")
            
            try:
                # In verbose mode, let output stream. Otherwise, capture for concise success/failure.
                if verbose:
                    # Stream output directly for verbose mode
                    process = subprocess.Popen(install_cmd, text=True, encoding='utf-8', errors='ignore',
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    stdout, stderr = process.communicate()
                    if process.returncode == 0:
                        log_success(f"Successfully installed/updated '{module_name}'.")
                        if stdout.strip(): log_info(f"Install output for {module_name}:\n{stdout.strip()}")
                        if stderr.strip(): log_warning(f"Install stderr for {module_name} (may be informational):\n{stderr.strip()}")
                    else:
                        raise subprocess.CalledProcessError(process.returncode, install_cmd, output=stdout, stderr=stderr)
                else:
                    # Capture output for non-verbose, print simple status
                    sys.stdout.write(f"Installing: {module_name} {mode_text}... ")
                    sys.stdout.flush()
                    result = subprocess.run(install_cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    # Using _GREEN_FB and _RED_FB for fallback compatibility
                    sys.stdout.write(f"{_GREEN_FB}✅{_RESET_FB}\n")
                    sys.stdout.flush()
                    if result.stdout.strip(): log_info(f"Install output for {module_name}:\n{result.stdout.strip()}")
                    if result.stderr.strip(): log_warning(f"Install stderr for {module_name} (may be informational):\n{result.stderr.strip()}")

            except subprocess.CalledProcessError as e:
                if not verbose: sys.stdout.write(f"{_RED_FB}❌{_RESET_FB}\n"); sys.stdout.flush() # Finish the non-verbose line
                log_error(f"Error installing module '{module_name}'.")
                log_error(f"Command: {' '.join(e.cmd)}")
                # e.output is stdout, e.stderr is stderr for CalledProcessError
                if e.output: log_error(f"Stdout:\n{e.output}")
                if e.stderr: log_error(f"Stderr:\n{e.stderr}")
                errors_encountered.append(f"Installation of {module_name} from {resolved_module_path}")
            except Exception as e: # Catch other unexpected errors like FileNotFoundError for pip
                if not verbose: sys.stdout.write(f"{_RED_FB}❌{_RESET_FB}\n"); sys.stdout.flush()
                log_error(f"An unexpected error occurred while trying to install '{module_name}': {type(e).__name__}: {e}")
                errors_encountered.append(f"Unexpected error installing {module_name} from {resolved_module_path}")

    if not found_module_to_install:
        log_info("No installable Python modules found in the modules directory.")
    return errors_encountered

def ensure_pythonpath(modules_dir: Path, dotfiles_dir: Path, verbose: bool = False):
    """Configures PYTHONPATH to include the modules_dir."""
    modules_dir_abs = str(modules_dir.resolve())
    path_separator = os.pathsep

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
                        match = re.search(regex_pattern, line.strip(), re.IGNORECASE) # Requires import re
                        if match: current_user_pythonpath = match.group(1).strip(); break
                
                if verbose: log_info(f"Current User PYTHONPATH from registry: '{current_user_pythonpath}'")

                current_paths_list = [p for p in current_user_pythonpath.split(path_separator) if p]
                if modules_dir_abs in current_paths_list:
                    log_success(f"{modules_dir_abs} is already in the User PYTHONPATH.")
                else:
                    log_info(f"Adding {modules_dir_abs} to User PYTHONPATH.")
                    new_pythonpath_list = current_paths_list + [modules_dir_abs]
                    new_pythonpath_value = path_separator.join(list(dict.fromkeys(new_pythonpath_list))) # Deduplicate

                    is_pwsh_available = bool(subprocess.run(["where", "pwsh"], capture_output=True, shell=True).stdout or \
                                          subprocess.run(["where", "powershell"], capture_output=True, shell=True).stdout)
                    if is_pwsh_available:
                        if verbose: log_info("Using PowerShell to update User PYTHONPATH.")
                        ps_command_parts = [
                            '$envName = "User";', '$varName = "PYTHONPATH";', f'$valueToAdd = "{modules_dir_abs}";',
                            '$currentValue = [System.Environment]::GetEnvironmentVariable($varName, $envName);',
                            '$elements = @($currentValue -split [System.IO.Path]::PathSeparator | Where-Object { $_ -ne "" });', # Filter empty strings
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
            except Exception as e: # Catch FileNotFoundError for reg/setx, CalledProcessError, and others
                log_error(f"Failed to update User PYTHONPATH: {type(e).__name__}: {e}")
                log_info(f"Please add '{modules_dir_abs}' to your User PYTHONPATH environment variable manually.")
    else: # POSIX-like (Zsh for now)
        with section("Zsh PYTHONPATH Update"):
            pythonpath_config_file = dotfiles_dir / "dynamic/setup_modules_pythonpath.zsh"
            pythonpath_config_file.parent.mkdir(parents=True, exist_ok=True)
            export_line = f'export PYTHONPATH="{modules_dir_abs}{path_separator}$PYTHONPATH"\n'
            
            current_config_content = ""
            if pythonpath_config_file.exists():
                try: current_config_content = pythonpath_config_file.read_text(encoding="utf-8")
                except Exception as e_read: log_warning(f"Could not read {pythonpath_config_file}: {e_read}")

            if export_line in current_config_content:
                log_success(f"PYTHONPATH configuration for '{modules_dir_abs}' already exists in {pythonpath_config_file}")
            else:
                try:
                    with open(pythonpath_config_file, "w", encoding="utf-8") as f:
                        f.write(f"# Added by modules/setup.py to include project modules\n{export_line}")
                    log_success(f"PYTHONPATH configuration updated in {pythonpath_config_file}")
                    
                    # Guarded Zsh sourcing
                    try:
                        source_cmd = f"source '{pythonpath_config_file}'" 
                        if verbose: log_info(f"Attempting to have Zsh sub-shell source: {source_cmd}")
                        result = subprocess.run(
                            ["zsh", "-c", source_cmd], timeout=5, # Add timeout
                            check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore'
                        )
                        log_success(f"Sourced {pythonpath_config_file} in a zsh sub-shell.")
                        if result.stdout.strip() and verbose: log_info(f"Zsh source stdout: {result.stdout.strip()}")
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

def main(scripts_dir_arg: Path, dotfiles_dir_arg: Path, bin_dir_arg: Path, skip_reinstall_arg: bool, production_arg: bool, verbose_arg: bool):
    """Main setup for modules: installs them and configures PYTHONPATH."""
    # Update global _is_verbose_fb_modules if standard_ui was not loaded
    global _is_verbose_fb_modules
    if 'FallbackSectionModules' in globals() and section == FallbackSectionModules: # Check if using fallback
        _is_verbose_fb_modules = verbose_arg

    all_errors = []
    with section("Python Modules Installation"):
        # scripts_dir_arg is the main project's scripts/ directory.
        # modules are in a subdirectory of this, e.g., scripts/modules/
        current_modules_dir = scripts_dir_arg / "modules" 
        install_errors = install_python_modules(current_modules_dir, skip_reinstall_arg, production_arg, verbose_arg)
        all_errors.extend(install_errors)

    with section("PYTHONPATH Configuration"):
        current_modules_dir = scripts_dir_arg / "modules" 
        ensure_pythonpath(current_modules_dir, dotfiles_dir_arg, verbose_arg)
    
    if not all_errors:
        log_success("Modules setup completed successfully.")
    else:
        log_error(f"Modules setup completed with {len(all_errors)} error(s): {', '.join(all_errors)}")
    
    # This script is run as a subprocess, so its exit code matters.
    if all_errors:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Python modules from the 'modules' directory and configure PYTHONPATH.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Base project scripts directory (e.g., where 'modules/' subdirectory is).")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Root directory of dotfiles for shell configurations.")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Target directory for binaries (passed for consistency).")
    parser.add_argument("--skip-reinstall", action="store_true", help="Skip reinstallation if already installed correctly.")
    parser.add_argument("--production", action="store_true", help="Install modules in production mode (no '-e').")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed output.")
    
    args = parser.parse_args()
    
    # Import re here if ensure_pythonpath uses it and it's not already top-level
    import re 

    main(
        args.scripts_dir,
        args.dotfiles_dir,
        args.bin_dir,
        args.skip_reinstall,
        args.production,
        args.verbose
    )
