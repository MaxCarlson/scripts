from concurrent.futures import ThreadPoolExecutor
import sqlite3

from compresser.cache import AnalysisCache
from compresser.models import CompressionStrategy, ImageResult


def test_connection_reuse_immediate_commit_and_memory_promotion(tmp_path, monkeypatch):
    source = tmp_path / "image.jpg"
    source.write_bytes(b"1234567890")
    strategy = CompressionStrategy("test", format="webp")
    result = ImageResult(source, source.with_suffix(".webp"), 10, 5, "JPEG", "WEBP")
    connect = sqlite3.connect
    calls = []

    def counted(*args, **kwargs):
        calls.append(args)
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counted)
    path = tmp_path / "cache.sqlite3"
    with AnalysisCache(path=path) as cache:
        cache.set(source, strategy, result)
        with connect(path) as reader:
            assert reader.execute("SELECT count(*) FROM entries").fetchone()[0] == 1
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert all(pool.map(lambda _: cache.get(source, strategy).cache_hit, range(40)))
        assert len(calls) == 1
    with AnalysisCache(path=path) as cache:
        assert cache.get(source, strategy).cache_hit
        monkeypatch.setattr(cache, "_load", lambda *a: (_ for _ in ()).throw(AssertionError("Disk read repeated")))
        assert cache.get(source, strategy).cache_hit


def test_periodic_eviction_stays_bounded(tmp_path):
    path = tmp_path / "cache.sqlite3"
    source = tmp_path / "image.jpg"
    source.write_bytes(b"1234567890")
    result = ImageResult(source, source, 10, 5, "JPEG", "JPEG")
    with AnalysisCache(max_entries=3, path=path) as cache:
        for i in range(20):
            cache.set(source, CompressionStrategy(str(i)), result)
            with sqlite3.connect(path) as reader:
                assert reader.execute("SELECT count(*) FROM entries").fetchone()[0] <= 5
        cache.clear()
        with sqlite3.connect(path) as reader:
            assert reader.execute("SELECT count(*) FROM entries").fetchone()[0] == 0
