"""Snapshot reuse must never silently substitute stale sources or populations."""

import json
import os
from pathlib import Path
import sqlite3

import pytest
from PIL import Image

from cli_test_support import main


def test_trusted_analysis_skips_discovery_and_labels_saved_population(
    tmp_path, monkeypatch, capsys
):
    import compresser.scanner as scanner

    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40)).save(root / "01.png")
    args = ["-i", str(root), "-I", str(tmp_path / "state")]
    assert main([*args, "-l"]) == 0
    capsys.readouterr()
    Image.new("RGB", (40, 40)).save(root / "02.png")

    def forbidden(*a, **k):
        pytest.fail("Trusted mode enumerated the library")

    monkeypatch.setattr(scanner, "observe_files", forbidden)
    assert main([*args, "-U", "trust", "-f", "png", "-e", "0", "-J"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (
        report["total_images"] == 1
    )  # Newly added pages are deliberately not discovered.
    snapshot = report["inventory_snapshot"]
    assert snapshot["policy"] == "trust"
    assert snapshot["membership_verified"] is False
    assert snapshot["selected_files_validated"] == 1
    assert snapshot["age_seconds"] >= 0
    assert snapshot["completed"]
    assert "saved snapshot" in report["estimate"]["population_warning"].lower()


@pytest.mark.parametrize("change", ["delete", "replace"])
def test_trust_rejects_selected_source_changes_before_cached_trials(
    tmp_path, capsys, change
):
    root = tmp_path / "library"
    root.mkdir()
    page = root / "01.png"
    Image.new("RGB", (40, 40)).save(page)
    args = [
        "-i",
        str(root),
        "-I",
        str(tmp_path / "state"),
        "-f",
        "png",
        "-e",
        "0",
        "-J",
    ]
    assert main(args) == 0  # Populate both snapshot and trial cache.
    capsys.readouterr()
    page.unlink()
    if change == "replace":
        Image.new("RGB", (50, 50)).save(page)
    assert main([*args, "-U", "trust"]) == 2
    assert "refresh" in capsys.readouterr().err.lower()


def test_missing_and_file_only_snapshots_cannot_be_trusted(tmp_path, capsys):
    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40)).save(root / "01.png")
    args = ["-i", str(root), "-I", str(tmp_path / "state")]
    assert main([*args, "-U", "trust", "-J"]) == 2
    assert "refresh" in capsys.readouterr().err.lower()
    assert main([*args, "-l", "-D", "files"]) == 0
    capsys.readouterr()
    assert main([*args, "-U", "trust", "-J"]) == 2
    assert "refresh" in capsys.readouterr().err.lower()


@pytest.mark.parametrize(
    "operation,extra,match",
    [
        ("apply", ["-U", "snapshot", "-w"], "apply requires inventory refresh"),
        ("inventory", ["-U", "snapshot"], "unrecognized arguments"),
        ("recover", ["-U", "snapshot"], "unrecognized arguments"),
        ("preview", ["-U", "snapshot"], "preview requires inventory refresh"),
    ],
)
def test_snapshot_reuse_is_only_available_to_analysis(tmp_path, capsys, operation, extra, match):
    with pytest.raises(SystemExit) as result:
        main([operation, "-i", str(tmp_path), *extra])
    assert result.value.code == 2
    assert match in capsys.readouterr().err


@pytest.mark.parametrize("damage", ["status", "policy", "escape", "metadata"])
def test_incompatible_or_invalid_snapshot_is_refused(tmp_path, capsys, damage):
    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40)).save(root / "01.png")
    path = tmp_path / "state" / ".compresser" / "library" / "inventory.sqlite3"
    args = ["-i", str(root), "-I", str(tmp_path / "state")]
    assert main([*args, "-l"]) == 0
    capsys.readouterr()
    with sqlite3.connect(path) as db:
        report = json.loads(
            db.execute("SELECT report FROM inventory_selections").fetchone()[0]
        )
        if damage == "status":
            report["status"] = "incomplete"
        elif damage == "policy":
            report["policy"] = "old scanner"
        elif damage == "escape":
            report["images"][0]["metadata"]["path"] = str(tmp_path / "outside.png")
        else:
            report["images"][0]["metadata"]["width"] = -1
        db.execute("UPDATE inventory_selections SET report=?", (json.dumps(report),))
    assert main([*args, "-U", "trust", "-J"]) == 2
    assert "refresh" in capsys.readouterr().err.lower()


