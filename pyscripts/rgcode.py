#!/usr/bin/env python3
"""
rgcodeblock: A tool to find and display enclosing code blocks for ripgrep matches.

Supports:
- Python (.py): Uses AST.
- Brace-based languages (.c, .cpp, .java, .js, etc.): Brace counting.
- JSON (.json): Uses the built-in `json` module.
- YAML (.yaml, .yml): Uses `PyYAML` (optional dependency).
- XML (.xml, .xsl, .xsd, . Kml, .svg etc.): Uses `lxml` (optional dependency).
- Ruby (.rb): Keyword-pair matching (def/class/module...end).
- Lua (.lua): Keyword-pair matching (function/if/for...end).

The matched search term is highlighted. Falls back to context if extraction fails.
"""

import subprocess
import json
import argparse
import os
import re
import ast # For Python code analysis
import sys

# --- Optional Dependency Handling ---
YAML_SUPPORT = False
try:
    import yaml # PyYAML
    YAML_SUPPORT = True
except ImportError:
    pass

LXML_SUPPORT = False
try:
    from lxml import etree
    LXML_SUPPORT = True
except ImportError:
    pass

# --- ANSI Color Codes ---
DEFAULT_HIGHLIGHT_COLOR_CODE_STR = "1;31"  # Bold Red
RESET_COLOR_ANSI = "\033[0m"

# --- Global list for messages about optional features ---
OPTIONAL_FEATURE_MESSAGES = []

def get_language_type(filename: str) -> str:
    """Determines language type based on file extension."""
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    # Python
    if ext == ".py": return "python"

    # JSON
    if ext == ".json": return "json"

    # YAML
    if ext in [".yaml", ".yml"]: return "yaml"

    # XML and related
    if ext in [".xml", ".xsd", ".xsl", ".xslt", ".kml", ".svg", ".plist", ".csproj", ".vbproj", ".fxml", ".graphml", ".gexf"]:
        return "xml"

    # Ruby
    if ext == ".rb": return "ruby"

    # Lua
    if ext == ".lua": return "lua"

    # Brace-based languages (expanded list)
    brace_extensions = [
        ".c", ".h",                                # C
        ".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx", # C++
        ".cs",                                     # C#
        ".java",                                   # Java
        ".js", ".jsx", ".mjs", ".cjs",               # JavaScript & variants
        ".ts", ".tsx",                             # TypeScript
        ".go",                                     # Go
        ".rs",                                     # Rust
        ".kt", ".kts",                             # Kotlin
        ".swift",                                  # Swift
        ".php", ".phtml",                          # PHP
        ".scl", ".sbt",                            # Scala (often uses braces)
        ".gd",                                     # GDScript (Godot Engine)
        ".glsl", ".frag", ".vert",                 # Shaders
        ".groovy", ".gvy", ".gy", ".gsh",           # Groovy
        ".dart",                                   # Dart
        ".r", ".R",                                # R (often uses braces for functions/blocks)
        ".objective-c", ".m", ".mm",               # Objective-C
        ".shader",                                 # Unity Shader
        ".pde",                                    # Processing
        ".vala",                                   # Vala
        ".d"                                       # D Language
    ]
    if ext in brace_extensions:
        return "brace"

    return "unknown"

def highlight_text_in_line(line: str, text_to_highlight: str, ansi_color_sequence: str) -> str:
    """Highlights text in a line using ANSI codes."""
    if not text_to_highlight: return line
    try:
        escaped_search_text = re.escape(text_to_highlight)
        return re.sub(f"({escaped_search_text})", f"{ansi_color_sequence}\\1{RESET_COLOR_ANSI}", line)
    except re.error:
        return line

# --- Extraction Functions ---

