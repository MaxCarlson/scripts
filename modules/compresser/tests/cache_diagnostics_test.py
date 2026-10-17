import sqlite3
import json

from PIL import Image

from compresser.cache import AnalysisCache
from compresser.models import CompressionStrategy, ImageResult


def test_cache_dates_and_lookup_counts_survive_reopen(tmp_path):
    source = tmp_path / "01.jpg"
    source.write_bytes(b"12345")
    path = tmp_path / "cache.sqlite3"
    strategy = CompressionStrategy("diagnostics", format="webp", mode="lossy")
    result = ImageResult(source, source.with_suffix(".webp"), 5, 3, "JPEG", "WEBP")
    with AnalysisCache(path=path) as cache:
        assert callable(getattr(cache, "diagnostics", None)), "Cache diagnostics API missing"
        first = cache.diagnostics()
        assert first["created_at"] is not None
        assert first["last_result_saved_at"] is None
        assert cache.get(source, strategy) is None
        cache.set(source, strategy, result)
        assert cache.get(source, strategy).cache_hit
        report = cache.diagnostics()
        assert report["lookup_hits"] == 1 and report["lookup_misses"] == 1
        assert report["miss_reasons"] == {"no_matching_entry": 1}
        assert report["last_result_saved_at"] is not None
    with AnalysisCache(path=path) as cache:
        reopened = cache.diagnostics()
        assert reopened["created_at"] == first["created_at"]
        assert reopened["last_result_saved_at"] == report["last_result_saved_at"]
        assert reopened["lookup_hits"] == reopened["lookup_misses"] == 0
        assert cache.get(source, strategy).cache_hit


def test_legacy_cache_does_not_invent_creation_date(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE entries (kind TEXT,key TEXT,data TEXT,PRIMARY KEY(kind,key))")
    with AnalysisCache(path=path) as cache:
        assert callable(getattr(cache, "diagnostics", None)), "Cache diagnostics API missing"
        report = cache.diagnostics()
        assert report["created_at"] is None
        assert report["tracking_started_at"] is not None


def test_refresh_lookup_is_not_counted_as_missing_compatible_data(tmp_path):
    source = tmp_path / "01.jpg"
    source.write_bytes(b"12345")
    with AnalysisCache(path=tmp_path / "cache.sqlite3", reuse_persistent=False) as cache:
        assert callable(getattr(cache, "diagnostics", None)), "Cache diagnostics API missing"
        assert cache.get(source, CompressionStrategy("refresh")) is None
        assert cache.diagnostics()["miss_reasons"] == {"refresh_policy": 1}


def test_cli_exposes_cache_dates_and_run_lookup_scope(tmp_path, capsys):
    from compresser.cli import main

    source = tmp_path / "01.png"
    Image.new("RGB", (40, 40), "white").save(source)
    args = ["-i", str(source), "-f", "webp", "-e", "0"]
    assert main(args + ["-J"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "lookup_hits" in report["cache"], "CLI cache diagnostics missing"
    assert report["cache"]["created_at"]
    assert report["cache"]["lookup_misses"] >= 1
    assert main(args + ["-J"]) == 0
    warm = json.loads(capsys.readouterr().out)
    assert warm["cache"]["lookup_hits"] == 1
    assert warm["cache"]["created_at"] == report["cache"]["created_at"]
    assert main(args + ["-N"]) == 0
    assert report["cache"]["created_at"] in capsys.readouterr().out
