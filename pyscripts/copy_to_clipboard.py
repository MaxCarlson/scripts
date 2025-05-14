#!/usr/bin/env python3

import sys
import os
import argparse

# Assuming cross_platform.clipboard_utils is a module available in your environment.
try:
    from cross_platform.clipboard_utils import set_clipboard, get_clipboard
except ImportError:
    print("[ERROR] The 'cross_platform.clipboard_utils' module was not found.")
    print("    Please ensure it is installed and accessible in your Python environment.")
    print("    You can often install packages using pip.")
    print("    (Note: The actual package name for 'cross_platform.clipboard_utils' might differ; please check its source.)")
    sys.exit(1)


def copy_files_to_clipboard(file_paths, show_full_path=False, force_wrap=False, raw_copy=False):
    """
    Copies content from files to the clipboard.
    - Default (1 file): Raw content.
    - Default (>1 file): Aggregate with relative paths and code fences.
    - --raw-copy (-r): Concatenate raw content for all files, overriding other formatting.
    - --force-wrap (-w): Wrap single file content like multiple files.
    - --show-full-path (-f): If wrapping, also show full absolute path.
    """
    non_default_ops = []
    text_to_copy = ""
    successful_files_count = 0
    is_single_file_input = (len(file_paths) == 1)
    operation_description = "" # Initialize
    input_file_count = len(file_paths)

    if raw_copy:
        non_default_ops.append("Raw copy mode enabled (filenames, paths, and wrapping are disabled)")
        print(f"[INFO] Raw copy mode active. Processing {input_file_count} file(s) for raw concatenation.")
        content_parts = []
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content_parts.append(f.read())
                successful_files_count += 1
                print(f"[INFO] Successfully read '{file_path}' for raw concatenation.")
            except FileNotFoundError:
                print(f"[WARNING] File not found: '{file_path}'. Skipping this file for raw concatenation.")
            except Exception as e:
                print(f"[WARNING] Could not read file '{file_path}' for raw concatenation: {e}. Skipping this file.")
        
        if not content_parts and successful_files_count == 0 : # Check if any file yielded content
            print("[INFO] No content was successfully processed from any files. Clipboard not updated.")
        
        text_to_copy = "".join(content_parts)
        operation_description = f"raw concatenated content from {successful_files_count} of {input_file_count} specified file(s)"

    elif is_single_file_input and not force_wrap:
        file_path = file_paths[0]
        print(f"[INFO] Processing single file for raw copy: '{file_path}'")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text_to_copy = f.read()
            successful_files_count = 1
            operation_description = f"raw content from 1 file ('{file_path}')"
            print(f"[INFO] Successfully read '{file_path}'.")
        except FileNotFoundError:
            print(f"[ERROR] File not found: '{file_path}'. Nothing will be copied.")
            # successful_files_count remains 0
        except Exception as e:
            print(f"[ERROR] Could not read file '{file_path}': {e}. Nothing will be copied.")
            # successful_files_count remains 0
    else:
        if is_single_file_input and force_wrap: 
            non_default_ops.append("Forced wrapping of single file in code block")
        
        non_default_ops.append(f"Wrapping content of {input_file_count} file(s) in code blocks with relative paths")

        if show_full_path:
            non_default_ops.append("Displaying full absolute paths above each code block")

        processed_blocks = []
        print(f"[INFO] Processing {input_file_count} file(s) for aggregated copy with code fences.")
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                
                header_lines = []
                abs_path_str = os.path.abspath(file_path)
                rel_path_str = os.path.relpath(file_path)

                if show_full_path:
                    header_lines.append(abs_path_str)
                header_lines.append(rel_path_str)
                
                header = "\n".join(header_lines)
                processed_blocks.append(f"{header}\n```\n{file_content}\n```")
                successful_files_count += 1
                print(f"[INFO] Processed '{file_path}' into code block.")
            except FileNotFoundError:
                print(f"[WARNING] File not found: '{file_path}'. Skipping this file.")
            except Exception as e:
                print(f"[WARNING] Could not read file '{file_path}': {e}. Skipping this file.")

        if not processed_blocks and successful_files_count == 0: # Check if any file yielded content
            print("[INFO] No content was successfully processed from any of the files. Clipboard not updated.")
        
        text_to_copy = "\n\n".join(processed_blocks)
        operation_description = f"wrapped content from {successful_files_count} of {input_file_count} file(s)"

    # Fallback for operation_description if not set, ensuring it reflects actual success
    if not operation_description:
        if successful_files_count == 1 and is_single_file_input and not force_wrap and not raw_copy: # Should have been caught by single file logic
             operation_description = f"raw content from 1 file ('{file_paths[0]}')"
        else: # Generic fallback
            operation_description = f"content from {successful_files_count} of {input_file_count} file(s)"


    # Clipboard operations and verification
    num_lines_payload = len(text_to_copy.splitlines())
    chars_in_payload = len(text_to_copy)

    if successful_files_count > 0:
        print(f"[INFO] Attempting to copy {operation_description} ({num_lines_payload} lines total) to clipboard.")
        try:
            set_clipboard(text_to_copy) 

            try:
                actual_clipboard_content = get_clipboard()
                copied_lines_found = len(actual_clipboard_content.splitlines())

                if actual_clipboard_content == text_to_copy:
                    print("[SUCCESS] Clipboard copy complete and content verified.")
                elif copied_lines_found == num_lines_payload:
                    print(f"[INFO] Clipboard line count ({copied_lines_found}) matches expected. "
                          "Content may have minor differences (e.g., newline normalization by clipboard manager).")
                elif copied_lines_found < num_lines_payload:
                    print(f"[WARNING] Clipboard content may be truncated or incomplete: "
                          f"{copied_lines_found} lines found in clipboard vs. {num_lines_payload} expected.")
                else: # copied_lines_found > num_lines_payload
                    print(f"[WARNING] Clipboard content has more lines than expected: "
                          f"{copied_lines_found} lines found in clipboard vs. {num_lines_payload} expected. This may indicate unexpected alterations.")
            except NotImplementedError:
                print("[INFO] get_clipboard is not implemented in clipboard_utils. Skipping verification step.")
            except Exception as e_get_clipboard:
                print(f"[WARNING] Could not retrieve or verify clipboard content after setting: {e_get_clipboard}")
                print("             The content might have been copied, but automatic verification failed.")

        except NotImplementedError:
            print("[ERROR] set_clipboard is not implemented in clipboard_utils. Cannot copy content.")
        except Exception as e_set_clipboard:
            print(f"[ERROR] Failed to set clipboard content: {e_set_clipboard}")
    # If successful_files_count is 0, messages like "Clipboard not updated" or "Nothing will be copied"
    # would have already been printed. No attempt to call set_clipboard or related logs here.


    # Print non-default behavior summary
    if non_default_ops:
        print("[CHANGES]")
        for op in non_default_ops:
            print(f"- {op}")

    # Stats Printing
    mode_desc = ""
    if raw_copy:
        mode_desc = "Raw Concatenation"
    elif is_single_file_input and not force_wrap:
        mode_desc = "Single File (Raw Content)"
    else: # Wrapped mode
        current_mode_parts = []
        if is_single_file_input and force_wrap:
            current_mode_parts.append("Single File (Forced Wrap)")
        elif not is_single_file_input:
             current_mode_parts.append(f"Multiple Files ({input_file_count} initially)")
        
        current_mode_parts.append("Aggregated (Code Fences)")
        if show_full_path:
            current_mode_parts.append("with Full & Relative Paths")
        else:
            current_mode_parts.append("with Relative Paths")
        mode_desc = ", ".join(filter(None, current_mode_parts))


    print("\n[CLIPBOARD STATS]")
    print(f"    Mode: {mode_desc}")
    print(f"    Input files specified: {input_file_count}")
    print(f"    Files successfully processed: {successful_files_count}")
    print(f"    Files failed/skipped: {input_file_count - successful_files_count}")
    
    if successful_files_count > 0:
        print(f"    Lines in clipboard payload: {num_lines_payload}")
        print(f"    Characters in clipboard payload: {chars_in_payload}")
    else: # Ensure these are 0 if no files were successfully processed
        print(f"    Lines in clipboard payload: 0")
        print(f"    Characters in clipboard payload: 0")
    print(f"    Operation summary: {operation_description}")


