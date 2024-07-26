"""
This script copies files based on name patterns and lists.

Usage:
    python copy-for-llms.py -i <input_folder> -o <output_folder> [-f <files>] [-p <patterns>] [-e]

Arguments:
    -i, --input-folder: Input folder to search for files.
    -o, --output-folder: Output folder to copy files to.
    -f, --files: Comma-separated list of file names to copy.
    -p, --pattern: Comma-separated list of patterns to match in file names.
    -e, --check-extensions: Check for matching extensions when copying from -f.
"""

import argparse
import os
import shutil
import re


def main():
    parser = argparse.ArgumentParser(
        description="Copy files based on name patterns and lists."
    )
    parser.add_argument(
        "-i", "--input-folder", required=True, help="Input folder to search for files."
    )
    parser.add_argument(
        "-o", "--output-folder", required=True, help="Output folder to copy files to."
    )
    parser.add_argument(
        "-f", "--files", help="Comma-separated list of file names to copy."
    )
    parser.add_argument(
        "-p",
        "--pattern",
        help="Comma-separated list of patterns to match in file names.",
    )
    parser.add_argument(
        "-e",
        "--check-extensions",
        action="store_true",
        default=False,
        help="Check for matching extensions when copying from -f.",
    )

    args = parser.parse_args()

    input_folder = args.input_folder
    output_folder = args.output_folder
    files_to_copy = (
        [file.strip() for file in args.files.split(",")] if args.files else []
    )
    patterns_to_match = (
        [pattern.strip() for pattern in args.pattern.split(",")] if args.pattern else []
    )
    check_extensions = args.check_extensions

    os.makedirs(output_folder, exist_ok=True)

    files_copied = 0

    def generate_prefixed_filename(relative_path, filename):
        """Generate a new filename with the relative path as a prefix."""
        relative_path = relative_path.replace(
            os.sep, "_"
        )  # Replace path separators with underscores
        return f"{relative_path}_{filename}"

    def copy_file(source_path, relative_path, filename):
        """Copies a single file to the destination, with the relative path as a prefix to the filename."""
        nonlocal files_copied
        prefixed_filename = generate_prefixed_filename(relative_path, filename)
        destination_path = os.path.join(output_folder, prefixed_filename)
        try:
            shutil.copy2(source_path, destination_path)
            print(f"Copied: {source_path} to {destination_path}")
            files_copied += 1
        except Exception as e:
            print(f"Failed to copy {source_path} to {destination_path}: {e}")

    if files_to_copy:
        for file_name in files_to_copy:
            for root, _, files in os.walk(input_folder):
                for file in files:
                    if check_extensions:
                        if file == file_name:
                            relative_path = os.path.relpath(root, input_folder)
                            copy_file(os.path.join(root, file), relative_path, file)
                    else:
                        if os.path.splitext(file)[0] == file_name:
                            relative_path = os.path.relpath(root, input_folder)
                            copy_file(os.path.join(root, file), relative_path, file)

    if patterns_to_match:
        for pattern in patterns_to_match:
            regex = re.compile(pattern)
            for root, _, files in os.walk(input_folder):
                for file in files:
                    if regex.search(file):
                        relative_path = os.path.relpath(root, input_folder)
                        copy_file(os.path.join(root, file), relative_path, file)

    print(f"Copied {files_copied} files to {output_folder}")


if __name__ == "__main__":
    main()
