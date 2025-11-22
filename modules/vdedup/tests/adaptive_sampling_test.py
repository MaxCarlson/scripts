#!/usr/bin/env python3
"""
Tests for adaptive frame sampling strategy.

Tests cover:
- Sampling parameter calculation for different durations and modes
- Frame count limits (min/max enforcement)
- Mode-specific behavior (fast/balanced/thorough)
- Edge cases (zero duration, very short/long videos)
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from vdedup.phash import (
    adaptive_sampling_params,
    compute_phash_signature_adaptive,
    AdaptiveSamplingParams,
)


class TestAdaptiveSamplingParams:
    """Tests for adaptive_sampling_params function."""

    def test_short_video_balanced_mode(self):
        """Short video (3 min) in balanced mode should use 1s intervals."""
        params = adaptive_sampling_params(180, "balanced")  # 3 minutes

        assert params.sampling_interval == 1.0  # 1 frame per second
        assert params.min_frames == 30
        assert params.max_frames == 500

    def test_medium_video_balanced_mode(self):
        """Medium video (30 min) in balanced mode should use 2s intervals."""
        params = adaptive_sampling_params(1800, "balanced")  # 30 minutes

        assert params.sampling_interval == 2.0  # 1 frame per 2 seconds
        assert params.min_frames == 50
        assert params.max_frames == 1000

    def test_long_video_balanced_mode(self):
        """Long video (2 hours) in balanced mode should use 4s intervals."""
        params = adaptive_sampling_params(7200, "balanced")  # 2 hours

        assert params.sampling_interval == 4.0  # 1 frame per 4 seconds
        assert params.min_frames == 50
        assert params.max_frames == 1000

    def test_fast_mode_uses_sparse_sampling(self):
        """Fast mode should use sparser sampling than balanced."""
        params_fast = adaptive_sampling_params(1800, "fast")  # 30 min
        params_balanced = adaptive_sampling_params(1800, "balanced")

        assert params_fast.sampling_interval > params_balanced.sampling_interval
        assert params_fast.max_frames < params_balanced.max_frames

    def test_thorough_mode_uses_dense_sampling(self):
        """Thorough mode should use denser sampling than balanced."""
        params_thorough = adaptive_sampling_params(1800, "thorough")  # 30 min
        params_balanced = adaptive_sampling_params(1800, "balanced")

        assert params_thorough.sampling_interval < params_balanced.sampling_interval
        assert params_thorough.max_frames > params_balanced.max_frames

    def test_fast_mode_short_video(self):
        """Fast mode on short video (3 min)."""
        params = adaptive_sampling_params(180, "fast")

        assert params.sampling_interval == 10.0
        assert params.min_frames == 10
        assert params.max_frames == 100

    def test_fast_mode_long_video(self):
        """Fast mode on long video (2 hours)."""
        params = adaptive_sampling_params(7200, "fast")

        assert params.sampling_interval == 30.0
        assert params.min_frames == 30
        assert params.max_frames == 300

    def test_thorough_mode_short_video(self):
        """Thorough mode on short video (3 min)."""
        params = adaptive_sampling_params(180, "thorough")

        assert params.sampling_interval == 0.5  # 2 fps
        assert params.min_frames == 50
        assert params.max_frames == 1000

    def test_thorough_mode_long_video(self):
        """Thorough mode on long video (2 hours)."""
        params = adaptive_sampling_params(7200, "thorough")

        assert params.sampling_interval == 2.0  # 0.5 fps
        assert params.min_frames == 100
        assert params.max_frames == 3000

    def test_boundary_duration_5_min(self):
        """Test boundary condition at exactly 5 minutes."""
        params = adaptive_sampling_params(300, "balanced")  # Exactly 5 min

        # Should be in short video category (≤5 min)
        assert params.sampling_interval == 1.0

    def test_boundary_duration_60_min(self):
        """Test boundary condition at exactly 60 minutes."""
        params = adaptive_sampling_params(3600, "balanced")  # Exactly 1 hour

        # Should be in medium video category (≤1 hr)
        assert params.sampling_interval == 2.0

    def test_very_short_video_1_sec(self):
        """Very short video (1 second) should still get reasonable params."""
        params = adaptive_sampling_params(1, "balanced")

        # Should use short video settings
        assert params.sampling_interval == 1.0
        assert params.min_frames == 30

    def test_very_long_video_4_hours(self):
        """Very long video (4 hours) should use sparse sampling."""
        params = adaptive_sampling_params(14400, "balanced")  # 4 hours

        assert params.sampling_interval == 4.0
        assert params.max_frames == 1000  # Cap prevents explosion

    def test_zero_duration_returns_defaults(self):
        """Zero duration should return safe defaults."""
        params = adaptive_sampling_params(0, "balanced")

        assert params.sampling_interval == 1.0
        assert params.min_frames == 5
        assert params.max_frames == 100

    def test_negative_duration_returns_defaults(self):
        """Negative duration should return safe defaults."""
        params = adaptive_sampling_params(-10, "balanced")

        assert params.sampling_interval == 1.0
        assert params.min_frames == 5
        assert params.max_frames == 100

    def test_unknown_mode_defaults_to_balanced(self):
        """Unknown mode should fall back to balanced."""
        params = adaptive_sampling_params(1800, "unknown_mode")
        params_balanced = adaptive_sampling_params(1800, "balanced")

        assert params == params_balanced

    def test_params_named_tuple_structure(self):
        """AdaptiveSamplingParams should be a NamedTuple with correct fields."""
        params = adaptive_sampling_params(1800, "balanced")

        assert isinstance(params, AdaptiveSamplingParams)
        assert hasattr(params, 'sampling_interval')
        assert hasattr(params, 'min_frames')
        assert hasattr(params, 'max_frames')

        # Test named access
        assert params.sampling_interval == 2.0
        assert params.min_frames == 50
        assert params.max_frames == 1000


class TestComputePhashSignatureAdaptive:
    """Tests for compute_phash_signature_adaptive function."""

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_phash_from_timestamps')
    def test_short_video_samples_densely(self, mock_compute, mock_probe):
        """Short video should sample more densely (more frames)."""
        # Mock 3-minute video
        mock_probe.return_value = {"format": {"duration": "180"}}
        mock_compute.return_value = tuple(range(180))  # 180 frames

        result = compute_phash_signature_adaptive(Path("short.mp4"), "balanced")

        # Verify probe was called
        assert mock_probe.called

        # Verify frame extraction was called with appropriate timestamp count
        assert mock_compute.called
        timestamps = mock_compute.call_args[0][1]  # Second positional arg

        # 3 min = 180s, interval=1s, should get ~180 frames
        # With min=30, max=500, actual should be 180
        assert len(timestamps) == 180

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_phash_from_timestamps')
    def test_long_video_samples_sparsely(self, mock_compute, mock_probe):
        """Long video should sample more sparsely to avoid explosion."""
        # Mock 2-hour video
        mock_probe.return_value = {"format": {"duration": "7200"}}
        mock_compute.return_value = tuple(range(1000))

        result = compute_phash_signature_adaptive(Path("movie.mp4"), "balanced")

        timestamps = mock_compute.call_args[0][1]

        # 2 hours = 7200s, interval=4s → theoretical=1800 frames
        # But max=1000, so should cap at 1000
        assert len(timestamps) == 1000

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_phash_from_timestamps')
    def test_min_frames_enforced(self, mock_compute, mock_probe):
        """Minimum frame count should be enforced even for tiny videos."""
        # Mock 1-second video
        mock_probe.return_value = {"format": {"duration": "1"}}
        mock_compute.return_value = tuple(range(30))

        result = compute_phash_signature_adaptive(Path("tiny.mp4"), "balanced")

        timestamps = mock_compute.call_args[0][1]

        # 1s video, interval=1s → theoretical=1 frame
        # But min=30, so should enforce 30 frames
        assert len(timestamps) == 30

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_phash_from_timestamps')
    def test_fast_mode_samples_less_than_balanced(self, mock_compute, mock_probe):
        """Fast mode should sample fewer frames than balanced."""
        mock_probe.return_value = {"format": {"duration": "1800"}}  # 30 min
        mock_compute.return_value = tuple(range(100))

        result = compute_phash_signature_adaptive(Path("video.mp4"), "fast")

        timestamps = mock_compute.call_args[0][1]

        # 30 min = 1800s, fast mode interval=20s → 90 frames
        # min=20, max=200, actual=90
        assert len(timestamps) == 90

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_phash_from_timestamps')
    def test_thorough_mode_samples_more_than_balanced(self, mock_compute, mock_probe):
        """Thorough mode should sample more frames than balanced."""
        mock_probe.return_value = {"format": {"duration": "1800"}}  # 30 min
        mock_compute.return_value = tuple(range(1800))

        result = compute_phash_signature_adaptive(Path("video.mp4"), "thorough")

        timestamps = mock_compute.call_args[0][1]

        # 30 min = 1800s, thorough mode interval=1s → 1800 frames
        # min=100, max=2000, actual=1800
        assert len(timestamps) == 1800

    @patch('vdedup.probe.run_ffprobe_json')
    def test_probe_failure_returns_none(self, mock_probe):
        """Failed ffprobe should return None."""
        mock_probe.return_value = None

        result = compute_phash_signature_adaptive(Path("broken.mp4"), "balanced")

        assert result is None

    @patch('vdedup.probe.run_ffprobe_json')
    def test_zero_duration_returns_none(self, mock_probe):
        """Zero duration video should return None."""
        mock_probe.return_value = {"format": {"duration": "0"}}

        result = compute_phash_signature_adaptive(Path("empty.mp4"), "balanced")

        assert result is None

    @patch('vdedup.probe.run_ffprobe_json')
    def test_missing_duration_returns_none(self, mock_probe):
        """Missing duration field should return None."""
        mock_probe.return_value = {"format": {}}

        result = compute_phash_signature_adaptive(Path("invalid.mp4"), "balanced")

        assert result is None

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_phash_from_timestamps')
    def test_timestamps_evenly_distributed(self, mock_compute, mock_probe):
        """Timestamps should be evenly distributed across video duration."""
        mock_probe.return_value = {"format": {"duration": "100"}}
        mock_compute.return_value = tuple(range(100))

        result = compute_phash_signature_adaptive(Path("video.mp4"), "balanced")

        timestamps = mock_compute.call_args[0][1]

        # Should have 100 frames (100s / 1s interval)
        assert len(timestamps) == 100

        # Timestamps should be evenly spaced
        # First timestamp should be > 0 (avoid very start)
        assert timestamps[0] > 0
        # Last timestamp should be < duration (avoid very end)
        assert timestamps[-1] < 100

        # Check spacing is roughly uniform
        if len(timestamps) > 1:
            spacing = timestamps[1] - timestamps[0]
            for i in range(1, len(timestamps) - 1):
                gap = timestamps[i+1] - timestamps[i]
                # Allow small floating point variance
                assert abs(gap - spacing) < 0.01

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_phash_from_timestamps')
    def test_gpu_parameter_passed_through(self, mock_compute, mock_probe):
        """GPU parameter should be passed to extraction function."""
        mock_probe.return_value = {"format": {"duration": "100"}}
        mock_compute.return_value = tuple(range(100))

        result = compute_phash_signature_adaptive(Path("video.mp4"), "balanced", gpu=True)

        # Verify GPU parameter was passed through
        assert mock_compute.called
        assert mock_compute.call_args[1]['gpu'] is True

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_phash_from_timestamps')
    def test_single_frame_for_very_short_duration(self, mock_compute, mock_probe):
        """Video shorter than min_frames × interval should still get min_frames."""
        mock_probe.return_value = {"format": {"duration": "0.5"}}  # 0.5 seconds
        mock_compute.return_value = tuple(range(30))

        result = compute_phash_signature_adaptive(Path("blink.mp4"), "balanced")

        timestamps = mock_compute.call_args[0][1]

        # Even with 0.5s duration, should enforce min_frames=30
        assert len(timestamps) == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
