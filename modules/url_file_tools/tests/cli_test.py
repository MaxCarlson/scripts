import sqlite3
from pathlib import Path

from url_file_tools.cli import main


def test_merge_dry_run_writes_nothing_and_prints_stats(tmp_path: Path, capsys) -> None:
    (tmp_path / "one.txt").write_text(
        "1. https://m.example.com/a\nhttps://example.com/a\nhttps://other.net/b\n",
        encoding="utf-8",
    )

    assert main(["merge", "-p", str(tmp_path), "-D", "remove"]) == 0

    output = capsys.readouterr().out
    assert "Mode: Dry run" in output
    assert "Duplicate occurrences      : 1" in output
    assert "Unique base domains        : 2" in output
    assert "Mobile m. prefixes removed : 1" in output
    assert not (tmp_path / "merged_urls.txt").exists()


def test_split_apply_creates_one_deduplicated_file_per_domain(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text(
        "https://m.example.com/a\nhttps://example.com/a\nhttps://www.other.net/b\n",
        encoding="utf-8",
    )
    output = tmp_path / "by-domain"

    assert main(["merge", "-p", str(tmp_path), "-s", "-o", str(output), "-D", "remove", "-a"]) == 0

    assert (output / "example.com.txt").read_text(encoding="utf-8") == "https://example.com/a\n"
    assert (output / "other.net.txt").read_text(encoding="utf-8") == "https://www.other.net/b\n"
    assert "https://example.com/a" in (output / "_duplicates.txt").read_text(encoding="utf-8")


def test_normalize_apply_creates_backup_and_rewrites(tmp_path: Path) -> None:
    path = tmp_path / "links.txt"
    path.write_text("1. A\n2. A\n3. B\n", encoding="utf-8")

    assert main(["normalize", "-p", str(path), "-u", "-b", "-a"]) == 0

    assert path.read_text(encoding="utf-8") == "A\nB\n"
    assert len(list(tmp_path.glob("links.txt.*.bak"))) == 1


def test_archive_match_dry_run_does_not_write_reports(tmp_path: Path, capsys) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "links.txt").write_text("https://example.com/a\nhttps://example.com/b\n", encoding="utf-8")
    archive = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(archive)
    try:
        connection.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, canonical_url TEXT, state TEXT, updated REAL)")
        connection.execute(
            "INSERT INTO jobs(canonical_url,state,updated) VALUES(?,?,?)",
            ("https://example.com/a", "skipped_archive", 1.0),
        )
        connection.commit()
    finally:
        connection.close()

    assert main(["archive", "match", "-p", str(inputs), "-a", str(archive)]) == 0

    output = capsys.readouterr().out
    assert "Downloaded                 : 1" in output
    assert "Not downloaded             : 1" in output
    assert not (inputs / "archive_match").exists()
