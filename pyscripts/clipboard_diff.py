#!/usr/bin/env python3
import sys
import difflib
from cross_platform.clipboard_utils import get_clipboard # Assuming this is a custom module

def diff_clipboard_with_file(
    file_path: str,
    context_lines: int = 3,
    similarity_threshold: float = 0.75,
    loc_diff_warning_threshold: int = 50
) -> None:
    """
    Compare current clipboard contents with the contents of a file and print a diff.

    :param file_path: Path to the file to compare against clipboard contents.
    :param context_lines: Number of context lines to show around changes.
    :param similarity_threshold: Ratio below which contents are considered very dissimilar.
    :param loc_diff_warning_threshold: Absolute LOC difference above which a warning is shown.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            file_lines = f.read().splitlines()
    except Exception as e:
        print(f"\033[91m[ERROR] Could not read file '{file_path}': {e}\033[0m", file=sys.stderr)
        sys.exit(1)

    clipboard_text = get_clipboard()
    if not clipboard_text or clipboard_text.isspace():
        print("\033[91m[CRITICAL WARNING] Clipboard is empty or contains only whitespace!\033[0m", file=sys.stderr)
        sys.exit(1) # Or handle as preferred, e.g., return

    clipboard_lines = clipboard_text.splitlines()

    diff = difflib.unified_diff(
        file_lines,
        clipboard_lines,
        fromfile=f"file: {file_path}",
        tofile="clipboard",
        lineterm="",
        n=context_lines
    )

    has_diff = False
    diff_output_lines = []
    for line in diff:
        has_diff = True
        if line.startswith('---') or line.startswith('+++'):
            diff_output_lines.append(line)
        elif line.startswith('@@'):
            # Hunk header in cyan
            diff_output_lines.append(f"\033[36m{line}\033[0m")
        elif line.startswith('-'):
            # Removals in red
            diff_output_lines.append(f"\033[31m{line}\033[0m")
        elif line.startswith('+'):
            # Additions in green
            diff_output_lines.append(f"\033[32m{line}\033[0m")
        else:
            diff_output_lines.append(line)

    if diff_output_lines: # Check if there's any diff content to print
        for line_out in diff_output_lines:
            print(line_out)
    elif not has_diff: # This case might be redundant if diff_output_lines covers it
        print("No differences found between file and clipboard.")


    print("\n--- Stats ---")
    file_loc = len(file_lines)
    clipboard_loc = len(clipboard_lines)
    loc_difference = abs(file_loc - clipboard_loc)

    print(f"File LOC: {file_loc}")
    print(f"Clipboard LOC: {clipboard_loc}")
    print(f"LOC Difference: {loc_difference}")

    if loc_difference > loc_diff_warning_threshold:
        print(f"\033[33m[WARNING] Large LOC difference detected ({loc_difference} lines). "
              "The sources may be significantly different in length.\033[0m")

    # Similarity check
    # Use join with newline to ensure original multiline structure is compared
    seq = difflib.SequenceMatcher(None, "\n".join(file_lines), "\n".join(clipboard_lines))
    ratio = seq.ratio()
    if ratio < similarity_threshold:
        print(f"\033[33mNote: The contents are very dissimilar (similarity ratio: {ratio:.2f}). "
              "They might not be the same source.\033[0m")
    else:
        print(f"Similarity ratio: {ratio:.2f}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Diff clipboard contents with a file, providing stats and warnings.",
        formatter_class=argparse.RawTextHelpFormatter # For better help text formatting
    )
    parser.add_argument(
        "file",
        help="File path to compare against clipboard contents"
    )
    parser.add_argument(
        "-c", "--context-lines",  # Changed full name for clarity
        type=int,
        default=3,
        help="Number of context lines to display (default: 3)"
    )
    parser.add_argument(
        "-t", "--similarity-threshold", # Changed full name for clarity
        type=float,
        default=0.75,
        help="Similarity threshold for dissimilarity note (range 0.0-1.0, default: 0.75)"
    )
    parser.add_argument(
        "-L", "--loc-diff-warn", # New argument for LOC difference warning
        type=int,
        default=50,
        help="Absolute LOC difference above which a warning is shown (default: 50)"
    )
    args = parser.parse_args()

    # A simple check for the clipboard utility, you might have this elsewhere
    try:
        get_clipboard()
    except NameError:
        print("\033[91m[ERROR] 'get_clipboard' function not found. "
              "Ensure 'cross_platform.clipboard_utils' is installed and accessible.\033[0m", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\033[91m[ERROR] Clipboard access failed: {e}. "
              "Ensure clipboard utilities (e.g., xclip, pbcopy) are installed.\033[0m", file=sys.stderr)
        sys.exit(1)


    diff_clipboard_with_file(
        args.file,
        args.context_lines, # Updated arg name
        args.similarity_threshold, # Updated arg name
        args.loc_diff_warn # New arg
    )
