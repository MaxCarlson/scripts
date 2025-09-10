#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional


class SimpleCache:
    """
    Extremely small file-based cache for HTTP GET payloads.
    Not concurrency-safe across processes (good enough for CLI usage).
    """

    def __init__(self, root: Optional[Path] = None, ttl_seconds: int = 6 * 3600):
        self.root = root or Path(os.getenv("POE2CRAFT_CACHE_DIR", Path.home() / ".cache" / "poe2craft"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds

    def _key(self, url: str) -> Path:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.root / f"{h}.json"

    def get(self, url: str) -> Optional[bytes]:
        fp = self._key(url)
        if not fp.exists():
            return None
        try:
            with fp.open("rb") as f:
                raw = f.read()
            meta = json.loads(raw[: raw.find(b"\n")].decode("utf-8"))
            if time.time() - meta.get("ts", 0) > self.ttl:
                return None
            return raw[raw.find(b"\n") + 1 :]
        except Exception:
            return None

    def put(self, url: str, payload: bytes) -> None:
        fp = self._key(url)
        meta = {"ts": time.time()}
        atom = fp.with_suffix(".json.tmp")
        with atom.open("wb") as f:
            f.write(json.dumps(meta).encode("utf-8"))
            f.write(b"\n")
            f.write(payload)
        atom.replace(fp)
