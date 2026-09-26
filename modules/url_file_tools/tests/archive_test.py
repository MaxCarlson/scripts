import sqlite3
from pathlib import Path

import pytest

from url_file_tools.archive import detect_archive_type, match_archive_urls
from url_file_tools.core import UrlFileError


def test_ytaedl_archive_matches_processed_and_unprocessed_urls(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "yt-links.txt").write_text(
        "downloaded\t1.0\t2026-01-01\t1.0MiB\tid1\thttps://m.example.com/a\n"
        "bad-url\t1.0\t2026-01-01\t0.0MiB\tid2\thttps://example.com/b\n",
        encoding="utf-8",
    )

    result = match_archive_urls(
        ["https://example.com/a", "https://example.com/b", "https://example.com/c"],
        archive,
    )

    assert result.archive_type == "ytaedl"
    assert [item.url for item in result.downloaded] == ["https://example.com/a"]
    assert [item.archive_status for item in result.not_downloaded] == ["bad-url", "not-in-archive"]


def _mangadl_state(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, canonical_url TEXT, state TEXT, updated REAL)")
        connection.executemany(
            "INSERT INTO jobs(canonical_url,state,updated) VALUES(?,?,?)",
            [
                ("https://example.com/series#old-fragment", "failed_http", 2.0),
                ("https://example.com/series", "succeeded", 1.0),
                ("https://example.com/pending", "queued", 3.0),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def test_mangadl_state_uses_url_level_success_evidence(tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite3"
    _mangadl_state(state)

    result = match_archive_urls(
        ["https://example.com/series#new", "https://example.com/pending", "https://example.com/new"],
        state,
    )

    assert detect_archive_type(state) == "mangadl"
    assert [item.url for item in result.downloaded] == ["https://example.com/series"]
    assert [item.archive_status for item in result.not_downloaded] == ["queued", "not-in-archive"]


def test_gallery_dl_archive_is_rejected_without_guessing(tmp_path: Path) -> None:
    archive = tmp_path / "gallery.sqlite3"
    connection = sqlite3.connect(archive)
    try:
        connection.execute("CREATE TABLE archive(entry TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO archive VALUES('site-key-1')")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(UrlFileError, match="per-media keys"):
        detect_archive_type(archive)
