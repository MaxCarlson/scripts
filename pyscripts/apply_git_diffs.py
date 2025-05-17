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
            if channel in ["Error", "Critical", "Warning"]:
                 print(f"FALLBACK_DEBUG [{channel}] {message}")
            exc_info_val = kwargs.get('exc_info')
            if exc_info_val and isinstance(exc_info_val, Exception): # Check if it's an actual exception instance
                 print(f"FALLBACK_DEBUG_EXCEPTION: {exc_info_val}")
            elif exc_info_val: # If exc_info=True, it won't be an instance
                 import traceback
                 print("FALLBACK_DEBUG_TRACEBACK:")
                 traceback.print_exc()


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
# Helper Functions
# ----------------------------
def get_path_from_diff_header_line(line_content, expected_prefix):
    if not line_content or not line_content.startswith(expected_prefix): # Added None check for line_content
        return None 
    
    path_part = line_content[len(expected_prefix):].strip()
    
    if path_part == "/dev/null": # Git sometimes uses "--- /dev/null" directly
        return "dev/null"
    # Standard git diff paths are "a/path" or "b/path" relative to repo root for files.
    # If "/dev/null" is used, it means one side doesn't exist in that state.
    # The "a/" or "b/" prefix needs to be stripped if present and not part of filename.
    if (path_part.startswith("a/") or path_part.startswith("b/")) and len(path_part) > 2 :
        return path_part[2:]
    return path_part 

def get_output_copy_path(original_path):
    dirname = os.path.dirname(original_path)
    filename = os.path.basename(original_path)
    name_part, ext_part = os.path.splitext(filename)
    
    actual_name_for_suffix = name_part
    if filename.startswith(".") and not ext_part: 
        actual_name_for_suffix = filename
        ext_part = "" 
    elif not ext_part and name_part == filename: 
        actual_name_for_suffix = filename
        
    counter = 1
    while True:
        new_filename = f"{actual_name_for_suffix}_applied_diff{counter}{ext_part}"
        new_path = os.path.join(dirname, new_filename)
        if not os.path.exists(new_path):
            return new_path
        counter += 1
        if counter > 999: 
            debug_utils.write_debug(f"Could not find a unique output copy name for '{original_path}' after 999 tries. Using last attempt: '{new_path}'", channel="Warning")
            return new_path

# (extract_hunks, apply_hunk, apply_unified_diff remain the same)
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
        return list(original_lines) 
    
    new_lines = list(original_lines) 

    for hunk_data in reversed(hunks):
        new_lines = apply_hunk(new_lines, hunk_data)
        
    return new_lines
# ----------------------------
# Core functions
# ----------------------------
def apply_diff_to_file(filepath_to_read, diff_content, dry_run, effective_write_filepath):
    try:
        original_lines = []
        if os.path.exists(filepath_to_read): 
            try:
                with open(filepath_to_read, 'r', encoding='utf-8') as f:
                    original_lines = f.readlines()
            except Exception as e:
                debug_utils.write_debug(f"Error reading source file '{filepath_to_read}': {e}", channel="Error", exc_info=e)
                return None
            
        log_source_path = filepath_to_read if os.path.exists(filepath_to_read) else f"source for new file '{os.path.basename(effective_write_filepath)}'"


        if dry_run:
            debug_utils.write_debug(f"DRY RUN: Processing diff for {log_source_path}", channel="Information")
        else:
            debug_utils.write_debug(f"Processing diff for {log_source_path}", channel="Information")

        # Determine if it's a new file based on the --- line from its own diff_content
        a_line_in_block = ""
        for l_content in diff_content.splitlines(): # Iterate over lines of the current diff_block
            if l_content.startswith("--- "):
                a_line_in_block = l_content
                break
        
        path_from_a_in_block = get_path_from_diff_header_line(a_line_in_block, "--- ")
        is_actually_new_file_op = (path_from_a_in_block == "dev/null")
        hunks_present_in_diff = '@@' in diff_content

        if not hunks_present_in_diff and not is_actually_new_file_op :
             debug_utils.write_debug(f"No content hunks '@@' detected for existing file operation on {log_source_path}. Assuming no change.", channel="Debug")
             return ''.join(original_lines)

        patched_lines = apply_unified_diff(original_lines, diff_content)
        patched_content_str = ''.join(patched_lines)
        
        if not dry_run:
            try:
                write_dir = os.path.dirname(effective_write_filepath)
                if write_dir and not os.path.exists(write_dir):
                    os.makedirs(write_dir, exist_ok=True)
                    debug_utils.write_debug(f"Created directory '{write_dir}' for output file.", channel="Information")

                with open(effective_write_filepath, 'w', encoding='utf-8') as f:
                    f.write(patched_content_str)
                debug_utils.write_debug(f"Successfully applied diff. Output written to: '{effective_write_filepath}'", channel="Information")
            except Exception as e:
                debug_utils.write_debug(f"Error writing output to file '{effective_write_filepath}': {e}", channel="Error", exc_info=e)
                return None 
        else:
            action_would_be = ""
            if not os.path.exists(filepath_to_read) and is_actually_new_file_op : 
                 action_would_be = "created"
            elif ''.join(original_lines) != patched_content_str: 
                 action_would_be = "modified"
            else: 
                 action_would_be = "unchanged"
            debug_utils.write_debug(f"DRY RUN: File '{effective_write_filepath}' would be {action_would_be}.", channel="Information")

        return patched_content_str 
    except Exception as e:
        debug_utils.write_debug(f"Error applying diff related to source '{filepath_to_read}': {e}", channel="Error", exc_info=e)
        return None

