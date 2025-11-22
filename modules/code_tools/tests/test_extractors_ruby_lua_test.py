import textwrap
from rgcodeblock_lib.extractors import extract_ruby_block, extract_lua_block

def test_extract_ruby_and_lua_named_and_line():
    ruby = textwrap.dedent('''
    class Foo
      def bar
        if true
          42
        end
      end
    end
    ''')
    lua = textwrap.dedent('''
    function foo(x)
      if x then
        return x*2
      end
    end
    ''')
    br = extract_ruby_block(ruby, name="bar")
    assert br and br.start < br.end
    line_ruby = ruby.splitlines().index("      42") + 1
    br2 = extract_ruby_block(ruby, line=line_ruby)
    assert br2 and br2.start <= line_ruby <= br2.end
    bl = extract_lua_block(lua, name="foo")
    assert bl and bl.start < bl.end
    line_lua = lua.splitlines().index("  if x then") + 1
    bl2 = extract_lua_block(lua, line=line_lua)
    assert bl2 and bl2.start <= line_lua <= bl2.end
