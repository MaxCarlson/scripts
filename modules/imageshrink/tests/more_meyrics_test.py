#!/usr/bin/env python3
from PIL import Image
import numpy as np

from imgshrink.more_metrics import (
    BasicDims, colorfulness_hasler_susstrunk, is_effectively_grayscale,
    sobel_edge_density, otsu_separability, noise_proxy_highpass, quick_content_metrics
)

def test_colorfulness_and_gray():
    im_gray = Image.fromarray((np.ones((64,64), dtype=np.uint8)*128), mode='L').convert('RGB')
    im_color = Image.fromarray(np.dstack([
        np.tile(np.linspace(0,255,64, dtype=np.uint8), (64,1)),
        np.tile(np.linspace(255,0,64, dtype=np.uint8), (64,1)),
        np.full((64,64), 128, dtype=np.uint8)
    ]), mode='RGB')
    cf_gray = colorfulness_hasler_susstrunk(im_gray)
    cf_color = colorfulness_hasler_susstrunk(im_color)
    assert cf_color > cf_gray
    assert is_effectively_grayscale(im_gray)

def test_edge_and_otsu_and_noise():
    # Vertical stripes -> many edges
    arr = np.zeros((64,64), dtype=np.uint8)
    arr[:, ::2] = 255
    im = Image.fromarray(arr, mode='L').convert('RGB')
    edge = sobel_edge_density(im)
    assert edge > 0.1

    otsu = otsu_separability(im.convert('L'))
    assert 0.0 <= otsu <= 1.0

    n = noise_proxy_highpass(im)
    assert n >= 0.0

def test_quick_content_metrics_smoke():
    im = Image.new('RGB', (100, 50), (128,128,128))
    d = quick_content_metrics(im, file_bytes=5000)
    assert 'megapixels' in d and 'colorfulness' in d and 'edge_density' in d
