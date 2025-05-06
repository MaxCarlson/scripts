#!/usr/bin/env python3
"""
func_replacer.py: Replaces a function/class in a target file with
                  content from clipboard or a source file.
"""
import argparse
import sys
import os
import re

# Assuming rgcodeblock_lib.py is in PYTHONPATH or installed
import rgcodeblock_lib as rgc_lib

# Assuming cross_platform module is in PYTHONPATH or installed
# If it's a sibling directory and you run from project root:
# from ..cross_platform.clipboard_utils import get_clipboard # If running as part of a larger package
# For simplicity, assume it's directly importable:
try:
    from cross_platform.clipboard_utils import get_clipboard
except ImportError:
    sys.stderr.write("Error: Could not import 'cross_platform.clipboard_utils'.\n"
                     "Ensure the 'cross_platform' module is installed or accessible in PYTHONPATH.\n")
    # Fallback dummy for environments without clipboard_utils, to allow script to load
    def get_clipboard():
        sys.stderr.write("Warning: get_clipboard (from cross_platform) not available. Clipboard operations will fail.\n")
        return None


def extract_entity_name_from_code_heuristic(code_block_text: str, lang_type: str) -> str | None:
    """
    Heuristically extracts the first function/class/module name from a block of code.
    This is a simplified heuristic and may need improvement for complex cases.
    """
    lines = code_block_text.splitlines()
    if not lines: return None

    for line_idx, line_content_orig in enumerate(lines):
        # Look for definition keywords on lines that are not heavily indented (likely top-level of the block)
        # This helps avoid picking names from nested structures if the whole block is passed.
        # A simple check for too much indent (e.g. if first line of block has indent X, don't go much deeper than X for name)
        # For now, just check first few lines.
        if line_idx > 5 and lang_type != "python": # Python AST is more robust
            break 

        first_significant_line = line_content_orig.lstrip()
        if not first_significant_line or first_significant_line.startswith(('#', '//', '--', '/*')): # Skip comments
            continue

        if lang_type == "python":
            # "def func_name(...):" or "class ClassName(...):"
            match = re.match(r"^\s*(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", first_significant_line)
            if match: return match.group(1)
        elif lang_type == "ruby":
            # "def func_name" or "class ClassName" or "module ModuleName"
            match = re.match(r"^\s*(?:def|class|module)\s+([A-Za-z_][A-Za-z0-9_:]*(?:\s*<.*)?)"
                             , first_significant_line) # Ruby names can have ::, and classes can have < Superclass
            if match: return match.group(1).split('<')[0].strip() # Get name before potential inheritance
        elif lang_type == "lua":
            # "function func_name" or "function module.func_name" or local function func_name
            match = re.match(r"^\s*(?:local\s+)?function\s+([A-Za-z_][A-Za-z0-9_.:]*)", first_significant_line)
            if match: return match.group(1)
        elif lang_type == "brace": # C, C++, Java, JS, TS, etc.
            # This is very tricky. Try to find common patterns.
            # 1. `function name(` (JS/TS)
            # 2. `class Name` / `struct Name` / `interface Name`
            # 3. `Type name(` (C/C++/Java/C# style function) - hardest to distinguish from calls
            
            # `function name(` or `class Name`
            m_keyword = re.match(r"^\s*(?:class|struct|interface|enum|function)\s+([A-Za-z_][A-Za-z0-9_]*)", first_significant_line)
            if m_keyword: return m_keyword.group(1)

            # Try to find `Type Name (` pattern. Avoid matching if it looks like a call inside parentheses.
            # This pattern is prone to false positives.
            # Look for name followed by '(', not preceded by common call characters like '.' or '->'
            # e.g. void myFunc ( or MyClass ( (constructor)
            # (\w+\s+)? is for optional return type
            # ([A-Za-z_][A-Za-z0-9_]+)\s*\(
            m_func_like = re.search(r"(?:\b(?:void|int|float|double|char|bool|string|static|public|private|protected|final|virtual|override|async|Task|List<[^>]+>|std::\w+)\s+)?\b([A-Za-z_][A-Za-z0-9_<>:]+)\s*\(", first_significant_line)
            if m_func_like:
                potential_name = m_func_like.group(1)
                # Avoid keywords as names, though this list is not exhaustive
                if potential_name not in ["if", "for", "while", "switch", "return", "new"]:
                    return potential_name
        # If found a potential name on this line, return it, otherwise continue to next line
        if line_idx == 0 and locals().get('match_found_on_this_line'): # If we found a name on the first line, good enough
            break
    return None


