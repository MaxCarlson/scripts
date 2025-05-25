#!/usr/bin/env python3
import sys
import re
import argparse
from pathlib import Path
from cross_platform.clipboard_utils import get_clipboard
from rich.console import Console
from rich.table import Table

console_stdout = Console()
console_stderr = Console(stderr=True)

# Renamed to parser_cr to avoid potential name collisions if tests import multiple scripts
parser_cr = argparse.ArgumentParser(
    description="Replaces a Python function or class block in a specified file with the content from the clipboard. The function/class name is determined from the clipboard content.",
    formatter_class=argparse.RawTextHelpFormatter
)
parser_cr.add_argument(
    "file",
    help="Path to the Python file to be modified."
)
parser_cr.add_argument(
    "--no-stats",
    action="store_true",
    help="Suppress statistics output."
)

def extract_function_name(code: str):
    m = re.search(r"^\s*(?:@[^\n]+\n)*\s*(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", code, re.MULTILINE)
    if not m:
        console_stderr.print("Clipboard content does not appear to be a Python def/class. Aborting.", style="bold red")
        sys.exit(1) 
    return m.group(2)

def replace_python_block(lines, func_name, new_block_content):
    block_stats = {"original_lines_in_block": 0, "new_lines_in_block": 0}
    start_idx = None
    block_indent_level = None 
    block_start_line_idx = -1
    
    for i, line_text in enumerate(lines):
        match_def_class = re.match(rf"^\s*(def|class)\s+{func_name}\b", line_text)
        if match_def_class:
            block_start_line_idx = i
            block_indent_level = len(line_text) - len(line_text.lstrip())
            start_idx = i
            for j in range(i - 1, -1, -1):
                if re.match(r"^\s*@", lines[j]):
                    decorator_indent = len(lines[j]) - len(lines[j].lstrip())
                    if decorator_indent <= block_indent_level:
                         start_idx = j
                    else: break
                elif lines[j].strip() == "": continue
                else: break
            break

    if start_idx is None or block_start_line_idx == -1:
        console_stderr.print(f"Function/class '{func_name}' not found. Aborting.", style="bold red")
        sys.exit(1)

    for i_check in range(block_start_line_idx + 1, len(lines)):
         if re.match(rf"^\s*(def|class)\s+{func_name}\b", lines[i_check]):
            console_stderr.print(f"Error: Multiple definitions of '{func_name}' found. Aborting.", style="bold red")
            sys.exit(1)

    end_idx = block_start_line_idx + 1
    while end_idx < len(lines):
        line_content = lines[end_idx]
        if line_content.strip():
            current_line_indent = len(line_content) - len(line_content.lstrip())
            if current_line_indent <= block_indent_level: break
        end_idx += 1
    
    block_stats["original_lines_in_block"] = (end_idx - start_idx)
    new_block_lines_with_newlines = [ln + "\n" for ln in new_block_content.rstrip("\n").split("\n")]
    block_stats["new_lines_in_block"] = len(new_block_lines_with_newlines)
    updated_file_lines = lines[:start_idx] + new_block_lines_with_newlines + lines[end_idx:]
    return updated_file_lines, block_stats

def run_clipboard_replace(file_path_str: str, no_stats: bool):
    stats_data = {}
    operation_successful = False
    exit_code = 0

    try:
        file_path_obj = Path(file_path_str)
        stats_data["File Path"] = str(file_path_obj.resolve())

        try:
            clipboard_content = get_clipboard()
        except NotImplementedError as nie:
            stats_data["Error"] = "Clipboard functionality (get_clipboard) not implemented."
            console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
            exit_code = 1
            raise # Propagate to main finally
        except Exception as e_get_clip:
            stats_data["Error"] = f"Failed to get clipboard content: {e_get_clip}"
            console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
            exit_code = 1
            raise # Propagate to main finally
            
        if not clipboard_content:
            stats_data["Clipboard Status"] = "Empty"
            console_stderr.print("Clipboard is empty. Aborting.", style="bold red")
            exit_code = 1 
        else:
            stats_data["Clipboard Chars"] = len(clipboard_content)
            stats_data["Clipboard Lines"] = len(clipboard_content.splitlines())

            func_name_to_replace = extract_function_name(clipboard_content) 
            stats_data["Target Name (from clipboard)"] = func_name_to_replace
            
            if not file_path_obj.exists():
                stats_data["File Status"] = "Not found"
                console_stderr.print(f"Error: File '{file_path_obj}' not found. Aborting.", style="bold red")
                exit_code = 1
            elif exit_code == 0: # Proceed only if no prior critical errors
                stats_data["File Status"] = "Exists"
                original_file_lines = file_path_obj.read_text(encoding="utf-8").splitlines(keepends=True)
                
                updated_lines, block_stats = replace_python_block(original_file_lines, func_name_to_replace, clipboard_content)
                stats_data.update(block_stats)

                try:
                    with open(file_path_obj, "w", encoding="utf-8") as f:
                        f.writelines(updated_lines)
                    operation_successful = True
                    console_stdout.print(f"Replaced '{func_name_to_replace}' successfully in '{file_path_obj}'.")
                    stats_data["Outcome"] = "Success"
                    stats_data["Lines in Original File"] = len(original_file_lines)
                    stats_data["Lines in Updated File"] = len(updated_lines)
                except Exception as e_write:
                    stats_data["Error"] = f"Error writing to file '{file_path_obj}': {e_write}"
                    console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                    exit_code = 1
        
        if exit_code == 0 and not operation_successful: # Should not be hit if file ops fail and set exit_code
             stats_data.setdefault("Warning", "Operation marked unsuccessful without specific error.")
             exit_code = 1


    except SystemExit: 
        if exit_code == 0: exit_code = 1 # Ensure error code if helper exited
        stats_data.setdefault("Outcome", "Failed (aborted by helper function)")
    except Exception as e: 
        if exit_code == 0: exit_code = 1
        error_message = f"An unexpected error occurred: {e}"
        stats_data.setdefault("Error", error_message)
        # Avoid double printing if console_stderr already printed it in a helper
        # This is tricky; for now, let specific error handlers print.
        # console_stderr.print(f"[bold red]{error_message}[/]", style="bold red")

    finally:
        if not no_stats:
            table = Table(title="clipboard_replace.py Statistics")
            table.add_column("Metric", style="cyan", overflow="fold")
            table.add_column("Value", overflow="fold")
            stats_data.setdefault("Outcome", "Failed" if exit_code !=0 else "Unknown")
            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            console_stdout.print(table)
        
        sys.exit(exit_code)

if __name__ == "__main__":
    args = parser_cr.parse_args()
    run_clipboard_replace(args.file, args.no_stats)
