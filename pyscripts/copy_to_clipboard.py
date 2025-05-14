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


def copy_files_to_clipboard(file_paths, show_full_path=False, force_wrap=False):
    """
    Copies content from files to the clipboard.
    - Default: Single file => raw content; Multiple files => aggregate with code fences and relative paths.
    - --force-wrap (-w): Wrap single file content in code fence like multiple files.
    - --show-full-path (-f): Also show full absolute path above each code block.
    """
    non_default_ops = []
    text_to_copy = ""
    successful_files_count = 0
    is_single = (len(file_paths) == 1)

    # Determine mode: raw vs wrap
    if is_single and not force_wrap:
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
        # Wrap mode for one or more files
        if is_single and force_wrap:
            non_default_ops.append("Forced wrapping of single file in code block")
        else:
            non_default_ops.append(f"Wrapping content of {len(file_paths)} file(s) in code blocks")
        if len(file_paths) > 1:
            non_default_ops.append("Displaying relative paths above each code block")
        if show_full_path:
            non_default_ops.append("Displaying full paths above each code block")

        processed = []
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                successful_files_count += 1
                rel = os.path.relpath(file_path)
                header_lines = [rel]
                if show_full_path:
                    header_lines.append(os.path.abspath(file_path))
                header = "\n".join(header_lines)
                processed.append(f"{header}\n```\n{file_content}\n```")
                print(f"[INFO] Processed '{file_path}' into code block.")
            except FileNotFoundError:
                print(f"[WARNING] File not found: '{file_path}'. Skipping this file.")
            except Exception as e:
                print(f"[WARNING] Could not read file '{file_path}': {e}. Skipping this file.")

        if not processed:
            print("[INFO] No content was successfully processed from any of the files. Clipboard not updated.")
            return

        text_to_copy = "\n\n".join(processed)
        operation_description = f"wrapped content from {successful_files_count} of {len(file_paths)} file(s)"

    # Copy to clipboard
    total_lines_expected = len(text_to_copy.splitlines())
    try:
        set_clipboard(text_to_copy)
        print(f"[INFO] Attempted to copy {operation_description} ({total_lines_expected} lines total) to clipboard.")
        try:
            actual = get_clipboard()
            copied_lines = len(actual.splitlines())
            if actual == text_to_copy:
                print("[SUCCESS] Clipboard copy complete and content verified.")
            elif copied_lines == total_lines_expected:
                print(f"[INFO] Clipboard line count ({copied_lines}) matches expected. Minor differences possible.")
            elif copied_lines < total_lines_expected:
                print(f"[WARNING] Clipboard content may be truncated: {copied_lines} vs {total_lines_expected} lines.")
            else:
                print(f"[WARNING] Clipboard content longer than expected: {copied_lines} vs {total_lines_expected} lines.")
        except NotImplementedError:
            print("[INFO] get_clipboard not implemented. Skipping verification.")
        except Exception as e:
            print(f"[WARNING] Verification failed: {e}")
    except NotImplementedError:
        print("[ERROR] set_clipboard not implemented. Cannot copy content.")
    except Exception as e:
        print(f"[ERROR] Failed to set clipboard content: {e}")

    # Print non-default behavior summary
    if non_default_ops:
        print("[CHANGES]")
        for op in non_default_ops:
            print(f"- {op}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=(
            "Copies file content to the clipboard. "
            "Default: single file raw. Multiple or --force-wrap: code-fenced blocks."
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        'files', metavar='FILE', nargs='+', help="One or more files to copy."
    )
    parser.add_argument(
        '--show-full-path', '-f', action='store_true',
        help="Show absolute full path above each code block."
    )
    parser.add_argument(
        '--force-wrap', '-w', action='store_true',
        help="Force wrap single file content in code fences."
    )
    args = parser.parse_args()
    copy_files_to_clipboard(args.files, show_full_path=args.show_full_path, force_wrap=args.force_wrap)

