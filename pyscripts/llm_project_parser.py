#!/usr/bin/env python3
"""
llm_project_parser.py

This script reads an input file containing an LLM output (with file definitions and code blocks)
and then creates a folder structure and individual files in a target output directory.

It identifies code blocks and looks for a filename on a line preceding it.
This allows it to handle multiple formats robustly.

Usage example:
    python llm_project_parser.py --input project.txt --output output_dir --confirm --verbose --dry-run

Arguments:
    --input / -i      : Path to the input file containing the LLM output.
    --output / -o     : Destination directory where files will be created.
    --dry-run / -d    : Perform a dry run (print actions without creating files).
    --verbose / -v    : Enable verbose output.
    --confirm / -c    : Enable interactive confirmation for ambiguous file blocks.
"""

import os
import re
import argparse
import sys
import logging

def parse_args():
    parser = argparse.ArgumentParser(
        description="Parse LLM output file and create folder structure and files."
    )
    parser.add_argument("--input", "-i", type=str, required=True,
                        help="Path to the input file containing the LLM output.")
    parser.add_argument("--output", "-o", type=str, default=".",
                        help="Output directory where the files will be created.")
    parser.add_argument("--dry-run", "-d", action="store_true",
                        help="Perform a dry run without actually creating files.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose output.")
    parser.add_argument("--confirm", "-c", action="store_true",
                        help="Enable interactive confirmation for ambiguous file blocks.")
    return parser.parse_args()

def clean_filename(raw_name):
    """
    Removes markdown formatting (e.g. **, __, backticks) and common prefixes
    from a potential file name line.
    """
    # First, remove list/header prefixes
    cleaned = re.sub(r'^(?:#{1,6}\s*)?(?:\d+\.\s*)?(?:-\s*)?''', '', raw_name).strip()
    # Then, remove markdown formatting like **, ` from the rest of the string
    cleaned = re.sub(r'[\*`]+', '', cleaned).strip()
    return cleaned

def preview_file_content(filename, content):
    """
    Prints a preview of the file content: first 5 lines and last 5 lines (or at least 3 if fewer).
    """
    lines = content.splitlines()
    total = len(lines)
    start_count = min(5, total) if total >= 3 else total
    end_count = min(5, total) if total >= 3 else total
    start_lines = lines[:start_count]
    end_lines = lines[-end_count:]
    preview = "\n".join(start_lines) + "\n...\n" + "\n".join(end_lines)
    print(f"\nFile: {filename}\nPreview:\n{preview}\n")

def confirm_file_creation(filename, content):
    """
    Shows a preview of the file content and asks the user to confirm file creation.
    Returns True if the user confirms, False otherwise.
    """
    preview_file_content(filename, content)
    answer = input(f"Create file '{filename}'? (y/N): ").strip().lower()
    return answer == 'y'

def extract_files_from_lines(lines, interactive=False):
    """
    Iterates through the input lines and extracts (filename, code_block) pairs.
    It identifies code blocks and looks for a filename on one of the lines
    immediately preceding it.
    """
    files = []
    lines_buffer = list(lines)
    total_lines = len(lines_buffer)
    i = 0

    while i < total_lines:
        line = lines_buffer[i]

        if line.strip().startswith("```"):
            filename_candidate = ""
            search_idx = i - 1
            while search_idx >= 0:
                prev_line = lines_buffer[search_idx].strip()
                if prev_line:
                    filename_candidate = prev_line
                    break
                search_idx -= 1

            code_lines = []
            i += 1
            while i < total_lines and not lines_buffer[i].strip().startswith("```"):
                code_lines.append(lines_buffer[i].rstrip('\n'))
                i += 1
            
            code_content = "\n".join(code_lines)

            if filename_candidate:
                cleaned_name = clean_filename(filename_candidate)
                
                # Heuristic: a filename should not be empty and must contain a dot (for an extension).
                if cleaned_name and '.' in cleaned_name:
                    logging.info("Found potential file: '%s'", cleaned_name)
                    
                    if len(code_content.splitlines()) < 6 and interactive:
                        if not confirm_file_creation(cleaned_name, code_content):
                            logging.info("User chose not to create file '%s'.", cleaned_name)
                            i += 1
                            continue
                    
                    files.append((cleaned_name, code_content))
                else:
                    logging.warning(
                        "Line '%s' before code block did not look like a valid filename. Skipping.",
                        filename_candidate
                    )
            else:
                logging.debug("Found a code block at line %d with no preceding filename; skipping.", i)
        
        i += 1

    return files

