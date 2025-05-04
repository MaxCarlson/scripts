#!/usr/bin/env python3
import sys
import re
from clipboard_utils import get_clipboard

def extract_function_name(code: str):
    """Extract function/class name from Python clipboard contents."""
    m = re.match(r"^\s*(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", code)
    if not m:
        print("Clipboard content is not a Python def/class. Aborting.", file=sys.stderr)
        sys.exit(1)
    return m.group(2)

def replace_python_block(lines, func_name, new_block):
    """
    Given file lines, replace the first def/class func_name block
    by new_block (a multiline string). Returns updated lines.
    """
    start_idx = None
    indent = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*(def|class)\s+{func_name}\b", line):
            if start_idx is not None:
                print(f"Error: Multiple definitions of '{func_name}' found. Aborting.", file=sys.stderr)
                sys.exit(1)
            start_idx = i
            indent = len(line) - len(line.lstrip())
    if start_idx is None:
        print(f"Function/class '{func_name}' not found. Aborting.", file=sys.stderr)
        sys.exit(1)

    # find end of block
    end_idx = start_idx + 1
    while end_idx < len(lines):
        l = lines[end_idx]
        if l.strip() and (len(l) - len(l.lstrip())) <= indent:
            break
        end_idx += 1

    # build new lines
    new_lines = [ln + "\n" for ln in new_block.rstrip("\n").split("\n")]
    return lines[:start_idx] + new_lines + lines[end_idx:]

def main():
    if len(sys.argv) != 2:
        print("Usage: clipboard_replace.py <file>", file=sys.stderr)
        sys.exit(1)

    file_path = sys.argv[1]
    content = get_clipboard()
    func_name = extract_function_name(content)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original_lines = f.readlines()

        updated = replace_python_block(original_lines, func_name, content)

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(updated)

        print(f"Replaced '{func_name}' successfully in {file_path}.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
