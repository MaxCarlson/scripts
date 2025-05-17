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
    import cross_platform.debug_utils as debug_utils
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
    import re 
    header = hunk[0]
    m = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', header)
    if not m:
        return original_lines
    orig_start = int(m.group(1)) - 1 
    orig_count = int(m.group(2)) if m.group(2) else 1
    
    new_hunk_lines = []
    for line in hunk[1:]:
        if line.startswith(' '):
            new_hunk_lines.append(line[1:] + "\n")
        elif line.startswith('+'):
            new_hunk_lines.append(line[1:] + "\n")
        elif line.startswith('-'):
            continue
            
    new_file_lines = original_lines[:orig_start] + \
                     new_hunk_lines + \
                     original_lines[orig_start+orig_count:]
    return new_file_lines

def apply_unified_diff(original_lines, diff_content):
    diff_lines = diff_content.splitlines()
    hunks = extract_hunks(diff_lines) 
    if not hunks:
        debug_utils.write_debug("No hunks found in diff.", channel="Debug")
        return original_lines
    
    new_lines = list(original_lines) 

    for hunk_data in reversed(hunks):
        new_lines = apply_hunk(new_lines, hunk_data)
        
    return new_lines

# ----------------------------
# Core functions
# ----------------------------
def apply_diff_to_file(filepath, diff_content):
    try:
        original_lines = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                original_lines = f.readlines()
        except FileNotFoundError:
            pass 
            
        debug_utils.write_debug(f"Applying diff to file: {filepath}", channel="Information")
        
        is_new_file_marker = "--- /dev/null" in diff_content 
        if not diff_content.strip() or ('@@' not in diff_content and not is_new_file_marker):
            if not is_new_file_marker:
                 debug_utils.write_debug(f"No actual changes (hunks '@@') detected for existing file: {filepath}", channel="Debug")
            return ''.join(original_lines)

        new_lines = apply_unified_diff(original_lines, diff_content)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(''.join(new_lines))
        debug_utils.write_debug(f"Successfully applied diff to file: {filepath}", channel="Information")
        return ''.join(new_lines)
    except Exception as e:
        debug_utils.write_debug(f"Error applying diff to file {filepath}: {e}", channel="Error")
        return None

