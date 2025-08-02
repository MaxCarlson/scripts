# rgcodeblock_lib/extractors.py
import re
import ast
import sys

YAML_SUPPORT = False
try: import yaml; YAML_SUPPORT = True
except ImportError: pass
LXML_SUPPORT = False
try: from lxml import etree; LXML_SUPPORT = True
except ImportError: pass
OPTIONAL_LIBRARY_NOTES = set()

def extract_python_block_ast(
    lines_with_newlines: list[str], file_content_str: str,
    target_entity_name: str | None = None, target_line_1idx: int | None = None
) -> tuple[list[str] | None, int, int]:
    try: tree = ast.parse(file_content_str)
    except SyntaxError as e: OPTIONAL_LIBRARY_NOTES.add(f"Python AST: SyntaxError line ~{e.lineno}"); return None, -1, -1
    except Exception as e_parse: OPTIONAL_LIBRARY_NOTES.add(f"Python AST: Parse error: {str(e_parse)[:60]}."); return None, -1, -1
    candidate_nodes_info = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            node_start_line = node.lineno; node_end_line = getattr(node, 'end_lineno', None)
            if node_end_line is None:
                if node.body: last_item = node.body[-1]; node_end_line = getattr(last_item, 'end_lineno', last_item.lineno)
                else: node_end_line = node_start_line
            current_node_matches = False; node_name = getattr(node, 'name', None)
            if target_entity_name and node_name == target_entity_name:
                matches_line = (node_start_line <= target_line_1idx <= node_end_line) if target_line_1idx else True
                if matches_line: current_node_matches = True
            elif target_line_1idx and not target_entity_name:
                if node_start_line <= target_line_1idx <= node_end_line: current_node_matches = True
            if current_node_matches:
                candidate_nodes_info.append({'name': node_name, 'start_line': node_start_line, 'end_line': node_end_line, 'size': node_end_line - node_start_line})
    if not candidate_nodes_info: return None, -1, -1
    valid_candidates = candidate_nodes_info
    if target_entity_name: valid_candidates = [n for n in valid_candidates if n['name'] == target_entity_name]
    if target_line_1idx: valid_candidates = [n for n in valid_candidates if n['start_line'] <= target_line_1idx <= n['end_line']]
    if not valid_candidates: return None, -1, -1
    best_node_info = min(valid_candidates, key=lambda n: (n['size'], -n['start_line']))
    start_0idx = best_node_info['start_line'] - 1; end_0idx = best_node_info['end_line'] - 1
    if not (0 <= start_0idx < len(lines_with_newlines) and 0 <= end_0idx < len(lines_with_newlines) and start_0idx <= end_0idx):
        OPTIONAL_LIBRARY_NOTES.add(f"Python AST: Invalid indices [{start_0idx+1}-{end_0idx+1}] for '{best_node_info.get('name', '<Unknown>')}'.")
        return None, -1, -1
    return lines_with_newlines[start_0idx : end_0idx + 1], start_0idx, end_0idx

def extract_brace_block(lines_with_newlines: list[str], target_line_0idx: int) -> tuple[list[str] | None, int, int]:
    open_b, close_b = '{', '}'; start_idx, balance = -1, 0
    for i in range(target_line_0idx, -1, -1):
        for char_idx in range(len(lines_with_newlines[i]) - 1, -1, -1):
            char = lines_with_newlines[i][char_idx]
            if char == close_b: balance += 1
            elif char == open_b: balance -= 1
            if balance < 0: start_idx = i; break
        if start_idx != -1: break
    if start_idx == -1: return None, -1, -1
    end_idx, balance_fwd, first_found = -1, 0, False
    for i in range(start_idx, len(lines_with_newlines)):
        for char in lines_with_newlines[i]:
            if char == open_b: balance_fwd += 1;
            if i >= start_idx: first_found = True
            elif char == close_b:
                if first_found: balance_fwd -= 1
        if first_found and balance_fwd == 0: end_idx = i; break
    if not first_found: return None, -1, -1
    if end_idx == -1: end_idx = len(lines_with_newlines) - 1
    return lines_with_newlines[start_idx : end_idx + 1], start_idx, end_idx

def extract_json_block(lines_with_newlines: list[str], target_line_0idx: int, file_content_str: str) -> tuple[list[str] | None, int, int]:
    best_block_info = None
    for open_d, close_d in [('{', '}'), ('[', ']')]:
        start_idx, balance_back = -1, 0
        for i in range(target_line_0idx, -1, -1):
            line = lines_with_newlines[i]
            for char_idx in range(len(line) - 1, -1, -1):
                char = line[char_idx]
                if char == close_d: balance_back += 1
                elif char == open_d: balance_back -= 1
                if balance_back < 0: start_idx = i; break
            if start_idx != -1: break
        if start_idx == -1: continue
        end_idx, balance_fwd, first_found = -1, 0, False
        for i in range(start_idx, len(lines_with_newlines)):
            line = lines_with_newlines[i]
            for char_fwd in line:
                if char_fwd == open_d: balance_fwd += 1;
                if i >= start_idx: first_found = True
                elif char_fwd == close_d:
                    if first_found: balance_fwd -= 1
            if first_found and balance_fwd == 0: end_idx = i; break
        if not first_found: continue
        if end_idx == -1: end_idx = len(lines_with_newlines) - 1
        current_block_lines = lines_with_newlines[start_idx : end_idx + 1]
        if best_block_info is None or len(current_block_lines) < len(best_block_info[0]):
            best_block_info = (current_block_lines, start_idx, end_idx)
    return best_block_info if best_block_info else (None, -1, -1)

