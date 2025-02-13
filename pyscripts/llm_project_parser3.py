#!/usr/bin/env python3
"""
llm_project_parser.py

This script reads an input file that contains an LLM output (with a drawn-out folder
structure and file definitions with code blocks) and then creates the folder hierarchy 
and files (with content) in a target output directory.

Usage example:
    python llm_project_parser.py --input project.txt --output output_dir --verbose

Arguments:
    --input / -i      : Path to the input file containing the LLM output.
    --output / -o     : Destination directory where the folder structure will be created.
    --dry-run / -d    : If set, perform a dry run (print what would be done without writing files).
    --verbose / -v    : Enable verbose output.
"""

import os
import re
import argparse
import sys

### Helper functions for tree printing (used at the end) ###
def build_tree(paths):
    """
    Build a nested dictionary representing the tree structure from a set of relative paths.
    """
    tree = {}
    for path in paths:
        parts = path.split(os.sep)
        current = tree
        for part in parts:
            current = current.setdefault(part, {})
    return tree

def print_tree_dict(tree, prefix=""):
    """
    Recursively prints the nested dictionary as a tree using Unicode characters.
    """
    keys = sorted(tree.keys())
    for i, key in enumerate(keys):
        connector = "└── " if i == len(keys) - 1 else "├── "
        print(prefix + connector + key)
        if tree[key]:
            extension = "    " if i == len(keys) - 1 else "│   "
            print_tree_dict(tree[key], prefix + extension)

def get_actual_paths(base_dir):
    """
    Walk the directory tree starting at base_dir and return a set of relative paths
    (both directories and files).
    """
    paths = set()
    for root, dirs, files in os.walk(base_dir):
        rel = os.path.relpath(root, base_dir)
        if rel == ".":
            rel = ""
        else:
            paths.add(rel)
        for d in dirs:
            p = os.path.join(rel, d) if rel else d
            paths.add(p)
        for f in files:
            p = os.path.join(rel, f) if rel else f
            paths.add(p)
    return paths

### End of tree-printing helper functions ###

def parse_args():
    parser = argparse.ArgumentParser(
        description="Parse LLM output file and create folder structure and files."
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="Path to the input file containing the LLM output."
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=".",
        help="Output directory where the folder structure will be created."
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Perform a dry run without actually creating files."
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output."
    )
    return parser.parse_args()

def split_into_sections(text):
    """
    Splits the text into sections using lines that contain three or more hyphens as delimiters.
    """
    pattern = re.compile(r'^\s*-{3,}\s*$', re.MULTILINE)
    sections = pattern.split(text)
    return [section.strip() for section in sections if section.strip()]

def parse_folder_structure(section):
    """
    Extracts the folder tree from a drawn-out folder structure.
    It extracts both directories and file names (to be created as empty files if not provided elsewhere).
    
    Returns a dict with:
      - 'root': the root folder name.
      - 'directories': a list of directory paths (relative to the output directory).
      - 'files': a list of file paths found in the tree.
    """
    lines = section.splitlines()
    tree_lines = []
    start_collecting = False
    for line in lines:
        stripped = line.rstrip()
        # Start when we see the first line ending with "/" (assumed to be the root).
        if not start_collecting and stripped.endswith("/"):
            start_collecting = True
        if start_collecting and stripped:
            tree_lines.append(stripped)
    
    directories = set()
    files = set()
    root = ""
    if tree_lines:
        # The first line is assumed to be the root directory.
        root_candidate = tree_lines[0].split(" # ")[0].strip()
        if not re.match(r'^[\w./\\-]+$', root_candidate):
            return {"root": "", "directories": [], "files": []}
        root = root_candidate.rstrip("/")
        directories.add(root)
        
        # Process subsequent tree lines.
        for line in tree_lines[1:]:
            # Remove tree-drawing characters and inline comments.
            cleaned = re.sub(r'^[\s│├└─]+', '', line).strip()
            cleaned = cleaned.split(" # ")[0].strip()
            if not cleaned:
                continue
            if not re.match(r'^[\w./\\-]+$', cleaned):
                continue
            if cleaned.endswith("/"):
                directories.add(os.path.join(root, cleaned.rstrip("/")))
            else:
                # If the basename contains a dot, treat it as a file.
                if '.' in os.path.basename(cleaned):
                    file_rel_path = os.path.join(root, cleaned) if not cleaned.startswith(root) else cleaned
                    files.add(file_rel_path)
                    # Also add its parent directory.
                    parent = os.path.dirname(file_rel_path)
                    if parent:
                        directories.add(parent)
                else:
                    directories.add(os.path.join(root, cleaned))
        return {"root": root, "directories": list(directories), "files": list(files)}
    else:
        return {"root": "", "directories": [], "files": []}

def is_file_section(section):
    """
    Heuristically determine if a section defines a file.
    The first nonempty line should be a file path in the expected format.
    """
    lines = [line for line in section.splitlines() if line.strip()]
    if not lines:
        return False
    first_line = lines[0].strip()
    # Remove any optional numbering.
    m = re.match(r'^(\d+\.\s+)?(.*)$', first_line)
    header = m.group(2) if m else first_line
    # Remove inline comment markers and trailing parentheticals.
    header = header.split(" # ")[0].strip()
    header = re.split(r'\s*.*$', header)[0].strip()
    return bool(re.match(r'^[\w./\\-]+$', header))

