# File: pyprjs/clip_tools/tests/test_copy_buffer.py
import clip_tools.cli as cli

def test_copy_buffer_full(fake_sysapi, ns, capsys):
    fake_sysapi._tmux = True
    fake_sysapi._pane = "line1\nline2\nline3\n"
    args = ns(full=True, no_stats=False)
    rc = cli.cmd_copy_buffer(args, fake_sysapi)
    assert rc == 0
    assert fake_sysapi.get_clipboard() == "line1\nline2\nline3"
    out = capsys.readouterr()
    assert "copy-buffer stats" in out.out

def test_copy_buffer_since_clear(fake_sysapi, ns):
    fake_sysapi._tmux = True
    # Include a "clear" marker then new content
    fake_sysapi._pane = "old\n\x1b[H\x1b[2Jnew1\nnew2\n"
    args = ns(full=False, no_stats=True)
    rc = cli.cmd_copy_buffer(args, fake_sysapi)
    assert rc == 0
    assert fake_sysapi.get_clipboard() == "new1\nnew2"

def test_copy_buffer_not_tmux(fake_sysapi, ns, capsys):
    fake_sysapi._tmux = False
    args = ns(full=False, no_stats=False)
    rc = cli.cmd_copy_buffer(args, fake_sysapi)
    assert rc == 1
    out = capsys.readouterr()
    assert "Not running inside tmux" in out.err