def extract_python_block_ast(lines_with_newlines: list[str], match_line_1idx: int, file_content_str: str) -> list[str] | None:
    """Extracts Python block using AST."""
    try:
        tree = ast.parse(file_content_str)
    except SyntaxError:
        return None

    candidate_nodes_info = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            node_start_line = node.lineno
            node_end_line = getattr(node, 'end_lineno', None)
            if node_end_line is None:
                if node.body:
                    last_stmt_or_expr = node.body[-1]
                    node_end_line = getattr(last_stmt_or_expr, 'end_lineno', last_stmt_or_expr.lineno)
                else:
                    node_end_line = node_start_line
            if node_start_line <= match_line_1idx <= node_end_line:
                candidate_nodes_info.append({'start_line': node_start_line, 'end_line': node_end_line})
    
    if not candidate_nodes_info: return None
    best_node_info = max(candidate_nodes_info, key=lambda n: n['start_line'])
    return lines_with_newlines[best_node_info['start_line'] - 1 : best_node_info['end_line']]

def extract_brace_block(lines_with_newlines: list[str], match_line_0idx: int) -> list[str] | None:
    """Extracts a brace-enclosed block."""
    open_b, close_b = '{', '}'
    enclosing_block_start_line_idx = -1
    balance = 0
    for i in range(match_line_0idx, -1, -1):
        line_content = lines_with_newlines[i]
        for char_idx in range(len(line_content) - 1, -1, -1):
            char = line_content[char_idx]
            if char == close_b: balance += 1
            elif char == open_b:
                balance -= 1
                if balance < 0:
                    enclosing_block_start_line_idx = i
                    break
        if enclosing_block_start_line_idx != -1: break
    if enclosing_block_start_line_idx == -1: return None

    block_end_line_idx = -1
    block_balance = 0
    first_brace_of_this_block_found = False
    for i in range(enclosing_block_start_line_idx, len(lines_with_newlines)):
        line_content = lines_with_newlines[i]
        for char_idx in range(len(line_content)):
            char = line_content[char_idx]
            if char == open_b:
                block_balance += 1
                if i >= enclosing_block_start_line_idx: first_brace_of_this_block_found = True
            elif char == close_b:
                if first_brace_of_this_block_found: block_balance -= 1
        if first_brace_of_this_block_found and block_balance == 0:
            block_end_line_idx = i
            break
    if not first_brace_of_this_block_found: return None
    if block_end_line_idx == -1: block_end_line_idx = len(lines_with_newlines) - 1
    return lines_with_newlines[enclosing_block_start_line_idx : block_end_line_idx + 1]

def extract_json_block(lines_with_newlines: list[str], match_line_0idx: int, file_content_str: str) -> list[str] | None:
    """
    Extracts the smallest JSON object or array enclosing the match.
    This is a heuristic based on brace/bracket counting, similar to extract_brace_block,
    but adapted for JSON's simpler structure.
    """
    # Try full parsing first if the content is small enough (as a quick check for validity)
    try:
        if len(file_content_str) < 1024 * 1024: # Only try to parse reasonably small JSON files
            json.loads(file_content_str)
        # If it parses, we still use the heuristic to find the *smallest* enclosing block
        # containing the string match, as full AST-like traversal for string match location is complex.
    except json.JSONDecodeError:
        OPTIONAL_FEATURE_MESSAGES.append(f"Warning: File appears to be invalid JSON, block extraction may be inaccurate.")
        # Proceed with heuristic anyway

    delimiters = [ ('{', '}'), ('[', ']') ]
    best_block = None

    for open_d, close_d in delimiters:
        enclosing_block_start_line_idx = -1
        balance = 0
        for i in range(match_line_0idx, -1, -1):
            line_content = lines_with_newlines[i]
            for char_idx in range(len(line_content) - 1, -1, -1):
                char = line_content[char_idx]
                if char == close_d: balance += 1
                elif char == open_d:
                    balance -= 1
                    if balance < 0:
                        enclosing_block_start_line_idx = i
                        break
            if enclosing_block_start_line_idx != -1: break
        
        if enclosing_block_start_line_idx == -1: continue

        block_end_line_idx = -1
        block_balance = 0
        first_delimiter_found = False
        for i in range(enclosing_block_start_line_idx, len(lines_with_newlines)):
            line_content = lines_with_newlines[i]
            for char_idx in range(len(line_content)):
                char = line_content[char_idx]
                if char == open_d:
                    block_balance += 1
                    if i >= enclosing_block_start_line_idx: first_delimiter_found = True
                elif char == close_d:
                    if first_delimiter_found: block_balance -= 1
            if first_delimiter_found and block_balance == 0:
                block_end_line_idx = i
                break
        
        if not first_delimiter_found: continue
        if block_end_line_idx == -1: block_end_line_idx = len(lines_with_newlines) - 1
        
        current_block = lines_with_newlines[enclosing_block_start_line_idx : block_end_line_idx + 1]
        if best_block is None or len(current_block) < len(best_block): # Prefer smaller (innermost) block
            best_block = current_block
            
    return best_block

