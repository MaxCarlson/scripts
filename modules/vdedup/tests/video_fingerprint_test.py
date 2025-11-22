#!/usr/bin/env python3
"""
Tests for per-frame pHash storage with timestamps (Phase 3.2).

Tests cover:
- FrameHash and VideoFingerprint data structures
- compute_video_fingerprint() function
- Timestamp and index preservation
- Backward compatibility via get_phash_tuple()
- Error handling
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from vdedup.phash import (
    FrameHash,
    VideoFingerprint,
    compute_video_fingerprint,
)


class TestFrameHash:
    """Tests for FrameHash dataclass."""

    def test_framehash_creation(self):
        """FrameHash should store timestamp, index, and phash."""
        frame = FrameHash(timestamp=1.5, index=0, phash=0x123456789abcdef0)

        assert frame.timestamp == 1.5
        assert frame.index == 0
        assert frame.phash == 0x123456789abcdef0

    def test_framehash_immutable(self):
        """FrameHash should be immutable (frozen dataclass)."""
        frame = FrameHash(timestamp=1.5, index=0, phash=0x123)

        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            frame.timestamp = 2.0

    def test_framehash_equality(self):
        """FrameHashes with same values should be equal."""
        frame1 = FrameHash(timestamp=1.5, index=0, phash=0x123)
        frame2 = FrameHash(timestamp=1.5, index=0, phash=0x123)

        assert frame1 == frame2

    def test_framehash_inequality(self):
        """FrameHashes with different values should not be equal."""
        frame1 = FrameHash(timestamp=1.5, index=0, phash=0x123)
        frame2 = FrameHash(timestamp=1.6, index=0, phash=0x123)

        assert frame1 != frame2


class TestVideoFingerprint:
    """Tests for VideoFingerprint dataclass."""

    def test_video_fingerprint_creation(self):
        """VideoFingerprint should store path, duration, and frames."""
        frames = tuple([
            FrameHash(timestamp=1.0, index=0, phash=0x111),
            FrameHash(timestamp=2.0, index=1, phash=0x222),
            FrameHash(timestamp=3.0, index=2, phash=0x333),
        ])

        fp = VideoFingerprint(
            path=Path("test.mp4"),
            duration=10.0,
            frames=frames
        )

        assert fp.path == Path("test.mp4")
        assert fp.duration == 10.0
        assert len(fp.frames) == 3
        assert fp.frames[0].timestamp == 1.0
        assert fp.frames[1].phash == 0x222

    def test_video_fingerprint_len(self):
        """len() should return number of frames."""
        frames = tuple([
            FrameHash(timestamp=i, index=i, phash=i*111)
            for i in range(5)
        ])

        fp = VideoFingerprint(path=Path("test.mp4"), duration=10.0, frames=frames)

        assert len(fp) == 5

    def test_video_fingerprint_get_phash_tuple(self):
        """get_phash_tuple() should extract just the pHash integers."""
        frames = tuple([
            FrameHash(timestamp=1.0, index=0, phash=0xaaa),
            FrameHash(timestamp=2.0, index=1, phash=0xbbb),
            FrameHash(timestamp=3.0, index=2, phash=0xccc),
        ])

        fp = VideoFingerprint(path=Path("test.mp4"), duration=10.0, frames=frames)
        phash_tuple = fp.get_phash_tuple()

        assert phash_tuple == (0xaaa, 0xbbb, 0xccc)
        assert isinstance(phash_tuple, tuple)

    def test_video_fingerprint_immutable(self):
        """VideoFingerprint should be immutable."""
        frames = tuple([FrameHash(timestamp=1.0, index=0, phash=0x111)])
        fp = VideoFingerprint(path=Path("test.mp4"), duration=10.0, frames=frames)

        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            fp.duration = 20.0

    def test_video_fingerprint_empty_frames(self):
        """VideoFingerprint with empty frames should work."""
        fp = VideoFingerprint(path=Path("test.mp4"), duration=10.0, frames=tuple())

        assert len(fp) == 0
        assert fp.get_phash_tuple() == tuple()


class TestComputeVideoFingerprint:
    """Tests for compute_video_fingerprint function."""

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_successful_fingerprint_computation(self, mock_compute, mock_probe):
        """Successful computation should return VideoFingerprint."""
        # Mock 10-second video
        mock_probe.return_value = {"format": {"duration": "10"}}

        # Mock frame hash extraction
        mock_frames = [
            FrameHash(timestamp=1.0, index=0, phash=0x111),
            FrameHash(timestamp=2.0, index=1, phash=0x222),
            FrameHash(timestamp=3.0, index=2, phash=0x333),
        ]
        mock_compute.return_value = mock_frames

        result = compute_video_fingerprint(Path("test.mp4"), "balanced")

        assert result is not None
        assert isinstance(result, VideoFingerprint)
        assert result.path == Path("test.mp4")
        assert result.duration == 10.0
        assert len(result.frames) == 3
        assert result.frames[0].timestamp == 1.0
        assert result.frames[1].phash == 0x222

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_timestamps_preserved(self, mock_compute, mock_probe):
        """Timestamps from extraction should be preserved in VideoFingerprint."""
        mock_probe.return_value = {"format": {"duration": "100"}}

        # Create frames with specific timestamps
        mock_frames = [
            FrameHash(timestamp=10.5, index=0, phash=0x1),
            FrameHash(timestamp=20.7, index=1, phash=0x2),
            FrameHash(timestamp=30.3, index=2, phash=0x3),
        ]
        mock_compute.return_value = mock_frames

        result = compute_video_fingerprint(Path("video.mp4"))

        assert result.frames[0].timestamp == 10.5
        assert result.frames[1].timestamp == 20.7
        assert result.frames[2].timestamp == 30.3

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_frame_indices_preserved(self, mock_compute, mock_probe):
        """Frame indices should be preserved in order."""
        mock_probe.return_value = {"format": {"duration": "100"}}

        mock_frames = [
            FrameHash(timestamp=i*10.0, index=i, phash=i*0x111)
            for i in range(10)
        ]
        mock_compute.return_value = mock_frames

        result = compute_video_fingerprint(Path("video.mp4"))

        for i, frame in enumerate(result.frames):
            assert frame.index == i

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_backward_compatibility_get_phash_tuple(self, mock_compute, mock_probe):
        """get_phash_tuple() should provide backward compatibility."""
        mock_probe.return_value = {"format": {"duration": "10"}}

        mock_frames = [
            FrameHash(timestamp=1.0, index=0, phash=0xaaa),
            FrameHash(timestamp=2.0, index=1, phash=0xbbb),
            FrameHash(timestamp=3.0, index=2, phash=0xccc),
        ]
        mock_compute.return_value = mock_frames

        result = compute_video_fingerprint(Path("test.mp4"))

        # Should be able to extract plain tuple for old code
        phash_tuple = result.get_phash_tuple()
        assert phash_tuple == (0xaaa, 0xbbb, 0xccc)
        assert isinstance(phash_tuple, tuple)

    @patch('vdedup.probe.run_ffprobe_json')
    def test_probe_failure_returns_none(self, mock_probe):
        """Failed ffprobe should return None."""
        mock_probe.return_value = None

        result = compute_video_fingerprint(Path("broken.mp4"))

        assert result is None

    @patch('vdedup.probe.run_ffprobe_json')
    def test_zero_duration_returns_none(self, mock_probe):
        """Zero duration video should return None."""
        mock_probe.return_value = {"format": {"duration": "0"}}

        result = compute_video_fingerprint(Path("empty.mp4"))

        assert result is None

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_extraction_failure_returns_none(self, mock_compute, mock_probe):
        """Failed frame extraction should return None."""
        mock_probe.return_value = {"format": {"duration": "10"}}
        mock_compute.return_value = None  # Extraction failed

        result = compute_video_fingerprint(Path("corrupted.mp4"))

        assert result is None

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_empty_frames_returns_none(self, mock_compute, mock_probe):
        """Empty frame list should return None."""
        mock_probe.return_value = {"format": {"duration": "10"}}
        mock_compute.return_value = []  # No frames extracted

        result = compute_video_fingerprint(Path("test.mp4"))

        assert result is None

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_mode_passed_to_sampling(self, mock_compute, mock_probe):
        """Sampling mode should be used for parameter calculation."""
        mock_probe.return_value = {"format": {"duration": "1800"}}  # 30 min
        mock_compute.return_value = [FrameHash(1.0, 0, 0x123)]

        # Fast mode should request fewer timestamps
        compute_video_fingerprint(Path("video.mp4"), "fast")

        # Check that appropriate number of timestamps were requested
        timestamps_fast = mock_compute.call_args[0][1]

        mock_compute.reset_mock()

        # Thorough mode should request more timestamps
        compute_video_fingerprint(Path("video.mp4"), "thorough")

        timestamps_thorough = mock_compute.call_args[0][1]

        # Thorough should have more timestamps than fast
        assert len(timestamps_thorough) > len(timestamps_fast)

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_gpu_parameter_passed_through(self, mock_compute, mock_probe):
        """GPU parameter should be passed to frame extraction."""
        mock_probe.return_value = {"format": {"duration": "10"}}
        mock_compute.return_value = [FrameHash(1.0, 0, 0x123)]

        compute_video_fingerprint(Path("video.mp4"), gpu=True)

        # Verify GPU parameter was passed
        assert mock_compute.called
        assert mock_compute.call_args[1]['gpu'] is True

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_frames_tuple_not_list(self, mock_compute, mock_probe):
        """VideoFingerprint.frames should be a tuple, not a list."""
        mock_probe.return_value = {"format": {"duration": "10"}}
        mock_frames = [FrameHash(1.0, 0, 0x111), FrameHash(2.0, 1, 0x222)]
        mock_compute.return_value = mock_frames

        result = compute_video_fingerprint(Path("test.mp4"))

        assert isinstance(result.frames, tuple)
        assert not isinstance(result.frames, list)

    @patch('vdedup.probe.run_ffprobe_json')
    @patch('vdedup.phash._compute_frame_hashes_with_timestamps')
    def test_large_video_many_frames(self, mock_compute, mock_probe):
        """Large video should handle many frames correctly."""
        mock_probe.return_value = {"format": {"duration": "7200"}}  # 2 hours

        # Mock 1000 frames (max for balanced mode)
        mock_frames = [
            FrameHash(timestamp=i*7.2, index=i, phash=i*0x1234)
            for i in range(1000)
        ]
        mock_compute.return_value = mock_frames

        result = compute_video_fingerprint(Path("movie.mp4"))

        assert len(result) == 1000
        assert result.frames[0].index == 0
        assert result.frames[999].index == 999
        assert result.duration == 7200.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