def parse_diff_and_apply(diff_text, target_directory, dry_run=False, output_copy=False):
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
        
        a_file_line_str = next((line for line in lines if line.startswith('--- ')), None)
        b_file_line_str = next((line for line in lines if line.startswith('+++ ')), None)

        path_from_a = get_path_from_diff_header_line(a_file_line_str, "--- ") if a_file_line_str else None
        path_from_b = get_path_from_diff_header_line(b_file_line_str, "+++ ") if b_file_line_str else None
        
        path_for_debug = "unknown_file_in_diff_block"
        if path_from_b and path_from_b != "dev/null": path_for_debug = path_from_b
        elif path_from_a and path_from_a != "dev/null": path_for_debug = path_from_a
        elif path_from_b: path_for_debug = path_from_b # Handles new file name from b when a is dev/null
        elif path_from_a: path_for_debug = path_from_a # Handles deleted file name from a when b is dev/null


        if not a_file_line_str or not b_file_line_str or path_from_a is None or path_from_b is None:
            debug_utils.write_debug(f"Unsupported diff format: Missing or unparsable '--- ' or '+++ ' Cfor '{path_for_debug}'. Cannot apply.", channel="Warning")
            return {} 

        for line_in_block in lines: # Iterate over metadata lines of the diff block
            stripped_line = line_in_block.strip() 
            if stripped_line.startswith("Binary files ") and stripped_line.endswith(" differ"):
                debug_utils.write_debug(f"Unsupported diff type: Binary file changes detected for '{path_for_debug}'. This script only handles text diffs. Cannot apply.", channel="Warning")
                return {}
            if stripped_line == "new file mode 120000" or stripped_line == "old mode 120000":
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
            if not is_actual_symlink_directive: 
                debug_utils.write_debug(f"Unsupported diff type: File mode change without content modification detected for '{path_for_debug}'. Cannot apply.", channel="Warning")
                return {}
        
        # *** MODIFIED HUNK VALIDATION ***
        # If it's not an explicitly rejected special type (binary, symlink, rename, pure mode change),
        # then it must have hunks to be considered a valid text content modification/creation.
        if not hunk_found:
            # This implies it's not a binary, symlink, rename, or mode-only change (as those would have returned {} already),
            # yet it's missing hunks. This is invalid for content modification or non-empty new files.
            debug_utils.write_debug(f"Invalid diff block: No content hunks '@@' found for textual diff operation on '{path_for_debug}'. Script requires hunks for content changes. Cannot apply.", channel="Warning")
            return {}
            
    # Second pass for application
    for diff_block_content in diff_blocks:
        if not diff_block_content.strip():
            continue
        try:
            lines = diff_block_content.strip().splitlines() # For extracting file paths from this block
            
            current_a_file_line_str = next((line for line in lines if line.startswith('--- ')), None)
            current_b_file_line_str = next((line for line in lines if line.startswith('+++ ')), None)
            
            if not current_a_file_line_str or not current_b_file_line_str: continue 

            current_path_from_a = get_path_from_diff_header_line(current_a_file_line_str, "--- ")
            current_path_from_b = get_path_from_diff_header_line(current_b_file_line_str, "+++ ")

            if current_path_from_a is None or current_path_from_b is None:
                debug_utils.write_debug(f"Could not determine paths in second pass. A_line: '{current_a_file_line_str}', B_line: '{current_b_file_line_str}'. Skipping block.", channel="Warning")
                continue

            file_path_in_diff = None 
            if current_path_from_b != "dev/null": 
                file_path_in_diff = current_path_from_b
            elif current_path_from_a != "dev/null": 
                file_path_in_diff = current_path_from_a
            # If both are "dev/null" (e.g. diff of /dev/null against /dev/null), file_path_in_diff remains None
            # This case should be rare and probably represents no actual file target.
            # The check "if not file_path_in_diff" below will catch it.

            if not file_path_in_diff: # If path is still None (e.g. both --- and +++ were /dev/null)
                 debug_utils.write_debug(f"File path in diff is empty or /dev/null for both sides. Skipping application. A: '{current_path_from_a}', B: '{current_path_from_b}'", channel="Warning")
                 continue 

            original_target_filepath = os.path.join(target_directory, file_path_in_diff)
            
            effective_write_filepath = original_target_filepath
            if output_copy:
                effective_write_filepath = get_output_copy_path(original_target_filepath)

            is_new_file_marker = (current_path_from_a == "dev/null")
            
            if os.path.exists(original_target_filepath) or is_new_file_marker:
                if output_copy and not dry_run:
                     debug_utils.write_debug(f"Output copy mode: Result for '{file_path_in_diff}' will be written to '{os.path.basename(effective_write_filepath)}'", channel="Information")

                patched_content = apply_diff_to_file(original_target_filepath, diff_block_content, dry_run, effective_write_filepath)
                if patched_content is not None:
                    modified[file_path_in_diff] = patched_content 
            else:
                debug_utils.write_debug(f"File '{original_target_filepath}' does not exist and not a new file diff (is_new_file_marker was {is_new_file_marker}). Skipping.", channel="Warning")
        except Exception as e:
            current_file_path_for_exc = file_path_in_diff if 'file_path_in_diff' in locals() and file_path_in_diff else "unknown_file_during_exception"
            debug_utils.write_debug(f"Error processing diff block for '{current_file_path_for_exc}': {e}", channel="Error", exc_info=e)
            return {} 
            
    debug_utils.write_debug("Diff application process completed.", channel="Information")
    return modified

