# In scripts_setup/setup_utils.py

import os
import sys
import shutil
import subprocess
from pathlib import Path
import re # Imported re

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

# Basic print logging for setup_utils, as standard_ui might not be available
# or appropriate for this low-level utility module if it's used by standard_ui's own setup.
def _log_info(message: str, verbose: bool):
    if verbose: print(f"INFO: {message}")
def _log_success(message: str, verbose: bool):
    if verbose: print(f"{GREEN}✅ {message}{RESET}")
def _log_warning(message: str, verbose: bool):
    # Warnings should always be printed
    print(f"{YELLOW}⚠️ {message}{RESET}")
def _log_error(message: str): # Errors should always be printed
    print(f"{RED}❌ {message}{RESET}")


def create_symlink(src: Path, dest: Path, verbose: bool = True) -> bool:
    """
    Create a symbolic link from dest -> src if it doesn't exist or is incorrect.
    Returns True if a new symlink was created or an existing one was corrected,
    False if it already existed and was correct. Exits on error if a file exists at dest
    that is not a symlink, or if symlink creation fails for other reasons.
    """
    src = src.resolve() # Ensure src path is absolute for reliable comparison and linking

    if dest.exists():
        if dest.is_symlink():
            try:
                existing_target = dest.resolve()
                if existing_target == src:
                    _log_info(f"Symlink already exists and is correct: {dest} -> {existing_target}", verbose)
                    return False
                else:
                    _log_warning(f"Symlink {dest} exists but points to {existing_target} (expected {src}). Attempting to recreate.", verbose)
                    try:
                        dest.unlink() # Remove incorrect symlink
                    except OSError as e:
                        _log_error(f"Error: Could not remove incorrect symlink {dest}: {e}")
                        sys.exit(1)
            except OSError as e: # Can happen if the symlink target is problematic or on some OS
                _log_warning(f"Could not resolve existing symlink {dest} fully (may be broken or pointing to a non-existent relative path): {e}. Attempting to recreate.", verbose)
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
            # On Windows, target must be an absolute path for os.symlink if it's a directory.
            # For files, relative paths might work, but absolute is safer.
            # Python's pathlib.Path.symlink_to handles target_is_directory correctly if src is a dir.
            target_is_directory = src.is_dir()
            dest.symlink_to(src, target_is_directory=target_is_directory)
        else:
            dest.symlink_to(src)
        _log_success(f"Created symlink: {dest} -> {src}", verbose)
        return True
    except OSError as e:
        _log_error(f"Error creating symlink: {dest} -> {src}: {e}")
        if os.name == 'nt':
            _log_warning("On Windows, creating symlinks may require Developer Mode to be enabled or the script to be run with administrator privileges.", verbose)
        sys.exit(1)
    except Exception as e: # Catch any other unexpected errors
        _log_error(f"An unexpected error occurred creating symlink {dest} -> {src}: {e}")
        sys.exit(1)

def make_executable(script_path: Path, verbose: bool = True) -> None:
    """Ensure a script is executable (POSIX) or inform about Windows behavior."""
    if os.name == 'nt':
        _log_info(f"On Windows, executability of {script_path.name} is determined by file association and PATH. No explicit chmod needed/applied.", verbose)
        # For .py files, they need to be associated with python.exe
        # For .bat/.cmd/.exe, they are directly executable if in PATH.
    else: # POSIX
        try:
            # Set to rwxr-xr-x (0o755)
            # Or add execute permission: script_path.chmod(script_path.stat().st_mode | 0o111)
            script_path.chmod(0o755)
            _log_success(f"Set executable permission (0o755) for {script_path}", verbose)
        except Exception as e:
            _log_error(f"Could not set executable permission for {script_path}: {e}")
            # Depending on severity, you might sys.exit(1)

