#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
import argparse
import sys 
import re 

# Basic print logging for this script
def log_print(level, message, verbose_flag=False):
    # For this script, let's print ERROR and WARNING always, INFO if verbose_flag
    if level.upper() == "INFO" and not verbose_flag:
        return
    # IMPORTANT messages should always be printed.
    if level.upper() == "IMPORTANT":
        print(f"[{level.upper()}] {message}")
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

    verbose = args.verbose

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
        log_print("INFO", "Windows OS detected for PATH update.", verbose)
        try:
            # Get current User PATH from registry
            completed_process = subprocess.run(
                ['reg', 'query', r'HKCU\Environment', '/v', 'Path'],
                capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore'
            )
            current_user_path_str = ""
            if completed_process.returncode == 0 and completed_process.stdout:
                regex_pattern = r"^\s*Path\s+REG_(?:EXPAND_)?SZ\s+(.*)$"
                for line in completed_process.stdout.splitlines():
                    match = re.search(regex_pattern, line.strip(), re.IGNORECASE)
                    if match:
                        current_user_path_str = match.group(1).strip()
                        break
            log_print("INFO", f"Current User PATH from registry: '{current_user_path_str}'", verbose)

            current_path_elements = [p for p in current_user_path_str.split(path_separator) if p.strip()]
            path_to_add_str = str(bin_path_to_add)

            if path_to_add_str in current_path_elements:
                log_print("SUCCESS", f"{path_to_add_str} is already in the User PATH environment variable (Registry).", verbose)
            else:
                log_print("INFO", f"Adding {path_to_add_str} to User PATH environment variable.", verbose)
                
                # Append new path, then join and deduplicate
                new_path_list = current_path_elements + [path_to_add_str]
                # Deduplicate while preserving order as much as possible (keeping first occurrence)
                # For PATH, usually new items are appended.
                # To strictly ensure no duplicates and append if missing:
                final_path_elements = []
                seen_paths = set()
                for p_item in new_path_list:
                    if p_item not in seen_paths:
                        final_path_elements.append(p_item)
                        seen_paths.add(p_item)
                new_path_value = path_separator.join(final_path_elements)

                is_pwsh_available = bool(subprocess.run("where pwsh", capture_output=True, shell=True, check=False).stdout or \
                                         subprocess.run("where powershell", capture_output=True, shell=True, check=False).stdout)

                if is_pwsh_available:
                    log_print("INFO", "Using PowerShell to update User PATH.", verbose)
                    ps_command_parts = [
                        '$envName = "User";', '$varName = "Path";', f'$valueToAdd = "{path_to_add_str}";',
                        '$currentPath = [System.Environment]::GetEnvironmentVariable($varName, $envName);',
                        # Ensure $currentPath is not null before splitting
                        '$pathElements = if ($currentPath) {{ @($currentPath -split [System.IO.Path]::PathSeparator | Where-Object {{ $_ -ne "" }}) }} else {{ @() }};',
                        'if ($pathElements -notcontains $valueToAdd) {',
                        '  $newPathElements = $pathElements + $valueToAdd;',
                        '  $newPath = $newPathElements -join [System.IO.Path]::PathSeparator;',
                        '  [System.Environment]::SetEnvironmentVariable($varName, $newPath, $envName);',
                        '  Write-Host "Successfully updated User PATH via PowerShell.";',
                        '} else { Write-Host ($valueToAdd + " already in User PATH (PowerShell check)."); }'
                    ]
                    ps_command = " ".join(ps_command_parts)
                    pwsh_exe = "pwsh" if subprocess.run("where pwsh", capture_output=True, shell=True, check=False).stdout else "powershell"
                    
                    ps_proc = subprocess.run([pwsh_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command], 
                                             check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    log_print("INFO", f"PowerShell output: {ps_proc.stdout.strip()}", verbose)
                    if ps_proc.stderr.strip() and verbose: log_print("WARNING", f"PowerShell stderr: {ps_proc.stderr.strip()}", verbose)
                else:
                    log_print("INFO", "PowerShell not found, attempting 'setx'. Note: 'setx' has a 1024 character limit for the variable value.", verbose)
                    # Using setx will replace the entire PATH with new_path_value.
                    # It's important new_path_value was constructed from the full existing path.
                    subprocess.run(['setx', 'PATH', new_path_value], check=True)
                    log_print("SUCCESS", "Successfully requested update for User PATH using 'setx'.", verbose)
                
                log_print("IMPORTANT", "PATH change will apply to new terminal sessions. You may need to restart your terminal or log out/in.", verbose_flag=True)

        except FileNotFoundError: # For 'reg' or 'setx'
            log_print("ERROR", "Could not find 'reg' or 'setx'. Cannot automatically update PATH on Windows.", verbose_flag=True)
            log_print("INFO", f"Please add '{str(bin_path_to_add)}' to your User PATH environment variable manually.", verbose_flag=True)
        except subprocess.CalledProcessError as e:
            log_print("ERROR", f"Failed to update User PATH environment variable: {e}", verbose_flag=True)
            if hasattr(e, 'stderr') and e.stderr: log_print("ERROR", f"Stderr: {e.stderr}", verbose_flag=True)
            if hasattr(e, 'stdout') and e.stdout: log_print("INFO", f"Stdout: {e.stdout}", verbose_flag=True)
            log_print("INFO", f"Please add '{str(bin_path_to_add)}' to your User PATH environment variable manually.", verbose_flag=True)
        except Exception as e:
            log_print("ERROR", f"An unexpected error occurred while updating Windows PATH: {type(e).__name__}: {e}", verbose_flag=True)
            log_print("INFO", f"Please add '{str(bin_path_to_add)}' to your User PATH environment variable manually.", verbose_flag=True)
    else: 
        log_print("INFO", "POSIX-like OS detected for PATH update.", verbose)
        shell_name = os.environ.get("SHELL", "").split("/")[-1]
        log_print("INFO", f"Detected SHELL: {shell_name}", verbose)

        if "zsh" in shell_name.lower():
            config_file_path = args.dotfiles_dir.resolve() / "dynamic/setup_path.zsh"
            config_file_path.parent.mkdir(parents=True, exist_ok=True)
            path_export_line = f'export PATH="{bin_path_to_add}{path_separator}$PATH"\n'
            write_changes = True
            if config_file_path.exists():
                try:
                    if path_export_line in config_file_path.read_text(encoding="utf-8"):
                        log_print("SUCCESS", f"PATH export line for '{bin_path_to_add}' already in {config_file_path}.", verbose)
                        write_changes = False
                except Exception as e_read:
                    log_print("WARNING", f"Could not read {config_file_path} to check for existing line: {e_read}", verbose)
            
            if write_changes:
                try:
                    with open(config_file_path, "w", encoding="utf-8") as f:
                        f.write(f"# Added by scripts_setup/setup_path.py\n{path_export_line}")
                    log_print("SUCCESS", f"Updated Zsh PATH configuration in: {config_file_path}", verbose)
                    log_print("IMPORTANT", f"To apply in current Zsh session, run: source '{config_file_path}'", verbose_flag=True)
                except IOError as e:
                    log_print("ERROR", f"Could not write to {config_file_path}: {e}", verbose_flag=True)
                    log_print("INFO", f"Please add manually: {path_export_line.strip()}", verbose_flag=True)
        else:
            log_print("WARNING", f"Unsupported shell '{shell_name}' for automatic PATH config. This script primarily handles Zsh for POSIX.", verbose_flag=True)
            log_print("INFO", f"Please add '{str(bin_path_to_add)}' to your PATH manually for shell '{shell_name}'.", verbose_flag=True)

if __name__ == "__main__":
    main()
