from __future__ import annotations

import json
import pytest
from pathlib import Path
from PIL import Image

from mangadl.cli import build_parser, main as _main
from mangadl.compress import discover_gallery_targets
from mangadl.destination_audit import _validate_image, _inspect_pages


def test_combined_all_format_plan_persists_one_budget_and_resumes(tmp_path, capsys):
    target = tmp_path / "hent1imageperpage"
    target.mkdir()
    Image.new("RGB", (32, 32), "white").save(target / "01.png")
    base = ["-I", str(tmp_path), "-d", str(target), "-J", "-N"]
    assert _main(["compress", "inventory", *base]) == 0
    capsys.readouterr()
    args = [
        "compress",
        "plan",
        *base,
        "-f",
        "all",
        "-m",
        "both",
        "-q",
        "85",
        "70",
        "-s",
        "200",
        "-T",
        "750",
        "-M",
        "15m",
    ]
    normal_args = [value for value in args if value != "-J"]
    assert _main(normal_args) == 0
    compact = capsys.readouterr()
    assert "12 recipes" in compact.out
    assert all(value in compact.out for value in ("AUTO", "WebP", "JPEG", "AVIF", "PNG"))
    assert str(tmp_path / ".mangadl" / target.name / "reports" / "latest.md") in compact.out.replace("\n", "")
    assert "Report saved:" not in compact.out + compact.err
    assert "COMPLETED — plan" not in compact.out

    assert _main(args) == 0
    plan = json.loads(capsys.readouterr().out)["plan"]
    assert len(plan["recipes"]) == 12
    assert {r["mode"] for r in plan["recipes"]} == {"lossless", "lossy"}
    assert plan["budget"]["max_images"] == 200
    assert plan["budget"]["max_new_encodes"] == 750
    assert plan["budget"]["max_runtime_seconds"] == 900
    saved = tmp_path / ".mangadl" / target.name / "plans" / (plan["plan_id"] + ".json")
    assert saved.is_file()
    assert _main([*args, "-r", plan["plan_id"]]) == 0
    resumed = json.loads(capsys.readouterr().out)["plan"]
    assert resumed["design_identity"] == plan["design_identity"]