# main_test_wrapper, main_testable, and main functions remain the same
def main_test_wrapper(directory, input_source, diff_text_terminal=None, dry_run=False, output_copy=False):
    class MockArgsLocalTest: 
        def __init__(self, directory, input_val, log_level="Debug", console_log_level="Debug", 
                     enable_file_log=False, log_dir="logs", force=False,
                     dry_run_val=False, output_copy_val=False): 
            self.directory = directory if directory is not None else "." 
            self.input = input_val 
            self.log_level = log_level
            self.console_log_level = console_log_level
            self.enable_file_log = enable_file_log
            self.log_dir = log_dir
            self.force = force 
            self.dry_run = dry_run_val
            self.output_copy = output_copy_val

    current_dir_for_mock = directory if directory is not None else "."
    mock_args = MockArgsLocalTest(directory=current_dir_for_mock, input_val=input_source, 
                                  dry_run_val=dry_run, output_copy_val=output_copy)

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
        
    if hasattr(args, 'dry_run') and args.dry_run: 
        debug_utils.write_debug("DRY RUN MODE: No changes will be written to disk.", channel="Information")

    modified_contents = parse_diff_and_apply(
        diff_text, 
        target_directory, 
        getattr(args, 'dry_run', False), 
        getattr(args, 'output_copy', False) 
    )

    if not modified_contents and diff_text.strip():
        return {"warning": "No valid diff applied. This could be due to unsupported diff types, validation errors, or all diffs skipped.", "diff_text": diff_text, "input_source": args.input}
            
    return {"modified_files": modified_contents, "input_source": args.input, "diff_text": diff_text}

def main():
    parser = argparse.ArgumentParser(description="Apply git diff to files in a directory.")
    parser.add_argument("-d", "--directory", default=".", 
                        help="Path to the directory containing the files to modify. Defaults to the current directory.")
    parser.add_argument("-i", "--input", nargs='?', const='terminal_input', default='clipboard',
                        help="Source of diff input: 'clipboard' (default), a file path, or 'terminal_input' "
                             "(or just -i). If clipboard empty, falls back to terminal.")
    parser.add_argument("-o", "--output-copy", action="store_true",
                        help="Write patched output to a new file (filename_applied_diffN.ext) instead of modifying in-place.")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Perform a dry run. Show what would be done but don't make any changes to files.")
    
    parser.add_argument("-l", "--log-level", default="Debug", 
                        help="Set the file logging level (Verbose, Debug, Information, Warning, Error, Critical).")
    parser.add_argument("-c", "--console-log-level", default="Information", 
                        help="Set the console logging level (Verbose, Debug, Information, Warning, Error, Critical).")
    parser.add_argument("-e", "--enable-file-log", action="store_true", 
                        help="Enable file logging to the specified log directory.")
    parser.add_argument("-g", "--log-dir", default=debug_utils.DEFAULT_LOG_DIR, 
                        help=f"Set the log directory (default: {debug_utils.DEFAULT_LOG_DIR}).")

    parser.add_argument("--help-format", action="store_true", 
                        help="Print a message to guide LLMs on how to format their output for easy application.")

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
    if args.enable_file_log: 
        debug_utils.set_log_directory(args.log_dir) 
        debug_utils.enable_file_logging()
    
    results = main_testable(args)

    if "error" in results:
        debug_utils.write_debug(results["error"], channel="Error")
        sys.exit(1)
    elif "warning" in results:
        debug_utils.write_debug(results["warning"], channel="Warning")
        if "No diff input provided." not in results["warning"] and \
           ("modified_files" not in results or not results["modified_files"]): 
             sys.exit(2) 
    elif "modified_files" in results:
        if results["modified_files"]:
            count = len(results["modified_files"])
            action_desc = "would be changed (dry run)" if args.dry_run else "changed"
            debug_utils.write_debug(f"Successfully processed diff. {count} file(s) {action_desc}.", channel="Information")
            if args.dry_run:
                 debug_utils.write_debug("Dry run complete. No files were actually modified.", channel="Information")
        elif results.get("diff_text","").strip(): 
             if not results.get("warning"): 
                debug_utils.write_debug("Diff processed, but no files were modified or targeted for modification.", channel="Information")

if __name__ == "__main__":
    main()
