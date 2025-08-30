# File: pyprjs/clip_tools/tests/test_diff.py
from pathlib import Path
import clip_tools.cli as cli

def test_diff_shows_changes_and_stats(tmp_path, fake_sysapi, ns, capsys):
    f = tmp_path / "f.txt"
    f.write_text("a\nb\nc\n")
    fake_sysapi.set_clipboard("a\nB\nc\n")

    args = ns(file=str(f), context=3, warn_loc_delta=50, warn_similarity=0.1, no_stats=False)
    rc = cli.cmd_diff(args, fake_sysapi)
    assert rc == 0
    captured = capsys.readouterr()
    # Expect unified diff with + and - lines
    assert "+B" in captured.out or "+B" in captured.err
    assert "-b" in captured.out or "-b" in captured.err
    assert "diff stats" in captured.out

def test_diff_warnings(tmp_path, fake_sysapi, ns, capsys):
    f = tmp_path / "f.txt"
    f.write_text("one\n")
    fake_sysapi.set_clipboard("x\n" * 200)  # large difference

    args = ns(file=str(f), context=1, warn_loc_delta=3, warn_similarity=0.99, no_stats=False)
    rc = cli.cmd_diff(args, fake_sysapi)
    assert rc == 0
    captured = capsys.readouterr()
    assert "Warning: Large LOC delta" in captured.err
    assert "Warning: Low similarity" in captured.err
