"""Inventory CLI summaries expose counts without pretending candidates are verified."""

import io
import json
from pathlib import Path
import re
import sys

import pytest
from PIL import Image

from compresser.cli import main


@pytest.mark.parametrize("depth", ["headers", "files"])
def test_interactive_inventory_closes_real_live_renderer_before_summary(tmp_path, monkeypatch, depth):
    from compresser.inventory_ui import InventoryProgress

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.delenv("TERM", raising=False)
    stream = Terminal()
    progress = InventoryProgress(tmp_path, depth=depth, stream=stream)
    try:
        progress.add_total_files(2)
        progress.advance_file(tmp_path / "01.png", size_bytes=100, inspected=depth == "headers")
        assert progress.interactive
        assert "DISCOVERING" in stream.getvalue()
        assert progress.bar.percent() == 50.0
        assert "50%" in progress._lines()[1]
        progress.close()
        progress.close()  # CLI error/finally paths may both attempt cleanup.
        assert progress.block._height == 0
        assert not progress.block._thread.is_alive()
        final = stream.getvalue()
        progress.block.update(lambda: ["must not appear after inventory summary"])
        assert stream.getvalue() == final
    finally:
        progress.block.close()  # Also stop the real renderer when the regression fails.


def test_file_inventory_summary_totals_types_and_redirected_json(tmp_path, capsys):
    root = tmp_path / "library"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    (root / "a" / "01.jpg").write_bytes(b"12345")
    (root / "b" / "01.webp").write_bytes(b"1234567890")
    args = ["-i", str(root), "-l", "-D", "files"]
    assert main(args) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["candidate_bytes"] == 15
    assert "Inventory Summary" in output.err
    assert re.search(r"Gallery folders with images\s*[:│]\s*2", output.err)
    assert re.search(r"Candidate images\s*[:│]\s*2", output.err)
    assert "15 B" in output.err
    assert re.search(r"\.jpg\s*│\s*1\s*│\s*5 B\s*│\s*50.0%\s*│\s*33.3%", output.err)
    assert "unverified" in output.err.lower()
    assert "Saved inventory:" in output.err
    assert main([*args, "-J"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["candidate_images"] == 2
    assert "Report saved:" in output.err and "Inventory Summary" not in output.err


def test_header_summary_reports_unreadable_and_reused_headers(tmp_path, capsys):
    Image.new("RGB", (40, 40)).save(tmp_path / "01.jpg", format="PNG")
    (tmp_path / "broken.jpg").write_bytes(b"not an image")
    args = ["-i", str(tmp_path), "-l"]
    assert main(args) == 0
    capsys.readouterr()
    assert main(args) == 0
    output = capsys.readouterr()
    assert re.search(r"Eligible image headers\s*[:│]\s*1", output.err)
    assert re.search(r"Unreadable candidates\s*[:│]\s*1", output.err)
    assert re.search(r"Headers reused / inspected\s*[:│]\s*1 / 1", output.err)
    assert "PNG: 1" in output.err
    assert "not a full decode audit" in output.err


def test_unknown_sizes_are_not_reported_as_zero_or_complete(tmp_path, monkeypatch, capsys):
    root = tmp_path / "library"
    root.mkdir()
    page = root / "01.jpg"
    page.write_bytes(b"12345")
    real_lstat = Path.lstat

    def denied(path, *a, **k):
        if path == page:
            raise PermissionError("test stat denied")
        return real_lstat(path, *a, **k)

    monkeypatch.setattr(Path, "lstat", denied)
    assert main(["-i", str(root), "-l", "-D", "files"]) == 0
    summary = capsys.readouterr().err
    assert "unknown" in summary.lower()
    assert re.search(r"Stat errors\s*[:│]\s*1", summary)
    assert "N/A" in summary  # No byte-share percentage when the denominator is unknown.


def test_terminal_inventory_shows_summary_not_entire_json(tmp_path, monkeypatch, capsys):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    Image.new("RGB", (40, 40)).save(tmp_path / "01.png")
    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    assert main(["-i", str(tmp_path), "-l"]) == 0
    summary = capsys.readouterr().err
    assert "Inventory Summary" in summary
    assert terminal.getvalue() == ""
    assert '"galleries":' not in summary


@pytest.mark.parametrize("depth", ["files", "headers"])
def test_empty_inventory_still_has_summary(tmp_path, capsys, depth):
    assert main(["-i", str(tmp_path), "-l", "-D", depth]) == 0
    summary = capsys.readouterr().err
    assert "Inventory Summary" in summary
    assert re.search(r"Gallery folders with images\s*[:│]\s*0", summary)
