import os
import sys
import shutil
import subprocess
from pathlib import Path
import re

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def _log_info(message: str, verbose: bool):
    if verbose: print(f"INFO: {message}")
def _log_success(message: str, verbose: bool):
    if verbose: print(f"{GREEN}✅ {message}{RESET}")
def _log_warning(message: str, verbose: bool):
    print(f"{YELLOW}⚠️ {message}{RESET}")
def _log_error(message: str):
    print(f"{RED}❌ {message}{RESET}")

def _write_text_if_changed(path: Path, content: str, verbose: bool, crlf: bool = False) -> bool:
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                _log_info(f"No change for {path.name}", verbose)
                return False
        except Exception:
            pass
    newline = "\r\n" if crlf else "\n"
    path.write_text(content, encoding="utf-8", newline=newline)
    _log_success(f"Wrote {path}", verbose)
    return True

def create_symlink(src: Path, dest: Path, verbose: bool = True) -> bool:
    """
    Create a symbolic link from dest -> src if it doesn't exist or is incorrect.
    Returns True if a new symlink was created or an existing one was corrected,
    False if it already existed and was correct. Exits on error if a file exists at dest
    that is not a symlink, or if symlink creation fails for other reasons.
    """
    src = src.resolve()

    if dest.exists():
        if dest.is_symlink():
            try:
                existing_target = dest.resolve()
                if existing_target == src:
                    _log_info(f"Symlink already exists and is correct: {dest} -> {existing_target}", verbose)
                    return False
                else:
                    _log_warning(f"Symlink {dest} exists but points to {existing_target} (expected {src}). Recreating.", verbose)
                    try:
                        dest.unlink()
                    except OSError as e:
                        _log_error(f"Error: Could not remove incorrect symlink {dest}: {e}")
                        sys.exit(1)
            except OSError as e:
                _log_warning(f"Could not resolve existing symlink {dest}: {e}. Recreating.", verbose)
                try:
                    dest.unlink()
                except OSError as e_unlink:
                    _log_error(f"Error: Could not remove problematic symlink {dest}: {e_unlink}")
                    sys.exit(1)
        else:
            _log_error(f"Error: A file/directory exists at {dest} but is not a symlink.")
            _log_error("Please remove it manually and rerun the setup.")
            sys.exit(1)
    
    _log_info(f"Creating symlink: {dest} -> {src}", verbose)
    try:
        if os.name == 'nt':
            target_is_directory = src.is_dir()
            dest.symlink_to(src, target_is_directory=target_is_directory)
        else:
            dest.symlink_to(src)
        _log_success(f"Created symlink: {dest} -> {src}", verbose)
        return True
    except OSError as e:
        _log_error(f"Error creating symlink: {dest} -> {src}: {e}")
        if os.name == 'nt':
            _log_warning("On Windows, symlink creation may require Developer Mode or admin privileges.", verbose)
        sys.exit(1)
    except Exception as e:
        _log_error(f"An unexpected error occurred creating symlink {dest} -> {src}: {e}")
        sys.exit(1)