def extract_file_sections(sections):
    """
    From the list of sections, return those that are valid file definitions.
    """
    file_sections = []
    for section in sections:
        if is_file_section(section):
            file_sections.append(section)
    return file_sections

def parse_file_section(section):
    """
    Parses a section that defines one file.
    The first nonempty line is the file path (with inline comments stripped)
    and the remaining lines are the file content.
    
    Returns:
      - file_path (str): the relative file path.
      - file_content (str): the contents to write to the file.
    """
    lines = section.splitlines()
    file_path = None
    header_line_index = None
    for i, line in enumerate(lines):
        if line.strip():
            header_line = line.strip()
            m = re.match(r'^(\d+\.\s+)?(.*)$', header_line)
            header = m.group(2).strip() if m else header_line
            header = header.split(" # ")[0].strip()
            header = re.split(r'\s*.*$', header)[0].strip()
            file_path = header
            header_line_index = i
            break
    if file_path is None:
        raise ValueError("No file header found in section.")
    file_content = "\n".join(lines[header_line_index+1:]).strip()
    return file_path, file_content

def check_rename_init(file_path):
    """
    If the file is named 'init.py', ask the user whether to rename it to '__init__.py'.
    Returns the (possibly modified) file path.
    """
    if os.path.basename(file_path) == "init.py":
        answer = input(f"File '{file_path}' is named 'init.py'. Should it be renamed to '__init__.py'? (y/N): ")
        if answer.strip().lower().startswith('y'):
            return os.path.join(os.path.dirname(file_path), "__init__.py") if os.path.dirname(file_path) else "__init__.py"
    return file_path

def create_directories(directories, base_dir, dry_run=False, verbose=False):
    """
    Creates each directory (relative to base_dir) if it does not exist.
    """
    for directory in directories:
        full_path = os.path.join(base_dir, directory)
        if verbose:
            print(f"Creating directory: {full_path}")
        if not dry_run:
            os.makedirs(full_path, exist_ok=True)

def write_file(file_path, content, base_dir, dry_run=False, verbose=False):
    """
    Writes the given content to file_path (relative to base_dir),
    creating any missing parent directories.
    """
    file_path = check_rename_init(file_path)
    full_file_path = os.path.join(base_dir, file_path)
    parent_dir = os.path.dirname(full_file_path)
    if not os.path.exists(parent_dir):
        if verbose:
            print(f"Creating parent directory: {parent_dir}")
        if not dry_run:
            os.makedirs(parent_dir, exist_ok=True)
    if verbose:
        print(f"Writing file: {full_file_path}")
    if not dry_run:
        with open(full_file_path, "w", encoding="utf-8") as f:
            f.write(content)

def main():
    args = parse_args()
    
    # Read the input file.
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as exc:
        print(f"Error reading input file: {exc}")
        sys.exit(1)
    
    # Split text into sections using '---' as delimiter.
    sections = split_into_sections(text)
    
    # Detect folder structure by its drawn-out tree (without using keywords).
    folder_section = None
    for section in sections:
        if any(line.rstrip().endswith("/") for line in section.splitlines()):
            folder_section = section
            break

    folder_structure = {"root": "", "directories": [], "files": []}
    if folder_section:
        folder_structure = parse_folder_structure(folder_section)
        if args.verbose:
            print("Parsed folder structure:")
            print("  Root:", folder_structure["root"])
            print("  Directories:", folder_structure["directories"])
            print("  Files (from tree):", folder_structure["files"])
        create_directories(folder_structure["directories"], args.output, dry_run=args.dry_run, verbose=args.verbose)
        sections.remove(folder_section)
    else:
        if args.verbose:
            print("No folder structure section found.")
    
    # Process file sections.
    file_sections = extract_file_sections(sections)
    if args.verbose:
        print(f"Found {len(file_sections)} file section(s).")
    
    created_files = set()
    for section in file_sections:
        try:
            file_path, file_content = parse_file_section(section)
            file_path = check_rename_init(file_path)
            write_file(file_path, file_content, args.output, dry_run=args.dry_run, verbose=args.verbose)
            created_files.add(file_path)
        except Exception as exc:
            print(f"Error processing a file section: {exc}")
    
    # Create empty files for those listed in the folder structure that weren't provided.
    for f in folder_structure.get("files", []):
        f_checked = check_rename_init(f)
        if f_checked not in created_files:
            if args.verbose:
                print(f"Creating empty file for: {f_checked}")
            write_file(f_checked, "", args.output, dry_run=args.dry_run, verbose=args.verbose)
    
    if args.verbose:
        print("Processing complete.\n")
        print("Final directory structure:")
        # For non-dry-run, scan the actual output directory; for dry-run, simulate from planned paths.
        if args.dry_run:
            planned_paths = set(folder_structure.get("directories", []))
            planned_paths.update(created_files)
            planned_paths.update(folder_structure.get("files", []))
            tree = build_tree(planned_paths)
        else:
            actual_paths = get_actual_paths(args.output)
            tree = build_tree(actual_paths)
        print_tree_dict(tree)

if __name__ == "__main__":
    main()
