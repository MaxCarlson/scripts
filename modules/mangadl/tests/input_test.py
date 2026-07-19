from pathlib import Path

import pytest

from mangadl.input import canonicalize_url, collect_inputs


def test_canonicalize_nhentai_id_and_url() -> None:
    assert canonicalize_url("123") == "https://nhentai.net/g/123/"
    assert canonicalize_url("https://nhentai.net/g/123") == "https://nhentai.net/g/123/"


def test_collect_inputs_comments_invalid_and_stable_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "urls.txt"
    source.write_text("# note\n123\n123  # duplicate\nnot-a-url\nhttps://example.com/a\n", encoding="utf-8")
    found, rejected = collect_inputs([source], ["https://example.com/a"])
    assert [item.canonical_url for item in found] == ["https://example.com/a", "https://nhentai.net/g/123/"]
    assert sorted(item["reason"] for item in rejected) == [
        "duplicate",
        "duplicate",
        "not a supported HTTP URL: not-a-url",
    ]


def test_collect_inputs_extracts_urls_from_numbered_and_pasted_lines(tmp_path: Path) -> None:
    source = tmp_path / "numbered.txt"
    source.write_text(
        "1. https://nhentai.net/g/419136/\n"
        "12) https://nhentai.net/search?q=English%20title&sort=popular\n"
        "label: https://example.com/gallery/7\n"
        "3. 123456\n",
        encoding="utf-8",
    )
    found, rejected = collect_inputs([source], [])
    assert rejected == []
    assert [item.canonical_url for item in found] == [
        "https://nhentai.net/g/419136/",
        "https://nhentai.net/search?q=English%20title&sort=popular",
        "https://example.com/gallery/7",
        "https://nhentai.net/g/123456/",
    ]


def test_canonicalize_rejects_non_http() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        canonicalize_url("ftp://example.com/a")
