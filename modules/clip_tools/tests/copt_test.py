# File: pyprjs/clip_tools/tests/test_copy.py
from pathlib import Path
import clip_tools.cli as cli

def test_copy_raw_single(tmp_path, fake_sysapi, ns, capsys):
    p = tmp_path / "a.txt"
    p.write_text("A\n")
    args = ns(files=[str(p)], raw_copy=True, wrap=False, whole_wrap=False,
              show_full_path=False, append=False, override_append_wrapping=False, no_stats=False)
    rc = cli.cmd_copy(args, fake_sysapi)
    assert rc == 0
    assert fake_sysapi.get_clipboard() == "A\n"
    out = capsys.readouterr()
    assert "copy stats" in out.out

def test_copy_wrap_multi(tmp_path, fake_sysapi, ns):
    a = tmp_path / "a.txt"; b = tmp_path / "b.txt"
    a.write_text("A"); b.write_text("B")
    args = ns(files=[str(a), str(b)], raw_copy=False, wrap=True, whole_wrap=False,
              show_full_path=True, append=False, override_append_wrapping=False, no_stats=True)
    rc = cli.cmd_copy(args, fake_sysapi)
    assert rc == 0
    cb = fake_sysapi.get_clipboard()
    assert "```" in cb and "# " in cb and "A" in cb and "B" in cb

def test_copy_whole_wrap(tmp_path, fake_sysapi, ns):
    p = tmp_path / "a.txt"; p.write_text("A")
    args = ns(files=[str(p)], raw_copy=False, wrap=False, whole_wrap=True,
              show_full_path=False, append=False, override_append_wrapping=False, no_stats=True)
    rc = cli.cmd_copy(args, fake_sysapi)
    assert rc == 0
    cb = fake_sysapi.get_clipboard()
    assert cb.startswith(cli.WHOLE_WRAP_HEADER_MARKER)

def test_copy_append_smart_into_whole(tmp_path, fake_sysapi, ns):
    # Existing clipboard has WHOLE block
    existing = f"{cli.WHOLE_WRAP_HEADER_MARKER}\n```\nold.txt\nOLD\n```"
    fake_sysapi.set_clipboard(existing)
    # New file to append
    p = tmp_path / "n.txt"; p.write_text("NEW")
    args = ns(files=[str(p)], raw_copy=False, wrap=True, whole_wrap=False,
              show_full_path=False, append=True, override_append_wrapping=False, no_stats=True)
    rc = cli.cmd_copy(args, fake_sysapi)
    assert rc == 0
    cb = fake_sysapi.get_clipboard()
    assert cb.startswith(cli.WHOLE_WRAP_HEADER_MARKER)
    assert "OLD" in cb and "NEW" in cb

def test_copy_append_override_simple_concat(tmp_path, fake_sysapi, ns):
    fake_sysapi.set_clipboard("EXISTING")
    p = tmp_path / "a.txt"; p.write_text("A")
    args = ns(files=[str(p)], raw_copy=True, wrap=False, whole_wrap=False,
              show_full_path=False, append=True, override_append_wrapping=True, no_stats=True)
    rc = cli.cmd_copy(args, fake_sysapi)
    assert rc == 0
    assert "EXISTING" in fake_sysapi.get_clipboard()
    assert "A" in fake_sysapi.get_clipboard()

def test_copy_verification_mismatch(tmp_path, fake_sysapi, ns, capsys):
    # Force mismatch by toggling flag
    fake_sysapi.verify_mismatch = True
    p = tmp_path / "a.txt"; p.write_text("A")
    args = ns(files=[str(p)], raw_copy=True, wrap=False, whole_wrap=False,
              show_full_path=False, append=False, override_append_wrapping=False, no_stats=False)
    rc = cli.cmd_copy(args, fake_sysapi)
    assert rc == 0  # still succeeds but warns
    out = capsys.readouterr()
    assert "verification mismatch" in out.err.lower()
