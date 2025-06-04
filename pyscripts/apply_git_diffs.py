#!/usr/bin/env python3
# File: apply_git_diffs.py
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
            if exc_info_val and isinstance(exc_info_val, Exception):
                print(f"FALLBACK_DEBUG_EXCEPTION: {exc_info_val}")
            elif exc_info_val:
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
    if not line_content or not line_content.startswith(expected_prefix):
        return None
    path_part = line_content[len(expected_prefix):].strip()
    if path_part == "/dev/null":
        return "dev/null"
    if (path_part.startswith("a/") or path_part.startswith("b/")) and len(path_part) > 2:
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

def extract_hunks(diff_lines):
    hunks = []
    i = 0
    while i < len(diff_lines):
        line = diff_lines[i]
        if line.startswith('@@'):
            hunk = [line]
            i += 1
            while i < len(diff_lines) and \
                  (diff_lines[i].startswith((' ', '+', '-')) or \
                   diff_lines[i].strip() == r"\ No newline at end of file"):
                hunk.append(diff_lines[i])
                i += 1
            hunks.append(hunk)
        else:
            i += 1
    return hunks

def apply_hunk(original_lines, hunk):
    header = hunk[0]
    m = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', header)
    if not m:
        debug_utils.write_debug(f"Malformed hunk header: {header}. Skipping hunk.", channel="Warning")
        return list(original_lines)

    old_start_line_num = int(m.group(1))
    old_line_count = int(m.group(2)) if m.group(2) else 1
    # new_start_line_num = int(m.group(3)) # Not directly used
    # new_line_count = int(m.group(4)) if m.group(4) else 1 # Not directly used

    new_hunk_lines_content = []
    hunk_body = hunk[1:]
    idx = 0
    while idx < len(hunk_body):
        current_diff_line = hunk_body[idx]
        
        if current_diff_line.startswith(' ') or current_diff_line.startswith('+'):
            payload = current_diff_line[1:]
            line_ending = "\n"
            if (idx + 1 < len(hunk_body)) and \
               (hunk_body[idx+1].strip() == r"\ No newline at end of file"):
                line_ending = ""
            
            new_hunk_lines_content.append(payload + line_ending)
            idx += 1
        elif current_diff_line.startswith('-'):
            if (idx + 1 < len(hunk_body)) and \
               (hunk_body[idx+1].strip() == r"\ No newline at end of file"):
                idx += 1 
            idx += 1 
        elif current_diff_line.strip() == r"\ No newline at end of file":
            idx += 1 
        else:
            debug_utils.write_debug(f"Unexpected line in hunk body: '{current_diff_line}'. Skipping.", channel="Warning")
            idx += 1
    
    # Debug prints (uncomment to trace specific test failures)
    # if old_start_line_num == 0:
    #     print(f"DEBUG apply_hunk (new file case): header='{header}'")
    #     print(f"DEBUG apply_hunk: original_lines: {original_lines}")
    #     print(f"DEBUG apply_hunk: hunk_body: {hunk_body}")
    #     print(f"DEBUG apply_hunk: new_hunk_lines_content: {new_hunk_lines_content}")

    if old_start_line_num == 0:
        if old_line_count == 0:
            return new_hunk_lines_content
        else:
            debug_utils.write_debug(
                f"Invalid hunk for new file (old_line_count > 0 when old_start_line is 0): {header}",
                channel="Warning",
            )
            return None

    orig_slice_start_idx = old_start_line_num - 1
    
    if orig_slice_start_idx < 0:
        debug_utils.write_debug(f"Calculated negative slice index {orig_slice_start_idx} from header {header}. Skipping hunk.", channel="Error")
        return list(original_lines)

    prefix = original_lines[:orig_slice_start_idx]
    suffix = original_lines[orig_slice_start_idx + old_line_count:]
    
    return prefix + new_hunk_lines_content + suffix


