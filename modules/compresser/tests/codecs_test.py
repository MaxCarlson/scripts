from __future__ import annotations

from PIL import Image
from compresser.codecs import PillowJpegCodec, PillowWebpCodec
from compresser.models import CompressionStrategy


def test_pillow_jpeg_refuses_lossless():
    codec = PillowJpegCodec()
    assert codec.is_available()
    im = Image.new("RGB", (100, 100), color=(150, 160, 170))
    strat = CompressionStrategy(name="jpeg-lossless", format="jpeg", mode="lossless")
    import pytest

    with pytest.raises(RuntimeError, match="Lossless JPEG optimization is not supported by Pillow"):
        codec.encode(im, "JPEG", strat)


def test_pillow_webp_perceptual():
    codec = PillowWebpCodec()
    assert codec.is_available()
    im = Image.new("RGB", (100, 100), color=(150, 160, 170))
    strat = CompressionStrategy(name="webp-perceptual", format="webp", mode="perceptual", perceptual_target=0.985)
    encoded, ssim = codec.encode(im, "WEBP", strat)
    assert len(encoded) > 0
    assert ssim is not None
    assert ssim >= 0.980


def test_pillow_webp_dimension_limit_error():
    codec = PillowWebpCodec()
    im_tall = Image.new("RGB", (100, 16385), color=(100, 100, 100))
    strat = CompressionStrategy(name="webp-lossy", format="webp", mode="lossy", quality=80)
    import pytest

    with pytest.raises(ValueError, match="exceeds WebP maximum limit"):
        codec.encode(im_tall, "WEBP", strat)
