#!/usr/bin/env python3
"""
llm_project_parser.py

This script intelligently parses LLM-generated project files. It automatically
detects one of two formats and extracts the files accordingly:

1.  Fenced Format: Identifies code within triple-backtick (```) blocks and
    searches for a filename in the vicinity.
2.  Header-Only Format: Identifies file headers (e.g., '# file.py') and
    treats all text between one header and the next as the file's content.

It detects and reports overlapping blocks (in fenced mode) and provides a
detailed preview before creating the project structure.

Usage example:
    python llm_project_parser.py -i project.txt -o output_dir
"""
import argparse
import os
import re
import sys
import logging
from typing import List, Dict, Optional, Tuple

# --- Constants ---
RED_TEXT = "\033[91m"
RESET_TEXT = "\033[0m"
ALLOWED_EXTENSIONS = {".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml"}
# This regex looks for a line that is primarily a filename, ignoring markdown noise.
FILENAME_REGEX = re.compile(r'^(?:[#*`\s]*)?([\w\./\\-]+\.[\w]+)[`*]*\s*$')
LEGACY_HEADER_REGEX = re.compile(r'^(?:#{1,6}\s*)?(\d+\.\s+.*)$')
COMMENT_HEADER_REGEX = re.compile(r'^\s*#\s+([\w\./\\-]+\.[\w]+)\s*$')

# --- Argument Parsing ---
def parse_args():
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Parse LLM output and extract code blocks into files.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-i", "--input", type=str, required=True,
                        help="Path to the input file.")
    parser.add_argument("-o", "--output", type=str, default=".",
                        help="Output directory for created files.")
    parser.add_argument("-d", "--dry-run", action="store_true",
                        help="Perform a dry run without creating files.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose (DEBUG level) logging.")
    parser.add_argument("-s", "--search-radius", type=int, default=3,
                        help="Line search radius for filenames in fenced mode (default: 3).")
    parser.add_argument("-p", "--preview-lines", type=int, default=5,
                        help="Lines to show in file previews (default: 5).")
    return parser.parse_args()

# --- Fenced Mode Logic ---
def find_code_blocks(lines: List[str]) -> Tuple[List[Dict], bool]:
    """Finds all fenced code blocks."""
    blocks, in_block, start_line, has_errors = [], False, -1, False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            if not in_block:
                in_block, start_line = True, i
            else:
                blocks.append({"start_line": start_line, "end_line": i, "content_lines": lines[start_line + 1:i]})
                in_block, start_line = False, -1
    
    sorted_blocks = sorted(blocks, key=lambda b: b['start_line'])
    for i in range(len(sorted_blocks) - 1):
        if sorted_blocks[i]['end_line'] > sorted_blocks[i+1]['start_line']:
            logging.error(f"{RED_TEXT}ERROR: OVERLAPPING CODE BLOCKS DETECTED! "
                          f"Block at lines {sorted_blocks[i]['start_line']}-{sorted_blocks[i]['end_line']} "
                          f"overlaps with block at {sorted_blocks[i+1]['start_line']}-{sorted_blocks[i+1]['end_line']}.{RESET_TEXT}")
            has_errors = True
    return sorted_blocks, has_errors

def find_filename_for_block(block: Dict, all_lines: List[str], radius: int, all_blocks: List[Dict]) -> Optional[str]:
    """Searches for a filename near a code block."""
    for i in range(1, radius + 1):
        for direction in [-1, 1]: # Up, then Down
            line_num = block['start_line' if direction == -1 else 'end_line'] + (i * direction)
            if 0 <= line_num < len(all_lines):
                if any(b['start_line'] <= line_num <= b['end_line'] for b in all_blocks if b != block): break
                match = FILENAME_REGEX.search(all_lines[line_num])
                if match: return match.group(1)
    return None

def extract_fenced_files(lines: List[str], search_radius: int) -> List[Dict]:
    """Orchestrates parsing for files with fenced code blocks."""
    all_blocks, has_errors = find_code_blocks(lines)
    if has_errors: sys.exit(1)
    if not all_blocks: return []
    
    logging.info(f"Found {len(all_blocks)} distinct code blocks. Searching for filenames...")
    valid_files = []
    for block in all_blocks:
        filename = find_filename_for_block(block, lines, search_radius, all_blocks)
        if filename:
            content = "".join(block['content_lines']).strip()
            valid_files.append({"name": filename, "content": content})
            logging.debug(f"Associated block at lines {block['start_line']}-{block['end_line']} with filename '{filename}'")
        else:
            logging.warning(f"Could not find a filename for code block at lines {block['start_line']}-{block['end_line']}.")
    return valid_files

