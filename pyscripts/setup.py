import os
import re
import subprocess
from pathlib import Path

RED = "\033[91m"
RESET = "\033[0m"

def parse_alias_file(alias_file):
    """Parse the alias_names.txt file and return a dictionary of script-to-alias mappings."""
    aliases = {}

    if not alias_file.exists():
        print(f"⚠️ Alias file not found: {alias_file}. Skipping alias setup.")
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
                print(f"⚠️ Invalid alias format in {alias_file}: {line}")

    return aliases

def get_existing_aliases():
    """Retrieve existing aliases from the active shell session."""
    try:
        result = subprocess.run(["zsh", "-c", "alias"], capture_output=True, text=True, check=True)
        aliases = set()

        for line in result.stdout.splitlines():
            if line.startswith("alias "):
                alias_name = line.split("=")[0].replace("alias ", "").strip()
                aliases.add(alias_name)

        return aliases
    except Exception as e:
        print(f"⚠️ Warning: Could not retrieve existing aliases: {e}")
        return set()

def write_aliases(bin_dir, alias_file, dotfiles_dir):
    """Write aliases to the dynamic shell config file and ensure no conflicts."""
    aliases = parse_alias_file(alias_file)
    shell_config = dotfiles_dir / "dynamic/setup_pyscripts.zsh"

    if not aliases:
        print("✅ No valid aliases to process.")
        return

    # Ensure the dynamic config directory exists
    shell_config.parent.mkdir(parents=True, exist_ok=True)

    # Retrieve **live aliases** from the active shell session
    existing_aliases = get_existing_aliases()

    new_aliases = []
    for script, alias in aliases.items():
        bin_script_path = bin_dir / script.replace(".py", "")

        # ✅ Now checks **active aliases**, not just static files
        if alias in existing_aliases:
            print(f"{RED}❌ Alias conflict: `{alias}` already exists in active shell. Skipping.{RESET}")
            continue

        new_aliases.append(f'alias {alias}="{bin_script_path}"')

    # Overwrite the alias file to ensure no duplicates
    with open(shell_config, "w", encoding="utf-8") as f:
        f.write("\n".join(new_aliases) + "\n")

    print(f"✅ Aliases updated in {shell_config}.")

    # 🔄 Automatically source the file to activate new aliases immediately
    subprocess.run(["zsh", "-c", f"source {shell_config}"], check=False)
    print("✅ Aliases have been applied. You can now use them immediately.")

def main(scripts_dir, dotfiles_dir, bin_dir):
    """Main function to set up Python scripts and aliases."""
    print("\n🔄 Running pyscripts/setup.py ...")

    alias_file = scripts_dir / "pyscripts/alias_names.txt"

    if not bin_dir.exists():
        bin_dir.mkdir(parents=True, exist_ok=True)

    # Ensure Python scripts in bin are executable
    for script in bin_dir.iterdir():
        if script.is_symlink() or script.suffix in {".sh", ".py", ".zsh"}:
            try:
                script.chmod(script.stat().st_mode | 0o111)
            except Exception as e:
                print(f"⚠️ Failed to make {script} executable: {e}")

    # Write aliases
    write_aliases(bin_dir, alias_file, dotfiles_dir)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Setup pyscripts and manage aliases.")
    parser.add_argument("--scripts-dir", type=Path, required=True, help="Path to the scripts/ directory")
    parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Path to the dotfiles/ directory")
    parser.add_argument("--bin-dir", type=Path, required=True, help="Path to the bin/ directory where symlinks are stored")

    args = parser.parse_args()
    main(args.scripts_dir, args.dotfiles_dir, args.bin_dir)
