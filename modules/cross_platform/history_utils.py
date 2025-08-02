# cross_platform/history_utils.py
# No changes to this file this round, the existing diagnostics should now work with the fixed test mock.
import os
import platform
import subprocess
import argparse
import sys
import shlex
from pathlib import Path # This is the Path that will be mocked in tests

from .system_utils import SystemUtils
from .debug_utils import write_debug, console # console is imported here

class HistoryUtils(SystemUtils):
    """
    Provides utilities to access and parse shell history
    for extracting recently used paths.
    Works with PowerShell 7, bash, and zsh.
    """

    def __init__(self):
        super().__init__()
        self.shell_type = self._get_shell_type()
        write_debug(f"HistoryUtils initialized for shell type: {self.shell_type}", channel="Debug")

    def _get_shell_type(self) -> str:
        """Detects the current shell environment."""
        if self.os_name == "windows":
            write_debug("Detected Windows, assuming PowerShell.", channel="Information")
            return "powershell"
        
        shell_env_path = os.environ.get("SHELL", "")
        shell_path_obj = Path(shell_env_path) 
        shell_name = shell_path_obj.name.lower() 

        if "zsh" == shell_name:
            write_debug("Detected Zsh from SHELL env.", channel="Information")
            return "zsh"
        elif "bash" == shell_name:
            write_debug("Detected Bash from SHELL env.", channel="Information")
            return "bash"
        else:
            write_debug(f"Could not determine shell from SHELL env: {shell_env_path} (name: {shell_name}). Trying fallback.", channel="Warning")
            if self.os_name == "darwin" and os.path.exists("/bin/zsh"):
                write_debug("Defaulting to Zsh for macOS based on path existence.", channel="Debug")
                return "zsh"
            elif self.os_name == "linux" and os.path.exists("/bin/bash"):
                write_debug("Defaulting to Bash for Linux based on path existence.", channel="Debug")
                return "bash"
            else: 
                if os.path.exists("/bin/bash"): 
                    write_debug("Defaulting to Bash based on /bin/bash existence (generic fallback).", channel="Debug")
                    return "bash"
                elif os.path.exists("/bin/zsh"): 
                    write_debug("Defaulting to Zsh based on /bin/zsh existence (generic fallback).", channel="Debug")
                    return "zsh"
                write_debug("Could not reliably determine shell type via fallbacks.", channel="Error")
                return "unknown"


    def _get_history_file_path(self) -> str | None:
        """Determines the path to the shell history file."""
        history_file_str = None 
        if self.shell_type == "powershell":
            try:
                cmd_pwsh = "pwsh -NoProfile -Command \"(Get-PSReadlineOption).HistorySavePath\""
                cmd_powershell = "powershell -NoProfile -Command \"(Get-PSReadlineOption).HistorySavePath\""
                path_output = None
                
                try:
                    write_debug(f"Attempting to get PS history path with: {cmd_pwsh}", channel="Debug")
                    path_output = self.run_command(cmd_pwsh)
                except FileNotFoundError:
                    write_debug("pwsh command not found.", channel="Warning")
                
                if not path_output or not path_output.strip():
                    write_debug(f"Attempting to get PS history path with: {cmd_powershell}", channel="Debug")
                    try:
                        path_output = self.run_command(cmd_powershell)
                    except FileNotFoundError:
                        write_debug("powershell command not found.", channel="Warning")

                if path_output and path_output.strip():
                    history_file_str = path_output.strip()
                else:
                    app_data = os.getenv("APPDATA")
                    if app_data:
                        fallback_path = os.path.join(app_data, "Microsoft", "Windows", "PowerShell", "PSReadLine", "ConsoleHost_history.txt")
                        if os.path.exists(fallback_path): 
                            history_file_str = fallback_path
                            write_debug(f"Falling back to default PSReadLine history path: {history_file_str}", channel="Debug")
                        else:
                             write_debug(f"Default PSReadLine history path not found: {fallback_path}", channel="Debug")
                    if not history_file_str: 
                        write_debug("PowerShell history path could not be determined.", channel="Warning")
            except Exception as e:
                write_debug(f"Error getting PowerShell history path: {e}", channel="Error")
                return None 
        
        elif self.shell_type == "zsh":
            histfile_env = os.environ.get("HISTFILE")
            if histfile_env:
                history_file_str = os.path.expanduser(histfile_env)
                write_debug(f"Zsh HISTFILE env var set to: {histfile_env}, expanded to: {history_file_str}", channel="Debug")
            else:
                history_file_str = os.path.expanduser("~/.zsh_history")
                write_debug(f"Zsh HISTFILE env var not set, using default: {history_file_str}", channel="Debug")

            if not os.path.exists(history_file_str):
                write_debug(f"Primary zsh history file not found: {history_file_str}", channel="Debug")
                if history_file_str == os.path.expanduser("~/.zsh_history"):
                    alt_histfile = os.path.expanduser("~/.histfile")
                    write_debug(f"Trying alternative zsh history file: {alt_histfile}", channel="Debug")
                    if os.path.exists(alt_histfile):
                        history_file_str = alt_histfile
            
        elif self.shell_type == "bash":
            histfile_env = os.environ.get("HISTFILE")
            if histfile_env:
                history_file_str = os.path.expanduser(histfile_env)
            else:
                history_file_str = os.path.expanduser("~/.bash_history")
        
        if history_file_str and os.path.exists(history_file_str): 
            write_debug(f"Using history file: {history_file_str} for shell: {self.shell_type}", channel="Information")
            return history_file_str
        else:
            write_debug(f"History file for shell '{self.shell_type}' not found or path is invalid. Path checked: '{history_file_str}'", channel="Warning")
            return None

    def _extract_paths_from_history_lines(self, lines: list[str]) -> list[str]:
        """Extracts unique, existing paths from a list of history command lines."""
        extracted_paths = []
        processed_lines = 0
        for line_content in reversed(lines): 
            processed_lines += 1
            line_content = line_content.strip()
            if not line_content:
                continue

            if self.shell_type == "zsh" and line_content.startswith(": ") and ";" in line_content:
                try:
                    line_content = line_content.split(";", 1)[1]
                except IndexError:
                    write_debug(f"Skipping malformed zsh history line: {line_content[:50]}...", channel="Verbose")
                    continue 

            try:
                args = shlex.split(line_content)
            except ValueError: 
                args = line_content.split()
                write_debug(f"shlex failed for line: '{line_content[:50]}...', using simple split.", channel="Verbose")

            for arg_candidate in args:
                if not arg_candidate or arg_candidate.startswith("-") or \
                   arg_candidate.startswith("http:") or arg_candidate.startswith("https:"):
                    continue
                
                if "=" in arg_candidate and self.shell_type != "powershell":
                    if not any(c in arg_candidate for c in ['/', '\\', '.']): 
                        write_debug(f"Checking existence of assignment-like arg: '{arg_candidate}'", channel="Verbose")
                        if not Path(arg_candidate).exists(): 
                            write_debug(f"Assignment-like arg '{arg_candidate}' does not exist as a path. Skipping.", channel="Verbose")
                            continue
                
                try:
                    write_debug(f"Processing arg_candidate: '{arg_candidate}'", channel="Verbose")
                    current_path_str = os.path.expanduser(arg_candidate)
                    write_debug(f"Expanded arg_candidate '{arg_candidate}' to current_path_str: '{current_path_str}'", channel="Verbose")
                    
                    path_obj = Path(current_path_str) 
                    
                    # ---- START DIAGNOSTIC BLOCK ----
                    exists_result_for_if_condition = None
                    path_obj_str_for_diag = f"Error_getting_str(path_obj_for_{current_path_str})" # Default
                    
                    try:
                        path_obj_str_for_diag = str(path_obj) 
                        # This call will trigger the print from verbose_exists_logic in the test mock
                        exists_result_for_if_condition = path_obj.exists() 
                    except Exception as e_diag:
                        write_debug(f"DIAGNOSTIC_ERROR_PRE_LOG: Exception during str(path_obj) or path_obj.exists() for arg '{current_path_str}'. Error: {e_diag}", channel="Critical")
                        exists_result_for_if_condition = False # Default to false on error path
                    
                    # This log MUST appear if the code reaches here.
                    write_debug(
                        f"DIAGNOSTIC_RESULT: current_path_str='{current_path_str}', path_obj_str='{path_obj_str_for_diag}', "
                        f"exists_call_returned='{exists_result_for_if_condition}', "
                        f"type_of_exists_call_returned='{type(exists_result_for_if_condition).__name__}'",
                        channel="Critical" 
                    )
                    # ---- END DIAGNOSTIC BLOCK ----
                    
                    if exists_result_for_if_condition: # Use the explicitly captured and logged result
                        write_debug(
                            f"IF_CONDITION_MET: Path '{current_path_str}' (from Path obj: '{path_obj_str_for_diag}') is being processed.", 
                            channel="Verbose"
                        )
                        abs_path_str = str(path_obj.resolve()) # This call will trigger VERBOSE_RESOLVE_LOGIC
                        write_debug(
                            f"DIAGNOSTIC_RESOLVE: Path obj '{path_obj_str_for_diag}' resolved to abs_path_str: '{abs_path_str}' "
                            f"(type: {type(abs_path_str).__name__})", 
                            channel="Critical"
                        )
                        
                        if abs_path_str not in extracted_paths:
                            extracted_paths.append(abs_path_str)
                            write_debug(f"Found and added path: {abs_path_str} from arg: '{arg_candidate}'", channel="Debug")
                        else:
                            write_debug(f"Path '{abs_path_str}' (from arg '{arg_candidate}') already extracted. Skipping.", channel="Verbose")
                    else:
                        write_debug(
                            f"IF_CONDITION_NOT_MET: Path '{current_path_str}' (from Path obj: '{path_obj_str_for_diag}'). "
                            f"exists_result_for_if_condition was '{exists_result_for_if_condition}'.", 
                            channel="Verbose"
                        )
                        
                except RuntimeError as e: 
                    write_debug(f"Could not resolve path for argument '{arg_candidate}': {e}", channel="Warning")
                except Exception as e: # This catches broader errors in the try block for an arg_candidate
                    write_debug(f"Error processing argument '{arg_candidate}' as path: {e}", channel="Error") 
                    continue 
        
        write_debug(f"Processed {processed_lines} history lines, extracted {len(extracted_paths)} unique paths.", channel="Debug")
        if extracted_paths: 
             write_debug(f"Extracted paths: {extracted_paths}", channel="Verbose")
        return extracted_paths

    def get_nth_recent_path(self, n: int) -> str | None:
        if not isinstance(n, int) or n <= 0:
            write_debug("N must be a positive integer.", channel="Error")
            return None

        history_file_path = self._get_history_file_path()
        if not history_file_path:
            write_debug("No history file path found, cannot retrieve paths.", channel="Error")
            return None

        try:
            with open(history_file_path, "r", errors="ignore", encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            write_debug(f"Error reading history file {history_file_path}: {e}", channel="Error")
            return None 
        
        if not lines:
            write_debug(f"History file {history_file_path} is empty or unreadable.", channel="Warning")
            return None

        all_paths = self._extract_paths_from_history_lines(lines)
        
        if 0 < n <= len(all_paths):
            path_to_return = all_paths[n-1]
            write_debug(f"Returning {n}th recent path: {path_to_return}", channel="Information")
            return path_to_return
        else:
            write_debug(f"Could not find {n}th recent path. Requested N={n}, Found {len(all_paths)} unique paths.", channel="Warning")
            return None

def main():
    parser = argparse.ArgumentParser(
        description="Get the Nth most recent, unique, existing path from shell history.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Cross-platform (PowerShell 7, bash, zsh).

Examples:
  python -m cross_platform.history_utils -N 1
  (Get the most recent valid path from history)

  python -m cross_platform.history_utils --number 5
  (Get the 5th most recent valid path from history)
"""
    )
    parser.add_argument(
        "-N", "--number", 
        type=int, 
        required=True, 
        help="The Nth most recent path to retrieve (1-indexed)."
    )
    
    args = parser.parse_args()

    history_util = HistoryUtils()
    path = history_util.get_nth_recent_path(args.number)

    if path:
        console.print(path) 
    else:
        message = f"Error: Could not retrieve the {args.number}th (1-indexed) recent path."
        console.print(f"[bold red]{message}[/]", stderr=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
