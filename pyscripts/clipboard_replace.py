#!/usr/bin/env python3

import sys
import re
from clipboard_utils import get_clipboard

def extract_function_name(code):
    """Extract function/class name from Python/C++ clipboard contents."""
    py_match = re.match(r"^\s*(def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)", code)
    cpp_match = re.match(r"^\s*(?:\w+\s+)?([a-zA-Z_][a-zA-Z0-9_]+)\s*.*\s*{?", code)

    if py_match:
        return py_match.group(2), "python"
    elif cpp_match:
        return cpp_match.group(1), "cpp"

    print("Clipboard content does not match a function/class definition. Aborting.")
    sys.exit(1)

def replace_function_in_file(file_path, function_name, language, new_function):
    """Find and replace function/class in a given file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = []
        inside_target_function = False
        matched = False

        for line in lines:
            if inside_target_function:
                if (language == "python" and re.match(r"^\s*$", line)) or (language == "cpp" and "{" in line):
                    inside_target_function = False
                continue

            if language == "python":
                match = re.match(r"^\s*(def|class)\s+" + function_name + r"\b", line)
            else:  # C++
                match = re.match(r"^\s*(?:\w+\s+)?(" + function_name + r")\s*", line)

            if match:
                if matched:
                    print(f"Error: Multiple definitions of '{function_name}' found. Aborting.")
                    sys.exit(1)
                matched = True
                inside_target_function = True
                updated_lines.append(new_function + "\n")
            else:
                updated_lines.append(line)

        if not matched:
            print(f"Function/class '{function_name}' not found in {file_path}. Aborting.")
            sys.exit(1)

        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)

        print(f"Replaced {function_name} in {file_path} successfully.")

    except Exception as e:
        print(f"Error modifying file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: clipboard_replace.py <file>")
        sys.exit(1)

    file_path = sys.argv[1]
    clipboard_text = get_clipboard()
    function_name, language = extract_function_name(clipboard_text)
    replace_function_in_file(file_path, function_name, language, clipboard_text)
