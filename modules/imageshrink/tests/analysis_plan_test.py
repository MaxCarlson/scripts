#!/usr/bin/env python3
from pathlib import Path

from PIL import Image

from imgshrink.analysis import analyze_images, decide_plan, predict_after_bytes, bytes_human


def _mk(tmp: Path, name: str, size=(2400, 3600), q=92) -> Path:
    p = tmp / name
    Image.new("RGB", size, (128, 128, 128)).save(p, "JPEG", quality=q)
    return p


def test_analyze_and_decide(tmp_path: Path):
    a = _mk(tmp_path, "a.jpg", (3600, 2400))
    b = _mk(tmp_path, "b.jpg", (4200, 2800))
    c = _mk(tmp_path, "c.jpg", (1200, 1800))

    infos, stats = analyze_images([a, b, c])
    assert stats is not None
    assert stats.count == 3
    assert stats.width_max >= 4200
    assert stats.height_max >= 2800

    plan = decide_plan(stats, phone_max_dim=3200)
    assert 0.1 <= plan.downsample_ratio <= 1.0
    assert 50 <= plan.jpeg_quality <= 95

    est = predict_after_bytes(infos, plan)
    assert est > 0

    # sanity: human bytes function returns a string with unit
    assert any(unit in bytes_human(1234567) for unit in ("KiB", "MiB", "GiB"))