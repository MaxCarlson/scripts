# rgcodeblock_lib/extractors.py
import re
import ast
import sys # For sys.stderr if any direct print is needed (should be rare in lib)

# --- Optional Dependency Handling & Messages ---
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

# This set will store notes about optional libraries if they are attempted to be used but not found,
# or if there are parsing issues that are non-fatal for a given extractor.
OPTIONAL_LIBRARY_NOTES = set()

# --- Extraction Functions ---
# Standard return for extractors: (block_lines: list[str] | None, start_line_0idx: int, end_line_0idx: int)
# If block not found or error, return (None, -1, -1)

def extract_python_block_ast(
    lines_with_newlines: list[str],
    file_content_str: str,
    target_entity_name: str | None = None,
    target_line_1idx: int | None = None
) -> tuple[list[str] | None, int, int]:
    """Extracts Python block using AST, finding by name and/or line."""
    try:
        tree = ast.parse(file_content_str)
    except SyntaxError as e:
        OPTIONAL_LIBRARY_NOTES.add(f"Python AST: SyntaxError in file (line ~{e.lineno}), cannot parse.")
        return None, -1, -1
    except Exception as e_parse: # Catch other potential parsing errors
        OPTIONAL_LIBRARY_NOTES.add(f"Python AST: Error parsing file: {str(e_parse)[:60]}.")
        return None, -1, -1


    candidate_nodes_info = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            node_start_line = node.lineno # 1-indexed
            node_end_line = getattr(node, 'end_lineno', None) # Python 3.8+
            
            if node_end_line is None: # Fallback for older Python or if end_lineno isn't there
                if node.body:
                    # Last item in body; could be an expression or a statement
                    last_item_in_body = node.body[-1]
                    node_end_line = getattr(last_item_in_body, 'end_lineno', last_item_in_body.lineno)
                else: # Empty body, e.g., "def foo(): pass" or "class A: ..."
                    node_end_line = node_start_line 
                    # For "class A:", end_lineno might be the same as lineno.
                    # This can be refined if needed by checking ast.unparse if available.
            
            # Check if this node matches the target criteria
            current_node_matches = False
            if target_entity_name and hasattr(node, 'name') and node.name == target_entity_name:
                if target_line_1idx: # If line also specified, name must span this line
                    if node_start_line <= target_line_1idx <= node_end_line:
                        current_node_matches = True
                else: # Name match is sufficient
                    current_node_matches = True
            elif target_line_1idx and not target_entity_name: # Only line specified
                if node_start_line <= target_line_1idx <= node_end_line:
                    current_node_matches = True
            
            if current_node_matches:
                candidate_nodes_info.append({
                    'name': getattr(node, 'name', '<node_without_name>'),
                    'start_line': node_start_line,
                    'end_line': node_end_line,
                    'size': node_end_line - node_start_line # For preferring smaller/inner blocks
                })
    
    if not candidate_nodes_info:
        return None, -1, -1

    # Select the best candidate:
    # If multiple candidates, prefer the "innermost" one that matches criteria.
    # Innermost can be defined as largest start_line or smallest size.
    # Largest start_line is usually a good proxy for innermost when target_line_1idx is given.
    # If only target_entity_name, we might get multiple (e.g. nested func with same name as outer).
    # For now, if name is primary, take first match. If line is primary, take innermost at line.
    
    if target_line_1idx: # Prefer innermost block containing the target_line_1idx
        # Filter candidates to only those spanning the target_line_1idx
        candidates_spanning_line = [
            n for n in candidate_nodes_info if n['start_line'] <= target_line_1idx <= n['end_line']
        ]
        if not candidates_spanning_line: return None, -1, -1
        # If name also specified, further filter by name
        if target_entity_name:
            named_candidates_spanning_line = [n for n in candidates_spanning_line if n['name'] == target_entity_name]
            if not named_candidates_spanning_line: return None, -1, -1 # Name not found at that line
            best_node_info = min(named_candidates_spanning_line, key=lambda n: (n['size'], -n['start_line'])) # Innermost by size, then latest start
        else: # No name, just innermost by line
            best_node_info = min(candidates_spanning_line, key=lambda n: (n['size'], -n['start_line']))
    elif target_entity_name: # Only name specified, no line hint
        # Take the first occurrence or potentially the smallest one if multiple.
        # For func_replacer, usually the first encountered definition is desired.
        # AST walk order is typically top-down.
        candidates_with_name = [n for n in candidate_nodes_info if n['name'] == target_entity_name]
        if not candidates_with_name: return None, -1, -1
        best_node_info = candidates_with_name[0] # Take first one found by ast.walk
    else: # Should not happen: either name or line must be provided for meaningful search
        return None, -1, -1
        
    start_0idx = best_node_info['start_line'] - 1
    end_0idx = best_node_info['end_line'] - 1 # AST end_lineno is inclusive
    
    if not (0 <= start_0idx < len(lines_with_newlines) and 0 <= end_0idx < len(lines_with_newlines) and start_0idx <= end_0idx):
        OPTIONAL_LIBRARY_NOTES.add(f"Python AST: Calculated node line indices [{start_0idx+1}-{end_0idx+1}] for '{best_node_info['name']}' out of bounds.")
        return None, -1, -1
        
    return lines_with_newlines[start_0idx : end_0idx + 1], start_0idx, end_0idx


