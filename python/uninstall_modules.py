import os
import subprocess
import argparse
import shutil
from pathlib import Path
import toml
import logging

# 📜 Setup logging (works on both Termux & WSL2)
LOG_DIR = Path(os.getenv("HOME", "/data/data/com.termux/files/home")) / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "uninstall_modules.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

def log(message):
    """Log to both console and file."""
    print(message)
    logging.info(message)

def get_installed_packages():
    """Retrieve installed packages from `pip list`."""
    result = subprocess.run(["pip", "list", "--format=freeze"], capture_output=True, text=True)
    installed_packages = {}

    for line in result.stdout.splitlines():
        if " @ " in line:
            package, _ = line.split(" @ ", 1)
            installed_packages[package] = "editable"
        elif "==" in line:
            package = line.split("==")[0]
            installed_packages[package] = "production"

    return installed_packages

def get_package_name(module_dir):
    """Extracts package name from `pyproject.toml`, `setup.py`, or `requirements.txt`."""
    toml_path = module_dir / "pyproject.toml"
    setup_path = module_dir / "setup.py"
    reqs_path = module_dir / "requirements.txt"

    if toml_path.exists():
        try:
            data = toml.load(toml_path)
            return data["project"]["name"]
        except (KeyError, toml.TomlDecodeError):
            log(f"⚠️ Warning: Invalid `pyproject.toml` in {module_dir}")
            return None

    if setup_path.exists():
        try:
            result = subprocess.run(["python", str(setup_path), "--name"], capture_output=True, text=True)
            return result.stdout.strip()
        except Exception as e:
            log(f"⚠️ Error extracting package name from {setup_path}: {e}")

    if reqs_path.exists():
        with open(reqs_path, "r") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    return line.split()[0]

    return None

def auto_remove_orphans():
    """Remove orphaned dependencies if `pip-autoremove` is available."""
    log("\n🧹 Removing orphaned dependencies...")
    if shutil.which("pip-autoremove") is None:
        log("⚠️ `pip-autoremove` not found. Skipping orphan removal.")
        return
    subprocess.run(["pip-autoremove", "-y"], check=False)

def uninstall_modules(base_dir, uninstall_editables=True, uninstall_production=True, dry_run=False, remove_orphans=False, keep_list=None, interactive=False):
    """Uninstalls modules with interactive, logging, and orphan-removal support."""
    base_dir = Path(base_dir)
    installed_packages = get_installed_packages()
    to_uninstall = []

    if not base_dir.exists():
        log(f"⚠️ Error: Modules directory '{base_dir}' not found!")
        return

    log(f"\n🔍 Scanning {base_dir} for installed modules...\n")

    for module_dir in base_dir.iterdir():
        if module_dir.is_dir():
            package_name = get_package_name(module_dir)
            if not package_name:
                log(f"⚠️ Warning: No identifiable package found in {module_dir}")
                continue

            if keep_list and package_name in keep_list:
                log(f"⏭️ Skipping {package_name} (in keep list)")
                continue

            install_type = installed_packages.get(package_name, "unknown")

            if install_type == "unknown":
                log(f"⚠️ Warning: {package_name} is not installed according to `pip list`")

            if (uninstall_editables and install_type == "editable") or (uninstall_production and install_type == "production"):
                to_uninstall.append(package_name)  # ✅ Ensure strings only

    if not to_uninstall:
        log("✅ No matching modules found for uninstallation.")
        return

    log("\n📌 **Modules Marked for Uninstallation:**")
    for package in to_uninstall:
        log(f"   - {package}")

    if dry_run:
        log("\n🛠️ **Dry Run Mode: No packages will be uninstalled.**")
        return

    if interactive:
        final_uninstall_list = []
        for package in to_uninstall:
            response = input(f"❓ Uninstall {package}? [y/n/A/s] ").strip().lower()
            if response == "y":
                final_uninstall_list.append(package)
            elif response == "a":
                final_uninstall_list.extend(to_uninstall)
                break
            elif response == "s":
                log("⏭️ Skipping rest...")
                break

        to_uninstall = final_uninstall_list

    if to_uninstall:
        log(f"\n🔄 Uninstalling {len(to_uninstall)} modules...")
        subprocess.run(["pip", "uninstall", "-y"] + to_uninstall)

        if remove_orphans:
            auto_remove_orphans()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Uninstall Python modules from a specified directory.")
    parser.add_argument("-p", "--path", default="./", help="Root directory for module folders (default: current directory)")
    parser.add_argument("-e", "--editables", action="store_true", help="Uninstall only editable (`pip install -e .`) modules")
    parser.add_argument("-n", "--production", action="store_true", help="Uninstall only non-editable (`pip install package`) modules")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Show modules that would be uninstalled without making changes")
    parser.add_argument("-o", "--orphaned", action="store_true", help="Auto-remove orphaned dependencies after uninstalling")
    parser.add_argument("-k", "--keep", nargs="+", default=[], help="List of packages to keep (won't be uninstalled)")
    parser.add_argument("-i", "--interactive", action="store_true", help="Ask before uninstalling each package")

    args = parser.parse_args()

    uninstall_editables = args.editables or not args.production
    uninstall_production = args.production or not args.editables

    uninstall_modules(
        args.path,
        uninstall_editables,
        uninstall_production,
        dry_run=args.dry_run,
        remove_orphans=args.orphaned,
        keep_list=args.keep,
        interactive=args.interactive
    )
