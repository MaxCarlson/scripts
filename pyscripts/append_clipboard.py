#!/usr/bin/env python3

import sys
import argparse
from pathlib import Path
from cross_platform.clipboard_utils import get_clipboard
from rich.console import Console
from rich.table import Table

console_stdout = Console()
console_stderr = Console(stderr=True)

parser = argparse.ArgumentParser(
    description="Appends the contents of the clipboard to the end of a specified file.",
    formatter_class=argparse.RawTextHelpFormatter
)
parser.add_argument(
    "file",
    help="Path to the file to which clipboard contents will be appended."
)
parser.add_argument(
    "--no-stats",
    action="store_true",
    help="Suppress statistics output."
)

def append_clipboard_to_file(file_path_str: str, no_stats: bool):
    stats_data = {}
    operation_successful = False
    exit_code = 0

    try:
        file_path_obj = Path(file_path_str)
        stats_data["File Path"] = str(file_path_obj.resolve())

        try:
            clipboard_text = get_clipboard()
        except NotImplementedError as nie:
            stats_data["Error"] = "Clipboard functionality (get_clipboard) not implemented."
            console_stderr.print(f"[bold red][ERROR] {stats_data['Error']} Ensure clipboard utilities are installed and accessible.[/]")
            exit_code = 1
            raise
        except Exception as e_get_clip:
            stats_data["Error"] = f"Failed to get clipboard content: {e_get_clip}"
            console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
            exit_code = 1
            raise

        if not clipboard_text:
            stats_data["Clipboard Status"] = "Empty"
            stats_data["Outcome"] = "No changes made as clipboard was empty."
            console_stderr.print("Clipboard is empty. Aborting.") # User message to stderr
            operation_successful = True 
        else:
            stats_data["Clipboard Status"] = f"Contains {len(clipboard_text)} chars, {len(clipboard_text.splitlines())} lines"
            
            text_to_append = "\n" + clipboard_text
            
            file_existed_and_had_content = file_path_obj.exists() and file_path_obj.stat().st_size > 0
            
            if not file_path_obj.exists():
                stats_data["File Action"] = "Created new file (as it was appended to)"
                console_stderr.print(f"Note: File '{file_path_obj}' did not exist, it will be created.")
            else:
                stats_data["File Action"] = "Appended to existing file"


            try:
                with open(file_path_obj, "a", encoding="utf-8") as f:
                    chars_appended = f.write(text_to_append)
                operation_successful = True
                console_stdout.print(f"Appended clipboard contents to '{file_path_obj}'.")
                stats_data["Chars Appended"] = chars_appended 
                stats_data["Lines Appended (from clipboard)"] = len(clipboard_text.splitlines())
                stats_data["Total Lines Written to file"] = len(text_to_append.splitlines())
                stats_data["Outcome"] = "Successfully appended."
            except Exception as e_write:
                stats_data["Error"] = f"Error writing to file '{file_path_obj}': {e_write}"
                console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                exit_code = 1
        
        if exit_code == 0 and not operation_successful:
             stats_data.setdefault("Warning", "Operation did not complete as expected but no specific error caught.")
             exit_code = 1


    except Exception: 
        if exit_code == 0: exit_code = 1
        if "Error" not in stats_data : 
            stats_data["Error"] = f"An unexpected error occurred: {sys.exc_info()[1]}"


    finally:
        if not no_stats:
            if not stats_data: 
                 stats_data["Status"] = "No operation performed or stats collected due to very early error."

            table = Table(title="append_clipboard.py Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", overflow="fold")
            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            console_stdout.print(table) 

        sys.exit(exit_code)

if __name__ == "__main__":
    args = parser.parse_args()
    append_clipboard_to_file(args.file, args.no_stats)
