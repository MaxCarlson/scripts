"""Failure-path tests for analysis purity, ownership and codec truthfulness."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from compresser import CompressionEngine, CompressionStrategy, scan_directory
from compresser.cli import main
from compresser.codecs.external_cli import ExternalCliCodec
from compresser.engine import validate_image_file
from compresser.perceptual import calculate_ssim, find_optimal_quality
from compresser.transactions import JOURNAL_FILENAME, digest, directory_lock, publish, recover


def test_standalone_writer_refuses_managed_library_owner(tmp_path):
    import subprocess
    import sys

    gallery = tmp_path / "gallery"
    gallery.mkdir()
    source = image(gallery / "001.jpg")
    before = source.read_bytes()
    _, images = scan_directory(gallery)
    child = subprocess.Popen(
        [sys.executable, "-u", "-c",
         "import sys; from pathlib import Path; from compresser.transactions import library_write_guard; "
         "\nwith library_write_guard(Path(sys.argv[1])):\n print('owned', flush=True); sys.stdin.read()",
         str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout.readline().strip() == "owned"
        engine = CompressionEngine()
        strategy = CompressionStrategy("test", mode="lossless")
        with pytest.raises(RuntimeError, match="locked"):
            engine.compress_batch(images, strategy, write_mode=True)
        with pytest.raises(RuntimeError, match="locked"):
            engine.compress_image(images[0], strategy, write_mode=True)
        assert main(["-i", str(gallery), "-w", "-N"]) == 2
        assert engine.compress_batch(images, strategy).failed_count == 0
        assert source.read_bytes() == before
        assert not (gallery / ".compress.lock").exists()
    finally:
        child.kill()
        child.communicate(timeout=10)


def test_managed_guard_is_held_through_worker_callbacks(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from compresser.transactions import managed_write_guard

    (tmp_path / ".mangadl").mkdir()
    gallery = tmp_path / "chapter"
    gallery.mkdir()
    image(gallery / "001.jpg")
    _, images = scan_directory(gallery)

    def acquire():
        with managed_write_guard([gallery]):
            pass

    def callback(done, total, result):
        with ThreadPoolExecutor(1) as pool:
            with pytest.raises(RuntimeError, match="locked"):
                pool.submit(acquire).result()

    result = CompressionEngine().compress_batch(
        images, CompressionStrategy("test", mode="lossless"), write_mode=True, progress_callback=callback
    )
    assert result.failed_count == 0
    acquire()


def image(path: Path) -> Path:
    Image.new("RGB", (80, 80), (30, 50, 70)).save(path, quality=90)
    return path


def payload() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80), (30, 50, 70)).save(buffer, "WEBP", lossless=True)
    return buffer.getvalue()


def test_analysis_does_not_recover(tmp_path):
    source = image(tmp_path / "001.jpg")
    journal = tmp_path / JOURNAL_FILENAME
    journal.write_text('{"version":1}', encoding="utf-8")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    _, images = scan_directory(tmp_path)
    CompressionEngine().compress_batch(images, CompressionStrategy("test", mode="lossless"))
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert source.exists()


def test_collision_is_preserved(tmp_path):
    source = image(tmp_path / "001.jpg")
    output = tmp_path / "001.webp"
    output.write_bytes(b"unrelated existing target")
    before = source.read_bytes()
    _, images = scan_directory(tmp_path)
    result = CompressionEngine().compress_image(
        images[0], CompressionStrategy("test", mode="lossless"), write_mode=True
    )
    assert result.error and "already exists" in result.error
    assert source.read_bytes() == before
    assert output.read_bytes() == b"unrelated existing target"


def test_journal_failure_prevents_publication(tmp_path, monkeypatch):
    import compresser.transactions as transactions

    source = image(tmp_path / "001.jpg")
    before = source.read_bytes()

    def fail(*args):
        raise PermissionError("record unavailable")

    monkeypatch.setattr(transactions, "_save_record", fail)
    with pytest.raises(PermissionError):
        publish(source, source.with_suffix(".webp"), payload(), digest(source), validate_image_file)
    assert source.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["001.jpg"]


def test_unlink_failure_preserves_evidence_and_explicit_recovery(tmp_path, monkeypatch):
    source = image(tmp_path / "001.jpg")
    output = source.with_suffix(".webp")
    original_unlink = Path.unlink

    def fail_selected(path, *args, **kwargs):
        if path == source:
            raise PermissionError("source locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_selected)
    with pytest.raises(PermissionError):
        publish(source, output, payload(), digest(source), validate_image_file)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert source.exists() and output.exists() and (tmp_path / JOURNAL_FILENAME).exists()
    assert recover(tmp_path) == 1
    assert source.exists() and output.exists() and (tmp_path / JOURNAL_FILENAME).exists()
    from concurrent.futures import ThreadPoolExecutor
    from compresser.transactions import library_write_guard

    with library_write_guard(tmp_path):
        assert recover(tmp_path) == 1  # Preview remains read-only during another operation.
        with ThreadPoolExecutor(1) as pool:
            with pytest.raises(RuntimeError, match="locked"):
                pool.submit(recover, tmp_path, apply=True).result()
        assert source.exists() and (tmp_path / JOURNAL_FILENAME).exists()
    assert recover(tmp_path, apply=True) == 1
    assert not source.exists() and output.exists()
    assert not (tmp_path / JOURNAL_FILENAME).exists()


def test_source_change_refused(tmp_path):
    source = image(tmp_path / "001.jpg")
    old_hash = digest(source)
    source.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="Source changed"):
        publish(source, source.with_suffix(".webp"), payload(), old_hash, validate_image_file)
    assert source.read_bytes() == b"changed"
    assert not source.with_suffix(".webp").exists()


def test_competing_process_refused(tmp_path):
    with directory_lock(tmp_path):
        with pytest.raises(RuntimeError, match="locked"):
            with directory_lock(tmp_path):
                pytest.fail("competing owner admitted")


def test_pending_write_refused(tmp_path):
    image(tmp_path / "001.jpg")
    (tmp_path / JOURNAL_FILENAME).write_text("{}", encoding="utf-8")
    _, images = scan_directory(tmp_path)
    with pytest.raises(RuntimeError, match="explicit recovery"):
        CompressionEngine().compress_batch(images, CompressionStrategy("test"), write_mode=True)


@pytest.mark.parametrize("target", ["not-a-format"])
def test_unsupported_encoder_not_silent_jpeg(tmp_path, target):
    image(tmp_path / "001.jpg")
    _, images = scan_directory(tmp_path)
    result = CompressionEngine().compress_image(images[0], CompressionStrategy("test", format=target, mode="lossy"))
    assert result.error and "No verified encoder" in result.error


def test_avif_not_lossless(tmp_path):
    engine = CompressionEngine()
    if "pillow-avif" not in engine.codecs:
        pytest.skip("AVIF unavailable")
    image(tmp_path / "001.jpg")
    _, images = scan_directory(tmp_path)
    result = engine.compress_image(images[0], CompressionStrategy("test", format="avif", mode="lossless"))
    assert result.error and "not lossless" in result.error


def test_lossless_alpha_samples(tmp_path):
    source = tmp_path / "001.png"
    im = Image.new("RGBA", (20, 20), (55, 100, 200, 0))
    im.putpixel((0, 0), (1, 2, 3, 128))
    im.save(source)
    _, images = scan_directory(tmp_path)
    result = CompressionEngine().compress_image(
        images[0], CompressionStrategy("test", mode="lossless", allow_larger=True), write_mode=True
    )
    assert result.applied and not result.error
    with Image.open(result.output_path) as output:
        assert output.convert("RGBA").tobytes() == im.tobytes()


def test_quality_search_refuses_unmet_threshold(monkeypatch):
    import compresser.perceptual as perceptual

    monkeypatch.setattr(perceptual, "calculate_ssim", lambda *args: 0.5)
    with pytest.raises(ValueError, match="No quality candidate"):
        find_optimal_quality(
            Image.new("RGB", (12, 12)), lambda *args: b"x", lambda data: Image.new("RGB", (12, 12)), 0.99
        )


def test_quality_search_selects_smallest_passing_bytes(monkeypatch):
    import compresser.perceptual as perceptual

    monkeypatch.setattr(perceptual, "calculate_ssim", lambda *args: 1.0)
    chosen = find_optimal_quality(
        Image.new("RGB", (12, 12)),
        lambda im, q: b"x" * (100 - q),
        lambda data: Image.new("RGB", (12, 12)),
        0.99,
        candidates=(60, 80, 95),
    )
    assert chosen[0] == 95 and len(chosen[1]) == 5


def test_tiny_metric_not_nan():
    im = Image.new("RGB", (1, 1))
    assert calculate_ssim(im, im) == pytest.approx(1)


def test_public_and_submodule_engine_identity():
    from compresser.engine import CompressionEngine as implementation

    assert implementation is CompressionEngine


def test_json_clean_without_no_ui(tmp_path, capsys):
    image(tmp_path / "001.jpg")
    assert main(["-i", str(tmp_path), "-J", "-m", "lossless"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True


@pytest.mark.parametrize("args", [["-q", "0"], ["-p", "1.1"], ["-t", "0"], ["-s", "-1"], ["-o", "elsewhere"]])
def test_invalid_cli_refused(args):
    with pytest.raises(SystemExit):
        main(["-i", "not-used", *args])


def test_jpegtran_uses_original_file(tmp_path, monkeypatch):
    import compresser.codecs.external_cli as adapter

    source = image(tmp_path / "001.jpg")
    original_bytes = source.read_bytes()
    monkeypatch.setattr(adapter.shutil, "which", lambda name: "jpegtran")

    def run(command, **kwargs):
        assert command[-1] == str(source)
        assert source.read_bytes() == original_bytes
        assert "-outfile" in command and kwargs["timeout"] == 120
        shutil.copyfile(source, command[command.index("-outfile") + 1])
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(adapter.subprocess, "run", run)
    with Image.open(source) as im:
        im.load()
        encoded, _ = ExternalCliCodec("jpegtran", "JPEG").encode(
            im, "JPEG", CompressionStrategy("test", mode="lossless")
        )
    assert encoded == original_bytes


def test_concurrent_pages_preserve_all_transactions(tmp_path):
    for number in range(1, 17):
        image(tmp_path / f"{number:03}.jpg")
    _, images = scan_directory(tmp_path)
    result = CompressionEngine().compress_batch(
        images, CompressionStrategy("test", mode="lossless"), write_mode=True, threads=4
    )
    assert result.applied_count == 16 and result.failed_count == 0
    assert len(list(tmp_path.glob("*.webp"))) == 16
    assert not list(tmp_path.glob("*.jpg"))
    assert sorted(p.name for p in tmp_path.glob(".compress*")) == [".compress.lock"]


def test_recovery_refuses_path_escape(tmp_path):
    journal = tmp_path / JOURNAL_FILENAME
    journal.write_text(
        json.dumps({"version": 2, "original": "../outside.jpg", "output": "001.webp", "temp": "tmp"}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="escapes"):
        recover(tmp_path, apply=True)
    assert journal.exists()


def test_changed_scan_refused(tmp_path):
    source = image(tmp_path / "001.jpg")
    _, images = scan_directory(tmp_path)
    source.write_bytes(source.read_bytes() + b"changed")
    result = CompressionEngine().compress_image(
        images[0], CompressionStrategy("test", mode="lossless"), write_mode=True
    )
    assert result.error and "changed since scan" in result.error
    assert not source.with_suffix(".webp").exists()


def test_decode_budget_checked_before_load(tmp_path, monkeypatch):
    import sys

    engine = sys.modules[CompressionEngine.__module__]
    image(tmp_path / "001.jpg")
    _, images = scan_directory(tmp_path)
    monkeypatch.setattr(engine, "MEMORY_BUDGET_BYTES", 1)
    result = CompressionEngine().compress_image(images[0], CompressionStrategy("test", mode="lossless"))
    assert result.error and "working-memory budget" in result.error


def test_recovery_refuses_changed_output(tmp_path, monkeypatch):
    source = image(tmp_path / "001.jpg")
    output = source.with_suffix(".webp")
    original_unlink = Path.unlink

    def fail_selected(path, *args, **kwargs):
        if path == source:
            raise PermissionError("source locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_selected)
    with pytest.raises(PermissionError):
        publish(source, output, payload(), digest(source), validate_image_file)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    output.write_bytes(b"external modification")
    with pytest.raises(RuntimeError, match="Output changed"):
        recover(tmp_path, apply=True)
    assert source.exists() and output.read_bytes() == b"external modification"
    assert (tmp_path / JOURNAL_FILENAME).exists()


def test_same_extension_atomic_replace(tmp_path):
    source = tmp_path / "001.webp"
    source.write_bytes(payload())
    old = digest(source)
    with directory_lock(tmp_path):
        publish(source, source, payload(), old, validate_image_file)
    assert validate_image_file(source)
    assert sorted(p.name for p in tmp_path.iterdir()) == [".compress.lock", "001.webp"]
