import os
import sys
import argparse
import subprocess
from pathlib import Path
from scripts_setup import setup_utils  # Import shared utility functions

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

def install_python_modules(modules_dir, skip_reinstall, production):
    """Install all modules in 'modules/'."""
    if not modules_dir.exists():
        print(f"⚠️ No 'modules' directory found at {modules_dir}. Skipping installation.")
        return

    for module in modules_dir.iterdir():
        if not module.is_dir() or not (module / "setup.py").exists():
            continue

        install_cmd = [sys.executable, "-m", "pip", "install"]
        if not production:
            install_cmd.append("-e")  # Editable mode for development
        install_cmd.append(str(module))

        # ✅ Skip reinstall if already installed
        if skip_reinstall and is_module_installed(module):
            print(f"🔹 Module already installed: {module.name}. Skipping.")
            continue

        print(f"🚀 Installing: {module.name} {'(production mode)' if production else '(development mode)'}")
        subprocess.run(install_cmd, check=True)

def ensure_pythonpath(modules_dir, dotfiles_dir):
    """Ensure PYTHONPATH includes the modules directory and persist it dynamically."""
    pythonpath_dynamic = dotfiles_dir / "dynamic/setup_modules.zsh"
    pythonpath_dynamic.parent.mkdir(parents=True, exist_ok=True)

    pythonpath_entry = f'export PYTHONPATH="{modules_dir}:$PYTHONPATH"\n'

    # ✅ Overwrite the file to prevent duplicates
    with open(pythonpath_dynamic, "w") as f:
        f.write(pythonpath_entry)

    print(f"✅ Updated PYTHONPATH in {pythonpath_dynamic}")

    # ✅ Source the new dynamic file to apply immediately
    try:
        subprocess.run(["zsh", "-c", f"source {pythonpath_dynamic}"], check=True)
        print(f"✅ Sourced {pythonpath_dynamic}. Changes applied immediately.")
    except Exception as e:
        print(f"❌ Failed to source {pythonpath_dynamic}: {e}")

def main(scripts_dir, dotfiles_dir, bin_dir, skip_reinstall, production):
    """Main function to set up Python modules and PYTHONPATH."""
    print("\n🔄 Running modules/setup.py ...")

    modules_dir = scripts_dir / "modules"

    # ✅ Install modules
    install_python_modules(modules_dir, skip_reinstall, production)

    # ✅ Ensure PYTHONPATH includes the modules directory
    ensure_pythonpath(modules_dir, dotfiles_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Python modules and PYTHONPATH.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Path to the scripts/ directory")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Path to the dotfiles/ directory")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Path to the bin/ directory")
    parser.add_argument("--skip-reinstall", action="store_true", help="Skip reinstallation of already installed modules")
    parser.add_argument("--production", action="store_true", help="Install modules in production mode (without -e)")

    args = parser.parse_args()
    main(args.scripts_dir, args.dotfiles_dir, args.bin_dir, args.skip_reinstall, args.production)
