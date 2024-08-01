import os
import shutil
import argparse
from fnmatch import fnmatch


def load_gitignore(repo_path):
    """
    Load the .gitignore file and return the patterns to ignore.
    """
    gitignore_path = os.path.join(repo_path, ".gitignore")
    ignore_patterns = []

    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r") as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith("#"):
                    ignore_patterns.append(line)

    return ignore_patterns


def should_ignore(path, ignore_patterns):
    """
    Determine if a given path should be ignored based on the ignore patterns.
    """
    for pattern in ignore_patterns:
        if fnmatch(path, pattern) or fnmatch(os.path.basename(path), pattern):
            return True
    return False


def extract_files(repo_path, output_folder, ignore_patterns):
    """
    This script extracts all files from a given Git repository folder into a single folder.
    It also generates a text document showing the folder structure of all files in the repository.
    Each copied file has a comment at the top with its original path.

    Parameters:
    repo_path (str): Path to the Git repository.
    output_folder (str): Path to the output folder where all files will be extracted.
    ignore_patterns (list): List of patterns to ignore based on .gitignore and other directories.
    """

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    structure_file = os.path.join(output_folder, "folderStructure.txt")

    with open(structure_file, "w") as f:
        f.write(
            "# This document shows the folder layout for all files in the given Git repository.\n\n"
        )

        for root, dirs, files in os.walk(repo_path):
            # Skip directories like .git, .vscode, and those specified in .gitignore
            dirs[:] = [
                d
                for d in dirs
                if not should_ignore(os.path.join(root, d), ignore_patterns)
            ]
            if should_ignore(root, ignore_patterns):
                continue

            level = root.replace(repo_path, "").count(os.sep)
            indent = " " * 4 * level
            f.write(f"{indent}{os.path.basename(root)}/\n")
            subindent = " " * 4 * (level + 1)
            for file in files:
                if should_ignore(file, ignore_patterns):
                    continue
                f.write(f"{subindent}{file}\n")
                src_file = os.path.join(root, file)
                dst_file = os.path.join(output_folder, file)

                # Ensure unique filenames in the output folder
                if os.path.exists(dst_file):
                    base, ext = os.path.splitext(file)
                    counter = 1
                    while os.path.exists(dst_file):
                        dst_file = os.path.join(output_folder, f"{base}_{counter}{ext}")
                        counter += 1

                shutil.copy2(src_file, dst_file)

                # Write the original path as a comment at the top of the copied file
                try:
                    with open(dst_file, "r+b") as dst_f:
                        content = dst_f.read()
                        dst_f.seek(0, 0)
                        dst_f.write(
                            f"# This file's full path is {os.path.relpath(src_file, repo_path)}\n\n".encode()
                            + content
                        )
                except Exception as e:
                    print(f"Failed to write to {dst_file}: {e}")

    print(
        f"Files extracted to {output_folder} and folder structure written to {structure_file}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract files from a Git repository into a single folder."
    )
    parser.add_argument("--path", required=True, help="Path to the Git repository")
    parser.add_argument("--output", help="Path to the output folder")

    args = parser.parse_args()

    if not args.output:
        args.output = os.path.join(os.getenv("LOCALAPPDATA"), "FolderFlattenOutput")

    ignore_patterns = load_gitignore(args.path) + [".git", ".vscode"]

    extract_files(args.path, args.output, ignore_patterns)
