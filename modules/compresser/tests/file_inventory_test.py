import json
import sqlite3
from pathlib import Path

from PIL import Image
import pytest

from cli_test_support import main


def test_files_inventory_counts_bytes_without_opening_images(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "library"
    (root / "a").mkdir(parents=True)
    (root / "b" / "chapter").mkdir(parents=True)
    (root / "a" / "01.JPG").write_bytes(b"12345")
    (root / "a" / "02.webp").write_bytes(b"1234567")
    (root / "b" / "chapter" / "01.png").write_bytes(b"123")
    (root / "notes.txt").write_text("not an image")
    (root / "_partial").mkdir()
    (root / "_partial" / "skip.jpg").write_bytes(b"ignored")

    def forbidden(*args, **kwargs):
        pytest.fail("Filesystem-only scan opened image content")

    monkeypatch.setattr(Image, "open", forbidden)
    database = tmp_path / "state" / ".compresser" / "library" / "inventory.sqlite3"
    assert (
        main(["-i", str(root), "-l", "-D", "files", "-I", str(tmp_path / "state")]) == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["candidate_images"] == 3
    assert report["candidate_bytes"] == 15
    assert report["content_verified"] is False
    assert report["galleries"]["a"]["extensions"] == {
        ".jpg": {"files": 1, "bytes": 5},
        ".webp": {"files": 1, "bytes": 7},
    }
    assert report["galleries"]["b"]["candidate_images"] == 1
    with sqlite3.connect(database) as connection:
        saved = json.loads(
            connection.execute(
                "SELECT report FROM inventory_file_snapshots"
            ).fetchone()[0]
        )
        assert saved["candidate_images"] == 3
    (root / "a" / "01.JPG").unlink()
    assert (
        main(["-i", str(root), "-l", "-D", "files", "-I", str(tmp_path / "state")]) == 0
    )
    assert json.loads(capsys.readouterr().out)["candidate_bytes"] == 10


def test_files_depth_is_inventory_only(tmp_path):
    from compresser.cli import build_parser
    from compresser.arguments import normalize_compression_arguments

    source = tmp_path / "01.png"
    source.write_bytes(b"not verified")
    args = build_parser().parse_args(["analyze", "-i", str(source)])
    args.inventory_depth = "files"
    with pytest.raises(ValueError):
        normalize_compression_arguments(args)


def test_stat_failure_reports_unknown_totals_instead_of_zero(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "library"
    root.mkdir()
    source = root / "01.jpg"
    source.write_bytes(b"12345")
    original = Path.lstat

    def denied(path, *args, **kwargs):
        if path == source:
            raise PermissionError("test file stat denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", denied)
    assert (
        main(["-i", str(root), "-l", "-D", "files", "-I", str(tmp_path / "state")]) == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["candidate_images"] == 1
    assert report["candidate_bytes"] is None
    assert report["totals_complete"] is False
    assert len(report["stat_errors"]) == 1


def test_failed_enumeration_preserves_last_complete_snapshot(
    tmp_path, monkeypatch, capsys
):
    import compresser.file_inventory as inventory

    root = tmp_path / "library"
    root.mkdir()
    (root / "01.jpg").write_bytes(b"12345")
    database = tmp_path / "state" / ".compresser" / "library" / "inventory.sqlite3"
    args = ["-i", str(root), "-l", "-D", "files", "-I", str(tmp_path / "state")]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["candidate_images"] == 1
    # Current-run diagnostics belong to the CLI response, not the saved population.
    # Compare durable snapshots directly to prove a failed refresh changes no bytes.
    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT report FROM inventory_file_snapshots"
        ).fetchone()[0]

    def interrupted(*args, **kwargs):
        raise PermissionError("test directory enumeration denied")
        yield

    monkeypatch.setattr(inventory.os, "walk", interrupted)
    assert main(args) == 2
    with sqlite3.connect(database) as connection:
        saved = connection.execute(
            "SELECT report FROM inventory_file_snapshots"
        ).fetchone()[0]
    assert saved == before
