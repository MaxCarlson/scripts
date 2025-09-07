#!/usr/bin/env python3
from __future__ import annotations
import io
import subprocess
from typing import List, Optional, Sequence, Tuple
from pathlib import Path

def _ffmpeg_frame_cmd(path: Path, ts: float, *, gpu: bool) -> list:
    """
    Build ffmpeg command to grab a single keyframe near timestamp ts.
    NVDEC/CUDA is hinted when gpu=True; ffmpeg falls back gracefully if unsupported.  # 5
    We request demuxer-side seek (-ss before -i) and decode only keyframes (-skip_frame nokey).  # 6
    """
    base = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{ts:.3f}", "-skip_frame", "nokey", "-i", str(path),
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
    ]
    if gpu:
        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-hwaccel", "cuda"] + base[2:]
    return base

def compute_phash_signature(path: Path, frames: int = 5, *, gpu: bool = False) -> Optional[Tuple[int, ...]]:
    try:
        from PIL import Image
        import imagehash
    except Exception:
        return None

    # Probe duration lazily via ffprobe (import locally to avoid cycle)
    from .probe import run_ffprobe_json
    fmt = run_ffprobe_json(path)
    try:
        duration = float(fmt.get("format", {}).get("duration", 0.0)) if fmt else 0.0
    except Exception:
        duration = 0.0
    if duration <= 0:
        return None

    sig: List[int] = []
    fractions = [(i + 1) / (frames + 1) for i in range(frames)]
    for frac in fractions:
        ts = max(0.0, min(duration * frac, max(0.0, duration - 0.1)))
        # Try GPU then CPU
        for attempt in (0, 1):
            try:
                cmd = _ffmpeg_frame_cmd(path, ts, gpu=(gpu and attempt == 0))
                raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
                img = Image.open(io.BytesIO(raw))
                img.load()
                h = imagehash.phash(img)  # 64-bit default
                sig.append(int(str(h), 16))
                break
            except Exception:
                # fallback once; if that fails, skip this frame
                continue

    if len(sig) < max(2, frames // 2):
        return None
    return tuple(sig)

def phash_distance(sig_a: Sequence[int], sig_b: Sequence[int]) -> int:
    dist = 0
    for a, b in zip(sig_a, sig_b):
        x = int(a) ^ int(b)
        dist += x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
    return dist
