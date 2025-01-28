import os
import shutil
import subprocess
from pathlib import Path

def create_symlink(src, dest):
    """Create a symbolic link if it does not exist."""
    if dest.exists() or dest.is_symlink():
        print(f"🔹 Symlink already exists: {dest}")
        return False
    dest.symlink_to(src)
    print(f"✅ Created symlink: {dest} -> {src}")
    return True

def make_executable(script):
    """Ensure a script is executable (Linux/macOS only)."""
    if os.name != "nt":  # Skip chmod on Windows
        script.chmod(script.stat().st_mode | 0o111)

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
