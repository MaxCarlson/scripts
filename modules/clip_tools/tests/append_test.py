# File: pyprjs/clip_tools/tests/test_append.py
import io
from pathlib import Path
import clip_tools.cli as cli

def test_append_creates_and_appends(tmp_path, fake_sysapi, ns, capsys):
    target = tmp_path / "out.txt"
    fake_sysapi.set_clipboard("foo\nbar")

    args = ns(file=str(target), no_stats=False)
    rc = cli.cmd_append(args, fake_sysapi)
    assert rc == 0
    assert target.exists()
    # First append creates file and writes "\n" prefix + content
    assert target.read_text() == "\nfoo\nbar"

    # Append again
    fake_sysapi.set_clipboard("BAZ")
    rc = cli.cmd_append(args, fake_sysapi)
    assert rc == 0
    assert target.read_text().endswith("BAZ")

    out = capsys.readouterr()
    assert "append stats" in out.out

def test_append_empty_clipboard_noop(tmp_path, fake_sysapi, ns, capsys):
    target = tmp_path / "out.txt"
    fake_sysapi.set_clipboard("   \n   ")  # whitespace only -> strip becomes empty in cmd
    args = ns(file=str(target), no_stats=False)
    rc = cli.cmd_append(args, fake_sysapi)
    assert rc == 0
    assert not target.exists()  # no file created on no-op
    out = capsys.readouterr()
    assert "Clipboard is empty" in out.err