def extract_yaml_block(lines_with_newlines: list[str], match_line_0idx: int, file_content_str: str) -> list[str] | None:
    """Extracts YAML block using PyYAML if available."""
    if not YAML_SUPPORT:
        OPTIONAL_FEATURE_MESSAGES.append(
            "YAML processing skipped: PyYAML library not found. Install with 'pip install PyYAML'."
        )
        return None
    try:
        # PyYAML loads all documents. We are interested in the one containing the match.
        # This is complex because a string match doesn't easily map to parsed YAML structure
        # for the purpose of defining "the block".
        # A simple heuristic: find the document that contains the match line.
        # Then, attempt to find the nearest mapping or sequence that contains the match.
        # For simplicity here, we'll return the whole document containing the match.
        # A more refined approach would traverse the parsed structure.
        
        doc_start_lines = [i for i, line in enumerate(lines_with_newlines) if line.strip() == "---"]
        if not doc_start_lines or doc_start_lines[0] != 0:
            doc_start_lines.insert(0,0) # Assume doc starts at line 0 if no '---' at start

        target_doc_start_line = 0
        target_doc_end_line = len(lines_with_newlines) -1

        for i in range(len(doc_start_lines)):
            start_idx = doc_start_lines[i]
            end_idx = doc_start_lines[i+1] -1 if (i + 1) < len(doc_start_lines) else len(lines_with_newlines) -1
            if start_idx <= match_line_0idx <= end_idx:
                target_doc_start_line = start_idx
                target_doc_end_line = end_idx
                break
        
        # Attempt to parse just this document to verify its validity somewhat
        doc_content_to_parse = "".join(lines_with_newlines[target_doc_start_line : target_doc_end_line + 1])
        try:
            list(yaml.safe_load_all(doc_content_to_parse)) # Check if it parses
        except yaml.YAMLError as e:
            OPTIONAL_FEATURE_MESSAGES.append(f"Warning: YAML document section has parsing errors: {e}")
            # Fallback to returning the identified section anyway
        
        return lines_with_newlines[target_doc_start_line : target_doc_end_line + 1]

    except Exception as e:
        OPTIONAL_FEATURE_MESSAGES.append(f"Error during YAML processing: {e}")
        return None

