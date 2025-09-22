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
    """
    Compute SHA-256 hash of a file with robust error handling.

    Args:
        path: Path to file to hash
        block_size: Read buffer size in bytes

    Returns:
        Hex string of SHA-256 hash, or None if error occurs

    Raises:
        No exceptions - returns None on any error for robustness
    """
    if not path or not path.exists() or not path.is_file():
        return None

    try:
        h = hashlib.sha256()
        file_size = path.stat().st_size

        # Skip empty files
        if file_size == 0:
            return h.hexdigest()  # Return hash of empty content

        with path.open("rb") as f:
            bytes_read = 0
            for block in iter(lambda: f.read(block_size), b""):
                h.update(block)
                bytes_read += len(block)

                # Sanity check to prevent infinite loops on special files
                if bytes_read > file_size * 2:  # Allow some tolerance
                    return None

        return h.hexdigest()

    except (FileNotFoundError, PermissionError, OSError) as e:
        # Expected file system errors
        return None
    except MemoryError:
        # Handle very large files that might exhaust memory
        return None
    except Exception:
        # Catch-all for unexpected errors
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
    Only reads the requested slices for HDD-friendly performance.

    Args:
        path: Path to file to hash
        head_bytes: Bytes to read from start of file
        tail_bytes: Bytes to read from end of file
        mid_bytes: Bytes to read from middle of file (0 to skip)

    Returns:
        Tuple of (head_hash, tail_hash, mid_hash_or_None, algorithm_name)
        or None if error occurs

    Raises:
        No exceptions - returns None on any error for robustness
    """
    if not path or not path.exists() or not path.is_file():
        return None

    # Validate parameters
    if head_bytes < 0 or tail_bytes < 0 or mid_bytes < 0:
        return None

    try:
        size = path.stat().st_size
        if size <= 0:
            return None

        # Calculate how much to read for head and tail
        # For small files, we'll read the whole file as both head and tail
        actual_head = min(head_bytes, size)
        actual_tail = min(tail_bytes, size)
        actual_mid = 0

        # If file is large enough, calculate middle section
        if mid_bytes > 0 and size > (head_bytes + tail_bytes + mid_bytes):
            actual_mid = min(mid_bytes, size - head_bytes - tail_bytes)

        head = tail = mid = b""

        with path.open("rb") as f:
            # Read head
            if actual_head > 0:
                f.seek(0)
                head = f.read(actual_head)

            # Read tail
            if actual_tail > 0:
                if size <= actual_head:
                    # Small file: tail is the same as head
                    tail = head
                else:
                    # Larger file: read from end
                    f.seek(max(0, size - actual_tail))
                    tail = f.read(actual_tail)

            # Read middle (only if file is large enough and it was requested)
            if actual_mid > 0:
                mid_start = head_bytes + ((size - head_bytes - tail_bytes - actual_mid) // 2)
                f.seek(mid_start)
                mid = f.read(actual_mid)

        algo = "blake3" if _HAS_BLAKE3 else "blake2b"
        mid_hash = _blake3_digest(mid) if actual_mid > 0 and mid else None

        return (_blake3_digest(head), _blake3_digest(tail), mid_hash, algo)

    except (FileNotFoundError, PermissionError, OSError):
        # Expected file system errors
        return None
    except MemoryError:
        # Handle large read requests that might exhaust memory
        return None
    except Exception:
        # Catch-all for unexpected errors
        return None