if __name__ == '__main__':
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
            "  %(prog)s my_doc.txt                     (Copies raw content of my_doc.txt)\n"
            "  %(prog)s chap1.txt chap2.txt            (Copies combined content, each with rel path & code fence)\n"
            "  %(prog)s -w report.md                   (Copies report.md with rel path & code fence)\n"
            "  %(prog)s -f script.py lib.py            (Copies with full & rel paths & code fences)\n"
            "  %(prog)s -r file1.txt file2.txt         (Copies raw concatenation of file1 and file2)\n\n"
            "The behavior changes based on the number of files and options provided."
        )
    )

    parser.add_argument(
        'files',
        metavar='FILE',
        nargs='+',
        help="Path to one or more files. Behavior depends on number of files and options."
    )
    parser.add_argument(
        '-w', '--force-wrap',
        action='store_true',
        help="Force wrap a single file's content with its relative path and code fences, similar to multi-file output."
    )
    parser.add_argument(
        '-f', '--show-full-path',
        action='store_true',
        help="When wrapping content (default for multiple files or with --force-wrap), "
             "also include the file's absolute path above its relative path."
    )
    parser.add_argument(
        '-r', '--raw-copy',
        action='store_true',
        help="Copy raw concatenated content of all files. Overrides --force-wrap and --show-full-path."
    )

    args = parser.parse_args()
    copy_files_to_clipboard(
        args.files,
        show_full_path=args.show_full_path,
        force_wrap=args.force_wrap,
        raw_copy=args.raw_copy
    )
