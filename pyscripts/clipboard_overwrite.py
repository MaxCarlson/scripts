#!/usr/bin/env python3

import sys
from clipboard_utils import get_clipboard

def replace_with_clipboard(file_path):
    try:
        clipboard_text = get_clipboard()

        if not clipboard_text:
            print("Clipboard is empty. Aborting.")
            sys.exit(1)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(clipboard_text)

        print(f"Replaced contents of {file_path} with clipboard data.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: replace_with_clipboard.py <file>")
        sys.exit(1)

    replace_with_clipboard(sys.argv[1])
