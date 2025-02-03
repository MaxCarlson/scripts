#!/usr/bin/env python3

import sys
from pathlib import Path
from cross_platform.clipboard_utils import get_clipboard

def replace_with_clipboard(file_path):
    try:
        clipboard_text = get_clipboard()

        if not clipboard_text:
            print("Clipboard is empty. Aborting.")
            sys.exit(1)

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            print(f"⚠️ {file_path} does not exist. Creating a new file.")

        with open(file_path, "w", encoding="utf-8") as f:
            # Remove any trailing newlines and append exactly one newline at the end.
            f.write(clipboard_text.rstrip("\n") + "\n")

        print(f"Replaced contents of {file_path} with clipboard data.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: replace_with_clipboard.py <file>")
        sys.exit(1)

    replace_with_clipboard(sys.argv[1])

