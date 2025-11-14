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

    # Use batch extraction for better performance
    return _compute_phash_batch(path, duration, frames, gpu=gpu)


def _compute_phash_batch(path: Path, duration: float, frames: int, *, gpu: bool = False) -> Optional[Tuple[int, ...]]:
    """
    Extract multiple frames more efficiently by batching seeks.
    Falls back to individual extraction if batch fails.
    """
    try:
        from PIL import Image
        import imagehash
        import tempfile
        import os
    except Exception:
        return None

    # Calculate frame timestamps
    fractions = [(i + 1) / (frames + 1) for i in range(frames)]
    timestamps = [max(0.0, min(duration * frac, max(0.0, duration - 0.1))) for frac in fractions]

    # Use a temporary directory for batch extraction
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_pattern = os.path.join(temp_dir, "frame_%03d.png")

            # Build optimized batch command
            cmd = _ffmpeg_batch_cmd_optimized(path, timestamps, output_pattern, gpu=gpu)

            # Run batch extraction
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                # Fallback to single-frame method
                return _compute_phash_fallback(path, timestamps, gpu=gpu)

            # Process extracted frames
            sig: List[int] = []
            for i in range(frames):
                frame_path = os.path.join(temp_dir, f"frame_{i+1:03d}.png")
                if os.path.exists(frame_path):
                    try:
                        with Image.open(frame_path) as img:
                            h = imagehash.phash(img)
                            sig.append(int(str(h), 16))
                    except Exception:
                        continue

            if len(sig) >= max(2, frames // 2):
                return tuple(sig)

    except Exception:
        pass

    # Fallback to single-frame extraction
    return _compute_phash_fallback(path, timestamps, gpu=gpu)


def _ffmpeg_batch_cmd_optimized(path: Path, timestamps: List[float], output_pattern: str, *, gpu: bool) -> List[str]:
    """
    Build optimized ffmpeg command to extract specific frames to files.
    Uses seek-based extraction which is more efficient than frame selection.
    """
    base_cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]  # -y to overwrite

    if gpu:
        base_cmd.extend(["-hwaccel", "cuda"])

    # Create filter for extracting frames at specific timestamps
    # Use fps filter to extract 1 frame per timestamp
    timestamp_str = ",".join([f"{ts:.3f}" for ts in timestamps])

    cmd = base_cmd + [
        "-i", str(path),
        "-vf", f"fps=fps=1/{len(timestamps)},scale=32:32",  # Extract evenly spaced frames
        "-frames:v", str(len(timestamps)),
        output_pattern
    ]

    return cmd


def _ffmpeg_batch_cmd(path: Path, timestamps: List[float], *, gpu: bool) -> List[str]:
    """
    Build simplified ffmpeg command to extract frames using select filter.
    More reliable than complex filter graphs.
    """
    base_cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]

    if gpu:
        base_cmd.extend(["-hwaccel", "cuda"])

    # Create select expression for specific timestamps
    # Convert timestamps to frame numbers (approximate)
    select_expr = "+".join([f"eq(n,{int(ts * 25)})" for ts in timestamps])  # Assume 25fps average

    cmd = base_cmd + [
        "-i", str(path),
        "-vf", f"select='{select_expr}',scale=32:32",
        "-vsync", "0",  # Don't duplicate/drop frames
        "-f", "image2pipe",
        "-vcodec", "png",
        "pipe:1"
    ]

    return cmd


def _compute_phash_fallback(path: Path, timestamps: List[float], *, gpu: bool) -> Optional[Tuple[int, ...]]:
    """
    Fallback to single-frame extraction if batch method fails.
    """
    try:
        from PIL import Image
        import imagehash
    except Exception:
        return None

    sig: List[int] = []
    for ts in timestamps:
        # Try GPU then CPU
        for attempt in (0, 1):
            try:
                cmd = _ffmpeg_frame_cmd(path, ts, gpu=(gpu and attempt == 0))
                raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
                img = Image.open(io.BytesIO(raw))
                img.load()
                h = imagehash.phash(img)
                sig.append(int(str(h), 16))
                break
            except Exception:
                # fallback once; if that fails, skip this frame
                continue

    if len(sig) < max(2, len(timestamps) // 2):
        return None
    return tuple(sig)

def phash_distance(sig_a: Sequence[int], sig_b: Sequence[int]) -> int:
    dist = 0
    for a, b in zip(sig_a, sig_b):
        x = int(a) ^ int(b)
        dist += x.bit_count() if hasattr(int, "bit_count") else bin(x).count("1")
    return dist


def compute_scene_fingerprint(
    path: Path,
    max_scenes: int = 24,
    scene_threshold: float = 0.35,
    *,
    gpu: bool = False,
) -> Optional[Tuple[int, ...]]:
    """
    Build scene-level perceptual hashes to enable coarse similarity comparisons.
    Returns a tuple of pHash integers, one per detected scene boundary.
    """
    try:
        from PIL import Image
        import imagehash
        import tempfile
    except Exception:
        return None

    threshold = max(0.05, min(scene_threshold, 1.0))
    max_scenes = max(4, max_scenes)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "scene_%05d.png"
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
            if gpu:
                cmd.extend(["-hwaccel", "cuda"])
            cmd += [
                "-i",
                str(path),
                "-vf",
                f"select=gt(scene\\,{threshold:.2f}),scale=96:96",
                "-vsync",
                "vfr",
                "-frames:v",
                str(max_scenes),
                str(output),
            ]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                return None

            sig: List[int] = []
            for frame in sorted(Path(tmp_dir).glob("scene_*.png")):
                if len(sig) >= max_scenes:
                    break
                try:
                    with Image.open(frame) as img:
                        h = imagehash.phash(img)
                        sig.append(int(str(h), 16))
                except Exception:
                    continue

            if len(sig) < 2:
                return None
            return tuple(sig)
    except Exception:
        return None


def compute_timeline_signature(
    path: Path,
    fps: float = 2.0,
    max_frames: int = 120,
    *,
    gpu: bool = False,
) -> Optional[Tuple[int, ...]]:
    """
    Produce a dense timeline fingerprint by sampling frames at a fixed FPS.
    Useful for motion-aware duplicate detection and subset alignment.
    """
    try:
        from PIL import Image
        import imagehash
        import tempfile
    except Exception:
        return None

    fps = max(0.25, min(fps, 10.0))
    max_frames = max(10, max_frames)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "timeline_%05d.png"
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
            if gpu:
                cmd.extend(["-hwaccel", "cuda"])
            cmd += [
                "-i",
                str(path),
                "-vf",
                f"fps={fps:.2f},scale=64:64",
                "-frames:v",
                str(max_frames),
                str(output),
            ]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                return None

            sig: List[int] = []
            for frame in sorted(Path(tmp_dir).glob("timeline_*.png")):
                if len(sig) >= max_frames:
                    break
                try:
                    with Image.open(frame) as img:
                        h = imagehash.phash(img)
                        sig.append(int(str(h), 16))
                except Exception:
                    continue

            if len(sig) < max(6, max_frames // 8):
                return None
            return tuple(sig)
    except Exception:
        return None
