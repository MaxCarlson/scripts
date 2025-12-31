#!/usr/bin/env python3
"""
Dataset generation script for `vdedup` test suite.

This script reads a mapping file of opaque keys and, using a separate JSON
mapping of keys to YouTube video IDs, downloads each video via `yt‑dlp` and
applies a series of transformations to create near‑duplicate variants.  It
produces a reproducible dataset under a given output directory with a
consistent layout:

```
output_dir/
├── original/
│   ├── <key>.mp4
│   └── ...
└── variants/
    ├── <key>/
    │   ├── <key>_clip15.mp4
    │   ├── <key>_clip10min.mp4
    │   ├── <key>_clip36_45.mp4
    │   ├── <key>_clip1023_7834.mp4 (if applicable)
    │   ├── <key>_360p.mp4
    │   ├── <key>_240p.mp4
    │   ├── <key>_64k.mp4
    │   ├── <key>_32k.mp4
    │   ├── <key>_noaudio.mp4
    │   ├── <key>_1M.mp4
    │   ├── <key>_crf30.mp4
    │   ├── <key>.mkv
    │   └── <key>_renamed.mp4
    └── ...
```

The script assumes that `yt‑dlp` and `ffmpeg` are installed and available
on the system `PATH`.  It uses helper functions from
`video_transformations.py` to perform trimming, scaling and bitrate
modifications.  If any command fails, the script logs the error and
continues to the next transformation so that partial datasets can still be
used.

Run this script from the root of the repository (or adjust paths
accordingly).  Use the `--mapping-file` argument to specify the list of
random keys, `--id-map` for the JSON mapping file that resolves keys to
YouTube IDs and `--output-dir` to choose the dataset directory.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from .video_transformations import (
    trim_video,
    scale_video,
    change_audio_bitrate,
    remove_audio,
    change_video_bitrate,
    change_container,
)

logger = logging.getLogger(__name__)


def _ensure_yt_dlp() -> None:
    """Raise a RuntimeError if yt-dlp is not available."""
    if not shutil.which("yt-dlp") and not shutil.which("yt_dlp"):
        raise RuntimeError(
            "yt-dlp not found in PATH. Install yt-dlp to download videos."
        )


def download_video(youtube_id: str, dest_dir: Path, key: str) -> Path:
    """
    Download a YouTube video using yt-dlp and return the path to the
    downloaded file.  The file is named after the key (e.g. `<key>.mp4`).
    If the file already exists and is non-empty, it will be reused.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Determine output template: always use mp4 container when possible
    # to simplify downstream processing.  yt-dlp will combine video and audio.
    output_template = str(dest_dir / f"{key}.%(ext)s")
    # Check if any file matching the template already exists
    existing_files = list(dest_dir.glob(f"{key}.*"))
    for f in existing_files:
        if f.stat().st_size > 0:
            logger.info("Reusing existing download for %s: %s", key, f)
            return f
    # Build yt-dlp command
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--merge-output-format",
        "mp4",
        "--format",
        "bestvideo+bestaudio/best",
        "-o",
        output_template,
        f"https://www.youtube.com/watch?v={youtube_id}",
    ]
    logger.info("Downloading video for key %s (ID=%s)", key, youtube_id)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp download failed for {youtube_id} (key {key}): {result.stderr.decode(errors='replace')}"
        )
    # Find the downloaded file
    downloaded_files = list(dest_dir.glob(f"{key}.*"))
    if not downloaded_files:
        raise RuntimeError(
            f"yt-dlp did not produce any file for key {key} ({youtube_id})."
        )
    return downloaded_files[0]


