import os
import subprocess
from pathlib import Path
import argparse
import sys # For sys.exit on critical errors

# Basic print logging for this script, as standard_ui might not be configured
# or this script might be called standalone.
def log_print(level, message):
    print(f"[{level}] {message}")

def main():
    parser = argparse.ArgumentParser(
        description="Ensure bin/ directory is in PATH for the appropriate shell."
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        required=True,
        help="Path to the bin/ directory to be added to PATH."
    )
    parser.add_argument(
        "--dotfiles-dir",
        type=Path,
        required=True,
        help="Path to the dotfiles/ directory, used for Zsh configuration."
    )
    # Verbose argument for more detailed output from this script itself
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed output during PATH setup."
    )
    args = parser.parse_args()

    bin_path_to_add = args.bin_dir.resolve()
    if args.verbose:
        log_print("INFO", f"Target bin directory: {bin_path_to_add}")
        log_print("INFO", f"Dotfiles directory: {args.dotfiles_dir}")

    current_path_env = os.environ.get("PATH", "")
    path_separator = os.pathsep

    if str(bin_path_to_add) in current_path_env.split(path_separator):
        log_print("SUCCESS", f"{bin_path_to_add} is already in the current session's PATH.")
        # Note: This doesn't mean it's permanently in PATH for future sessions.
        # The script will still check/update persistent configuration.
    else:
        log_print("INFO", f"{bin_path_to_add} not found in current session's PATH. Will attempt to add to shell config.")


    if os.name == "nt":
        log_print("INFO", "Windows OS detected.")
        # Attempt to update User PATH environment variable
        try:
            # Get current User PATH
            # Using 'reg query' is more reliable than GetEnvironmentVariable for unexpanded vars
            completed_process = subprocess.run(
                ['reg', 'query', r'HKCU\Environment', '/v', 'Path'],
                capture_output=True, text=True, check=False
            )
            
            current_user_path = ""
            if completed_process.returncode == 0 and completed_process.stdout:
                # Example output: HKEY_CURRENT_USER\Environment Path REG_SZ C:\Users\user\path1;C:\path2
                match = Path(r"Path\s+REG_(EXPAND_)?SZ\s+(.*)").search(completed_process.stdout)
                if match:
                    current_user_path = match.group(2).strip()
            if args.verbose:
                log_print("INFO", f"Current User PATH from registry: '{current_user_path}'")

            if str(bin_path_to_add) in current_user_path.split(path_separator):
                log_print("SUCCESS", f"{bin_path_to_add} is already in the User PATH environment variable.")
            else:
                log_print("INFO", f"Adding {bin_path_to_add} to User PATH environment variable.")
                # Append to existing path, or set new if path was empty
                new_path_value = f"{current_user_path}{path_separator}{bin_path_to_add}" if current_user_path else str(bin_path_to_add)
                
                # Use setx to make the change persistent for the user
                # setx HKCU\Environment Path "new_path_value" - No, setx works differently
                # setx Path "new_path_value"
                # Note: setx has a 1024 char limit for the combined variable.
                # For longer paths, direct registry modification (more complex) or PowerShell is needed.
                # Given PowerShell is often available:
                
                is_pwsh_available = bool(subprocess.run(["where", "pwsh"], capture_output=True).stdout or \
                                      subprocess.run(["where", "powershell"], capture_output=True).stdout)

                if is_pwsh_available:
                    log_print("INFO", "Using PowerShell to update User PATH.")
                    ps_command = (
                        f'$currentUserPath = [System.Environment]::GetEnvironmentVariable("Path", "User"); '
                        f'if (($currentUserPath -split "{path_separator}") -notcontains "{str(bin_path_to_add)}") {{ '
                        f'  $newPath = if ([string]::IsNullOrEmpty($currentUserPath)) {{ "{str(bin_path_to_add)}" }} else {{ "$currentUserPath{path_separator}{str(bin_path_to_add)}" }}; '
                        f'  [System.Environment]::SetEnvironmentVariable("Path", $newPath, "User"); '
                        f'  Write-Host "Successfully updated User PATH via PowerShell." '
                        f'}} else {{ Write-Host "{str(bin_path_to_add)} already in User PATH (PowerShell check)." }}'
                    )
                    pwsh_exe = "pwsh" if subprocess.run(["where", "pwsh"], capture_output=True).stdout else "powershell"
                    subprocess.run([pwsh_exe, "-NoProfile", "-Command", ps_command], check=True, capture_output=True if not args.verbose else False)
                else:
                    log_print("INFO", "PowerShell not found, attempting 'setx'.")
                    # setx truncates to 1024 chars. This is a limitation.
                    subprocess.run(['setx', 'PATH', new_path_value], check=True)
                    log_print("SUCCESS", f"Successfully requested update for User PATH using 'setx'.")
                
                log_print("IMPORTANT", "PATH change will apply to new terminal sessions. You may need to restart your terminal or log out and log back in.")

        except FileNotFoundError:
            log_print("ERROR", "Could not find 'reg' or 'setx'/'powershell'. Cannot automatically update PATH on Windows.")
            log_print("INFO", f"Please add '{bin_path_to_add}' to your User PATH environment variable manually.")
        except subprocess.CalledProcessError as e:
            log_print("ERROR", f"Failed to update User PATH environment variable: {e}")
            if e.stderr: log_print("ERROR", f"Stderr: {e.stderr}")
            if e.stdout: log_print("INFO", f"Stdout: {e.stdout}")
            log_print("INFO", f"Please add '{bin_path_to_add}' to your User PATH environment variable manually.")
        except Exception as e:
            log_print("ERROR", f"An unexpected error occurred while updating Windows PATH: {e}")
            log_print("INFO", f"Please add '{bin_path_to_add}' to your User PATH environment variable manually.")

    else: # Zsh/Linux/macOS (POSIX-like)
        log_print("INFO", "POSIX-like OS detected (Linux, macOS, or other Unix-like).")
        shell_name = os.environ.get("SHELL", "").split("/")[-1]
        if args.verbose:
            log_print("INFO", f"Detected SHELL: {shell_name}")

        # Currently, this script only explicitly supports Zsh for POSIX.
        # Other shells would require different config files (e.g., .bashrc, .profile).
        if "zsh" in shell_name.lower() or True: # Defaulting to Zsh-like behavior for now if not Windows
            config_file_path = args.dotfiles_dir / "dynamic/setup_path.zsh"
            config_file_path.parent.mkdir(parents=True, exist_ok=True)
            path_export_line = f'export PATH="{bin_path_to_add}{path_separator}$PATH"\n'

            write_changes = True
            if config_file_path.exists():
                with open(config_file_path, "r", encoding="utf-8") as f:
                    if path_export_line in f.read(): # Crude check, assumes line uniqueness
                        log_print("SUCCESS", f"'{bin_path_to_add}' export line already exists in {config_file_path}.")
                        write_changes = False
            
            if write_changes:
                try:
                    with open(config_file_path, "w", encoding="utf-8") as f: # Overwrite to ensure it's the only/main one
                        f.write(f"# Added by setup_path.py\n")
                        f.write(path_export_line)
                    log_print("SUCCESS", f"Updated Zsh PATH configuration in: {config_file_path}")
                    log_print("INFO", f"To apply in current Zsh session, run: source {config_file_path}")
                    log_print("INFO", "Or open a new Zsh terminal.")
                except IOError as e:
                    log_print("ERROR", f"Could not write to {config_file_path}: {e}")
                    log_print("INFO", f"Please add '{path_export_line.strip()}' to your Zsh configuration manually.")
            
            # Attempt to source for current Zsh session if possible (won't affect parent calling script's env)
            # This is more for immediate feedback than lasting effect on the setup script's own process
            if "zsh" in shell_name.lower() and write_changes:
                try:
                    # This will only affect subprocesses of this script, not the calling shell.
                    # The user still needs to source it in their active terminal.
                    if args.verbose:
                        log_print("INFO", f"Attempting to have Zsh parse {config_file_path} (effects limited to sub-shells of this script).")
                    # subprocess.run(["zsh", "-c", f"source {config_file_path}"], check=True, capture_output=True)
                    # log_print("INFO", f"Successfully had a Zsh sub-shell source {config_file_path}.")
                except subprocess.CalledProcessError as e:
                    log_print("WARNING", f"Could not have Zsh sub-shell source {config_file_path}: {e}")
        else:
            log_print("WARNING", f"Unsupported shell '{shell_name}' for automatic PATH configuration.")
            log_print("INFO", f"Please add '{str(bin_path_to_add)}' to your PATH manually for your shell.")

if __name__ == "__main__":
    main()
