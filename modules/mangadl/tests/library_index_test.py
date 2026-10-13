from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from mangadl.library_index import (
    backfill_source_indexes,
    read_source_manifest,
    resolve_url_folders,
    scan_library,
    write_source_manifest,
)


def test_manifest_is_atomic_versioned_and_resolves_exact_source(tmp_path: Path) -> None:
    folder = tmp_path / "Some Manga"
    folder.mkdir()
    target = write_source_manifest(folder, "https://example.test/manga/a", "gallery-dl")

    assert target.name == ".mangadl-source.json"
    manifest = read_source_manifest(folder)
    assert manifest == {
        "backend": "gallery-dl",
        "canonical_url": "https://example.test/manga/a",
        "expected_pages": None,
        "folder_name": "Some Manga",
        "identity_evidence": "download_success",
        "schema": 1,
    }
    assert not list(folder.glob(".mangadl-source-*.tmp"))

    rows = scan_library([tmp_path])
    assert [row.path for row in resolve_url_folders("https://example.test/manga/a", rows)] == [folder]


def test_invalid_manifest_falls_back_to_existing_metadata(tmp_path: Path) -> None:
    folder = tmp_path / "Legacy"
    folder.mkdir()
    (folder / ".mangadl-source.json").write_text("not json", encoding="utf-8")
    (folder / "info.json").write_text(json.dumps({"url": "https://example.test/legacy"}), encoding="utf-8")
    Image.new("RGB", (1, 1)).save(folder / "001.jpg")

    rows = scan_library([tmp_path])

    assert rows[0].source_url == "https://example.test/legacy"
    assert rows[0].evidence == "gallery_metadata"


def test_duplicate_metadata_urls_are_ambiguous_and_not_resolved(tmp_path: Path) -> None:
    for name in ("one", "two"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "info.json").write_text(json.dumps({"url": "https://example.test/shared"}), encoding="utf-8")
        Image.new("RGB", (1, 1)).save(folder / "001.jpg")

    rows = scan_library([tmp_path])

    assert len(resolve_url_folders("https://example.test/shared", rows)) == 2


def test_backfill_adds_exact_metadata_pair_once(tmp_path: Path) -> None:
    folder = tmp_path / "Legacy Series"
    folder.mkdir()
    (folder / "info.json").write_text(json.dumps({"url": "https://example.test/series"}), encoding="utf-8")
    Image.new("RGB", (1, 1)).save(folder / "001.jpg")
    rows = scan_library([tmp_path])

    first = backfill_source_indexes(["https://example.test/series"], rows)
    second = backfill_source_indexes(["https://example.test/series"], scan_library([tmp_path]))

    assert first["created"] == 1
    assert second["already_indexed"] == 1
    manifest = read_source_manifest(folder)
    assert manifest is not None
    assert manifest["canonical_url"] == "https://example.test/series"
    assert manifest["identity_evidence"] == "gallery_metadata"


def test_backfill_uses_only_unique_deterministic_identity_and_skips_ambiguous(tmp_path: Path) -> None:
    unique = tmp_path / "nhentai-42 - Unique"
    unique.mkdir()
    Image.new("RGB", (1, 1)).save(unique / "001.jpg")
    for name in ("nhentai-43 - Copy A", "nhentai-43 - Copy B"):
        folder = tmp_path / name
        folder.mkdir()
        Image.new("RGB", (1, 1)).save(folder / "001.jpg")
    rows = scan_library([tmp_path])

    summary = backfill_source_indexes(
        ["https://nhentai.net/g/42/", "https://nhentai.net/g/43/", "https://nhentai.net/g/44/"], rows
    )

    assert summary["created"] == 1
    assert summary["ambiguous"] == 1
    assert summary["unresolved"] == 1
    assert read_source_manifest(unique)["identity_evidence"] == "nhentai_gallery_id"
    assert not (tmp_path / "nhentai-43 - Copy A" / ".mangadl-source.json").exists()


def test_folder_name_fallback_cannot_override_known_different_source(tmp_path: Path) -> None:
    folder = tmp_path / "nhentai-42 - Wrong source"
    folder.mkdir()
    Image.new("RGB", (1, 1)).save(folder / "001.jpg")
    write_source_manifest(folder, "https://nhentai.net/g/99/", "gallery-dl")

    matches = resolve_url_folders("https://nhentai.net/g/42/", scan_library([tmp_path]))

    assert matches == []


def test_backfill_preserves_empty_and_conflicting_manifest_folders(tmp_path: Path) -> None:
    empty = tmp_path / "nhentai-51 - Empty"
    empty.mkdir()
    conflicting = tmp_path / "nhentai-52 - Conflict"
    conflicting.mkdir()
    Image.new("RGB", (1, 1)).save(conflicting / "001.jpg")
    write_source_manifest(conflicting, "https://nhentai.net/g/99/", "gallery-dl")
    rows = scan_library([tmp_path])

    summary = backfill_source_indexes(
        ["https://nhentai.net/g/51/", "https://nhentai.net/g/52/"], rows
    )

    assert summary["empty_folder"] == 1
    assert summary["unresolved"] == 1
    assert read_source_manifest(conflicting)["canonical_url"] == "https://nhentai.net/g/99/"
