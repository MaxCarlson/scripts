from __future__ import annotations

import io
from PIL import Image
from compresser.perceptual import calculate_ssim, is_grayscale_image, binary_search_quality


def test_ssim_identical_images():
    im = Image.new("RGB", (100, 100), color=(120, 140, 160))
    ssim = calculate_ssim(im, im)
    assert abs(ssim - 1.0) < 1e-4


def test_ssim_different_images():
    im1 = Image.new("RGB", (100, 100), color=(0, 0, 0))
    im2 = Image.new("RGB", (100, 100), color=(255, 255, 255))
    ssim = calculate_ssim(im1, im2)
    assert ssim < 0.1


def test_ssim_rejects_equal_luminance_color_shift():
    first = Image.new("RGB", (40, 40), (255, 0, 0))
    second = Image.new("RGB", (40, 40), (0, 130, 0))
    assert abs(first.convert("L").getpixel((0, 0)) - second.convert("L").getpixel((0, 0))) <= 1
    assert calculate_ssim(first, second) < 0.1


def test_ssim_dimensions_not_silently_resized():
    import pytest

    with pytest.raises(ValueError, match="identical dimensions"):
        calculate_ssim(Image.new("RGB", (40, 40)), Image.new("RGB", (50, 50)))


def test_is_grayscale():
    im_gray = Image.new("RGB", (64, 64), color=(100, 100, 100))
    assert is_grayscale_image(im_gray) is True

    im_color = Image.new("RGB", (64, 64), color=(255, 0, 0))
    assert is_grayscale_image(im_color) is False


def test_binary_search_quality():
    im = Image.new("RGB", (120, 120), color=(150, 180, 210))

    def encode_fn(img: Image.Image, q: int) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=q)
        return buf.getvalue()

    def decode_fn(data: bytes) -> Image.Image:
        return Image.open(io.BytesIO(data))

    chosen_q, encoded, achieved_ssim = binary_search_quality(
        im, encode_fn, decode_fn, target_ssim=0.980, q_min=50, q_max=95
    )
    assert 50 <= chosen_q <= 95
    assert len(encoded) > 0
    assert achieved_ssim >= 0.970
