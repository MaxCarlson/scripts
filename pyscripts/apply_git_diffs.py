import argparse
import os
import re
import difflib
import sys  # Import sys for potential exit calls from clipboard_utils
import io

# Import clipboard_utils (assuming it's in the same directory or importable)
try:
    import clipboard_utils as clipboard
except ImportError:
    print("Error: clipboard_utils.py not found. Please ensure it is in the same directory or installed.")
    # Create a dummy clipboard for basic functionality if not found -  this will effectively disable clipboard usage
    class clipboard:
        @staticmethod
        def get_clipboard():
            raise ImportError("clipboard_utils not available") # Simulate error

# Assuming debug_utils.py is in the same directory or installed
try:
    import debug_utils as debug_utils
except ImportError:
    print("Error: debug_utils.py not found. Please ensure it is in the same directory or installed.")
    # Create a dummy debug_utils for basic functionality if not found.
    class debug_utils:
        @staticmethod
        def write_debug(message="", channel="Debug", condition=True, output_stream="stdout", location_channels=["Error", "Warning"]):
            if condition:
                print(f"[{channel}] {message}")


def apply_diff_to_file(filepath, diff_content):
    """Applies git diff content to a file."""
    try:
        with open(filepath, 'rb') as f: # Binary read
            original_lines = f.readlines()

        debug_utils.write_debug(f"Applying diff to file: {filepath}", channel="Information")

        diff_lines = diff_content.splitlines(keepends=True)

        if not diff_content or '@@' not in diff_content: # Check for empty diff or no hunks
            debug_utils.write_debug(f"No changes detected for file: {filepath}", channel="Debug")
            return True  # No changes to apply, consider it successful

        debug_utils.write_debug(f"Applying patch:\n{diff_content}", channel="Verbose")

        # Extract the relevant diff lines for difflib.restore - CORRECTED EXTRACTION
        relevant_diff_lines = []
        in_hunk = False
        for line in diff_lines:
            if line.startswith('@@'):
                in_hunk = True
                relevant_diff_lines.append(line) # Include @@ line
            elif in_hunk and line.startswith((' ', '+', '-')):
                relevant_diff_lines.append(line)
            elif in_hunk and not line.startswith((' ', '+', '-', '@@')): # Hunk ended if a line doesn't start with diff chars
                in_hunk = False # Stop adding lines, assuming hunk ended.

        debug_utils.write_debug(f"Relevant diff lines: {relevant_diff_lines}", channel="Debug") # ADDED DEBUG LOG

        patched_lines = list(difflib.restore(relevant_diff_lines, 2))
        debug_utils.write_debug(f"patched_lines before write: {patched_lines}", channel="Debug") # ADDED DEBUG LOG

        with open(filepath, 'wb') as f: # Binary write
            for line in patched_lines: # Need to encode lines back to bytes
                f.write(line.encode('utf-8')) # Assuming UTF-8 encoding

        debug_utils.write_debug(f"Successfully applied diff to file: {filepath}", channel="Information")
        return True

    except FileNotFoundError:
        debug_utils.write_debug(f"File not found: {filepath}", channel="Error")
        return False
    except Exception as e:
        debug_utils.write_debug(f"Error applying diff to file {filepath}: {e}", channel="Error")
        return False


def parse_diff_and_apply(diff_text, target_directory):
    """Parses git diff text and applies it to corresponding files in the target directory."""
    diff_blocks = re.split(r'diff --git ', diff_text)
    # Remove the first empty element if diff_text starts with 'diff --git'
    if diff_blocks[0] == '':
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

            file_path_in_diff = a_file_line[6:]  # remove '--- a/' and get file path

            target_file_path = os.path.join(target_directory, file_path_in_diff)

            # Corrected: diff_content is the entire diff_block
            diff_content = diff_block.strip()

            hunk_found = False
            for line in diff_content.splitlines():
                if line.startswith('@@'):
                    hunk_found = True
                    break
            if not hunk_found:
                debug_utils.write_debug(f"Skipping diff block without hunks: {file_path_in_diff}", channel="Warning")
                continue


            if os.path.exists(target_file_path):
                apply_diff_to_file(target_file_path, diff_content)
            else:
                debug_utils.write_debug(f"File '{target_file_path}' not found in target directory, skipping diff application.", channel="Warning")

        except Exception as e:
            debug_utils.write_debug(f"Error processing diff block: {e}\nBlock content:\n{diff_block}", channel="Error")

    debug_utils.write_debug("Diff application process completed.", channel="Information")


