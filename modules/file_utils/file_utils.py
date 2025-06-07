import os
import glob
import re
import sys
from cross_platform.debug_utils import write_debug


def merge_files(base_folder, files=None, glob_pattern="*.txt", output_file=None, line_pattern=None,
                line_range=None, start_pattern=None, end_pattern=None, include_headers=False, reverse=False,
                encoding="utf-8", transform=None, debug=False):
    """
    Merge the contents of files in a directory with advanced options for filtering and transformation.
    """
    # Validate the base folder
    if not os.path.exists(base_folder):
        write_debug(f"Base folder not found: {base_folder}", channel="Error", condition=True)
        return

    # Collect files
    write_debug(f"Gathering files in {base_folder} with glob pattern '{glob_pattern}'.", channel="Debug", condition=debug)
    file_paths = files if files else glob.glob(os.path.join(base_folder, glob_pattern))
    if reverse:
        file_paths.reverse()

    if not file_paths:
        write_debug(f"No files found matching pattern '{glob_pattern}' in {base_folder}.", channel="Information", condition=True)
        return

    # Parse line range
    start_line, end_line = parse_line_range(line_range)

    # Buffer debug messages and merged content separately
    debug_messages = []
    merged_content = []

    # Process each file
    for file_path in file_paths:
        try:
            if not os.path.exists(file_path):
                debug_messages.append(f"File not found: {file_path}")
                continue

            write_debug(f"Processing file: {file_path}", channel="Debug", condition=debug)

            with open(file_path, 'r', encoding=encoding) as infile:
                lines = infile.readlines()

                # Apply start pattern
                if start_pattern:
                    start_index = next((i for i, line in enumerate(lines) if re.search(start_pattern, line)), None)
                    if start_index is None:
                        write_debug(f"Skipping file '{file_path}' as start pattern '{start_pattern}' was not found.",
                                    channel="Information", condition=True)
                        continue
                    lines = lines[start_index:]

                # Apply end pattern
                if end_pattern:
                    end_index = next((i for i, line in enumerate(lines) if re.search(end_pattern, line)), None)
                    if end_index is not None:
                        lines = lines[:end_index + 1]

                # Apply line range
                if line_range:
                    if start_line is not None and start_line >= len(lines):
                        write_debug(f"Skipping file '{file_path}' as start line {start_line} is beyond file length.",
                                    channel="Information", condition=True)
                        continue
                    lines = lines[start_line:end_line]

                # Apply transformations and collect content
                for line in lines:
                    if line_pattern and not re.match(line_pattern, line.strip()):
                        continue
                    if transform:
                        line = apply_transform(line, transform)
                    merged_content.append(line)

                # Include headers if specified
                if include_headers:
                    merged_content.insert(0, f"===== {os.path.basename(file_path)} =====\n")

        except Exception as e:
            write_debug(f"Error processing file '{file_path}': {str(e)}", channel="Error", condition=True)
            continue

    # Write debug messages
    for msg in debug_messages:
        write_debug(msg, channel="Debug", condition=debug)

    # Write or print merged content
    if output_file:
        try:
            with open(output_file, 'w', encoding=encoding) as outfile:
                outfile.writelines(merged_content)
            write_debug(f"Merged content written to {output_file}", channel="Information", condition=True)
        except Exception as e:
            write_debug(f"Failed to write to {output_file}: {str(e)}", channel="Error", condition=True)
    else:
        sys.stdout.writelines(merged_content)


def parse_line_range(line_range):
    """Parse Python-like slice syntax for line ranges."""
    if not line_range:
        return None, None
    match = re.match(r"(-?\d*):(-?\d*)", line_range)
    if not match:
        write_debug(f"Invalid line range syntax: {line_range}", channel="Error", condition=True)
        return None, None
    start, end = match.groups()
    return int(start) if start else None, int(end) if end else None


def apply_transform(line, transform):
    """Apply transformations to a line using Vim-like syntax."""
    match = re.match(r":s/(.*?)/(.*?)/", transform)
    if match:
        pattern, replacement = match.groups()
        return re.sub(pattern, replacement, line)
    return line


# Main script logic for CLI
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Merge contents of files in a directory with advanced options.")
    parser.add_argument("base_folder", help="Base folder containing the files to merge.")
    parser.add_argument("--files", "-f", nargs="*", help="Specific files to merge (optional).")
    parser.add_argument("--glob_pattern", "-g", default="*.txt", help="Glob pattern to match files.")
    parser.add_argument("--output_file", "-o", help="Output file (defaults to stdout).")
    parser.add_argument("--line_pattern", "-p", help="Filter lines based on this pattern.")
    parser.add_argument("--line_range", "-l", help="Specify line range in Python slice syntax, e.g., [2:-1].")
    parser.add_argument("--start_pattern", "-sp", help="Start processing lines from the first match of this pattern.")
    parser.add_argument("--end_pattern", "-ep", help="Stop processing lines at the first match of this pattern.")
    parser.add_argument("--include_headers", "-ih", action="store_true", help="Include file headers in the merged content.")
    parser.add_argument("--reverse", "-r", action="store_true", help="Reverse the order of files before merging.")
    parser.add_argument("--encoding", "-e", default="utf-8", help="Character encoding for reading files.")
    parser.add_argument("--transform", "-t", help="Apply Vim-like transformations, e.g., ':s/error/warning/'.")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()

    merge_files(
        base_folder=args.base_folder,
        files=args.files,
        glob_pattern=args.glob_pattern,
        output_file=args.output_file,
        line_pattern=args.line_pattern,
        line_range=args.line_range,
        start_pattern=args.start_pattern,
        end_pattern=args.end_pattern,
        include_headers=args.include_headers,
        reverse=args.reverse,
        encoding=args.encoding,
        transform=args.transform,
        debug=args.debug
    )