def apply_unified_diff(original_lines, diff_content):
    diff_lines_for_hunk_extraction = diff_content.splitlines()
    hunks = extract_hunks(diff_lines_for_hunk_extraction)
    if not hunks:
        # This handles "@@ -0,0 +0,0 @@" or no hunks for new empty files correctly if apply_hunk returns []
        # For existing files, if no hunks, it means no change.
        debug_utils.write_debug("No hunks found in diff content for apply_unified_diff. Returning original lines.", channel="Debug")
        return list(original_lines)
    
    current_lines = list(original_lines)
    for hunk_data in reversed(hunks):
        patched = apply_hunk(current_lines, hunk_data)
        if patched is None:
            return None
        current_lines = patched
    return current_lines

def apply_diff_to_file(filepath_to_read, diff_content_for_file, dry_run, effective_write_filepath):
    try:
        original_lines = []
        if os.path.exists(filepath_to_read):
            try:
                with open(filepath_to_read, 'r', encoding='utf-8') as f:
                    file_content_str = f.read()
                    original_lines = [line + '\n' for line in file_content_str.splitlines()]
                    if file_content_str and not file_content_str.endswith('\n') and original_lines:
                        original_lines[-1] = original_lines[-1].rstrip('\n')
            except Exception as e:
                debug_utils.write_debug(f"Error reading source file '{filepath_to_read}': {e}", channel="Error", exc_info=e)
                return None
        
        log_source_path = filepath_to_read if os.path.exists(filepath_to_read) else f"source for new file '{os.path.basename(effective_write_filepath)}'"
        if dry_run:
            debug_utils.write_debug(f"DRY RUN: Processing diff for {log_source_path}", channel="Information")
        else:
            debug_utils.write_debug(f"Processing diff for {log_source_path}", channel="Information")

        a_line_in_block = ""
        for l_content in diff_content_for_file.splitlines(): # Use the specific block's content
            if l_content.startswith("--- "):
                a_line_in_block = l_content
                break
        
        path_from_a_in_block = get_path_from_diff_header_line(a_line_in_block, "--- ")
        is_actually_new_file_op = (path_from_a_in_block == "dev/null")
        hunks_present_in_this_diff_block = '@@' in diff_content_for_file

        if not hunks_present_in_this_diff_block and not is_actually_new_file_op:
            debug_utils.write_debug(f"No content hunks '@@' detected for existing file operation on {log_source_path}. Assuming no change to content.", channel="Debug")
            return ''.join(original_lines)

        patched_lines = apply_unified_diff(original_lines, diff_content_for_file)
        if patched_lines is None:
            debug_utils.write_debug(
                f"Skipping patch application for {log_source_path} due to invalid hunk(s).",
                channel="Warning",
            )
            return None
        patched_content_str = ''.join(patched_lines)
        
        if not dry_run:
            try:
                write_dir = os.path.dirname(effective_write_filepath)
                if write_dir and not os.path.exists(write_dir):
                    os.makedirs(write_dir, exist_ok=True)
                with open(effective_write_filepath, 'w', encoding='utf-8') as f:
                    f.write(patched_content_str)
                debug_utils.write_debug(f"Successfully applied diff. Output written to: '{effective_write_filepath}'", channel="Information")
            except Exception as e:
                debug_utils.write_debug(f"Error writing output to file '{effective_write_filepath}': {e}", channel="Error", exc_info=e)
                return None
        else:
            action_would_be = "unchanged"
            original_content_str = ''.join(original_lines)
            if is_actually_new_file_op and not os.path.exists(filepath_to_read):
                action_would_be = "created"
            elif original_content_str != patched_content_str:
                action_would_be = "modified"
            debug_utils.write_debug(f"DRY RUN: File '{effective_write_filepath}' would be {action_would_be}.", channel="Information")

        return patched_content_str
    except Exception as e:
        debug_utils.write_debug(f"Error applying diff related to source '{filepath_to_read}': {e}", channel="Error", exc_info=e)
        return None

