import textwrap
from scripts.modules.code_tools.rgcodeblock_lib.extractors import (
    extract_brace_block, extract_json_block, extract_yaml_block, extract_xml_block
)

def test_extract_brace_block_by_line_and_name():
    src = textwrap.dedent('''
    int foo() {
        return 1;
    }

    int bar() {
        if (true) { return 2; }
        return 2;
    }
    ''')
    line = src.splitlines().index("    int bar() {") + 1
    b1 = extract_brace_block(src, line=line)
    assert b1 and b1.start <= line <= b1.end
    b2 = extract_brace_block(src, name="bar")
    assert b2 and (b2.start, b2.end) == (b1.start, b1.end)

def test_extract_json_block_object():
    src = '{\n "a": 1,\n "b": {"c": [1,2,{"d":4}]}\n}\n'
    b = extract_json_block(src, line=3)
    assert b and b.start == 1 and b.end >= 3

def test_extract_yaml_block_section():
    src = textwrap.dedent('''
    root:
      child1: 1
      child2:
        grand: 3
    another: 4
    ''')
    line = src.splitlines().index("      child2:") + 1
    b = extract_yaml_block(src, line=line)
    assert b and b.start <= line <= b.end

def test_extract_xml_block_nested_and_selfclosing():
    src = '<root>\n  <node>text</node>\n  <self/>\n</root>\n'
    b1 = extract_xml_block(src, line=2)
    assert b1 and b1.start == 1 and b1.end == 4
    b2 = extract_xml_block(src, line=3)
    assert b2 and b2.start == 3 and b2.end == 3
