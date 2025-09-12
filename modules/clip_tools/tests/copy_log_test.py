# File: pyprjs/clip_tools/tests/test_copy_log.py
from pathlib import Path
import os
import clip_tools.cli as cli

def test_copy_log_success(tmp_path, fake_sysapi, ns, capsys, monkeypatch):
    # SHLVL=3 from autouse fixture; create corresponding log file in HOME
    log = Path(os.path.expanduser("~")) / ".term_log.session_shlvl_3"
    log.write_text("\n".join([f"line{i}" for i in range(10)]) + "\n")
    args = ns(lines=4, no_stats=False)
    rc = cli.cmd_copy_log(args, fake_sysapi)
    assert rc == 0
    assert fake_sysapi.get_clipboard() == "line6\nline7\nline8\nline9"
    out = capsys.readouterr()
    assert "copy-log stats" in out.out

def test_copy_log_missing(fake_sysapi, ns, capsys, monkeypatch):
    monkeypatch.setenv("SHLVL", "99")
    args = ns(lines=5, no_stats=False)
    rc = cli.cmd_copy_log(args, fake_sysapi)
    assert rc == 1
    out = capsys.readouterr()
    assert "not found" in out.err.lower()
