# File: pyprjs/clip_tools/tests/test_paste.py
from pathlib import Path
import clip_tools.cli as cli

def test_paste_to_file_creates(tmp_path, fake_sysapi, ns):
    fake_sysapi.set_clipboard("hello\nworld")
    target = tmp_path / "out.txt"
    args = ns(file=str(target), no_stats=True)
    rc = cli.cmd_paste(args, fake_sysapi)
    assert rc == 0
    assert target.read_text() == "hello\nworld\n"  # ensures trailing newline

def test_paste_print_stdout(fake_sysapi, ns, capsys):
    fake_sysapi.set_clipboard("X\nY")
    args = ns(file=None, no_stats=False)
    rc = cli.cmd_paste(args, fake_sysapi)
    assert rc == 0
    out = capsys.readouterr()
    assert out.out == "X\nY"
    assert "paste stats" in out.err  # stats for stdout mode go to stderr
