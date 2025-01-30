import os
import re
import stat
import subprocess
from pathlib import Path

RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RESET = "\033[0m"


def command_exists(command):
    """Check if a command, alias, or function exists in zsh."""
    try:
        result = subprocess.run(
            ["zsh", "-c", f"command -v {command}"],
            capture_output=True, text=True, check=False
        )
        return result.returncode == 0
    except Exception as e:
        print(f"⚠️ Warning: Could not check command existence for `{command}`: {e}")
        return False

def parse_alias_file(alias_file):
    """Parse the alias_names.txt file and return a dictionary of script-to-alias mappings."""
    aliases = {}

    if not alias_file.exists():
        print(f"{YELLOW}⚠️ Alias file not found: {alias_file}. Skipping alias setup.{RESET}")
        return aliases

    with open(alias_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            match = re.match(r"^(.+?)\s*:\s*(.+?)$", line)
            if match:
                script, alias = match.groups()
                aliases[script.strip()] = alias.strip()
            else:
                print(f"{YELLOW}⚠️ Invalid alias format in {alias_file}: {line}{RESET}")

    return aliases


def get_existing_aliases_from_file(alias_file):
    """Retrieve aliases already written in the alias config file."""
    aliases = {}

    if alias_file.exists():
        with open(alias_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("alias "):
                    alias_name, alias_value = line.split("=", 1)
                    alias_name = alias_name.replace("alias ", "").strip()
                    alias_value = alias_value.strip().strip('"')
                    aliases[alias_name] = alias_value
    return aliases


def write_aliases(bin_dir, alias_file, dotfiles_dir):
    """Write aliases to the dynamic shell config file and ensure no conflicts."""
    aliases = parse_alias_file(alias_file)
    shell_config = dotfiles_dir / "dynamic/setup_pyscripts.zsh"
    temp_aliases = []
    warnings_raised = False

    existing_aliases = get_existing_aliases_from_file(shell_config)

    for script, alias in aliases.items():
        bin_script_path = bin_dir / script.replace(".py", "")

        # ✅ Check if alias is an existing command/function
        if command_exists(alias):
            if alias not in existing_aliases:
                print(f"{RED}❌ Alias conflict: `{alias}` is already an existing command/function. Skipping.{RESET}")
                warnings_raised = True
                continue
            else:
                print(f"🔹 Alias `{alias}` already exists and is correctly set.")

        # ✅ Add to new alias list
        temp_aliases.append(f'alias {alias}="{bin_script_path}"')

    if warnings_raised:
        print(f"{YELLOW}⚠️ Warning: Some aliases were skipped due to conflicts. Please resolve them manually.{RESET}")

    if temp_aliases:
        with open(shell_config, "w", encoding="utf-8") as f:
            f.write("\n".join(temp_aliases) + "\n")

        print(f"{GREEN}✅ Aliases updated in {shell_config}.{RESET}")

        # ✅ Source the file to apply changes immediately
        subprocess.run(["zsh", "-c", f"source {shell_config}"], check=False)
        print(f"{GREEN}✅ Aliases have been applied. You can now use them immediately.{RESET}")
    else:
        print(f"{YELLOW}🔹 No new aliases to write. {shell_config} remains unchanged.{RESET}")



def ensure_symlinks(scripts_dir, bin_dir):
    """Ensure all Python scripts in pyscripts/ are symlinked to bin/ with executable permissions."""
    print("🔄 Ensuring Python scripts are symlinked and executable...")

    pyscripts_dir = scripts_dir / "pyscripts"

    if not pyscripts_dir.exists():
        print(f"⚠️ No pyscripts directory found at {pyscripts_dir}. Skipping symlink creation.")
        return

    for script in pyscripts_dir.glob("*.py"):
        if script.name == "setup.py":
            continue  # Skip setup.py itself

        symlink_path = bin_dir / script.stem  # Strip .py extension

        # Ensure the script itself is executable
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        if symlink_path.exists():
            if symlink_path.is_symlink() and symlink_path.resolve() == script.resolve():
                print(f"🔹 Symlink already exists: {symlink_path} -> {script}")
                continue  # Correct symlink exists, skip

            # ❌ Conflict: A symlink with the same name exists but points elsewhere
            print(f"{RED}❌ Symlink conflict: `{symlink_path}` exists but does not point to `{script}`!{RESET}")
            continue

        symlink_path.symlink_to(script)
        print(f"✅ Created symlink: {symlink_path} -> {script}")

        # Ensure the symlink is also executable
        symlink_path.chmod(symlink_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

def main(scripts_dir, dotfiles_dir, bin_dir):
    """Main function to set up Python scripts, aliases, and symlinks."""
    print("\n🔄 Running pyscripts/setup.py ...")

    alias_file = scripts_dir / "pyscripts/alias_names.txt"

    if not bin_dir.exists():
        bin_dir.mkdir(parents=True, exist_ok=True)

    # ✅ Ensure symlinks exist
    ensure_symlinks(scripts_dir, bin_dir)

    # ✅ Write aliases and check conflicts
    write_aliases(bin_dir, alias_file, dotfiles_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Setup pyscripts and manage aliases.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Path to the scripts/ directory")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Path to the dotfiles/ directory")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Path to the bin/ directory where symlinks are stored")

    args = parser.parse_args()
    main(args.scripts_dir, args.dotfiles_dir, args.bin_dir)
