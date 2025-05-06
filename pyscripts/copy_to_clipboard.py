#!/usr/bin/env python3

import sys
from cross_platform.clipboard_utils import set_clipboard, get_clipboard

def copy_to_clipboard(files):
    try:
        content = []
        for file in files:
            with open(file, "r", encoding="utf-8") as f:
                content.append(f.read())

        # Join all file contents and copy to clipboard
        text_to_copy = "\n\n".join(content)
        #total_lines = text_to_copy.count("\n") + 1
        total_lines = len(text_to_copy.splitlines())

        set_clipboard(text_to_copy)
        print(f"[INFO] Requested copy: {total_lines} lines.")

        # Fetch clipboard contents and validate
        actual_clipboard = get_clipboard()
        #copied_lines = actual_clipboard.count("\n") + 1
        copied_lines = len(actual_clipboard.splitlines())

        if copied_lines < total_lines:
            print(f"[WARNING] Clipboard may have been truncated: {copied_lines} / {total_lines} lines copied.")
        else:
            print("[SUCCESS] Clipboard copy appears complete.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: copy_to_clipboard.py <file1> <file2> ...")
        sys.exit(1)

    copy_to_clipboard(sys.argv[1:])
