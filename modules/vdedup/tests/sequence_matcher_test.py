#!/usr/bin/env python
"""
Tests for sequence-based partial overlap detection (Phase 4.2).

Tests cover:
- Diagonal streak detection
- Temporal overlap calculation
- Full duplicate detection
- Partial overlap detection (≥10% threshold)
- Gap tolerance in streaks
"""

import pytest
from pathlib import Path

from vdedup.sequence_matcher import (
    SequenceMatcher,
    OverlapMatch,
    DiagonalStreak,
    find_all_overlaps
)
from vdedup.phash import FrameHash, VideoFingerprint
from vdedup.phash_index import PHashIndex


class TestOverlapMatch:
    """Tests for OverlapMatch dataclass."""

    def test_overlap_match_creation(self):
        """OverlapMatch should store all overlap information."""
        match = OverlapMatch(
            video_a_path=Path("video1.mp4"),
            video_b_path=Path("video2.mp4"),
            overlap_duration=60.0,
            overlap_ratio=0.5,
            start_a=10.0,
            end_a=70.0,
            start_b=5.0,
            end_b=65.0,
            matching_frames=30
        )

        assert match.video_a_path == Path("video1.mp4")
        assert match.overlap_duration == 60.0
        assert match.overlap_ratio == 0.5
        assert match.matching_frames == 30

    def test_is_full_duplicate_high_overlap(self):
        """Overlap ≥95% should be considered full duplicate."""
        match = OverlapMatch(
            video_a_path=Path("a.mp4"),
            video_b_path=Path("b.mp4"),
            overlap_duration=95.0,
            overlap_ratio=0.95,
            start_a=0.0,
            end_a=95.0,
            start_b=0.0,
            end_b=95.0,
            matching_frames=95
        )

        assert match.is_full_duplicate()

    def test_is_full_duplicate_low_overlap(self):
        """Overlap <95% should not be considered full duplicate."""
        match = OverlapMatch(
            video_a_path=Path("a.mp4"),
            video_b_path=Path("b.mp4"),
            overlap_duration=50.0,
            overlap_ratio=0.5,
            start_a=0.0,
            end_a=50.0,
            start_b=0.0,
            end_b=50.0,
            matching_frames=50
        )

        assert not match.is_full_duplicate()

    def test_is_subset_above_threshold(self):
        """Overlap ≥10% should be considered subset."""
        match = OverlapMatch(
            video_a_path=Path("a.mp4"),
            video_b_path=Path("b.mp4"),
            overlap_duration=15.0,
            overlap_ratio=0.15,
            start_a=0.0,
            end_a=15.0,
            start_b=0.0,
            end_b=15.0,
            matching_frames=15
        )

        assert match.is_subset(min_ratio=0.10)

    def test_is_subset_below_threshold(self):
        """Overlap <10% should not be considered subset."""
        match = OverlapMatch(
            video_a_path=Path("a.mp4"),
            video_b_path=Path("b.mp4"),
            overlap_duration=5.0,
            overlap_ratio=0.05,
            start_a=0.0,
            end_a=5.0,
            start_b=0.0,
            end_b=5.0,
            matching_frames=5
        )

        assert not match.is_subset(min_ratio=0.10)


