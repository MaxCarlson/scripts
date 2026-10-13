#!/usr/bin/env python3
"""
Pluggable discovery and invocation for external CLI compression binaries.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .base import BaseCodec
from ..models import CompressionStrategy
from ..perceptual import calculate_ssim


class ExternalCliCodec(BaseCodec):
    """Encodes images via external command-line utilities if installed."""

    def __init__(self, binary_name: str, target_format: str) -> None:
        self._binary_name = binary_name
        self._format = target_format.upper()
        self._path = shutil.which(binary_name)

    @property
    def name(self) -> str:
        return f"cli-{self._binary_name}"

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return (self._format,)

    def is_available(self) -> bool:
        return self._path is not None

    def encode(
        self,
        im: Image.Image,
        target_format: str,
        strategy: CompressionStrategy,
    ) -> tuple[bytes, float | None]:
        if not self.is_available() or not self._path:
            raise RuntimeError(f"CLI binary '{self._binary_name}' is not found on PATH")

        with tempfile.TemporaryDirectory(prefix="compresser-cli-") as temp_dir:
            temp_path = Path(temp_dir)
            out_file = temp_path / f"output.{self._format.lower()}"
            cmd = [self._path]
            if self._binary_name == "cwebp":
                in_file = temp_path / "input.png"
                im.save(in_file, format="PNG")
                if strategy.mode == "lossless":
                    cmd.extend(["-lossless", "-z", "9", "-m", "6"])
                else:
                    cmd.extend(["-q", str(strategy.quality), "-m", "6"])
                cmd.extend([str(in_file), "-o", str(out_file)])
            elif self._binary_name == "jpegtran":
                if strategy.mode != "lossless" or im.format != "JPEG" or not im.filename:
                    raise ValueError("jpegtran requires an original JPEG file and lossless mode")
                in_file = Path(im.filename)
                cmd.extend(["-optimize", "-progressive", "-copy", "all"])
                cmd.extend(["-outfile", str(out_file), str(in_file)])
            else:
                in_file = temp_path / "input.png"
                im.save(in_file, format="PNG")
                cmd.extend([str(in_file), str(out_file)])

            res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
            if res.returncode != 0 or not out_file.exists():
                raise RuntimeError(f"{self._binary_name} execution failed (code {res.returncode}): {res.stderr}")

            encoded = out_file.read_bytes()
            decoded = self.decode_bytes(encoded)
            ssim = calculate_ssim(im, decoded)
            return encoded, ssim


def discover_available_codecs() -> dict[str, BaseCodec]:
    """Discover all active codecs in the current environment."""
    from .pillow_jpeg import PillowJpegCodec
    from .pillow_webp import PillowWebpCodec
    from .pillow_avif import PillowAvifCodec
    from .pillow_png import PillowPngCodec

    codecs: dict[str, BaseCodec] = {
        "pillow-jpeg": PillowJpegCodec(),
        "pillow-webp": PillowWebpCodec(),
        "pillow-png": PillowPngCodec(),
    }

    avif = PillowAvifCodec()
    if avif.is_available():
        codecs["pillow-avif"] = avif

    # Only advertise the adapter whose invocation and fidelity are verified.
    # Installing an unrelated external binary must not change encoding policy.
    for binary, fmt in [("jpegtran", "JPEG")]:
        cli_codec = ExternalCliCodec(binary, fmt)
        if cli_codec.is_available():
            codecs[cli_codec.name] = cli_codec

    return codecs
