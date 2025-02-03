#!/usr/bin/env python3
import argparse
import os
import re
import sys
import io

# Import clipboard_utils (using the backward-compatible wrapper)
try:
    import clipboard_utils as clipboard
except ImportError:
    print("Error: clipboard_utils.py not found. Please ensure it is in the same directory or installed.")
    class clipboard:
        @staticmethod
        def get_clipboard():
            raise ImportError("clipboard_utils not available")

# Import debug_utils (or its wrapper)
try:
    import debug_utils as debug_utils
except ImportError:
    print("Error: debug_utils.py not found. Please ensure it is in the same directory or installed.")
    class debug_utils:
        @staticmethod
        def write_debug(message="", channel="Debug", **kwargs):
            print(f"[{channel}] {message}")
        DEFAULT_LOG_DIR = os.path.expanduser("~/logs")
        @staticmethod
        def set_log_verbosity(level): pass
        @staticmethod
        def set_console_verbosity(level): pass
        @staticmethod
        def set_log_directory(path): pass
        @staticmethod
        def enable_file_logging(): pass

# ----------------------------
# Unified-diff patch functions
# ----------------------------

def extract_hunks(diff_lines):
    """
    Given diff_lines (list of lines from a diff block),
    return a list of hunks. Each hunk is a list of lines starting with a header (@@ ...) 
    followed by lines that start with space, '+', or '-'.
    """
    hunks = []
    i = 0
    while i < len(diff_lines):
        line = diff_lines[i]
        if line.startswith('@@'):
            hunk = [line]
            i += 1
            while i < len(diff_lines) and diff_lines[i].startswith((' ', '+', '-')):
                hunk.append(diff_lines[i])
                i += 1
            hunks.append(hunk)
        else:
            i += 1
    return hunks

def apply_hunk(original_lines, hunk):
    """
    Apply one hunk (a list of lines, with first line being the hunk header)
    to original_lines (list of lines including newlines). Returns new list of lines.
    This is a very simple implementation and does not perform full validation.
    """
    import re
    header = hunk[0]
    m = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', header)
    if not m:
        # If header is invalid, do nothing.
        return original_lines
    orig_start = int(m.group(1)) - 1
    orig_count = int(m.group(2)) if m.group(2) else 1
    # We ignore new file numbers; we simply replace original_lines[orig_start:orig_start+orig_count]
    new_hunk_lines = []
    # Process the hunk lines (skip header)
    for line in hunk[1:]:
        if line.startswith(' '):
            new_hunk_lines.append(line[1:] + "\n")
        elif line.startswith('+'):
            new_hunk_lines.append(line[1:] + "\n")
        elif line.startswith('-'):
            # Removed line: skip it.
            continue
    # Build new file lines: before hunk, then new_hunk_lines, then after hunk.
    new_file_lines = original_lines[:orig_start] + new_hunk_lines + original_lines[orig_start+orig_count:]
    return new_file_lines

def apply_unified_diff(original_lines, diff_content):
    """
    Given the original file's lines (list of strings, each ending with newline)
    and diff_content (string of a unified diff), apply all hunks and return the new lines.
    If no hunks are found, return original_lines.
    """
    diff_lines = diff_content.splitlines()
    hunks = extract_hunks(diff_lines)
    if not hunks:
        debug_utils.write_debug("No hunks found in diff.", channel="Debug")
        return original_lines
    new_lines = original_lines
    for hunk in hunks:
        new_lines = apply_hunk(new_lines, hunk)
    return new_lines

# ----------------------------
# Core functions
# ----------------------------
def apply_diff_to_file(filepath, diff_content):
    """Applies git diff content to a file and returns its updated content.
    
    Returns:
      - Updated file content as a string if successful.
      - The original file content if no changes were detected.
      - None if the file was not found or an error occurred.
    """
    try:
        # Read original file content as lines.
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                original_lines = f.readlines()
        except FileNotFoundError:
            # For our purposes, if file is not found, treat original as empty.
            original_lines = []
        debug_utils.write_debug(f"Applying diff to file: {filepath}", channel="Information")
        if not diff_content or '@@' not in diff_content:
            debug_utils.write_debug(f"No changes detected for file: {filepath}", channel="Debug")
            # Return original content instead of empty string.
            return ''.join(original_lines)
        # Apply the unified diff.
        new_lines = apply_unified_diff(original_lines, diff_content)
        # Write new content to file.
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(''.join(new_lines))
        debug_utils.write_debug(f"Successfully applied diff to file: {filepath}", channel="Information")
        return ''.join(new_lines)
    except Exception as e:
        debug_utils.write_debug(f"Error applying diff to file {filepath}: {e}", channel="Error")
        return None

