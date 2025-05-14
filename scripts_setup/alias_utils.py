#!/usr/bin/env python3
import re
import subprocess
from pathlib import Path # <--- CRUCIAL IMPORT FOR Path

RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RESET = "\033[0m"

def _log_warning(message: str): # Added type hint for clarity
    print(f"{YELLOW}⚠️ {message}{RESET}")

def command_exists(command: str) -> bool:
    try:
        base_command_for_check = command.split()[0]
        # Check if it's a file path first
        if Path(base_command_for_check).is_absolute() or \
           (Path.cwd() / base_command_for_check).exists(): # Check relative to CWD too
            if (Path.cwd() / base_command_for_check).is_file() or Path(base_command_for_check).is_file():
                # For a direct file path, os.access might be more reliable for executability
                # import os
                # return os.access(str(Path(base_command_for_check).resolve()), os.X_OK)
                return True # Simplified: if it's a file, assume it might be executable

        result = subprocess.run(
            ["zsh", "-c", f"command -v {base_command_for_check}"],
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0
    except Exception as e:
        _log_warning(f"Could not check command existence for `{base_command_for_check}`: {e}")
        return False

def get_executable_path(bin_dir: Path, script_filename_from_alias_file: str) -> Path:
    name_to_process = script_filename_from_alias_file
    
    if name_to_process.endswith(".py%"):
        name_to_process = name_to_process[:-3] 
    elif name_to_process.endswith("%") and not name_to_process.endswith(".py%"):
        name_to_process = name_to_process[:-1]

    base_name = name_to_process
    known_extensions = [".py", ".sh", ".pl", ".rb"] 
    for ext_to_strip in known_extensions:
        if name_to_process.endswith(ext_to_strip):
            base_name = name_to_process[:-len(ext_to_strip)]
            break 
            
    return bin_dir / base_name

def parse_alias_file(alias_file: Path) -> list:
    parsed_aliases = []
    if not alias_file.exists():
        _log_warning(f"Alias file not found: {alias_file}. Skipping alias setup.")
        return parsed_aliases
        
    with open(alias_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            parts = [p.strip() for p in line.split(":", 2)] 
            
            script_file = ""
            alias_name = ""
            args_str = ""

            if len(parts) >= 2: 
                script_file = parts[0]
                alias_name = parts[1]
                if len(parts) == 3: 
                    args_str = parts[2]
            else: 
                _log_warning(f"Invalid alias format in {alias_file} (line {line_num}). Expected 'source_script : alias_name : [arguments]' or 'source_script : alias_name'. Line: '{line}'")
                continue

            if not script_file:
                _log_warning(f"Invalid format in {alias_file} (line {line_num}): Source script name missing. Line: '{line}'")
                continue
            if not alias_name:
                _log_warning(f"Invalid format in {alias_file} (line {line_num}): Desired alias name missing. Line: '{line}'")
                continue
            
            parsed_aliases.append((script_file, alias_name, args_str))
            
    return parsed_aliases

def get_existing_aliases(alias_config: Path) -> dict:
    aliases = {}
    if not alias_config.exists():
        return aliases
    try:
        with open(alias_config, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("alias "):
                    match = re.match(r"alias\s+([^=]+)=(['\"])(.*?)\2", line)
                    if match:
                        name = match.group(1).strip()
                        value = match.group(3).strip()
                        aliases[name] = value
    except FileNotFoundError:
        _log_warning(f"Alias configuration file {alias_config} not found during get_existing_aliases (should have been caught by exists()).")
    except Exception as e:
        _log_warning(f"Error reading alias configuration file {alias_config}: {e}")
    return aliases

def write_aliases(
    parsed_alias_definitions: list, 
    bin_dir: Path, 
    alias_config: Path, 
    alias_file_path_for_header: str, 
    verbose: bool = False
) -> None:
    temp_aliases_lines = []
    existing_aliases_map = get_existing_aliases(alias_config)
    newly_created_or_changed = {}
    aliases_to_process = {} 

    for script_file_from_parser, desired_alias_name, args_string in parsed_alias_definitions:
        base_executable_command_path = get_executable_path(bin_dir, script_file_from_parser)
        full_command_for_alias = str(base_executable_command_path)
        if args_string: 
            full_command_for_alias += f" {args_string.strip()}"
            
        if desired_alias_name in aliases_to_process:
            _log_warning(f"Duplicate alias name '{desired_alias_name}' defined in {Path(alias_file_path_for_header).name}. Using last definition for script '{script_file_from_parser}'.")
        aliases_to_process[desired_alias_name] = full_command_for_alias.strip()

    sorted_alias_names = sorted(aliases_to_process.keys())

    for alias_name in sorted_alias_names:
        command_string = aliases_to_process[alias_name]
        if alias_name in existing_aliases_map and existing_aliases_map[alias_name] == command_string:
            if verbose: print(f"🔹 Alias unchanged: {alias_name} : {command_string}")
        else:
            old_cmd_display = ""
            if alias_name in existing_aliases_map:
                newly_created_or_changed[alias_name] = (command_string, existing_aliases_map[alias_name])
                old_cmd_display = f" (was: {existing_aliases_map[alias_name]})"
                if verbose: print(f"🔄 Alias updated: {alias_name} : {command_string}{old_cmd_display}")
            else: 
                newly_created_or_changed[alias_name] = (command_string, None)
                if verbose: print(f"✨ Alias created: {alias_name} : {command_string}")
        temp_aliases_lines.append(f'alias {alias_name}="{command_string}"')

    try:
        alias_config.parent.mkdir(parents=True, exist_ok=True)
        with open(alias_config, "w", encoding="utf-8") as f:
            f.write(f"# Generated by alias_utils.py from {Path(alias_file_path_for_header).name}\n\n")
            f.write("\n".join(temp_aliases_lines) + "\n")
        print(f"{GREEN}✅ Aliases written to {alias_config}.{RESET}")
    except Exception as e:
        _log_warning(f"Could not write aliases to {alias_config}: {e}")
        return

    print("---------- Alias Definitions Summary ----------")
    if not newly_created_or_changed and not verbose: print("No new or changed aliases.")
    elif not newly_created_or_changed and verbose:
        if aliases_to_process: print("All defined aliases were existing and unchanged.")
        else: print(f"No aliases were defined to process from {Path(alias_file_path_for_header).name}.")
    
    if newly_created_or_changed:
        if not verbose: print("New or Changed Aliases:")
        for alias, (new_cmd, old_cmd) in sorted(newly_created_or_changed.items()):
            if not verbose :
                if old_cmd is not None: print(f"    🔄 {alias} : {new_cmd} (was: {old_cmd})")
                else: print(f"    ✨ {alias} : {new_cmd}")
    
    if verbose and not newly_created_or_changed and aliases_to_process: 
        print("Processed aliases (all were existing and unchanged):")
        for alias_name in sorted_alias_names: print(f"    {alias_name} : {aliases_to_process[alias_name]}")
    
    if not aliases_to_process and not newly_created_or_changed: 
        if not verbose:
            print(f"No alias definitions were found/processed from {Path(alias_file_path_for_header).name}.")
        
    print("---------------------------------------------")
    
    try:
        if command_exists("zsh"):
            source_command = f"source {alias_config}"
            print(f"{GREEN}✅ Aliases updated. To apply in your current Zsh session, run: {RESET}{YELLOW}{source_command}{RESET}")
        else:
            _log_warning(f"zsh not found. Please source {alias_config} manually in your shell.")
    except Exception as e:
        _log_warning(f"Automatic sourcing of aliases might not have taken full effect. Error: {e}")