def parse_diff_and_apply(diff_text, target_directory, dry_run=False, output_copy=False):
    modified = {}
    # Improved regex to capture the "diff --git" line and the content until the next "diff --git" or EOF
    # This regex uses a positive lookahead (?=...) to find the boundary.
    diff_block_segments = re.split(r'(?=^diff --git )', diff_text, flags=re.MULTILINE)
    
    actual_diff_blocks = []
    for segment in diff_block_segments:
        if segment.strip().startswith("diff --git"):
            actual_diff_blocks.append(segment.strip()) # Add the block if it starts correctly
    
    if not actual_diff_blocks and diff_text.strip():
        debug_utils.write_debug("No 'diff --git' blocks found in input. Ensure diffs start with 'diff --git'.", channel="Warning")
        return {}
    if not actual_diff_blocks: # Input was empty or only whitespace
        return {}

    # First pass for validation
    for diff_block_content_for_validation in actual_diff_blocks:
        lines_for_validation = diff_block_content_for_validation.splitlines() # No strip() here, keep original lines
        
        a_file_line_str_val = next((line for line in lines_for_validation if line.startswith('--- ')), None)
        b_file_line_str_val = next((line for line in lines_for_validation if line.startswith('+++ ')), None)

        path_from_a_val = get_path_from_diff_header_line(a_file_line_str_val, "--- ")
        path_from_b_val = get_path_from_diff_header_line(b_file_line_str_val, "+++ ")
        
        path_for_debug_val = "unknown_file_in_diff_block"
        if path_from_b_val and path_from_b_val != "dev/null": path_for_debug_val = path_from_b_val
        elif path_from_a_val and path_from_a_val != "dev/null": path_for_debug_val = path_from_a_val
        elif path_from_b_val: path_for_debug_val = path_from_b_val 
        elif path_from_a_val: path_for_debug_val = path_from_a_val

        if not a_file_line_str_val or not b_file_line_str_val or path_from_a_val is None or path_from_b_val is None:
            debug_utils.write_debug(f"Unsupported diff format: Missing or unparsable '--- ' or '+++ ' for '{path_for_debug_val}' in block. Cannot apply entire patch.", channel="Warning")
            return {}

        for line_in_block_val in lines_for_validation:
            stripped_line_val = line_in_block_val.strip()
            if stripped_line_val.startswith("Binary files ") and stripped_line_val.endswith(" differ"):
                debug_utils.write_debug(f"Unsupported diff type: Binary file changes detected for '{path_for_debug_val}'. Cannot apply entire patch.", channel="Warning")
                return {}
            if stripped_line_val == "new file mode 120000" or stripped_line_val == "old mode 120000":
                debug_utils.write_debug(f"Unsupported diff type: Symbolic link operation (mode 120000) detected for '{path_for_debug_val}'. Cannot apply entire patch.", channel="Warning")
                return {}
            if stripped_line_val.startswith("rename from ") or stripped_line_val.startswith("rename to ") or \
               stripped_line_val.startswith("copy from ") or stripped_line_val.startswith("copy to "):
                debug_utils.write_debug(f"Unsupported diff type: File rename/copy operation detected for '{path_for_debug_val}'. Cannot apply entire patch.", channel="Warning")
                return {}
        
        has_mode_directive = any(line.strip().startswith("old mode ") or line.strip().startswith("new mode ") or line.strip().startswith("deleted file mode ") for line in lines_for_validation)
        hunk_found_in_block = any(line.startswith('@@') for line in lines_for_validation)

        if has_mode_directive and not hunk_found_in_block:
            is_symlink_mode = any(line.strip() == "new file mode 120000" or line.strip() == "old mode 120000" for line in lines_for_validation)
            if not is_symlink_mode:
                debug_utils.write_debug(f"Unsupported diff type: File mode change without content modification detected for '{path_for_debug_val}'. Cannot apply entire patch.", channel="Warning")
                return {}
        
        is_new_file_op_val = (path_from_a_val == "dev/null" and path_from_b_val != "dev/null")
        is_file_deletion_op_val = (path_from_b_val == "dev/null" and path_from_a_val != "dev/null")

        if not hunk_found_in_block:
            if is_new_file_op_val:
                debug_utils.write_debug(f"Detected new empty file operation for '{path_for_debug_val}'. No hunks needed for this block.", channel="Debug")
            elif is_file_deletion_op_val:
                 debug_utils.write_debug(f"Invalid diff block: No content hunks '@@' found for file deletion operation on '{path_for_debug_val}'. Cannot apply entire patch.", channel="Warning")
                 return {}
            elif not is_new_file_op_val and not is_file_deletion_op_val:
                debug_utils.write_debug(f"Invalid diff block: No content hunks '@@' found for existing file modification on '{path_for_debug_val}'. Cannot apply entire patch.", channel="Warning")
                return {}

    # Second pass for application
    for diff_block_content in actual_diff_blocks:
        try:
            lines = diff_block_content.splitlines() # No strip here, keep original lines from block
            current_a_file_line_str = next((line for line in lines if line.startswith('--- ')), None)
            current_b_file_line_str = next((line for line in lines if line.startswith('+++ ')), None)
            if not current_a_file_line_str or not current_b_file_line_str: continue

            current_path_from_a = get_path_from_diff_header_line(current_a_file_line_str, "--- ")
            current_path_from_b = get_path_from_diff_header_line(current_b_file_line_str, "+++ ")
            if current_path_from_a is None or current_path_from_b is None: continue

            file_path_in_diff = None
            is_new_file_marker = (current_path_from_a == "dev/null" and current_path_from_b != "dev/null")
            is_deleted_file_marker = (current_path_from_b == "dev/null" and current_path_from_a != "dev/null")

            if is_new_file_marker: file_path_in_diff = current_path_from_b
            elif is_deleted_file_marker: file_path_in_diff = current_path_from_a
            elif current_path_from_b != "dev/null": file_path_in_diff = current_path_from_b
            elif current_path_from_a != "dev/null": file_path_in_diff = current_path_from_a
            if not file_path_in_diff: continue

            original_target_filepath = os.path.join(target_directory, file_path_in_diff)
            effective_write_filepath = original_target_filepath
            if output_copy and not is_deleted_file_marker:
                effective_write_filepath = get_output_copy_path(original_target_filepath)

            if is_deleted_file_marker:
                if os.path.exists(original_target_filepath):
                    if not dry_run:
                        try:
                            os.remove(original_target_filepath)
                            debug_utils.write_debug(f"Successfully deleted file: '{original_target_filepath}'", channel="Information")
                            modified[file_path_in_diff] = "DELETED"
                        except Exception as e:
                            debug_utils.write_debug(f"Error deleting file '{original_target_filepath}': {e}", channel="Error", exc_info=e)
                    else:
                        debug_utils.write_debug(f"DRY RUN: File '{original_target_filepath}' would be deleted.", channel="Information")
                        modified[file_path_in_diff] = "WOULD_BE_DELETED"
                else:
                    debug_utils.write_debug(f"File deletion specified for non-existent file '{original_target_filepath}'. Skipping.", channel="Warning")
                continue

            if os.path.exists(original_target_filepath) or is_new_file_marker:
                if output_copy and not dry_run and not is_new_file_marker : # Log copy only if not a new file being copied
                     debug_utils.write_debug(f"Output copy mode: Result for '{file_path_in_diff}' will be written to '{os.path.basename(effective_write_filepath)}'", channel="Information")
                
                # Pass the full diff_block_content for this specific file to apply_diff_to_file
                patched_content = apply_diff_to_file(original_target_filepath, diff_block_content, dry_run, effective_write_filepath)
                if patched_content is not None:
                    modified[file_path_in_diff] = patched_content
            else:
                debug_utils.write_debug(f"File '{original_target_filepath}' does not exist and not a new file diff (is_new_file_marker was {is_new_file_marker}). Skipping.", channel="Warning")
        
        except Exception as e:
            current_file_path_for_exc = file_path_in_diff if 'file_path_in_diff' in locals() and file_path_in_diff else "unknown_file_during_exception"
            debug_utils.write_debug(f"Error processing diff block for '{current_file_path_for_exc}': {e}", channel="Error", exc_info=e)
            
    debug_utils.write_debug("Diff application process completed.", channel="Information")
    return modified