def parse_diff_and_apply(diff_text, target_directory):
    """
    Parses git diff text and applies it to corresponding files in the target directory.
    
    Returns a dictionary mapping file paths (as given in the diff, without the 'a/' prefix)
    to their updated contents. If any diff block is invalid, returns an empty dict (i.e.
    transactional behavior: either all diffs are applied or none).
    """
    import re, os
    modified = {}
    # Split on diff header lines.
    diff_blocks = re.split(r'^diff --git ', diff_text, flags=re.MULTILINE)
    if diff_blocks and diff_blocks[0].strip() == '':
        diff_blocks = diff_blocks[1:]
    
    # First pass: Validate all diff blocks.
    for diff_block in diff_blocks:
        if not diff_block.strip():
            continue
        lines = diff_block.strip().splitlines()
        if len(lines) < 3:
            debug_utils.write_debug(f"Invalid diff block (not enough lines):\n{diff_block}", channel="Warning")
            return {}  # Transactional failure: abort if any block is invalid.
        a_file_line = next((line for line in lines if line.startswith('--- a/')), None)
        b_file_line = next((line for line in lines if line.startswith('+++ b/')), None)
        if not a_file_line or not b_file_line:
            debug_utils.write_debug(f"Invalid diff block (missing file markers):\n{diff_block}", channel="Warning")
            return {}
        hunk_found = any(line.startswith('@@') for line in diff_block.splitlines())
        if not hunk_found:
            debug_utils.write_debug(f"Invalid diff block (no hunks found) for file: {a_file_line[6:]}", channel="Warning")
            return {}
    
    # Second pass: All diff blocks are valid; apply them.
    for diff_block in diff_blocks:
        if not diff_block.strip():
            continue
        try:
            lines = diff_block.strip().splitlines()
            a_file_line = next((line for line in lines if line.startswith('--- a/')), None)
            # Get the file path from the a/ marker.
            file_path_in_diff = a_file_line[6:]
            target_file_path = os.path.join(target_directory, file_path_in_diff)
            diff_content = diff_block.strip()
            # Check that there is at least one hunk.
            hunk_found = any(line.startswith('@@') for line in diff_content.splitlines())
            if not hunk_found:
                debug_utils.write_debug(f"Skipping diff block without hunks: {file_path_in_diff}", channel="Warning")
                continue
            if os.path.exists(target_file_path):
                new_content = apply_diff_to_file(target_file_path, diff_content)
                if new_content is not None:
                    modified[file_path_in_diff] = new_content
            else:
                debug_utils.write_debug(f"File '{target_file_path}' not found in target directory, skipping diff application.", channel="Warning")
        except Exception as e:
            debug_utils.write_debug(f"Error processing diff block: {e}\nBlock content:\n{diff_block}", channel="Error")
            return {}  # In case of error, abort applying any diffs.
    debug_utils.write_debug("Diff application process completed.", channel="Information")
    return modified


def main_test_wrapper(directory, input_source, diff_text_terminal=None):
    """A wrapper for the main function for testing purposes."""
    class MockArgs:
        def __init__(self, directory, input, log_level="Debug", console_log_level="Debug", enable_file_log=False, log_dir="logs"):
            self.directory = directory
            self.input = input
            self.log_level = log_level
            self.console_log_level = console_log_level
            self.enable_file_log = enable_file_log
            self.log_dir = log_dir

    if input_source == 'terminal_input':
        mock_args = MockArgs(directory=directory, input='terminal_input')
        sys.stdin = io.StringIO(diff_text_terminal)
    else:
        mock_args = MockArgs(directory=directory, input=input_source)
    main_output = main_testable(mock_args)
    return main_output

