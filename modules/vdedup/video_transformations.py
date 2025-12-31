#!/usr/bin/env python3
"""
Video transformation helpers for generating test variants.

This module wraps `ffmpeg` operations in Python functions to produce
shorter clips, downscaled versions, bitrate‑modified copies and container
changes.  It centralizes error handling and ensures commands are safe on
Windows, WSL2 and Termux.  All functions log their actions and raise
`RuntimeError` on failure.

The module assumes that `ffmpeg` is installed and available on the system
PATH.  On Windows, install via Chocolatey or the official static build;
on Linux/Termux install via the package manager.  Use `shutil.which('ffmpeg')`
to verify availability.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _ensure_ffmpeg() -> None:
    """Raise a RuntimeError if ffmpeg is not available."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg not found in PATH. Install ffmpeg to use video transformations."
        )


def _run_ffmpeg(args: list[str]) -> None:
    """Run an ffmpeg command and raise on error."""
    logger.debug("Running ffmpeg: %s", " ".join(args))
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        # Include stderr in exception for debugging
        raise RuntimeError(
            f"ffmpeg command failed (code {result.returncode}): {' '.join(args)}\n"
            f"stderr: {result.stderr.decode(errors='replace')}"
        )


def trim_video(
    input_path: Path,
    output_path: Path,
    *,
    start: float = 0.0,
    duration: Optional[float] = None,
    audio_copy: bool = True,
) -> None:
    """
    Trim the video at `input_path` starting from `start` seconds for the given
    duration and write the result to `output_path`.  If duration is None, the
    output will include everything from the start to the end.  Audio is
    preserved by default; set `audio_copy=False` to remove audio.
    """
    _ensure_ffmpeg()
    args: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(max(0.0, start)),
        "-i",
        str(input_path),
    ]
    if duration is not None and duration > 0:
        args += ["-t", str(duration)]
    # Use stream copy to avoid re‑encoding video; audio copy if requested
    args += ["-c:v", "copy"]
    if audio_copy:
        args += ["-c:a", "copy"]
    else:
        args += ["-an"]
    args += [str(output_path)]
    _run_ffmpeg(args)
    logger.info("Created trimmed video: %s", output_path)


def scale_video(
    input_path: Path,
    output_path: Path,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    keep_aspect: bool = True,
) -> None:
    """
    Downscale or upscale the video to the specified width and/or height.  If
    `keep_aspect` is True and one dimension is None, ffmpeg will
    automatically calculate the other dimension to preserve the aspect ratio.
    """
    _ensure_ffmpeg()
    if width is None and height is None:
        raise ValueError("Either width or height must be provided for scaling.")
    # Build scale filter
    if keep_aspect:
        w = width if width is not None else -1
        h = height if height is not None else -1
    else:
        w = width if width is not None else "iw"
        h = height if height is not None else "ih"
    scale_filter = f"scale={w}:{h}"
    args: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        scale_filter,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "copy",
        str(output_path),
    ]
    _run_ffmpeg(args)
    logger.info("Created scaled video: %s", output_path)


def change_audio_bitrate(
    input_path: Path,
    output_path: Path,
    *,
    bitrate: str,
) -> None:
    """
    Change the audio bitrate of a video file while copying the video stream.
    `bitrate` must be a string like '64k'.
    """
    _ensure_ffmpeg()
    args: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        str(output_path),
    ]
    _run_ffmpeg(args)
    logger.info("Changed audio bitrate: %s", output_path)


def remove_audio(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Remove the audio track from a video.  Video stream is copied without
    re‑encoding.
    """
    _ensure_ffmpeg()
    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-c:v",
        "copy",
        "-an",
        str(output_path),
    ]
    _run_ffmpeg(args)
    logger.info("Removed audio: %s", output_path)


def change_video_bitrate(
    input_path: Path,
    output_path: Path,
    *,
    bitrate: Optional[str] = None,
    crf: Optional[int] = None,
) -> None:
    """
    Re-encode the video stream with a specified bitrate (e.g. '1M') or CRF
    value to introduce compression artifacts.  If only `crf` is specified,
    ffmpeg will choose the bitrate automatically.  Audio is copied unchanged.
    """
    _ensure_ffmpeg()
    args: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-c:v",
        "libx264",
    ]
    if bitrate:
        args += ["-b:v", bitrate]
    if crf is not None:
        args += ["-crf", str(crf)]
    if not bitrate and crf is None:
        raise ValueError("Either bitrate or crf must be provided for re-encoding.")
    args += ["-preset", "medium", "-c:a", "copy", str(output_path)]
    _run_ffmpeg(args)
    logger.info("Changed video bitrate/compression: %s", output_path)


def change_container(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Copy the streams into a new container (e.g. from .mp4 to .mkv) without
    re-encoding.  This is useful for testing container-specific logic.
    """
    _ensure_ffmpeg()
    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-c",
        "copy",
        str(output_path),
    ]
    _run_ffmpeg(args)
    logger.info("Changed container format: %s", output_path)