import textwrap
from scripts.modules.code_tools.rgcodeblock_lib.extractors import extract_python_block_ast

def test_extract_python_function_by_name_and_line():
    src = textwrap.dedent('''
    async def a():
        return 0

    class C:
        def b(self):
            return 1

    def target(x):
        return x*2
    ''')
    b_name = extract_python_block_ast(src, name="target")
    assert b_name and b_name.kind == "function" and b_name.language == "python"
    line = src.splitlines().index("        return x*2") + 1
    b_line = extract_python_block_ast(src, line=line)
    assert b_line and b_line.start <= line <= b_line.end

def test_extract_python_class_by_name():
    src = "class Foo:\n    pass\n"
    b = extract_python_block_ast(src, name="Foo")
    assert b and b.kind == "class"
