#!/usr/bin/env python3

import sys
from clipboard_utils import get_clipboard

def append_clipboard(file_path):
    try:
        clipboard_text = get_clipboard()

        if not clipboard_text:
            print("Clipboard is empty. Aborting.")
            sys.exit(1)

        with open(file_path, "a", encoding="utf-8") as f:
            f.write("\n" + clipboard_text)

        print(f"Appended clipboard contents to {file_path}.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: append_clipboard.py <file>")
        sys.exit(1)

    append_clipboard(sys.argv[1])
