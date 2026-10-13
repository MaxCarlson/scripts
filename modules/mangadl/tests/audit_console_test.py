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


def test_progress_has_distinct_item_and_overall_rows(capsys):
    display = AuditProgress(enabled=True)
    display.update({"phase": "images", "index": 2, "total": 10, "url": "https://example.test/gallery",
                    "checked": 7, "image_total": 20})
    lines = display._lines()
    assert len(lines) == 3
    assert lines[0].startswith("URL 2/10:")
    assert "7/20" in lines[1]
    assert "Overall:" in lines[2] and "1/10" in lines[2]
    assert "Elapsed:" in lines[2] and "ETA:" in lines[2]
    display.close()


def test_ambiguous_defects_are_not_hidden():
    from mangadl.cli_core import _format_audit_findings
    item = {"identity_status": "ambiguous", "completeness": "incomplete", "image_integrity": "valid",
            "folder": "unknown title", "missing_pages": [3, 4], "valid_images": 2, "present_images": 2}
    assert "Missing pages: 3-4 (2)" in _format_audit_findings([item])
    assert "inferred numbering gaps" in _format_audit_findings([item])
    item["missing_pages"] = []
    assert "AMBIGUOUS:" not in _format_audit_findings([item])
    assert "AMBIGUOUS:" in _format_audit_findings([item], all_findings=True)
