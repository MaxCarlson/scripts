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
    from cli_test_support import main

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


def test_indexed_cache_miss_explanations_for_source_settings_runtime_and_eviction(tmp_path):
    source = tmp_path / "01.jpg"
    source.write_bytes(b"12345")
    other = tmp_path / "02.jpg"
    other.write_bytes(b"67890")
    db_path = tmp_path / "cache.sqlite3"
    s80 = CompressionStrategy("webp-80", format="webp", mode="lossy", quality=80)
    s90 = CompressionStrategy("webp-90", format="webp", mode="lossy", quality=90)
    res1 = ImageResult(source, source.with_suffix(".webp"), 5, 3, "JPEG", "WEBP")
    res2 = ImageResult(other, other.with_suffix(".webp"), 5, 4, "JPEG", "WEBP")

    with AnalysisCache(max_entries=1, path=db_path) as cache:
        # 1. Never measured before -> no_matching_entry (and invalidation_causes["never_measured"] == 1)
        assert cache.get(source, s80) is None
        diag = cache.diagnostics()
        assert diag["miss_reasons"]["no_matching_entry"] == 1
        assert diag["invalidation_causes"]["never_measured"] == 1

        cache.set(source, s80, res1)
        # 2. Same source, different quality -> settings_changed
        assert cache.get(source, s90) is None
        diag = cache.diagnostics()
        assert diag["miss_reasons"]["settings_changed"] == 1
        assert diag["invalidation_causes"]["settings_changed"] == 1

        # 3. Evict source from entries by inserting `other` into a max_entries=1 cache
        cache.set(other, s80, res2)
        assert cache.get(source, s80) is None
        diag = cache.diagnostics()
        assert diag["miss_reasons"]["evicted"] == 1
        assert diag["invalidation_causes"]["evicted"] == 1

        # Re-save source at s80, then modify source file bytes -> source_changed
        cache.set(source, s80, res1)
        source.write_bytes(b"12345678")
        assert cache.get(source, s80) is None
        diag = cache.diagnostics()
        assert diag["miss_reasons"]["source_changed"] == 1
        assert diag["invalidation_causes"]["source_changed"] == 1

        # Re-save updated source at s80, then simulate codec/runtime upgrade -> runtime_changed
        cache.set(source, s80, res1)
        cache.identity = '{"schema": 999}'
        assert cache.get(source, s80) is None
        diag = cache.diagnostics()
        assert diag["miss_reasons"]["runtime_changed"] == 1
        assert diag["invalidation_causes"]["runtime_changed"] == 1

