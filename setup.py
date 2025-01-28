import os
import sys
import argparse
import subprocess
from pathlib import Path

# Define paths dynamically
SCRIPTS_DIR = Path(__file__).resolve().parent
DOTFILES_DIR = Path(os.environ.get("DOTFILES", SCRIPTS_DIR.parent / "dotfiles"))
BIN_DIR = SCRIPTS_DIR / "bin"
SCRIPTS_SETUP_DIR = SCRIPTS_DIR / "scripts_setup"  # ✅ Updated directory

# ✅ Install `scripts_setup/` as a package before proceeding
print("🔄 Installing setup utilities...")
subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(SCRIPTS_SETUP_DIR)], check=True)

# ✅ Now that scripts_setup is installed, we can import it normally
from scripts_setup import setup_utils

# Setup scripts
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
    parser.add_argument("--skip-reinstall", default=False, action="store_true", help="Skip reinstallation of already installed modules")
    parser.add_argument("--production", action="store_true", help="Install modules in production mode (without -e)")
    args = parser.parse_args()

    print("\n=== Running Master Setup Script ===\n")

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

    # ✅ Run `setup_path.py` separately, passing only relevant arguments
    path_setup_args = [
        "--bin-dir", str(BIN_DIR),
        "--dotfiles-dir", str(DOTFILES_DIR)
    ]
    run_setup(SCRIPTS_DIR / "scripts_setup/setup_path.py", *path_setup_args)

if __name__ == "__main__":
    main()