def main_testable(args):
    """A testable version of main that returns a dict of results."""
    try:
        target_directory = os.path.abspath(args.directory)
    except Exception:
        return {"error": f"Error: Directory parameter is invalid: {args.directory}"}
    if not os.path.isdir(target_directory):
        return {"error": f"Error: Directory '{target_directory}' does not exist."}
    diff_text = ""
    input_source = args.input
    if input_source == 'clipboard':
        debug_utils.write_debug("Reading diff from clipboard using clipboard_utils.", channel="Debug")
        try:
            diff_text = clipboard.get_clipboard()
        except Exception as e:
            debug_utils.write_debug(f"Error reading from clipboard using clipboard_utils: {e}. Falling back to terminal input.", channel="Warning")
            input_source = None
    if input_source is None or (input_source == 'clipboard' and diff_text == ""):
        debug_utils.write_debug("Reading diff from terminal input. Press Ctrl+D after pasting the diff.", channel="Debug")
        diff_text = sys.stdin.read()
    elif os.path.isfile(input_source):
        debug_utils.write_debug(f"Reading diff from file: {input_source}", channel="Debug")
        try:
            with open(input_source, 'r') as f:
                diff_text = f.read()
        except Exception as e:
            debug_utils.write_debug(f"Error reading from file '{input_source}': {e}", channel="Error")
            return {"error": f"Error reading from file '{input_source}': {e}"}
    elif input_source != 'clipboard':
        debug_utils.write_debug("Treating input as direct diff text.", channel="Debug")
        diff_text = input_source
    if not diff_text:
        return {"warning": "No diff input provided."}
    debug_utils.write_debug("Starting diff parsing and application.", channel="Information")
    modified_contents = parse_diff_and_apply(diff_text, target_directory)
    # If no hunks were applied (i.e. modified_contents is empty) but diff_text was nonempty,
    # return a warning.
    if not modified_contents and diff_text.strip():
        return {"warning": "No valid diff applied.", "diff_text": diff_text, "input_source": input_source}
    return {"modified_files": modified_contents, "input_source": input_source, "diff_text": diff_text}

def main():
    parser = argparse.ArgumentParser(description="Apply git diff to files in a directory.")
    parser.add_argument("-d", "--directory", required=True, help="Path to the directory containing the files to modify.")
    parser.add_argument("-i", "--input", nargs='?', const='clipboard', default='clipboard',
                        help="Source of diff input. Use 'clipboard' (default) to read from clipboard, "
                             "a file path to read from a file, or just -i to read from terminal input.")
    parser.add_argument("--log-level", default="Debug", help="Set the debug log level (Verbose, Debug, Information, Warning, Error, Critical).")
    parser.add_argument("--console-log-level", default="Debug", help="Set the console log level (Verbose, Debug, Information, Warning, Error, Critical).")
    parser.add_argument("--enable-file-log", action="store_true", help="Enable file logging.")
    parser.add_argument("--log-dir", default=debug_utils.DEFAULT_LOG_DIR, help=f"Set the log directory (default: {debug_utils.DEFAULT_LOG_DIR}).")
    args = parser.parse_args()
    debug_utils.set_log_verbosity(args.log_level)
    debug_utils.set_console_verbosity(args.console_log_level)
    debug_utils.set_log_directory(args.log_dir)
    if args.enable_file_log:
        debug_utils.enable_file_logging()
    target_directory = os.path.abspath(args.directory)
    if not os.path.isdir(target_directory):
        debug_utils.write_debug(f"Error: Directory '{target_directory}' does not exist.", channel="Error")
        return
    diff_text = ""
    input_source = args.input
    if input_source == 'clipboard':
        debug_utils.write_debug("Reading diff from clipboard using clipboard_utils.", channel="Debug")
        try:
            diff_text = clipboard.get_clipboard()
        except Exception as e:
            debug_utils.write_debug(f"Error reading from clipboard using clipboard_utils: {e}. Falling back to terminal input.", channel="Warning")
            input_source = None
    if input_source is None or (input_source == 'clipboard' and diff_text == ""):
        debug_utils.write_debug("Reading diff from terminal input. Press Ctrl+D after pasting the diff.", channel="Debug")
        diff_text = sys.stdin.read()
    elif os.path.isfile(input_source):
        debug_utils.write_debug(f"Reading diff from file: {input_source}", channel="Debug")
        try:
            with open(input_source, 'r') as f:
                diff_text = f.read()
        except Exception as e:
            debug_utils.write_debug(f"Error reading from file '{input_source}': {e}", channel="Error")
            return
    elif input_source != 'clipboard':
        debug_utils.write_debug("Treating input as direct diff text.", channel="Debug")
        diff_text = input_source
    if not diff_text:
        debug_utils.write_debug("No diff input provided.", channel="Warning")
        return
    debug_utils.write_debug("Starting diff parsing and application.", channel="Information")
    parse_diff_and_apply(diff_text, target_directory)

if __name__ == "__main__":
    main()

