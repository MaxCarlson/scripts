#!/usr/bin/env python3

"""
Setup Script for Managing Python and Shell Scripts with Symlinks & Dependency Installation

This script automates the setup of Python and shell scripts by:
- Creating a `bin/` directory for executables if it doesn't exist.
- Symlinking Python scripts from `~/scripts/pyscripts/` to `bin/` for easy execution.
- Symlinking shell scripts (`.sh` and `.zsh`) from `~/scripts/shell-scripts/` to `bin/`.
- Making all linked scripts executable.
- Installing Python modules from `~/scripts/modules/`, supporting both development (`-e`) and production mode.
- Scanning all Python scripts in `pyscripts/` and `modules/` to determine required dependencies.
- Installing missing dependencies with Conda (if available), falling back to Pip.
- Ensuring the `bin/` directory is permanently added to the user's `PATH`, supporting PowerShell (Windows) and Zsh (Linux/macOS).

---

Features:
1. **Script and Module Management**
   - Symlink all Python scripts in `~/scripts/pyscripts/` to `bin/` for direct execution.
   - Symlink all shell scripts (`.sh`, `.zsh`) in `~/scripts/shell-scripts/` to `bin/`.
   - Ensures all linked scripts are executable for direct execution in terminals.
   - Supports custom bin directories via `--bin-dir`.

2. **Python Module Installation**
   - Installs all modules found in `~/scripts/modules/` using `pip`.
   - Supports development mode (`-e`) for local module installation.
   - Production mode (`-p`) installs modules without `-e`, making them behave like normal installed packages.
   - Reinstallation mode (`-r`) forces reinstallation of all modules.

3. **Dependency Management**
   - Scans Python scripts to detect required imported packages.
   - Installs missing dependencies using Conda, falling back to Pip if Conda is unavailable.
   - Ensures all required libraries are installed for Python scripts.

4. **Environment Setup**
   - Adds `bin/` to the `PATH` environment variable for persistent access.
   - Supports PowerShell (`pwsh`) by modifying Windows environment variables.
   - Supports Zsh (`Linux/macOS`) by modifying `dynamic.zsh`.

---

Usage Examples:
- **Basic Setup**  
  Run the setup script to create symlinks, install modules, and ensure dependencies are installed:
  `python setup.py`

- **Install Python Modules in Production Mode**  
  Installs modules without `-e` (editable mode), making them behave like normal installed packages:
  `python setup.py -p`

- **Reinstall All Python Modules**  
  Forces reinstallation of modules, even if they are already installed:
  `python setup.py -r`

- **Use a Custom `bin/` Directory**  
  Places symlinks in `~/my_custom_bin` instead of the default `~/scripts/bin`:
  `python setup.py --bin-dir ~/my_custom_bin`

---

Dependencies:
- Python 3.6+
- Conda (optional, for optimized package installation)
"""

import os
import re
import sys
import shutil
import argparse
import subprocess
from pathlib import Path
from itertools import chain

# Default directories
SCRIPTS_DIR = Path.home() / "scripts"
PY_SCRIPTS_DIR = SCRIPTS_DIR / "pyscripts"
MODULES_DIR = SCRIPTS_DIR / "modules"
SHELL_SCRIPTS_DIR = SCRIPTS_DIR / "shell-scripts"
DEFAULT_BIN_DIR = Path.home() / "scripts/bin"

def make_executable(file_path):
    """Ensure a file is executable."""
    file_path.chmod(file_path.stat().st_mode | 0o111)

def create_symlink(src, dest):
    """Create a symbolic link if it does not exist."""
    if dest.exists() or dest.is_symlink():
        print(f"🔹 Symlink already exists: {dest}")
        return False
    dest.symlink_to(src)
    print(f"✅ Created symlink: {dest} -> {src}")
    return True

def setup_python_scripts(bin_dir):
    """Create symlinks for Python scripts in bin/ and make them executable."""
    if not PY_SCRIPTS_DIR.exists():
        print(f"⚠️ No 'pyscripts' directory found at {PY_SCRIPTS_DIR}. Skipping.")
        return

    for script in PY_SCRIPTS_DIR.glob("*.py"):
        script_name = script.stem  # Remove `.py`
        link_path = bin_dir / script_name

        if create_symlink(script, link_path):
            make_executable(script)
            make_executable(link_path)