def extract_xml_block(lines_with_newlines: list[str], match_line_0idx: int, file_content_str: str) -> list[str] | None:
    """Extracts XML block using lxml if available."""
    if not LXML_SUPPORT:
        OPTIONAL_FEATURE_MESSAGES.append(
            "XML processing skipped: lxml library not found. Install with 'pip install lxml'."
        )
        return None
    try:
        # lxml line numbers are 1-based.
        parser = etree.XMLParser(recover=True, collect_ids=False, strip_cdata=False) # recover mode
        root = etree.fromstring(file_content_str.encode('utf-8'), parser=parser)
        
        best_node_info = None
        for element in root.xpath('//*'): # Iterate over all elements
            if not hasattr(element, 'sourceline'): continue # Skip comments, PIs etc. that don't have sourceline

            # Approximate end line. lxml doesn't directly give end_sourceline for an element.
            # We can take the sourceline of the next sibling or parent's end, or EOF.
            # For simplicity, we'll find the smallest element that *starts* at or before the match
            # and whose *text or tail or attribute value* on that line (or children) implies it covers the match.
            # This is hard to map directly from a string match to an AST node without string content.
            # Heuristic: Find smallest element whose sourceline <= match_line and whose content spans it.

            node_start_line = element.sourceline # 1-indexed
            
            # Heuristic for node_end_line: Last child's line or element's own line if no children
            node_end_line = node_start_line
            if len(element): # Has children
                last_child = element[-1]
                while len(last_child) and hasattr(last_child[-1], 'sourceline'): # Deepest last child
                    last_child = last_child[-1]
                if hasattr(last_child, 'sourceline'):
                    node_end_line = last_child.sourceline 
                    # Add length of last child's text if it's multi-line.
                    if last_child.text: node_end_line += last_child.text.count('\n')
            elif element.text: # No children, check element text
                 node_end_line += element.text.count('\n')

            # Check if match_line_0idx + 1 (to make it 1-indexed) is within this node
            if node_start_line <= (match_line_0idx + 1) <= node_end_line:
                current_size = node_end_line - node_start_line
                if best_node_info is None or current_size < best_node_info['size']:
                    # Refine end_line to be more accurate by finding the actual end tag.
                    # This is tricky. For now, we'll use the lines from lxml's parsed element.
                    # This can be improved by serializing the element and getting its line count.
                    temp_element_str = etree.tostring(element).decode('utf-8')
                    num_lines_in_element_str = temp_element_str.count('\n')
                    actual_end_line = node_start_line + num_lines_in_element_str

                    best_node_info = {
                        'start_line': node_start_line, # 1-indexed
                        'end_line': actual_end_line,   # 1-indexed
                        'size': actual_end_line - node_start_line
                    }
        
        if best_node_info:
            # lxml lines are 1-indexed. Slice lines_with_newlines (0-indexed).
            return lines_with_newlines[best_node_info['start_line'] - 1 : best_node_info['end_line']]
        return None

    except etree.XMLSyntaxError as e:
        OPTIONAL_FEATURE_MESSAGES.append(f"Warning: XML file has syntax errors: {e}")
        return None # Fallback to context
    except Exception as e:
        OPTIONAL_FEATURE_MESSAGES.append(f"Error during XML processing: {e}")
        return None

def _extract_keyword_pair_block(
    lines_with_newlines: list[str],
    match_line_0idx: int,
    block_starters_regex: str, # e.g., r"^\s*(def|class|module)\b"
    block_ender_regex: str,    # e.g., r"^\s*end\b"
    optional_intermediate_keywords_regex: str | None = None # e.g., r"^\s*(else|elsif|rescue|ensure)\b"
) -> list[str] | None:
    """Helper for languages like Ruby, Lua using keyword pairs (def/end, function/end)."""
    
    # Phase 1: Find the line index of the block starter (def, function, etc.)
    block_start_line_idx = -1
    indent_level_of_starter = -1
    balance = 0 # When scanning upwards: 'end' increments, 'starter' decrements.

    for i in range(match_line_0idx, -1, -1):
        line_content = lines_with_newlines[i].strip() # Compare stripped lines for keywords
        if re.match(block_ender_regex, line_content):
            balance += 1
        elif re.match(block_starters_regex, line_content):
            balance -=1
            if balance < 0: # This is our starter
                block_start_line_idx = i
                # Get indent of the original line
                match_indent = re.match(r"^(\s*)", lines_with_newlines[i])
                indent_level_of_starter = len(match_indent.group(1)) if match_indent else 0
                break
    
    if block_start_line_idx == -1:
        return None

    # Phase 2: Find the matching 'end'
    block_end_line_idx = -1
    balance = 0 # Reset balance. Starter increments, ender decrements.
    
    for i in range(block_start_line_idx, len(lines_with_newlines)):
        line_content_orig = lines_with_newlines[i]
        line_content_stripped = line_content_orig.strip()

        if re.match(block_starters_regex, line_content_stripped):
            balance +=1
        elif re.match(block_ender_regex, line_content_stripped):
            balance -=1
        # Optional: Handle intermediate keywords like 'else', 'elsif' if they don't affect balance
        # For simplicity, this basic version doesn't deeply handle them for balance,
        # assuming they are within a balanced starter/ender pair.

        if balance == 0 and i >= block_start_line_idx : # Make sure we've at least seen the starter
             # Check indentation for 'end' to ensure it matches the starter (simple heuristic for Ruby/Lua)
             match_end_indent = re.match(r"^(\s*)", line_content_orig)
             current_indent = len(match_end_indent.group(1)) if match_end_indent else 0
             if re.match(block_ender_regex, line_content_stripped) and current_indent == indent_level_of_starter:
                block_end_line_idx = i
                break
    
    if block_end_line_idx == -1: # Potentially malformed or reached EOF
        # As a fallback, if balance is 1 (meaning one 'starter' is open), take to EOF
        if balance == 1 and block_start_line_idx != -1:
             block_end_line_idx = len(lines_with_newlines) - 1
        else:
            return None

    return lines_with_newlines[block_start_line_idx : block_end_line_idx + 1]