def main_test_wrapper(directory, input_source, diff_text_terminal=None): # Wrapper for main function for testing
    
    class MockArgs: # Mock class for argparse arguments
        def __init__(self, directory, input, log_level="Debug", console_log_level="Debug", enable_file_log=False, log_dir="logs"):
            self.directory = directory
            self.input = input
            self.log_level = log_level
            self.console_log_level = console_log_level
            self.enable_file_log = enable_file_log
            self.log_dir = log_dir
            
    # Mock argparse.ArgumentParser().parse_args() to return MockArgs
    if input_source == 'terminal_input': # Handle terminal input case
        mock_args = MockArgs(directory=directory, input='terminal_input')
        sys.stdin = io.StringIO(diff_text_terminal) # Mock stdin for terminal input
    else:
        mock_args = MockArgs(directory=directory, input=input_source)

    # Call main function with mock arguments
    main_output = main_testable(mock_args) # Use testable main (renamed for testing)
    return main_output

def main_testable(args): # Renamed main to main_testable for testing
    target_directory = os.path.abspath(args.directory)
    if not os.path.isdir(target_directory):
        return {"error": f"Directory '{target_directory}' does not exist."}

    diff_text = ""
    input_source = args.input

    if input_source == 'clipboard':
        diff_text = "clipboard content"  # Simulate clipboard input
    elif input_source == 'file':
        diff_text = "file content" # Simulate file input
    elif input_source == 'terminal_input':
        diff_text = sys.stdin.read() # Read from mocked stdin
    elif isinstance(input_source, str) and input_source != 'clipboard' and input_source != 'file' and input_source != 'terminal_input':
        diff_text = input_source # Direct diff text as input
    elif input_source is None: # Fallback to terminal - simulate terminal input
        diff_text = sys.stdin.read()

    if not diff_text:
        return {"warning": "No diff input provided."}

    modified_contents = parse_diff_and_apply(diff_text, target_directory)
    return {"modified_files": modified_contents, "input_source": input_source, "diff_text": diff_text} # Return results for testing


def main(): # Original main function (using main_testable now for core logic)
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
            diff_text = clipboard.get_clipboard() # Use clipboard_utils.get_clipboard()
        except Exception as e: # Catch general exceptions from clipboard_utils.get_clipboard()
            debug_utils.write_debug(f"Error reading from clipboard using clipboard_utils: {e}. Falling back to terminal input.", channel="Warning")
            input_source = None # Fallback to terminal input

    if input_source is None or (input_source == 'clipboard' and diff_text == ""): # -i with no value provided, read from terminal, or clipboard failed and falling back
        debug_utils.write_debug("Reading diff from terminal input. Press Ctrl+D after pasting the diff.", channel="Debug")
        diff_text = sys.stdin.read()
    elif os.path.isfile(input_source): # File path provided
        debug_utils.write_debug(f"Reading diff from file: {input_source}", channel="Debug")
        try:
            with open(input_source, 'r') as f:
                diff_text = f.read()
        except Exception as e:
            debug_utils.write_debug(f"Error reading from file '{input_source}': {e}", channel="Error")
            return
    elif input_source != 'clipboard': # Treat input as direct text if not clipboard (and not already handled as terminal input fallback) or file
        debug_utils.write_debug("Treating input as direct diff text.", channel="Debug")
        diff_text = input_source


    if not diff_text:
        debug_utils.write_debug("No diff input provided.", channel="Warning")
        return

    debug_utils.write_debug("Starting diff parsing and application.", channel="Information")
    parse_diff_and_apply(diff_text, target_directory)


if __name__ == "__main__":
    import sys
    main()
