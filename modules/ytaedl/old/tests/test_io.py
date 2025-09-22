"""
Tests for the io.py module.
"""
from pathlib import Path
from ytaedl.io import read_urls_from_files, load_archive, write_to_archive

def test_read_urls_from_files(tmp_path: Path):
    # Create dummy url files
    file1 = tmp_path / "file1.txt"
    file1.write_text(
        "# This is a comment\n"
        "http://example.com/a\n"
        "http://example.com/b  ; inline comment\n"
        "\n"
        "http://example.com/a  # duplicate\n"
    )
    file2 = tmp_path / "file2.txt"
    file2.write_text("http://example.com/c")
    
    # Test reading from multiple files
    urls = read_urls_from_files([file1, file2])
    assert urls == ["http://example.com/a", "http://example.com/b", "http://example.com/c"]

    # Test with a non-existent file
    urls_with_bad_file = read_urls_from_files([file1, tmp_path / "nonexistent.txt"])
    assert urls_with_bad_file == ["http://example.com/a", "http://example.com/b"]

def test_archive_functions(tmp_path: Path):
    archive_file = tmp_path / "archive.txt"

    # 1. Test loading a non-existent archive
    assert load_archive(archive_file) == set()

    # 2. Write to the archive
    write_to_archive(archive_file, "http://example.com/1")
    write_to_archive(archive_file, "http://example.com/2 ") # with trailing space

    # 3. Load the archive and check contents
    archive_content = load_archive(archive_file)
    assert archive_content == {"http://example.com/1", "http://example.com/2"}

    # 4. Write another URL
    write_to_archive(archive_file, "http://example.com/3")
    assert load_archive(archive_file) == {"http://example.com/1", "http://example.com/2", "http://example.com/3"}

