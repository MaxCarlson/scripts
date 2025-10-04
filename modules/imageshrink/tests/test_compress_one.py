#!/usr/bin/env python3
from pathlib import Path

from PIL import Image

from imgshrink.analysis import decide_plan, analyze_images
from imgshrink.compress import compress_one


def test_compress_to_subdir(tmp_path: Path):
    # build an image
    p = tmp_path / "orig.png"
    Image.new("RGB", (3000, 2000), (150, 150, 150)).save(p, "PNG")

    infos, stats = analyze_images([p])
    assert stats is not None
    plan = decide_plan(stats, phone_max_dim=1600, prefer_format="jpeg")

    # write to _compressed
    out_dir = tmp_path / "_compressed"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = compress_one(p, out_dir=out_dir, plan=plan, overwrite=False, backup=False)

    assert res.output_path.exists()
    assert res.after_bytes < res.before_bytes
    assert res.width_after <= res.width_before