def main_test_wrapper(directory, input_source, diff_text_terminal=None, dry_run=False, output_copy=False):
    class MockArgsLocalTest:
        def __init__(self, directory, input_val, log_level="Debug", console_log_level="Debug",
                     enable_file_log=False, log_dir="logs", force=False,
                     dry_run_val=False, output_copy_val=False):
            self.directory = directory if directory is not None else "."
            self.input = input_val; self.log_level = log_level; self.console_log_level = console_log_level
            self.enable_file_log = enable_file_log; self.log_dir = log_dir; self.force = force
            self.dry_run = dry_run_val; self.output_copy = output_copy_val
    current_dir_for_mock = directory if directory is not None else "."
    mock_args = MockArgsLocalTest(directory=current_dir_for_mock, input_val=input_source, dry_run_val=dry_run, output_copy_val=output_copy)
    original_stdin = sys.stdin
    if input_source == 'terminal_input':
        sys.stdin = io.StringIO(diff_text_terminal if diff_text_terminal is not None else "")
    try: main_output = main_testable(mock_args)
    finally:
        if input_source == 'terminal_input': sys.stdin = original_stdin
    return main_output

def main_testable(args):
    try: target_directory = os.path.abspath(args.directory)
    except Exception as e: return {"error": f"Error resolving target directory '{getattr(args, 'directory', 'MISSING')}': {e}"}
    if not os.path.isdir(target_directory): return {"error": f"Error: Directory '{target_directory}' does not exist."}
    diff_text = ""; input_source = args.input
    if input_source == 'clipboard':
        debug_utils.write_debug("Reading diff from clipboard.", channel="Debug")
        try:
            diff_text = clipboard.get_clipboard()
            if not diff_text or not diff_text.strip():
                debug_utils.write_debug("Clipboard empty. Falling back to terminal.", channel="Warning"); input_source = 'terminal_input'
        except Exception as e:
            debug_utils.write_debug(f"Clipboard error: {e}. Falling back to terminal.", channel="Warning"); input_source = 'terminal_input'; diff_text = ""
    if input_source == 'terminal_input':
        if sys.stdin and sys.stdin.isatty(): debug_utils.write_debug("Reading from terminal. Ctrl+D/Ctrl+Z.", channel="Debug")
        else: debug_utils.write_debug("Reading from piped terminal.", channel="Debug")
        if sys.stdin: diff_text = sys.stdin.read()
        else: return {"error": "Cannot read from terminal, stdin not available."}
    elif os.path.isfile(input_source):
        debug_utils.write_debug(f"Reading from file: {input_source}", channel="Debug")
        try:
            with open(input_source, 'r', encoding='utf-8') as f: diff_text = f.read()
        except Exception as e: return {"error": f"Error reading file '{input_source}': {e}"}
    elif input_source != 'clipboard': diff_text = input_source # Direct text
    if not diff_text or not diff_text.strip(): return {"warning": "No diff input provided."}
    if hasattr(args, 'dry_run') and args.dry_run: debug_utils.write_debug("DRY RUN MODE.", channel="Information")
    modified_contents = parse_diff_and_apply(diff_text, target_directory, getattr(args, 'dry_run', False), getattr(args, 'output_copy', False))
    if not modified_contents and diff_text.strip():
        return {"warning": "Diff processed, but no valid operations applied or files skipped.", "diff_text": diff_text, "input_source": args.input}
    return {"modified_files": modified_contents, "input_source": args.input, "diff_text": diff_text}