def extract_brace_block(
    lines_with_newlines: list[str],
    target_line_0idx: int,
    # target_entity_name: str | None = None # For func_replacer, name check would be outside this basic heuristic
) -> tuple[list[str] | None, int, int]:
    """Extracts a brace-enclosed block containing target_line_0idx."""
    open_b, close_b = '{', '}'
    
    enclosing_block_start_line_idx = -1
    balance = 0 # R->L scan: } increments, { decrements. Target is balance < 0 for opening {
    for i in range(target_line_0idx, -1, -1):
        line_content = lines_with_newlines[i]
        # Ignore braces in comments or strings (simple check, not a full parser)
        # This requires a more complex line pre-processing if we want to be robust here.
        # For now, assume braces are structural.
        for char_idx in range(len(line_content) - 1, -1, -1):
            char = line_content[char_idx]
            if char == close_b: balance += 1
            elif char == open_b:
                balance -= 1
                if balance < 0:
                    enclosing_block_start_line_idx = i; break
        if enclosing_block_start_line_idx != -1: break
    if enclosing_block_start_line_idx == -1: return None, -1, -1

    block_end_line_idx = -1
    block_balance = 0 # L->R scan: { increments, } decrements. Target is balance == 0.
    first_brace_of_this_block_found = False
    for i in range(enclosing_block_start_line_idx, len(lines_with_newlines)):
        line_content = lines_with_newlines[i]
        for char_idx in range(len(line_content)):
            char = line_content[char_idx]
            if char == open_b:
                block_balance += 1
                # Ensure we start counting balance from the identified block's opening brace onwards
                if i >= enclosing_block_start_line_idx: first_brace_of_this_block_found = True
            elif char == close_b:
                if first_brace_of_this_block_found: block_balance -= 1
        
        if first_brace_of_this_block_found and block_balance == 0:
            block_end_line_idx = i; break
            
    if not first_brace_of_this_block_found: return None, -1, -1 # Should not happen if start_idx was valid
    if block_end_line_idx == -1: # EOF reached before block closed
        # OPTIONAL_LIBRARY_NOTES.add("Brace: Reached EOF with unbalanced braces. Taking block to end of file.")
        block_end_line_idx = len(lines_with_newlines) - 1
    
    return lines_with_newlines[enclosing_block_start_line_idx : block_end_line_idx + 1], \
           enclosing_block_start_line_idx, block_end_line_idx


