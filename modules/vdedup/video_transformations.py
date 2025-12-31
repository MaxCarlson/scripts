#!/usr/bin/env python3
"""
Compat shim: vdedup now uses the shared transformations from
`modules.video_dataset_tools.transformations`. The functions are re-exported
to preserve existing import paths.
"""

from modules.video_dataset_tools.transformations import (
    change_audio_bitrate,
    change_container,
    change_video_bitrate,
    remove_audio,
    scale_video,
    trim_video,
)

__all__ = [
    "trim_video",
    "scale_video",
    "change_audio_bitrate",
    "remove_audio",
    "change_video_bitrate",
    "change_container",
]