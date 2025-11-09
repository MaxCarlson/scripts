from __future__ import annotations

from pathlib import Path

from termdash import utils as td_utils


def test_color_text_handles_unknown():
    assert td_utils.color_text("plain", None) == "plain"
    assert td_utils.color_text("plain", "unknown") == "plain"
    colored = td_utils.color_text("hi", "red")
    assert colored.startswith("\033[")
    assert colored.endswith(td_utils.ANSI_RESET)


def test_wrap_text_respects_width():
    wrapped = td_utils.wrap_text("a bb ccc dddd eeee", 4)
    assert all(len(line) <= 4 for line in wrapped)
    flattened = " ".join(wrapped).split()
    assert flattened == ["a", "bb", "ccc", "dddd", "eeee"]


def test_format_bytes_binary():
    assert td_utils.format_bytes_binary(0) == "0 B"
    assert td_utils.format_bytes_binary(1024) == "1.00 KiB"
    assert td_utils.format_bytes_binary(1024 ** 2) == "1.00 MiB"


def test_get_disk_stats(tmp_path):
    nested = tmp_path / "child"
    nested.mkdir()
    stats = td_utils.get_disk_stats(nested)
    assert stats.path == nested.resolve()
    assert stats.total_bytes >= stats.free_bytes > 0
    stats_2 = td_utils.get_disk_stats(tmp_path)
    assert td_utils.same_disk(stats, stats_2)
