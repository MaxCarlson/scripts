import json

import pytest
from PIL import Image

from compresser import AnalysisCache, CompressionEngine, CompressionStrategy, scan_directory
from cli_test_support import main


def test_cache_hits_bypass_memory_scheduler_admission(tmp_path):
    img1 = tmp_path / "01.png"
    img2 = tmp_path / "02.png"
    Image.new("RGB", (120, 120), (20, 40, 60)).save(img1)
    Image.new("RGB", (120, 120), (80, 100, 120)).save(img2)
    _, images = scan_directory(tmp_path)
    cache = AnalysisCache(path=tmp_path.parent / "admission_cache.sqlite3")
    strategy = CompressionStrategy("webp-lossless", format="webp", mode="lossless", method=0)

    engine = CompressionEngine(cache=cache)
    cold = engine.compress_batch(images, strategy, threads=2)
    assert cold.worker_diagnostics["pre_admission_cache_hits"] == 0
    assert cold.worker_diagnostics["peak_reserved_bytes"] > 0

    warm = engine.compress_batch(images, strategy, threads=2)
    assert warm.worker_diagnostics["pre_admission_cache_hits"] == 2
    assert warm.worker_diagnostics["peak_reserved_bytes"] == 0
    assert all(r.cache_hit for r in warm.results)
    assert [r.compressed_bytes for r in warm.results] == [r.compressed_bytes for r in cold.results]
    cache.close()


def test_scratch_staging_preserves_identities_skips_cached_and_cleans_up(tmp_path, capsys):
    library = tmp_path / "library"
    library.mkdir()
    for idx in range(2):
        Image.new("RGB", (96, 96), (idx * 40, 80, 120)).save(library / f"{idx:02d}.png")
    scratch_root = tmp_path / "scratch_ssd"
    scratch_root.mkdir()
    bystander = scratch_root / "keep_me.txt"
    bystander.write_text("unrelated file", encoding="utf-8")
    cache_file = tmp_path / "trials.sqlite3"

    args = [
        "-i",
        str(library),
        "-f",
        "webp",
        "-m",
        "lossless",
        "-e",
        "0",
        "-K",
        str(cache_file),
        "-X",
        str(scratch_root),
        "-J",
    ]
    assert main(args) == 0
    cold_out = json.loads(capsys.readouterr().out)
    assert cold_out["failed_count"] == 0
    scratch_diag = cold_out["worker_diagnostics"]["scratch"]
    assert scratch_diag["staged_images"] == 2
    assert scratch_diag["staged_bytes"] > 0
    assert scratch_diag["cleaned_up"] is True
    assert "scratch_copy" in cold_out["worker_diagnostics"]["phase_seconds"]
    # Owned run directory was cleaned up, while unrelated bystander file remains
    assert list(scratch_root.iterdir()) == [bystander]

    # Warm run with scratch enabled should bypass staging via pre-admission cache hits
    assert main(args) == 0
    warm_out = json.loads(capsys.readouterr().out)
    assert warm_out["cache_hits"] == 2
    assert warm_out["worker_diagnostics"]["pre_admission_cache_hits"] == 2
    assert warm_out["worker_diagnostics"]["scratch"]["staged_images"] == 0


def test_scratch_rejects_invalid_combinations_and_source_changes(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    img_path = library / "01.png"
    Image.new("RGB", (64, 64), "white").save(img_path)
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()

    # Reject write mode, inventory-only, or scratch inside input tree
    for bad_args in (
        ["-i", str(library), "-X", str(scratch_root), "-w"],
        ["-i", str(library), "-X", str(scratch_root), "-l"],
        ["-i", str(library), "-X", str(library / "nested_scratch")],
    ):
        with pytest.raises(SystemExit):
            main(bad_args)

    # Source change after scan before scratch copy fails closed
    _, images = scan_directory(library)
    img_path.write_bytes(img_path.read_bytes() + b"\x00")
    engine = CompressionEngine()
    batch = engine.compress_batch(
        images,
        CompressionStrategy("webp-lossless", format="webp", mode="lossless", method=0),
        threads=1,
        scratch_dir=scratch_root,
    )
    assert batch.failed_count == 1
    assert "Source changed" in batch.results[0].error
    assert list(scratch_root.iterdir()) == []
