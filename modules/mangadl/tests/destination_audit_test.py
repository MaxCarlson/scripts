import json
from pathlib import Path

from mangadl.cli import main
from mangadl.destination_audit import audit_destinations
from mangadl.input import collect_inputs


def _gallery(root: Path, name: str, *, metadata_url: str | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "001.jpg").write_bytes(b"image")
    if metadata_url:
        (folder / "info.json").write_text(json.dumps({"url": metadata_url}), encoding="utf-8")
    return folder


def test_audit_multiple_files_and_destinations_with_duplicates(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _gallery(first, "nhentai-123 - Present")
    _gallery(first, "shared title", metadata_url="https://example.com/gallery/one")
    _gallery(second, "shared title", metadata_url="https://example.com/gallery/one")
    _gallery(second, "manhwa title")
    urls_one = tmp_path / "one.txt"
    urls_two = tmp_path / "two.txt"
    urls_one.write_text("123\nhttps://example.com/gallery/one\n", encoding="utf-8")
    urls_two.write_text(
        "https://hdporncomics.com/manhwa/manhwa-title/\nhttps://example.com/missing\n", encoding="utf-8"
    )
    inputs, rejected = collect_inputs([urls_one, urls_two], [])
    audit = audit_destinations(inputs, [first, second])
    assert rejected == []
    assert {item.canonical_url for item in audit.unresolved} == {"https://example.com/missing"}
    assert len(audit.resolved) == 3
    assert [path.name for path in audit.duplicates["shared title"]] == ["shared title", "shared title"]


def test_audit_cli_writes_missing_urls_and_duplicate_locations(tmp_path: Path, capsys) -> None:
    destination = tmp_path / "downloads"
    _gallery(destination, "nhentai-5 - Present")
    urls = tmp_path / "urls.txt"
    missing = tmp_path / "outputs" / "missing.txt"
    duplicates = tmp_path / "outputs" / "duplicates.json"
    urls.write_text("5\n6\n", encoding="utf-8")
    assert (
        main(
            [
                "audit-destinations",
                "-i",
                str(urls),
                "-d",
                str(destination),
                "-o",
                str(missing),
                "-p",
                str(duplicates),
                "-j",
            ]
        )
        == 0
    )
    assert missing.read_text(encoding="utf-8") == "6\n"
    assert json.loads(duplicates.read_text(encoding="utf-8")) == []
    assert '"resolved": 1' in capsys.readouterr().out


def test_audit_expands_input_globs_and_reports_progress(tmp_path: Path, capsys) -> None:
    destination = tmp_path / "downloads"
    _gallery(destination, "nhentai-7 - Present")
    (tmp_path / "urls1.txt").write_text("7\n", encoding="utf-8")
    (tmp_path / "urls2.txt").write_text("8\n", encoding="utf-8")
    missing = tmp_path / "missing.txt"
    duplicates = tmp_path / "duplicates.json"
    assert (
        main(
            [
                "audit",
                "-i",
                str(tmp_path / "urls*.txt"),
                "-d",
                str(destination),
                "-o",
                str(missing),
                "-p",
                str(duplicates),
                "-j",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert missing.read_text(encoding="utf-8") == "8\n"
    assert '"input_urls": 2' in captured.out
    assert "Audit: Loading 2 URL file(s)" in captured.err
    assert "Audit: Matching complete: 1 found, 1 missing" in captured.err
