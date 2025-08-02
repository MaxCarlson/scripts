#!/usr/bin/env python3

import sys
import os
import argparse
import re 
from pathlib import Path
from rich.console import Console
from rich.table import Table

console_info = Console(stderr=True)
console_stats = Console()

try:
    from cross_platform.clipboard_utils import set_clipboard, get_clipboard
except ImportError:
    console_info.print("[bold red][ERROR] The 'cross_platform.clipboard_utils' module was not found.[/]")
    console_info.print("    Please ensure it is installed and accessible in your Python environment.")
    sys.exit(1)

WHOLE_WRAP_HEADER_MARKER = "WHOLE_CLIPBOARD_CONTENT_BLOCK_V1"

parser = argparse.ArgumentParser(
    description=(
        "Copies file content to the clipboard with flexible wrapping and appending options."
    ),
    formatter_class=argparse.RawTextHelpFormatter,
    epilog=(
        "Usage Examples:\n"
        "  %(prog)s my_doc.txt                                   # Raw copy of single file\n"
        "  %(prog)s chap1.txt chap2.txt                          # Individually wraps chap1 & chap2 by default\n"
        "  %(prog)s -w report.md                                 # Individually wraps report.md\n"
        "  %(prog)s -W report.md chap1.txt                       # Wraps combined content of report & chap1 in one marked block\n"
        "  %(prog)s -r file1.txt file2.txt                       # Raw concatenated content\n"
        "  %(prog)s -a my_snippet.py                             # Append snippet, intelligently\n"
        "  %(prog)s -a -o -w my_func.py                        # Append func (individually wrapped) simply after current clipboard\n\n"
        "Wrapping Flags (-r, -w, -W) are mutually exclusive for new content generation."
    )
)
parser.add_argument(
    'files',
    metavar='FILE',
    nargs='+',
    help="Path to one or more files."
)

format_group = parser.add_mutually_exclusive_group()
format_group.add_argument(
    '-r', '--raw-copy', action='store_true',
    help="Copy raw concatenated content. Overrides other wrapping."
)
format_group.add_argument(
    '-w', '--wrap', action='store_true',
    help="Individually wrap each input file's content with its name and code fences."
)
format_group.add_argument(
    '-W', '--whole-wrap', action='store_true',
    help=f"Wrap all generated content in a single block, marked with '{WHOLE_WRAP_HEADER_MARKER}'."
)

parser.add_argument(
    '-f', '--show-full-path', action='store_true',
    help="When using -w (for headers per file) or -W (for headers inside the whole block), include absolute paths."
)
parser.add_argument(
    '-a', '--append', action='store_true',
    help="Append to existing clipboard content instead of overwriting."
)
parser.add_argument(
    '-o', '--override-append-wrapping', action='store_true',
    help="With -a, new content (formatted by its own flags) is appended AFTER existing clipboard content, "
         "bypassing any smart insertion logic."
)
parser.add_argument(
    "--no-stats", action="store_true", help="Suppress statistics output."
)


def _generate_file_header(file_path_obj: Path, show_full_path: bool, current_dir: Path) -> str:
    abs_path_str = str(file_path_obj.resolve())
    rel_path_str = os.path.relpath(file_path_obj, current_dir)
    header_lines = [abs_path_str] if show_full_path else []
    header_lines.append(rel_path_str)
    return "\n".join(header_lines)

def _is_whole_wrapped_block(text: str) -> bool:
    return text.startswith(WHOLE_WRAP_HEADER_MARKER + "\n```") and text.rstrip().endswith("\n```")

def _extract_content_from_whole_wrapped_block(text: str) -> str | None:
    if _is_whole_wrapped_block(text):
        content_start_match = re.search(re.escape(WHOLE_WRAP_HEADER_MARKER) + r"\n```\n", text)
        if not content_start_match:
            return None 
        content_start = content_start_match.end()
        content_end = text.rfind("\n```")
        if content_end > content_start:
            return text[content_start:content_end]
    return None

