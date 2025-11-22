#!/usr/bin/env python
"""
Tests for pHash indexing (Phase 4.1).

Tests cover:
- Index creation and configuration
- Frame addition and storage
- Segment extraction and bucketing
- Query operations with Hamming distance filtering
- Video-level duplicate detection
- Statistics and edge cases
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from vdedup.phash_index import PHashIndex, FrameReference
from vdedup.phash import FrameHash, VideoFingerprint


class TestPHashIndexCreation:
    """Tests for PHashIndex initialization."""

    def test_default_creation(self):
        """Default index should use 4 segments."""
        index = PHashIndex()

        assert index.num_segments == 4
        assert index.bits_per_segment == 16  # 64 / 4
        assert index.total_frames == 0
        assert index.total_videos == 0

    def test_custom_segments(self):
        """Should support custom number of segments."""
        index = PHashIndex(num_segments=8)

        assert index.num_segments == 8
        assert index.bits_per_segment == 8  # 64 / 8

    def test_invalid_num_segments_too_low(self):
        """Should reject num_segments < 1."""
        with pytest.raises(ValueError):
            PHashIndex(num_segments=0)

    def test_invalid_num_segments_too_high(self):
        """Should reject num_segments > 8."""
        with pytest.raises(ValueError):
            PHashIndex(num_segments=9)


class TestFrameReference:
    """Tests for FrameReference namedtuple."""

    def test_frame_reference_creation(self):
        """FrameReference should store all frame metadata."""
        ref = FrameReference(
            video_path=Path("test.mp4"),
            frame_index=5,
            timestamp=10.5,
            phash=0x123456789abcdef0
        )

        assert ref.video_path == Path("test.mp4")
        assert ref.frame_index == 5
        assert ref.timestamp == 10.5
        assert ref.phash == 0x123456789abcdef0


class TestPHashIndexAdd:
    """Tests for adding frames to the index."""

    def test_add_single_frame(self):
        """Adding a frame should update statistics."""
        index = PHashIndex()

        index.add(Path("video.mp4"), 0, 1.0, 0x1234567890abcdef)

        assert index.total_frames == 1
        assert index.total_videos == 1

    def test_add_multiple_frames_same_video(self):
        """Adding multiple frames from same video should count correctly."""
        index = PHashIndex()

        index.add(Path("video.mp4"), 0, 1.0, 0x111)
        index.add(Path("video.mp4"), 1, 2.0, 0x222)
        index.add(Path("video.mp4"), 2, 3.0, 0x333)

        assert index.total_frames == 3
        assert index.total_videos == 1  # Still only 1 video

    def test_add_frames_different_videos(self):
        """Adding frames from different videos should count correctly."""
        index = PHashIndex()

        index.add(Path("video1.mp4"), 0, 1.0, 0x111)
        index.add(Path("video2.mp4"), 0, 1.0, 0x222)
        index.add(Path("video3.mp4"), 0, 1.0, 0x333)

        assert index.total_frames == 3
        assert index.total_videos == 3

    def test_add_creates_buckets(self):
        """Adding frames should populate buckets."""
        index = PHashIndex(num_segments=4)

        index.add(Path("video.mp4"), 0, 1.0, 0x1234567890abcdef)

        # Should create 4 buckets (one per segment)
        assert len(index.buckets) == 4

    def test_add_fingerprint(self):
        """add_fingerprint should add all frames from VideoFingerprint."""
        index = PHashIndex()

        frames = tuple([
            FrameHash(timestamp=1.0, index=0, phash=0x111),
            FrameHash(timestamp=2.0, index=1, phash=0x222),
            FrameHash(timestamp=3.0, index=2, phash=0x333),
        ])

        fingerprint = VideoFingerprint(
            path=Path("video.mp4"),
            duration=10.0,
            frames=frames
        )

        index.add_fingerprint(fingerprint)

        assert index.total_frames == 3
        assert index.total_videos == 1


class TestSegmentExtraction:
    """Tests for segment extraction logic."""

    def test_segment_extraction_4_segments(self):
        """Should split 64-bit hash into 4 × 16-bit segments."""
        index = PHashIndex(num_segments=4)

        # Use a simple pattern: 0x0001_0002_0003_0004
        phash = 0x0001000200030004

        segments = index._extract_segments(phash)

        # Should have 4 segments
        assert len(segments) == 4

        # Each segment should be unique (includes segment index in key)
        assert len(set(segments)) == 4

    def test_segment_extraction_different_segments(self):
        """Different segment counts should produce different results."""
        phash = 0x123456789abcdef0

        index4 = PHashIndex(num_segments=4)
        index8 = PHashIndex(num_segments=8)

        segments4 = index4._extract_segments(phash)
        segments8 = index8._extract_segments(phash)

        assert len(segments4) == 4
        assert len(segments8) == 8


class TestPHashIndexQuery:
    """Tests for querying the index."""

    def test_query_exact_match(self):
        """Querying with exact same pHash should return the frame."""
        index = PHashIndex()

        phash = 0x123456789abcdef0
        index.add(Path("video.mp4"), 0, 1.0, phash)

        matches = index.query(phash)

        assert len(matches) == 1
        assert matches[0].phash == phash
        assert matches[0].video_path == Path("video.mp4")

    def test_query_similar_hash(self):
        """Querying with similar pHash should return match if within threshold."""
        index = PHashIndex()

        # Add a frame
        phash1 = 0x123456789abcdef0
        index.add(Path("video.mp4"), 0, 1.0, phash1)

        # Query with very similar hash (1 bit different)
        phash2 = 0x123456789abcdef1

        # Should find it with threshold of 5
        matches = index.query(phash2, hamming_threshold=5)
        assert len(matches) == 1

    def test_query_dissimilar_hash_filtered(self):
        """Querying with dissimilar pHash should not return match if beyond threshold."""
        index = PHashIndex()

        # Add a frame
        phash1 = 0x1234567890abcdef
        index.add(Path("video.mp4"), 0, 1.0, phash1)

        # Query with very different hash
        phash2 = 0xfedcba9876543210

        # Should not find it with low threshold
        matches = index.query(phash2, hamming_threshold=5)
        assert len(matches) == 0

    def test_query_no_threshold(self):
        """Query without threshold should return all bucket candidates."""
        index = PHashIndex()

        # Add several frames
        index.add(Path("v1.mp4"), 0, 1.0, 0x1111111111111111)
        index.add(Path("v2.mp4"), 0, 1.0, 0x2222222222222222)

        # Query should return candidates from buckets (without distance filtering)
        matches = index.query(0x1111111111111111, hamming_threshold=None)

        # Should get at least the exact match
        assert len(matches) >= 1

    def test_query_exclude_video(self):
        """Query should exclude frames from specified video."""
        index = PHashIndex()

        phash = 0x123456789abcdef0

        # Add same pHash from two videos
        index.add(Path("video1.mp4"), 0, 1.0, phash)
        index.add(Path("video2.mp4"), 0, 1.0, phash)

        # Query excluding video1
        matches = index.query(phash, exclude_video=Path("video1.mp4"))

        assert len(matches) == 1
        assert matches[0].video_path == Path("video2.mp4")

    def test_query_multiple_matches(self):
        """Query should return all matching frames."""
        index = PHashIndex()

        phash = 0x123456789abcdef0

        # Add multiple frames with same pHash
        index.add(Path("video1.mp4"), 0, 1.0, phash)
        index.add(Path("video1.mp4"), 1, 2.0, phash)
        index.add(Path("video2.mp4"), 0, 1.0, phash)

        matches = index.query(phash)

        assert len(matches) == 3

    def test_query_deduplicates_frames(self):
        """Query should deduplicate same frame from multiple buckets."""
        index = PHashIndex()

        phash = 0x123456789abcdef0
        index.add(Path("video.mp4"), 0, 1.0, phash)

        # Query (frame will appear in multiple buckets but should be deduped)
        matches = index.query(phash)

        assert len(matches) == 1


class TestFindMatchingVideos:
    """Tests for video-level duplicate detection."""

    @staticmethod
    def _make_distinct_phash(i: int) -> int:
        """Create distinct pHashes that don't share segment buckets."""
        # Use a simple hash function to create well-distributed values
        return ((i * 0x9e3779b97f4a7c15) ^ (i << 32)) & 0xffffffffffffffff

    def test_find_matching_videos_exact_duplicate(self):
        """Should find videos with many matching frames."""
        index = PHashIndex()

        # Use distinct pHashes
        phashes = [self._make_distinct_phash(i) for i in range(10)]

        # Add frames from video1
        for i in range(10):
            index.add(Path("video1.mp4"), i, float(i), phashes[i])

        # Add same frames from video2 (exact duplicate)
        for i in range(10):
            index.add(Path("video2.mp4"), i, float(i), phashes[i])

        # Create fingerprint for video1
        frames = tuple([
            FrameHash(timestamp=float(i), index=i, phash=phashes[i])
            for i in range(10)
        ])
        fp = VideoFingerprint(path=Path("video1.mp4"), duration=10.0, frames=frames)

        # Find matching videos
        matches = index.find_matching_videos(fp, hamming_threshold=5, min_matching_frames=5)

        assert len(matches) == 1
        assert matches[0][0] == Path("video2.mp4")
        assert matches[0][1] == 10  # 10 matching frames

    def test_find_matching_videos_partial_match(self):
        """Should find videos with partial frame matches."""
        index = PHashIndex()

        phashes = [self._make_distinct_phash(i) for i in range(10)]

        # Add frames from video1
        for i in range(10):
            index.add(Path("video1.mp4"), i, float(i), phashes[i])

        # Add partial match from video2 (only first 5 frames match)
        for i in range(5):
            index.add(Path("video2.mp4"), i, float(i), phashes[i])

        # Create fingerprint for video1
        frames = tuple([
            FrameHash(timestamp=float(i), index=i, phash=phashes[i])
            for i in range(10)
        ])
        fp = VideoFingerprint(path=Path("video1.mp4"), duration=10.0, frames=frames)

        # Should find video2 with 5 matching frames
        matches = index.find_matching_videos(fp, min_matching_frames=3)

        assert len(matches) == 1
        assert matches[0][0] == Path("video2.mp4")
        assert matches[0][1] == 5

    def test_find_matching_videos_below_threshold(self):
        """Should not return videos below min_matching_frames threshold."""
        index = PHashIndex()

        phashes = [self._make_distinct_phash(i) for i in range(10)]

        for i in range(10):
            index.add(Path("video1.mp4"), i, float(i), phashes[i])

        # Add only 2 matching frames from video2
        for i in range(2):
            index.add(Path("video2.mp4"), i, float(i), phashes[i])

        frames = tuple([
            FrameHash(timestamp=float(i), index=i, phash=phashes[i])
            for i in range(10)
        ])
        fp = VideoFingerprint(path=Path("video1.mp4"), duration=10.0, frames=frames)

        # Require at least 5 matching frames
        matches = index.find_matching_videos(fp, min_matching_frames=5)

        assert len(matches) == 0

    def test_find_matching_videos_sorted_by_count(self):
        """Results should be sorted by match count descending."""
        index = PHashIndex()

        phashes = [self._make_distinct_phash(i) for i in range(10)]

        # Add different numbers of matches from different videos
        for i in range(3):
            index.add(Path("video_3match.mp4"), i, float(i), phashes[i])

        for i in range(7):
            index.add(Path("video_7match.mp4"), i, float(i), phashes[i])

        for i in range(5):
            index.add(Path("video_5match.mp4"), i, float(i), phashes[i])

        frames = tuple([
            FrameHash(timestamp=float(i), index=i, phash=phashes[i])
            for i in range(10)
        ])
        fp = VideoFingerprint(path=Path("query.mp4"), duration=10.0, frames=frames)

        matches = index.find_matching_videos(fp, min_matching_frames=1)

        # Should be sorted by count descending
        assert matches[0][1] == 7  # video_7match
        assert matches[1][1] == 5  # video_5match
        assert matches[2][1] == 3  # video_3match