def setup_shell_scripts(bin_dir):
    """Create symlinks for shell scripts in bin/ and make them executable."""
    if not SHELL_SCRIPTS_DIR.exists():
        print(f"⚠️ No 'shell-scripts' directory found at {SHELL_SCRIPTS_DIR}. Skipping.")
        return

    for script in chain(SHELL_SCRIPTS_DIR.glob("*.sh"), SHELL_SCRIPTS_DIR.glob("*.zsh")):
        script_name = script.stem  # Remove extension
        link_path = bin_dir / script_name

        if create_symlink(script, link_path):
            make_executable(script)
            make_executable(link_path)

def is_module_installed(module_path):
    """Check if a module is already installed."""
    module_name = module_path.name
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", module_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception:
        return False

def install_python_modules(production=False, reinstall=False):
    """Install all modules in 'modules/'."""
    if not MODULES_DIR.exists():
        print(f"⚠️ No 'modules' directory found at {MODULES_DIR}. Skipping.")
        return

    for module_dir in MODULES_DIR.iterdir():
        if not module_dir.is_dir() or not (module_dir / "setup.py").exists():
            continue

        install_cmd = [sys.executable, "-m", "pip", "install"]
        if not production:
            install_cmd.append("-e")
        install_cmd.append(str(module_dir))

        if not reinstall and is_module_installed(module_dir):
            print(f"🔹 Module already installed: {module_dir.name}")
            continue

        print(f"🚀 Installing: {module_dir.name} {'(production mode)' if production else '(development mode)'}")
        subprocess.run(install_cmd, check=True)


def extract_python_imports(file_path):
    """Extract import statements from a Python file."""
    imports = set()
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            match = re.match(r"^\s*(?:import|from) (\S+)", line)
            if match:
                imports.add(match.group(1).split(".")[0])  # Extract top-level package
    return imports

def get_required_python_packages(scripts_dir, modules_dir):
    """Get a list of required packages by scanning Python files."""
    required_packages = set()
    
    for directory in [scripts_dir, modules_dir]:
        if directory.exists():
            for py_file in directory.rglob("*.py"):
                required_packages.update(extract_python_imports(py_file))

    # Filter out standard library modules (optional)
    try:
        std_libs = set(subprocess.run([sys.executable, "-c", "help('modules')"], capture_output=True, text=True).stdout.split())
        required_packages -= std_libs
    except:
        pass  # Fallback: Install everything if stdlibs cannot be determined

    return required_packages

def install_python_packages(packages):
    """Install Python packages, prioritizing Conda, with a fallback to Pip."""
    if not packages:
        print("✅ No additional dependencies needed.")
        return

    # Remove empty package names
    packages = sorted({pkg.strip() for pkg in packages if pkg.strip()})

    if not packages:
        print("✅ No valid packages found for installation.")
        return

    print(f"🔍 Installing dependencies: {', '.join(packages)}")

    # Check if conda exists
    conda_installed = shutil.which("conda") is not None

    if conda_installed:
        print("🚀 Attempting to install with Conda...")
        conda_result = subprocess.run(["conda", "install", "-y"] + packages, capture_output=True, text=True)
        
        # Find packages that failed in conda
        failed_packages = set()
        for line in conda_result.stderr.split("\n"):
            match = re.search(r"PackagesNotFoundError: ([\w\s,]+)", line)
            if match:
                failed_packages.update(match.group(1).split(", "))

        packages = {pkg.strip() for pkg in failed_packages if pkg.strip()}  # Filter empty packages

    if packages:
        print(f"⚠️ Some packages failed with Conda. Installing with Pip: {', '.join(packages)}")
        subprocess.run([sys.executable, "-m", "pip", "install"] + list(packages))

    print("✅ All dependencies installed.")


import subprocess
import os
from pathlib import Path

