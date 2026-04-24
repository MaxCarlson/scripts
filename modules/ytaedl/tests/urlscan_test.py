from __future__ import annotations

import math
from pathlib import Path

from ytaedl import urlscan


def _entry(name: str, *, remaining: int = 0, ratio: float = 0.0, mp4_bytes: int = 0) -> urlscan.UrlEntry:
    return urlscan.UrlEntry(
        name=name,
        total_unique_urls=remaining,
        ae_line_count=0,
        ae_unique_urls=0,
        stars_line_count=0,
        stars_unique_urls=0,
        mp4_count=0,
        mp4_bytes=mp4_bytes,
        mp4_files=[],
        remaining=remaining,
        ratio=ratio,
        ae_path=None,
        stars_path=Path(f"{name}.txt"),
        media_path=Path(name),
    )


def test_ratio_descending_sorts_infinity_first():
    entries = [
        _entry("finite_high", ratio=20.0),
        _entry("infinite", ratio=math.inf),
        _entry("finite_low", ratio=1.0),
    ]

    sorted_names = [entry.name for entry in urlscan.sort_entries(entries, "ratio", ascending=False)]

    assert sorted_names == ["infinite", "finite_high", "finite_low"]


def test_gb_sort_uses_mp4_bytes():
    entries = [
        _entry("small", mp4_bytes=1),
        _entry("large", mp4_bytes=10),
        _entry("medium", mp4_bytes=5),
    ]

    sorted_names = [entry.name for entry in urlscan.sort_entries(entries, "gb", ascending=False)]

    assert sorted_names == ["large", "medium", "small"]


def test_filter_entries_by_name_supports_substring_and_glob():
    entries = [_entry("mary_rock"), _entry("mary_jane"), _entry("sara_luvv")]

    assert [entry.name for entry in urlscan.filter_entries_by_name(entries, "mary")] == [
        "mary_rock",
        "mary_jane",
    ]
    assert [entry.name for entry in urlscan.filter_entries_by_name(entries, "mary_*ock")] == ["mary_rock"]
    assert urlscan.filter_entries_by_name(entries, "") == entries
