#!/usr/bin/env python3
"""
Audio fingerprint helpers for vdedup.

Uses ffmpeg to downsample audio to mono PCM blocks, then hashes each window to
create a lightweight signature suitable for similarity matching.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


def compute_audio_fingerprint(
    path: Path,
    *,
    sample_rate: int = 8000,
    window_seconds: float = 3.0,
    max_windows: int = 256,
) -> Optional[Tuple[int, ...]]:
    """
    Generate an audio fingerprint as a tuple of integers.

    Each integer represents the BLAKE2b digest of a PCM window. This keeps the
    signature compact while remaining robust to re-encoding and gain changes.
    """
    sample_rate = max(2000, min(sample_rate, 16000))
    window_seconds = max(0.5, min(window_seconds, 6.0))
    window_bytes = int(sample_rate * window_seconds * 2)  # pcm_s16le => 2 bytes per sample
    if window_bytes <= 0:
        return None

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "pipe:1",
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:
        return None

    sig: List[int] = []
    try:
        if not proc.stdout:
            return None
        while len(sig) < max_windows:
            chunk = proc.stdout.read(window_bytes)
            if not chunk:
                break
            if not chunk.strip(b"\x00"):
                continue
            digest = hashlib.blake2b(chunk, digest_size=8).digest()
            sig.append(int.from_bytes(digest, "big"))
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        return None
    finally:
        if proc.stdout:
            proc.stdout.close()

    if len(sig) < max(6, max_windows // 8):
        return None
    return tuple(sig)
