import hashlib
import json
from pathlib import Path
import threading

from PIL import Image
import pytest

from cli_test_support import main
from compresser.arguments import parse_quality as parse_preview_quality


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
    for extra in (["-n", "0"], ["-w"], ["-s", "1"]):
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


def test_preview_parallel_owners_and_single_ordered_manifest(tmp_path, monkeypatch, capsys):
    import compresser.preview as module
    from compresser.engine import CompressionEngine

    root = tmp_path / "library"
    root.mkdir()
    for n in range(3):
        Image.new("RGB", (64, 64), (n * 40, 0, 0)).save(root / f"{n}.png")
    barrier = threading.Barrier(2)
    second_complete = threading.Event()
    worker_ids, writer_ids = set(), set()
    original, save = CompressionEngine._encode_verified, module._save_manifest
    main_thread = threading.get_ident()

    def encode(self, image, fmt, strategy):
        worker_ids.add(threading.get_ident())
        if strategy.mode == "lossless" and Path(image.filename).parent.name in ("0001", "0002"):
            barrier.wait(timeout=3)
            if Path(image.filename).parent.name == "0001":
                assert second_complete.wait(timeout=3)
        return original(self, image, fmt, strategy)

    def publish(path, report):
        writer_ids.add(threading.get_ident())
        save(path, report)
        if report["images"][1]["status"] == "complete":
            second_complete.set()
        assert json.loads(path.read_text())["status"] in (
            "running",
            "complete",
            "completed_with_errors",
            "cancelled",
            "failed",
        )

    monkeypatch.setattr(CompressionEngine, "_encode_verified", encode)
    monkeypatch.setattr(module, "_save_manifest", publish)
    assert (
        main(["-i", str(root), "-O", str(tmp_path / "previews"), "-n", "3", "-t", "2", "-f", "webp", "-e", "0", "-J"])
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert len(worker_ids) == 2 and writer_ids == {main_thread}
    assert [row["original"].split("/")[0] for row in report["images"]] == ["0001", "0002", "0003"]
    assert report["worker_diagnostics"]["peak_active_workers"] == 2
    assert report["worker_diagnostics"]["peak_pending_futures"] <= 2
    assert report["worker_diagnostics"]["peak_reserved_bytes"] <= 512 * 1024**2


def test_cancelled_preview_marks_unsubmitted_sources(tmp_path, monkeypatch):
    from compresser.engine import CompressionEngine

    root = tmp_path / "library"
    root.mkdir()
    for n in range(4):
        Image.new("RGB", (40, 40)).save(root / f"{n}.png")
    output = tmp_path / "previews"

    def stop(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(CompressionEngine, "_encode_verified", stop)
    assert main(["-i", str(root), "-O", str(output), "-n", "4", "-t", "1", "-f", "webp", "-J"]) == 130
    report = json.loads(next(output.glob("*/manifest.json")).read_text())
    assert len(report["images"]) == 4
    assert all(row["status"] == "cancelled" for row in report["images"])


def test_preview_short_write_is_not_published_and_never_overwrites(tmp_path):
    from compresser.preview_pipeline import _publish_file, _write

    class ShortStream:
        def write(self, payload):
            return len(payload) - 1

    with pytest.raises(OSError, match="Short write"):
        _write(ShortStream(), b"data")
    destination = tmp_path / "keep.webp"
    destination.write_bytes(b"bystander")

    def writer(stream):
        _write(stream, b"new bytes")
        return hashlib.sha256(b"new bytes").hexdigest()

    with pytest.raises(FileExistsError):
        _publish_file(destination, writer)
    assert destination.read_bytes() == b"bystander"
    assert list(tmp_path.iterdir()) == [destination]


def test_manifest_failure_drains_workers_and_preserves_parseable_state(tmp_path, monkeypatch, capsys):
    import compresser.preview as module

    root = tmp_path / "library"
    root.mkdir()
    for n in range(3):
        Image.new("RGB", (64, 64)).save(root / f"{n}.png")
    output = tmp_path / "previews"
    original = module._save_manifest
    calls = 0

    def failed(path, report):
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise OSError("simulated disk full during manifest replacement")
        original(path, report)

    monkeypatch.setattr(module, "_save_manifest", failed)
    assert main(["-i", str(root), "-O", str(output), "-n", "3", "-t", "2", "-f", "webp", "-e", "0", "-J"]) == 2
    assert "manifest replacement" in capsys.readouterr().err
    assert json.loads(next(output.glob("*/manifest.json")).read_text())["status"] == "running"
    assert not any(thread.name.startswith("compression-preview") for thread in threading.enumerate())


def test_small_budget_previews_remain_serial_and_successful(tmp_path, capsys):
    root = tmp_path / "library"
    root.mkdir()
    for n in range(2):
        Image.new("RGB", (1000, 1000), "navy").save(root / f"{n}.png")
    assert (
        main(
            [
                "-i",
                str(root),
                "-O",
                str(tmp_path / "previews"),
                "-n",
                "2",
                "-t",
                "4",
                "-B",
                "64",
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
    assert report["worker_diagnostics"]["effective_workers"] == 1
    assert report["worker_diagnostics"]["peak_reserved_bytes"] <= 64 * 1024**2


@pytest.mark.parametrize("failure", ["disk-full", "permission"])
def test_failed_candidate_publication_keeps_original_and_no_partial(tmp_path, monkeypatch, capsys, failure):
    import compresser.preview_pipeline as module

    source = tmp_path / "01.png"
    Image.new("RGB", (40, 40)).save(source)
    before = source.read_bytes()
    output = tmp_path.parent / (tmp_path.name + "-previews")
    original_write, original_link = module._write, module.os.link

    def write(stream, payload):
        if failure == "disk-full" and payload.startswith(b"RIFF"):
            stream.write(payload[:4])
            raise OSError("simulated disk full")
        original_write(stream, payload)

    def link(src, dst):
        if failure == "permission" and str(dst).endswith(".webp"):
            raise PermissionError("simulated permission error")
        original_link(src, dst)

    monkeypatch.setattr(module, "_write", write)
    monkeypatch.setattr(module.os, "link", link)
    assert main(["-i", str(source), "-O", str(output), "-f", "webp", "-e", "0", "-J"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "completed_with_errors"
    assert source.read_bytes() == before
    folder = next(output.glob("*/0001"))
    assert [path.name for path in folder.iterdir()] == ["original.png"]


def test_changed_source_after_copy_is_reported_not_verified(tmp_path, monkeypatch, capsys):
    from compresser.engine import CompressionEngine

    source = tmp_path / "01.png"
    Image.new("RGB", (40, 40)).save(source)
    output = tmp_path.parent / (tmp_path.name + "-previews")
    original = CompressionEngine._encode_verified

    def mutate(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        source.write_bytes(source.read_bytes() + b"changed by external writer")
        return result

    monkeypatch.setattr(CompressionEngine, "_encode_verified", mutate)
    assert main(["-i", str(source), "-O", str(output), "-f", "webp", "-e", "0", "-J"]) == 1
    row = json.loads(capsys.readouterr().out)["images"][0]
    assert row["status"] == "failed" and "Source changed" in row["error"]
    assert all(variant["status"] != "running" for variant in row["variants"])
