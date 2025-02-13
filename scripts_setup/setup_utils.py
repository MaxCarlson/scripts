# In scripts_setup/setup_utils.py

import os
import sys
import shutil
import subprocess
from pathlib import Path

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def create_symlink(src: Path, dest: Path, verbose: bool = True) -> bool:
    """
    Create a symbolic link from dest -> src if it doesn't exist.
    Returns True if a new symlink was created, False if it already existed.
    Exits on error.
    """
    if dest.exists():
        if dest.is_symlink():
            existing_target = dest.resolve()
            if existing_target == src:
                if verbose:
                    print(f"🔹 Symlink already exists: {dest} -> {existing_target}")
                return False
            else:
                if verbose:
                    print(f"\n{RED}❌ Error: Symlink {dest} already exists but points to {existing_target}, not {src}.{RESET}")
                    print("💡 You may need to remove it manually and rerun the setup.")
                sys.exit(1)
        else:
            if verbose:
                print(f"\n{RED}❌ Error: A file with the name {dest} exists but is not a symlink.{RESET}")
                print("💡 You may need to remove it manually and rerun the setup.")
            sys.exit(1)
    try:
        dest.symlink_to(src)
    except Exception as e:
        if verbose:
            print(f"\n{RED}❌ Error creating symlink: {dest} -> {src}: {e}{RESET}")
        sys.exit(1)
    if verbose:
        print(f"✅ Created symlink: {dest} -> {src}")
    return True

def make_executable(script: Path, verbose: bool = True) -> None:
    """Ensure a script is executable (Linux/macOS only)."""
    if os.name != "nt":
        try:
            script.chmod(script.stat().st_mode | 0o111)
            if verbose:
                print(f"✅ Set executable permission for {script}")
        except Exception as e:
            if verbose:
                print(f"{RED}❌ Could not set executable permission for {script}: {e}{RESET}")
    else:
        if verbose:
            print(f"\n{RED}🚨 Warning: no make_executable support on non-Linux platforms{RESET}")

def process_symlinks(source_dir: Path, glob_pattern: str, bin_dir: Path,
                     verbose: bool = True, skip_names: list = None) -> (int, int):
    """
    Process files in source_dir matching glob_pattern:
      - For each file (unless its name is in skip_names), remove its extension (using .stem),
        make the file executable, create a symlink in bin_dir, and make the symlink executable.
    Returns a tuple (created_count, existing_count).
    """
    if skip_names is None:
        skip_names = []
    created_count = 0
    existing_count = 0
    for file in source_dir.glob(glob_pattern):
        if file.name in skip_names:
            continue
        # The target name is the file name with extension removed.
        target = file.stem
        dest = bin_dir / target
        make_executable(file, verbose=verbose)
        result = create_symlink(file, dest, verbose=verbose)
        make_executable(dest, verbose=verbose)
        if result:
            created_count += 1
        else:
            existing_count += 1
    return created_count, existing_count

def validate_symlinks(bin_dir):
    """Check for broken symlinks and prompt for removal."""
    auto_delete_all = False

    for symlink in bin_dir.iterdir():
        if symlink.is_symlink():
            target = symlink.resolve()
            if not target.exists():
                print(f"\n{RED}🚨 Warning: Broken symlink found!{RESET}")
                print(f"   ❌ {symlink} -> {target} (Target does not exist)")

                if not auto_delete_all:
                    user_choice = input("❓ Delete this broken symlink? (y/n/A) ").strip().lower()
                    if user_choice == "a":
                        auto_delete_all = True  # User wants to delete all invalid symlinks
                    elif user_choice != "y":
                        continue  # Skip deletion for this symlink

                try:
                    symlink.unlink()
                    print(f"✅ Deleted broken symlink: {symlink}")
                except Exception as e:
                    print(f"⚠️ Failed to delete {symlink}: {e}")

def install_dependencies(dependencies):
    """Install dependencies using Conda first, then fallback to Pip."""
    if not dependencies:
        print("✅ No additional dependencies needed.")
        return

    dependencies = sorted(set(dependencies))
    print(f"🔍 Installing dependencies: {', '.join(dependencies)}")

    conda_installed = shutil.which("conda") is not None
    if conda_installed:
        print("🚀 Attempting Conda installation first...")
        conda_result = subprocess.run(["conda", "install", "-y"] + dependencies, capture_output=True, text=True)

        failed_packages = set()
        for line in conda_result.stderr.split("\n"):
            match = re.search(r"PackagesNotFoundError: ([\w\s,]+)", line)
            if match:
                failed_packages.update(match.group(1).split(", "))

        dependencies = sorted(set(pkg.strip() for pkg in failed_packages if pkg.strip()))

    if dependencies:
        print(f"⚠️ Some packages failed in Conda. Installing with Pip: {', '.join(dependencies)}")
        subprocess.run([sys.executable, "-m", "pip", "install"] + dependencies)

    print("✅ All dependencies installed.")