def ensure_bin_in_path(bin_dir):
    """Ensure the bin directory is in PATH for PowerShell (pwsh) and Linux (zsh), and set scripts as executable."""
    bin_path = str(bin_dir.resolve())

    # Detect system type
    is_windows = os.name == "nt"
    shell = os.environ.get("SHELL", "").split("/")[-1] if "SHELL" in os.environ else ""
    is_pwsh = shell == "pwsh" or is_windows  # Detect PowerShell

    # Ensure scripts are executable (only for Linux/macOS)
    if not is_pwsh:  # Skip chmod on Windows
        for script in bin_dir.iterdir():
            if script.is_symlink() or script.suffix in {".sh", ".py", ".zsh"}:
                try:
                    script.chmod(script.stat().st_mode | 0o111)  # Add execute permission
                    print(f"✅ Ensured executable: {script}")
                except Exception as e:
                    print(f"❌ Error setting executable permission for {script}: {e}")

    # Check if bin directory is already in PATH
    if bin_path in os.environ["PATH"]:
        print(f"✅ {bin_path} is already in PATH.")
        return

    print(f"🔄 Adding {bin_path} to PATH...")

    dotfiles_path = os.environ.get("DOTFILES", str(Path.home() / "dotfiles"))
    dynamic_zsh_path = Path(dotfiles_path) / "dynamic.zsh"

    if is_pwsh:
        try:
            # PowerShell: Permanently add to PATH
            subprocess.run([
                "pwsh", "-Command",
                f'[System.Environment]::SetEnvironmentVariable("Path", '
                f'[System.Environment]::GetEnvironmentVariable("Path", "User") + ";{bin_path}", "User")'
            ], check=True)
            print(f"✅ Added {bin_path} permanently to PowerShell (pwsh). Restart pwsh for changes to take effect.")
        except Exception as e:
            print(f"❌ Error updating PATH in PowerShell: {e}")
    else:
        try:
            # Linux/macOS (Zsh): Append to $DOTFILES/dynamic.zsh
            with open(dynamic_zsh_path, "a") as f:
                f.write(f'\nexport PATH="{bin_path}:$PATH"\n')

            print(f"✅ Added {bin_path} permanently to {dynamic_zsh_path}. Restart your shell or run `source {dynamic_zsh_path}`.")
        except Exception as e:
            print(f"❌ Error updating PATH in Zsh: {e}")

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Setup and manage Python and shell scripts with symlinks, install Python modules, "
            "and ensure required dependencies are installed."
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "-p", "--production",
        action="store_true",
        help=(
            "Install Python modules in production mode (without `-e`).\n"
            "This makes modules behave like normal installed packages instead of being linked for development."
        ),
    )

    parser.add_argument(
        "-r", "--reinstall",
        action="store_true",
        help=(
            "Reinstall all Python modules, even if they are already installed.\n"
            "Useful if dependencies have changed or modules need to be refreshed."
        ),
    )

    parser.add_argument(
        "--bin-dir",
        type=Path,
        default=DEFAULT_BIN_DIR,
        help=(
            "Specify a custom bin directory where symlinks for scripts will be created.\n"
            "Default: ~/scripts/bin\n"
            "Example: `python setup.py --bin-dir ~/my_custom_bin`"
        ),
    )

    args = parser.parse_args()
    bin_dir = args.bin_dir

    print("\n=== Setup Script: Python & Shell Script Management ===\n")
    print("This script performs the following actions:")
    print("1. Creates a `bin/` directory for executables if it doesn't exist.")
    print("2. Symlinks Python scripts from `~/scripts/pyscripts/` to the bin directory.")
    print("3. Symlinks shell scripts (`.sh` and `.zsh`) from `~/scripts/shell-scripts/` to bin.")
    print("4. Makes all linked scripts executable.")
    print("5. Installs Python modules from `~/scripts/modules/`, supporting both development (`-e`) and production mode.")
    print("6. Scans Python scripts to detect and install missing dependencies using Conda/Pip.")
    print("7. Ensures `bin/` is permanently added to PATH for PowerShell and Zsh.\n")

    print(f"🔄 Setting up Python scripts in {bin_dir} ...")
    setup_python_scripts(bin_dir)

    print(f"🔄 Setting up shell scripts in {bin_dir} ...")
    setup_shell_scripts(bin_dir)

    print(f"🔄 Installing Python modules from {MODULES_DIR} ...")
    install_python_modules(production=args.production, reinstall=args.reinstall)

    print(f"🔄 Parsing Python files to find required packages ...")
    packages = get_required_python_packages(PY_SCRIPTS_DIR, MODULES_DIR)

    print(f"🔄 Installing Python packages...")
    install_python_packages(packages)

    print(f"🔄 Ensuring bin directory {bin_dir} is on PATH..")
    ensure_bin_in_path(bin_dir)

    print("✅ Setup complete!\n")
    print("Usage Examples:")
    print("  - Run the setup script: `python setup.py`")
    print("  - Install Python modules in production mode: `python setup.py -p`")
    print("  - Reinstall all Python modules: `python setup.py -r`")
    print("  - Use a custom bin directory: `python setup.py --bin-dir ~/my_custom_bin`\n")

if __name__ == "__main__":
    main()