def parse_diff_and_apply(diff_text, target_directory):
    import re, os
    modified = {}
    diff_blocks = re.split(r'^diff --git ', diff_text, flags=re.MULTILINE)
    if diff_blocks and diff_blocks[0].strip() == '':
        diff_blocks = diff_blocks[1:]

    if not diff_blocks and diff_text.strip():
        debug_utils.write_debug("No 'diff --git' blocks found in input.", channel="Warning")
        return {}
    if not diff_blocks:
        return {}

    for diff_block_content in diff_blocks:
        if not diff_block_content.strip():
            continue
        lines = diff_block_content.strip().splitlines()
        
        a_file_line = next((line for line in lines if line.startswith('--- a/')), None)
        b_file_line = next((line for line in lines if line.startswith('+++ b/')), None)

        path_for_debug = "unknown_file"
        # Determine path for debug messages robustly
        if b_file_line and b_file_line[len("+++ b/"):].strip() != "/dev/null":
            path_for_debug = b_file_line[len("+++ b/"):].strip()
        elif a_file_line and a_file_line[len("--- a/"):].strip() != "/dev/null":
            path_for_debug = a_file_line[len("--- a/"):].strip()
        elif b_file_line: # Fallback for new files where a_file is /dev/null
            path_for_debug = b_file_line[len("+++ b/"):].strip()
        elif a_file_line: # Fallback for deleted files where b_file is /dev/null
             path_for_debug = a_file_line[len("--- a/"):].strip()

        if not a_file_line or not b_file_line:
            debug_utils.write_debug(f"Unsupported diff format: Missing '--- a/' or '+++ b/' markers for '{path_for_debug}'. Cannot apply.", channel="Warning")
            return {} 

        # --- Check for unsupported diff types (MODIFIED CHECKS) ---
        # These checks look for lines that *are* directives, not just *contain* the strings.
        # These lines are part of the diff metadata, not hunk content lines starting with ' ', '+', '-'
        
        # For lines that are actual git directives (e.g. "old mode ...", "new file mode ...")
        # These lines do not start with '+', '-', ' ' in the `lines` list here.
        
        for line_in_block in lines:
            stripped_line = line_in_block.strip() # Check the line itself
            if stripped_line.startswith("Binary files ") and stripped_line.endswith(" differ"):
                debug_utils.write_debug(f"Unsupported diff type: Binary file changes detected for '{path_for_debug}'. This script only handles text diffs. Cannot apply.", channel="Warning")
                return {}
            if stripped_line == "new file mode 120000" or stripped_line == "old mode 120000":
                 # More specific check for symlink mode lines
                debug_utils.write_debug(f"Unsupported diff type: Symbolic link operation (mode 120000) detected for '{path_for_debug}'. Cannot apply.", channel="Warning")
                return {}
            if stripped_line.startswith("rename from ") or stripped_line.startswith("rename to ") or \
               stripped_line.startswith("copy from ") or stripped_line.startswith("copy to "):
                debug_utils.write_debug(f"Unsupported diff type: File rename/copy operation detected for '{path_for_debug}'. Cannot apply.", channel="Warning")
                return {}
        
        has_mode_directive = any(line.strip().startswith("old mode ") or line.strip().startswith("new mode ") or line.strip().startswith("deleted file mode ") for line in lines)
        hunk_found = any(line.startswith('@@') for line in lines)

        if has_mode_directive and not hunk_found:
            is_actual_symlink_directive = any(line.strip() == "new file mode 120000" or line.strip() == "old mode 120000" for line in lines)
            if not is_actual_symlink_directive: # Avoid double warning if already caught as symlink
                debug_utils.write_debug(f"Unsupported diff type: File mode change without content modification detected for '{path_for_debug}'. Cannot apply.", channel="Warning")
                return {}
            
        if not hunk_found:
            # If it's not a recognized special type (binary, symlink, rename, mode-only) but still lacks hunks.
            # This can happen for new empty files or deleting all content.
            # Git usually generates "empty" hunks like @@ -0,0 +0,0 @@ or similar.
            # For now, keeping the strict check that substantive text diffs need hunks.
            is_new_empty_file = a_file_line.strip() == "--- /dev/null" and not any(l.startswith('+') for l in lines if l.startswith(('+','-',' ')))
            is_delete_all_content = b_file_line.strip() == "+++ /dev/null" and not any(l.startswith('-') for l in lines if l.startswith(('+','-',' ')))

            if not (is_new_empty_file or is_delete_all_content):
                 debug_utils.write_debug(f"Unsupported diff format: No content hunks '@@' found for '{path_for_debug}' and not a recognized empty file operation. Cannot apply.", channel="Warning")
                 return {}
            
    # Second pass: Apply them
    for diff_block_content in diff_blocks:
        if not diff_block_content.strip():
            continue
        try:
            lines = diff_block_content.strip().splitlines()
            
            current_a_file_line = next((line for line in lines if line.startswith('--- a/')), None)
            current_b_file_line = next((line for line in lines if line.startswith('+++ b/')), None)
            
            if not current_a_file_line or not current_b_file_line: 
                continue 

            file_path_in_diff = None
            path_from_b = current_b_file_line[len("+++ b/"):].strip()
            path_from_a = current_a_file_line[len("--- a/"):].strip()

            if path_from_b != "/dev/null":
                file_path_in_diff = path_from_b
            elif path_from_a != "/dev/null": 
                file_path_in_diff = path_from_a
            elif path_from_a == "/dev/null" and path_from_b == "/dev/null":
                 debug_utils.write_debug(f"Skipping diff block with /dev/null for both a and b paths.", channel="Warning")
                 continue
            else: 
                 debug_utils.write_debug(f"Could not determine filename from diff headers for applying: '{current_a_file_line}' and '{current_b_file_line}'. Skipping block.", channel="Warning")
                 continue

            if not file_path_in_diff: 
                 debug_utils.write_debug(f"File path could not be determined for block. Skipping application.\n{diff_block_content[:200]}...", channel="Warning")
                 continue 

            target_file_path = os.path.join(target_directory, file_path_in_diff)
            is_new_file_marker = (path_from_a == "/dev/null")
            
            if os.path.exists(target_file_path) or is_new_file_marker:
                new_content = apply_diff_to_file(target_file_path, diff_block_content)
                if new_content is not None:
                    modified[file_path_in_diff] = new_content
            else:
                debug_utils.write_debug(f"File '{target_file_path}' does not exist and not a new file diff. Skipping.", channel="Warning")
        except Exception as e:
            debug_utils.write_debug(f"Error processing diff block: {e}\nBlock content:\n{diff_block_content[:200]}...", channel="Error")
            return {} 
            
    debug_utils.write_debug("Diff application process completed.", channel="Information")
    return modified

# main_test_wrapper, main_testable, and main functions remain the same as the version that passed 22 tests.
def main_test_wrapper(directory, input_source, diff_text_terminal=None):
    class MockArgsLocalTest: 
        def __init__(self, directory, input_val, log_level="Debug", console_log_level="Debug", 
                     enable_file_log=False, log_dir="logs", force=False):
            self.directory = directory if directory is not None else "." 
            self.input = input_val 
            self.log_level = log_level
            self.console_log_level = console_log_level
            self.enable_file_log = enable_file_log
            self.log_dir = log_dir
            self.force = force 

    current_dir_for_mock = directory if directory is not None else "."
    mock_args = MockArgsLocalTest(directory=current_dir_for_mock, input_val=input_source)

    original_stdin = sys.stdin
    if input_source == 'terminal_input':
        sys.stdin = io.StringIO(diff_text_terminal if diff_text_terminal is not None else "")
    
    try:
        main_output = main_testable(mock_args)
    finally:
        if input_source == 'terminal_input':
            sys.stdin = original_stdin
            
    return main_output

