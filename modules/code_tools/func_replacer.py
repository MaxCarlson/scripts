#!/usr/bin/env python3
"""
func_replacer.py: Replaces a function/class in a target file with
                  content from clipboard or a source file.
"""
import argparse
import sys
import os
import re
import shutil # <<< IMPORT ADDED HERE

import rgcodeblock_lib as rgc_lib
try:
    from cross_platform.clipboard_utils import get_clipboard
except ImportError:
    sys.stderr.write("Error: Could not import 'cross_platform.clipboard_utils'. Check installation/PYTHONPATH.\n")
    def get_clipboard(): sys.stderr.write("Warning: get_clipboard not available.\n"); return None

def extract_entity_name_from_code_heuristic(code_block_text: str, lang_type: str) -> str | None:
    lines = code_block_text.splitlines();
    if not lines: return None
    for line_idx, line_content_orig in enumerate(lines):
        if line_idx > 5 and lang_type != "python": break
        first_significant_line = line_content_orig.lstrip()
        if not first_significant_line or first_significant_line.startswith(('#', '//', '--', '/*')): continue
        if lang_type == "python":
            match = re.match(r"^\s*(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", first_significant_line)
            if match: return match.group(1)
        elif lang_type == "ruby":
            match = re.match(r"^\s*(?:def|class|module)\s+([A-Za-z_][A-Za-z0-9_:]*(?:\s*<.*)?)" , first_significant_line)
            if match: return match.group(1).split('<')[0].strip()
        elif lang_type == "lua":
            match = re.match(r"^\s*(?:local\s+)?function\s+([A-Za-z_][A-Za-z0-9_.:]*)", first_significant_line)
            if match: return match.group(1)
        elif lang_type == "brace":
            m_keyword = re.match(r"^\s*(?:class|struct|interface|enum|function)\s+([A-Za-z_][A-Za-z0-9_]*)", first_significant_line)
            if m_keyword: return m_keyword.group(1)
            m_func_like = re.search(r"(?:\b(?:void|int|float|double|char|bool|string|static|public|private|protected|final|virtual|override|async|Task|List<[^>]+>|std::\w+)\s+)?\b([A-Za-z_][A-Za-z0-9_<>:]+)\s*\(", first_significant_line)
            if m_func_like:
                potential_name = m_func_like.group(1)
                if potential_name not in ["if", "for", "while", "switch", "return", "new"]: return potential_name
        # Removed potentially problematic locals().get() check
    return None