def _extract_payload_from_single_script_generated_block(block_text: str) -> str:
    if block_text.startswith(WHOLE_WRAP_HEADER_MARKER + "\n```"):
        inner_content = _extract_content_from_whole_wrapped_block(block_text)
        return inner_content if inner_content is not None else block_text 

    match_w = re.match(r"^(.*?)\n```\n(.*?)\n```$", block_text.rstrip(), re.DOTALL)
    if match_w:
        header = match_w.group(1)
        inner_content = match_w.group(2)
        return f"{header}\n{inner_content}"
        
    return block_text

def copy_files_to_clipboard(
    file_paths_str: list[str],
    raw_copy: bool,
    wrap: bool,
    whole_wrap: bool,
    show_full_path: bool,
    append: bool,
    override_append_wrapping: bool,
    no_stats: bool
):
    stats_data = {} 
    exit_code = 0 
    
    file_paths = [Path(p) for p in file_paths_str]
    text_to_copy_initially = "" 
    successful_files_count = 0
    input_file_count = len(file_paths)
    current_dir = Path.cwd()
    
    effective_wrap_mode_for_new_content = "raw_single_default"
    if raw_copy:
        effective_wrap_mode_for_new_content = "raw_explicit"
    elif wrap:
        effective_wrap_mode_for_new_content = "individual_wrap"
    elif whole_wrap:
        effective_wrap_mode_for_new_content = "whole_wrap"
    elif input_file_count > 1:
        effective_wrap_mode_for_new_content = "individual_wrap_multi_default"

    stats_data["Effective New Content Mode"] = effective_wrap_mode_for_new_content
    stats_data["Append Mode"] = "Enabled" if append else "Disabled"
    stats_data["Override Append Wrapping"] = "Enabled" if override_append_wrapping else "Disabled"

    content_parts_for_processing = []
    for file_path_obj in file_paths:
        try:
            content_parts_for_processing.append(
                (file_path_obj, file_path_obj.read_text(encoding='utf-8'))
            )
            successful_files_count += 1
            console_info.print(f"[INFO] Successfully read '{file_path_obj}'.")
        except FileNotFoundError:
            console_info.print(f"[WARNING] File not found: '{file_path_obj}'. Skipping.")
        except Exception as e:
            console_info.print(f"[WARNING] Could not read file '{file_path_obj}': {e}. Skipping.")

    stats_data["Input Files Specified"] = input_file_count
    stats_data["Files Successfully Processed"] = successful_files_count
    stats_data["Files Failed/Skipped"] = input_file_count - successful_files_count

    if not successful_files_count:
        console_info.print("[bold red][ERROR] No files successfully processed. Nothing to copy.[/]")
        exit_code = 1
        stats_data["Operation Summary"] = "No files processed."
    else:
        if effective_wrap_mode_for_new_content in ["raw_explicit", "raw_single_default"]:
            text_to_copy_initially = "".join([content for _, content in content_parts_for_processing])
            stats_data["Mode Description"] = "Raw content"
        elif effective_wrap_mode_for_new_content in ["individual_wrap", "individual_wrap_multi_default"]:
            blocks = []
            for path_obj, content in content_parts_for_processing:
                header = _generate_file_header(path_obj, show_full_path, current_dir)
                blocks.append(f"{header}\n```\n{content}\n```")
            text_to_copy_initially = "\n\n".join(blocks)
            stats_data["Mode Description"] = "Individually wrapped files"
        elif effective_wrap_mode_for_new_content == "whole_wrap":
            inner_content_parts = []
            for path_obj, content in content_parts_for_processing:
                header = _generate_file_header(path_obj, show_full_path, current_dir)
                inner_content_parts.append(f"{header}\n{content}")
            all_inner_content = "\n\n---\n\n".join(inner_content_parts) 
            text_to_copy_initially = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{all_inner_content}\n```"
            stats_data["Mode Description"] = "All content in a single marked wrapper block"
        
        current_mode_desc = stats_data.get("Mode Description", "Unknown")
        if effective_wrap_mode_for_new_content == "raw_explicit": current_mode_desc += " (due to --raw-copy)"
        elif effective_wrap_mode_for_new_content == "raw_single_default": current_mode_desc += " (single file default)"
        elif effective_wrap_mode_for_new_content == "individual_wrap": current_mode_desc += " (due to --wrap)"
        elif effective_wrap_mode_for_new_content == "individual_wrap_multi_default": current_mode_desc += " (multiple files default)"
        elif effective_wrap_mode_for_new_content == "whole_wrap": current_mode_desc += " (due to --whole-wrap)"
        stats_data["Mode Description"] = current_mode_desc

        stats_data["Operation Summary"] = f"Generated content from {successful_files_count} of {input_file_count} file(s)."
    
    final_text_for_clipboard = text_to_copy_initially
    original_clipboard_text_for_append = None 

    if append and exit_code == 0:
        stats_data["Append Attempted"] = "Yes"
        if not text_to_copy_initially and successful_files_count > 0:
            try:
                original_clipboard_text_for_append = get_clipboard()
                final_text_for_clipboard = original_clipboard_text_for_append if original_clipboard_text_for_append else ""
                stats_data["Append Action"] = "Skipped (new content was empty), clipboard unchanged"
                console_info.print("[INFO] New content is empty. Clipboard content (if any) preserved in append mode.")
            except Exception as e_get_clip_empty:
                final_text_for_clipboard = "" 
                stats_data["Append Action"] = f"Skipped (new content empty, get_clip failed: {type(e_get_clip_empty).__name__})"
        elif not successful_files_count:
             stats_data["Append Action"] = "Skipped (no new files to process for append)"
        else: 
            try:
                original_clipboard_text_for_append = get_clipboard()
                stats_data["Original Clipboard Read For Append"] = "Success"

                if not original_clipboard_text_for_append:
                    stats_data["Append Action"] = "Normal copy (original clipboard was empty)"
                    console_info.print("[INFO] Clipboard was empty; performing normal copy (append mode).")
                else:
                    payload_to_append = text_to_copy_initially 

                    if override_append_wrapping:
                        final_text_for_clipboard = original_clipboard_text_for_append.rstrip('\n') + '\n\n' + payload_to_append
                        console_info.print("[INFO] Appended new content (using its own specified format) after existing clipboard content due to override.")
                        stats_data["Append Action"] = "General append after original (override active)"
                    else: # Smart append (no -o)
                        is_original_whole_wrapped = _is_whole_wrapped_block(original_clipboard_text_for_append)
                        
                        if is_original_whole_wrapped:
                            original_inner_content = _extract_content_from_whole_wrapped_block(original_clipboard_text_for_append)
                            if original_inner_content is None: original_inner_content = "" 

                            content_to_insert_into_whole_block = ""
                            if effective_wrap_mode_for_new_content in ["individual_wrap", "individual_wrap_multi_default"]:
                                inserted_payloads = []
                                for single_new_block_str in payload_to_append.split("\n\n"):
                                    inserted_payloads.append(_extract_payload_from_single_script_generated_block(single_new_block_str))
                                content_to_insert_into_whole_block = "\n\n---\n\n".join(inserted_payloads)
                            elif effective_wrap_mode_for_new_content == "whole_wrap":
                                inner_new = _extract_content_from_whole_wrapped_block(payload_to_append)
                                content_to_insert_into_whole_block = inner_new if inner_new is not None else payload_to_append
                            else: # Raw new content
                                content_to_insert_into_whole_block = payload_to_append
                            
                            separator = "\n\n---\n\n" 
                            if not original_inner_content.strip(): separator = "" 
                            
                            final_inner_content = original_inner_content.rstrip() + separator + content_to_insert_into_whole_block
                            final_text_for_clipboard = f"{WHOLE_WRAP_HEADER_MARKER}\n```\n{final_inner_content}\n```"
                            
                            stripped_original = original_clipboard_text_for_append.rstrip()
                            if len(original_clipboard_text_for_append) > len(stripped_original):
                                final_text_for_clipboard += original_clipboard_text_for_append[len(stripped_original):]

                            console_info.print(f"[INFO] Appended new content into existing '{WHOLE_WRAP_HEADER_MARKER}' block (smart append).")
                            stats_data["Append Action"] = f"Appended into existing '{WHOLE_WRAP_HEADER_MARKER}' block (smart)"
                        else: 
                            final_text_for_clipboard = original_clipboard_text_for_append.rstrip('\n') + '\n\n' + payload_to_append
                            console_info.print("%%%% NON_W_ORIGINAL_SMART_APPEND_LOG %%%%") # DEBUG LINE / MODIFIED MESSAGE
                            # console_info.print("[INFO] Appended new content after existing (non-whole-wrapped) clipboard content (smart append).") 
                            stats_data["Append Action"] = "General append after original (smart / non-whole-wrap original)"
            except Exception as e_get_clip_append:
                console_info.print(f"[WARNING] Error getting clipboard for append: {e_get_clip_append}. Performing normal copy.")
                stats_data["Original Clipboard Read For Append"] = f"Failed ({type(e_get_clip_append).__name__})"
                stats_data["Append Action"] = "Skipped (get_clipboard error), normal copy performed"
    
    num_lines_payload = len(final_text_for_clipboard.splitlines()) if final_text_for_clipboard else 0
    chars_in_payload = len(final_text_for_clipboard) if final_text_for_clipboard else 0
    stats_data["Lines in Clipboard Payload"] = num_lines_payload
    stats_data["Characters in Clipboard Payload"] = chars_in_payload
    
    clipboard_action_status = "Not Attempted"
    should_set_clipboard_flag = False

    if exit_code == 0 and successful_files_count > 0 :
        should_set_clipboard_flag = True
    elif exit_code == 0 and append: 
        if original_clipboard_text_for_append is not None and not text_to_copy_initially: 
             should_set_clipboard_flag = True 
        elif text_to_copy_initially : 
             should_set_clipboard_flag = True
    
    if should_set_clipboard_flag:
        if append and original_clipboard_text_for_append is not None and \
           final_text_for_clipboard == original_clipboard_text_for_append and \
           stats_data.get("Append Action") == "Skipped (new content was empty), clipboard unchanged":
            console_info.print("[INFO] Clipboard content is unchanged. Skipping set_clipboard call.")
            clipboard_action_status = "No Change (content identical)"
        elif final_text_for_clipboard or (successful_files_count > 0 and not final_text_for_clipboard):
            console_info.print(f"[INFO] Attempting to copy to clipboard ({num_lines_payload} lines, {chars_in_payload} chars).")
            try:
                set_clipboard(final_text_for_clipboard)
                clipboard_action_status = "Set Succeeded (Verification pending)"
                try: 
                    actual_clipboard_content = get_clipboard()
                    if actual_clipboard_content == final_text_for_clipboard:
                        verification_msg = "[SUCCESS] Clipboard copy complete and content verified."
                        clipboard_action_status = "Set & Verified OK"
                    elif len(actual_clipboard_content) == chars_in_payload and \
                         len(actual_clipboard_content.splitlines()) == num_lines_payload:
                        verification_msg = "[INFO] Clipboard content size matches. Minor differences possible."
                        clipboard_action_status = "Set & Verified (Size Match)"
                    else:
                        verification_msg = "[WARNING] Clipboard content may differ or be truncated/altered."
                        clipboard_action_status = "Set & Verified (Potential Discrepancy)"
                    console_info.print(verification_msg)
                except NotImplementedError: 
                    console_info.print("[INFO] get_clipboard not implemented. Skipping verification.")
                    clipboard_action_status = "Set Succeeded (Verification NI)" 
                except Exception as e_get_clipboard:
                    console_info.print(f"[WARNING] Could not verify clipboard content: {e_get_clipboard}")
                    clipboard_action_status = "Set Succeeded (Verification Failed)"
            except Exception as e_set_clip:
                error_msg = f"Failed to set clipboard content: {e_set_clip}"
                stats_data["Error"] = error_msg
                console_info.print(f"[bold red][ERROR] {error_msg}[/]")
                clipboard_action_status = f"Set Failed ({type(e_set_clip).__name__})"
                exit_code = 1 
        else: 
             clipboard_action_status = "Not Attempted (no content to set and not an intentional clear)"
    else: 
        if exit_code == 0 : 
            clipboard_action_status = "Not Attempted (no content or files processed)"
        if input_file_count > 0 and successful_files_count == 0 and exit_code == 0: 
            exit_code = 1

    stats_data["Clipboard Action Status"] = clipboard_action_status
    
    final_non_default_ops_messages = []
    if append: final_non_default_ops_messages.append("Append mode enabled")
    if override_append_wrapping: final_non_default_ops_messages.append("Append wrapping override enabled")
    
    active_mode_desc_for_log = stats_data.get("Mode Description", "Unknown mode for new content")
    is_truly_basic_default = (effective_wrap_mode_for_new_content == "raw_single_default" and
                             not append and
                             not override_append_wrapping and
                             not show_full_path)

    if not is_truly_basic_default:
        final_non_default_ops_messages.append(f"New content mode: {active_mode_desc_for_log}")
    
    if show_full_path and (effective_wrap_mode_for_new_content not in ["raw_explicit", "raw_single_default"]):
        final_non_default_ops_messages.append("Displaying full absolute paths in headers")

    if final_non_default_ops_messages:
        console_info.print("\n[ACTIVE MODES / CHANGES FROM DEFAULT]")
        for op_msg in final_non_default_ops_messages:
            console_info.print(f"- {op_msg}")
            
    stats_data.setdefault("Mode Description", "N/A")
    stats_data.setdefault("Append Attempted", "No")
    stats_data.setdefault("Original Clipboard Read For Append", "N/A")
    stats_data.setdefault("Append Action", "N/A")
    stats_data.setdefault("Operation Summary", "Operation incomplete or no files processed.")
    
    return exit_code


if __name__ == '__main__':
    args = parser.parse_args()
    script_exit_code = 1 
    
    if args.override_append_wrapping and not args.append:
        console_info.print("[bold red][ERROR] --override-append-wrapping (-o) can only be used with --append (-a).[/]")
        sys.exit(1) 

    final_stats_data_for_main_fallback = {}
    try:
        script_exit_code = copy_files_to_clipboard(
            args.files,
            raw_copy=args.raw_copy,
            wrap=args.wrap,
            whole_wrap=args.whole_wrap,
            show_full_path=args.show_full_path,
            append=args.append,
            override_append_wrapping=args.override_append_wrapping,
            no_stats=args.no_stats
        )
    except SystemExit as e: 
        script_exit_code = e.code if e.code is not None else 1
    except Exception as e_outer_main:
        console_info.print(f"[bold red][CRITICAL MAIN ERROR] An unhandled exception occurred: {e_outer_main}[/]")
        script_exit_code = 1
        if not args.no_stats:
            final_stats_data_for_main_fallback = {
                "Outcome": "CRITICAL FAILURE IN MAIN", "Error": str(e_outer_main),
                **{f"Arg: {k}": v for k,v in vars(args).items()}
            }
    finally:
        if not args.no_stats and "Outcome" in final_stats_data_for_main_fallback:
            table = Table(title="copy_to_clipboard.py Statistics (CRITICAL FALLBACK)")
            table.add_column("Metric", style="cyan", overflow="fold")
            table.add_column("Value", overflow="fold")
            for key, value in final_stats_data_for_main_fallback.items():
                table.add_row(str(key), str(value))
            console_stats.print(table)
        sys.exit(script_exit_code)