def _create_windows_cmd_wrapper(wrapper_path: Path, target_script: Path, verbose: bool):
    """
    Create/refresh a .cmd wrapper that invokes the target Python script.
    Order of interpreter preference:
      1) The exact Python used to run setup (sys.executable) if it exists
      2) %CONDA_PREFIX%\\python.exe if a conda/mamba env is active
      3) %MAMBA_ROOT_PREFIX%\\python.exe (base) if defined
      4) python.exe found on PATH
      5) py.exe -3 (Windows launcher) LAST, to avoid broken conda 'py' shims
    """
    py_abs = sys.executable.replace("/", "\\")
    script_abs = str(target_script.resolve()).replace("/", "\\")
    content = (
        "@echo off\r\n"
        "setlocal\r\n"
        f"set \"_PY_ABS={py_abs}\"\r\n"
        f"set \"_SCRIPT={script_abs}\"\r\n"
        "if exist \"%_PY_ABS%\" goto run\r\n"
        "if defined CONDA_PREFIX (\r\n"
        "  if exist \"%CONDA_PREFIX%\\python.exe\" set \"_PY_ABS=%CONDA_PREFIX%\\python.exe\"\r\n"
        ")\r\n"
        "if exist \"%_PY_ABS%\" goto run\r\n"
        "if defined MAMBA_ROOT_PREFIX (\r\n"
        "  if exist \"%MAMBA_ROOT_PREFIX%\\python.exe\" set \"_PY_ABS=%MAMBA_ROOT_PREFIX%\\python.exe\"\r\n"
        ")\r\n"
        "if exist \"%_PY_ABS%\" goto run\r\n"
        "for %%I in (python.exe) do if exist \"%%~$PATH:I\" set \"_PY_ABS=%%~$PATH:I\"\r\n"
        "if exist \"%_PY_ABS%\" goto run\r\n"
        "for %%I in (py.exe) do if exist \"%%~$PATH:I\" set \"_PY_LAUNCH=%%~$PATH:I\"\r\n"
        "if defined _PY_LAUNCH \"%_PY_LAUNCH%\" -3 \"%_SCRIPT%\" %* & goto :eof\r\n"
        "echo Python interpreter not found. Ensure Python is installed and on PATH.\r\n"
        "exit /b 9009\r\n"
        ":run\r\n"
        "\"%_PY_ABS%\" \"%_SCRIPT%\" %*\r\n"
    )
    _write_text_if_changed(wrapper_path, content, verbose, crlf=True)

def make_executable(script_path: Path, verbose: bool = True) -> None:
    """Ensure a script is executable (POSIX) or inform about Windows behavior."""
    if os.name == 'nt':
        _log_info(f"Windows: executability of {script_path.name} is via PATHEXT/associations or wrappers; no chmod.", verbose)
    else:
        try:
            script_path.chmod(0o755)
            _log_success(f"Set executable permission (0o755) for {script_path}", verbose)
        except Exception as e:
            _log_error(f"Could not set executable permission for {script_path}: {e}")

def process_symlinks(source_dir: Path, glob_pattern: str, bin_dir: Path,
                     verbose: bool = True, skip_names: list = None) -> (int, int):
    """
    Process files in source_dir matching glob_pattern:
      - For each file (unless its name is in skip_names), remove its extension (using .stem),
        make the source file executable (on POSIX), create a symlink in bin_dir.
      - On Windows, also create a .cmd wrapper alongside the symlink so commands run by name.
    Returns a tuple (created_or_updated_count, existing_and_correct_count).
    """
    if skip_names is None:
        skip_names = []
    
    created_or_updated_count = 0
    existing_and_correct_count = 0

    if not source_dir.exists() or not source_dir.is_dir():
        _log_warning(f"Source directory '{source_dir}' for symlinks does not exist or is not a directory. Skipping.", verbose)
        return 0, 0
        
    if not bin_dir.exists() or not bin_dir.is_dir():
        _log_error(f"Target bin directory '{bin_dir}' does not exist or is not a directory.")
        return 0, 0

    for file_path in source_dir.glob(glob_pattern):
        if not file_path.is_file():
            if verbose:
                _log_info(f"Skipping {file_path.name}, not a file.", verbose)
            continue

        if file_path.name in skip_names:
            _log_info(f"Skipping {file_path.name} as per skip_names list.", verbose)
            continue

        target_name_in_bin = file_path.stem
        symlink_dest_path = bin_dir / target_name_in_bin

        # Ensure original is executable first (primarily POSIX)
        make_executable(file_path, verbose=verbose)
            
        # Symlink create/update
        if create_symlink(file_path, symlink_dest_path, verbose=verbose):
            created_or_updated_count += 1
        else:
            existing_and_correct_count += 1

        # Windows: create/refresh .cmd wrapper next to the symlink
        if os.name == 'nt':
            wrapper_path = symlink_dest_path.with_suffix(".cmd")
            _create_windows_cmd_wrapper(wrapper_path, file_path.resolve(), verbose=verbose)

        # POSIX: set the symlink itself executable (nice-to-have)
        if os.name != 'nt':
            make_executable(symlink_dest_path, verbose=verbose)

    return created_or_updated_count, existing_and_correct_count

