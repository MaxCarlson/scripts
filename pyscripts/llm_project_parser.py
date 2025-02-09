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

def find_section_by_keyword(sections, keyword):
    """
    Returns the first section that contains the given keyword (case-insensitive).
    """
    for section in sections:
        if keyword.lower() in section.lower():
            return section
    return None

def extract_file_sections(sections):
    """
    From the list of sections, return those that look like file definitions.
    We assume that a file section contains a header line starting with a number and a dot.
    """
    file_sections = []
    file_section_pattern = re.compile(r'^\s*\d+\.\s+.*$', re.MULTILINE)
    for section in sections:
        if file_section_pattern.search(section):
            file_sections.append(section)
    return file_sections

def parse_file_section(section):
    """
    Parses a section that defines one file.
    Expects a header line like "1. web_scraper/__init__.py" and then the file contents.
    
    Returns:
        file_path (str): the relative file path.
        file_content (str): the contents to write to the file.
    """
    lines = section.splitlines()
    file_path = None
    header_line_index = None
    header_pattern = re.compile(r'^\s*\d+\.\s+(.*)$')
    for i, line in enumerate(lines):
        m = header_pattern.match(line)
        if m:
            file_path = m.group(1).strip()
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
        stripped = line.strip()
        # Start when we see a line that ends with "/" and looks like a folder name
        if not start_collecting and stripped.endswith("/"):
            start_collecting = True
        if start_collecting:
            if stripped:
                tree_lines.append(line.rstrip())
    directories = set()
    files = set()
    root = ""
    if tree_lines:
        # Assume first line is the root directory (e.g., "web_scraper/")
        root = tree_lines[0].strip().rstrip("/")
        directories.add(root)
        # Process subsequent lines:
        for line in tree_lines[1:]:
            # Remove common tree-drawing characters (like ├──, └──) and whitespace.
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
    
    # Attempt to find the folder structure section.
    folder_section = find_section_by_keyword(sections, "Folder Structure")
    if folder_section:
        folder_structure = parse_folder_structure(folder_section)
        if args.verbose:
            print("Parsed folder structure:")
            print("  Root:", folder_structure["root"])
            print("  Directories:", folder_structure["directories"])
            print("  Files (from tree):", folder_structure["files"])
        # Create directories from the tree.
        create_directories(folder_structure["directories"], args.output, dry_run=args.dry_run, verbose=args.verbose)
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
