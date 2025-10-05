#!/usr/bin/env python3
"""
Display & viewing-geometry helpers for content-aware downsampling.

This module is **additive**: it does not alter existing public interfaces.
It can be imported from imgshrink.analysis/cli to enable device-aware planning.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Tuple, Literal


FitMode = Literal["fit-longer", "fit-shorter", "fit-width", "fit-height"]


@dataclass(frozen=True)
class DeviceProfile:
    """A physical display and viewing context.
    
    Attributes:
        diagonal_in: Screen diagonal in inches (e.g., 6.7 for a phone).
        width_px:    Physical screen width in pixels (native resolution in current orientation).
        height_px:   Physical screen height in pixels.
        viewing_distance_cm: Average distance from eyes to screen in centimeters.
    """
    diagonal_in: float
    width_px: int
    height_px: int
    viewing_distance_cm: float

    @property
    def ppi(self) -> float:
        """Pixels-per-inch computed from native resolution and diagonal size."""
        # Guard against division-by-zero
        diag_px = math.hypot(self.width_px, self.height_px)
        return diag_px / max(self.diagonal_in, 1e-6)

    @property
    def width_in(self) -> float:
        return self.width_px / self.ppi

    @property
    def height_in(self) -> float:
        return self.height_px / self.ppi

    def aspect(self) -> float:
        return self.width_px / self.height_px


def parse_resolution(res: str) -> Tuple[int, int]:
    """Parse strings like '2560x1440' -> (2560, 1440)."""
    s = res.lower().replace(" ", "").replace("×", "x")
    w, h = s.split("x", 1)
    return int(w), int(h)


def visual_angle_deg(length_in: float, viewing_distance_cm: float) -> float:
    """Return the visual angle in degrees for a physical length in inches.
    
    angle = 2 * atan( L / (2 * D) ), where D is viewing distance (same units as L).
    """
    # Convert distance to inches to match length_in
    distance_in = viewing_distance_cm / 2.54
    return math.degrees(2.0 * math.atan2(length_in, 2.0 * max(distance_in, 1e-6)))


def pixels_per_degree(pixels: int, length_in: float, viewing_distance_cm: float) -> float:
    """Pixels-per-degree for a given pixel extent displayed over a physical span."""
    ang = visual_angle_deg(length_in, viewing_distance_cm)
    return pixels / max(ang, 1e-9)


def displayed_size_px(
    src_wh: Tuple[int, int],
    device: DeviceProfile,
    fit_mode: FitMode = "fit-longer",
) -> Tuple[int, int]:
    """Given source (w,h), compute on-screen pixel size after fitting to device.
    
    This assumes "no zoom": image is scaled to either fit the longer side, shorter side,
    width, or height of the device while preserving aspect ratio.
    """
    sw, sh = src_wh
    dw, dh = device.width_px, device.height_px
    if sw <= 0 or sh <= 0:
        return (0, 0)

    src_aspect = sw / sh
    dev_aspect = dw / dh

    if fit_mode == "fit-width":
        w = dw
        h = int(round(w / src_aspect))
    elif fit_mode == "fit-height":
        h = dh
        w = int(round(h * src_aspect))
    else:
        # Compare longer sides or shorter sides depending on mode
        if fit_mode == "fit-longer":
            # Fit to the limiting dimension (max side)
            if src_aspect >= 1:  # source wider than tall
                w = dw
                h = int(round(w / src_aspect))
                if h > dh:
                    h = dh
                    w = int(round(h * src_aspect))
            else:
                h = dh
                w = int(round(h * src_aspect))
                if w > dw:
                    w = dw
                    h = int(round(w / src_aspect))
        elif fit_mode == "fit-shorter":
            # Ensure both dimensions fit, but leave margin
            if src_aspect >= 1:  # wide
                h = dh
                w = int(round(h * src_aspect))
                if w > dw:  # should not happen for "fit-shorter", but guard
                    w = dw
                    h = int(round(w / src_aspect))
            else:  # tall
                w = dw
                h = int(round(w * src_aspect))
                if h > dh:
                    h = dh
                    w = int(round(h * src_aspect))
        else:
            raise ValueError(f"Unknown fit_mode: {fit_mode}")
    return max(1, w), max(1, h)


def device_ppd(device: DeviceProfile) -> Tuple[float, float]:
    """Return (PPD_width, PPD_height) for full-screen usage."""
    ppd_w = pixels_per_degree(device.width_px, device.width_in, device.viewing_distance_cm)
    ppd_h = pixels_per_degree(device.height_px, device.height_in, device.viewing_distance_cm)
    return ppd_w, ppd_h


def target_source_size_from_ppd(
    src_wh: Tuple[int, int],
    device: DeviceProfile,
    fit_mode: FitMode = "fit-longer",
    ppd_target: float = 60.0,
    safety_scale: float = 1.0,
) -> Tuple[int, int, float]:
    """Compute a **target source size** that is sufficient for a PPD target on this device.
    
    Returns (target_w, target_h, downsample_ratio) where downsample_ratio = min(1, target_w/src_w, target_h/src_h)
    
    Logic:
      1) Compute on-screen size in pixels for the source under the fit policy.
      2) Compute device PPD along width/height for **full screen**.
      3) If device PPD >= target, we don't need more source pixels than the on-screen size.
         -> Target = on-screen pixels * safety_scale (to allow minor zoom/cropping).
      4) Else, device is limiting: return min(src, on-screen).
    """
    sw, sh = src_wh
    if sw <= 0 or sh <= 0:
        return 0, 0, 0.0

    disp_w, disp_h = displayed_size_px(src_wh, device, fit_mode=fit_mode)
    ppd_w, ppd_h = device_ppd(device)
    ppd_min = min(ppd_w, ppd_h)

    if ppd_min >= ppd_target:
        tw = int(round(disp_w * safety_scale))
        th = int(round(disp_h * safety_scale))
    else:
        # Device cannot achieve the desired PPD anyway; cap at display size
        tw, th = disp_w, disp_h

    # Do not ask for more than the original
    tw = min(tw, sw)
    th = min(th, sh)
    ratio = min(1.0, tw / sw, th / sh)
    return max(1, tw), max(1, th), float(ratio)