# --- Header-Only Mode Logic ---
def clean_header_filename(raw_name: str) -> str:
    """Cleans filenames found in headers."""
    cleaned = re.sub(r'^\d+\.\s*', '', raw_name).strip()
    return re.sub(r'[\*_`]+', '', cleaned).strip()

def extract_header_only_files(lines: List[str]) -> List[Dict]:
    """Orchestrates parsing for files with headers and no fences."""
    headers = []
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        match = LEGACY_HEADER_REGEX.match(line_stripped) or COMMENT_HEADER_REGEX.match(line_stripped)
        if match:
            filename = clean_header_filename(match.group(1))
            headers.append({'filename': filename, 'start_line': i})
            logging.debug(f"Found header for '%s' at line %d", filename, i)
    
    if not headers: return []
    logging.info(f"Found {len(headers)} file headers. Extracting content...")
    
    valid_files = []
    for i, header in enumerate(headers):
        start_content = header['start_line'] + 1
        end_content = headers[i + 1]['start_line'] if i + 1 < len(headers) else len(lines)
        content = "".join(lines[start_content:end_content]).strip()
        valid_files.append({"name": header['filename'], "content": content})
    return valid_files

# --- Output and File Operations ---
def display_file_preview(filename: str, content: str, num_lines: int):
    """Prints a formatted preview of a file's content with line numbers."""
    print(f"--- File: {filename} ---")
    lines = content.splitlines()
    if not lines:
        print("    (empty file)")
    else:
        total_lines = len(lines)
        max_ln_len = len(str(total_lines - 1))
        def print_line(i): print(f"  {str(i).rjust(max_ln_len)}:    {lines[i]}")
        if total_lines <= num_lines * 2:
            for i in range(total_lines): print_line(i)
        else:
            for i in range(num_lines): print_line(i)
            print(f"  {' ' * max_ln_len}      ....skipping....")
            for i in range(total_lines - num_lines, total_lines): print_line(i)
    print("-" * (len(filename) + 8) + "\n")

def write_file(file_path: str, content: str, base_dir: str, dry_run: bool):
    """Writes content to a file, creating parent directories."""
    full_path = os.path.join(base_dir, file_path)
    parent_dir = os.path.dirname(full_path)
    logging.info(f"Preparing to write file: {full_path}")
    if dry_run:
        logging.info(f"[Dry Run] Would write {len(content.splitlines())} lines to {full_path}")
        return
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except Exception as e:
            logging.error(f"Failed to create parent directory {parent_dir}: {e}")
            return
    try:
        with open(full_path, "w", encoding="utf-8", newline="\n") as f: f.write(content)
        logging.debug(f"Successfully wrote file: {full_path}")
    except Exception as e:
        logging.error(f"Error writing file {full_path}: {e}")

# --- Main Orchestrator ---
def main():
    """Main script execution."""
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s: %(message)s', stream=sys.stdout)
    logging.debug(f"Arguments: {args}")

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            text = f.read()
            lines = text.splitlines(keepends=True)
        logging.info(f"Successfully read {len(lines)} lines from '{args.input}'.")
    except Exception as exc:
        logging.error(f"Error reading input file '{args.input}': {exc}"); sys.exit(1)

    if "```" in text:
        logging.info("Detected fenced code blocks. Using 'fenced' parsing mode.")
        valid_files = extract_fenced_files(lines, args.search_radius)
    else:
        logging.info("No fences detected. Using 'header-only' parsing mode.")
        valid_files = extract_header_only_files(lines)

    if not valid_files:
        logging.info("Could not find any valid files to create."); sys.exit(0)

    print("\n" + "="*20 + " FILE PREVIEW " + "="*20 + "\n")
    for f in valid_files: display_file_preview(f['name'], f['content'], args.preview_lines)
    print("="*54 + "\n")

    if args.dry_run: logging.info("Dry run is enabled. No files will be written.")
    for f in valid_files: write_file(f['name'], f['content'], args.output, args.dry_run)
    logging.info("Processing complete.")

if __name__ == "__main__":
    main()
