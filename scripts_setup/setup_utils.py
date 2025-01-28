import os
import sys
import shutil
import subprocess
from pathlib import Path

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def create_symlink(src, dest):
    """Create a symbolic link if it does not exist."""
    if dest.exists():
        if dest.is_symlink():
            existing_target = dest.resolve()
            if existing_target == src:
                print(f"🔹 Symlink already exists: {dest} -> {existing_target}")
                return
            else:
                print(f"\n{RED}❌ Error: Symlink {dest} already exists but points to {existing_target}, not {src}.{RESET}")
                print("💡 You may need to remove it manually and rerun the setup.")
                sys.exit(1)
        else:
            print(f"\n{RED}❌ Error: A file with the name {dest} already exists but is NOT a symlink.{RESET}")
            print("💡 You may need to remove it manually and rerun the setup.")
            sys.exit(1)
    
    dest.symlink_to(src)
    print(f"✅ Created symlink: {dest} -> {src}")

def make_executable(script):
    """Ensure a script is executable (Linux/macOS only)."""
    if os.name != "nt":  # Skip chmod on Windows
        script.chmod(script.stat().st_mode | 0o111)
    else:
        print(f"\n{RED}🚨 Warning: no make_executable setup for non-linux")

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