def main_testable(args):
    try:
        target_directory = os.path.abspath(args.directory) 
    except Exception as e:
        return {"error": f"Error resolving target directory '{getattr(args, 'directory', 'MISSING')}': {e}"}

    if not os.path.isdir(target_directory):
        return {"error": f"Error: Directory '{target_directory}' does not exist."}
        
    diff_text = ""
    input_source = args.input

    if input_source == 'clipboard':
        debug_utils.write_debug("Reading diff from clipboard using clipboard_utils.", channel="Debug")
        try:
            diff_text = clipboard.get_clipboard()
            if not diff_text or not diff_text.strip(): 
                 debug_utils.write_debug("Clipboard is empty. Falling back to terminal input.", channel="Warning")
                 input_source = 'terminal_input' 
        except Exception as e:
            debug_utils.write_debug(f"Error reading from clipboard: {e}. Falling back to terminal input.", channel="Warning")
            input_source = 'terminal_input'
            diff_text = "" 
    
    if input_source == 'terminal_input': 
        if sys.stdin is not None and sys.stdin.isatty():
            debug_utils.write_debug("Reading diff from terminal input. Press Ctrl+D (Unix) or Ctrl+Z then Enter (Windows) after pasting.", channel="Debug")
        else: 
            debug_utils.write_debug("Reading diff from piped terminal input or non-interactive stdin.", channel="Debug")
        if sys.stdin is not None:
            diff_text = sys.stdin.read()
        else:
            debug_utils.write_debug("sys.stdin is None, cannot read terminal input.", channel="Error")
            return {"error": "Cannot read from terminal input, stdin is not available."}

    elif os.path.isfile(input_source):
        debug_utils.write_debug(f"Reading diff from file: {input_source}", channel="Debug")
        try:
            with open(input_source, 'r', encoding='utf-8') as f:
                diff_text = f.read()
        except Exception as e:
            return {"error": f"Error reading from file '{input_source}': {e}"}
    elif input_source != 'clipboard': 
        debug_utils.write_debug("Treating input as direct diff text.", channel="Debug")
        diff_text = input_source

    if not diff_text or not diff_text.strip():
        return {"warning": "No diff input provided."}
        
    debug_utils.write_debug("Starting diff parsing and application.", channel="Information")
    modified_contents = parse_diff_and_apply(diff_text, target_directory)

    if not modified_contents and diff_text.strip():
        return {"warning": "No valid diff applied. This could be due to unsupported diff types, validation errors, or all diffs skipped.", "diff_text": diff_text, "input_source": args.input}
            
    return {"modified_files": modified_contents, "input_source": args.input, "diff_text": diff_text}

def main():
    parser = argparse.ArgumentParser(description="Apply git diff to files in a directory.")
    parser.add_argument("-d", "--directory", default=".", 
                        help="Path to the directory containing the files to modify. Defaults to the current directory.")
    parser.add_argument("-i", "--input", nargs='?', const='terminal_input', default='clipboard',
                        help="Source of diff input. Use 'clipboard' (default) to read from clipboard, "
                             "a file path to read from a file, or 'terminal_input' (or just -i with no value) to read from terminal input. "
                             "If clipboard is empty, it will fall back to terminal input.")
    parser.add_argument("--log-level", default="Debug", help="Set the debug log level (Verbose, Debug, Information, Warning, Error, Critical).")
    parser.add_argument("--console-log-level", default="Debug", help="Set the console log level (Verbose, Debug, Information, Warning, Error, Critical).")
    parser.add_argument("--enable-file-log", action="store_true", help="Enable file logging.")
    parser.add_argument("--log-dir", default=debug_utils.DEFAULT_LOG_DIR, help=f"Set the log directory (default: {debug_utils.DEFAULT_LOG_DIR}).")

    parser.add_argument("--help-format", action="store_true", help="Print a message to guide LLMs on how to format their output for easy application.")

    args = parser.parse_args()

    if args.help_format:
        print("""
        To format output in a way that can be easily copied and applied to change a file, follow this structure:

        ```<language> name=<filename>
        <contents of the file>
        ```

        Example:
        ```python name=example.py
        print("Hello, World!")
        ```
        The diff tool expects standard `git diff -u` or `diff -u` formatted patches.
        Provide the patch content via clipboard, file, or terminal input.
        """)
        return

    debug_utils.set_log_verbosity(args.log_level)
    debug_utils.set_console_verbosity(args.console_log_level)
    debug_utils.set_log_directory(args.log_dir)
    if args.enable_file_log:
        debug_utils.enable_file_logging()
    
    results = main_testable(args)

    if "error" in results:
        debug_utils.write_debug(results["error"], channel="Error")
        sys.exit(1)
    elif "warning" in results:
        debug_utils.write_debug(results["warning"], channel="Warning")
    elif "modified_files" in results and results["modified_files"]:
        count = len(results["modified_files"])
        debug_utils.write_debug(f"Successfully applied changes to {count} file(s).", channel="Information")
    elif "modified_files" in results and not results["modified_files"] and results.get("diff_text","").strip():
         debug_utils.write_debug("No files were modified. This could be due to invalid/unsupported diff types or all diffs skipped.", channel="Information")


if __name__ == "__main__":
    main()