class TestDiagonalStreakDetection:
    """Tests for diagonal streak detection in match pairs."""

    def test_simple_diagonal_streak(self):
        """Consecutive diagonal matches should form a streak."""
        matcher = SequenceMatcher(min_streak_length=3)

        # Perfect diagonal: (0,0), (1,1), (2,2), (3,3), (4,4)
        matches = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]

        streaks = matcher._find_diagonal_streaks(matches)

        assert len(streaks) == 1
        assert streaks[0].start_a == 0
        assert streaks[0].start_b == 0
        assert streaks[0].length == 5

    def test_multiple_separate_streaks(self):
        """Non-consecutive matches should create separate streaks."""
        matcher = SequenceMatcher(min_streak_length=2)

        # Two separate streaks: (0,0)-(2,2) and (10,10)-(12,12)
        matches = [(0, 0), (1, 1), (2, 2), (10, 10), (11, 11), (12, 12)]

        streaks = matcher._find_diagonal_streaks(matches)

        assert len(streaks) == 2
        assert streaks[0].length == 3
        assert streaks[1].length == 3

    def test_streak_with_small_gap(self):
        """Small gaps within gap_tolerance should be accepted."""
        matcher = SequenceMatcher(min_streak_length=3, gap_tolerance=2)

        # Streak with 1-frame gap: (0,0), (1,1), (3,3), (4,4)
        matches = [(0, 0), (1, 1), (3, 3), (4, 4)]

        streaks = matcher._find_diagonal_streaks(matches)

        assert len(streaks) == 1
        assert streaks[0].length >= 3

    def test_no_streak_below_min_length(self):
        """Streaks shorter than min_length should be filtered."""
        matcher = SequenceMatcher(min_streak_length=5)

        # Only 3 consecutive matches
        matches = [(0, 0), (1, 1), (2, 2)]

        streaks = matcher._find_diagonal_streaks(matches)

        assert len(streaks) == 0

    def test_offset_diagonal(self):
        """Diagonal streaks can start at any offset."""
        matcher = SequenceMatcher(min_streak_length=3)

        # Diagonal starting at (5, 10)
        matches = [(5, 10), (6, 11), (7, 12), (8, 13)]

        streaks = matcher._find_diagonal_streaks(matches)

        assert len(streaks) == 1
        assert streaks[0].start_a == 5
        assert streaks[0].start_b == 10
        assert streaks[0].length == 4

    def test_non_diagonal_matches_rejected(self):
        """Matches that don't form diagonals should be rejected."""
        matcher = SequenceMatcher(min_streak_length=2)

        # Random matches, no clear diagonal
        matches = [(0, 5), (1, 20), (2, 3), (10, 8)]

        streaks = matcher._find_diagonal_streaks(matches)

        # Should find no valid streaks (or very short ones filtered out)
        assert len(streaks) == 0 or all(s.length < 3 for s in streaks)


class TestSequenceMatcherIntegration:
    """Integration tests using real VideoFingerprint and PHashIndex."""

    @staticmethod
    def _make_fingerprint(path: str, num_frames: int, start_phash: int = 0):
        """Create a test VideoFingerprint with sequential pHashes.

        Each frame gets a distinct pHash by using a hash function to ensure
        frames are well-distributed (high Hamming distance between different frames).
        Identical frame indices in different videos will have identical pHashes (Hamming=0).
        """
        frames = tuple([
            FrameHash(
                timestamp=float(i),
                index=i,
                # Use hash function to create well-distributed pHashes
                # Same index in different videos will have IDENTICAL phash (Hamming=0)
                # Different indices will have LARGE Hamming distance
                phash=((start_phash + i) * 0x9e3779b97f4a7c15) & 0xffffffffffffffff
            )
            for i in range(num_frames)
        ])

        return VideoFingerprint(
            path=Path(path),
            duration=float(num_frames),
            frames=frames
        )

    def test_full_duplicate_detection(self):
        """Should detect two identical videos as full duplicates."""
        # Create two identical videos
        fp1 = self._make_fingerprint("video1.mp4", 100, start_phash=0x1000)
        fp2 = self._make_fingerprint("video2.mp4", 100, start_phash=0x1000)

        # Build index
        index = PHashIndex()
        index.add_fingerprint(fp1)
        index.add_fingerprint(fp2)

        # Find overlap
        matcher = SequenceMatcher(hamming_threshold=5, min_streak_length=10)
        overlap = matcher.find_overlap(fp1, fp2, index)

        assert overlap is not None
        assert overlap.is_full_duplicate()
        assert overlap.overlap_ratio >= 0.95

    def test_partial_overlap_detection(self):
        """Should detect partial overlap when first half matches."""
        # Video 1: frames 0-99
        # Video 2: frames 0-49 match, frames 50-99 different
        fp1 = self._make_fingerprint("video1.mp4", 100, start_phash=0x1000)

        # Create video2 with only first 50 frames matching
        frames2 = list(fp1.frames[:50])  # First 50 match
        frames2.extend([
            FrameHash(timestamp=float(i), index=i, phash=0x9999 + i)
            for i in range(50, 100)
        ])

        fp2 = VideoFingerprint(
            path=Path("video2.mp4"),
            duration=100.0,
            frames=tuple(frames2)
        )

        # Build index
        index = PHashIndex()
        index.add_fingerprint(fp1)
        index.add_fingerprint(fp2)

        # Find overlap
        matcher = SequenceMatcher(hamming_threshold=5, min_streak_length=10)
        overlap = matcher.find_overlap(fp1, fp2, index)

        assert overlap is not None
        assert overlap.is_subset(min_ratio=0.10)
        # Should find ~50% overlap (first half matches)
        assert 0.4 <= overlap.overlap_ratio <= 0.6

    def test_clip_detection(self):
        """Should detect when short video is subset of long video."""
        # Long video: 100 frames
        fp_long = self._make_fingerprint("long.mp4", 100, start_phash=0x1000)

        # Short video: frames 20-39 (middle section of long video)
        # Need to reindex frames to 0-19 for the short video
        frames_short = tuple([
            FrameHash(timestamp=float(new_idx), index=new_idx, phash=frame.phash)
            for new_idx, frame in enumerate(fp_long.frames[20:40])
        ])
        fp_short = VideoFingerprint(
            path=Path("short.mp4"),
            duration=20.0,
            frames=frames_short
        )

        # Build index
        index = PHashIndex()
        index.add_fingerprint(fp_long)
        index.add_fingerprint(fp_short)

        # Find overlap
        matcher = SequenceMatcher(hamming_threshold=5, min_streak_length=5)
        overlap = matcher.find_overlap(fp_short, fp_long, index)

        assert overlap is not None
        assert overlap.is_subset(min_ratio=0.10)
        # 20 frames out of 100 = 20% of longer video
        assert overlap.overlap_ratio >= 0.15

    def test_no_overlap_different_videos(self):
        """Should find no overlap when videos are completely different."""
        # Two completely different videos
        fp1 = self._make_fingerprint("video1.mp4", 50, start_phash=0x1000)
        fp2 = self._make_fingerprint("video2.mp4", 50, start_phash=0x9000)

        # Build index
        index = PHashIndex()
        index.add_fingerprint(fp1)
        index.add_fingerprint(fp2)

        # Find overlap
        matcher = SequenceMatcher(hamming_threshold=5, min_streak_length=5)
        overlap = matcher.find_overlap(fp1, fp2, index)

        # Should find no significant overlap
        assert overlap is None or overlap.overlap_ratio < 0.10


