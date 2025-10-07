#!/usr/bin/env python3
"""
Tests for quality preset functionality.
"""

import argparse
from pathlib import Path
import pytest

from imgshrink.cli import get_quality_preset, _apply_quality_preset


def test_quality_preset_range():
    """Test that all preset levels 0-9 are valid and return expected values."""
    for level in range(10):
        preset = get_quality_preset(level)
        assert preset.level == level
        assert 0.0 < preset.ssim_min <= 1.0
        assert preset.ppd_photo > 0
        assert preset.ppd_line > 0
        assert 1 <= preset.jpeg_quality <= 100
        assert 1 <= preset.webp_quality <= 100
        assert 0.0 < preset.downsample_factor <= 1.0
        assert len(preset.description) > 0


def test_quality_preset_invalid_level():
    """Test that invalid preset levels raise ValueError."""
    with pytest.raises(ValueError, match="Quality preset level must be 0-9"):
        get_quality_preset(-1)

    with pytest.raises(ValueError, match="Quality preset level must be 0-9"):
        get_quality_preset(10)


def test_quality_preset_ordering():
    """Test that presets follow expected ordering (higher level = more compression)."""
    presets = [get_quality_preset(i) for i in range(10)]

    # SSIM should decrease with level (more compression = lower quality threshold)
    for i in range(len(presets) - 1):
        assert presets[i].ssim_min >= presets[i + 1].ssim_min

    # PPD should decrease with level (more compression = less detail preserved)
    for i in range(len(presets) - 1):
        assert presets[i].ppd_photo >= presets[i + 1].ppd_photo
        assert presets[i].ppd_line >= presets[i + 1].ppd_line

    # JPEG quality should decrease with level
    for i in range(len(presets) - 1):
        assert presets[i].jpeg_quality >= presets[i + 1].jpeg_quality


def test_apply_quality_preset():
    """Test that _apply_quality_preset correctly modifies args."""
    args = argparse.Namespace(
        quality_preset=3,
        guard_ssim=None,
        ppd_photo=60.0,
        ppd_line=75.0
    )

    _apply_quality_preset(args)

    preset = get_quality_preset(3)
    assert args.guard_ssim == preset.ssim_min
    assert args.ppd_photo == preset.ppd_photo
    assert args.ppd_line == preset.ppd_line
    assert hasattr(args, '_preset')
    assert args._preset == preset


def test_apply_quality_preset_none():
    """Test that _apply_quality_preset does nothing when quality_preset is None."""
    args = argparse.Namespace(
        quality_preset=None,
        guard_ssim=0.9,
        ppd_photo=60.0,
        ppd_line=75.0
    )

    original_ssim = args.guard_ssim
    original_ppd_photo = args.ppd_photo
    original_ppd_line = args.ppd_line

    _apply_quality_preset(args)

    # Values should remain unchanged
    assert args.guard_ssim == original_ssim
    assert args.ppd_photo == original_ppd_photo
    assert args.ppd_line == original_ppd_line
    assert not hasattr(args, '_preset')


def test_quality_preset_specific_values():
    """Test specific values for key presets."""
    # Preset 0: Maximum quality
    p0 = get_quality_preset(0)
    assert p0.ssim_min == 0.98
    assert p0.jpeg_quality == 95
    assert p0.downsample_factor == 1.0

    # Preset 3: High quality (recommended default)
    p3 = get_quality_preset(3)
    assert p3.ssim_min == 0.95
    assert p3.ppd_photo == 60.0
    assert p3.ppd_line == 75.0

    # Preset 5: Balanced
    p5 = get_quality_preset(5)
    assert p5.ssim_min == 0.91
    assert p5.jpeg_quality == 78

    # Preset 9: Aggressive compression
    p9 = get_quality_preset(9)
    assert p9.ssim_min == 0.82
    assert p9.jpeg_quality == 60
    assert p9.downsample_factor == 0.75


def test_quality_preset_descriptions():
    """Test that all presets have meaningful descriptions."""
    keywords = {
        0: ["maximum", "quality"],
        3: ["high", "quality"],
        5: ["balanced"],
        9: ["aggressive", "compression"]
    }

    for level, expected_words in keywords.items():
        preset = get_quality_preset(level)
        desc_lower = preset.description.lower()
        for word in expected_words:
            assert word in desc_lower, f"Expected '{word}' in preset {level} description"