def test_mangadl_compress_estimate_runs_and_resumes(tmp_path, capsys):
    target = tmp_path / "hent1imageperpage"
    target.mkdir()
    Image.new("RGB", (32, 32), "white").save(target / "01.png")
    base = ["-I", str(tmp_path), "-d", str(target), "-J", "-N"]
    assert _main(["compress", "inventory", *base]) == 0
    capsys.readouterr()

    # Create plan
    plan_args = ["compress", "plan", *base, "-f", "webp", "-m", "lossy", "-q", "80"]
    assert _main(plan_args) == 0
    plan = json.loads(capsys.readouterr().out)["plan"]
    plan_id = plan["plan_id"]

    # Run estimate with -r plan_id
    est_args = ["compress", "estimate", *base, "-r", plan_id]
    assert _main(est_args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["operation"] == "estimate"
    assert out["stopping_reason"] == "complete"
    assert out["new_encodes"] > 0
    assert len(out["estimates"]) == 1
    assert out["estimates"][0]["estimated_saved_bytes"] is not None

    # Resume estimate with -r plan_id
    assert _main(est_args) == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["operation"] == "estimate"
    assert out2["new_encodes"] == 0


def main(argv):
    """Keep older engine-integration vectors while passing canonical CLI syntax.

    Public parser rejection of the removed flags is covered directly in
    compresser/tests/arguments_test.py; this adapter only selects the new
    operation for historical scenarios that test downstream ownership/codecs.
    """
    values = list(argv)
    operations = {"inventory", "plan", "estimate", "analyze", "compare", "preview", "apply", "recover"}
    if len(values) < 2 or values[0] != "compress":
        return _main(values)
    explicit = values[1] if values[1] in operations else None
    flags = values[2:] if explicit else values[1:]
    if explicit and not (
        explicit == "inventory" and any(flag in flags for flag in ("-f", "-m", "-w", "-c", "-b", "-O", "-B"))
    ):
        return _main(values)
    if "-R" in flags or "-C" in flags or "--confirm-recovery" in flags:
        operation = "recover"
    elif "-l" in flags or "-D" in flags:
        operation = "inventory"
    elif "-O" in flags:
        operation = "preview"
    elif "-b" in flags or "-c" in flags:
        operation = "compare"
    elif "-w" in flags:
        operation = "apply"
    else:
        operation = "analyze"
    if explicit:
        values.pop(1)
    values.insert(1, operation)
    translated = []
    index = 0
    while index < len(values):
        token = values[index]
        if token in ("-l", "-b", "-c", "-R"):
            index += 1
            continue
        if token == "-P" and index + 1 < len(values):
            translated.extend(("-s", values[index + 1] + "%"))
            index += 2
            continue
        translated.append({"-Q": "-q", "--confirm-recovery": "-C"}.get(token, token))
        if token == "-U" and index + 1 < len(values) and values[index + 1] == "trust":
            translated.append("snapshot")
            index += 2
            continue
        index += 1
    if operation == "compare" and "-f" not in translated:
        translated.extend(["-f", "webp", "jpeg", "auto"])
        if "-q" in translated:
            translated[2:2] = ["-m", "both"]
    return _main(translated)


@pytest.mark.parametrize("direct", [False, True])
def test_inventory_enumerates_each_directory_once(tmp_path, monkeypatch, capsys, direct):
    import os
    from collections import Counter

    root = tmp_path / "library"
    chapter = root / "manga" / "chapter"
    chapter.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(chapter / "01.png")
    if direct:
        Image.new("RGB", (40, 40)).save(root / "01.png")
    original = os.scandir
    original_listdir = os.listdir
    calls = Counter()

    def observed(path):
        resolved = Path(path).resolve()
        if resolved == root or root in resolved.parents:
            calls[resolved] += 1
        return original(path)

    monkeypatch.setattr(os, "scandir", observed)

    def listed(path):
        resolved = Path(path).resolve()
        if resolved == root or root in resolved.parents:
            calls[resolved] += 1
        return original_listdir(path)

    monkeypatch.setattr(os, "listdir", listed)
    assert main(["compress", "inventory", "-d", str(root), "-J"]) == 0
    assert json.loads(capsys.readouterr().out)["images"] == (2 if direct else 1)
    assert calls == {root: 1, root / "manga": 1, chapter: 1}


def test_compress_rejects_junction_root_before_resolution(tmp_path, monkeypatch, capsys):
    import stat
    from types import SimpleNamespace

    root = tmp_path / "library"
    root.mkdir()
    original = Path.lstat

    def junction(path, *args, **kwargs):
        if path == root:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024),
            )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", junction)
    assert main(["compress", "inventory", "-d", str(root), "-J"]) == 2
    assert "unlinked destination" in capsys.readouterr().err


def test_inventory_profile_is_not_an_implicit_sample(tmp_path, capsys):
    root = tmp_path / "library"
    chapter = root / "manga" / "chapter"
    chapter.mkdir(parents=True)
    for n in range(5):
        Image.new("RGB", (40, 40)).save(chapter / f"{n}.png")
    args = [
        "compress",
        "inventory",
        "-d",
        str(root),
        "-I",
        str(tmp_path / "state"),
        "-J",
    ]
    assert main([*args]) == 0
    profile = json.loads(capsys.readouterr().out)["sampling_profile"]
    assert profile["profile_revision"] == 2
    assert "starter_samples" not in profile
    assert "does not predict compression outcomes" in profile["limitations"]
    with pytest.raises(SystemExit):
        main(["compress", "analyze", "-d", str(root), "-s", "auto"])


def test_mangadl_pipeline_has_scan_evidence(tmp_path, capsys):
    root = tmp_path / "library"
    (root / "manga").mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(root / "manga" / "01.png")
    assert main(["compress", "inventory", "-d", str(root), "-J"]) == 0
    report = json.loads(capsys.readouterr().out)["pipeline"]
    assert report["counters"]["headers_inspected"] == 1
    assert report["settings"]["inventory_effective_workers"] == 1