def process_symlinks(source_dir: Path, glob_pattern: str, bin_dir: Path,
                     verbose: bool = True, skip_names: list = None) -> (int, int):
    """
    Process files in source_dir matching glob_pattern:
      - For each file (unless its name is in skip_names), remove its extension (using .stem),
        make the source file executable (on POSIX), create a symlink in bin_dir.
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
        _log_error(f"Target bin directory '{bin_dir}' for symlinks does not exist or is not a directory. Symlink creation will fail.")
        # Consider creating it or exiting:
        # try:
        #     bin_dir.mkdir(parents=True, exist_ok=True)
        #     _log_info(f"Created bin directory: {bin_dir}", verbose)
        # except OSError as e:
        #     _log_error(f"Could not create bin directory {bin_dir}: {e}")
        #     sys.exit(1) # Or return (0,0) if you want to be less strict
        return 0,0 # Assuming main setup script handles bin_dir creation


    for file_path in source_dir.glob(glob_pattern):
        if file_path.is_file(): # Ensure it's a file, not a directory matching the pattern
            if file_path.name in skip_names:
                _log_info(f"Skipping {file_path.name} as per skip_names list.", verbose)
                continue

            target_name_in_bin = file_path.stem # Name in bin_dir without extension
            symlink_dest_path = bin_dir / target_name_in_bin

            # Make the original script executable first (primarily for POSIX)
            make_executable(file_path, verbose=verbose)
            
            # Create or update the symlink
            # create_symlink returns True if created/updated, False if already correct
            if create_symlink(file_path, symlink_dest_path, verbose=verbose):
                created_or_updated_count += 1
            else:
                existing_and_correct_count += 1
            
            # On POSIX, symlinks to executables are typically also made executable.
            # On Windows, this has no real effect for symlinks to .py files.
            if os.name != 'nt':
                 make_executable(symlink_dest_path, verbose=verbose) # Make the symlink itself executable

        elif verbose:
            _log_info(f"Skipping {file_path.name}, as it's not a file.", verbose)
            
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
                # Resolving a symlink checks if its target exists.
                # strict=True will raise FileNotFoundError if the target is missing.
                item.resolve(strict=True)
            except FileNotFoundError:
                broken_found = True
                target_path = os.readlink(item) # Get target path even if broken
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
            except OSError as e: # Other errors during resolve (e.g. permission issues)
                 _log_error(f"Error checking symlink {item}: {e}")


    if not broken_found:
        _log_info("No broken symlinks found.", verbose)

def install_dependencies(dependencies: list, verbose: bool = True): # Added verbose
    """Install dependencies using Conda first, then fallback to Pip."""
    if not dependencies:
        _log_success("No additional dependencies specified for installation.", verbose)
        return

    dependencies = sorted(list(set(dependencies))) # Ensure unique and sorted
    _log_info(f"Installing dependencies: {', '.join(dependencies)}", verbose)

    conda_path = shutil.which("conda")
    pip_path = sys.executable # Assumes pip is available in the current Python env

    remaining_dependencies = list(dependencies) # Make a copy to modify

    if conda_path:
        _log_info("Attempting Conda installation first...", verbose)
        # Constructing the command carefully
        conda_cmd = [conda_path, "install", "-y"] + remaining_dependencies
        if verbose:
             _log_info(f"Running Conda: {' '.join(conda_cmd)}", verbose)
        
        # Using subprocess.run for better control and error handling
        conda_result = subprocess.run(conda_cmd, capture_output=True, text=True, check=False)

        if conda_result.returncode == 0:
            _log_success(f"Conda successfully installed/updated: {', '.join(remaining_dependencies)}", verbose)
            if conda_result.stdout and verbose: print(f"Conda stdout:\n{conda_result.stdout}")
            if conda_result.stderr and verbose: print(f"Conda stderr:\n{conda_result.stderr}")
            remaining_dependencies = [] # All installed
        else:
            _log_warning(f"Conda command failed with return code {conda_result.returncode}.", verbose)
            if verbose:
                _log_info(f"Conda stdout:\n{conda_result.stdout}", verbose)
                _log_error(f"Conda stderr:\n{conda_result.stderr}")
            
            # Try to parse which packages failed if possible, though Conda's output can be complex.
            # A simpler approach: if conda failed, try all with pip.
            # For a more sophisticated approach, one might parse Conda's error messages.
            # For now, if Conda reports an error, we assume all listed deps might still need pip.
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
            # sys.exit(1) # Or handle error as appropriate

    _log_success("Dependency installation process finished.", verbose)