class TestHammingDistance:
    """Tests for Hamming distance calculation."""

    def test_hamming_distance_identical(self):
        """Identical hashes should have distance 0."""
        index = PHashIndex()

        dist = index._hamming_distance(0x123456789abcdef0, 0x123456789abcdef0)

        assert dist == 0

    def test_hamming_distance_one_bit(self):
        """One bit difference should have distance 1."""
        index = PHashIndex()

        dist = index._hamming_distance(0x0000000000000000, 0x0000000000000001)

        assert dist == 1

    def test_hamming_distance_all_bits(self):
        """Completely different hashes should have distance 64."""
        index = PHashIndex()

        dist = index._hamming_distance(0x0000000000000000, 0xffffffffffffffff)

        assert dist == 64

    def test_hamming_distance_symmetric(self):
        """Hamming distance should be symmetric."""
        index = PHashIndex()

        hash1 = 0x123456789abcdef0
        hash2 = 0xfedcba9876543210

        dist1 = index._hamming_distance(hash1, hash2)
        dist2 = index._hamming_distance(hash2, hash1)

        assert dist1 == dist2


class TestIndexStatistics:
    """Tests for index statistics."""

    def test_get_stats_empty_index(self):
        """Empty index should report zero statistics."""
        index = PHashIndex()

        stats = index.get_stats()

        assert stats['total_frames'] == 0
        assert stats['total_videos'] == 0
        assert stats['num_buckets'] == 0

    def test_get_stats_with_data(self):
        """Statistics should reflect index contents."""
        index = PHashIndex()

        for i in range(10):
            index.add(Path("video1.mp4"), i, float(i), i * 0x111)

        for i in range(5):
            index.add(Path("video2.mp4"), i, float(i), i * 0x222)

        stats = index.get_stats()

        assert stats['total_frames'] == 15
        assert stats['total_videos'] == 2
        assert stats['num_buckets'] > 0
        assert stats['avg_bucket_size'] > 0

    def test_clear_index(self):
        """Clearing should reset all statistics."""
        index = PHashIndex()

        for i in range(10):
            index.add(Path("video.mp4"), i, float(i), i * 0x111)

        index.clear()

        assert index.total_frames == 0
        assert index.total_videos == 0
        assert len(index.buckets) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
