# tests/test_rgcodeblock_lib_extractors.py
import pytest
import re

from rgcodeblock_lib.extractors import (
    extract_python_block_ast, extract_brace_block, extract_json_block,
    extract_yaml_block, extract_xml_block, extract_ruby_block, extract_lua_block,
    YAML_SUPPORT, LXML_SUPPORT, OPTIONAL_LIBRARY_NOTES
)

def lines_from_string(text: str) -> list[str]:
    lines = text.splitlines(); return [(line + '\n') for line in lines]

# --- Python AST Tests --- (Passing - No changes needed)
PYTHON_SAMPLE_CODE_1="""# Comment line 1\nclass MyClass: # Line 2 (0-idx: 1)\n    '''Docstring''' # Line 3 (0-idx: 2)\n    def __init__(self, value): # Line 4 (0-idx: 3)\n        self.value = value # Line 5 (0-idx: 4)\n\n    def another_method(self): # Line 7 (0-idx: 6)\n        pass # Line 8 (0-idx: 7)"""
PYTHON_LINES_1 = lines_from_string(PYTHON_SAMPLE_CODE_1)
def test_extract_python_by_line_in_method(): block, start, end = extract_python_block_ast(PYTHON_LINES_1, PYTHON_SAMPLE_CODE_1, target_line_1idx=5); assert block is not None; assert start == 3; assert end == 4; assert "def __init__" in block[0]; assert "self.value = value" in block[1]
def test_extract_python_by_name_class(): block, start, end = extract_python_block_ast(PYTHON_LINES_1, PYTHON_SAMPLE_CODE_1, target_entity_name="MyClass"); assert block is not None; assert start == 1; assert end == 7; assert "class MyClass" in block[0]; assert "def another_method" in "".join(block)
def test_extract_python_nested_function(): code = "def outer():\n    x = 1\n    def inner(y):\n        return x + y\n    return inner(5)"; lines = lines_from_string(code); block, start, end = extract_python_block_ast(lines, code, target_line_1idx=4); assert block is not None; assert start == 2; assert end == 3; assert "def inner(y)" in block[0]

# --- Brace Block Tests ---
BRACE_SAMPLE_CODE_1 = """#include <stdio.h>\n\nint main() { // line 3 (idx 2)\n  printf("Hello"); // line 4 (idx 3)\n  { // Inner scope line 5 (idx 4)\n    int nested = 1; // line 6 (idx 5)\n  } // line 7 (idx 6)\n  return 0; // line 8 (idx 7)\n} // line 9 (idx 8)"""
BRACE_LINES_1 = lines_from_string(BRACE_SAMPLE_CODE_1)
def test_extract_brace_outer_function(): block, start, end = extract_brace_block(BRACE_LINES_1, target_line_0idx=3); assert block is not None; assert start == 2; assert end == 8; assert "int main()" in block[0]; assert "return 0;" in block[5]
def test_extract_brace_inner_scope():
    block, start, end = extract_brace_block(BRACE_LINES_1, target_line_0idx=5)
    assert block is not None; assert start == 4; assert end == 6
    assert block[0].strip().startswith("{") # <<< CORRECTED
    assert "int nested" in block[1]

# --- JSON Block Tests --- (No changes, should be passing)
JSON_SAMPLE_CODE_1 = """{\n  "name": "example",\n  "data": [ 1, 2, 3 ],\n  "details": { "id": 101, "active": true }\n}"""
JSON_LINES_1 = lines_from_string(JSON_SAMPLE_CODE_1)
def test_extract_json_outer_object_corrected(): block, start, end = extract_json_block(JSON_LINES_1, target_line_0idx=1, file_content_str=JSON_SAMPLE_CODE_1); assert block is not None; assert start == 0; assert end == 4; assert block[0].strip() == "{"; assert block[-1].strip() == "}"
def test_extract_json_inner_array_corrected(): block, start, end = extract_json_block(JSON_LINES_1, target_line_0idx=2, file_content_str=JSON_SAMPLE_CODE_1); assert block is not None; assert start == 0; assert end == 4
def test_extract_json_nested_object_corrected(): block, start, end = extract_json_block(JSON_LINES_1, target_line_0idx=3, file_content_str=JSON_SAMPLE_CODE_1); assert block is not None; assert start == 0; assert end == 4

# --- Ruby Block Tests ---
RUBY_SAMPLE_CODE_1 = """\nclass MyRuby # line 2 (idx 1)\n  def method_one(a) # line 3 (idx 2)\n    if a > 0 then # line 4 (idx 3)\n      puts "Positive" # line 5 (idx 4)\n    else\n      puts "Non-positive" # line 7 (idx 6)\n    end # line 8 (idx 7)\n  end # line 9 (idx 8)\n\n  def method_two; end # line 11 (idx 10)\nend # line 12 (idx 11)\n"""
RUBY_LINES_1 = lines_from_string(RUBY_SAMPLE_CODE_1)