def validate_symlinks(bin_dir: Path, verbose: bool = True):
    """Check for broken symlinks in bin_dir and prompt for removal."""
    if not bin_dir.is_dir():
        _log_warning(f"Bin directory {bin_dir} does not exist. Skipping symlink validation.", verbose)
        return

    auto_delete_all = False
    broken_found = False

    for item in bin_dir.iterdir():
        if item.is_symlink():
            try:
                item.resolve(strict=True)
            except FileNotFoundError:
                broken_found = True
                target_path = os.readlink(item)
                _log_warning(f"Broken symlink found: {item} -> {target_path} (Target does not exist)", verbose)

                if not auto_delete_all:
                    user_choice = input(f"❓ Delete this broken symlink '{item.name}'? (y/n/A for All) ").strip().lower()
                    if user_choice == "a":
                        auto_delete_all = True
                    elif user_choice != "y":
                        _log_info(f"Skipping deletion of broken symlink: {item}", verbose)
                        continue
                try:
                    item.unlink()
                    _log_success(f"Deleted broken symlink: {item}", verbose)
                except OSError as e:
                    _log_error(f"Failed to delete broken symlink {item}: {e}")
            except OSError as e:
                 _log_error(f"Error checking symlink {item}: {e}")

    if not broken_found:
        _log_info("No broken symlinks found.", verbose)

def install_dependencies(dependencies: list, verbose: bool = True):
    """Install dependencies using Conda first, then fallback to Pip."""
    if not dependencies:
        _log_success("No additional dependencies specified for installation.", verbose)
        return

    dependencies = sorted(list(set(dependencies)))
    _log_info(f"Installing dependencies: {', '.join(dependencies)}", verbose)

    conda_path = shutil.which("conda")
    pip_path = sys.executable

    remaining_dependencies = list(dependencies)

    if conda_path:
        _log_info("Attempting Conda installation first...", verbose)
        conda_cmd = [conda_path, "install", "-y"] + remaining_dependencies
        if verbose:
             _log_info(f"Running Conda: {' '.join(conda_cmd)}", verbose)
        conda_result = subprocess.run(conda_cmd, capture_output=True, text=True, check=False)

        if conda_result.returncode == 0:
            _log_success(f"Conda successfully installed/updated: {', '.join(remaining_dependencies)}", verbose)
            if conda_result.stdout and verbose: print(f"Conda stdout:\n{conda_result.stdout}")
            if conda_result.stderr and verbose: print(f"Conda stderr:\n{conda_result.stderr}")
            remaining_dependencies = []
        else:
            _log_warning(f"Conda command failed with return code {conda_result.returncode}.", verbose)
            if verbose:
                _log_info(f"Conda stdout:\n{conda_result.stdout}", verbose)
                _log_error(f"Conda stderr:\n{conda_result.stderr}")
            _log_info("Some packages might not have been installed by Conda. Will try remaining/all with Pip.", verbose)

    if remaining_dependencies:
        _log_info(f"Attempting Pip installation for: {', '.join(remaining_dependencies)}", verbose)
        pip_cmd = [pip_path, "-m", "pip", "install"] + remaining_dependencies
        if verbose:
            _log_info(f"Running Pip: {' '.join(pip_cmd)}", verbose)

        pip_result = subprocess.run(pip_cmd, capture_output=True, text=True, check=False)

        if pip_result.returncode == 0:
            _log_success(f"Pip successfully installed/updated: {', '.join(remaining_dependencies)}", verbose)
            if pip_result.stdout and verbose: print(f"Pip stdout:\n{pip_result.stdout}")
            if pip_result.stderr and verbose: print(f"Pip stderr:\n{pip_result.stderr}")
        else:
            _log_error(f"Pip command failed with return code {pip_result.returncode}.")
            if verbose:
                _log_info(f"Pip stdout:\n{pip_result.stdout}", verbose)
            _log_error(f"Pip stderr:\n{pip_result.stderr}")
            _log_error(f"Failed to install some dependencies with Pip: {', '.join(remaining_dependencies)}")

    _log_success("Dependency installation process finished.", verbose)

