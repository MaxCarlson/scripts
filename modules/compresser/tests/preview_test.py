import hashlib
import json

from PIL import Image
import pytest

from compresser.cli import main
from compresser.preview import parse_preview_quality


def test_preview_outputs_original_lossless_and_quality_variants(tmp_path, capsys):
    root = tmp_path / "library"
    root.mkdir()
    source = root / "01.jpg"
    Image.effect_noise((100, 100), 20).convert("RGB").save(source, quality=70)
    original = source.read_bytes()
    output = tmp_path / "previews"
    args = ["-i", str(root), "-O", str(output), "-n", "1", "-Q", "0.9", "0.8", "-f", "webp", "-e", "0", "-J"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    run = output / next(output.iterdir()).name
    assert report["status"] == "complete"
    row = report["images"][0]
    assert [v["name"] for v in row["variants"]] == ["lossless", "lossy-q90", "lossy-q80"]
    assert (run / row["original"]).read_bytes() == original == source.read_bytes()
    assert hashlib.sha256(original).hexdigest() == row["original_sha256"]
    for variant in row["variants"]:
        path = run / variant["file"]
        assert len(path.read_bytes()) == variant["bytes"]
        with Image.open(path) as image:
            assert image.size == (100, 100)
            if variant["mode"] == "lossless":
                with Image.open(source) as im:
                    assert image.convert("RGBA").tobytes() == im.convert("RGBA").tobytes()
    assert row["variants"][0]["bytes"] > len(original)  # Larger candidates are still useful visual previews.
    assert main(args) == 0
    capsys.readouterr()
    assert len(list(output.iterdir())) == 2
    assert source.read_bytes() == original


def test_preview_validation_does_not_write_to_sources(tmp_path):
    Image.new("RGB", (40, 40)).save(tmp_path / "01.png")
    for extra in (["-n", "0"], ["-w"], ["-c"], ["-s", "1"], ["-f", "png"]):
        with pytest.raises(SystemExit):
            main(["-i", str(tmp_path), "-O", str(tmp_path.parent / "preview"), *extra])
    with pytest.raises(SystemExit):
        main(["-i", str(tmp_path), "-O", str(tmp_path / "preview")])
    with pytest.raises(SystemExit):
        main(["-i", str(tmp_path), "-Q", "90"])
    assert [p.name for p in tmp_path.iterdir()] == ["01.png"]


def test_quality_parse():
    assert [parse_preview_quality(q) for q in ("90", "0.9", "0.80", "1.0", "1")] == [90, 90, 80, 100, 1]
    for value in ("nan", "0", "101", "-1", "0.925", "inf"):
        with pytest.raises(Exception):
            parse_preview_quality(value)


def test_cancelled_preview_retains_manifest_and_originals(tmp_path, monkeypatch, capsys):
    from compresser.engine import CompressionEngine

    source = tmp_path / "01.png"
    Image.new("RGB", (40, 40)).save(source)
    before = source.read_bytes()
    output = tmp_path.parent / (tmp_path.name + "-preview")

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(CompressionEngine, "_encode_verified", interrupt)
    assert main(["-i", str(source), "-O", str(output), "-f", "webp", "-J"]) == 130
    report = json.loads(next(output.glob("*/manifest.json")).read_text())
    assert report["status"] == "cancelled"
    assert report["images"][0]["status"] == "cancelled"
    assert report["images"][0]["variants"][0]["status"] == "cancelled"
    assert source.read_bytes() == before


def test_failed_variant_is_explicit(tmp_path, monkeypatch, capsys):
    from compresser.engine import CompressionEngine

    source = tmp_path / "01.png"
    Image.new("RGB", (40, 40)).save(source)
    output = tmp_path.parent / (tmp_path.name + "-preview")

    def reject(*args):
        raise ValueError("unsupported test encoder")

    monkeypatch.setattr(CompressionEngine, "_encode_verified", reject)
    assert main(["-i", str(source), "-O", str(output), "-f", "webp", "-J"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "completed_with_errors"
    assert all(v["status"] == "failed" for v in report["images"][0]["variants"])
