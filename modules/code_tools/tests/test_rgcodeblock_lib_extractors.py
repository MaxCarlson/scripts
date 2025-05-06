# tests/test_rgcodeblock_lib_extractors.py
import pytest

# Import directly from the library's extractors module
from rgcodeblock_lib.extractors import (
    extract_python_block_ast,
    extract_brace_block,
    extract_json_block,
    extract_yaml_block,
    extract_xml_block,
    extract_ruby_block,
    extract_lua_block,
    YAML_SUPPORT, # To check if the library is available
    LXML_SUPPORT  # To check if the library is available
)
# Import OPTIONAL_LIBRARY_NOTES if testing its population is needed
from rgcodeblock_lib.extractors import OPTIONAL_LIBRARY_NOTES

# --- Helper ---
def lines_from_string(text: str) -> list[str]:
    """Ensure consistent line ending simulation for tests."""
    lines = text.splitlines()
    # Add newline back to each line, mirroring readlines() behavior
    return [(line + '\n') for line in lines]

# --- Python AST Tests ---
PYTHON_SAMPLE_CODE_1 = """# Comment line 1
class MyClass: # Line 2 (0-idx: 1)
    '''Docstring''' # Line 3 (0-idx: 2)
    def __init__(self, value): # Line 4 (0-idx: 3)
        self.value = value # Line 5 (0-idx: 4)

    def another_method(self): # Line 7 (0-idx: 6)
        pass # Line 8 (0-idx: 7)"""
PYTHON_LINES_1 = lines_from_string(PYTHON_SAMPLE_CODE_1)

def test_extract_python_by_line_in_method():
    # Target line 5 ("self.value = value", 1-based)
    block, start, end = extract_python_block_ast(PYTHON_LINES_1, PYTHON_SAMPLE_CODE_1, target_line_1idx=5)
    assert block is not None, "Block should be found"
    assert start == 3, f"Expected start index 3 (def __init__), got {start}"
    assert end == 4, f"Expected end index 4 (self.value = value), got {end}" # AST end_lineno is inclusive
    assert "def __init__" in block[0]
    assert "self.value = value" in block[1]

def test_extract_python_by_name_class():
    block, start, end = extract_python_block_ast(PYTHON_LINES_1, PYTHON_SAMPLE_CODE_1, target_entity_name="MyClass")
    assert block is not None, "Block should be found for MyClass"
    assert start == 1, f"Expected start index 1 (class MyClass), got {start}"
    assert end == 7, f"Expected end index 7 (pass), got {end}"
    assert "class MyClass" in block[0]
    assert "def another_method" in "".join(block) # Check method is within class block

def test_extract_python_nested_function():
    code = """
def outer():
    x = 1
    def inner(y): # line 4 (idx 3)
        return x + y # line 5 (idx 4)
    return inner(5) # line 6 (idx 5)"""
    lines = lines_from_string(code)
    # Target line 5 (inside 'inner')
    block, start, end = extract_python_block_ast(lines, code, target_line_1idx=5)
    assert block is not None
    assert start == 3, f"Expected start index 3 (def inner), got {start}"
    assert end == 4, f"Expected end index 4 (return x+y), got {end}"
    assert "def inner(y)" in block[0]

# --- Brace Block Tests ---
BRACE_SAMPLE_CODE_1 = """#include <stdio.h>

int main() { // line 3 (idx 2)
  printf("Hello"); // line 4 (idx 3)
  { // Inner scope line 5 (idx 4)
    int nested = 1; // line 6 (idx 5)
  } // line 7 (idx 6)
  return 0; // line 8 (idx 7)
} // line 9 (idx 8)"""
BRACE_LINES_1 = lines_from_string(BRACE_SAMPLE_CODE_1)

def test_extract_brace_outer_function():
    block, start, end = extract_brace_block(BRACE_LINES_1, target_line_0idx=3) # printf line
    assert block is not None
    assert start == 2, f"Expected start index 2 (int main), got {start}"
    assert end == 8, f"Expected end index 8 (closing brace of main), got {end}"
    assert "int main()" in block[0]
    assert "return 0;" in block[5] # Relative to start of block

def test_extract_brace_inner_scope():
    block, start, end = extract_brace_block(BRACE_LINES_1, target_line_0idx=5) # 'int nested' line
    assert block is not None
    # CORRECTED LINE BELOW: Use double quotes for f-string, double {{ and }} for literal braces
    assert start == 4, f"Expected start index 4 (inner scope '{{'), got {start}" 
    assert end == 6, f"Expected end index 6 (inner scope '}}'), got {end}" 
    assert block[0].strip() == "{"
    assert "int nested" in block[1]

