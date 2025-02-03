#!/usr/bin/env python3

import sys
from clipboard_utils.clipboard_utils import set_clipboard

def copy_to_clipboard(files):
    try:
        content = []
        for file in files:
            with open(file, "r", encoding="utf-8") as f:
                content.append(f.read())

        # Join all file contents and copy to clipboard
        text_to_copy = "\n\n".join(content)
        set_clipboard(text_to_copy)

        print("Files copied to clipboard successfully!")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: copy_to_clipboard.py <file1> <file2> ...")
        sys.exit(1)

    copy_to_clipboard(sys.argv[1:])

