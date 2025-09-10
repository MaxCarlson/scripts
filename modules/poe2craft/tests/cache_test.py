#!/usr/bin/env python3
from __future__ import annotations

import os
import time
from pathlib import Path

# Ensure package import works when repo layout is <root>/scripts/poe2craft
import sys
ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "scripts"
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))

from poe2craft.util.cache import SimpleCache  # noqa: E402


def test_cache_put_get_roundtrip(tmp_path: Path, monkeypatch):
    cache_dir = tmp_path / ".cache"
    cache = SimpleCache(root=cache_dir, ttl_seconds=3600)

    url = "http://example.com/a"
    payload = b"hello-world"
    cache.put(url, payload)

    got = cache.get(url)
    assert got == payload


def test_cache_expired_returns_none(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    cache = SimpleCache(root=cache_dir, ttl_seconds=0)  # expires immediately

    url = "http://example.com/expire"
    payload = b"payload"
    cache.put(url, payload)

    # With ttl=0, any get() should be considered expired
    assert cache.get(url) is None


def test_cache_corrupted_header_returns_none(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    cache = SimpleCache(root=cache_dir, ttl_seconds=3600)

    url = "http://example.com/corrupt"
    fp = cache._key(url)
    fp.parent.mkdir(parents=True, exist_ok=True)

    # Write a file with a non-JSON header and no newline (to exercise error path)
    fp.write_bytes(b"NOTJSON HEADER WITHOUT NEWLINE")  # no newline; will raise and return None

    assert cache.get(url) is None


def test_cache_bad_json_then_payload_returns_none(tmp_path: Path):
    cache_dir = tmp_path / ".cache"
    cache = SimpleCache(root=cache_dir, ttl_seconds=3600)

    url = "http://example.com/badjson"
    fp = cache._key(url)
    fp.parent.mkdir(parents=True, exist_ok=True)

    # Header is invalid JSON but with a newline; should be handled gracefully.
    fp.write_bytes(b"{this is not json}\nreal-payload-ignored")

    assert cache.get(url) is None