def extract_ruby_block(lines_with_newlines: list[str], match_line_0idx: int) -> list[str] | None:
    """Extracts Ruby block (def/class/module...end, if...end, etc.)."""
    # More specific regex might be needed for do...end blocks if they are primary targets
    starters = r"^\s*(def|class|module|if|unless|case|while|until|for|begin)\b"
    ender = r"^\s*end\b"
    # `else`, `elsif`, `rescue`, `ensure`, `when` can appear within these blocks.
    # A full parser would handle these. This heuristic focuses on the main block.
    return _extract_keyword_pair_block(lines_with_newlines, match_line_0idx, starters, ender)

def extract_lua_block(lines_with_newlines: list[str], match_line_0idx: int) -> list[str] | None:
    """Extracts Lua block (function...end, if...end, etc.)."""
    starters = r"^\s*(function|if|while|for|repeat)\b" # repeat...until is different
    ender = r"^\s*end\b"
    # `elseif`, `else` are intermediates. `until` pairs with `repeat`.
    # This simplified version handles common `... end` blocks.
    return _extract_keyword_pair_block(lines_with_newlines, match_line_0idx, starters, ender)


def print_context_fallback(lines_with_newlines: list[str], match_line_0idx: int, text_to_highlight: str,
                           ansi_color_sequence: str, num_context_lines: int):
    """Prints context lines as a fallback."""
    start_slice = max(0, match_line_0idx - num_context_lines)
    end_slice = min(len(lines_with_newlines), match_line_0idx + num_context_lines + 1)
    for i in range(start_slice, end_slice):
        line_to_print = lines_with_newlines[i].rstrip('\n')
        if i == match_line_0idx:
            line_to_print = highlight_text_in_line(line_to_print, text_to_highlight, ansi_color_sequence)
        print(line_to_print)