def main():
    parser = argparse.ArgumentParser(prog="func_replacer", description="Replaces function/class in file.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("target_file", help="File to modify.")
    parser.add_argument("-n", "--name", help="Name to replace (inferred if omitted).")
    parser.add_argument("-s", "--source-file", help="File with replacement code (uses clipboard if omitted).")
    parser.add_argument("-l", "--line", type=int, help="Approximate 1-based line number of definition to replace.")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt.")
    parser.add_argument("--lang", choices=list(rgc_lib.LANGUAGE_DEFINITIONS.keys()), help="Manually specify target file language type.")
    parser.add_argument("--backup", action="store_true", help="Create a .bak backup before replacing.")
    args = parser.parse_args()

    new_block_content_str = ""; source_description = ""
    if args.source_file:
        try:
            with open(args.source_file, 'r', encoding='utf-8') as f: new_block_content_str = f.read()
            source_description = f"file '{args.source_file}'"
        except Exception as e: sys.stderr.write(f"Error reading source: {e}\n"); sys.exit(1)
    else:
        if get_clipboard is None: sys.stderr.write("Clipboard unavailable. Use --source-file.\n"); sys.exit(1)
        try: new_block_content_str = get_clipboard(); source_description = "clipboard"
        except Exception as e: sys.stderr.write(f"Error getting clipboard: {e}\n"); sys.exit(1)
        if new_block_content_str is None: # Explicit check if dummy returns None
            sys.stderr.write("Error: Clipboard function returned None. Aborting.\n"); sys.exit(1)
    if not new_block_content_str.strip(): sys.stderr.write(f"Error: Content from {source_description} empty.\n"); sys.exit(1)

    if args.lang: target_lang_type = args.lang
    else: target_lang_type, _ = rgc_lib.get_language_type_from_filename(args.target_file)
    if target_lang_type == "unknown": sys.stderr.write(f"Error: Cannot determine language for '{args.target_file}'. Use --lang.\n"); sys.exit(1)

    target_entity_name = args.name
    if not target_entity_name:
        target_entity_name = extract_entity_name_from_code_heuristic(new_block_content_str, target_lang_type)
        if not target_entity_name: sys.stderr.write(f"Error: Cannot infer name from {source_description} for '{target_lang_type}'. Use --name.\n"); sys.exit(1)
        print(f"Inferred entity name to replace: '{target_entity_name}' (from {source_description})")

    try:
        with open(args.target_file, 'r', encoding='utf-8', errors='surrogateescape') as f:
            original_lines_with_newlines = f.readlines(); f.seek(0); original_file_content_str = f.read()
    except FileNotFoundError: sys.stderr.write(f"Error: Target file '{args.target_file}' not found.\n"); sys.exit(1)
    except Exception as e: sys.stderr.write(f"Error reading target: {e}\n"); sys.exit(1)

    old_block_lines, old_block_start_0idx, old_block_end_0idx = None, -1, -1
    extractor_func = rgc_lib.EXTRACTOR_DISPATCH_MAP.get(target_lang_type)
    if not extractor_func: sys.stderr.write(f"Error: No extractor for '{target_lang_type}'.\n"); sys.exit(1)
    try:
        if args.line:
            target_line_1idx_for_extraction = args.line
            if target_lang_type == "python": old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(original_lines_with_newlines, original_file_content_str, target_entity_name=target_entity_name, target_line_1idx=target_line_1idx_for_extraction)
            elif target_lang_type in ["json", "yaml", "xml"]: old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(original_lines_with_newlines, target_line_1idx_for_extraction - 1, original_file_content_str)
            else: old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(original_lines_with_newlines, target_line_1idx_for_extraction - 1, target_entity_name=target_entity_name)
        elif target_entity_name:
            if target_lang_type == "python": old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(original_lines_with_newlines, original_file_content_str, target_entity_name=target_entity_name)
            else: # Heuristic scan
                found_declaration_line_0idx = -1
                for idx, line_txt in enumerate(original_lines_with_newlines):
                    is_declaration_line = False; stripped_line = line_txt.lstrip()
                    if target_lang_type == "ruby" and re.match(r"^\s*(def|class|module)\s+" + re.escape(target_entity_name) + r"\b", stripped_line): is_declaration_line = True
                    elif target_lang_type == "lua" and re.match(r"^\s*(?:local\s+)?function\s+" + re.escape(target_entity_name) + r"\b", stripped_line): is_declaration_line = True
                    elif target_lang_type == "brace" and re.search(r"\b" + re.escape(target_entity_name) + r"\b", stripped_line):
                         if "(" in stripped_line or "{" in stripped_line or "class" in stripped_line or "struct" in stripped_line: is_declaration_line=True
                    if is_declaration_line: found_declaration_line_0idx = idx; break
                if found_declaration_line_0idx != -1:
                    if target_lang_type in ["json", "yaml", "xml"]: old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(original_lines_with_newlines, found_declaration_line_0idx, original_file_content_str)
                    else: old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(original_lines_with_newlines, found_declaration_line_0idx, target_entity_name=target_entity_name)
                else: sys.stderr.write(f"Warning: Could not find declaration line for '{target_entity_name}'.\n")
        else: sys.stderr.write("Error: No name or line specified.\n"); sys.exit(1)
    except Exception as e_extract_replace: sys.stderr.write(f"Error during block location: {e_extract_replace}\n")

    if not old_block_lines or old_block_start_0idx == -1:
        sys.stderr.write(f"Error: Could not find or extract block for '{target_entity_name}' {('near line ' + str(args.line)) if args.line else ''} in '{args.target_file}'. Lang: {target_lang_type}\n")
        if rgc_lib.OPTIONAL_LIBRARY_NOTES: [sys.stderr.write(f"Note: {note}\n") for note in rgc_lib.OPTIONAL_LIBRARY_NOTES]
        sys.exit(1)

    print(f"Found block for '{target_entity_name}' in '{args.target_file}' (lines {old_block_start_0idx + 1} - {old_block_end_0idx + 1}).")
    print("--- Current Block (first 5 lines) ---"); [print(line.rstrip()) for line in old_block_lines[:5]]; print("---")
    print(f"\n--- New Block (from {source_description}, first 5 lines) ---"); [print(line) for line in new_block_content_str.splitlines()[:5]]; print("---")
    if not args.yes:
        try: confirm = input(f"\nReplace content for '{target_entity_name}' in '{args.target_file}'? (y/N): ")
        except EOFError: confirm = 'n'
        if confirm.lower() != 'y': print("Replacement aborted by user."); sys.exit(0)

    old_block_first_line_indent_str = re.match(r"^(\s*)", old_block_lines[0]).group(1) if old_block_lines else ""
    new_block_intermediate_lines = new_block_content_str.rstrip('\n').split('\n')
    new_block_lines_with_preserved_indent = []
    for line_new in new_block_intermediate_lines:
        new_block_lines_with_preserved_indent.append((old_block_first_line_indent_str + line_new.lstrip() + "\n") if line_new.strip() else "\n")
    if not any(line.strip() for line in new_block_lines_with_preserved_indent) and new_block_content_str.strip() == "":
        new_block_lines_with_preserved_indent = [old_block_first_line_indent_str + "\n"]
    final_file_lines = original_lines_with_newlines[:old_block_start_0idx] + new_block_lines_with_preserved_indent + original_lines_with_newlines[old_block_end_0idx + 1:]

    if args.backup:
        backup_file_path = args.target_file + ".bak"
        try:
            shutil.copy2(args.target_file, backup_file_path) # shutil imported at top
            print(f"Backup created: {backup_file_path}")
        except Exception as e_backup: sys.stderr.write(f"Warning: Could not create backup: {e_backup}\n")
    try:
        with open(args.target_file, 'w', encoding='utf-8') as f: f.writelines(final_file_lines)
        print(f"Successfully replaced '{target_entity_name}' in '{args.target_file}'.")
    except Exception as e: sys.stderr.write(f"Error writing target file: {e}\n"); sys.exit(1)

if __name__ == "__main__":
    main()