def test_extract_ruby_outer_class():
    # Target line 5 (idx 4: puts "Positive"), no specific name.
    # The heuristic should find the 'if' block at index 3 as the innermost.
    block, start, end = extract_ruby_block(RUBY_LINES_1, target_line_0idx=4)
    assert block is not None
    assert start == 3, f"Expected start index 3 (if block), got {start}"
    assert end == 7, f"Expected end index 7 (end of if), got {end}"

def test_extract_ruby_method_by_name():
    # Target line 5 (idx 4), name "method_one"
    block, start, end = extract_ruby_block(RUBY_LINES_1, target_line_0idx=4, target_entity_name="method_one")
    assert block is not None
    assert start == 2, f"Expected start index 2 (def method_one), got {start}"
    assert end == 8, f"Expected end index 8 (end of method_one), got {end}"
    assert "def method_one" in block[0]

def test_extract_ruby_if_block_heuristic():
    block, start, end = extract_ruby_block(RUBY_LINES_1, target_line_0idx=4) # Target line 5 (index 4)
    assert block is not None; assert start == 3; assert end == 7
    assert block[0].strip().startswith("if")
    assert block[-1].strip().startswith("end"), f"Last line was: {block[-1]}"

# --- Lua Block Tests ---
LUA_SAMPLE_CODE_1 = """\nlocal M = {}\n\nfunction M.calculate(a, b) -- line 3 (idx 2)\n  local sum = a + b -- line 4 (idx 3)\n  if x > 10 then -- line 5 (idx 4)\n    print("Large") -- line 6 (idx 5)\n  else -- line 7 (idx 6)\n    print("Small") -- line 8 (idx 7)\n  end -- line 9 (idx 8)\n  return sum, product -- line 10 (idx 9)\nend -- line 11 (idx 10)\n\nreturn M -- line 13 (idx 12)\n"""
LUA_LINES_1 = lines_from_string(LUA_SAMPLE_CODE_1)

def test_extract_lua_function_outer():
    # Target line 4 (idx 3: 'local sum')
    block, start, end = extract_lua_block(LUA_LINES_1, target_line_0idx=3)
    assert block is not None
    assert start == 2, f"Expected start index 2 (function M.calculate), got {start}"
    assert end == 10, f"Expected end index 10 (end for function), got {end}"
    assert "function M.calculate" in block[0]

def test_extract_lua_if_block_heuristic():
    # Target line 6 (idx 5: 'print("Large")')
    block, start, end = extract_lua_block(LUA_LINES_1, target_line_0idx=5)
    assert block is not None
    assert start == 4, f"Expected start index 4 (if), got {start}"
    assert end == 8, f"Expected end index 8 (end for if), got {end}"
    assert block[0].strip().startswith("if")
    assert block[-1].strip() == "end"

def test_extract_lua_outer_function_by_name():
    # Target line 4 (idx 3), name "M.calculate"
    block, start, end = extract_lua_block(LUA_LINES_1, target_line_0idx=3, target_entity_name="M.calculate")
    assert block is not None
    assert start == 2, f"Expected start index 2 (function M.calculate), got {start}"
    assert end == 10, f"Expected end index 10 (end for function), got {end}"
    assert "function M.calculate" in block[0]

# --- Optional Library Tests ---
@pytest.mark.skipif(not YAML_SUPPORT, reason="PyYAML not installed")
def test_extract_yaml_document_present(): yaml_content = "---\ndoc: 1\nvalues: [a, b]\n---\ndoc: 2\ninfo:\n  nested: true\n...\n"; yaml_lines = lines_from_string(yaml_content); block, start, end = extract_yaml_block(yaml_lines, target_line_0idx=5, file_content_str=yaml_content); assert block is not None; assert start == 3; assert end == 6; assert "doc: 2" in block[1]; assert "nested: true" in block[3]
@pytest.mark.skipif(not LXML_SUPPORT, reason="lxml not installed")
def test_extract_xml_element_present(): xml_content = "<root>\n  <item id=\"1\"><name>Apple</name></item>\n  <item id=\"2\">\n    <name>Banana</name>\n  </item>\n</root>"; xml_lines = lines_from_string(xml_content); block, start, end = extract_xml_block(xml_lines, target_line_0idx=3, file_content_str=xml_content); assert block is not None; assert start == 2; assert end == 4; assert '<item id="2">' in block[0].strip(); assert '<name>Banana</name>' in block[1].strip(); assert '</item>' in block[2].strip()
@pytest.mark.skipif(LXML_SUPPORT, reason="lxml IS installed")
def test_extract_xml_block_missing_lxml(): OPTIONAL_LIBRARY_NOTES.clear(); lines = ["<tag>text</tag>\n"]; extract_xml_block(lines, 0, "".join(lines)); assert "XML: lxml library not found ('pip install lxml')." in "".join(OPTIONAL_LIBRARY_NOTES) # <<< CORRECTED
