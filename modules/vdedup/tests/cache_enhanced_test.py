#!/usr/bin/env python3
"""
Enhanced tests for cache consistency and robustness improvements.
"""
import tempfile
import time
from pathlib import Path

from vdedup.cache import HashCache


def test_cache_mtime_validation():
    """Test that cache validates mtime to prevent stale data."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        cache_path = temp_path / "test_cache.jsonl"
        test_file = temp_path / "test_file.txt"

        # Create test file
        test_file.write_text("original content")
        original_stat = test_file.stat()
        original_size = original_stat.st_size
        original_mtime = original_stat.st_mtime

        # Create cache and store a hash
        cache = HashCache(cache_path)
        cache.open_append()
        cache.put_field(test_file, original_size, original_mtime, "sha256", "fake_hash_1")

        # Verify we can retrieve the hash with correct metadata
        result = cache.get_sha256(test_file, original_size, original_mtime)
        assert result == "fake_hash_1"

        # Modify file (change mtime)
        time.sleep(1.1)  # Ensure mtime difference > 1 second
        test_file.write_text("modified content")
        new_stat = test_file.stat()
        new_mtime = new_stat.st_mtime

        # Should return None due to mtime mismatch (using new actual mtime vs old cached mtime)
        result = cache.get_sha256(test_file, new_stat.st_size, new_mtime)
        assert result is None  # Cache entry has old mtime, won't match

        cache.close()


def test_cache_tolerance():
    """Test that cache allows reasonable mtime tolerance."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        cache_path = temp_path / "test_cache.jsonl"
        test_file = temp_path / "test_file.txt"

        # Create test file
        test_file.write_text("test content")
        stat = test_file.stat()

        # Create cache and store a hash
        cache = HashCache(cache_path)
        try:
            cache.open_append()
            cache.put_field(test_file, stat.st_size, stat.st_mtime, "sha256", "fake_hash")

            # Test with slight mtime difference (within tolerance)
            result = cache.get_sha256(test_file, stat.st_size, stat.st_mtime + 0.5)
            assert result == "fake_hash"

            # Test with larger mtime difference (outside tolerance)
            result = cache.get_sha256(test_file, stat.st_size, stat.st_mtime + 2.0)
            assert result is None
        finally:
            cache.close()


def test_cache_all_getters_validation():
    """Test that all cache getter methods validate mtime consistently."""
    with tempfile.TemporaryDirectory() as temp_dir:
        cache_path = Path(temp_dir) / "test_cache.jsonl"
        test_file = Path(temp_dir) / "test_file.txt"

        # Create test file
        test_file.write_text("test content")
        stat = test_file.stat()

        # Create cache and store various data types
        cache = HashCache(cache_path)
        cache.open_append()
        cache.put_field(test_file, stat.st_size, stat.st_mtime, "sha256", "fake_hash")
        cache.put_field(test_file, stat.st_size, stat.st_mtime, "partial", {"head": "fake_partial"})
        cache.put_field(test_file, stat.st_size, stat.st_mtime, "video_meta", {"duration": 123.45})
        cache.put_field(test_file, stat.st_size, stat.st_mtime, "phash", [1, 2, 3, 4])

        # Test all getters with correct metadata
        assert cache.get_sha256(test_file, stat.st_size, stat.st_mtime) == "fake_hash"
        assert cache.get_partial(test_file, stat.st_size, stat.st_mtime) == {"head": "fake_partial"}
        assert cache.get_video_meta(test_file, stat.st_size, stat.st_mtime) == {"duration": 123.45}
        assert cache.get_phash(test_file, stat.st_size, stat.st_mtime) == [1, 2, 3, 4]

        # Test all getters with incorrect mtime (should all return None)
        bad_mtime = stat.st_mtime + 5.0
        assert cache.get_sha256(test_file, stat.st_size, bad_mtime) is None
        assert cache.get_partial(test_file, stat.st_size, bad_mtime) is None
        assert cache.get_video_meta(test_file, stat.st_size, bad_mtime) is None
        assert cache.get_phash(test_file, stat.st_size, bad_mtime) is None

        cache.close()


if __name__ == "__main__":
    test_cache_mtime_validation()
    test_cache_tolerance()
    test_cache_all_getters_validation()
    print("All cache enhancement tests passed!")