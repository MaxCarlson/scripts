#!/usr/bin/env python3

import sys
import os
import argparse
from pathlib import Path
from rich.console import Console
from rich.table import Table

# Module-level console for consistent output
console_info = Console(stderr=True) # For progress messages and errors
console_stats = Console()      # For the final stats table

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
        "  %(prog)s -r file1.txt file2.txt\n"
        "  %(prog)s --append my_snippet.py\n\n"
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
    '-a', '--append', action='store_true',
    help="Append to existing clipboard content instead of overwriting. "
         "Intelligently appends into the last detected code block if possible."
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
    help="Copy raw concatenated content. Overrides -w, -f, and smart append formatting."
)
parser.add_argument(
    "--no-stats", action="store_true", help="Suppress statistics output."
)

def copy_files_to_clipboard(
    file_paths_str: list[str],
    show_full_path: bool,
    force_wrap: bool,
    raw_copy: bool,
    append: bool,
    no_stats: bool
):
    stats_data = {}
    exit_code = 0 
    
    file_paths = [Path(p) for p in file_paths_str]
    text_to_copy_initially = "" # Content generated from files
    successful_files_count = 0
    is_single_file_input = (len(file_paths) == 1)
    input_file_count = len(file_paths)
    operation_description_for_stats = ""
    current_dir = Path.cwd()

    if append:
        stats_data["Append Mode"] = "Enabled"
    else:
        stats_data["Append Mode"] = "Disabled"

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
            text_to_copy_initially = "".join(content_parts)
            operation_description_for_stats = f"Raw concatenated content from {successful_files_count} of {input_file_count} file(s)."

        elif is_single_file_input and not force_wrap:
            stats_data["Mode"] = "Single File (Raw Content)"
            file_path_obj = file_paths[0]
            console_info.print(f"[INFO] Processing single file for raw copy: '{file_path_obj}'")
            try:
                text_to_copy_initially = file_path_obj.read_text(encoding='utf-8')
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
            text_to_copy_initially = "\n\n".join(processed_blocks)
            operation_description_for_stats = f"Wrapped content from {successful_files_count} of {input_file_count} file(s)."

        if exit_code != 0 and successful_files_count == 0 and is_single_file_input:
            raise IOError("Primary file processing failed, cannot proceed to clipboard operations.") 

        if not operation_description_for_stats:
            operation_description_for_stats = f"Content from {successful_files_count} of {input_file_count} file(s)."
        stats_data["Operation Summary"] = operation_description_for_stats
        stats_data["Input Files Specified"] = input_file_count
        stats_data["Files Successfully Processed"] = successful_files_count
        stats_data["Files Failed/Skipped"] = input_file_count - successful_files_count
        
        final_text_for_clipboard = text_to_copy_initially
        original_clipboard_text_for_append = None # Store for later if needed

        if append and successful_files_count > 0: # Only attempt append if there's new content
            stats_data["Append Attempted"] = "Yes"
            try:
                original_clipboard_text_for_append = get_clipboard()
                stats_data["Original Clipboard Read For Append"] = "Success"
                
                if not text_to_copy_initially: # New content is empty
                    final_text_for_clipboard = original_clipboard_text_for_append if original_clipboard_text_for_append else ""
                    console_info.print("[INFO] New content is empty, clipboard remains unchanged (append mode).")
                    stats_data["Append Action"] = "Skipped (new content was empty), clipboard unchanged"
                elif original_clipboard_text_for_append: # Both old and new content exist
                    stripped_original_clipboard = original_clipboard_text_for_append.rstrip()
                    # Smart append into code block (not for raw_copy mode)
                    if not raw_copy and stripped_original_clipboard.endswith('\n```'):
                        insertion_point = stripped_original_clipboard.rfind('\n```')
                        clipboard_prefix = stripped_original_clipboard[:insertion_point]
                        
                        separator = '\n' 
                        if not clipboard_prefix or clipboard_prefix.endswith('\n'):
                            separator = '' 
                        
                        final_text_for_clipboard = clipboard_prefix + separator + text_to_copy_initially + '\n```'
                        
                        if len(original_clipboard_text_for_append) > len(stripped_original_clipboard):
                            final_text_for_clipboard += original_clipboard_text_for_append[len(stripped_original_clipboard):]
                        
                        console_info.print("[INFO] Appended new content into the last detected code block of existing clipboard content.")
                        stats_data["Append Action"] = "Appended into existing code block"
                    else: # General append (or raw_copy mode)
                        final_text_for_clipboard = original_clipboard_text_for_append.rstrip('\n') + '\n\n' + text_to_copy_initially
                        console_info.print("[INFO] Appended new content to existing clipboard content with a newline separator.")
                        stats_data["Append Action"] = "General append"
                else: # Original clipboard was empty, new content exists
                    # final_text_for_clipboard is already text_to_copy_initially
                    stats_data["Original Clipboard Read For Append"] = "Empty, normal copy"
                    console_info.print("[INFO] Clipboard was empty; performing normal copy (append mode).")
                    stats_data["Append Action"] = "Normal copy (clipboard was empty)"

            except NotImplementedError:
                console_info.print("[WARNING] Could not get clipboard content for append. Performing normal copy.")
                stats_data["Original Clipboard Read For Append"] = "Failed (NotImplementedError)"
                stats_data["Append Action"] = "Skipped (get_clipboard NI), normal copy performed"
                # final_text_for_clipboard remains text_to_copy_initially
            except Exception as e_get_clip_append:
                console_info.print(f"[WARNING] Error getting clipboard for append: {e_get_clip_append}. Performing normal copy.")
                stats_data["Original Clipboard Read For Append"] = f"Failed (Error: {e_get_clip_append})"
                stats_data["Append Action"] = "Skipped (get_clipboard error), normal copy performed"
                # final_text_for_clipboard remains text_to_copy_initially
        elif append: # Append was true, but no successful files or no initial text
            stats_data["Append Attempted"] = "Yes"
            if not successful_files_count > 0:
                 stats_data["Append Action"] = "Skipped (no files processed)"
            elif not text_to_copy_initially: # Should be caught by above if append was true
                 stats_data["Append Action"] = "Skipped (new content was initially empty)"
        
        num_lines_payload = len(final_text_for_clipboard.splitlines()) if final_text_for_clipboard else 0
        chars_in_payload = len(final_text_for_clipboard) if final_text_for_clipboard else 0
        
        stats_data["Lines in Clipboard Payload"] = num_lines_payload
        stats_data["Characters in Clipboard Payload"] = chars_in_payload
        
        clipboard_action_status = "Not Attempted (No content or no successful files)"

        # Determine if clipboard operation should proceed
        # If append mode and new content was empty, and clipboard had content,
        # we might not want to call set_clipboard if it's identical to original.
        # However, current logic will call set_clipboard with original_clipboard_text.
        # For simplicity, we'll always attempt to set if there's *something* to set,
        # or if append was intended but new content was empty (to restore original).
        
        should_set_clipboard = False
        if successful_files_count > 0: # If any files were processed to generate text_to_copy_initially
            should_set_clipboard = True
        elif append and original_clipboard_text_for_append is not None and not text_to_copy_initially:
            # Append mode, new content empty, but original clipboard had content (or was empty but read)
            # We set `final_text_for_clipboard` to `original_clipboard_text_for_append`
            should_set_clipboard = True 
            if not final_text_for_clipboard: # If original was also empty
                 clipboard_action_status = "Not Attempted (Clipboard and new content were empty in append mode)"


        if should_set_clipboard:
            console_info.print(f"[INFO] Attempting to copy to clipboard ({num_lines_payload} lines, {chars_in_payload} chars).")
            try:
                set_clipboard(final_text_for_clipboard) 
                clipboard_action_status = "Set Succeeded (Verification pending)"

                try: 
                    actual_clipboard_content = get_clipboard()
                    copied_lines_found = len(actual_clipboard_content.splitlines())
                    copied_chars_found = len(actual_clipboard_content)
                    verification_msg = ""
                    if actual_clipboard_content == final_text_for_clipboard:
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
        
        elif input_file_count > 0 and successful_files_count == 0 and not append: 
             # Only log this if not in append mode where original clipboard might be "kept"
             console_info.print("[INFO] No content successfully processed from any files. Clipboard not updated.")
             clipboard_action_status = "Not Attempted (no successful file reads)"
             if exit_code == 0:
                exit_code = 1 

        stats_data["Clipboard Action Status"] = clipboard_action_status
        
        final_non_default_ops_messages = []
        if append:
            final_non_default_ops_messages.append("Append mode enabled")
        if raw_copy:
            final_non_default_ops_messages.append("Raw copy mode enabled (filenames, paths, and wrapping are disabled)")
        elif is_single_file_input and force_wrap:
            final_non_default_ops_messages.append("Forced wrapping of single file in code block")
            if show_full_path:
                 final_non_default_ops_messages.append("Displaying full absolute paths above each code block")
        elif not is_single_file_input: 
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
            if not isinstance(outer_e, (IOError, NotImplementedError)):
                 console_info.print(f"[bold red][CRITICAL ERROR] {outer_e}[/]")

    finally:
        if not no_stats:
            console_stats.print("") 
            table = Table(title="copy_to_clipboard.py Statistics")
            table.add_column("Metric", style="cyan", overflow="fold")
            table.add_column("Value", overflow="fold")
            
            stats_data.setdefault("Mode", "Unknown due to early error")
            stats_data.setdefault("Append Mode", "Disabled (or error before check)")
            stats_data.setdefault("Append Attempted", "No (or error before check)")
            stats_data.setdefault("Original Clipboard Read For Append", "N/A")
            stats_data.setdefault("Append Action", "N/A")
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
        append=args.append,
        no_stats=args.no_stats
    )
    sys.exit(final_exit_code)