def main():
    parser = argparse.ArgumentParser(
        prog="func_replacer",
        description="Replaces a specified function or class in a target file with new content "
                    "from clipboard or a source file. Uses block extraction logic from rgcodeblock_lib.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("target_file", help="The file in which to replace the function/class.")
    parser.add_argument(
        "-n", "--name",
        help="Name of the function/class to replace. If not provided, attempts to infer from "
             "the first line of clipboard or source file content (this is heuristic)."
    )
    parser.add_argument(
        "-s", "--source-file",
        help="Path to a file containing the new function/class code. If not provided, uses clipboard content."
    )
    parser.add_argument(
        "-l", "--line",
        type=int,
        help="An approximate 1-indexed line number in the target_file where the function/class to be "
             "replaced is defined. This helps pinpoint the correct block, especially if the name is "
             "not unique or if by-name searching is ambiguous for the language."
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Automatically confirm replacement without prompting."
    )
    parser.add_argument(
        "--lang", choices=list(rgc_lib.LANGUAGE_DEFINITIONS.keys()), # Use keys from lib
        help="Manually specify the language type of the target file if its extension is "
             "ambiguous, missing, or not recognized. Affects parsing strategy."
    )
    parser.add_argument(
        "--backup", action="store_true",
        help="Create a backup of the target file (e.g., file.ext.bak) before replacing."
    )

    args = parser.parse_args()

    # 1. Get the new block content (replacement code)
    new_block_content_str = ""
    source_description = ""
    if args.source_file:
        try:
            with open(args.source_file, 'r', encoding='utf-8') as f:
                new_block_content_str = f.read()
            source_description = f"file '{args.source_file}'"
        except Exception as e:
            sys.stderr.write(f"Error reading source file '{args.source_file}': {e}\n")
            sys.exit(1)
    else:
        if get_clipboard is None: # Check if dummy was assigned
             sys.stderr.write("Clipboard functionality is not available on this system or due to missing dependencies.\n"
                              "Please use --source-file to provide replacement content.\n")
             sys.exit(1)
        try:
            new_block_content_str = get_clipboard()
            source_description = "clipboard"
        except Exception as e: 
            sys.stderr.write(f"Error getting clipboard content: {e}\n")
            sys.exit(1)

    if not new_block_content_str.strip(): # Check if content is all whitespace
        sys.stderr.write(f"Error: Content from {source_description} is empty or whitespace only.\n")
        sys.exit(1)

    # 2. Determine target file language type
    if args.lang:
        target_lang_type = args.lang
        # If user specified lang, also get a representative raw_ext for stats/logging if needed
        # This is a bit of a hack; normally raw_ext comes from the actual filename.
        # Find first ext for this lang type for consistency if needed elsewhere.
        _ , target_raw_ext = rgc_lib.get_language_type_from_filename(f"dummy{rgc_lib.LANGUAGE_DEFINITIONS.get(target_lang_type, {}).get('exts', [''])[0]}")

    else:
        target_lang_type, target_raw_ext = rgc_lib.get_language_type_from_filename(args.target_file)

    if target_lang_type == "unknown":
        sys.stderr.write(f"Error: Could not determine language type for '{args.target_file}'. "
                         f"Please use the --lang argument to specify it from available types "
                         f"(see rgcodeblock --list-languages).\n")
        sys.exit(1)

    # 3. Determine the name of the function/class to replace
    target_entity_name = args.name
    if not target_entity_name: # If name not provided via --name
        target_entity_name = extract_entity_name_from_code_heuristic(new_block_content_str, target_lang_type)
        if not target_entity_name:
            sys.stderr.write(f"Error: Could not automatically infer function/class name from {source_description} "
                             f"for language '{target_lang_type}'.\nThis heuristic is basic. "
                             f"Please provide the name explicitly using the --name argument.\n")
            sys.exit(1)
        print(f"Inferred entity name to replace: '{target_entity_name}' (from {source_description})")


    # 4. Read target file content
    try:
        with open(args.target_file, 'r', encoding='utf-8', errors='surrogateescape') as f:
            original_lines_with_newlines = f.readlines()
            f.seek(0) # Rewind for full content string if needed by extractors
            original_file_content_str = f.read()
    except FileNotFoundError:
        sys.stderr.write(f"Error: Target file '{args.target_file}' not found.\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"Error reading target file '{args.target_file}': {e}\n")
        sys.exit(1)

    # 5. Find the block to replace in the target file using rgcodeblock_lib
    old_block_lines, old_block_start_0idx, old_block_end_0idx = None, -1, -1
    
    extractor_func = rgc_lib.EXTRACTOR_DISPATCH_MAP.get(target_lang_type)
    if not extractor_func:
        sys.stderr.write(f"Error: No block extractor implementation available for language type '{target_lang_type}'.\n")
        sys.exit(1)

    try:
        # Prioritize line number if given, as it's more specific for locating the *instance*
        # Pass target_entity_name to extractors that support it (Python, Ruby, Lua potentially)
        if args.line:
            target_line_1idx_for_extraction = args.line
            if target_lang_type == "python":
                 old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(
                    original_lines_with_newlines, original_file_content_str,
                    target_entity_name=target_entity_name, # Use name to confirm at the line
                    target_line_1idx=target_line_1idx_for_extraction
                )
            elif target_lang_type in ["json", "yaml", "xml"]: # These primarily use line_0idx and full content
                old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(
                    original_lines_with_newlines, target_line_1idx_for_extraction - 1, original_file_content_str
                )
            else: # brace, ruby, lua might use name with line
                old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(
                    original_lines_with_newlines, target_line_1idx_for_extraction - 1, target_entity_name=target_entity_name
                )
        elif target_entity_name: # No line hint, find by name (AST for Python, others more heuristic)
            if target_lang_type == "python":
                old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(
                    original_lines_with_newlines, original_file_content_str, target_entity_name=target_entity_name
                )
            else: # Heuristic scan for other languages to find first declaration line
                found_declaration_line_0idx = -1
                for idx, line_txt in enumerate(original_lines_with_newlines):
                    # Refined heuristic for finding declaration by name
                    is_declaration_line = False
                    stripped_line = line_txt.lstrip()
                    if target_lang_type == "ruby" and re.match(r"^\s*(def|class|module)\s+" + re.escape(target_entity_name) + r"\b", stripped_line): is_declaration_line = True
                    elif target_lang_type == "lua" and re.match(r"^\s*(?:local\s+)?function\s+" + re.escape(target_entity_name) + r"\b", stripped_line): is_declaration_line = True
                    elif target_lang_type == "brace": 
                        # Look for name followed by ( or { on roughly the same line, or class/struct Name
                        if re.search(r"\b" + re.escape(target_entity_name) + r"\s*\(", stripped_line) or \
                           re.search(r"\b" + re.escape(target_entity_name) + r"\s*\{", stripped_line) or \
                           re.match(r"^\s*(class|struct|enum|interface)\s+" + re.escape(target_entity_name) + r"\b", stripped_line):
                            is_declaration_line = True
                    
                    if is_declaration_line:
                        found_declaration_line_0idx = idx
                        break # Found first likely declaration
                
                if found_declaration_line_0idx != -1:
                    # Now call the extractor with this found line as the target_line_0idx
                    if target_lang_type in ["json", "yaml", "xml"]: # Unlikely for named entities, but for completeness
                        old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(original_lines_with_newlines, found_declaration_line_0idx, original_file_content_str)
                    else: # brace, ruby, lua
                        old_block_lines, old_block_start_0idx, old_block_end_0idx = extractor_func(original_lines_with_newlines, found_declaration_line_0idx, target_entity_name=target_entity_name)
                else:
                    sys.stderr.write(f"Warning: Could not heuristically find a declaration line for '{target_entity_name}' in '{args.target_file}'.\n"
                                     f"Try providing the --line argument for a more precise location.\n")
        else: # Should not be reached if logic for getting target_entity_name is correct
            sys.stderr.write("Error: No entity name or line number specified for replacement.\n")
            sys.exit(1)
            
    except Exception as e_extract_replace:
        sys.stderr.write(f"Error during block location for '{target_entity_name}': {e_extract_replace}\n")
        # old_block_lines will remain None or previous value

    if not old_block_lines or old_block_start_0idx == -1:
        sys.stderr.write(f"Error: Could not find or extract the specified block for '{target_entity_name}' "
                         f"{('near line ' + str(args.line)) if args.line else ''} in '{args.target_file}'.\n"
                         f"Please check the name, line number, and language type. Lang: {target_lang_type}\n")
        if rgc_lib.OPTIONAL_LIBRARY_NOTES:
            for note in rgc_lib.OPTIONAL_LIBRARY_NOTES: sys.stderr.write(f"Note: {note}\n")
        sys.exit(1)

    print(f"Found block for '{target_entity_name}' in '{args.target_file}' (lines {old_block_start_0idx + 1} - {old_block_end_0idx + 1}).")
    print("--- Current Block (first 5 lines) ---")
    for line_idx_preview in range(min(5, len(old_block_lines))): print(old_block_lines[line_idx_preview].rstrip())
    if len(old_block_lines) > 5: print("...")
    print("--- End Current Block ---")
    
    print(f"\n--- New Block (from {source_description}, first 5 lines) ---")
    new_block_preview_lines = new_block_content_str.splitlines()
    for line_idx_preview in range(min(5, len(new_block_preview_lines))): print(new_block_preview_lines[line_idx_preview])
    if len(new_block_preview_lines) > 5: print("...")
    print("--- End New Block ---")

    # 6. Confirmation
    if not args.yes:
        try:
            confirm = input(f"\nReplace content for '{target_entity_name}' in '{args.target_file}'? (y/N): ")
        except EOFError: # Handle non-interactive environments
            confirm = 'n'
        if confirm.lower() != 'y':
            print("Replacement aborted by user.")
            sys.exit(0)

    # 7. Perform replacement
    # Preserve indentation of the first line of the old block for the new block.
    old_block_first_line_indent_str = ""
    if old_block_lines: # Should always be true if we reached here
        indent_match_obj = re.match(r"^(\s*)", old_block_lines[0])
        if indent_match_obj:
            old_block_first_line_indent_str = indent_match_obj.group(1)

    # Prepare new block lines, applying old block's initial indent to each new line.
    # Ensure new block content ends with a newline if it's multi-line or if original did.
    # new_block_content_str typically comes from file or clipboard, usually with newlines.
    
    # Split new content, re-indent, and add newlines back.
    # Remove trailing newlines from input string, then add them per line.
    new_block_intermediate_lines = new_block_content_str.rstrip('\n').split('\n')
    new_block_lines_with_preserved_indent = []
    for line_idx_new, line_new in enumerate(new_block_intermediate_lines):
        # Add indent to non-empty lines. Empty lines in the middle of block keep their relative structure.
        if line_new.strip(): # Only add indent to lines with content
             new_block_lines_with_preserved_indent.append(old_block_first_line_indent_str + line_new.lstrip() + "\n")
        else: # Preserve empty lines as they are (with a newline)
             new_block_lines_with_preserved_indent.append("\n")
    
    # If the new block content was effectively empty after stripping (e.g. just whitespace),
    # make it a single indented newline (might represent an empty function body or 'pass').
    if not any(line.strip() for line in new_block_lines_with_preserved_indent) and \
       new_block_content_str.strip() == "":
        new_block_lines_with_preserved_indent = [old_block_first_line_indent_str + "\n"]


    # Construct the final list of lines for the new file content
    final_file_lines = original_lines_with_newlines[:old_block_start_0idx] + \
                       new_block_lines_with_preserved_indent + \
                       original_lines_with_newlines[old_block_end_0idx + 1:]

    # 8. Backup and Write
    if args.backup:
        backup_file_path = args.target_file + ".bak"
        try:
            import shutil
            shutil.copy2(args.target_file, backup_file_path)
            print(f"Backup created: {backup_file_path}")
        except Exception as e_backup:
            sys.stderr.write(f"Warning: Could not create backup file at {backup_file_path}: {e_backup}\n")


    try:
        with open(args.target_file, 'w', encoding='utf-8') as f:
            f.writelines(final_file_lines)
        print(f"Successfully replaced '{target_entity_name}' in '{args.target_file}'.")
    except Exception as e:
        sys.stderr.write(f"Error writing updated content to '{args.target_file}': {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