def test_trusted_comparison_rechecks_sources_between_stages(
    tmp_path, capsys, monkeypatch
):
    from compresser.engine import CompressionEngine

    root = tmp_path / "library"
    root.mkdir()
    page = root / "01.png"
    Image.new("RGB", (40, 40)).save(page)
    args = ["-i", str(root), "-I", str(tmp_path / "state")]
    assert main([*args, "-l"]) == 0
    capsys.readouterr()
    real_batch = CompressionEngine.compress_batch

    def change_after_first_stage(self, *a, **k):
        result = real_batch(self, *a, **k)
        Image.new("RGB", (50, 50)).save(page)
        return result

    monkeypatch.setattr(CompressionEngine, "compress_batch", change_after_first_stage)
    assert main([*args, "-U", "trust", "-c", "-e", "0", "-J"]) == 2
    assert "refresh" in capsys.readouterr().err.lower()


def test_aborted_refresh_preserves_whole_snapshot(tmp_path, monkeypatch, capsys):
    import compresser.scanner as scanner

    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40)).save(root / "01.png")
    path = tmp_path / "state" / ".compresser" / "library" / "inventory.sqlite3"
    args = ["-i", str(root), "-I", str(tmp_path / "state"), "-l"]
    assert main(args) == 0
    capsys.readouterr()
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT report FROM inventory_selections").fetchall()

    def interrupted(*a, **k):
        raise PermissionError("blocked enumeration")

    monkeypatch.setattr(scanner, "observe_files", interrupted)
    assert main(args) == 2
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT report FROM inventory_selections").fetchall() == before
        )


def test_trusted_selected_link_is_refused(tmp_path, capsys):
    root = tmp_path / "library"
    root.mkdir()
    page = root / "01.png"
    outside = tmp_path / "outside.png"
    Image.new("RGB", (40, 40)).save(page)
    outside.write_bytes(page.read_bytes())
    args = ["-i", str(root), "-I", str(tmp_path / "state")]
    assert main([*args, "-l"]) == 0
    capsys.readouterr()
    page.unlink()
    try:
        os.symlink(outside, page)
    except OSError as exc:
        pytest.skip(f"Symlink permission unavailable: {exc}")
    assert main([*args, "-U", "trust", "-J"]) == 2
    error = capsys.readouterr().err.lower()
    assert "linked" in error and "refresh" in error


def test_trusted_text_warns_about_snapshot_age_and_membership(tmp_path, capsys):
    Image.new("RGB", (40, 40)).save(tmp_path / "01.png")
    args = ["-i", str(tmp_path), "-I", str(tmp_path.parent / f"{tmp_path.name}-state")]
    assert main([*args, "-l"]) == 0
    capsys.readouterr()
    assert main([*args, "-U", "trust", "-f", "png", "-e", "0", "-N"]) == 0
    report = capsys.readouterr().out
    assert "Saved snapshot UTC" in report and "Snapshot age (seconds)" in report
    assert "Use -U refresh to update." in " ".join(report.replace("│", " ").split())


def test_trusted_sampling_does_not_resolve_every_unselected_source(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "library"
    root.mkdir()
    for index in range(5):
        Image.new("RGB", (40, 40)).save(root / f"{index}.png")
    args = ["-i", str(root), "-I", str(tmp_path / "state")]
    assert main([*args, "-l"]) == 0
    capsys.readouterr()
    resolve = Path.resolve
    resolved_images = set()

    def no_image_resolution(path, *a, **k):
        if path.suffix == ".png":
            resolved_images.add(path)
        return resolve(path, *a, **k)

    monkeypatch.setattr(Path, "resolve", no_image_resolution)
    assert main([*args, "-U", "trust", "-s", "1", "-f", "png", "-e", "0", "-J"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total_images"] == 1
    assert report["inventory_snapshot"]["selected_files_validated"] == 1
    assert (
        len(resolved_images) == 1
    )  # Cache identities may resolve selected sources, never the other four.