def extract_json_block(
    lines_with_newlines: list[str],
    target_line_0idx: int,
    file_content_str: str
) -> tuple[list[str] | None, int, int]:
    """Heuristic for smallest JSON object/array enclosing target_line_0idx."""
    # Optional: try full parsing for validation early on
    # try:
    #     json.loads(file_content_str)
    # except json.JSONDecodeError as e:
    #     OPTIONAL_LIBRARY_NOTES.add(f"JSON: File content is not valid JSON (line {e.lineno} col {e.colno}). Heuristic may be inaccurate.")

    best_block_info = None # Stores (block_lines, start_idx, end_idx)

    for open_d, close_d in [('{', '}'), ('[', ']')]:
        # Find enclosing start delimiter
        start_idx, balance = -1, 0
        for i in range(target_line_0idx, -1, -1):
            line = lines_with_newlines[i]
            for char_idx in range(len(line) - 1, -1, -1):
                char = line[char_idx]
                if char == close_d: balance += 1
                elif char == open_d:
                    balance -= 1
                    if balance < 0: start_idx = i; break
            if start_idx != -1: break
        if start_idx == -1: continue # No suitable opening delimiter of this type found

        # Find matching end delimiter
        end_idx, balance, first_found = -1, 0, False
        for i in range(start_idx, len(lines_with_newlines)):
            line = lines_with_newlines[i]
            for char_fwd in line: # Renamed to avoid conflict
                if char_fwd == open_d: balance += 1; first_found = True
                elif char_fwd == close_d:
                    if first_found: balance -= 1
            if first_found and balance == 0: end_idx = i; break
        if not first_found: continue # Should be rare if start_idx was found
        if end_idx == -1: end_idx = len(lines_with_newlines) - 1 # EOF, unbalanced
        
        current_block_lines = lines_with_newlines[start_idx : end_idx + 1]
        if best_block_info is None or len(current_block_lines) < len(best_block_info[0]):
            best_block_info = (current_block_lines, start_idx, end_idx)
            
    return best_block_info if best_block_info else (None, -1, -1)


def extract_yaml_block(
    lines_with_newlines: list[str],
    target_line_0idx: int,
    file_content_str: str # Used for parsing attempt
) -> tuple[list[str] | None, int, int]:
    """Extracts YAML document containing target_line_0idx using PyYAML (if available)."""
    if not YAML_SUPPORT:
        OPTIONAL_LIBRARY_NOTES.add("YAML: PyYAML library not found. Install with 'pip install PyYAML'.")
        return None, -1, -1
    try:
        # Heuristic: find the YAML document (separated by '---' or start of file)
        # that contains the target_line_0idx.
        doc_start_lines = [i for i, line_str in enumerate(lines_with_newlines) if line_str.strip() == "---"]
        
        # Add implicit document start at line 0 if no '---' at the beginning
        if not doc_start_lines or doc_start_lines[0] != 0:
            doc_start_lines.insert(0,0)

        doc_s_idx, doc_e_idx = 0, len(lines_with_newlines) -1 # Default to whole file
        found_containing_doc = False
        for i in range(len(doc_start_lines)):
            s = doc_start_lines[i]
            e = doc_start_lines[i+1] - 1 if (i + 1) < len(doc_start_lines) else len(lines_with_newlines) - 1
            if s <= target_line_0idx <= e:
                doc_s_idx, doc_e_idx = s, e
                found_containing_doc = True
                break
        
        # If target_line_0idx is after the last '---', it belongs to the last document
        if not found_containing_doc and doc_start_lines and target_line_0idx >= doc_start_lines[-1]:
             doc_s_idx = doc_start_lines[-1]
             doc_e_idx = len(lines_with_newlines) -1

        # Attempt to parse just this document section to provide a note if it's invalid
        doc_content_to_parse = "".join(lines_with_newlines[doc_s_idx : doc_e_idx + 1])
        try:
            # Test parsability; actual parsed data not used for block boundaries here
            list(yaml.safe_load_all(doc_content_to_parse)) 
        except yaml.YAMLError as ye:
            OPTIONAL_LIBRARY_NOTES.add(f"YAML: Doc (lines {doc_s_idx+1}-{doc_e_idx+1}) parse error: {str(ye)[:50]}...")
            # Still return the heuristically determined block
        
        return lines_with_newlines[doc_s_idx : doc_e_idx + 1], doc_s_idx, doc_e_idx
    except Exception as e: # Catch any other unexpected errors
        OPTIONAL_LIBRARY_NOTES.add(f"YAML: Unexpected error: {str(e)[:50]}...")
        return None, -1, -1


