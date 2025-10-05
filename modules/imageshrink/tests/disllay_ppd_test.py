#!/usr/bin/env python3
import math
from imgshrink.display import DeviceProfile, parse_resolution, device_ppd, target_source_size_from_ppd

def test_ppi_and_ppd_basic():
    prof = DeviceProfile(diagonal_in=6.7, width_px=2400, height_px=1080, viewing_distance_cm=35)
    ppi = prof.ppi
    assert 300 <= ppi <= 500  # typical phone
    ppd_w, ppd_h = device_ppd(prof)
    # Hand-wavy sanity: closer distance -> larger angle -> lower PPD
    prof2 = DeviceProfile(diagonal_in=6.7, width_px=2400, height_px=1080, viewing_distance_cm=20)
    ppd_w2, _ = device_ppd(prof2)
    assert ppd_w2 < ppd_w

def test_target_size_ratio():
    prof = DeviceProfile(diagonal_in=6.7, width_px=2400, height_px=1080, viewing_distance_cm=35)
    src_wh = (4000, 3000)
    tw, th, r = target_source_size_from_ppd(src_wh, prof, ppd_target=60.0)
    assert 1 <= tw <= 4000
    assert 1 <= th <= 3000
    assert 0.0 < r <= 1.0
