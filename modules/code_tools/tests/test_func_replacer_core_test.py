import io
import textwrap
import func_replacer as fr

def test_replacement_python_name_and_indent_and_backup(tmp_path):
    target = tmp_path / "m.py"
    target.write_text(textwrap.dedent('''
    def keep():
        return 1

    def target(x):
        return x+1
    '''))
    new_code = textwrap.dedent('''
    def target(x):
        # changed
        return x + 42
    ''')
    plan = fr.plan_replacement(target, new_code, backup=True)
    fr.apply_replacement(plan, assume_yes=True)
    out = target.read_text()
    assert "# changed" in out
    assert (tmp_path / "m.py.bak").exists()
    assert out.splitlines()[4].startswith("def target")

def test_replacement_by_line_no_backup_and_prompt_abort(tmp_path, monkeypatch):
    target = tmp_path / "x.c"
    target.write_text(textwrap.dedent('''
    int a(){return 0;}
    int b(){
        return 1;
    }
    '''))
    new_code = textwrap.dedent('''
    int b(){
        return 9;
    }
    ''')
    line = target.read_text().splitlines().index("int b(){") + 1
    plan = fr.plan_replacement(target, new_code, approx_line=line, backup=False)
    monkeypatch.setattr(fr.sys, "stdin", io.StringIO("n\n"))
    fr.apply_replacement(plan, assume_yes=False)
    assert target.read_text().count("return 9;") == 0

def test_infer_name_heuristics_for_multiple_langs(tmp_path):
    t_rb = tmp_path / "m.rb"
    t_rb.write_text("def foo\n  1\nend\n")
    new_rb = "def foo\n  2\nend\n"
    plan = fr.plan_replacement(t_rb, new_rb)
    assert plan.detected_name == "foo" and plan.language == "ruby"

    t_lua = tmp_path / "m.lua"
    t_lua.write_text("function bar()\n  return 1\nend\n")
    new_lua = "function bar()\n  return 3\nend\n"
    plan2 = fr.plan_replacement(t_lua, new_lua)
    assert plan2.detected_name == "bar" and plan2.language == "lua"

    t_c = tmp_path / "m.c"
    t_c.write_text("int z(){return 1;}\n")
    new_c = "int z(){return 2;}\n"
    plan3 = fr.plan_replacement(t_c, new_c)
    assert plan3.detected_name == "z" and plan3.language == "brace"

def test_errors_block_not_found(tmp_path):
    tgt = tmp_path / "a.py"
    tgt.write_text("def f():\n  return 1\n")
    new_code = "def g():\n  return 2\n"
    try:
        fr.plan_replacement(tgt, new_code)
        assert False, "expected ValueError"
    except ValueError:
        assert True
