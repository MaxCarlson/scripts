from pathlib import Path

import pytest

from url_file_tools.core import (
    UrlFileError,
    build_merge_plan,
    build_normalize_plan,
    discover_files,
    grouped_output,
    normalize_mobile_url,
    registered_domain,
)


def test_mobile_normalization_and_registered_domain() -> None:
    normalized, changed = normalize_mobile_url("HTTPS://m.News.Example.co.uk:443/story?q=1#part")

    assert changed is True
    assert normalized == "https://news.example.co.uk:443/story?q=1#part"
    assert registered_domain(normalized) == "example.co.uk"


def test_merge_plan_tracks_normalization_duplicates_domains_and_invalid_rows(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.urls"
    first.write_text(
        "1. https://m.example.com/a\nhttps://other.net/b\nnot a URL\n",
        encoding="utf-8",
    )
    second.write_text("https://example.com/a\n# ignored\n\n", encoding="utf-8")

    plan = build_merge_plan(tmp_path, [first, second])

    assert [record.url for record in plan.unique_records] == [
        "https://example.com/a",
        "https://other.net/b",
    ]
    assert plan.stats.source_files == 2
    assert plan.stats.numbered_prefixes_removed == 1
    assert plan.stats.mobile_prefixes_removed == 1
    assert plan.stats.duplicate_occurrences == 1
    assert plan.stats.duplicate_groups == 1
    assert plan.stats.unique_base_domains == 2
    assert plan.stats.invalid_rows == 1
    assert plan.stats.comment_rows == 1
    assert plan.stats.blank_rows == 1
    assert plan.duplicates[0].first.line_number == 1
    assert plan.duplicates[0].duplicate.line_number == 1

    groups = grouped_output(plan.unique_records)
    assert list(groups) == ["example.com", "other.net"]


def test_normalize_plan_preserves_encoding_and_keeps_first_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "links.txt"
    path.write_text("1. One\r\n2. one\r\n3. Two\r\n", encoding="utf-16", newline="")

    plan = build_normalize_plan(path, unique=True, ignore_case=True)

    assert plan.original.encoding == "utf-16"
    assert plan.new_text == "One\r\nTwo\r\n"
    assert [change.kind for change in plan.changes] == ["numbering", "duplicate", "numbering"]


def test_manifest_selection_is_contained_and_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "urls"
    root.mkdir()
    (root / "b.txt").write_text("https://b.example\n", encoding="utf-8")
    (root / "a.txt").write_text("https://a.example\n", encoding="utf-8")
    manifest = tmp_path / "selected.txt"
    manifest.write_text("# order is normalized\nb.txt\na.txt\nb.txt\n", encoding="utf-8")

    found = discover_files(root, manifest=manifest)

    assert [path.name for path in found] == ["a.txt", "b.txt"]

    outside = tmp_path / "outside.txt"
    outside.write_text("https://outside.example\n", encoding="utf-8")
    manifest.write_text("../outside.txt\n", encoding="utf-8")
    with pytest.raises(UrlFileError, match="escapes the target folder"):
        discover_files(root, manifest=manifest)
