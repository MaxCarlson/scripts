from __future__ import annotations

import os

from mangadl.audit_console import AuditProgress, field, styled


def test_console_color_respects_terminal_and_no_color(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert "\x1b[" in styled("INCOMPLETE", "red")
    monkeypatch.setenv("NO_COLOR", "1")
    assert styled("INCOMPLETE", "red") == "INCOMPLETE"
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert styled("INCOMPLETE", "red") == "INCOMPLETE"


def test_console_wraps_long_folder_with_aligned_continuation(monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda: os.terminal_size((60, 24)))
    text = field("Folder", "A long gallery title " * 8)
    lines = text.splitlines()
    assert len(lines) > 1
    assert max(map(len, lines)) <= 60
    assert lines[1].startswith(" " * len("    Folder: "))


def test_progress_quiet_and_redirected_output(capsys) -> None:
    state = {"phase": "images", "index": 19, "total": 38, "url": "https://example.test/gallery",
             "checked": 7, "image_total": 20}
    quiet = AuditProgress(enabled=False)
    quiet.log("quiet")
    quiet.update(state)
    quiet.close()
    assert capsys.readouterr().err == ""

    display = AuditProgress(enabled=True)
    display.update(state)
    display.close()
    output = capsys.readouterr().err
    assert "URL 19/38" in output and "7/20" in output
    assert "\x1b[" not in output
