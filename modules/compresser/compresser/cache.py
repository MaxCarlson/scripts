#!/usr/bin/env python3
"""
Caching layer for image analysis and compression benchmarks.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
from dataclasses import asdict, replace
from pathlib import Path

import PIL
from PIL import features

from .models import CompressionStrategy, ImageMetadata, ImageResult
from .timing import timed

CACHE_SCHEMA = 3
METRIC_REVISION = "bounded-gaussian-rgb-native-patches-3"


def _runtime_identity() -> dict:
    tool = shutil.which("jpegtran")
    tool_stamp = None
    if tool:
        stat = Path(tool).stat()
        tool_stamp = [tool, stat.st_size, stat.st_mtime_ns]
    return {
        "schema": CACHE_SCHEMA,
        "pillow": PIL.__version__,
        "metric": METRIC_REVISION,
        "jpeg": features.version_codec("jpg"),
        "webp": features.version_module("webp"),
        "zlib": features.version_codec("zlib"),
        "jpegtran": tool_stamp,
        "avif": features.version_module("avif") if "avif" in features.get_supported_modules() else None,
        "encoder_policy": "verified-measured-auto-png-1",
    }


def _strategy_key(strategy: CompressionStrategy, *, legacy: bool = False) -> str:
    payload = {
        "pillow_version": getattr(PIL, "__version__", "unknown"),
        "format": strategy.format,
        "mode": strategy.mode,
        "quality": (
            strategy.quality if legacy or strategy.mode != "lossless" or not 1 <= strategy.quality <= 100 else None
        ),
        "perceptual_target": strategy.perceptual_target,
        "method": strategy.method,
        "progressive": strategy.progressive,
        "allow_larger": strategy.allow_larger,
        "allow_lossy": strategy.allow_lossy,
        "encoder": strategy.encoder,
        "extra_params": strategy.extra_params,
    }
    if legacy:
        payload["name"] = strategy.name
    return json.dumps(payload, sort_keys=True)


class AnalysisCache:
    """Thread-safe in-memory cache for repeated compression benchmarks."""

    def __init__(self, max_entries: int = 20_000, *, path: Path | None = None) -> None:
        self.max_entries = max_entries
        if max_entries < 1:
            raise ValueError("Cache capacity must be positive")
        self._entries: dict[str, ImageResult] = {}
        self._metadata: dict[str, ImageMetadata] = {}
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._closed = False
        self._writes_since_prune = 0
        self._prune_interval = min(256, max_entries)
        self.path = path.expanduser().resolve() if path else None
        self.identity = json.dumps(_runtime_identity(), sort_keys=True)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
            try:
                self._connection.execute(
                    "CREATE TABLE IF NOT EXISTS entries (kind TEXT, key TEXT, data TEXT, PRIMARY KEY(kind,key))"
                )
                self._prune()
                self._connection.commit()
            except BaseException:
                self.close()
                raise

    def close(self) -> None:
        """Release SQLite handles; every successful set is already committed."""
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        if getattr(self, "_connection", None) is not None:
            self._connection.close()

    def _database(self) -> sqlite3.Connection:
        if self._closed or self._connection is None:
            raise RuntimeError("Analysis cache is closed")
        return self._connection

    def _prune(self) -> None:
        self._database().execute(
            "DELETE FROM entries WHERE rowid IN (SELECT rowid FROM entries ORDER BY rowid DESC LIMIT -1 OFFSET ?)",
            (self.max_entries,),
        )
        self._writes_since_prune = 0

    def _make_key(self, path: Path, strategy: CompressionStrategy, *, legacy: bool = False) -> str:
        try:
            stat = path.stat()
            ident = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}:{self.identity}:{_strategy_key(strategy, legacy=legacy)}"
        except OSError:
            ident = f"{path.resolve()}:{self.identity}:{_strategy_key(strategy, legacy=legacy)}"
        return hashlib.sha256(ident.encode("utf-8")).hexdigest()

    @timed("cache")
    def get(self, path: Path, strategy: CompressionStrategy) -> ImageResult | None:
        key = self._make_key(path, strategy)
        with self._lock:
            cached = self._entries.get(key)
            if cached is None and self.path:
                data = self._load("trial", key)
                if data is None:
                    # Previous versions included display labels and irrelevant
                    # lossless quality settings. Exact legacy matches remain safe.
                    data = self._load("trial", self._make_key(path, strategy, legacy=True))
                if data:
                    try:
                        data["input_path"] = Path(data["input_path"])
                        data["output_path"] = Path(data["output_path"])
                        cached = ImageResult(**data)
                        if len(self._entries) >= self.max_entries:
                            self._entries.pop(next(iter(self._entries)))
                        self._entries[key] = cached
                    except (KeyError, TypeError, ValueError):
                        return None
            return replace(cached, cache_hit=True) if cached else None

    @timed("cache")
    def set(self, path: Path, strategy: CompressionStrategy, result: ImageResult) -> None:
        key = self._make_key(path, strategy)
        with self._lock:
            if len(self._entries) >= self.max_entries:
                keys = list(self._entries.keys())[: max(1, self.max_entries // 5)]
                for k in keys:
                    self._entries.pop(k, None)
            self._entries[key] = result
            self._save("trial", key, asdict(result))

    def _load(self, kind: str, key: str) -> dict | None:
        if not self.path:
            return None
        row = self._database().execute("SELECT data FROM entries WHERE kind=? AND key=?", (kind, key)).fetchone()
        if row:
            try:
                data = json.loads(row[0])
                return data if isinstance(data, dict) else None
            except ValueError:
                return None
        return None

    def _save(self, kind: str, key: str, data: dict) -> None:
        if not self.path:
            return
        connection = self._database()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO entries VALUES(?,?,?)", (kind, key, json.dumps(data, default=str))
            )
            self._writes_since_prune += 1
            if self._writes_since_prune >= self._prune_interval:
                self._prune()
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def _metadata_key(self, path: Path, check_grayscale: bool) -> str:
        stat = path.stat()
        return hashlib.sha256(
            f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}:{self.identity}:{check_grayscale}".encode()
        ).hexdigest()

    def get_metadata(self, path: Path, check_grayscale: bool = False) -> ImageMetadata | None:
        key = self._metadata_key(path, check_grayscale)
        with self._lock:
            result = self._metadata.get(key)
            if result is None:
                data = self._load("metadata", key)
                if data:
                    try:
                        data["path"] = Path(data["path"])
                        result = ImageMetadata(**data)
                        if len(self._metadata) >= self.max_entries:
                            self._metadata.pop(next(iter(self._metadata)))
                        self._metadata[key] = result
                    except (ValueError, KeyError, TypeError):
                        return None
            return result

    def set_metadata(self, meta: ImageMetadata, check_grayscale: bool = False) -> None:
        stat = meta.path.stat()
        if meta.mtime_ns and (stat.st_mtime_ns != meta.mtime_ns or stat.st_size != meta.size_bytes):
            return
        key = self._metadata_key(meta.path, check_grayscale)
        with self._lock:
            if len(self._metadata) >= self.max_entries:
                self._metadata.pop(next(iter(self._metadata)))
            self._metadata[key] = meta
            self._save("metadata", key, asdict(meta))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._metadata.clear()
            if self.path:
                connection = self._database()
                connection.execute("DELETE FROM entries")
                connection.commit()
