from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from mangadl.repair_pages import apply_page_repair, make_page_repair_plan, repair_confirmation_token


def _archive(path: Path, rows: list[str]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE archive (entry TEXT PRIMARY KEY) WITHOUT ROWID")
        connection.executemany("INSERT INTO archive(entry) VALUES (?)", [(row,) for row in rows])
        connection.commit()
    finally:
        connection.close()


def _rows(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute("SELECT entry FROM archive")}
    finally:
        connection.close()


def test_page_repair_preview_maps_exact_archive_rows_without_mutating(tmp_path: Path) -> None:
    folder = tmp_path / "nhentai-1 - title"
    folder.mkdir()
    archive = tmp_path / "archive.sqlite3"
    _archive(archive, ["nhentai 1_1", "nhentai 1_2", "other 3"])

    plan = make_page_repair_plan(
        "https://nhentai.net/g/1/",
        folder,
        2,
        [2],
        [],
        {1: "nhentai 1_1", 2: "nhentai 1_2"},
        archive,
    )

    assert plan.eligible
    assert plan.archive_rows_found == ("nhentai 1_2",)
    assert _rows(archive) == {"nhentai 1_1", "nhentai 1_2", "other 3"}


def test_page_repair_quarantines_corrupt_image_and_restores_exact_archive_identity(tmp_path: Path) -> None:
    folder = tmp_path / "nhentai-1 - title"
    folder.mkdir()
    corrupt = folder / "002.jpg"
    corrupt.write_bytes(b"bad image")
    archive = tmp_path / "archive.sqlite3"
    _archive(archive, ["nhentai 1_1", "nhentai 1_2", "other 3"])
    plan = make_page_repair_plan(
        "https://nhentai.net/g/1/",
        folder,
        2,
        [2],
        ["002.jpg"],
        {1: "nhentai 1_1", 2: "nhentai 1_2"},
        archive,
    )

    def download(file_range: str, token: str) -> None:
        assert file_range == "2"
        assert token
        Image.new("RGB", (1, 1), "white").save(folder / "002.jpg")

    result = apply_page_repair(
        plan,
        archive,
        tmp_path / ".mangadl" / "repair-quarantine",
        download,
        lambda: (True, set()),
    )

    assert result["verified"] is True
    assert result["archive_backup"] and Path(result["archive_backup"]).is_file()
    assert Path(result["quarantine"], "repair-manifest.json").is_file()
    manifest = json.loads(Path(result["quarantine"], "repair-manifest.json").read_text(encoding="utf-8"))
    assert manifest["target_pages"] == [2]
    assert _rows(archive) == {"nhentai 1_1", "nhentai 1_2", "other 3"}
    assert Image.open(folder / "002.jpg").verify() is None
    assert not (tmp_path / ".mangadl" / "repair.lock").exists()


def test_page_repair_refuses_incomplete_archive_page_mapping(tmp_path: Path) -> None:
    folder = tmp_path / "gallery"
    folder.mkdir()
    archive = tmp_path / "archive.sqlite3"
    _archive(archive, [])
    plan = make_page_repair_plan(
        "https://nhentai.net/g/1/", folder, 2, [2], [], {1: "key-1"}, archive
    )

    assert not plan.eligible
    with pytest.raises(ValueError, match="not eligible"):
        apply_page_repair(plan, archive, tmp_path / "q", lambda *_: None, lambda: (False, {2}))


def test_missing_only_repair_creates_manifest_before_download(tmp_path: Path) -> None:
    folder = tmp_path / "gallery"
    folder.mkdir()
    archive = tmp_path / "archive.sqlite3"
    _archive(archive, ["nhentai 1_1", "nhentai 1_2", "other 3"])
    plan = make_page_repair_plan(
        "https://nhentai.net/g/1/", folder, 2, [2], [],
        {1: "nhentai 1_1", 2: "nhentai 1_2"}, archive,
    )
    quarantine_root = tmp_path / "q"

    def download(file_range: str, token: str) -> None:
        manifests = list(quarantine_root.glob("*/repair-manifest.json"))
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        assert manifest["folder"] == str(folder)
        assert manifest["quarantined_files"] == []
        assert file_range == "2" and token
        assert _rows(archive) == {"nhentai 1_1", "other 3"}
        Image.new("RGB", (1, 1), "white").save(folder / "002.jpg")

    result = apply_page_repair(plan, archive, quarantine_root, download, lambda: (True, set()))

    assert result["verified"] is True
    assert len(Path(result["quarantine"]).relative_to(quarantine_root).parts) == 1
    assert _rows(archive) == {"nhentai 1_1", "nhentai 1_2", "other 3"}
    assert not (tmp_path / "repair.lock").exists()


def test_manifest_failure_preserves_archive_keys(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "gallery"
    folder.mkdir()
    archive = tmp_path / "archive.sqlite3"
    original_rows = {"nhentai 1_1", "nhentai 1_2", "other 3"}
    _archive(archive, list(original_rows))
    plan = make_page_repair_plan(
        "https://nhentai.net/g/1/", folder, 2, [2], [],
        {1: "nhentai 1_1", 2: "nhentai 1_2"}, archive,
    )
    original_write = Path.write_text

    def fail_manifest(path, *args, **kwargs):
        if path.name == "repair-manifest.json":
            raise OSError("manifest write failed")
        return original_write(path, *args, **kwargs)

    def unexpected_download(*_args):
        pytest.fail("download must not start after manifest failure")

    monkeypatch.setattr(Path, "write_text", fail_manifest)
    with pytest.raises(OSError, match="manifest write failed"):
        apply_page_repair(plan, archive, tmp_path / "q", unexpected_download, lambda: (True, set()))

    assert _rows(archive) == original_rows
    assert not (tmp_path / "repair.lock").exists()


def test_repair_confirmation_token_is_bound_to_exact_targets(tmp_path: Path) -> None:
    folder = tmp_path / "gallery"
    folder.mkdir()
    archive = tmp_path / "archive.sqlite3"
    keys = {page: f"nhentai 1_{page}" for page in range(1, 4)}
    plan = make_page_repair_plan("https://nhentai.net/g/1/", folder, 3, [2], [], keys, archive)
    same_plan = make_page_repair_plan("https://nhentai.net/g/1/", folder, 3, [2], [], keys, archive)
    changed_plan = make_page_repair_plan(
        "https://nhentai.net/g/1/", folder, 3, [3], [], keys, archive
    )
    assert repair_confirmation_token(plan) == repair_confirmation_token(same_plan)
    assert repair_confirmation_token(plan) != repair_confirmation_token(changed_plan)


def test_page_repair_refuses_placeholder_and_repeated_keys(tmp_path: Path) -> None:
    folder = tmp_path / "gallery"
    folder.mkdir()
    for keys in ({1: "None", 2: "None"}, {1: "same-key", 2: "same-key"}):
        plan = make_page_repair_plan(
            "https://nhentai.net/g/1/", folder, 2, [2], [], keys, tmp_path / "archive.sqlite3",
        )
        assert not plan.eligible