def create_variants(key: str, src_path: Path, dest_dir: Path) -> None:
    """
    Generate a suite of derivative videos from the original at `src_path` and
    write them into `dest_dir`.  Each transformation is wrapped in
    try/except so that failures do not stop subsequent variants.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    base_name = key
    # 1. Trimming
    variants: list[tuple[str, dict]] = [
        ("clip15", {"start": 0.0, "duration": 15.0}),
        ("clip10min", {"start": 0.0, "duration": 600.0}),
        ("clip36_45", {"start": 36.0, "duration": 9.0}),
        ("clip1023_7834", {"start": 1023.0, "duration": 7834.0 - 1023.0}),
    ]
    for suffix, params in variants:
        out_file = dest_dir / f"{base_name}_{suffix}.mp4"
        # Skip if already exists
        if out_file.exists():
            continue
        try:
            # Clip 1023_7834 only if expected duration is positive
            if suffix == "clip1023_7834" and params["duration"] <= 0:
                continue
            trim_video(src_path, out_file, start=params["start"], duration=params["duration"])
        except Exception as exc:
            logger.warning("Failed to create %s: %s", out_file, exc)
    # 2. Resolution changes
    res_variants = [
        ("360p", {"width": None, "height": 360}),
        ("240p", {"width": None, "height": 240}),
    ]
    for suffix, params in res_variants:
        out_file = dest_dir / f"{base_name}_{suffix}.mp4"
        if out_file.exists():
            continue
        try:
            scale_video(src_path, out_file, width=params.get("width"), height=params.get("height"), keep_aspect=True)
        except Exception as exc:
            logger.warning("Failed to create %s: %s", out_file, exc)
    # 3. Audio and bitrate modifications
    audio_variants = [
        ("64k", {"bitrate": "64k"}),
        ("32k", {"bitrate": "32k"}),
    ]
    for suffix, params in audio_variants:
        out_file = dest_dir / f"{base_name}_{suffix}.mp4"
        if out_file.exists():
            continue
        try:
            change_audio_bitrate(src_path, out_file, bitrate=params["bitrate"])
        except Exception as exc:
            logger.warning("Failed to create %s: %s", out_file, exc)
    # Remove audio entirely
    out_noaudio = dest_dir / f"{base_name}_noaudio.mp4"
    if not out_noaudio.exists():
        try:
            remove_audio(src_path, out_noaudio)
        except Exception as exc:
            logger.warning("Failed to create %s: %s", out_noaudio, exc)
    # Video bitrate modifications
    vb_variants = [
        ("1M", {"bitrate": "1M", "crf": None}),
        ("crf30", {"bitrate": None, "crf": 30}),
    ]
    for suffix, params in vb_variants:
        out_file = dest_dir / f"{base_name}_{suffix}.mp4"
        if out_file.exists():
            continue
        try:
            change_video_bitrate(
                src_path,
                out_file,
                bitrate=params.get("bitrate"),
                crf=params.get("crf"),
            )
        except Exception as exc:
            logger.warning("Failed to create %s: %s", out_file, exc)
    # 4. Container change (to mkv)
    out_mkv = dest_dir / f"{base_name}.mkv"
    if not out_mkv.exists():
        try:
            change_container(src_path, out_mkv)
        except Exception as exc:
            logger.warning("Failed to create %s: %s", out_mkv, exc)
    # 5. Renamed copy (file name only)
    # Simply copy the original file to a new name to test filename independence.
    out_renamed = dest_dir / f"{base_name}_renamed.mp4"
    if not out_renamed.exists():
        try:
            shutil.copy2(src_path, out_renamed)
            logger.info("Created renamed copy: %s", out_renamed)
        except Exception as exc:
            logger.warning("Failed to copy %s to %s: %s", src_path, out_renamed, exc)


def load_keys(mapping_file: Path) -> list[str]:
    """Read the random mapping file and return a list of keys (one per line)."""
    with mapping_file.open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_id_map(id_map_file: Path) -> dict[str, str]:
    """Load the JSON mapping of keys to YouTube IDs."""
    with id_map_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {str(k): str(v) for k, v in data.items()}


def generate_dataset(
    keys: Iterable[str],
    id_map: dict[str, str],
    output_dir: Path,
    *,
    skip_download: bool = False,
) -> None:
    """
    Download videos for the given keys and create variants.  If
    `skip_download` is True, assumes that original videos already exist in
    `output_dir/original/` and skips downloading.
    """
    originals_dir = output_dir / "original"
    variants_dir = output_dir / "variants"
    originals_dir.mkdir(parents=True, exist_ok=True)
    variants_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        youtube_id = id_map.get(key)
        if youtube_id is None:
            logger.warning("No YouTube ID found for key %s; skipping.", key)
            continue
        try:
            if skip_download:
                # Expect file to already exist
                existing = list(originals_dir.glob(f"{key}.*"))
                if not existing:
                    logger.error(
                        "skip_download specified but original file for key %s is missing", key
                    )
                    continue
                src_path = existing[0]
            else:
                src_path = download_video(youtube_id, originals_dir, key)
        except Exception as exc:
            logger.error("Failed to download video for key %s: %s", key, exc)
            continue
        # Create variants
        dest = variants_dir / key
        try:
            create_variants(key, src_path, dest)
        except Exception as exc:
            logger.error("Failed to create variants for key %s: %s", key, exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate test dataset for vdedup")
    parser.add_argument(
        "--mapping-file",
        type=Path,
        default=Path("random_mapping.txt"),
        help="Path to the text file containing random keys (one per line)",
    )
    parser.add_argument(
        "--id-map",
        type=Path,
        default=Path("yt_ids.json"),
        help="Path to the JSON file mapping keys to YouTube IDs",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Directory where original and variant videos will be stored",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading videos and assume originals already exist",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set the logging level",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level))
    try:
        _ensure_yt_dlp()
    except RuntimeError as exc:
        logger.error(str(exc))
        return
    try:
        keys = load_keys(args.mapping_file)
    except Exception as exc:
        logger.error("Failed to read mapping file %s: %s", args.mapping_file, exc)
        return
    try:
        id_map = load_id_map(args.id_map)
    except Exception as exc:
        logger.error("Failed to read ID map %s: %s", args.id_map, exc)
        return
    generate_dataset(keys, id_map, args.output_dir, skip_download=args.skip_download)


if __name__ == "__main__":
    main()