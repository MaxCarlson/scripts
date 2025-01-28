import os
import subprocess
from pathlib import Path
import argparse

parser = argparse.ArgumentParser(description="Ensure bin/ is in PATH")
parser.add_argument("--bin-dir", type=Path, required=True, help="Path to the bin/ directory")
parser.add_argument("--dotfiles-dir", type=Path, required=True, help="Path to the dotfiles/ directory")
args = parser.parse_args()

bin_path = str(args.bin_dir.resolve())

# ✅ Detect shell type
is_windows = os.name == "nt"
shell = os.environ.get("SHELL", "").split("/")[-1] if "SHELL" in os.environ else ""
is_pwsh = shell == "pwsh" or is_windows  # Detect PowerShell

if bin_path in os.environ["PATH"]:
    print(f"✅ {bin_path} is already in PATH. No changes needed.")
else:
    print(f"🔄 Adding {bin_path} to PATH...")

    if is_pwsh:
        # ✅ PowerShell: Modify Windows User Environment Variable (Only Add, Don't Overwrite)
        print(f"🔄 Updating PowerShell PATH...")

        try:
            existing_path = subprocess.run(
                ["pwsh", "-Command", '[System.Environment]::GetEnvironmentVariable("Path", "User")'],
                capture_output=True,
                text=True
            ).stdout.strip()

            # ✅ Ensure we don't overwrite existing PATH
            if bin_path not in existing_path:
                new_path = f"{existing_path};{bin_path}" if existing_path else bin_path
                subprocess.run([
                    "pwsh", "-Command",
                    f'[System.Environment]::SetEnvironmentVariable("Path", "{new_path}", "User")'
                ], check=True)
                print(f"✅ Added {bin_path} permanently to PowerShell PATH. Restart pwsh to apply.")
            else:
                print(f"✅ {bin_path} is already in PowerShell PATH. No changes needed.")

        except Exception as e:
            print(f"❌ Failed to update PowerShell PATH: {e}")

    else:
        # ✅ Zsh/Linux/macOS: Modify `dynamic/setup_path.zsh`
        dotfiles_dynamic = args.dotfiles_dir / "dynamic/setup_path.zsh"
        dotfiles_dynamic.parent.mkdir(parents=True, exist_ok=True)

        # ✅ Overwrite the file (not append) to ensure no duplicates
        with open(dotfiles_dynamic, "w") as f:
            f.write(f'export PATH="{bin_path}:$PATH"\n')

        print(f"✅ Added {bin_path} permanently to {dotfiles_dynamic}.")

        # ✅ Source the file immediately to apply changes
        try:
            subprocess.run(["zsh", "-c", f"source {dotfiles_dynamic}"], check=True)
            print(f"✅ Sourced {dotfiles_dynamic}. Changes applied immediately.")
        except Exception as e:
            print(f"❌ Failed to source {dotfiles_dynamic}: {e}")
