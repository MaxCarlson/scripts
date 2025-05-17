import os
import subprocess
from pathlib import Path
import argparse
import sys 
import re # Import the 're' module for regular expressions

# Basic print logging for this script
def log_print(level, message, verbose_flag=False):
    if level == "INFO" and not verbose_flag: # Only print INFO if verbose
        return
    print(f"[{level.upper()}] {message}")

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
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed output during PATH setup."
    )
    args = parser.parse_args()

    verbose = args.verbose # Store verbosity

    bin_path_to_add = args.bin_dir.resolve()
    log_print("INFO", f"Target bin directory: {bin_path_to_add}", verbose)
    log_print("INFO", f"Dotfiles directory: {args.dotfiles_dir}", verbose)

    current_path_env = os.environ.get("PATH", "")
    path_separator = os.pathsep

    if str(bin_path_to_add) in current_path_env.split(path_separator):
        log_print("SUCCESS", f"{bin_path_to_add} is already in the current session's PATH.", verbose)
    else:
        log_print("INFO", f"{bin_path_to_add} not found in current session's PATH. Will attempt to add to shell config.", verbose)


    if os.name == "nt":
        log_print("INFO", "Windows OS detected.", verbose)
        try:
            completed_process = subprocess.run(
                ['reg', 'query', r'HKCU\Environment', '/v', 'Path'],
                capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore'
            )
            
            current_user_path = ""
            if completed_process.returncode == 0 and completed_process.stdout:
                # Corrected line: Use re.search, not Path().search
                # Regex to find 'Path REG_SZ <value>' or 'Path REG_EXPAND_SZ <value>'
                # Making it case-insensitive for 'Path' and tolerant of extra spaces around REG_SZ
                regex_pattern = r"^\s*Path\s+REG_(?:EXPAND_)?SZ\s+(.*)$"
                # Search line by line
                for line in completed_process.stdout.splitlines():
                    match = re.search(regex_pattern, line.strip(), re.IGNORECASE)
                    if match:
                        current_user_path = match.group(1).strip()
                        break # Found the path line
            
            log_print("INFO", f"Current User PATH from registry: '{current_user_path}'", verbose)

            if str(bin_path_to_add) in current_user_path.split(path_separator):
                log_print("SUCCESS", f"{bin_path_to_add} is already in the User PATH environment variable (Registry).", verbose)
            else:
                log_print("INFO", f"Adding {bin_path_to_add} to User PATH environment variable.", verbose)
                new_path_value = f"{current_user_path}{path_separator}{bin_path_to_add}" if current_user_path and current_user_path[-1] != path_separator else \
                                 f"{current_user_path}{bin_path_to_add}" if current_user_path else \
                                 str(bin_path_to_add)
                
                # Deduplicate, preserving order of existing, then adding new if not present
                existing_paths = current_user_path.split(path_separator) if current_user_path else []
                if str(bin_path_to_add) not in existing_paths:
                    updated_paths = existing_paths + [str(bin_path_to_add)]
                    # Filter out empty strings that might result from os.pathsep at end of string
                    new_path_value = path_separator.join(filter(None, updated_paths))
                else: # Already there (should have been caught by earlier check, but good to be robust)
                    new_path_value = current_user_path


                is_pwsh_available = bool(subprocess.run(["where", "pwsh"], capture_output=True, shell=True).stdout or \
                                      subprocess.run(["where", "powershell"], capture_output=True, shell=True).stdout)

                if is_pwsh_available:
                    log_print("INFO", "Using PowerShell to update User PATH.", verbose)
                    ps_command_parts = [
                        '$envName = "User";',
                        '$varName = "Path";',
                        f'$valueToAdd = "{str(bin_path_to_add)}";',
                        '$currentPath = [System.Environment]::GetEnvironmentVariable($varName, $envName);',
                        '$pathElements = @($currentPath -split [System.IO.Path]::PathSeparator);',
                        'if ($pathElements -notcontains $valueToAdd) {',
                        '  if ([string]::IsNullOrEmpty($currentPath) -or $currentPath.EndsWith([System.IO.Path]::PathSeparator)) {',
                        '    $newPath = $currentPath + $valueToAdd;',
                        '  } else {',
                        '    $newPath = $currentPath + [System.IO.Path]::PathSeparator + $valueToAdd;',
                        '  }',
                        '  [System.Environment]::SetEnvironmentVariable($varName, $newPath, $envName);',
                        '  Write-Host "Successfully updated User PATH via PowerShell.";',
                        '} else { Write-Host ($valueToAdd + " already in User PATH (PowerShell check)."); }'
                    ]
                    ps_command = " ".join(ps_command_parts)
                    pwsh_exe = "pwsh" if subprocess.run(["where", "pwsh"], capture_output=True, shell=True).stdout else "powershell"
                    
                    # Use shell=True for `where` if it's a built-in, but not for execution of pwsh itself if possible
                    # However, for simplicity here if `where` needs it, pwsh execution might also benefit.
                    # For security, better to use full paths if known or ensure pwsh_exe is just "pwsh" or "powershell".
                    run_args = [pwsh_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command]

                    ps_proc = subprocess.run(run_args, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    log_print("INFO", f"PowerShell output: {ps_proc.stdout.strip()}", verbose)
                    if ps_proc.stderr.strip():
                        log_print("WARNING", f"PowerShell stderr: {ps_proc.stderr.strip()}", verbose)

                else:
                    log_print("INFO", "PowerShell not found, attempting 'setx'. This has a 1024 char limit.", verbose)
                    subprocess.run(['setx', 'PATH', new_path_value], check=True) # setx PATH "%PATH%;NEW_DIR"
                    log_print("SUCCESS", "Successfully requested update for User PATH using 'setx'.", verbose)
                
                log_print("IMPORTANT", "PATH change will apply to new terminal sessions. You may need to restart your terminal or log out/in.", verbose_flag=True) # Always print this

        except FileNotFoundError:
            log_print("ERROR", "Could not find 'reg' or 'setx'/'powershell'. Cannot automatically update PATH on Windows.", verbose_flag=True)
            log_print("INFO", f"Please add '{bin_path_to_add}' to your User PATH environment variable manually.", verbose_flag=True)
        except subprocess.CalledProcessError as e:
            log_print("ERROR", f"Failed to update User PATH environment variable: {e}", verbose_flag=True)
            if e.stderr: log_print("ERROR", f"Stderr: {e.stderr}", verbose_flag=True)
            if e.stdout: log_print("INFO", f"Stdout: {e.stdout}", verbose_flag=True)
            log_print("INFO", f"Please add '{bin_path_to_add}' to your User PATH environment variable manually.", verbose_flag=True)
        except Exception as e:
            log_print("ERROR", f"An unexpected error occurred while updating Windows PATH: {e} (Type: {type(e).__name__})", verbose_flag=True)
            log_print("INFO", f"Please add '{bin_path_to_add}' to your User PATH environment variable manually.", verbose_flag=True)

    else: 
        log_print("INFO", "POSIX-like OS detected (Linux, macOS, or other Unix-like).", verbose)
        shell_name = os.environ.get("SHELL", "").split("/")[-1]
        log_print("INFO", f"Detected SHELL: {shell_name}", verbose)

        if "zsh" in shell_name.lower():
            config_file_path = args.dotfiles_dir / "dynamic/setup_path.zsh"
            config_file_path.parent.mkdir(parents=True, exist_ok=True)
            path_export_line = f'export PATH="{bin_path_to_add}{path_separator}$PATH"\n'

            write_changes = True
            if config_file_path.exists():
                try:
                    if path_export_line in config_file_path.read_text(encoding="utf-8"):
                        log_print("SUCCESS", f"'{bin_path_to_add}' export line already exists in {config_file_path}.", verbose)
                        write_changes = False
                except Exception as e:
                    log_print("WARNING", f"Could not read {config_file_path} to check for existing line: {e}", verbose)
            
            if write_changes:
                try:
                    with open(config_file_path, "w", encoding="utf-8") as f:
                        f.write(f"# Added by setup_path.py\n")
                        f.write(path_export_line)
                    log_print("SUCCESS", f"Updated Zsh PATH configuration in: {config_file_path}", verbose)
                    log_print("INFO", f"To apply in current Zsh session, run: source {config_file_path}", verbose_flag=True) # Always print this
                except IOError as e:
                    log_print("ERROR", f"Could not write to {config_file_path}: {e}", verbose_flag=True)
                    log_print("INFO", f"Please add '{path_export_line.strip()}' to your Zsh configuration manually.", verbose_flag=True)
        else:
            log_print("WARNING", f"Unsupported shell '{shell_name}' for automatic PATH configuration. This script primarily handles Zsh for POSIX.", verbose_flag=True)
            log_print("INFO", f"Please add '{str(bin_path_to_add)}' to your PATH manually for your shell.", verbose_flag=True)

if __name__ == "__main__":
    main()