class TestFindAllOverlaps:
    """Tests for finding overlaps among multiple videos."""

    @staticmethod
    def _make_fingerprint(path: str, num_frames: int, start_phash: int = 0):
        """Create a test VideoFingerprint."""
        frames = tuple([
            FrameHash(
                timestamp=float(i),
                index=i,
                # Use hash function to create well-distributed pHashes
                phash=((start_phash + i) * 0x9e3779b97f4a7c15) & 0xffffffffffffffff
            )
            for i in range(num_frames)
        ])

        return VideoFingerprint(
            path=Path(path),
            duration=float(num_frames),
            frames=frames
        )

    def test_find_all_overlaps_multiple_duplicates(self):
        """Should find all pairwise overlaps among duplicates."""
        # Create 3 identical videos
        fingerprints = [
            self._make_fingerprint(f"video{i}.mp4", 50, start_phash=0x1000)
            for i in range(3)
        ]

        # Build index
        index = PHashIndex()
        for fp in fingerprints:
            index.add_fingerprint(fp)

        # Find all overlaps
        overlaps = find_all_overlaps(
            fingerprints,
            index,
            min_overlap_ratio=0.10,
            min_streak_length=10
        )

        # Should find 3 pairs: (0,1), (0,2), (1,2)
        assert len(overlaps) == 3

        # All should be full duplicates
        assert all(o.is_full_duplicate() for o in overlaps)

    def test_find_all_overlaps_mixed(self):
        """Should find only significant overlaps among mixed videos."""
        # Video 0: frames 0-49
        # Video 1: identical to video 0 (full duplicate)
        # Video 2: completely different (no overlap)
        # Video 3: frames 0-24 match video 0 (partial overlap)

        fp0 = self._make_fingerprint("video0.mp4", 50, start_phash=0x1000)
        fp1 = self._make_fingerprint("video1.mp4", 50, start_phash=0x1000)  # Duplicate
        fp2 = self._make_fingerprint("video2.mp4", 50, start_phash=0x9000)  # Different

        # Partial overlap: first half matches
        frames3 = list(fp0.frames[:25])
        frames3.extend([
            FrameHash(timestamp=float(i), index=i, phash=0x8888 + i)
            for i in range(25, 50)
        ])
        fp3 = VideoFingerprint(path=Path("video3.mp4"), duration=50.0, frames=tuple(frames3))

        fingerprints = [fp0, fp1, fp2, fp3]

        # Build index
        index = PHashIndex()
        for fp in fingerprints:
            index.add_fingerprint(fp)

        # Find all overlaps (≥10%)
        overlaps = find_all_overlaps(
            fingerprints,
            index,
            min_overlap_ratio=0.10,
            min_streak_length=5
        )

        # Should find:
        # - (0,1): full duplicate
        # - (0,3): partial overlap
        # - (1,3): partial overlap
        # Should NOT find any involving video2
        assert len(overlaps) >= 2

        # No overlap should involve video2
        for overlap in overlaps:
            assert Path("video2.mp4") not in [overlap.video_a_path, overlap.video_b_path]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
