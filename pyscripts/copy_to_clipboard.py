#!/usr/bin/env python3

import sys
import os
import argparse
from pathlib import Path
from rich.console import Console
from rich.table import Table

# Module-level console for consistent output
# Messages to user (INFO, WARNING, ERROR during processing) can go to stderr
# Final stats table goes to stdout.
console_info = Console(stderr=True) # For progress messages and errors
console_stats = Console()      # For the final stats table

# Attempt to import clipboard utils, critical for this script
try:
    from cross_platform.clipboard_utils import set_clipboard, get_clipboard
except ImportError:
    console_info.print("[bold red][ERROR] The 'cross_platform.clipboard_utils' module was not found.[/]")
    console_info.print("    Please ensure it is installed and accessible in your Python environment.")
    sys.exit(1)


parser = argparse.ArgumentParser(
    description=(
        "Copies file content to the clipboard.\n"
        "Default (1 file): Raw content is copied.\n"
        "Default (>1 file): Contents are combined, each prefixed with its relative path and wrapped in code fences (```).\n"
        "Use --raw-copy to get purely concatenated content without any paths or wrapping."
    ),
    formatter_class=argparse.RawTextHelpFormatter,
    epilog=(
        "Usage Examples:\n"
        "  %(prog)s my_doc.txt\n"
        "  %(prog)s chap1.txt chap2.txt\n"
        "  %(prog)s -w report.md\n"
        "  %(prog)s -f script.py lib.py\n"
        "  %(prog)s -r file1.txt file2.txt\n\n"
        "The behavior changes based on the number of files and options provided."
    )
)
parser.add_argument(
    'files',
    metavar='FILE',
    nargs='+',
    help="Path to one or more files."
)
parser.add_argument(
    '-w', '--force-wrap', action='store_true',
    help="Force wrap a single file's content."
)
parser.add_argument(
    '-f', '--show-full-path', action='store_true',
    help="When wrapping, also include the file's absolute path."
)
parser.add_argument(
    '-r', '--raw-copy', action='store_true',
    help="Copy raw concatenated content. Overrides -w and -f."
)
parser.add_argument(
    "--no-stats", action="store_true", help="Suppress statistics output."
)