def test_inventory_progress_finishes_candidate_galleries_not_nested_chapters(tmp_path, monkeypatch, capsys):
    import io
    import mangadl.compress as adapter
    from compresser.inventory_ui import InventoryProgress

    states = []

    class ObservedProgress(InventoryProgress):
        def __init__(self, *args, **kwargs):
            kwargs.update(enabled=True, interactive=False, stream=io.StringIO())
            super().__init__(*args, **kwargs)

        def finish_gallery(self, key, status="complete"):
            super().finish_gallery(key, status)
            states.append(self.snapshot())

    for name in ("a/ch1", "a/ch2", "b", "empty"):
        folder = tmp_path / name
        folder.mkdir(parents=True)
        if name != "empty":
            Image.new("RGB", (40, 40)).save(folder / "01.png")
    monkeypatch.setattr(adapter, "InventoryProgress", ObservedProgress)
    assert main(["compress", "inventory", "-d", str(tmp_path), "-J"]) == 0
    assert json.loads(capsys.readouterr().out)["images"] == 3
    assert [state["completed_galleries"] for state in states] == [1, 2, 3]
    assert states[-1]["total_galleries"] == 3
    assert states[-1]["overall_percent"] == 100


def test_interactive_inventory_publishes_snapshot_and_prints_summary(tmp_path, monkeypatch, capsys):
    import io
    import sys

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    root = tmp_path / "library"
    gallery = root / "manga"
    gallery.mkdir(parents=True)
    image = gallery / "01.png"
    Image.new("RGB", (40, 40)).save(image)
    original = image.read_bytes()
    inventory = tmp_path / "state" / ".mangadl" / "library" / "inventory.sqlite3"
    terminal = Terminal()
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.setattr(sys, "stderr", terminal)
    assert (
        main(
            [
                "compress",
                "-d",
                str(root),
                "-D",
                "headers",
                "-I",
                str(tmp_path / "state"),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["images"] == 1
    assert inventory.exists()
    assert "DISCOVERING" in terminal.getvalue()
    assert "Inventory Summary" in terminal.getvalue()
    assert "Saved inventory:" in terminal.getvalue()
    assert image.read_bytes() == original


def test_trusted_snapshot_preserves_nested_gallery_selection(tmp_path, monkeypatch, capsys):
    import mangadl.compress as adapter

    root = tmp_path / "library"
    for name in ("manga-a", "manga-b"):
        chapter = root / name / "chapter"
        chapter.mkdir(parents=True)
        Image.new("RGB", (40, 40)).save(chapter / "01.png")
        Image.new("RGB", (40, 40)).save(chapter / "cover.png")
    args = ["compress", "inventory", "-d", str(root), "-I", str(tmp_path / "state")]
    assert main([*args]) == 0
    capsys.readouterr()

    def forbidden(*a, **k):
        pytest.fail("Trust mode rediscovered galleries")

    monkeypatch.setattr(adapter, "discover_gallery_targets", forbidden)
    assert main([*args, "-U", "snapshot", "-f", "png", "-e", "0", "-J"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total_images"] == 2
    assert report["sampling"]["galleries"] == 2
    assert report["inventory_snapshot"]["selected_files_validated"] == 2
    assert report["estimate"]["population_warning"]
    assert (
        main(
            [
                "compress",
                "analyze",
                "-d",
                str(root),
                "-I",
                str(tmp_path / "state"),
                "-U",
                "snapshot",
                "-u",
                "manga-a",
                "-J",
            ]
        )
        == 2
    )
    assert "refresh" in capsys.readouterr().err.lower()


def test_fast_inventory_preserves_manga_page_exclusions(tmp_path, monkeypatch, capsys):
    root = tmp_path / "library"
    chapter = root / "manga" / "chapter"
    chapter.mkdir(parents=True)
    (chapter / "01.jpg").write_bytes(b"12345")
    (chapter / "cover.webp").write_bytes(b"ignored")
    (root / "manga" / "_partial").mkdir()
    (root / "manga" / "_partial" / "bad.jpg").write_bytes(b"ignored")

    def forbidden(*args, **kwargs):
        pytest.fail("Fast MangaDL inventory opened image content")

    monkeypatch.setattr(Image, "open", forbidden)
    assert (
        main(
            [
                "compress",
                "-d",
                str(root),
                "-D",
                "files",
                "-I",
                str(tmp_path / "state"),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["candidate_images"] == 1
    assert report["candidate_bytes"] == 5
    assert list(report["galleries"]) == ["manga"]
    assert report["content_verified"] is False


@pytest.mark.parametrize("depth", ["files", "headers"])
def test_inventory_summary_shared_with_standalone(tmp_path, capsys, depth):
    chapter = tmp_path / "manga" / "chapter"
    chapter.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(chapter / "01.png")
    args = ["compress", "inventory", "-d", str(tmp_path), "-D", depth]
    assert main(args) == 0
    output = capsys.readouterr()
    assert "Inventory Summary" in output.err
    assert "Gallery folders with images" in output.err
    assert "Saved inventory:" in output.err
    assert json.loads(output.out)["galleries"]
    assert main([*args, "-J"]) == 0
    output = capsys.readouterr()
    assert "Report saved:" in output.err and "Inventory Summary" not in output.err
    assert json.loads(output.out)["galleries"]


def test_rejected_trusted_write_does_not_create_library_controls(tmp_path, capsys):
    Image.new("RGB", (40, 40)).save(tmp_path / "01.png")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert main(["compress", "apply", "-d", str(tmp_path), "-U", "snapshot", "-w"]) == 2
    assert "apply requires inventory refresh" in capsys.readouterr().err
    assert {path.name for path in tmp_path.iterdir()} == {"01.png"}
    assert (tmp_path / "01.png").read_bytes() == before["01.png"]


def test_rejected_recovery_confirmation_does_not_create_workspace(tmp_path, capsys):
    root = tmp_path / "library"
    root.mkdir()
    assert main(["compress", "recover", "-d", str(root), "-C", "TOKEN"]) == 2
    assert not (tmp_path / "library-mangadl").exists()
    assert "--confirm requires --write" in capsys.readouterr().err


def test_preview_uses_eligible_nested_pages_and_preserves_sources(tmp_path, capsys):
    gallery = tmp_path / "library" / "manga" / "chapter"
    gallery.mkdir(parents=True)
    Image.new("RGB", (40, 40), "white").save(gallery / "01.png")
    Image.new("RGB", (40, 40), "white").save(gallery / "cover.png")
    before = {p.name: p.read_bytes() for p in gallery.iterdir()}
    assert (
        main(
            [
                "compress",
                "-d",
                str(gallery.parents[1]),
                "-O",
                str(tmp_path / "previews"),
                "-n",
                "2",
                "-q",
                "0.9",
                "0.8",
                "-f",
                "webp",
                "-e",
                "0",
                "-J",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "complete"
    assert len(report["images"]) == 1
    assert report["images"][0]["source"].endswith("01.png")
    assert {p.name: p.read_bytes() for p in gallery.iterdir()} == before


def test_preview_accepts_multiple_explicit_formats(tmp_path, capsys):
    root = tmp_path / "library"
    root.mkdir()
    Image.new("RGB", (40, 40), "white").save(root / "01.png")
    output = tmp_path / "previews"
    assert (
        main(
            [
                "compress",
                "preview",
                "-d",
                str(root),
                "-O",
                str(output),
                "-f",
                "webp",
                "auto",
                "-q",
                "85",
                "-n",
                "1",
                "-e",
                "0",
                "-J",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    variants = report["images"][0]["variants"]
    assert {variant["name"] for variant in variants} == {
        "webp-lossless",
        "webp-lossy-q85",
        "auto-lossless",
        "auto-lossy-q85",
    }
    assert all(variant["status"] == "complete" for variant in variants)


def test_multi_quality_gallery_comparison(tmp_path, capsys):
    Image.new("RGB", (40, 40), "white").save(tmp_path / "01.png")
    assert (
        main(
            [
                "compress",
                "compare",
                "-d",
                str(tmp_path),
                "-f",
                "webp",
                "jpeg",
                "auto",
                "-m",
                "both",
                "-q",
                "90",
                "80",
                "-e",
                "0",
                "-J",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 9
    assert {r["quality"] for r in rows if r["mode"] == "lossy"} == {"q=90", "q=80"}


def test_inventory_only_reuses_nested_headers(tmp_path, capsys, monkeypatch):
    import compresser.scanner as scanner

    root = tmp_path / "library"
    gallery = root / "manga" / "chapter"
    gallery.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(gallery / "01.png")
    Image.new("RGB", (40, 40)).save(gallery / "cover.png")
    args = [
        "compress",
        "inventory",
        "-d",
        str(root),
        "-I",
        str(tmp_path / "state"),
    ]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["images"] == 1
    assert report["galleries"][str(root / "manga")]["images"] == 1
    monkeypatch.setattr(
        scanner,
        "inspect_image_file",
        lambda *a, **k: pytest.fail("Unchanged header reopened"),
    )
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["headers_reused"] >= 2


def test_combined_gallery_sample_report(tmp_path, capsys):
    for gallery in ("small", "large"):
        directory = tmp_path / gallery / "chapter"
        directory.mkdir(parents=True)
        for i in range(3 if gallery == "small" else 9):
            Image.new("RGB", (40, 40), "white").save(directory / f"{i}.png")
    assert (
        main(
            [
                "compress",
                "compare",
                "-d",
                str(tmp_path),
                "-f",
                "webp",
                "jpeg",
                "auto",
                "-m",
                "both",
                "-s",
                "50%",
                "-q",
                "75",
                "-e",
                "0",
                "-J",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 6
    assert all(row["sampling"]["galleries"] == 2 for row in rows)
    assert all(row["measured_images"] == 6 for row in rows)
    assert all("estimate" in row for row in rows)


def test_compress_cli_help(capsys):
    import pytest

    parser = build_parser(["compress", "--help"])
    assert parser is not None
    with pytest.raises(SystemExit) as result:
        parser.parse_args(["compress", "--help"])
    assert result.value.code == 0
    assert "inventory" in capsys.readouterr().out


def test_compress_interrupt_returns_130(tmp_path, monkeypatch, capsys):
    from compresser import CompressionEngine

    Image.new("RGB", (40, 40)).save(tmp_path / "001.png")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(CompressionEngine, "compress_batch", interrupt)
    assert main(["compress", "analyze", "-d", str(tmp_path), "-N", "-J"]) == 130
    output = capsys.readouterr()
    assert output.out == "" and "Cancelled" in output.err


def test_discover_gallery_targets(tmp_path: Path):
    dest = tmp_path / "library"
    dest.mkdir()
    gal1 = dest / "manga-1"
    gal1.mkdir()
    im = Image.new("RGB", (100, 100), color=(10, 20, 30))
    im.save(gal1 / "001.jpg", format="JPEG")

    gal2 = dest / "manga-2"
    gal2.mkdir()
    im.save(gal2 / "001.jpg", format="JPEG")

    hidden = dest / ".mangadl"
    hidden.mkdir()

    targets = discover_gallery_targets(dest)
    assert len(targets) == 2
    assert gal1 in targets
    assert gal2 in targets
    assert hidden not in targets


def test_compress_dry_run(tmp_path: Path, capsys):
    dest = tmp_path / "library"
    dest.mkdir()
    gal = dest / "series-a"
    gal.mkdir()
    im = Image.new("RGB", (120, 120), color=(50, 100, 150))
    src = gal / "001.jpg"
    im.save(src, format="JPEG", quality=85)

    ret = main(["compress", "inventory", "-d", str(dest), "-f", "webp", "-m", "perceptual", "-N"])
    assert ret == 0

    # Ensure dry run did not touch original file
    assert src.exists()
    assert not (gal / "001.webp").exists()


def test_compress_write_mode_and_audit(tmp_path: Path):
    dest = tmp_path / "library"
    dest.mkdir()
    gal = dest / "series-b"
    gal.mkdir()

    # Create two pages
    im = Image.new("RGB", (120, 120), color=(80, 120, 160))
    im.save(gal / "001.jpg", format="JPEG", quality=90)
    im.save(gal / "002.jpg", format="JPEG", quality=90)

    # Sidecar file
    (gal / "info.json").write_text('{"title": "B"}', encoding="utf-8")

    # Apply compression (with explicit -L / --allow-lossy)
    ret = main(
        [
            "compress",
            "-d",
            str(dest),
            "-f",
            "webp",
            "-m",
            "lossy",
            "-q",
            "75",
            "-w",
            "-L",
            "-N",
        ]
    )
    assert ret == 0

    # Check files
    assert not (gal / "001.jpg").exists()
    assert not (gal / "002.jpg").exists()
    assert (gal / "001.webp").exists()
    assert (gal / "002.webp").exists()
    assert (gal / "info.json").exists()

    # Verify audit integrity: inspect_pages should see exactly valid pages 1 and 2, no duplicates
    findings = _inspect_pages(gal, expected_count=2, image_validator=_validate_image)
    assert findings["completeness"] == "complete"
    assert findings["image_integrity"] == "valid"
    assert findings["valid_images"] == 2
    assert len(findings["duplicate_pages"]) == 0
    assert len(findings["missing_pages"]) == 0


def test_compress_audit_defect_non_regression(tmp_path: Path):
    """Verify that compression introduces no new audit defects and preserves existing defect status."""
    dest = tmp_path / "library"
    dest.mkdir()
    gal = dest / "incomplete-series"
    gal.mkdir()

    # Create incomplete gallery: pages 1 and 3 exist, page 2 is missing
    im = Image.new("RGB", (100, 100), color=(10, 20, 30))
    im.save(gal / "001.jpg", format="JPEG", quality=90)
    im.save(gal / "003.jpg", format="JPEG", quality=90)

    # Pre-audit check
    findings_before = _inspect_pages(gal, expected_count=3, image_validator=_validate_image)
    assert findings_before["completeness"] == "incomplete"
    assert findings_before["missing_pages"] == [2]

    # Run compression with write mode
    ret = main(
        [
            "compress",
            "-d",
            str(dest),
            "-f",
            "webp",
            "-m",
            "lossy",
            "-q",
            "75",
            "-w",
            "-L",
            "-N",
        ]
    )
    assert ret == 0

    # Post-audit check: incomplete status preserved, page 2 still missing, zero duplicate pages
    findings_after = _inspect_pages(gal, expected_count=3, image_validator=_validate_image)
    assert findings_after["completeness"] == "incomplete"
    assert findings_after["missing_pages"] == [2]
    assert len(findings_after["duplicate_pages"]) == 0
    assert findings_after["valid_images"] == 2
    assert findings_after["image_integrity"] == "valid"
    assert (gal / "001.webp").exists()
    assert (gal / "003.webp").exists()
    assert not (gal / "001.jpg").exists()
    assert not (gal / "003.jpg").exists()


def test_compress_compare_json(tmp_path: Path, capsys):
    dest = tmp_path / "library"
    dest.mkdir()
    gal = dest / "series-c"
    gal.mkdir()
    im = Image.new("RGB", (100, 100), color=(10, 20, 30))
    im.save(gal / "001.jpg", format="JPEG")

    ret = main(["compress", "inventory", "-d", str(dest), "-c", "-J", "-N"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) > 0
    assert any("strategy" in row for row in data)


def test_exact_url_selection_and_cover_exclusion(tmp_path):
    from mangadl.library_index import write_source_manifest

    destination = tmp_path / "library"
    gallery = destination / "renamed-gallery"
    gallery.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(gallery / "001.jpg")
    cover = gallery / "cover.jpg"
    Image.new("RGB", (40, 40)).save(cover)
    before = cover.read_bytes()
    write_source_manifest(gallery, "https://nhentai.net/g/633374/", "gallery-dl")
    assert discover_gallery_targets(destination, ["https://nhentai.net/g/633374/"]) == [gallery]
    import pytest

    with pytest.raises(ValueError, match="unresolved"):
        discover_gallery_targets(destination, ["renamed"])
    assert (
        main(
            [
                "compress",
                "-d",
                str(destination),
                "-u",
                "https://nhentai.net/g/633374/",
                "-m",
                "lossless",
                "-w",
                "-N",
            ]
        )
        == 0
    )
    assert cover.read_bytes() == before


def test_active_repair_blocks_compression_write(tmp_path):
    root = tmp_path / "library"
    gallery = root / "gallery"
    gallery.mkdir(parents=True)
    Image.new("RGB", (40, 40)).save(gallery / "001.jpg")
    controls = root / ".mangadl"
    controls.mkdir()
    (controls / "repair.lock").write_text("active", encoding="utf-8")
    assert main(["compress", "inventory", "-d", str(gallery), "-w", "-N"]) == 2
    assert (gallery / "001.jpg").exists()


def test_nested_gallery_selection_and_analysis(tmp_path, capsys):
    from mangadl.library_index import write_source_manifest

    root = tmp_path / "library"
    gallery = root / "series"
    chapter = gallery / "chapter-1"
    chapter.mkdir(parents=True)
    image = Image.new("RGB", (40, 40))
    page = chapter / "001.png"
    image.save(page)
    before = page.read_bytes()
    for directory in (gallery / ".controls", gallery / "_partial"):
        directory.mkdir()
        image.save(directory / "002.png")
    image.save(chapter / "cover.png")
    write_source_manifest(gallery, "https://nhentai.net/g/633374/", "gallery-dl")

    assert discover_gallery_targets(root) == [gallery]
    assert discover_gallery_targets(gallery) == [gallery]
    assert discover_gallery_targets(gallery, ["https://nhentai.net/g/633374/"]) == [gallery]
    assert main(["compress", "analyze", "-d", str(root), "-J", "-N"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["inventory_images"] == 1
    assert result["total_images"] == 1
    assert page.read_bytes() == before
    assert not (chapter / ".compress.lock").exists()


def test_nested_gallery_write_preserves_chapter_paths(tmp_path):
    gallery = tmp_path / "library" / "series"
    for name in ("chapter-1", "chapter-2"):
        chapter = gallery / name
        chapter.mkdir(parents=True)
        Image.new("RGB", (120, 120), (80, 120, 160)).save(chapter / "001.jpg", quality=90)
    assert (
        main(
            [
                "compress",
                "-d",
                str(gallery.parent),
                "-f",
                "webp",
                "-m",
                "lossy",
                "-w",
                "-L",
                "-N",
            ]
        )
        == 0
    )
    for name in ("chapter-1", "chapter-2"):
        assert not (gallery / name / "001.jpg").exists()
        with Image.open(gallery / name / "001.webp") as image:
            image.load()
            assert image.size == (120, 120)


def test_mangadl_reader_acceptance_preserves_manifests_covers_archives_and_recommendations(tmp_path, capsys):
    from mangadl.library_index import read_source_manifest, write_source_manifest

    library = tmp_path / "library"
    gallery = library / "series-alpha"
    ch1 = gallery / "ch01"
    ch1.mkdir(parents=True)
    for page_num in (1, 2):
        im = Image.new("RGB", (100, 100), (page_num * 40, 90, 140))
        im.save(ch1 / f"{page_num:03d}.png")
    cover = gallery / "cover.jpg"
    Image.new("RGB", (80, 120), (200, 50, 50)).save(cover)
    cover_bytes = cover.read_bytes()
    archive = gallery / "bonus.cbz"
    archive.write_bytes(b"PK\x03\x04dummy-cbz")
    sidecar = gallery / "series.json"
    sidecar.write_text('{"series": "Alpha"}', encoding="utf-8")
    partial_dir = gallery / "_partial"
    partial_dir.mkdir()
    Image.new("RGB", (60, 60), "black").save(partial_dir / "001.png")
    partial_bytes = (partial_dir / "001.png").read_bytes()
    write_source_manifest(gallery, "https://nhentai.net/g/633374/", "gallery-dl")

    scratch_dir = tmp_path / "ssd_scratch"
    scratch_dir.mkdir()
    assert (
        main(
            [
                "compress",
                "-d",
                str(library),
                "-b",
                "-q",
                "90",
                "80",
                "-e",
                "0",
                "-X",
                str(scratch_dir),
                "-J",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["recommendations"]["maximum_savings"] is not None
    assert rows[0]["recommendations"]["practical_tradeoff"] is not None
    assert list(scratch_dir.iterdir()) == []

    # Apply lossless WebP compression and verify reader/library invariants
    assert (
        main(
            [
                "compress",
                "-d",
                str(library),
                "-f",
                "webp",
                "-m",
                "lossless",
                "-e",
                "0",
                "-w",
                "-N",
            ]
        )
        == 0
    )
    assert read_source_manifest(gallery)["canonical_url"] == "https://nhentai.net/g/633374/"
    assert cover.read_bytes() == cover_bytes
    assert archive.read_bytes() == b"PK\x03\x04dummy-cbz"
    assert sidecar.read_text(encoding="utf-8") == '{"series": "Alpha"}'
    assert (partial_dir / "001.png").read_bytes() == partial_bytes
    findings = _inspect_pages(ch1, expected_count=2, image_validator=_validate_image)
    assert findings["completeness"] == "complete"
    assert findings["image_integrity"] == "valid"
    assert findings["valid_images"] == 2
    assert not findings["duplicate_pages"]


def test_compress_accepts_uncapped_memory_budgets(tmp_path):
    Image.new("RGB", (40, 40), "white").save(tmp_path / "01.png")
    assert main(["compress", "inventory", "-d", str(tmp_path), "-B", "40%", "-N"]) == 0
    assert main(["compress", "inventory", "-d", str(tmp_path), "-B", "8192", "-N"]) == 0
    assert main(["compress", "inventory", "-d", str(tmp_path), "-B", "16G", "-N"]) == 0
