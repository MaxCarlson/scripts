#!/usr/bin/env python3
"""
Compat shim: vdedup now delegates dataset generation to
`modules.video_dataset_tools`. This module re-exports the public API so
existing imports keep working while the functionality lives in the shared
toolkit package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

from modules.video_dataset_tools import dataset as _ds

ensure_yt_dlp = _ds.ensure_yt_dlp
ensure_ffmpeg = _ds.ensure_ffmpeg
load_keys = _ds.load_keys
load_id_map = _ds.load_id_map
download_video = _ds.download_video
create_variants = _ds.create_variants
generate_dataset = _ds.generate_dataset
build_truth_manifest = _ds.build_truth_manifest
write_truth_manifest = _ds.write_truth_manifest
parse_args = _ds.parse_args


def main(argv: Optional[List[str]] = None) -> None:
    _ds.main(argv)


__all__ = [
    "ensure_yt_dlp",
    "ensure_ffmpeg",
    "load_keys",
    "load_id_map",
    "download_video",
    "create_variants",
    "generate_dataset",
    "build_truth_manifest",
    "write_truth_manifest",
    "parse_args",
    "main",
]
