import sqlite3
from pathlib import Path

from mangadl.archive_ui import filter_records, load_archive, render_archive_browser
from mangadl.ui import visible_len


def test_archive_reader_filter_and_render(tmp_path: Path) -> None:
    archive = tmp_path / "archive.sqlite3"
    connection = sqlite3.connect(archive)
    try:
        connection.execute(
            "CREATE TABLE archive(extractor TEXT, category TEXT, directory TEXT, filename TEXT)"
        )
        connection.executemany(
            "INSERT INTO archive VALUES(?,?,?,?)",
            [
                ("manga18fx", "manga", "Example One", "0001.jpg"),
                ("gallery-dl", "gallery", "Different Work", "0002.webp"),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    snapshot = load_archive(archive)
    filtered = filter_records(snapshot.records, "example manga18fx")
    output = render_archive_browser(
        snapshot,
        filtered,
        selected=0,
        query="example manga18fx",
        width=140,
        height=24,
    )

    assert snapshot.columns == ("extractor", "category", "directory", "filename")
    assert len(snapshot.records) == 2
    assert len(filtered) == 1
    assert "Example One" in output
    assert "Different Work" not in output
    assert "Records 1/2" in output
    assert all(visible_len(line) <= 140 for line in output.splitlines())


def test_archive_reader_handles_database_without_archive_table(tmp_path: Path) -> None:
    archive = tmp_path / "other.sqlite3"
    connection = sqlite3.connect(archive)
    try:
        connection.execute("CREATE TABLE metadata(key TEXT, value TEXT)")
        connection.commit()
    finally:
        connection.close()

    snapshot = load_archive(archive)

    assert snapshot.tables == ("metadata",)
    assert snapshot.columns == ()
    assert snapshot.records == ()
