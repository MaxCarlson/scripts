#!/usr/bin/env python3
"""
Tests for enhanced subset detection algorithm with cross-resolution support.
"""
from vdedup.pipeline import _alignable_distance
from vdedup.grouping import alignable_avg_distance


def test_alignable_distance_basic():
    """Test basic subset detection functionality."""
    # Create test signatures - B is a subset of A
    sig_short = [0x1234567890ABCDEF, 0x2345678901BCDEF0, 0x3456789012CDEF01]
    sig_long = [0x0000000000000000, 0x1234567890ABCDEF, 0x2345678901BCDEF0,
                0x3456789012CDEF01, 0x4567890123DEF012]

    # Should find alignment with short sig embedded in long sig
    result = _alignable_distance(sig_short, sig_long, 10)
    assert result is not None
    assert result.distance < 5  # Should be very low distance for identical frames


def test_alignable_distance_frame_rate_handling():
    """Test handling of different frame rates (skip every other frame)."""
    # Create signatures where every other frame matches
    sig_short = [0x1111111111111111, 0x3333333333333333, 0x5555555555555555]
    sig_long = [0x1111111111111111, 0x2222222222222222, 0x3333333333333333,
                0x4444444444444444, 0x5555555555555555, 0x6666666666666666]

    # Should find alignment using step=2 strategy
    result = _alignable_distance(sig_short, sig_long, 10)
    assert result is not None
    assert result.distance < 5  # Should be very low distance for matching frames


def test_alignable_distance_intro_outro():
    """Test handling of intro/outro differences."""
    # Create signatures where short version has intro/outro cut
    sig_short = [0x2222222222222222, 0x3333333333333333, 0x4444444444444444]
    sig_long = [0x1111111111111111, 0x2222222222222222, 0x3333333333333333,
                0x4444444444444444, 0x5555555555555555]

    # Should find alignment with offset
    result = _alignable_distance(sig_short, sig_long, 10)
    assert result is not None
    assert result.distance < 5  # Should be very low distance for matching frames


def test_alignable_distance_complexity_adaptation():
    """Test adaptive thresholding based on content complexity."""
    # Create high-complexity content (lots of variation between frames)
    sig_short = [0x1111111111111111, 0xAAAAAAAAAAAAAAAA, 0x5555555555555555]
    sig_long = [0x1111111111111111, 0xAAAAAAAAAAAAAAAA, 0x5555555555555555,
                0xCCCCCCCCCCCCCCCC]

    # Should allow higher threshold for complex content
    result = _alignable_distance(sig_short, sig_long, 8)
    assert result is not None

    # Create low-complexity content (similar frames)
    sig_short_simple = [0x1111111111111111, 0x1111111111111112, 0x1111111111111113]
    sig_long_simple = [0x1111111111111111, 0x1111111111111112, 0x1111111111111113,
                       0x1111111111111114]

    # Should use stricter threshold for simple content
    result_simple = _alignable_distance(sig_short_simple, sig_long_simple, 8)
    assert result_simple is not None


def test_alignable_distance_minimum_frames():
    """Test minimum frame requirements."""
    # Test with too few frames
    sig_too_short = [0x1111111111111111]
    sig_normal = [0x1111111111111111, 0x2222222222222222, 0x3333333333333333]

    result = _alignable_distance(sig_too_short, sig_normal, 10)
    assert result is None  # Should reject due to insufficient frames


def test_alignable_distance_no_match():
    """Test that non-matching signatures return None."""
    # Create completely different signatures
    sig_a = [0x1111111111111111, 0x2222222222222222, 0x3333333333333333]
    sig_b = [0xAAAAAAAAAAAAAAAA, 0xBBBBBBBBBBBBBBBB, 0xCCCCCCCCCCCCCCCC]

    result = _alignable_distance(sig_a, sig_b, 10)
    assert result is None  # Should not find alignment


def test_grouping_module_consistency():
    """Test that grouping module function works similarly."""
    sig_short = [0x1234567890ABCDEF, 0x2345678901BCDEF0, 0x3456789012CDEF01]
    sig_long = [0x0000000000000000, 0x1234567890ABCDEF, 0x2345678901BCDEF0,
                0x3456789012CDEF01, 0x4567890123DEF012]

    # Both functions should find similar results
    result_pipeline = _alignable_distance(sig_short, sig_long, 10)
    result_grouping = alignable_avg_distance(sig_short, sig_long, 10)

    assert result_pipeline is not None
    assert result_grouping is not None
    # Results should be similar (within reasonable tolerance)
    assert abs(result_pipeline.distance - result_grouping) < 2.0


def test_empty_signatures():
    """Test handling of empty or None signatures."""
    sig_normal = [0x1234567890ABCDEF, 0x2345678901BCDEF0]

    # Test empty signatures
    assert _alignable_distance([], sig_normal, 10) is None
    assert _alignable_distance(sig_normal, [], 10) is None
    assert _alignable_distance([], [], 10) is None

    # Test None signatures
    assert _alignable_distance(None, sig_normal, 10) is None
    assert _alignable_distance(sig_normal, None, 10) is None


if __name__ == "__main__":
    test_alignable_distance_basic()
    test_alignable_distance_frame_rate_handling()
    test_alignable_distance_intro_outro()
    test_alignable_distance_complexity_adaptation()
    test_alignable_distance_minimum_frames()
    test_alignable_distance_no_match()
    test_grouping_module_consistency()
    test_empty_signatures()
    print("All subset detection tests passed!")
