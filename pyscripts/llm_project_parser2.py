#!/usr/bin/env python3
"""
llm_project_parser.py

This script reads an input file that contains an LLM output (with a folder structure
and file definitions) and then creates the folder hierarchy and files (with content)
in a target output directory.

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
    Splits the text into sections by lines that contain only three or more hyphens.
    """
    pattern = re.compile(r'^\s*-{3,}\s*$', re.MULTILINE)
    sections = pattern.split(text)
    sections = [section.strip() for section in sections if section.strip()]
    return sections

def is_folder_structure_section(section):
    """
    Heuristically determine if a section looks like a folder structure.
    It checks for at least one line that ends with '/' and at least one tree-drawing character.
    """
    lines = section.splitlines()
    has_root = any(line.strip().endswith("/") for line in lines)
    has_tree_chars = any(any(ch in line for ch in "├└│") for line in lines)
    return has_root and (has_tree_chars or len(lines) > 1)

def detect_folder_structure_section(sections):
    """
    Returns the first section that looks like a folder structure.
    """
    for section in sections:
        if is_folder_structure_section(section):
            return section
    return None

def is_file_section(section):
    """
    Heuristically decide if a section defines a file.
    We assume that the file section’s first nonempty line is a file path.
    """
    lines = [line for line in section.splitlines() if line.strip()]
    if not lines:
        return False
    first_line = lines[0].strip()
    # If the first line is a file path, it will usually contain a slash or a dot.
    if "/" in first_line or "\\" in first_line or '.' in first_line:
        return True
    return False

def extract_file_sections(sections):
    """
    Returns sections that look like file definitions.
    """
    file_sections = []
    for section in sections:
        if is_file_section(section):
            file_sections.append(section)
    return file_sections

def parse_file_section(section):
    """
    Parses a section that defines one file.
    Expects the first nonempty line to be the file path (optionally prefixed with numbering)
    and the rest of the section to be the file contents.
    
    Returns:
        file_path (str): the relative file path.
        file_content (str): the contents to write to the file.
    """
    lines = section.splitlines()
    file_path = None
    header_line_index = None
    for i, line in enumerate(lines):
        if line.strip():
            header_line = line.strip()
            # Remove any leading numbering like "1. " if present.
            m = re.match(r'^(\d+\.\s+)?(.*)$', header_line)
            file_path = m.group(2).strip() if m else header_line
            header_line_index = i
            break
    if file_path is None:
        raise ValueError("No file header found in section.")
    # The file content is all lines after the header line.
    file_content = "\n".join(lines[header_line_index+1:]).strip()
    return file_path, file_content

def parse_folder_structure(section):
    """
    Attempts to extract the folder structure (a tree) from a section.
    We assume that the tree starts with a line ending with "/" (the root directory)
    and then subsequent lines representing files or subdirectories.
    
    Returns a dict with keys:
        'root'        : the root folder name.
        'directories' : a list of directory paths.
        'files'       : a list of file paths (as given in the tree).
    """
    lines = section.splitlines()
    tree_lines = []
    start_collecting = False
    for line in lines:
        stripped = line.rstrip()
        # Start when we see a line that ends with "/" (likely the root)
        if not start_collecting and stripped.endswith("/"):
            start_collecting = True
        if start_collecting:
            if stripped:
                tree_lines.append(stripped)
    directories = set()
    files = set()
    root = ""
    if tree_lines:
        # Assume first line is the root directory (e.g., "folder_util/")
        root = tree_lines[0].strip().rstrip("/")
        directories.add(root)
        # Process subsequent lines:
        for line in tree_lines[1:]:
            # Remove common tree-drawing characters and whitespace.
            line_clean = re.sub(r'^[\s│├└─]+', '', line).strip()
            if not line_clean:
                continue
            if line_clean.endswith("/"):
                directories.add(os.path.join(root, line_clean.rstrip("/")))
            else:
                files.add(os.path.join(root, line_clean))
    return {"root": root, "directories": list(directories), "files": list(files)}

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
    
    # Read the input file
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as exc:
        print(f"Error reading input file: {exc}")
        sys.exit(1)
    
    # Split text into sections using '---' as a delimiter.
    sections = split_into_sections(text)
    
    # Detect folder structure section (if any)
    folder_section = detect_folder_structure_section(sections)
    if folder_section:
        folder_structure = parse_folder_structure(folder_section)
        if args.verbose:
            print("Parsed folder structure:")
            print("  Root:", folder_structure["root"])
            print("  Directories:", folder_structure["directories"])
            print("  Files (from tree):", folder_structure["files"])
        create_directories(folder_structure["directories"], args.output, dry_run=args.dry_run, verbose=args.verbose)
        # Remove the folder structure section from further processing
        sections.remove(folder_section)
    else:
        if args.verbose:
            print("No folder structure section found.")
    
    # Extract file sections and process each.
    file_sections = extract_file_sections(sections)
    if args.verbose:
        print(f"Found {len(file_sections)} file section(s).")
    
    for section in file_sections:
        try:
            file_path, file_content = parse_file_section(section)
            write_file(file_path, file_content, args.output, dry_run=args.dry_run, verbose=args.verbose)
        except Exception as exc:
            print(f"Error processing a file section: {exc}")
    
    if args.verbose:
        print("Processing complete.")

if __name__ == "__main__":
    main()