def extract_xml_block(
    lines_with_newlines: list[str],
    target_line_0idx: int,
    file_content_str: str
) -> tuple[list[str] | None, int, int]:
    """Extracts smallest XML element enclosing target_line_0idx using lxml (if available)."""
    if not LXML_SUPPORT:
        OPTIONAL_LIBRARY_NOTES.add("XML: lxml library not found. Install with 'pip install lxml'.")
        return None, -1, -1
    try:
        parser = etree.XMLParser(recover=True, collect_ids=False, strip_cdata=False, resolve_entities=False)
        try:
            root = etree.fromstring(file_content_str.encode('utf-8'), parser=parser)
        except ValueError: # E.g. empty string
            if not file_content_str.strip(): return None, -1, -1
            OPTIONAL_LIBRARY_NOTES.add(f"XML: Parse error (ValueError, possibly empty/malformed).")
            return None, -1, -1
        except etree.XMLSyntaxError as xe_root: # Catch syntax error at root parsing
             OPTIONAL_LIBRARY_NOTES.add(f"XML: Root syntax error: {str(xe_root)[:60]}...")
             return None, -1, -1


        best_node_info = None # Stores {'start_0idx': s, 'end_0idx': e, 'size': size}
        target_line_1idx = target_line_0idx + 1

        for element in root.xpath('//*[not(self::processing-instruction()) and not(self::comment())]'):
            if not hasattr(element, 'sourceline') or element.sourceline is None: continue

            node_start_line_1idx = element.sourceline
            node_end_line_1idx = node_start_line_1idx # Default end line
            
            # Try to get a more accurate end line
            try:
                # Serialize the element to count its lines. This is most accurate.
                # Use a basic encoding that won't fail easily.
                element_str_bytes = etree.tostring(element, encoding='utf-8', xml_declaration=False, pretty_print=False)
                element_str = element_str_bytes.decode('utf-8', errors='surrogateescape')
                num_lines_in_element = element_str.count('\n')
                node_end_line_1idx = node_start_line_1idx + num_lines_in_element
            except Exception:
                # Fallback heuristic if tostring fails (e.g. very malformed sub-element)
                # Check children and text, this is less reliable.
                if len(element): # Has children
                    last_child_with_line = None
                    for child_idx_iter in range(len(element) -1, -1, -1): # Iterate children
                        child_el = element[child_idx_iter]
                        if hasattr(child_el, 'sourceline') and child_el.sourceline is not None:
                            # This is complex: need end line of the last child recursively
                            # For simplicity, just take last child's start + its text lines
                            last_child_end_approx = child_el.sourceline
                            if child_el.text and '\n' in child_el.text:
                                last_child_end_approx += child_el.text.count('\n')
                            if child_el.tail and '\n' in child_el.tail: # Tail of last child
                                last_child_end_approx += child_el.tail.count('\n')
                            node_end_line_1idx = max(node_end_line_1idx, last_child_end_approx)
                            break # Found a last child with sourceline
                elif element.text and '\n' in element.text:
                     node_end_line_1idx = node_start_line_1idx + element.text.count('\n')
                # Also consider tail of the current element
                if element.tail and '\n' in element.tail:
                    node_end_line_1idx = max(node_end_line_1idx, node_start_line_1idx + element.tail.count('\n'))


            if node_start_line_1idx <= target_line_1idx <= node_end_line_1idx:
                current_size = node_end_line_1idx - node_start_line_1idx
                if best_node_info is None or current_size < best_node_info['size'] or \
                   (current_size == best_node_info['size'] and node_start_line_1idx > (best_node_info['start_0idx'] + 1)): # Prefer inner
                    best_node_info = {
                        'start_0idx': node_start_line_1idx - 1,
                        'end_0idx': node_end_line_1idx -1, # Assuming end_line from count is inclusive
                        'size': current_size
                    }
        
        if best_node_info:
            s_idx, e_idx = best_node_info['start_0idx'], best_node_info['end_0idx']
            s_idx = max(0, s_idx) 
            e_idx = min(e_idx, len(lines_with_newlines) - 1) 
            if s_idx > e_idx : 
                 OPTIONAL_LIBRARY_NOTES.add(f"XML: Calculated invalid block range s_idx={s_idx}, e_idx={e_idx}.")
                 return None, -1, -1
            return lines_with_newlines[s_idx : e_idx + 1], s_idx, e_idx
        return None, -1, -1
    except etree.XMLSyntaxError as xe: OPTIONAL_LIBRARY_NOTES.add(f"XML: File syntax error: {str(xe)[:60]}..."); return None, -1, -1
    except Exception as e: OPTIONAL_LIBRARY_NOTES.add(f"XML: Unexpected error: {str(e)[:60]}..."); return None, -1, -1


