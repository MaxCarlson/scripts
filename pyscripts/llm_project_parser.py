#!/usr/bin/env python3
"""
llm_project_parser.py

This script reads an input file containing an LLM output (with file definitions and code blocks)
and then creates a folder structure and individual files in a target output directory.

Files are only created if a valid file header is immediately followed by a code block.
Filenames are cleaned of markdown formatting and validated for proper file extensions.
If no folder structure is found, a flat structure is used (all files are created directly under the output directory).

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

# Allowed file extensions (adjust as needed)
ALLOWED_EXTENSIONS = {".py", ".txt", ".md", ".json", ".yaml", ".yml"}

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
    Removes markdown formatting (e.g. **, __, backticks) from the file name.
    """
    cleaned = re.sub(r'[\*_`]+', '', raw_name).strip()
    return cleaned

def has_valid_extension(filename):
    """
    Checks if the file has one of the allowed extensions.
    """
    _, ext = os.path.splitext(filename)
    valid = ext.lower() in ALLOWED_EXTENSIONS
    if not valid:
        logging.warning("File '%s' does not have a valid extension.", filename)
    return valid

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
    Iterates line-by-line through the input lines and extracts (filename, code_block)
    pairs. A file header is expected to be a line that optionally starts with markdown header markers
    (like "##") followed by a number, a dot, and a file name.
    The very next encountered code block (delimited by triple backticks) is associated with that header.
    """
    files = []
    candidate_header = None
    header_regex = re.compile(r'^(?:#{1,6}\s*)?(\d+\.\s+.*)$')
    i = 0
    total_lines = len(lines)
    while i < total_lines:
        line = lines[i].rstrip("\n")
        header_match = header_regex.match(line)
        if header_match:
            # Found a file header; extract and clean filename.
            raw_header = header_match.group(1)
            candidate_header = clean_filename(raw_header)
            logging.debug("Found header at line %d: %s", i, candidate_header)
            i += 1
            continue
        if line.startswith("```"):
            # Found the start of a code block.
            if candidate_header is not None:
                # Optionally, capture language info (ignored here).
                i += 1  # skip the opening backticks line
                code_lines = []
                while i < total_lines and not lines[i].startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                # Skip the closing backticks, if present.
                if i < total_lines and lines[i].startswith("```"):
                    i += 1
                candidate_code = "\n".join(code_lines).strip()
                num_lines = len(candidate_code.splitlines())
                if num_lines < 6:
                    logging.warning("Code block for '%s' is very short (%d lines).", candidate_header, num_lines)
                    if interactive:
                        if not confirm_file_creation(candidate_header, candidate_code):
                            logging.info("User chose not to create file '%s'.", candidate_header)
                            candidate_header = None
                            continue
                    else:
                        logging.info("Skipping file '%s' due to short code block (use --confirm for interactive confirmation).", candidate_header)
                        candidate_header = None
                        continue
                if not has_valid_extension(candidate_header):
                    logging.warning("Skipping file '%s' due to invalid extension.", candidate_header)
                else:
                    files.append((candidate_header, candidate_code))
                    logging.info("Valid file found: %s", candidate_header)
                candidate_header = None  # reset header after pairing with code block
                continue
            else:
                # Found a code block without a preceding header.
                logging.debug("Encountered a code block at line %d with no candidate header; skipping.", i)
                # Skip this code block entirely.
                i += 1
                while i < total_lines and not lines[i].startswith("```"):
                    i += 1
                if i < total_lines and lines[i].startswith("```"):
                    i += 1
                continue
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
            line_clean = re.sub(r'^[\s│├└─]+', '', line).strip()
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
            text = f.read()
        logging.info("Successfully read input file: %s", args.input)
    except Exception as exc:
        logging.error("Error reading input file %s: %s", args.input, exc)
        sys.exit(1)
    
    # Split into sections to try to find a folder structure (if present).
    sections = re.split(r'^\s*-{3,}\s*$', text, flags=re.MULTILINE)
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
    
    # Process the entire file line-by-line to extract file definitions.
    file_lines = text.splitlines()
    valid_files = extract_files_from_lines(file_lines, interactive=args.confirm)
    logging.info("Found %d valid file(s).", len(valid_files))
    
    base_output = args.output
    for filename, content in valid_files:
        write_file(filename, content, base_output, dry_run=args.dry_run)
    
    logging.info("Processing complete.")

if __name__ == "__main__":
    main()

