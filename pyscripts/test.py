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
    operation_description = ""

    if raw_copy:
        non_default_ops.append("Raw copy mode enabled (filenames, paths, and wrapping are disabled)")
        print(f"[INFO] Raw copy mode active. Processing {len(file_paths)} file(s) for raw concatenation.")
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
        
        if not content_parts:
            print("[INFO] No content was successfully processed from any files. Clipboard not updated.")
            return
        
        text_to_copy = "".join(content_parts)
        operation_description = f"raw concatenated content from {successful_files_count} of {len(file_paths)} specified file(s)"

    elif is_single_file_input and not force_wrap:
        # Default single-file raw copy
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
            return
        except Exception as e:
            print(f"[ERROR] Could not read file '{file_path}': {e}. Nothing will be copied.")
            return
    else:
        # Wrap mode for one or more files (multiple files by default, or single with --force-wrap)
        if is_single_file_input and force_wrap: # This implies force_wrap is True
            non_default_ops.append("Forced wrapping of single file in code block")
        
        # This will always be true in this branch now, due to new logic structure
        non_default_ops.append(f"Wrapping content of {len(file_paths)} file(s) in code blocks with relative paths")

        if show_full_path:
            non_default_ops.append("Displaying full absolute paths above each code block")

        processed_blocks = []
        print(f"[INFO] Processing {len(file_paths)} file(s) for aggregated copy with code fences.")
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

        if not processed_blocks:
            print("[INFO] No content was successfully processed from any of the files. Clipboard not updated.")
            return

        text_to_copy = "\n\n".join(processed_blocks)
        operation_description = f"wrapped content from {successful_files_count} of {len(file_paths)} file(s)"

    # Copy to clipboard and validate
    total_lines_expected = len(text_to_copy.splitlines())
    try:
        set_clipboard(text_to_copy)
        print(f"[INFO] Attempted to copy {operation_description} ({total_lines_expected} lines total) to clipboard.")

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
        except NotImplementedError:
            print("[INFO] get_clipboard is not implemented in clipboard_utils. Skipping verification step.")
        except Exception as e_get_clipboard:
            print(f"[WARNING] Could not retrieve or verify clipboard content after setting: {e_get_clipboard}")
            print("             The content might have been copied, but automatic verification failed.")

    except NotImplementedError:
        print("[ERROR] set_clipboard is not implemented in clipboard_utils. Cannot copy content.")
    except Exception as e_set_clipboard:
        print(f"[ERROR] Failed to set clipboard content: {e_set_clipboard}")
    except Exception as e_general:
        print(f"[ERROR] An unexpected error occurred during clipboard operations: {e_general}")

    # Print non-default behavior summary
    if non_default_ops:
        print("[CHANGES]")
        for op in non_default_ops:
            print(f"- {op}")


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