def parse_folder_structure(sections):
    """
    Attempts to extract a folder structure (a tree) from a section.
    We assume that the tree starts with a line ending with "/" (the root directory)
    and then subsequent lines representing files or subdirectories.
    
    Returns a dict with keys:
        'root'        : the root folder name.
        'directories' : a list of directory paths.
        'files'       : a list of file paths (as given in the tree).
    """
    lines = sections.splitlines()
    tree_lines = []
    start_collecting = False
    for line in lines:
        stripped = line.strip()
        if not start_collecting and stripped.endswith("/"):
            start_collecting = True
        if start_collecting and stripped:
            tree_lines.append(line.rstrip())
    logging.debug("Collected %d tree lines from folder structure section.", len(tree_lines))
    directories = set()
    files = set()
    root = ""
    if tree_lines:
        root = tree_lines[0].strip().rstrip("/")
        directories.add(root)
        for line in tree_lines[1:]:
            # Remove common tree-drawing characters and extra whitespace.
            line_clean = re.sub(r'^[\\s│├└─]+''', '', line).strip()
            if not line_clean:
                continue
            if line_clean.endswith("/"):
                directories.add(os.path.join(root, line_clean.rstrip("/")))
            else:
                files.add(os.path.join(root, line_clean))
    logging.debug("Parsed folder structure: root=%s, directories=%s, files=%s", root, directories, files)
    return {"root": root, "directories": list(directories), "files": list(files)}

def create_directories(directories, base_dir, dry_run=False):
    """
    Creates each directory (relative to base_dir) if it does not exist.
    """
    for directory in directories:
        full_path = os.path.join(base_dir, directory)
        logging.info("Creating directory: %s", full_path)
        if dry_run:
            logging.debug("Dry run enabled; directory not actually created.")
        else:
            try:
                os.makedirs(full_path, exist_ok=True)
                logging.debug("Directory created or already exists: %s", full_path)
            except Exception as e:
                logging.error("Failed to create directory %s: %s", full_path, e)

def write_file(file_path, content, base_dir, dry_run=False):
    """
    Writes the given content to file_path (relative to base_dir),
    creating any missing parent directories.
    """
    full_file_path = os.path.join(base_dir, file_path)
    parent_dir = os.path.dirname(full_file_path)
    if not os.path.exists(parent_dir):
        logging.info("Creating parent directory: %s", parent_dir)
        if dry_run:
            logging.debug("Dry run enabled; parent directory not actually created.")
        else:
            try:
                os.makedirs(parent_dir, exist_ok=True)
                logging.debug("Parent directory created: %s", parent_dir)
            except Exception as e:
                logging.error("Failed to create parent directory %s: %s", parent_dir, e)
    logging.info("Writing file: %s", full_file_path)
    if dry_run:
        logging.debug("Dry run enabled; file not actually written.")
    else:
        try:
            with open(full_file_path, "w", encoding="utf-8") as f:
                f.write(content)
            logging.debug("File written successfully: %s", full_file_path)
        except Exception as e:
            logging.error("Error writing file %s: %s", full_file_path, e)

def main():
    args = parse_args()
    
    # Configure logging.
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(levelname)s: %(message)s')
    
    logging.info("Starting llm_project_parser.py")
    logging.debug("Arguments: input=%s, output=%s, dry_run=%s, confirm=%s, verbose=%s",
                  args.input, args.output, args.dry_run, args.confirm, args.verbose)
    
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            lines = f.readlines()
        logging.info("Successfully read input file: %s", args.input)
    except Exception as exc:
        logging.error("Error reading input file %s: %s", args.input, exc)
        sys.exit(1)
    
    # For backward compatibility, we can still look for a "Folder Structure" section.
    text = "".join(lines)
    sections = re.split(r'^\s*-{3,}\s*$''', text, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]
    
    folder_section = None
    for sec in sections:
        if "Folder Structure" in sec:
            folder_section = sec
            break
    if folder_section:
        try:
            folder_structure = parse_folder_structure(folder_section)
            logging.info("Folder structure parsed successfully.")
            logging.debug("Folder structure: %s", folder_structure)
            create_directories(folder_structure["directories"], args.output, dry_run=args.dry_run)
        except Exception as e:
            logging.error("Error parsing folder structure: %s", e)
    else:
        logging.info("No folder structure section found; defaulting to flat structure.")
    
    valid_files = extract_files_from_lines(lines, interactive=args.confirm)
    logging.info("Found %d valid file(s).", len(valid_files))
    
    base_output = args.output
    for filename, content in valid_files:
        write_file(filename, content, base_output, dry_run=args.dry_run)
    
    logging.info("Processing complete.")

if __name__ == "__main__":
    main()
