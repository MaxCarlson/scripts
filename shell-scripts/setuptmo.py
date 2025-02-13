import os
from pathlib import Path

SHELL_SCRIPTS_DIR = Path.home() / "scripts/shell-scripts"
BIN_DIR = Path.home() / "scripts/bin"

def create_symlink(src, dest):
    """Create a symbolic link if it does not exist."""
    if dest.exists() or dest.is_symlink():
        print(f"🔹 Symlink already exists: {dest}")
        return False
    dest.symlink_to(src)
    print(f"✅ Created symlink: {dest} -> {src}")
    return True

def make_executable(script):
    """Ensure a script is executable."""
    script.chmod(script.stat().st_mode | 0o111)

def setup_shell_scripts():
    """Creates symlinks for shell scripts in bin/ and makes them executable."""
    if not SHELL_SCRIPTS_DIR.exists():
        print(f"⚠️ Directory {SHELL_SCRIPTS_DIR} does not exist. Skipping setup.")
        return

    BIN_DIR.mkdir(parents=True, exist_ok=True)

    for script in SHELL_SCRIPTS_DIR.glob("*.sh"):
        link_path = BIN_DIR / script.name
        if create_symlink(script, link_path):
            make_executable(script)

if __name__ == "__main__":
    print("\n🔄 Setting up shell scripts...")
    setup_shell_scripts()
