# File: pyprjs/clip_tools/tests/test_replace_block.py
from pathlib import Path
import clip_tools.cli as cli

def test_replace_function_with_decorator(tmp_path, fake_sysapi, ns):
    src = tmp_path / "mod.py"
    src.write_text(
        "@dec\n"
        "def target(x):\n"
        "    return x+1\n"
        "\n"
        "def other():\n"
        "    return 0\n"
    )
    fake_sysapi.set_clipboard(
        "def target(x):\n"
        "    # replaced\n"
        "    return x+2\n"
    )
    args = ns(file=str(src), no_stats=True)
    rc = cli.cmd_replace_block(args, fake_sysapi)
    assert rc == 0
    text = src.read_text()
    assert "# replaced" in text
    assert "@dec" not in text  # decorator not preserved because clipboard lacked it

def test_replace_class_block(tmp_path, fake_sysapi, ns):
    src = tmp_path / "mod.py"
    src.write_text(
        "class Foo:\n"
        "    def a(self):\n"
        "        return 1\n"
        "\n"
        "class Bar:\n"
        "    pass\n"
    )
    fake_sysapi.set_clipboard(
        "class Foo:\n"
        "    def a(self):\n"
        "        return 2\n"
    )
    args = ns(file=str(src), no_stats=True)
    rc = cli.cmd_replace_block(args, fake_sysapi)
    assert rc == 0
    text = src.read_text()
    assert "return 2" in text

def test_replace_not_found(tmp_path, fake_sysapi, ns, capsys):
    src = tmp_path / "mod.py"
    src.write_text("def nope():\n    return 1\n")
    fake_sysapi.set_clipboard("def missing():\n    return 2\n")
    args = ns(file=str(src), no_stats=False)
    rc = cli.cmd_replace_block(args, fake_sysapi)
    assert rc == 1
    out = capsys.readouterr()
    assert "not found" in (out.err + out.out).lower()

def test_replace_multiple_defs_error(tmp_path, fake_sysapi, ns, capsys):
    src = tmp_path / "mod.py"
    src.write_text(
        "def target():\n    pass\n\n"
        "def target():\n    pass\n"
    )
    fake_sysapi.set_clipboard("def target():\n    return 123\n")
    args = ns(file=str(src), no_stats=False)
    rc = cli.cmd_replace_block(args, fake_sysapi)
    assert rc == 1
    out = capsys.readouterr()
    assert "Multiple def/class" in out.err
