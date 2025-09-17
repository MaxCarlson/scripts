#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class HashCache:
    """
    JSONL append-only cache. Each line is an object with at least:
      - "path": str, "size": int, "mtime": float
    Optional fields (written as produced):
      - "sha256": str
      - "partial": {"algo": "blake3"|"sha256", "head": str, "tail": str, "mid": str|None, "head_bytes": int, "tail_bytes": int, "mid_bytes": int}
      - "video_meta": {...} (normalized ffprobe info)
      - "phash": [int, ...]  (list of 64-bit ints)
    Lookup key is (path, size, mtime).
    """
    def __init__(self, path: Optional[Path]):
        self.path = path
        self._map: Dict[Tuple[str, int, float], Dict[str, Any]] = {}
        self._fh = None
        if path:
            self._load()

    def _load(self):
        p = Path(self.path).expanduser()
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            return
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        k = (rec.get("path", ""), int(rec.get("size", 0)), float(rec.get("mtime", 0.0)))
                        if k[0]:
                            self._map[k] = rec
                    except Exception:
                        continue
        except Exception:
            pass

    def open_append(self):
        if not self.path:
            return
        p = Path(self.path).expanduser()
        self._fh = p.open("a", encoding="utf-8")

    def close(self):
        if self._fh:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None

    def _key(self, path: Path, size: int, mtime: float):
        return (str(path), int(size), float(mtime))

    def get_record(self, path: Path, size: int, mtime: float) -> Optional[Dict[str, Any]]:
        return self._map.get(self._key(path, size, mtime))

    def put_field(self, path: Path, size: int, mtime: float, field: str, value: Any):
        k = self._key(path, size, mtime)
        rec = self._map.get(k) or {"path": str(path), "size": int(size), "mtime": float(mtime)}
        rec[field] = value
        self._map[k] = rec
        if self._fh:
            try:
                self._fh.write(json.dumps(rec) + "\n")
                self._fh.flush()
            except Exception:
                pass

    # Convenience getters
    def get_sha256(self, path: Path, size: int, mtime: float) -> Optional[str]:
        rec = self.get_record(path, size, mtime)
        return rec.get("sha256") if rec else None

    def get_partial(self, path: Path, size: int, mtime: float) -> Optional[Dict[str, Any]]:
        rec = self.get_record(path, size, mtime)
        return rec.get("partial") if rec else None

    def get_video_meta(self, path: Path, size: int, mtime: float) -> Optional[Dict[str, Any]]:
        rec = self.get_record(path, size, mtime)
        return rec.get("video_meta") if rec else None

    def get_phash(self, path: Path, size: int, mtime: float) -> Optional[Any]:
        rec = self.get_record(path, size, mtime)
        return rec.get("phash") if rec else None