def _extract_keyword_pair_block(
    lines_with_newlines: list[str],
    target_line_0idx: int,
    block_starters_regex_str: str,
    block_ender_regex_str: str,
    target_entity_name: str | None = None
) -> tuple[list[str] | None, int, int]:
    """Helper for keyword-paired blocks (Ruby, Lua)."""
    
    block_starters_re = re.compile(block_starters_regex_str)
    block_ender_re = re.compile(block_ender_regex_str)

    actual_block_start_line_idx = -1
    starter_indent = -1
    balance = 0 # R->L scan: ender increments, starter decrements. Target balance < 0.

    for i in range(target_line_0idx, -1, -1):
        line_content_stripped = lines_with_newlines[i].lstrip() # Check keyword on lstripped line
        original_line_for_indent = lines_with_newlines[i]

        # Basic comment skipping (lines starting with # or -- for Lua/SQL)
        # This should be language specific if made more robust.
        if line_content_stripped.startswith("#") or line_content_stripped.startswith("--"):
            continue

        if block_ender_re.match(line_content_stripped):
            balance += 1
        elif block_starters_re.match(line_content_stripped):
            name_match = True # Assume true if no target_entity_name or if name pattern is in starter_regex
            if target_entity_name:
                # A simple check: does the line contain the name *after* the starter keyword?
                # More robust: starter_regex should have a capturing group for the name.
                # For now, a simple string search on the line containing the starter keyword.
                # This might be too broad if target_entity_name is a common word.
                m = block_starters_re.match(line_content_stripped)
                if m: # Check if the line actually starts with a starter keyword
                    # Heuristic: check if name appears after the matched starter part
                    if not re.search(r"\b" + re.escape(target_entity_name) + r"\b", line_content_stripped[m.end():]):
                         # Or, if the starter regex itself captures the name, check that group
                         # This requires starter_regex to be designed for it.
                         # Example: r"^\s*(def)\s+([A-Za-z_][A-Za-z0-9_]*)" where group 2 is name.
                         # For the generic _extract_keyword_pair_block, this is hard.
                         # The line match is simpler for now.
                         pass # Keep name_match true and let balance decide, or set name_match=False

            if name_match: # If name check passes or no name to check
                balance -=1
                if balance < 0: 
                    actual_block_start_line_idx = i
                    indent_match_obj = re.match(r"^(\s*)", original_line_for_indent)
                    starter_indent = len(indent_match_obj.group(1)) if indent_match_obj else 0
                    break 
    
    if actual_block_start_line_idx == -1:
        return None, -1, -1

    # Phase 2: Find the matching 'end' from actual_block_start_line_idx
    block_end_line_idx = -1
    balance = 0 # Reset balance for L->R scan. Starter increments, ender decrements.
    
    for i in range(actual_block_start_line_idx, len(lines_with_newlines)):
        line_content_stripped = lines_with_newlines[i].lstrip()
        original_line_for_indent = lines_with_newlines[i]

        if line_content_stripped.startswith("#") or line_content_stripped.startswith("--"):
            continue
        
        # More careful balance: only increment for starters at same or less indent than our main starter?
        # This helps with nested functions. But can be tricky.
        # For now, simple balance:
        if block_starters_re.match(line_content_stripped):
            balance +=1
        elif block_ender_re.match(line_content_stripped):
            balance -=1
        
        if balance == 0 and i >= actual_block_start_line_idx: # Must have seen at least one starter
             indent_match_obj = re.match(r"^(\s*)", original_line_for_indent)
             current_indent = len(indent_match_obj.group(1)) if indent_match_obj else 0
             # The 'end' keyword should typically be at the same indentation level as its starter
             if block_ender_re.match(line_content_stripped) and current_indent == starter_indent:
                block_end_line_idx = i
                break
            # Handle case where 'end' might be less indented (e.g. syntax error, but we try)
            # Or if no matching indent 'end' found, the balance might still hit 0 earlier.
            # The indent check is a strong heuristic for well-formed code.
    
    if block_end_line_idx == -1: # If no perfectly indented 'end' found
        # Fallback: if balance is 1 (one starter open) and we started a block, take to EOF.
        # Or, if balance became 0 without matching indent, that might be the end.
        # This part can be made more lenient if needed.
        if balance >= 1 and actual_block_start_line_idx != -1: 
             # If still open, consider it to EOF. This is risky if code is malformed.
             # OPTIONAL_LIBRARY_NOTES.add(f"Keyword-Pair: Reached EOF with unbalanced block starting line {actual_block_start_line_idx+1}.")
             block_end_line_idx = len(lines_with_newlines) - 1 
        else: # Balance is 0 or less, but no matching indent end.
              # This implies a syntax issue or a more complex structure not handled.
            return None, -1, -1

    return lines_with_newlines[actual_block_start_line_idx : block_end_line_idx + 1], \
           actual_block_start_line_idx, block_end_line_idx


def extract_ruby_block(lines_with_newlines: list[str], target_line_0idx: int, target_entity_name: str | None = None) -> tuple[list[str] | None, int, int]:
    # `do` is often paired with iterators (e.g. .each do |x|) or for `while`/`until` conditions
    # Handling `do...end` as general blocks is complex because `do` can also be part of a single line.
    # This regex focuses on typical multi-line structural blocks.
    starters = r"^\s*(def|class|module|if|unless|case|while|until|for|begin)\b"
    ender = r"^\s*end\b"
    return _extract_keyword_pair_block(lines_with_newlines, target_line_0idx, starters, ender, target_entity_name)

def extract_lua_block(lines_with_newlines: list[str], target_line_0idx: int, target_entity_name: str | None = None) -> tuple[list[str] | None, int, int]:
    # `repeat ... until condition` - `until` is the ender, but condition can be on same line.
    # `if ... then ... elseif ... then ... else ... end`
    # This simplified version handles common `keyword ... end` blocks.
    starters = r"^\s*(function|if|while|for|repeat)\b" 
    ender = r"^\s*(end|until)\b" # `until` specifically pairs with `repeat`
    return _extract_keyword_pair_block(lines_with_newlines, target_line_0idx, starters, ender, target_entity_name)