# --- JSON Block Tests ---
JSON_SAMPLE_CODE_1 = """{
  "name": "example",
  "data": [
    1,
    2,
    3
  ],
  "details": { "id": 101, "active": true }
}""" # Ends line 9 (idx 8)
JSON_LINES_1 = lines_from_string(JSON_SAMPLE_CODE_1)

def test_extract_json_outer_object_corrected():
    # Target line 2 ("name": "example", 0-indexed)
    block, start, end = extract_json_block(JSON_LINES_1, target_line_0idx=1, file_content_str=JSON_SAMPLE_CODE_1)
    assert block is not None
    assert start == 0, f"Expected start index 0 ('{{'), got {start}"
    assert end == 8, f"Expected end index 8 ('}}'), got {end}"
    assert block[0].strip() == "{"
    assert block[-1].strip() == "}"

def test_extract_json_inner_array_corrected():
    # Target line 5 ('2,', 0-indexed)
    block, start, end = extract_json_block(JSON_LINES_1, target_line_0idx=4, file_content_str=JSON_SAMPLE_CODE_1)
    assert block is not None
    assert start == 2, f"Expected start index 2 ('[' for data), got {start}"
    assert end == 6, f"Expected end index 6 (']'), got {end}"
    assert block[0].strip().endswith("[")
    # Check start of last line, ignoring potential trailing comma/whitespace
    assert block[-1].strip().startswith("]")

def test_extract_json_nested_object_corrected():
     # Target line 8 ('details': { ... }, 0-indexed) - line containing "id"
     block, start, end = extract_json_block(JSON_LINES_1, target_line_0idx=7, file_content_str=JSON_SAMPLE_CODE_1)
     assert block is not None
     # The heuristic finds the *outer* block containing this line
     assert start == 0, f"Expected start index 0 (outer '{{'), got {start}"
     assert end == 8, f"Expected end index 8 (outer '}}'), got {end}"

# --- Ruby Block Tests ---
RUBY_SAMPLE_CODE_1 = """
class MyRuby # line 2 (idx 1)
  def method_one(a) # line 3 (idx 2)
    if a > 0 then # line 4 (idx 3)
      puts "Positive" # line 5 (idx 4)
    else
      puts "Non-positive" # line 7 (idx 6)
    end # line 8 (idx 7)
  end # line 9 (idx 8)

  def method_two; end # line 11 (idx 10)
end # line 12 (idx 11)
"""
RUBY_LINES_1 = lines_from_string(RUBY_SAMPLE_CODE_1)

def test_extract_ruby_outer_class():
    # Target line 4 (inside method_one) -> finds outer `class`
    block, start, end = extract_ruby_block(RUBY_LINES_1, target_line_0idx=4)
    assert block is not None
    assert start == 1, f"Expected start index 1 (class MyRuby), got {start}"
    assert end == 11, f"Expected end index 11 (end of class), got {end}"
    assert "class MyRuby" in block[0]

def test_extract_ruby_method_by_name():
    # Target the specific method by name (provide a line inside it to help find instance)
    block, start, end = extract_ruby_block(RUBY_LINES_1, target_line_0idx=4, target_entity_name="method_one")
    assert block is not None
    assert start == 2, f"Expected start index 2 (def method_one), got {start}"
    assert end == 8, f"Expected end index 8 (end of method_one), got {end}"
    assert "def method_one" in block[0]

def test_extract_ruby_if_block_heuristic():
    # Target line 5 ('puts "Positive"') which is inside the 'if'
    block, start, end = extract_ruby_block(RUBY_LINES_1, target_line_0idx=4) # Target line 5 (index 4)
    # Scans back, finds 'if' at line 4 (idx 3). Scans forward, finds matching 'end' at line 8 (idx 7).
    assert block is not None
    assert start == 3, f"Expected start index 3 (if), got {start}"
    assert end == 7, f"Expected end index 7 (end for if), got {end}"
    assert block[0].strip().startswith("if")
    assert block[-1].strip() == "end"

