#!/usr/bin/env python3
from PIL import Image, ImageFilter
from imgshrink.perceptual import ssim, binary_search_quality, PerceptualThresholds

def test_ssim_id_and_blur():
    im = Image.new('RGB', (96, 96), (140, 140, 140))
    assert abs(ssim(im, im) - 1.0) < 1e-6
    im_blur = im.filter(ImageFilter.GaussianBlur(2.0))
    assert ssim(im, im_blur) < 1.0

def test_binary_search_quality_smoke():
    im = Image.new('RGB', (96, 96), (200, 120, 80))
    dec, nbytes, q, s = binary_search_quality(im, fmt='WEBP', q_lo=30, q_hi=60, thresholds=PerceptualThresholds(ssim_min=0.95))
    assert 30 <= q <= 60
    assert 0.0 <= s <= 1.0
    assert nbytes > 0
