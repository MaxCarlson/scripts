import json
from pathlib import Path

from PIL import Image

from mangadl.cli import main
from mangadl import cli_core
from mangadl.destination_audit import audit_destinations
from mangadl.input import collect_inputs
from mangadl.library_index import read_source_manifest
from mangadl.page_adapters import ExpectedPages


def _gallery(root: Path, name: str, *, metadata_url: str | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    Image.new("RGB", (1, 1), "white").save(folder / "001.jpg")
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


def test_audit_url_file_short_option_is_read_only_and_marks_completeness_unknown(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli_core, "resolve_nhentai_metadata", lambda _gallery_id: (_ for _ in ()).throw(OSError("offline")))
    destination = tmp_path / "downloads"
    _gallery(destination, "nhentai-7 - Present")
    urls = tmp_path / "urls.txt"
    urls.write_text("7\n8\n", encoding="utf-8")

    assert main(["audit", "-u", str(urls), "-d", str(destination), "-j", "-q"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [(item["status"], item["completeness"], item["image_integrity"]) for item in payload["items"]] == [
        ("matched", "unknown", "valid"),
        ("missing", "unknown", "unverified"),
    ]
    assert payload["items"][0]["source"] == str(urls)
    assert payload["items"][0]["line"] == 1
    assert payload["items"][0]["repair_eligible"] is False
    assert payload["missing_output"] is None
    assert payload["duplicates_output"] is None
    assert set(path.name for path in destination.iterdir()) == {"nhentai-7 - Present"}


def test_audit_url_file_long_alias_and_ambiguous_match(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli_core, "resolve_nhentai_metadata", lambda _gallery_id: (_ for _ in ()).throw(OSError("offline")))
    first = tmp_path / "first"
    second = tmp_path / "second"
    _gallery(first, "nhentai-7 - Present")
    _gallery(second, "nhentai-7 - Present")
    urls = tmp_path / "urls.txt"
    urls.write_text("7\n", encoding="utf-8")

    assert main(["audit", "--url-file", str(urls), "-d", str(first), "-d", str(second), "-j", "-q"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["items"][0]["status"] == "ambiguous"
    assert len(payload["items"][0]["folders"]) == 2


def test_audit_finds_truncated_nhentai_gallery_and_bad_images(tmp_path: Path) -> None:
    destination = tmp_path / "downloads"
    folder = destination / "nhentai-633374 - Paradise"
    folder.mkdir(parents=True)
    for page in range(159, 193):
        Image.new("RGB", (1, 1), "white").save(folder / f"{page}.webp", format="WEBP")
    (folder / "175.webp").write_bytes(b"truncated")
    inputs, _ = collect_inputs([], ["https://nhentai.net/g/633374/"])

    audit = audit_destinations(
        inputs,
        [destination],
        metadata_resolver=lambda _gallery_id: type("Metadata", (), {"page_count": 192})(),
    )

    detail = audit.details[inputs[0].canonical_url]
    assert detail["completeness"] == "incomplete"
    assert detail["expected_images"] == 192
    assert detail["missing_pages"] == sorted([*range(1, 159), 175])
    assert detail["corrupt_pages"] == [175]
    assert detail["repair_eligible"] is False


def test_audit_without_metadata_detects_leading_numbered_gap(tmp_path: Path) -> None:
    destination = tmp_path / "downloads"
    folder = destination / "nhentai-633374 - Paradise"
    folder.mkdir(parents=True)
    for page in range(159, 193):
        Image.new("RGB", (1, 1), "white").save(folder / f"{page}.webp", format="WEBP")
    inputs, _ = collect_inputs([], ["https://nhentai.net/g/633374/"])

    audit = audit_destinations(inputs, [destination])

    detail = audit.details[inputs[0].canonical_url]
    assert detail["completeness"] == "incomplete"
    assert detail["missing_pages"] == list(range(1, 159))


def test_folder_only_audit_reports_unknown_source_and_page_total(tmp_path: Path, capsys) -> None:
    destination = tmp_path / "downloads"
    _gallery(destination, "legacy title")

    assert main(["audit", "-d", str(destination), "-j", "-q"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "folder-only"
    assert payload["folders"] == 1
    assert payload["unknown"] == 1
    assert payload["items"][0]["identity_status"] == "unknown"
    assert payload["items"][0]["completeness"] == "unknown"


def test_audit_uses_enumerated_page_ids_to_find_missing_middle_pages(tmp_path: Path) -> None:
    destination = tmp_path / "downloads"
    folder = destination / "manga"
    folder.mkdir(parents=True)
    (folder / "info.json").write_text(json.dumps({"url": "https://example.test/manga"}), encoding="utf-8")
    Image.new("RGB", (1, 1), "white").save(folder / "001.jpg")
    Image.new("RGB", (1, 1), "white").save(folder / "003.jpg")
    inputs, _ = collect_inputs([], ["https://example.test/manga"])

    audit = audit_destinations(
        inputs,
        [destination],
        page_resolver=lambda _url: ExpectedPages(3, (1, 2, 3), "mock extractor", True),
    )

    detail = audit.details[inputs[0].canonical_url]
    assert detail["expected_images"] == 3
    assert detail["missing_pages"] == [2]
    assert detail["completeness"] == "incomplete"


def test_url_file_audit_backfills_unique_source_index_by_default(tmp_path: Path, capsys) -> None:
    destination = tmp_path / "downloads"
    folder = _gallery(destination, "Legacy Series", metadata_url="https://example.test/series")
    urls = tmp_path / "urls.txt"
    urls.write_text("https://example.test/series\n", encoding="utf-8")

    assert main(["audit", "-i", str(urls), "-d", str(destination), "-j", "-q"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["index_backfill"]["created"] == 1
    assert read_source_manifest(folder)["canonical_url"] == "https://example.test/series"


def test_url_file_audit_can_explicitly_skip_index_backfill(tmp_path: Path, capsys) -> None:
    destination = tmp_path / "downloads"
    folder = _gallery(destination, "Legacy Series", metadata_url="https://example.test/series")
    urls = tmp_path / "urls.txt"
    urls.write_text("https://example.test/series\n", encoding="utf-8")

    assert main([
        "audit", "-i", str(urls), "-d", str(destination), "-j", "-q", "--no-index-backfill",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["index_backfill"] is None
    assert read_source_manifest(folder) is None
