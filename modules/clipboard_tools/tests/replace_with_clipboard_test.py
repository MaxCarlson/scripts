from __future__ import annotations

from pathlib import Path

from pyscripts import replace_with_clipboard as rwc


def test_replace_prints_clipboard(monkeypatch, capsys):
    monkeypatch.setattr(rwc, "get_clipboard", lambda: "CLIP")
    try:
        rwc.replace_or_print_clipboard(None, no_stats=True, from_last_cld=False, buffer_id=None)
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "CLIP" in out
