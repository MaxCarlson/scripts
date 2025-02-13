import re
import subprocess
from pathlib import Path

RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RESET = "\033[0m"

def command_exists(command: str) -> bool:
    try:
        result = subprocess.run(
            ["zsh", "-c", f"command -v {command}"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"{YELLOW}⚠️ Warning: Could not check command existence for `{command}`: {e}{RESET}")
        return False

def parse_alias_file(alias_file: Path) -> dict:
    aliases = {}
    if not alias_file.exists():
        print(f"{YELLOW}⚠️ Alias file not found: {alias_file}. Skipping alias setup.{RESET}")
        return aliases
    with open(alias_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^(.+?)\s*:\s*(.+?)$", line)
            if match:
                script, alias = match.groups()
                aliases[script.strip()] = alias.strip()
            else:
                print(f"{YELLOW}⚠️ Invalid alias format in {alias_file}: {line}{RESET}")
    return aliases

def get_existing_aliases(alias_config: Path) -> dict:
    aliases = {}
    if alias_config.exists():
        with open(alias_config, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("alias "):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        alias_name = parts[0].replace("alias", "").strip()
                        alias_value = parts[1].strip().strip('"')
                        aliases[alias_name] = alias_value
    return aliases

def alias_target(bin_dir: Path, script: str, ext: str) -> Path:
    if script.endswith(ext):
        script = script[:-len(ext)]
    return bin_dir / script

def write_aliases(aliases: dict, bin_dir: Path, alias_config: Path, ext: str, verbose: bool = False) -> None:
    """
    Write alias definitions to alias_config.
    In verbose mode, prints all aliases as:
      alias_name : alias_value
    In non-verbose mode, prints only the aliases that are newly created (i.e. did not exist before).
    """
    temp_aliases = []
    existing_aliases = get_existing_aliases(alias_config)
    newly_created = {}

    for script, alias in aliases.items():
        target = alias_target(bin_dir, script, ext)
        # If the alias already exists with the same value, consider it not new.
        if alias in existing_aliases and str(existing_aliases[alias]) == str(target):
            if verbose:
                print(f"🔹 Alias already exists: {alias} : {target}")
        else:
            newly_created[alias] = target
        temp_aliases.append(f'alias {alias}="{target}"')

    alias_config.parent.mkdir(parents=True, exist_ok=True)
    with open(alias_config, "w", encoding="utf-8") as f:
        f.write("\n".join(temp_aliases) + "\n")
    print(f"{GREEN}✅ Aliases updated in {alias_config}.{RESET}")

    # Print alias details:
    print("---------- Alias Definitions ----------")
    if verbose:
        for line in temp_aliases:
            parts = line.split("=", 1)
            if len(parts) == 2:
                alias_name = parts[0].replace("alias", "").strip()
                alias_value = parts[1].strip().strip('"')
                print(f"{alias_name} : {alias_value}")
    else:
        if newly_created:
            print("Newly created aliases:")
            for alias, target in newly_created.items():
                print(f"{alias} : {target}")
        else:
            print("No new aliases were created.")
    print("---------------------------------------")
    
    try:
        subprocess.run(["zsh", "-c", f"source {alias_config}"], check=True)
        print(f"{GREEN}✅ Aliases have been applied. You can now use them immediately.{RESET}")
    except subprocess.CalledProcessError:
        print(f"{YELLOW}⚠️ Automatic sourcing of aliases failed. Please source {alias_config} manually.{RESET}")
#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from pathlib import Path
from scripts_setup import setup_utils  # Shared utilities, if needed

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def get_module_install_mode(module_path: Path) -> str:
    """
    Returns the install mode of the module:
      - "editable" if installed with -e,
      - "normal" if installed normally,
      - None if not installed.
    """
    module_name = module_path.name
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=freeze"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if " @ " in line:
            name = line.split(" @ ")[0].strip()
            if name.lower() == module_name.lower():
                return "editable"
        elif "==" in line:
            name = line.split("==")[0].strip()
            if name.lower() == module_name.lower():
                return "normal"
    return None

def is_module_installed(module_path: Path) -> bool:
    return get_module_install_mode(module_path) is not None

def install_python_modules(modules_dir: Path, skip_reinstall: bool, production: bool, verbose: bool) -> None:
    if not modules_dir.exists():
        print(f"{YELLOW}⚠️ No 'modules' directory found at {modules_dir}. Skipping installation.{RESET}")
        return

    print(f"🔍 Scanning for modules inside: {modules_dir}")
    found_any = False

    for module in modules_dir.iterdir():
        if not module.is_dir():
            print(f"{YELLOW}⚠️ Skipping {module}, not a directory.{RESET}")
            continue

        setup_py = module / "setup.py"
        pyproject_toml = module / "pyproject.toml"
        if not setup_py.exists() and not pyproject_toml.exists():
            print(f"{YELLOW}⚠️ Skipping {module.name}, no setup.py or pyproject.toml found.{RESET}")
            continue

        found_any = True

        install_cmd = [sys.executable, "-m", "pip", "install"]
        if not production:
            install_cmd.append("-e")  # Editable mode
        install_cmd.append(str(module))

        # Check current install mode if skip_reinstall is enabled.
        if skip_reinstall:
            installed_mode = get_module_install_mode(module)
            desired_mode = "editable" if not production else "normal"
            if installed_mode == desired_mode:
                print(f"⏭ Module already installed ({installed_mode}): {module.name}. Skipping.")
                continue

        mode_text = "(production mode)" if production else "(development mode)"
        if verbose:
            print(f"🚀 Installing: {module.name} {mode_text}")
        else:
            print(f"🚀 Installing: {module.name} {mode_text}...", end=" ")

        try:
            if verbose:
                subprocess.run(install_cmd, check=True)
                print(f"{GREEN}✅{RESET}")
            else:
                result = subprocess.run(install_cmd, check=True,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE,
                                          text=True)
                print(f"{GREEN}✅{RESET}")
        except subprocess.CalledProcessError as e:
            if verbose:
                print(f"{RED}❌ Failed to install {module.name}:{RESET}")
                print(e.stderr)
            else:
                print(f"{RED}❌{RESET}")
                print(e.stderr)
    if not found_any:
        print(f"{RED}❌ No valid modules found in {modules_dir}. Check if they have setup.py or pyproject.toml.{RESET}")

def ensure_pythonpath(modules_dir: Path, dotfiles_dir: Path) -> None:
    pythonpath_dynamic = dotfiles_dir / "dynamic/setup_modules.zsh"
    pythonpath_dynamic.parent.mkdir(parents=True, exist_ok=True)
    pythonpath_entry = f'export PYTHONPATH="{modules_dir}:$PYTHONPATH"\n'
    current_pythonpath = os.environ.get("PYTHONPATH", "").split(":")
    if str(modules_dir) in current_pythonpath:
        print(f"✅ PYTHONPATH already includes {modules_dir}. No changes needed.")
        return
    print(f"🔄 Updating PYTHONPATH to include {modules_dir}...")
    with open(pythonpath_dynamic, "w", encoding="utf-8") as f:
        f.write(pythonpath_entry)
    print(f"✅ Updated PYTHONPATH in {pythonpath_dynamic}")
    try:
        subprocess.run(["zsh", "-c", f"source {pythonpath_dynamic}"], check=True)
        print(f"✅ Sourced {pythonpath_dynamic}. Python path changes applied immediately.")
    except Exception as e:
        print(f"❌ Failed to source {pythonpath_dynamic}: {e}")

def main(scripts_dir: Path, dotfiles_dir: Path, bin_dir: Path, skip_reinstall: bool, production: bool, verbose: bool) -> None:
    print("\n========== Starting MODULES SETUP ==========")
    modules_dir = scripts_dir / "modules"
    install_python_modules(modules_dir, skip_reinstall, production, verbose)
    ensure_pythonpath(modules_dir, dotfiles_dir)
    print("========== Finished MODULES SETUP ==========\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Python modules and PYTHONPATH.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Path to the scripts directory")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Path to the dotfiles directory")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Path to the bin directory")
    parser.add_argument("--skip-reinstall", action="store_true", help="Skip reinstallation of already installed modules")
    parser.add_argument("--production", action="store_true", help="Install modules in production mode (without -e)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()
    main(args.scripts_dir, args.dotfiles_dir, args.bin_dir,
         args.skip_reinstall, args.production, args.verbose)