def extract_yaml_block(lines_with_newlines: list[str], target_line_0idx: int, file_content_str: str) -> tuple[list[str] | None, int, int]:
    if not YAML_SUPPORT: OPTIONAL_LIBRARY_NOTES.add("YAML: PyYAML not found ('pip install PyYAML')."); return None, -1, -1
    try:
        doc_start_lines = [i for i, line_str in enumerate(lines_with_newlines) if line_str.strip() == "---"]
        if not doc_start_lines or doc_start_lines[0] != 0: doc_start_lines.insert(0,0)
        doc_s_idx, doc_e_idx = 0, len(lines_with_newlines) -1; found_containing_doc = False
        for i in range(len(doc_start_lines)):
            s = doc_start_lines[i]; e = doc_start_lines[i+1] - 1 if (i + 1) < len(doc_start_lines) else len(lines_with_newlines) - 1
            if s <= target_line_0idx <= e: doc_s_idx, doc_e_idx = s, e; found_containing_doc = True; break
        if not found_containing_doc and doc_start_lines and target_line_0idx >= doc_start_lines[-1]:
             doc_s_idx = doc_start_lines[-1]; doc_e_idx = len(lines_with_newlines) -1
        doc_content_to_parse = "".join(lines_with_newlines[doc_s_idx : doc_e_idx + 1])
        try: list(yaml.safe_load_all(doc_content_to_parse))
        except yaml.YAMLError as ye: OPTIONAL_LIBRARY_NOTES.add(f"YAML: Doc (lines {doc_s_idx+1}-{doc_e_idx+1}) parse error: {str(ye)[:50]}...")
        return lines_with_newlines[doc_s_idx : doc_e_idx + 1], doc_s_idx, doc_e_idx
    except Exception as e: OPTIONAL_LIBRARY_NOTES.add(f"YAML: Unexpected error: {str(e)[:50]}..."); return None, -1, -1

def extract_xml_block(lines_with_newlines: list[str], target_line_0idx: int, file_content_str: str) -> tuple[list[str] | None, int, int]:
    if not LXML_SUPPORT: OPTIONAL_LIBRARY_NOTES.add("XML: lxml library not found ('pip install lxml')."); return None, -1, -1
    try:
        parser = etree.XMLParser(recover=True, collect_ids=False, strip_cdata=False, resolve_entities=False)
        try: root = etree.fromstring(file_content_str.encode('utf-8'), parser=parser)
        except ValueError:
            if not file_content_str.strip(): return None, -1, -1
            OPTIONAL_LIBRARY_NOTES.add(f"XML: Parse error (ValueError)."); return None, -1, -1
        except etree.XMLSyntaxError as xe_root: OPTIONAL_LIBRARY_NOTES.add(f"XML: Root syntax error: {str(xe_root)[:60]}..."); return None, -1, -1
        best_node_info = None; target_line_1idx = target_line_0idx + 1
        for element in root.xpath('//*[not(self::processing-instruction()) and not(self::comment())]'):
            if not hasattr(element, 'sourceline') or element.sourceline is None: continue
            node_start_line_1idx = element.sourceline; node_end_line_1idx = node_start_line_1idx
            try:
                element_str_bytes = etree.tostring(element, encoding='utf-8', xml_declaration=False); element_str = element_str_bytes.decode('utf-8', errors='surrogateescape')
                num_lines_in_element = element_str.count('\n'); node_end_line_1idx = node_start_line_1idx + num_lines_in_element
            except Exception: # Fallback heuristic
                 if len(element):
                    last_child_with_line = None
                    for child_idx_iter in range(len(element) -1, -1, -1):
                        child_el = element[child_idx_iter]
                        if hasattr(child_el, 'sourceline') and child_el.sourceline is not None: last_child_with_line = child_el; break
                    if last_child_with_line is not None:
                        last_child_end_approx = last_child_with_line.sourceline
                        if last_child_with_line.text and '\n' in last_child_with_line.text: last_child_end_approx += last_child_with_line.text.count('\n')
                        if last_child_with_line.tail and '\n' in last_child_with_line.tail: last_child_end_approx += last_child_with_line.tail.count('\n')
                        node_end_line_1idx = max(node_end_line_1idx, last_child_end_approx)
                 elif element.text and '\n' in element.text: node_end_line_1idx = node_start_line_1idx + element.text.count('\n')
                 if element.tail and '\n' in element.tail: node_end_line_1idx = max(node_end_line_1idx, node_start_line_1idx + element.tail.count('\n'))
            if node_start_line_1idx <= target_line_1idx <= node_end_line_1idx:
                current_size = node_end_line_1idx - node_start_line_1idx
                if best_node_info is None or current_size < best_node_info['size'] or (current_size == best_node_info['size'] and node_start_line_1idx > (best_node_info['start_0idx'] + 1)):
                    best_node_info = {'start_0idx': node_start_line_1idx - 1, 'end_0idx': node_end_line_1idx - 1, 'size': current_size}
        if best_node_info:
            s_idx, e_idx = best_node_info['start_0idx'], best_node_info['end_0idx']
            s_idx = max(0, s_idx); e_idx = min(e_idx, len(lines_with_newlines) - 1)
            if s_idx > e_idx: OPTIONAL_LIBRARY_NOTES.add(f"XML: Invalid block range s={s_idx}, e={e_idx}."); return None, -1, -1
            return lines_with_newlines[s_idx : e_idx + 1], s_idx, e_idx
        return None, -1, -1
    except etree.XMLSyntaxError as xe: OPTIONAL_LIBRARY_NOTES.add(f"XML: File syntax error: {str(xe)[:60]}..."); return None, -1, -1
    except Exception as e: OPTIONAL_LIBRARY_NOTES.add(f"XML: Unexpected error: {str(e)[:60]}..."); return None, -1, -1