def main():
    parser = argparse.ArgumentParser(description="Apply git diff to files. Supports text mods, new files (empty too), deletions. No binary, symlinks, renames, mode-only.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-d", "--directory", default=".", help="Target directory (default: current).")
    parser.add_argument("-i", "--input", nargs='?', const='terminal_input', default='clipboard', help="Diff source: 'clipboard' (default), 'terminal_input' (or -i), or <filepath>.")
    parser.add_argument("-o", "--output-copy", action="store_true", help="Write to new file (filename_applied_diffN.ext), not in-place. No effect on deletions.")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Dry run. Show actions, no disk changes.")
    parser.add_argument("-l", "--log-level", default="Debug", choices=["Verbose", "Debug", "Information", "Warning", "Error", "Critical"], help="File logging level (default: Debug).")
    parser.add_argument("-c", "--console-log-level", default="Information", choices=["Verbose", "Debug", "Information", "Warning", "Error", "Critical"], help="Console logging level (default: Information).")
    parser.add_argument("-e", "--enable-file-log", action="store_true", help="Enable file logging.")
    parser.add_argument("-g", "--log-dir", default=debug_utils.DEFAULT_LOG_DIR, help=f"Log directory (default: {debug_utils.DEFAULT_LOG_DIR}).")
    parser.add_argument("--help-format", action="store_true", help="Print LLM diff formatting guide.")
    args = parser.parse_args()
    if args.help_format: print(f"""LLM Diff Formatting Guide: Standard `git diff -u`. Key points:
1. Headers: `diff --git a/path b/path`, `--- a/path` (or `/dev/null`), `+++ b/path` (or `/dev/null`). Relative paths.
2. Hunk Headers: `@@ -old_start[,lines] +new_start[,lines] @@`.
3. Hunk Content: ` ` context, `-` removed, `+` added.
4. No Newline EOF: If line lacks trailing newline, next diff line must be `\\ No newline at end of file`.
5. New Empty Files: `--- /dev/null`, `+++ b/new_empty.txt`. Hunks optional (`@@ -0,0 +0,0 @@` or none).
6. Deletions: `--- a/to_delete.txt`, `+++ /dev/null`, then hunks for deleted content.
7. Unsupported (AVOID): Binary, mode-only changes, symlinks, renames/copies.
8. Encoding: UTF-8. Multiple files: Concatenate diff blocks."""); return
    debug_utils.set_log_verbosity(args.log_level); debug_utils.set_console_verbosity(args.console_log_level)
    if args.enable_file_log: debug_utils.set_log_directory(args.log_dir); debug_utils.enable_file_logging()
    results = main_testable(args)
    if "error" in results: debug_utils.write_debug(results["error"], channel="Error"); sys.exit(1)
    elif "warning" in results:
        debug_utils.write_debug(results["warning"], channel="Warning")
        if "No diff input provided." not in results["warning"] and ("modified_files" not in results or not results["modified_files"]): sys.exit(2)
    elif "modified_files" in results:
        if results["modified_files"]:
            count = len(results["modified_files"]); action = "would be changed/created/deleted (dry run)" if args.dry_run else "changed/created/deleted"
            debug_utils.write_debug(f"Success. {count} file(s) {action}.", channel="Information")
            if args.dry_run: debug_utils.write_debug("Dry run complete. No files modified.", channel="Information")
        elif results.get("diff_text","").strip() and not results.get("warning"):
            debug_utils.write_debug("Diff processed, but no files modified/targeted.", channel="Information")

if __name__ == "__main__":
    main()
# End of File: apply_git_diffs.py
