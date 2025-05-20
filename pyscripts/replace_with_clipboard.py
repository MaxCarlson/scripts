#!/usr/bin/env python3

import sys
import argparse
from pathlib import Path
from cross_platform.clipboard_utils import get_clipboard
from rich.console import Console
from rich.table import Table

# Global console instances
console_stdout = Console()
console_stderr = Console(stderr=True) # Dedicated console for stderr messages

# Module-level parser for potential test access, though runner fixtures are preferred.
# Initialized in __main__ is also fine if tests don't need direct parser access.
parser = argparse.ArgumentParser(
    description="Replaces file contents with clipboard data, or prints clipboard to stdout if no file is specified.",
    formatter_class=argparse.RawTextHelpFormatter
)
parser.add_argument(
    "file",
    nargs="?",
    default=None,
    help="Path to the file whose contents will be replaced. If omitted, clipboard contents are printed to stdout."
)
parser.add_argument(
    "--no-stats",
    action="store_true",
    help="Suppress statistics output."
)

def replace_or_print_clipboard(file_path_str: str | None, no_stats: bool):
    stats_data = {}
    operation_successful = False
    exit_code = 0 # Default to success

    # Determine console for stats based on operation mode
    # If printing to stdout, stats go to stderr. Otherwise, stats go to stdout.
    stats_console = console_stderr if file_path_str is None else console_stdout

    try:
        try:
            clipboard_text = get_clipboard() # This can raise NotImplementedError or other critical errors
        except NotImplementedError as nie:
            stats_data["Error"] = "Clipboard functionality (get_clipboard) not implemented."
            console_stderr.print(f"[bold red][ERROR] {stats_data['Error']} Ensure clipboard utilities are installed and accessible.[/]", style="bold red")
            exit_code = 1
            raise # Re-raise to go to finally block and then exit
        except Exception as e_get_clip:
            stats_data["Error"] = f"Failed to get clipboard content: {e_get_clip}"
            console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]", style="bold red")
            exit_code = 1
            raise

        if not clipboard_text:
            stats_data["Status"] = "Clipboard is empty. Aborting."
            console_stderr.print(stats_data["Status"], style="bold red") # User message
            exit_code = 1 # Empty clipboard is an actionable issue for this script
        else:
            stats_data["Clipboard Content"] = f"{len(clipboard_text)} chars, {len(clipboard_text.splitlines())} lines"

            if file_path_str is None: # Print to stdout mode
                stats_data["Operation Mode"] = "Print to stdout"
                try:
                    # sys.stdout.write is used to avoid rich console formatting for piped output
                    sys.stdout.write(clipboard_text)
                    sys.stdout.flush()
                    operation_successful = True
                    stats_data["Chars Printed"] = len(clipboard_text)
                    stats_data["Lines Printed"] = len(clipboard_text.splitlines())
                except Exception as e_print:
                    stats_data["Error"] = f"Error printing to stdout: {e_print}"
                    console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                    exit_code = 1
            
            else: # Replace file content mode
                stats_data["Operation Mode"] = "Replace file content"
                file_path_obj = Path(file_path_str)
                stats_data["File Path"] = str(file_path_obj.resolve())
                
                created_new_file = False
                original_content_desc = "File did not exist"

                if not file_path_obj.exists():
                    message = f"File '{file_path_obj}' does not exist. Creating new file."
                    console_stdout.print(message) # User message to stdout
                    stats_data["File Action"] = "Created new file"
                    created_new_file = True
                else:
                    try:
                        original_text = file_path_obj.read_text(encoding="utf-8")
                        original_content_desc = f"{len(original_text)} chars, {len(original_text.splitlines())} lines"
                        stats_data["File Action"] = "Overwritten existing file"
                    except Exception as e_read_orig:
                        original_content_desc = f"Could not read original for stats: {e_read_orig}"
                    stats_data["Original Content (approx)"] = original_content_desc

                content_to_write = clipboard_text.rstrip("\n") + "\n"
                
                try:
                    with open(file_path_obj, "w", encoding="utf-8") as f:
                        chars_written = f.write(content_to_write)
                    operation_successful = True
                    console_stdout.print(f"Replaced contents of '{file_path_obj}' with clipboard data.")
                    stats_data["Chars Written"] = chars_written
                    stats_data["Lines Written"] = len(content_to_write.splitlines())
                    if created_new_file:
                         stats_data["Note"] = "File was newly created."
                except Exception as e_write:
                    stats_data["Error"] = f"Error writing to file '{file_path_obj}': {e_write}"
                    console_stderr.print(f"[bold red][ERROR] {stats_data['Error']}[/]")
                    exit_code = 1
        
        if exit_code == 0 and not operation_successful and file_path_str is not None : # If not print mode and op not successful
            # This case might occur if clipboard was empty for file mode
             if not clipboard_text: # Handled by exit_code = 1 above
                 pass
             else: # Should not happen if logic is correct
                 stats_data.setdefault("Warning", "Operation did not complete as expected but no specific error caught.")
                 exit_code = 1


    except Exception: # Catch re-raised exceptions or new ones
        if exit_code == 0: exit_code = 1 # Ensure error exit code if an exception bubbles up
        # Error message should have been printed by the raising point or above
        if "Error" not in stats_data and "Status" not in stats_data: # Generic fallback
            stats_data["Error"] = f"An unexpected error occurred: {sys.exc_info()[1]}"


    finally:
        if not no_stats:
            if not stats_data:
                 stats_data["Status"] = "No operation performed or stats collected due to early error."

            table = Table(title="replace_with_clipboard.py Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", overflow="fold")

            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            
            stats_console.print(table) # Use the determined console for stats
        
        sys.exit(exit_code)


if __name__ == "__main__":
    args = parser.parse_args()
    replace_or_print_clipboard(args.file, args.no_stats)