def _extract_keyword_pair_block( # <<< Parameter name changed here to target_line_0idx
    lines_with_newlines: list[str], target_line_0idx: int, # <<< CHANGED
    block_starters_regex_str: str, block_ender_regex_str: str,
    target_entity_name: str | None = None
) -> tuple[list[str] | None, int, int]:
    block_starters_re = re.compile(block_starters_regex_str)
    block_ender_re = re.compile(block_ender_regex_str)
    actual_block_start_line_idx = -1; starter_indent = -1; balance = 0
    for i in range(target_line_0idx, -1, -1): # Use target_line_0idx
        original_line = lines_with_newlines[i]; line_s = original_line.lstrip()
        if line_s.startswith(("#", "--")): continue
        is_potential_starter = block_starters_re.match(line_s)
        if block_ender_re.match(line_s): balance += 1
        elif is_potential_starter:
            name_ok = True
            if target_entity_name:
                m_start = is_potential_starter # Already matched
                # Check if name appears after the matched starter keyword part
                # Use original_line for slicing to preserve leading spaces for regex if pattern expects them
                line_after_keyword = original_line[m_start.end():]
                if not re.search(r"^\s*" + re.escape(target_entity_name) + r"\b", line_after_keyword): # Name should be next
                    name_ok = False
            if name_ok:
                balance -=1
                if balance < 0:
                    actual_block_start_line_idx = i
                    starter_indent = len(re.match(r"^(\s*)", original_line).group(1) or "")
                    break
    if actual_block_start_line_idx == -1: return None, -1, -1

    block_end_line_idx = -1; balance = 0
    for i in range(actual_block_start_line_idx, len(lines_with_newlines)):
        original_line = lines_with_newlines[i]; line_s = original_line.lstrip()
        if line_s.startswith(("#", "--")): continue
        current_indent = len(re.match(r"^(\s*)", original_line).group(1) or "")
        is_starter = block_starters_re.match(line_s); is_ender = block_ender_re.match(line_s)
        if is_starter:
            if i == actual_block_start_line_idx or current_indent > starter_indent: balance +=1
        elif is_ender:
            if current_indent >= starter_indent: balance -=1
        if balance == 0 and i >= actual_block_start_line_idx and is_ender and current_indent == starter_indent:
            block_end_line_idx = i; break
    if block_end_line_idx == -1:
        if balance >= 1 and actual_block_start_line_idx != -1: block_end_line_idx = len(lines_with_newlines) - 1
        else: return None, -1, -1
    return lines_with_newlines[actual_block_start_line_idx : block_end_line_idx + 1], actual_block_start_line_idx, block_end_line_idx

# Make sure these functions call _extract_keyword_pair_block with the correct parameter name
def extract_ruby_block(lines_with_newlines: list[str], target_line_0idx: int, target_entity_name: str | None = None) -> tuple[list[str] | None, int, int]:
    starters = r"^\s*(def|class|module|if|unless|case|while|until|for|begin)\b"
    ender = r"^\s*end\b"
    return _extract_keyword_pair_block(lines_with_newlines, target_line_0idx, starters, ender, target_entity_name)

def extract_lua_block(lines_with_newlines: list[str], target_line_0idx: int, target_entity_name: str | None = None) -> tuple[list[str] | None, int, int]:
    starters = r"^\s*(function|if|while|for|repeat)\b"
    ender = r"^\s*(end|until)\b"
    return _extract_keyword_pair_block(lines_with_newlines, target_line_0idx, starters, ender, target_entity_name)
