import os
import sys
import argparse
import subprocess
import platform
from pathlib import Path

# Define paths dynamically
SCRIPTS_DIR = Path(__file__).resolve().parent
DOTFILES_DIR = Path(os.environ.get("DOTFILES", SCRIPTS_DIR.parent / "dotfiles"))
BIN_DIR = SCRIPTS_DIR / "bin"
SCRIPTS_SETUP_DIR = SCRIPTS_DIR / "scripts_setup"  # Updated directory

# --- Install setup utilities package only if not already installed ---
try:
    from scripts_setup import setup_utils
    print("✅ Setup utilities already installed.")
except ImportError:
    print("🔄 Installing setup utilities (setup_utils.py)...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(SCRIPTS_SETUP_DIR)],
        check=True
    )
    # Try importing again after installation.
    try:
        from scripts_setup import setup_utils
        print("✅ Successfully installed setup utilities.")
    except ImportError:
        print("❌ Failed to import setup utilities even after installation.")
        sys.exit(1)

# Setup scripts to run as part of the master setup.
SETUP_SCRIPTS = [
    SCRIPTS_DIR / "pyscripts/setup.py",
    SCRIPTS_DIR / "shell-scripts/setup.py",
    SCRIPTS_DIR / "modules/setup.py",
    SCRIPTS_DIR / "scripts_setup/setup_path.py"
]

def run_setup(script_path, *args):
    """Run a setup script with given arguments."""
    if script_path.exists():
        print(f"🔄 Running {script_path} ...")
        subprocess.run([sys.executable, str(script_path)] + list(args), check=True)
    else:
        print(f"⚠️ Setup script {script_path} not found. Skipping.")

def main():
    parser = argparse.ArgumentParser(description="Master setup script.")
    parser.add_argument("--skip-reinstall", default=False, action="store_true",
                        help="Skip reinstallation of already installed modules")
    parser.add_argument("--production", action="store_true",
                        help="Install modules in production mode (without -e)")
    args = parser.parse_args()

    print("\n=== Running Master Setup Script ===\n")

    # --- WSL2 Pre-Setup: Install win32yank if on WSL ---
    if "microsoft" in platform.uname().release.lower():
        print("🔄 Detected WSL2 environment. Running win32yank setup...")
        wsl2_setup = SCRIPTS_DIR / "scripts_setup/setup_wsl2.py"
        subprocess.run([sys.executable, str(wsl2_setup)], check=True)
    else:
        print("✅ Not running on WSL2. Skipping win32yank setup.")

    # Common arguments for most scripts
    common_args = [
        "--scripts-dir", str(SCRIPTS_DIR),
        "--dotfiles-dir", str(DOTFILES_DIR),
        "--bin-dir", str(BIN_DIR)
    ]

    setup_scripts = [
        "pyscripts/setup.py",
        "shell-scripts/setup.py",
        "modules/setup.py",
    ]

    # Run standard setup scripts
    for script in setup_scripts:
        extra_args = []
        if "modules" in script:
            if args.skip_reinstall:
                extra_args.append("--skip-reinstall")
            if args.production:
                extra_args.append("--production")
        run_setup(SCRIPTS_DIR / script, *common_args, *extra_args)

    # --- Run additional setup script (setup_path.py) from scripts_setup ---
    path_setup_args = [
        "--bin-dir", str(BIN_DIR),
        "--dotfiles-dir", str(DOTFILES_DIR)
    ]
    run_setup(SCRIPTS_DIR / "scripts_setup/setup_path.py", *path_setup_args)

if __name__ == "__main__":
    main()