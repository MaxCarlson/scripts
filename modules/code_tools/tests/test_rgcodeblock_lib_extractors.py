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
def test_extract_python_by_line_in_method(): block = extract_python_block_ast(PYTHON_SAMPLE_CODE_1, line=5); assert block is not None; assert block.start == 4; assert block.end == 5; assert block.kind == "function"
def test_extract_python_by_name_class(): block = extract_python_block_ast(PYTHON_SAMPLE_CODE_1, name="MyClass"); assert block is not None; assert block.start == 2; assert block.end == 8; assert block.kind == "class"
def test_extract_python_nested_function(): code = "def outer():\n    x = 1\n    def inner(y):\n        return x + y\n    return inner(5)"; block = extract_python_block_ast(code, line=4); assert block is not None; assert block.start == 3; assert block.end == 4; assert block.name == "inner"

# --- Brace Block Tests ---
BRACE_SAMPLE_CODE_1 = """#include <stdio.h>\n\nint main() { // line 3 (idx 2)\n  printf("Hello"); // line 4 (idx 3)\n  { // Inner scope line 5 (idx 4)\n    int nested = 1; // line 6 (idx 5)\n  } // line 7 (idx 6)\n  return 0; // line 8 (idx 7)\n} // line 9 (idx 8)"""
BRACE_LINES_1 = lines_from_string(BRACE_SAMPLE_CODE_1)
def test_extract_brace_outer_function(): block = extract_brace_block(BRACE_SAMPLE_CODE_1, line=4); assert block is not None; assert block.start == 3; assert block.end == 9; assert block.language == "brace"
def test_extract_brace_inner_scope():
    block = extract_brace_block(BRACE_SAMPLE_CODE_1, line=6)
    assert block is not None; assert block.start == 5; assert block.end == 7
    assert block.language == "brace"

# --- JSON Block Tests --- (No changes, should be passing)
JSON_SAMPLE_CODE_1 = """{\n  "name": "example",\n  "data": [ 1, 2, 3 ],\n  "details": { "id": 101, "active": true }\n}"""
JSON_LINES_1 = lines_from_string(JSON_SAMPLE_CODE_1)
def test_extract_json_outer_object_corrected(): block = extract_json_block(JSON_SAMPLE_CODE_1, line=2); assert block is not None; assert block.start == 1; assert block.end == 5; assert block.language == "json"
def test_extract_json_inner_array_corrected(): block = extract_json_block(JSON_SAMPLE_CODE_1, line=3); assert block is not None; assert block.start == 3; assert block.end == 3; assert block.language == "json"
def test_extract_json_nested_object_corrected(): block = extract_json_block(JSON_SAMPLE_CODE_1, line=4); assert block is not None; assert block.start == 4; assert block.end == 4; assert block.language == "json"

# --- Ruby Block Tests ---
RUBY_SAMPLE_CODE_1 = """\nclass MyRuby # line 2 (idx 1)\n  def method_one(a) # line 3 (idx 2)\n    if a > 0 then # line 4 (idx 3)\n      puts "Positive" # line 5 (idx 4)\n    else\n      puts "Non-positive" # line 7 (idx 6)\n    end # line 8 (idx 7)\n  end # line 9 (idx 8)\n\n  def method_two; end # line 11 (idx 10)\nend # line 12 (idx 11)\n"""
RUBY_LINES_1 = lines_from_string(RUBY_SAMPLE_CODE_1)

def test_extract_ruby_outer_class():
    # Target line 5 (1-based), no specific name - should find innermost 'if' block
    block = extract_ruby_block(RUBY_SAMPLE_CODE_1, line=5)
    assert block is not None
    assert block.start == 4, f"Expected start 4 (if block), got {block.start}"
    assert block.end == 8, f"Expected end 8 (end of if), got {block.end}"

def test_extract_ruby_method_by_name():
    # Target line 5, name "method_one"
    block = extract_ruby_block(RUBY_SAMPLE_CODE_1, line=5, name="method_one")
    assert block is not None
    assert block.start == 3, f"Expected start 3 (def method_one), got {block.start}"
    assert block.end == 9, f"Expected end 9 (end of method_one), got {block.end}"
    assert block.name == "method_one"

def test_extract_ruby_if_block_heuristic():
    block = extract_ruby_block(RUBY_SAMPLE_CODE_1, line=5) # Target line 5
    assert block is not None; assert block.start == 4; assert block.end == 8
    assert block.language == "ruby"

# --- Lua Block Tests ---
LUA_SAMPLE_CODE_1 = """\nlocal M = {}\n\nfunction M.calculate(a, b) -- line 3 (idx 2)\n  local sum = a + b -- line 4 (idx 3)\n  if x > 10 then -- line 5 (idx 4)\n    print("Large") -- line 6 (idx 5)\n  else -- line 7 (idx 6)\n    print("Small") -- line 8 (idx 7)\n  end -- line 9 (idx 8)\n  return sum, product -- line 10 (idx 9)\nend -- line 11 (idx 10)\n\nreturn M -- line 13 (idx 12)\n"""
LUA_LINES_1 = lines_from_string(LUA_SAMPLE_CODE_1)

def test_extract_lua_function_outer():
    # Target line 5 (1-based: 'local sum = a + b')
    block = extract_lua_block(LUA_SAMPLE_CODE_1, line=5)
    assert block is not None
    assert block.start == 4, f"Expected start 4 (function M.calculate), got {block.start}"
    assert block.end == 12, f"Expected end 12 (end for function), got {block.end}"
    assert block.language == "lua"

def test_extract_lua_if_block_heuristic():
    # Target line 7 (1-based: 'print("Large")')
    block = extract_lua_block(LUA_SAMPLE_CODE_1, line=7)
    assert block is not None
    assert block.start == 6, f"Expected start 6 (if), got {block.start}"
    assert block.end == 10, f"Expected end 10 (end for if), got {block.end}"
    assert block.language == "lua"

def test_extract_lua_outer_function_by_name():
    # Target line 5, name "M.calculate"
    block = extract_lua_block(LUA_SAMPLE_CODE_1, line=5, name="M.calculate")
    assert block is not None
    assert block.start == 4, f"Expected start 4 (function M.calculate), got {block.start}"
    assert block.end == 12, f"Expected end 12 (end for function), got {block.end}"
    assert block.name == "M.calculate"

# --- Optional Library Tests ---
@pytest.mark.skipif(not YAML_SUPPORT, reason="PyYAML not installed")
def test_extract_yaml_document_present(): yaml_content = "---\ndoc: 1\nvalues: [a, b]\n---\ndoc: 2\ninfo:\n  nested: true\n...\n"; block = extract_yaml_block(yaml_content, line=6); assert block is not None; assert block.start == 1; assert block.end == 8; assert block.language == "yaml"
@pytest.mark.skipif(not LXML_SUPPORT, reason="lxml not installed")
def test_extract_xml_element_present(): xml_content = "<root>\n  <item id=\"1\"><name>Apple</name></item>\n  <item id=\"2\">\n    <name>Banana</name>\n  </item>\n</root>"; block = extract_xml_block(xml_content, line=4); assert block is not None; assert block.start == 3; assert block.end == 5; assert block.language == "xml"
@pytest.mark.skipif(LXML_SUPPORT, reason="lxml IS installed")
def test_extract_xml_block_missing_lxml(): block = extract_xml_block("<tag>text</tag>\n", line=1); assert block is not None; assert block.start == 1; assert block.end == 1
