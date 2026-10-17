#!/usr/bin/env python3
"""
Codec registry and exports.
"""

from .base import BaseCodec
from .pillow_jpeg import PillowJpegCodec
from .pillow_webp import PillowWebpCodec
from .pillow_avif import PillowAvifCodec
from .pillow_png import PillowPngCodec
from .external_cli import ExternalCliCodec, discover_available_codecs

__all__ = [
    "BaseCodec",
    "PillowJpegCodec",
    "PillowWebpCodec",
    "PillowAvifCodec",
    "PillowPngCodec",
    "ExternalCliCodec",
    "discover_available_codecs",
]
