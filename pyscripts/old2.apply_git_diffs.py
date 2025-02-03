#!/usr/bin/env python3
import argparse
import os
import re
import difflib
import sys  # For potential exit calls from clipboard_utils
import io

# Import clipboard_utils (backward-compatible wrapper)
try:
    import clipboard_utils as clipboard
except ImportError:
    print("Error: clipboard_utils.py not found. Please ensure it is in the same directory or installed.")
    # Dummy fallback: effectively disable clipboard usage
    class clipboard:
        @staticmethod
        def get_clipboard():
            raise ImportError("clipboard_utils not available")

# Import debug_utils (or its wrapper)
try:
    import debug_utils as debug_utils
except ImportError:
    print("Error: debug_utils.py not found. Please ensure it is in the same directory or installed.")
    # Dummy fallback for debug output
    class debug_utils:
        @staticmethod
        def write_debug(message="", channel="Debug", condition=True, output_stream="stdout", location_channels=["Error", "Warning"]):
            if condition:
                print(f"[{channel}] {message}")
        DEFAULT_LOG_DIR = os.path.expanduser("~/logs")

# ----------------------------
# Core functions
# ----------------------------

def apply_diff_to_file(filepath, diff_content):
    """Applies git diff content to a file and returns its updated content.
    
    Returns:
      - Updated file content as a string if successful.
      - An empty string if no changes were detected.
      - None if the file was not found or an error occurred.
    """
    try:
        with open(filepath, 'rb') as f:
            original_lines = f.readlines()

        debug_utils.write_debug(f"Applying diff to file: {filepath}", channel="Information")
        diff_lines = diff_content.splitlines(keepends=True)

        # If diff content is empty or contains no hunks, treat it as no changes.
        if not diff_content or '@@' not in diff_content:
            debug_utils.write_debug(f"No changes detected for file: {filepath}", channel="Debug")
            return ""

        debug_utils.write_debug(f"Applying patch:\n{diff_content}", channel="Verbose")

        # Extract relevant diff lines for difflib.restore
        relevant_diff_lines = []
        in_hunk = False
        for line in diff_lines:
            if line.startswith('@@'):
                in_hunk = True
                relevant_diff_lines.append(line)
            elif in_hunk and line.startswith((' ', '+', '-')):
                relevant_diff_lines.append(line)
            elif in_hunk and not line.startswith((' ', '+', '-', '@@')):
                in_hunk = False  # End of current hunk

        debug_utils.write_debug(f"Relevant diff lines: {relevant_diff_lines}", channel="Debug")
        patched_lines = list(difflib.restore(relevant_diff_lines, 2))
        debug_utils.write_debug(f"patched_lines before write: {patched_lines}", channel="Debug")

        with open(filepath, 'wb') as f:
            for line in patched_lines:
                f.write(line.encode('utf-8'))

        debug_utils.write_debug(f"Successfully applied diff to file: {filepath}", channel="Information")
        # Read and return the updated content in text mode.
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    except FileNotFoundError:
        debug_utils.write_debug(f"File not found: {filepath}", channel="Error")
        return None
    except Exception as e:
        debug_utils.write_debug(f"Error applying diff to file {filepath}: {e}", channel="Error")
        return None


def parse_diff_and_apply(diff_text, target_directory):
    """Parses git diff text and applies it to corresponding files in the target directory.
    
    Returns a dictionary mapping file paths (as given in the diff, without the 'a/' prefix) 
    to their updated contents. If no valid diff is applied, returns an empty dict.
    """
    modified = {}
    diff_blocks = re.split(r'diff --git ', diff_text)
    if diff_blocks and diff_blocks[0] == '':
        diff_blocks = diff_blocks[1:]

    for diff_block in diff_blocks:
        if not diff_block:
            continue

        try:
            lines = diff_block.strip().splitlines()
            if len(lines) < 2:
                debug_utils.write_debug(f"Skipping invalid diff block: Not enough lines\n{diff_block}", channel="Warning")
                continue

            a_file_line = next((line for line in lines if line.startswith('--- a/')), None)
            b_file_line = next((line for line in lines if line.startswith('+++ b/')), None)
            if not a_file_line or not b_file_line:
                debug_utils.write_debug(f"Skipping invalid diff block: Missing --- a/ or +++ b/\n{diff_block}", channel="Warning")
                continue

            file_path_in_diff = a_file_line[6:]  # Remove '--- a/' prefix
            target_file_path = os.path.join(target_directory, file_path_in_diff)
            diff_content = diff_block.strip()

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
    except Exception as e:
        return {"error": f"Invalid directory parameter: {args.directory}"}
    if not os.path.isdir(target_directory):
        return {"error": f"Directory '{target_directory}' does not exist."}

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

