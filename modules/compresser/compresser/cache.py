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
from collections import Counter, OrderedDict
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import PIL
from PIL import features

from .models import CompressionStrategy, ImageMetadata, ImageResult
from .timing import timed
from .inventory_pipeline import FileObservation
from .cancellation import check_cancelled

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

    def __init__(self, max_entries: int = 20_000, *, path: Path | None = None, reuse_persistent: bool = True) -> None:
        self.max_entries = max_entries
        if max_entries < 1:
            raise ValueError("Cache capacity must be positive")
        self._entries: dict[str, ImageResult] = {}
        self._metadata: dict[str, ImageMetadata] = {}
        self._trial_index: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()
        self._history_complete = True
        self._lock = threading.RLock()
        self.reuse_persistent = reuse_persistent
        self._connection: sqlite3.Connection | None = None
        self._closed = False
        self._writes_since_prune = 0
        self._prune_interval = min(256, max_entries)
        self._lookup_hits = 0
        self._miss_reasons: Counter[str] = Counter()
        self._invalidation_causes: Counter[str] = Counter()
        self._dates = {"created_at": None, "tracking_started_at": None, "last_result_saved_at": None}
        self.path = path.expanduser().resolve() if path else None
        self.identity = json.dumps(_runtime_identity(), sort_keys=True)
        if self.path:
            existing = self.path.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
            try:
                self._connection.execute(
                    "CREATE TABLE IF NOT EXISTS entries (kind TEXT, key TEXT, data TEXT, PRIMARY KEY(kind,key))"
                )
                self._connection.execute("CREATE TABLE IF NOT EXISTS cache_metadata (key TEXT PRIMARY KEY,value TEXT)")
                self._connection.execute(
                    "CREATE TABLE IF NOT EXISTS trial_index ("
                    "path_hash TEXT, strategy_hash TEXT, entry_key TEXT, "
                    "source_stamp TEXT, runtime_hash TEXT, updated_at TEXT, "
                    "PRIMARY KEY(path_hash, strategy_hash))"
                )
                now = datetime.now(timezone.utc).isoformat()
                initial = {
                    "created_at": None if existing else now,
                    "tracking_started_at": now,
                    "last_result_saved_at": None,
                    "history_complete": "0" if existing else "1",
                }
                self._connection.executemany("INSERT OR IGNORE INTO cache_metadata VALUES(?,?)", initial.items())
                self._dates.update(dict(self._connection.execute("SELECT key,value FROM cache_metadata")))
                self._history_complete = self._dates.pop("history_complete") == "1"
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

    def diagnostics(self) -> dict:
        """Return run trial-lookup counters and trustworthy persisted cache dates."""
        with self._lock:
            if self.path and not self._closed:
                values = dict(self._database().execute("SELECT key,value FROM cache_metadata"))
                self._dates.update({key: value for key, value in values.items() if key != "history_complete"})
            return {
                "file": str(self.path) if self.path else None,
                **self._dates,
                "lookup_hits": self._lookup_hits,
                "lookup_misses": sum(self._miss_reasons.values()),
                "miss_reasons": dict(self._miss_reasons),
                "invalidation_causes": dict(self._invalidation_causes),
                "diagnostic_memory_entries": len(self._trial_index),
                "diagnostic_memory_limit": self.max_entries,
                "history_complete": self._history_complete,
                "counter_scope": "current run trial lookups, including AUTO candidate probes; not image counts",
            }

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
        db = self._database()
        db.execute(
            "DELETE FROM entries WHERE rowid IN (SELECT rowid FROM entries ORDER BY rowid DESC LIMIT -1 OFFSET ?)",
            (self.max_entries,),
        )
        # Diagnostic history is durable, separate from bounded result retention.
        self._writes_since_prune = 0

    def _trial_components(
        self, path: Path, strategy: CompressionStrategy, *, legacy: bool = False
    ) -> tuple[str, str, str, str]:
        resolved = str(path.resolve())
        path_hash = hashlib.sha256(resolved.encode("utf-8")).hexdigest()
        try:
            stat = path.stat()
            source_stamp = f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
        except OSError:
            source_stamp = "missing"
        strategy_hash = hashlib.sha256(_strategy_key(strategy, legacy=legacy).encode("utf-8")).hexdigest()
        runtime_hash = hashlib.sha256(self.identity.encode("utf-8")).hexdigest()
        return path_hash, strategy_hash, source_stamp, runtime_hash

    def _make_key(self, path: Path, strategy: CompressionStrategy, *, legacy: bool = False) -> str:
        try:
            stat = path.stat()
            ident = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}:{self.identity}:{_strategy_key(strategy, legacy=legacy)}"
        except OSError:
            ident = f"{path.resolve()}:{self.identity}:{_strategy_key(strategy, legacy=legacy)}"
        return hashlib.sha256(ident.encode("utf-8")).hexdigest()

    def _classify_miss(self, path: Path, strategy: CompressionStrategy) -> tuple[str, str]:
        if self.path and not self.reuse_persistent:
            return "refresh_policy", "refresh_policy"
        path_hash, strategy_hash, source_stamp, runtime_hash = self._trial_components(path, strategy)
        exact_strat = self._trial_index.get((path_hash, strategy_hash))
        known = [value for (p_hash, _), value in self._trial_index.items() if p_hash == path_hash]
        if self.path and not self._closed:
            db = self._database()
            row = db.execute(
                "SELECT entry_key,source_stamp,runtime_hash FROM trial_index WHERE path_hash=? AND strategy_hash=?",
                (path_hash, strategy_hash),
            ).fetchone()
            if row:
                exact_strat = dict(zip(("entry_key", "source_stamp", "runtime_hash"), row))
                self._remember_trial(path_hash, strategy_hash, exact_strat)
            if exact_strat is None:
                # Do not materialize all settings ever tried for this path.
                if db.execute(
                    "SELECT 1 FROM trial_index WHERE path_hash=? AND source_stamp!=? LIMIT 1",
                    (path_hash, source_stamp),
                ).fetchone():
                    return "source_changed", "source_changed"
                if db.execute("SELECT 1 FROM trial_index WHERE path_hash=? LIMIT 1", (path_hash,)).fetchone():
                    return "settings_changed", "settings_changed"
        if exact_strat is not None:
            if exact_strat["source_stamp"] != source_stamp:
                return "source_changed", "source_changed"
            if exact_strat["runtime_hash"] != runtime_hash:
                return "runtime_changed", "runtime_changed"
            return "evicted", "evicted"
        if not self.path and not self._history_complete:
            return "no_matching_entry", "history_unavailable"
        if not known:
            return "no_matching_entry", "never_measured" if self._history_complete else "history_unavailable"
        if any(item["source_stamp"] != source_stamp for item in known):
            return "source_changed", "source_changed"
        return "settings_changed", "settings_changed"

    def _remember_trial(self, path_hash: str, strategy_hash: str, value: dict[str, str]) -> None:
        ident = (path_hash, strategy_hash)
        self._trial_index[ident] = value
        self._trial_index.move_to_end(ident)
        while len(self._trial_index) > self.max_entries:
            self._trial_index.popitem(last=False)
            if not self.path:
                self._history_complete = False

    @timed("cache")
    def get(self, path: Path, strategy: CompressionStrategy) -> ImageResult | None:
        return self._lookup(path, strategy, self._make_key(path, strategy))

    def _lookup(self, path, strategy, key, *, rows=None, legacy_key=None):
        with self._lock:
            cached = self._entries.get(key)
            if cached is None and self.path and self.reuse_persistent:
                data = rows.get(key) if rows is not None else self._load("trial", key)
                if data is None:
                    # Previous versions included display labels and irrelevant
                    # lossless quality settings. Exact legacy matches remain safe.
                    legacy_key = legacy_key or self._make_key(path, strategy, legacy=True)
                    data = rows.get(legacy_key) if rows is not None else self._load("trial", legacy_key)
                if data:
                    try:
                        data["input_path"] = Path(data["input_path"])
                        data["output_path"] = Path(data["output_path"])
                        cached = ImageResult(**data)
                        if len(self._entries) >= self.max_entries:
                            self._entries.pop(next(iter(self._entries)))
                        self._entries[key] = cached
                    except (KeyError, TypeError, ValueError):
                        self._miss_reasons["invalid_record"] += 1
                        self._invalidation_causes["invalid_record"] += 1
                        return None
            if cached is not None:
                self._lookup_hits += 1
            else:
                reason, cause = self._classify_miss(path, strategy)
                self._miss_reasons[reason] += 1
                self._invalidation_causes[cause] += 1
            return replace(cached, cache_hit=True) if cached else None

    @timed("cache")
    def get_many(
        self, requests: Sequence[tuple[ImageMetadata, CompressionStrategy, FileObservation]]
    ) -> list[ImageResult | None]:
        """Bounded bulk SQL with scalar semantics and fresh no-follow evidence."""
        results = []
        for start in range(0, len(requests), 128):
            prepared = []
            for meta, strategy, observation in requests[start : start + 128]:
                check_cancelled()
                observation.validate()
                info = observation.info
                if (
                    meta.path != observation.path
                    or meta.size_bytes != info.st_size
                    or (meta.mtime_ns and meta.mtime_ns != info.st_mtime_ns)
                ):
                    raise RuntimeError(f"Source changed before cache lookup: {meta.path}")
                resolved = meta.path.resolve()
                prefix = f"{resolved}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}:{self.identity}:"
                key, legacy_key = [
                    hashlib.sha256((prefix + _strategy_key(strategy, legacy=legacy)).encode("utf-8")).hexdigest()
                    for legacy in (False, True)
                ]
                prepared.append((meta, strategy, observation, key, legacy_key))
            with self._lock:
                rows = {}
                if self.path and self.reuse_persistent:
                    keys = list(
                        dict.fromkeys(
                            key
                            for meta, strategy, observation, primary, legacy in prepared
                            for key in (primary, legacy)
                        )
                    )
                    if keys:
                        marks = ",".join("?" for _ in keys)
                        for key, payload in self._database().execute(
                            f"SELECT key,data FROM entries WHERE kind='trial' AND key IN ({marks})", keys
                        ):
                            try:
                                value = json.loads(payload)
                                rows[key] = value if isinstance(value, dict) else None
                            except ValueError:
                                rows[key] = None
            for meta, strategy, observation, key, legacy in prepared:
                check_cancelled()
                observation.validate()
                result = self._lookup(meta.path, strategy, key, rows=rows, legacy_key=legacy)
                observation.validate()
                results.append(result)
        return results

    @timed("cache")
    def set(self, path: Path, strategy: CompressionStrategy, result: ImageResult) -> None:
        key = self._make_key(path, strategy)
        path_hash, strategy_hash, source_stamp, runtime_hash = self._trial_components(path, strategy)
        with self._lock:
            if len(self._entries) >= self.max_entries:
                keys = list(self._entries.keys())[: max(1, self.max_entries // 5)]
                for k in keys:
                    self._entries.pop(k, None)
            self._entries[key] = result
            self._save(
                "trial",
                key,
                asdict(result),
                index_row=(path_hash, strategy_hash, key, source_stamp, runtime_hash),
            )
            self._remember_trial(
                path_hash,
                strategy_hash,
                {"entry_key": key, "source_stamp": source_stamp, "runtime_hash": runtime_hash},
            )

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

    def _save(
        self,
        kind: str,
        key: str,
        data: dict,
        *,
        index_row: tuple[str, str, str, str, str] | None = None,
    ) -> None:
        if not self.path:
            return
        connection = self._database()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO entries VALUES(?,?,?)", (kind, key, json.dumps(data, default=str))
            )
            if kind == "trial" and index_row is not None:
                saved_at = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    "INSERT OR REPLACE INTO trial_index VALUES(?,?,?,?,?,?)",
                    (*index_row, saved_at),
                )
            self._writes_since_prune += 1
            if self._writes_since_prune >= self._prune_interval:
                self._prune()
            if kind == "trial":
                saved_at = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    "INSERT OR REPLACE INTO cache_metadata VALUES(?,?)", ("last_result_saved_at", saved_at)
                )
            connection.commit()
            if kind == "trial":
                self._dates["last_result_saved_at"] = saved_at
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
            if result is None and self.reuse_persistent:
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
            self._trial_index.clear()
            self._history_complete = True
            if self.path:
                connection = self._database()
                connection.execute("DELETE FROM entries")
                connection.execute("DELETE FROM trial_index")
                connection.execute("INSERT OR REPLACE INTO cache_metadata VALUES('history_complete','1')")
                connection.commit()


def create_analysis_cache(args, root: Path) -> AnalysisCache:
    """Choose per-library persistence; refreshed trials remain reusable in-run."""
    from .inventory import inventory_path

    policy = getattr(args, "cache_policy", "use")
    if policy == "off":
        return AnalysisCache()
    explicit = getattr(args, "cache_file", None)
    path = (
        Path(explicit).expanduser().resolve() if explicit else inventory_path(args, root).with_suffix(".trials.sqlite3")
    )
    target = root.resolve()
    if path == target or (target.is_dir() and target in path.parents):
        raise ValueError("Analysis cache must be outside the input tree")
    if path == inventory_path(args, root):
        raise ValueError("Inventory and trial cache must use different files")
    return AnalysisCache(path=path, reuse_persistent=policy == "use")
