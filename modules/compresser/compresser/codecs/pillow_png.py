"""Lossless PNG recompression with supported metadata preservation."""

from __future__ import annotations

import io

from PIL import Image, PngImagePlugin

from .base import BaseCodec
from ..models import CompressionStrategy
from ..trial_budget import trial_entry


class PillowPngCodec(BaseCodec):
    @property
    def name(self) -> str:
        return "pillow-png"

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return ("PNG",)

    def is_available(self) -> bool:
        return True

    def encode(self, im: Image.Image, target_format: str, strategy: CompressionStrategy) -> tuple[bytes, float]:
        metadata = PngImagePlugin.PngInfo()
        for key, value in im.info.items():
            if isinstance(value, str):
                metadata.add_itxt(key, value)
        if im.info.get("xmp"):
            value = im.info["xmp"]
            metadata.add_itxt("XML:com.adobe.xmp", value.decode("utf-8") if isinstance(value, bytes) else value)
        options = {key: im.info[key] for key in ("icc_profile", "exif", "transparency", "dpi") if key in im.info}
        buffer = io.BytesIO()
        with trial_entry(strategy.name or "png"):
            im.save(buffer, format="PNG", pnginfo=metadata, compress_level=round(strategy.method * 9 / 6), **options)
        return buffer.getvalue(), 1.0