# --- Main ---
def main():
    parser = argparse.ArgumentParser(
        prog="rgcodeblock",
        description=(
            "Finds and prints enclosing code blocks for ripgrep matches.\n"
            "Supports Python, C-style, JSON, YAML (optional), XML (optional), Ruby, Lua.\n"
            "Highlights matched text. Falls back to context if block extraction fails."
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("pattern", help="Pattern for ripgrep.")
    parser.add_argument("path", nargs="?", default=".", help="File/directory to search (default: .).")
    parser.add_argument("-c", "--color", default=DEFAULT_HIGHLIGHT_COLOR_CODE_STR,
                        help=f"ANSI color code string for highlight (e.g., '1;31'). Default: '{DEFAULT_HIGHLIGHT_COLOR_CODE_STR}'.")
    parser.add_argument("-C", "--context", type=int, default=3, metavar="NUM",
                        help="Context lines for fallback (default: 3).")
    args = parser.parse_args()

    highlight_ansi_sequence = f"\033[{args.color}m"

    try:
        rg_cmd = ["rg", "--json", args.pattern, args.path]
        process = subprocess.run(rg_cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print("Error: ripgrep (rg) not found. Please install it.", file=sys.stderr)
        sys.exit(2)
    
    if process.returncode > 1:
        print(f"Error from ripgrep (rg):\n{process.stderr}", file=sys.stderr)
        sys.exit(process.returncode)
    if not process.stdout.strip():
        sys.exit(0 if process.returncode == 1 else 1)

    processed_matches_count = 0
    global OPTIONAL_FEATURE_MESSAGES # To collect messages
    unique_opt_messages = set()

    for line_json_str in process.stdout.strip().split('\n'):
        if not line_json_str: continue
        try:
            data = json.loads(line_json_str)
        except json.JSONDecodeError:
            print(f"Warning: Bad rg JSON: {line_json_str[:100]}...", file=sys.stderr)
            continue
        if data.get("type") != "match": continue
        
        match_data = data.get("data", {})
        file_path = match_data.get("path", {}).get("text")
        match_line_1idx = match_data.get("line_number")
        text_to_highlight = args.pattern
        submatches = match_data.get("submatches", [])
        if submatches and submatches[0].get("match", {}).get("text"):
            text_to_highlight = submatches[0]["match"]["text"]

        if not all([file_path, isinstance(match_line_1idx, int)]):
            print(f"Warning: Incomplete rg data: {data}", file=sys.stderr)
            continue
        
        processed_matches_count +=1
        print(f"\n--- Match in {file_path}:{match_line_1idx} (Highlight: \"{text_to_highlight}\") ---")

        try:
            with open(file_path, 'r', encoding='utf-8', errors='surrogateescape') as f:
                lines_with_newlines = f.readlines()
                f.seek(0)
                file_content_str = f.read()
        except Exception as e:
            print(f"Error reading {file_path}: {e}", file=sys.stderr)
            continue

        lang_type = get_language_type(file_path)
        extracted_block_lines = None
        match_line_0idx = match_line_1idx - 1
        current_func_opt_messages_len = len(OPTIONAL_FEATURE_MESSAGES)

        try:
            if lang_type == "python":
                extracted_block_lines = extract_python_block_ast(lines_with_newlines, match_line_1idx, file_content_str)
            elif lang_type == "brace":
                extracted_block_lines = extract_brace_block(lines_with_newlines, match_line_0idx)
            elif lang_type == "json":
                extracted_block_lines = extract_json_block(lines_with_newlines, match_line_0idx, file_content_str)
            elif lang_type == "yaml":
                extracted_block_lines = extract_yaml_block(lines_with_newlines, match_line_0idx, file_content_str)
            elif lang_type == "xml":
                extracted_block_lines = extract_xml_block(lines_with_newlines, match_line_0idx, file_content_str)
            elif lang_type == "ruby":
                extracted_block_lines = extract_ruby_block(lines_with_newlines, match_line_0idx)
            elif lang_type == "lua":
                extracted_block_lines = extract_lua_block(lines_with_newlines, match_line_0idx)
            # Add other language handlers here
        except Exception as e: # Catch errors from individual extractors
            print(f"Error during {lang_type} block extraction for {file_path}: {e}", file=sys.stderr)
            extracted_block_lines = None # Ensure fallback

        # Store unique optional feature messages
        if len(OPTIONAL_FEATURE_MESSAGES) > current_func_opt_messages_len:
            for msg_idx in range(current_func_opt_messages_len, len(OPTIONAL_FEATURE_MESSAGES)):
                unique_opt_messages.add(OPTIONAL_FEATURE_MESSAGES[msg_idx])


        if extracted_block_lines:
            for line_content in extracted_block_lines:
                line_to_print = line_content.rstrip('\n')
                highlighted_line = highlight_text_in_line(line_to_print, text_to_highlight, highlight_ansi_sequence)
                print(highlighted_line)
            print(f"--- End of block for {file_path}:{match_line_1idx} ---")
        else:
            print(f"Fallback: Context for '{lang_type}' file (or block not found/extractor error).")
            print_context_fallback(lines_with_newlines, match_line_0idx, text_to_highlight,
                                   highlight_ansi_sequence, args.context)

    # Print unique optional feature messages at the end
    if unique_opt_messages:
        print("\n--- Optional Feature Notes ---", file=sys.stderr)
        for msg in sorted(list(unique_opt_messages)):
            print(msg, file=sys.stderr)

    sys.exit(0 if processed_matches_count > 0 or process.returncode == 1 else 1)

if __name__ == "__main__":
    sys.exit(main())
