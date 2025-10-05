#!/usr/bin/env python3
import numpy as np
from PIL import Image, ImageFilter
from imgshrink.perceptual import ssim, binary_search_quality, PerceptualThresholds

def test_ssim_id_and_blur():
    # Create an image with some structure (a checkerboard)
    arr = np.zeros((96, 96), dtype=np.uint8)
    arr[0:48, 0:48] = 255
    arr[48:96, 48:96] = 255
    im = Image.fromarray(arr, mode='L').convert('RGB')

    assert abs(ssim(im, im) - 1.0) < 1e-6
    im_blur = im.filter(ImageFilter.GaussianBlur(5.0))
    assert ssim(im, im_blur) < 0.999

def test_binary_search_quality_smoke():
    im = Image.new('RGB', (96, 96), (200, 120, 80))
    dec, nbytes, q, s = binary_search_quality(im, fmt='WEBP', q_lo=30, q_hi=60, thresholds=PerceptualThresholds(ssim_min=0.95))
    assert 30 <= q <= 60
    assert 0.0 <= s <= 1.0
    assert nbytes > 0