def copy_files_to_clipboard(
    file_paths_str: list[str],
    show_full_path: bool,
    force_wrap: bool,
    raw_copy: bool,
    no_stats: bool
):
    stats_data = {}
    exit_code = 0 
    
    file_paths = [Path(p) for p in file_paths_str]
    text_to_copy = ""
    successful_files_count = 0
    is_single_file_input = (len(file_paths) == 1)
    input_file_count = len(file_paths)
    operation_description_for_stats = ""
    current_dir = Path.cwd()

    try: 
        if raw_copy:
            stats_data["Mode"] = "Raw Concatenation"
            console_info.print(f"[INFO] Raw copy mode active. Processing {input_file_count} file(s) for raw concatenation.")
            content_parts = []
            for file_path_obj in file_paths:
                try:
                    content_parts.append(file_path_obj.read_text(encoding='utf-8'))
                    successful_files_count += 1
                    console_info.print(f"[INFO] Successfully read '{file_path_obj}' for raw concatenation.")
                except FileNotFoundError:
                    console_info.print(f"[WARNING] File not found: '{file_path_obj}'. Skipping.")
                except Exception as e:
                    console_info.print(f"[WARNING] Could not read file '{file_path_obj}': {e}. Skipping.")
            text_to_copy = "".join(content_parts)
            operation_description_for_stats = f"Raw concatenated content from {successful_files_count} of {input_file_count} file(s)."

        elif is_single_file_input and not force_wrap:
            stats_data["Mode"] = "Single File (Raw Content)"
            file_path_obj = file_paths[0]
            console_info.print(f"[INFO] Processing single file for raw copy: '{file_path_obj}'")
            try:
                text_to_copy = file_path_obj.read_text(encoding='utf-8')
                successful_files_count = 1
                console_info.print(f"[INFO] Successfully read '{file_path_obj}'.")
                operation_description_for_stats = f"Raw content from 1 file ('{file_path_obj}')"
            except FileNotFoundError:
                console_info.print(f"[bold red][ERROR] File not found: '{file_path_obj}'. Nothing will be copied.[/]")
                exit_code = 1 
            except Exception as e:
                console_info.print(f"[bold red][ERROR] Could not read file '{file_path_obj}': {e}. Nothing will be copied.[/]")
                exit_code = 1
        
        else: # Wrapped mode (multiple files, or single file with --force-wrap)
            mode_desc_parts = []
            if is_single_file_input and force_wrap:
                mode_desc_parts.append("Single File (Forced Wrap)")
            elif not is_single_file_input:
                mode_desc_parts.append(f"Multiple Files ({input_file_count} initially)")
            mode_desc_parts.append("Aggregated (Code Fences)")

            if show_full_path:
                mode_desc_parts.append("with Full & Relative Paths")
            else:
                mode_desc_parts.append("with Relative Paths")
            stats_data["Mode"] = ", ".join(filter(None, mode_desc_parts))

            processed_blocks = []
            console_info.print(f"[INFO] Processing {input_file_count} file(s) for aggregated copy with code fences.")
            for file_path_obj in file_paths:
                try:
                    file_content = file_path_obj.read_text(encoding='utf-8')
                    abs_path_str = str(file_path_obj.resolve())
                    rel_path_str = os.path.relpath(file_path_obj, current_dir)
                    header_lines = [abs_path_str] if show_full_path else []
                    header_lines.append(rel_path_str)
                    header = "\n".join(header_lines)
                    processed_blocks.append(f"{header}\n```\n{file_content}\n```")
                    successful_files_count += 1
                    console_info.print(f"[INFO] Processed '{file_path_obj}' into code block.")
                except FileNotFoundError:
                    console_info.print(f"[WARNING] File not found: '{file_path_obj}'. Skipping this file.")
                except Exception as e:
                    console_info.print(f"[WARNING] Could not read file '{file_path_obj}': {e}. Skipping this file.")
            text_to_copy = "\n\n".join(processed_blocks)
            operation_description_for_stats = f"Wrapped content from {successful_files_count} of {input_file_count} file(s)."

        # If file reading itself failed critically for single file mode, and nothing was read.
        if exit_code != 0 and successful_files_count == 0 and is_single_file_input:
            raise IOError("Primary file processing failed, cannot proceed to clipboard operations.") 

        if not operation_description_for_stats:
            operation_description_for_stats = f"Content from {successful_files_count} of {input_file_count} file(s)."
        stats_data["Operation Summary"] = operation_description_for_stats
        stats_data["Input Files Specified"] = input_file_count
        stats_data["Files Successfully Processed"] = successful_files_count
        stats_data["Files Failed/Skipped"] = input_file_count - successful_files_count
        
        num_lines_payload = len(text_to_copy.splitlines()) if text_to_copy else 0
        chars_in_payload = len(text_to_copy) if text_to_copy else 0
        stats_data["Lines in Clipboard Payload"] = num_lines_payload
        stats_data["Characters in Clipboard Payload"] = chars_in_payload
        
        clipboard_action_status = "Not Attempted (No content or no successful files)"

        if successful_files_count > 0:
            console_info.print(f"[INFO] Attempting to copy to clipboard ({num_lines_payload} lines, {chars_in_payload} chars).")
            try:
                set_clipboard(text_to_copy) 
                clipboard_action_status = "Set Succeeded (Verification pending)"

                try: 
                    actual_clipboard_content = get_clipboard()
                    copied_lines_found = len(actual_clipboard_content.splitlines())
                    copied_chars_found = len(actual_clipboard_content)
                    verification_msg = ""
                    if actual_clipboard_content == text_to_copy:
                        verification_msg = "[SUCCESS] Clipboard copy complete and content verified."
                        clipboard_action_status = "Set & Verified OK"
                    elif copied_chars_found == chars_in_payload and copied_lines_found == num_lines_payload:
                        verification_msg = (f"[INFO] Clipboard content size matches. Minor differences possible.")
                        clipboard_action_status = "Set & Verified (Size Match)"
                    elif copied_lines_found < num_lines_payload or copied_chars_found < chars_in_payload:
                        verification_msg = (f"[WARNING] Clipboard content may be truncated/incomplete.")
                        clipboard_action_status = "Set & Verified (Potential Truncation)"
                    else:
                        verification_msg = (f"[WARNING] Clipboard content has more data than expected.")
                        clipboard_action_status = "Set & Verified (Potential Alteration)"
                    console_info.print(verification_msg)
                except NotImplementedError: 
                    console_info.print("[INFO] get_clipboard not implemented. Skipping verification.")
                    clipboard_action_status = "Set Succeeded (Verification NI)" 
                except Exception as e_get_clipboard:
                    console_info.print(f"[WARNING] Could not verify clipboard content: {e_get_clipboard}")
                    clipboard_action_status = "Set Succeeded (Verification Failed)"

            except NotImplementedError: 
                error_msg = "set_clipboard is not implemented in clipboard_utils. Cannot copy content."
                stats_data["Error"] = error_msg
                console_info.print(f"[bold red][ERROR] {error_msg}[/]")
                clipboard_action_status = "Set Failed (Not Implemented)"
                exit_code = 1 
                raise 
            except Exception as e_set_clipboard:
                error_msg = f"Failed to set clipboard content: {e_set_clipboard}"
                stats_data["Error"] = error_msg
                console_info.print(f"[bold red][ERROR] {error_msg}[/]")
                clipboard_action_status = f"Set Failed: {e_set_clipboard}"
                exit_code = 1 
                raise 
        
        elif input_file_count > 0 and successful_files_count == 0: 
             console_info.print("[INFO] No content successfully processed from any files. Clipboard not updated.")
             clipboard_action_status = "Not Attempted (no successful file reads)"
             if exit_code == 0: # Ensure error if not already set (e.g., by single file read fail)
                exit_code = 1 

        stats_data["Clipboard Action Status"] = clipboard_action_status
        
        final_non_default_ops_messages = []
        if raw_copy:
            final_non_default_ops_messages.append("Raw copy mode enabled (filenames, paths, and wrapping are disabled)")
        elif is_single_file_input and force_wrap:
            final_non_default_ops_messages.append("Forced wrapping of single file in code block")
            if show_full_path:
                 final_non_default_ops_messages.append("Displaying full absolute paths above each code block")
        elif not is_single_file_input: # Multiple files
            final_non_default_ops_messages.append(f"Wrapping content of {successful_files_count if successful_files_count > 0 else input_file_count} file(s) in code blocks with relative paths")
            if show_full_path:
                 final_non_default_ops_messages.append("Displaying full absolute paths above each code block")

        if final_non_default_ops_messages:
            console_info.print("\n[CHANGES FROM DEFAULT BEHAVIOR]")
            for op_msg in final_non_default_ops_messages:
                console_info.print(f"- {op_msg}")
    
    except Exception as outer_e: 
        if exit_code == 0: exit_code = 1 
        if "Error" not in stats_data: 
            stats_data["Error"] = f"A critical error occurred: {outer_e}"
            # Only print critical error if it's not one of the re-raised, already-logged types
            if not isinstance(outer_e, (IOError, NotImplementedError)):
                 console_info.print(f"[bold red][CRITICAL ERROR] {outer_e}[/]")

    finally:
        if not no_stats:
            console_stats.print("") 
            table = Table(title="copy_to_clipboard.py Statistics")
            table.add_column("Metric", style="cyan", overflow="fold")
            table.add_column("Value", overflow="fold")
            
            stats_data.setdefault("Mode", "Unknown due to early error")
            stats_data.setdefault("Operation Summary", "Incomplete due to error")
            _input_file_count_val = locals().get('input_file_count', 'N/A')
            _successful_files_count_val = locals().get('successful_files_count', 'N/A')
            
            stats_data.setdefault("Input Files Specified", _input_file_count_val)
            stats_data.setdefault("Files Successfully Processed", _successful_files_count_val)
            if isinstance(_input_file_count_val, int) and isinstance(_successful_files_count_val, int):
                stats_data.setdefault("Files Failed/Skipped", _input_file_count_val - _successful_files_count_val)
            else:
                stats_data.setdefault("Files Failed/Skipped", 'N/A')

            stats_data.setdefault("Lines in Clipboard Payload", stats_data.get("Lines in Clipboard Payload",0))
            stats_data.setdefault("Characters in Clipboard Payload", stats_data.get("Characters in Clipboard Payload",0))
            stats_data.setdefault("Clipboard Action Status", "Unknown due to error")

            for key, value in stats_data.items():
                table.add_row(str(key), str(value))
            console_stats.print(table)
        
        return exit_code


if __name__ == '__main__':
    args = parser.parse_args()
    final_exit_code = copy_files_to_clipboard(
        args.files,
        show_full_path=args.show_full_path,
        force_wrap=args.force_wrap,
        raw_copy=args.raw_copy,
        no_stats=args.no_stats
    )
    sys.exit(final_exit_code)
