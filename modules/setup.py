import os
import sys
import argparse
import subprocess
from pathlib import Path
from scripts_setup import setup_utils  # Import shared utility functions

def is_module_installed(module_path):
    """Check if a module is installed (production or editable)."""
    module_name = module_path.name

    # Use `pip list --format=freeze` to check if the module is actually installed
    result = subprocess.run([sys.executable, "-m", "pip", "list", "--format=freeze"], capture_output=True, text=True)

    installed_modules = {line.split("==")[0] for line in result.stdout.splitlines() if "==" in line}  # Only normal installs
    installed_editables = {line.split(" @ ")[0] for line in result.stdout.splitlines() if " @" in line}  # Editable installs

    return module_name in installed_modules or module_name in installed_editables

def install_python_modules(modules_dir, skip_reinstall, production):
    """Install all modules in 'modules/'."""
    if not modules_dir.exists():
        print(f"⚠️ No 'modules' directory found at {modules_dir}. Skipping installation.")
        return

    print(f"🔍 Scanning for modules inside: {modules_dir}")

    found_any = False  # Track if we find modules at all

    for module in modules_dir.iterdir():
        if not module.is_dir():
            print(f"⚠️ Skipping {module}, not a directory.")
            continue

        setup_py = module / "setup.py"
        pyproject_toml = module / "pyproject.toml"

        if not setup_py.exists() and not pyproject_toml.exists():
            print(f"⚠️ Skipping {module.name}, no setup.py or pyproject.toml found.")
            continue

        found_any = True  # We found a valid module!

        install_cmd = [sys.executable, "-m", "pip", "install"]
        if not production:
            install_cmd.append("-e")  # Editable mode for development
        install_cmd.append(str(module))

        # ✅ Skip reinstall if already installed
        if skip_reinstall and is_module_installed(module):
            print(f"🔹 Module already installed: {module.name}. Skipping.")
            continue

        print(f"🚀 Installing: {module.name} {'(production mode)' if production else '(development mode)'}")
        try:
            subprocess.run(install_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install {module.name}: {e}")

    if not found_any:
        print(f"❌ No valid modules found in {modules_dir}. Check if they have setup.py or pyproject.toml.")

def ensure_pythonpath(modules_dir, dotfiles_dir):
    """Ensure PYTHONPATH includes the modules directory and persist it dynamically."""
    pythonpath_dynamic = dotfiles_dir / "dynamic/setup_modules.zsh"
    pythonpath_dynamic.parent.mkdir(parents=True, exist_ok=True)

    pythonpath_entry = f'export PYTHONPATH="{modules_dir}:$PYTHONPATH"\n'

    # ✅ Check if PYTHONPATH already contains the module path
    current_pythonpath = os.environ.get("PYTHONPATH", "").split(":")
    if str(modules_dir) in current_pythonpath:
        print(f"✅ PYTHONPATH already includes {modules_dir}. No changes needed.")
        return

    # ✅ Overwrite the file to prevent duplicates
    print(f"🔄 Updating PYTHONPATH to include {modules_dir}...")
    with open(pythonpath_dynamic, "w", encoding="utf-8") as f:
        f.write(pythonpath_entry)

    print(f"✅ Updated PYTHONPATH in {pythonpath_dynamic}")

    # ✅ Source the new dynamic file **only if changes were made**
    try:
        subprocess.run(["zsh", "-c", f"source {pythonpath_dynamic}"], check=True)
        print(f"✅ Sourced {pythonpath_dynamic}. Python path changes applied immediately.")
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
