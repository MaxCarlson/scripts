#!/usr/bin/env python3
"""
Reusable video transformation helpers for dataset generation.

These functions wrap ffmpeg commands to trim, scale, modify bitrate, drop
audio, and change containers. They raise RuntimeError on failures and use
logging for diagnostics.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH. Install ffmpeg to use video transformations.")


def _ffmpeg_prefix(mode: str) -> list[str]:
    prefix = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if mode == "cuda":
        prefix += ["-hwaccel", "cuda"]
    return prefix


def _run_ffmpeg(args: list[str]) -> None:
    logger.debug("Running ffmpeg: %s", " ".join(args))
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
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
    mode: str = "cpu",
    threads: Optional[int] = None,
) -> None:
    _ensure_ffmpeg()
    args: list[str] = _ffmpeg_prefix(mode) + ["-ss", str(max(0.0, start)), "-i", str(input_path)]
    if duration is not None and duration > 0:
        args += ["-t", str(duration)]
    args += ["-c:v", "copy"]
    if audio_copy:
        args += ["-c:a", "copy"]
    else:
        args += ["-an"]
    if threads is not None:
        args += ["-threads", str(threads)]
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
    mode: str = "cpu",
    threads: Optional[int] = None,
) -> None:
    _ensure_ffmpeg()
    if width is None and height is None:
        raise ValueError("Either width or height must be provided for scaling.")
    if keep_aspect:
        w = width if width is not None else -1
        h = height if height is not None else -1
    else:
        w = width if width is not None else "iw"
        h = height if height is not None else "ih"
    scale_filter = f"scale={w}:{h}"
    encoder = "h264_nvenc" if mode == "cuda" else "libx264"
    args: list[str] = _ffmpeg_prefix(mode) + [
        "-i",
        str(input_path),
        "-vf",
        scale_filter,
        "-c:v",
        encoder,
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "copy",
    ]
    if threads is not None:
        args += ["-threads", str(threads)]
    args += [str(output_path)]
    _run_ffmpeg(args)
    logger.info("Created scaled video: %s", output_path)


def change_audio_bitrate(
    input_path: Path,
    output_path: Path,
    *,
    bitrate: str,
) -> None:
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


def remove_audio(input_path: Path, output_path: Path) -> None:
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
    mode: str = "cpu",
    threads: Optional[int] = None,
) -> None:
    _ensure_ffmpeg()
    encoder = "h264_nvenc" if mode == "cuda" else "libx264"
    args: list[str] = _ffmpeg_prefix(mode) + ["-i", str(input_path), "-c:v", encoder]
    if bitrate:
        args += ["-b:v", bitrate]
    if crf is not None:
        args += ["-crf", str(crf)]
    if not bitrate and crf is None:
        raise ValueError("Either bitrate or crf must be provided for re-encoding.")
    args += ["-preset", "medium", "-c:a", "copy"]
    if threads is not None:
        args += ["-threads", str(threads)]
    args += [str(output_path)]
    _run_ffmpeg(args)
    logger.info("Changed video bitrate/compression: %s", output_path)


def change_container(input_path: Path, output_path: Path) -> None:
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
