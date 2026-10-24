"""Tests for deterministic temporal sample window generation."""

import pytest
from videocompress.sampling import SampleWindow, generate_sample_windows


def test_generate_sample_windows_s3_standard():
    """Verify standard S3 schedule on 100s video with 10s windows."""
    windows = generate_sample_windows(duration_seconds=100.0, schedule="s3", window_duration_seconds=10.0)
    assert len(windows) == 3
    assert [w.window_index for w in windows] == [0, 1, 2]
    # Check that windows fit within total duration
    for w in windows:
        assert w.start_seconds >= 0.0
        assert w.duration_seconds == 10.0
        assert w.start_seconds + w.duration_seconds <= 100.0

    # Ensure windows are spaced monotonically without overlapping
    assert windows[0].start_seconds < windows[1].start_seconds < windows[2].start_seconds
    assert windows[0].start_seconds + windows[0].duration_seconds <= windows[1].start_seconds
    assert windows[1].start_seconds + windows[1].duration_seconds <= windows[2].start_seconds


def test_generate_sample_windows_s5_and_s8():
    """Verify S5 and S8 schedule window counts and spread."""
    w5 = generate_sample_windows(duration_seconds=1000.0, schedule="s5", window_duration_seconds=15.0)
    assert len(w5) == 5
    for w in w5:
        assert w.duration_seconds == 15.0
        assert w.start_seconds + w.duration_seconds <= 1000.0

    w8 = generate_sample_windows(duration_seconds=1000.0, schedule="s8", window_duration_seconds=10.0)
    assert len(w8) == 8
    for i in range(len(w8) - 1):
        assert w8[i].start_seconds + w8[i].duration_seconds <= w8[i + 1].start_seconds


def test_generate_sample_windows_short_duration():
    """Video shorter than window duration should produce a single window spanning full duration."""
    windows = generate_sample_windows(duration_seconds=6.5, schedule="s3", window_duration_seconds=10.0)
    assert len(windows) == 1
    assert windows[0].window_index == 0
    assert windows[0].start_seconds == 0.0
    assert windows[0].duration_seconds == 6.5


def test_generate_sample_windows_zero_or_negative():
    """Zero or negative duration should return empty list."""
    assert generate_sample_windows(duration_seconds=0.0) == []
    assert generate_sample_windows(duration_seconds=-10.0) == []


def test_generate_sample_windows_invalid_schedule():
    """Unknown schedule name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown sampling schedule"):
        generate_sample_windows(duration_seconds=100.0, schedule="invalid_s99")
