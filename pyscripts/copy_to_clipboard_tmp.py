#!/usr/bin/env python3

import sys
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

def copy_files_to_clipboard(file_paths):
    """
    Copies content from files to the clipboard.
    - If one file is provided, its raw content is copied.
    - If multiple files are provided, their contents are combined with headers/footers
      including filenames.
    Also, validates the clipboard content against the expected content if possible.
    """
    text_to_copy = ""  # Initialize to ensure it's defined
    successful_files_count = 0
    is_single_file_operation = (len(file_paths) == 1)
    operation_description = "" # For logging the type of copy operation

    if is_single_file_operation:
        file_path = file_paths[0]
        print(f"[INFO] Processing single file for raw copy: '{file_path}'")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text_to_copy = f.read()
            successful_files_count = 1
            operation_description = f"raw content from 1 file ('{file_path}')"
            print(f"[INFO] Successfully read '{file_path}'.")
        except FileNotFoundError:
            print(f"[ERROR] File not found: '{file_path}'. Nothing will be copied.")
            return # Exit if the single file cannot be processed
        except Exception as e_file:
            print(f"[ERROR] Could not read file '{file_path}': {e_file}. Nothing will be copied.")
            return # Exit if the single file cannot be processed
    else: # Multiple files
        print(f"[INFO] Processing {len(file_paths)} files for aggregated copy with separators.")
        processed_content_blocks = []
        separator_visual = "---" * 18  # Visual separator line

        for file_path in file_paths:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    file_content = f.read()
                
                header = f"{separator_visual}\n--- Start of file: {file_path} ---\n{separator_visual}"
                footer = f"{separator_visual}\n--- End of file: {file_path} ---\n{separator_visual}"
                
                processed_content_blocks.append(f"{header}\n{file_content}\n{footer}")
                successful_files_count += 1
                print(f"[INFO] Successfully processed '{file_path}' for aggregation.")
            except FileNotFoundError:
                print(f"[WARNING] File not found: '{file_path}'. Skipping this file.")
            except Exception as e_file:
                print(f"[WARNING] Could not read file '{file_path}': {e_file}. Skipping this file.")

        if not processed_content_blocks:
            print("[INFO] No content was successfully processed from any of the multiple files. Clipboard not updated.")
            return # Exit if no files in the multi-list could be processed
        
        text_to_copy = "\n\n".join(processed_content_blocks)
        operation_description = f"formatted content from {successful_files_count} of {len(file_paths)} specified file(s)"

    # If we've reached here, text_to_copy contains the content to be copied.
    # This could be an empty string if the single file processed was empty.

    total_lines_expected = len(text_to_copy.splitlines())

    try:
        set_clipboard(text_to_copy)
        print(f"[INFO] Attempted to copy {operation_description} ({total_lines_expected} lines total) to clipboard.")

        # Validate clipboard content by fetching it back
        try:
            actual_clipboard_content = get_clipboard()
            copied_lines_found = len(actual_clipboard_content.splitlines())

            if actual_clipboard_content == text_to_copy:
                print("[SUCCESS] Clipboard copy complete and content verified.")
            elif copied_lines_found == total_lines_expected:
                print(f"[INFO] Clipboard line count ({copied_lines_found}) matches expected. "
                      "Content may have minor differences (e.g., newline normalization by clipboard manager).")
            elif copied_lines_found < total_lines_expected:
                print(f"[WARNING] Clipboard content may be truncated or incomplete: "
                      f"{copied_lines_found} lines found in clipboard vs. {total_lines_expected} expected.")
            else: # copied_lines_found > total_lines_expected
                print(f"[WARNING] Clipboard content has more lines than expected: "
                      f"{copied_lines_found} lines found in clipboard vs. {total_lines_expected} expected. This may indicate unexpected alterations.")
        except NotImplementedError: # If get_clipboard isn't available
            print("[INFO] get_clipboard is not implemented in clipboard_utils. Skipping verification step.")
        except Exception as e_get_clipboard:
            print(f"[WARNING] Could not retrieve or verify clipboard content after setting: {e_get_clipboard}")
            print("         The content might have been copied, but automatic verification failed.")

    except NotImplementedError: # If set_clipboard isn't available
        print(f"[ERROR] set_clipboard is not implemented in clipboard_utils. Cannot copy content.")
    except Exception as e_set_clipboard:
        print(f"[ERROR] Failed to set clipboard content: {e_set_clipboard}")
    except Exception as e_general: # Catch any other unexpected errors in this block
        print(f"[ERROR] An unexpected error occurred during clipboard operations: {e_general}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Copies file content to the clipboard. If a single file is given, its raw content is copied. "
            "If multiple files are given, their contents are combined with clear separators including filenames."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Usage Examples:\n"
            "  %(prog)s my_document.txt                   (Copies raw content of my_document.txt)\n"
            "  %(prog)s chapter1.txt chapter2.txt       (Copies combined content with separators)\n\n"
            "The behavior changes based on the number of files provided."
        )
    )

    parser.add_argument(
        'files',
        metavar='FILE',
        nargs='+',  # Requires at least one file argument
        help="Path to one or more files. If one file, raw content is copied. If multiple, content is combined with separators."
    )

    args = parser.parse_args()
    copy_files_to_clipboard(args.files)