# --- Lua Block Tests ---
LUA_SAMPLE_CODE_1 = """
local M = {}

function M.calculate(a, b) -- line 3 (idx 2)
  local sum = a + b -- line 4 (idx 3)
  if x > 10 then -- line 5 (idx 4) -- Assume x defined
    print("Large") -- line 6 (idx 5)
  else -- line 7 (idx 6)
    print("Small") -- line 8 (idx 7)
  end -- line 9 (idx 8)
  return sum, product -- line 10 (idx 9) -- Assume product defined
end -- line 11 (idx 10)

return M -- line 13 (idx 12)
"""
LUA_LINES_1 = lines_from_string(LUA_SAMPLE_CODE_1)

def test_extract_lua_function_outer():
    # Target line 4 (inside function but outside if)
    block, start, end = extract_lua_block(LUA_LINES_1, target_line_0idx=3)
    assert block is not None
    assert start == 2, f"Expected start index 2 (function M.calculate), got {start}"
    assert end == 10, f"Expected end index 10 (end for function), got {end}"
    assert "function M.calculate" in block[0]

def test_extract_lua_if_block_heuristic():
     # Target line 6 (inside 'if'/'else')
    block, start, end = extract_lua_block(LUA_LINES_1, target_line_0idx=5)
    # Scans back from 5. Line 4 'if' matches starter. bal=-1. start=4.
    # Scans forward from 4. Line 4 'if' bal=1. Line 8 'end' matches ender, bal=0. Indent matches. end=8.
    assert block is not None
    assert start == 4, f"Expected start index 4 (if), got {start}"
    assert end == 8, f"Expected end index 8 (end for if), got {end}"
    assert block[0].strip().startswith("if")
    assert block[-1].strip() == "end"

def test_extract_lua_outer_function_by_name():
     # Target function by name (line hint helps find the right instance if overloaded)
    block, start, end = extract_lua_block(LUA_LINES_1, target_line_0idx=3, target_entity_name="M.calculate")
    assert block is not None
    assert start == 2, f"Expected start index 2 (function M.calculate), got {start}"
    assert end == 10, f"Expected end index 10 (end for function), got {end}"
    assert "function M.calculate" in block[0]

# --- Optional Library Tests ---
@pytest.mark.skipif(not YAML_SUPPORT, reason="PyYAML not installed")
def test_extract_yaml_document_present():
    yaml_content = """---
doc: 1
values: [a, b]
---
doc: 2 # line 5 (idx 4)
info:
  nested: true # line 7 (idx 6)
... # line 8 (idx 7)"""
    yaml_lines = lines_from_string(yaml_content)
    # Target line 6 (inside doc 2)
    block, start, end = extract_yaml_block(yaml_lines, target_line_0idx=6, file_content_str=yaml_content)
    assert block is not None
    assert start == 3, f"Expected start index 3 (--- before doc 2), got {start}"
    # End index depends on whether final '...' exists and is counted. Assuming it is.
    assert end == 7, f"Expected end index 7 (... after doc 2), got {end}"
    assert "doc: 2" in block[1] # Relative index within block
    assert "nested: true" in block[3]

@pytest.mark.skipif(not LXML_SUPPORT, reason="lxml not installed")
def test_extract_xml_element_present():
    xml_content = """<root>
  <item id="1">
    <name>Apple</name> <!-- line 3 (idx 2) -->
  </item>
  <item id="2"> <!-- line 5 (idx 4) -->
    <name>Banana</name> <!-- line 6 (idx 5) -->
  </item> <!-- line 7 (idx 6) -->
</root>"""
    xml_lines = lines_from_string(xml_content)
    # Target line 6 (name Banana)
    block, start, end = extract_xml_block(xml_lines, target_line_0idx=5, file_content_str=xml_content)
    assert block is not None
    assert start == 4, f"Expected start index 4 (<item id='2'>), got {start}"
    # End line calculation via serialization might include closing tag line
    assert end == 6, f"Expected end index 6 (</item>), got {end}"
    assert '<item id="2">' in block[0].strip()
    assert '<name>Banana</name>' in block[1].strip()
    assert '</item>' in block[2].strip()


@pytest.mark.skipif(LXML_SUPPORT, reason="lxml IS installed")
def test_extract_xml_block_missing_lxml():
    OPTIONAL_LIBRARY_NOTES.clear()
    lines = ["<tag>text</tag>\n"]
    # Need to ensure the function is imported for the test to run, even if skipped
    from rgcodeblock_lib.extractors import extract_xml_block
    extract_xml_block(lines, 0, "".join(lines)) # Call the function
    # Check the global set in the library module
    assert "XML: lxml library not found" in "".join(OPTIONAL_LIBRARY_NOTES)
