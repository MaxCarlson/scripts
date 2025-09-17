#!/usr/bin/env python3
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Optional, Tuple

# Try for blake3 python module
try:
    import blake3  # type: ignore
    _HAS_BLAKE3 = True
except Exception:
    _HAS_BLAKE3 = False


def sha256_file(path: Path, block_size: int = 1 << 20) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for block in iter(lambda: f.read(block_size), b""):
                h.update(block)
        return h.hexdigest()
    except Exception:
        return None


def _blake3_digest(data: bytes) -> str:
    if _HAS_BLAKE3:
        return blake3.blake3(data).hexdigest()
    # Fallback: blake2b (~fast) then note algo elsewhere
    return hashlib.blake2b(data).hexdigest()


def partial_hash(
    path: Path,
    *,
    head_bytes: int = 2 * 1024 * 1024,
    tail_bytes: int = 2 * 1024 * 1024,
    mid_bytes: int = 0,
) -> Optional[Tuple[str, str, Optional[str], str]]:
    """
    Return (head_hex, tail_hex, mid_hex_or_None, algo_name)
    Using BLAKE3 if available, else BLAKE2b as fallback.
    Only reads the requested slices.
    """
    try:
        size = path.stat().st_size
        if size <= 0:
            return None
        head = tail = mid = b""
        with path.open("rb") as f:
            if head_bytes > 0:
                head = f.read(head_bytes)
            if tail_bytes > 0:
                # Seek from end
                f.seek(max(0, size - tail_bytes))
                tail = f.read(tail_bytes)
        if mid_bytes > 0 and size > (head_bytes + tail_bytes + mid_bytes):
            with path.open("rb") as f2:
                start = max(0, (size // 2) - (mid_bytes // 2))
                f2.seek(start)
                mid = f2.read(mid_bytes)
        algo = "blake3" if _HAS_BLAKE3 else "blake2b"
        return (_blake3_digest(head), _blake3_digest(tail), (_blake3_digest(mid) if mid_bytes > 0 else None), algo)
    except Exception:
        return None
