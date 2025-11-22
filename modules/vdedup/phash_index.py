#!/usr/bin/env python
"""
pHash indexing for efficient near-neighbor search.

This module provides a bucket-based index for fast lookup of similar pHashes
without requiring O(N²) comparisons. Uses segment-based bucketing where each
64-bit pHash is split into multiple segments for indexing.

Strategy:
- Split 64-bit pHash into 4 × 16-bit segments
- Index each frame in multiple buckets (one per segment)
- Query returns candidates from all matching buckets
- Filter candidates by Hamming distance threshold

This enables O(1) bucket lookup + O(k) candidate filtering instead of O(N²)
pairwise comparisons across all frames.
"""

from __future__ import annotations
from typing import Dict, List, Set, Tuple, Optional, NamedTuple
from pathlib import Path
from collections import defaultdict


class FrameReference(NamedTuple):
    """Reference to a specific frame in a video."""
    video_path: Path
    frame_index: int
    timestamp: float
    phash: int


class PHashIndex:
    """
    Bucket-based index for efficient pHash near-neighbor search.

    Uses segment-based bucketing: each 64-bit pHash is split into segments
    (e.g., 4 × 16-bit) and indexed in multiple buckets. Query returns all
    frames in matching buckets, which can then be filtered by Hamming distance.

    Example:
        >>> index = PHashIndex(num_segments=4)
        >>> index.add(Path("video1.mp4"), 0, 1.5, 0x123456789abcdef0)
        >>> index.add(Path("video2.mp4"), 0, 2.0, 0x123456789abcdef1)
        >>> matches = index.query(0x123456789abcdef0, hamming_threshold=5)
        >>> print(f"Found {len(matches)} similar frames")
    """

    def __init__(self, num_segments: int = 4):
        """
        Initialize pHash index.

        Args:
            num_segments: Number of segments to split each pHash into (default: 4)
                         More segments = more buckets = higher memory but faster queries
        """
        if num_segments < 1 or num_segments > 8:
            raise ValueError("num_segments must be between 1 and 8")

        self.num_segments = num_segments
        self.bits_per_segment = 64 // num_segments

        # Buckets: segment_key -> list of FrameReferences
        # Each pHash is indexed in num_segments buckets (one per segment)
        self.buckets: Dict[int, List[FrameReference]] = defaultdict(list)

        # Statistics
        self.total_frames = 0
        self.total_videos = 0
        self._video_paths: Set[Path] = set()

    def add(self, video_path: Path, frame_index: int, timestamp: float, phash: int) -> None:
        """
        Add a frame to the index.

        The frame will be indexed in multiple buckets based on its pHash segments.

        Args:
            video_path: Path to video file
            frame_index: Frame index in the video (0-based)
            timestamp: Timestamp in seconds
            phash: 64-bit perceptual hash as integer
        """
        frame_ref = FrameReference(
            video_path=video_path,
            frame_index=frame_index,
            timestamp=timestamp,
            phash=phash
        )

        # Extract segments and add to corresponding buckets
        segments = self._extract_segments(phash)
        for segment in segments:
            self.buckets[segment].append(frame_ref)

        # Update statistics
        self.total_frames += 1
        if video_path not in self._video_paths:
            self._video_paths.add(video_path)
            self.total_videos += 1

    def add_fingerprint(self, fingerprint) -> None:
        """
        Add all frames from a VideoFingerprint to the index.

        Args:
            fingerprint: VideoFingerprint object with frames
        """
        for frame in fingerprint.frames:
            self.add(
                video_path=fingerprint.path,
                frame_index=frame.index,
                timestamp=frame.timestamp,
                phash=frame.phash
            )

    def query(
        self,
        phash: int,
        hamming_threshold: Optional[int] = None,
        exclude_video: Optional[Path] = None
    ) -> List[FrameReference]:
        """
        Find frames similar to the given pHash.

        Strategy:
        1. Extract segments from query pHash
        2. Collect all frames from matching buckets (union)
        3. Deduplicate candidates
        4. Optionally filter by Hamming distance threshold
        5. Optionally exclude frames from a specific video

        Args:
            phash: Query pHash to find neighbors for
            hamming_threshold: Maximum Hamming distance (None = no filtering)
            exclude_video: Exclude frames from this video (useful for finding
                          duplicates in other videos)

        Returns:
            List of FrameReference objects for matching frames
        """
        # Collect candidates from all matching buckets
        candidates: Dict[Tuple[Path, int], FrameReference] = {}

        segments = self._extract_segments(phash)
        for segment in segments:
            for frame_ref in self.buckets[segment]:
                # Use (video_path, frame_index) as key to deduplicate
                key = (frame_ref.video_path, frame_ref.frame_index)
                if key not in candidates:
                    candidates[key] = frame_ref

        # Convert to list
        results = list(candidates.values())

        # Filter by Hamming distance if threshold provided
        if hamming_threshold is not None:
            results = [
                frame_ref for frame_ref in results
                if self._hamming_distance(phash, frame_ref.phash) <= hamming_threshold
            ]

        # Exclude specific video if requested
        if exclude_video is not None:
            results = [
                frame_ref for frame_ref in results
                if frame_ref.video_path != exclude_video
            ]

        return results

    def find_matching_videos(
        self,
        fingerprint,
        hamming_threshold: int = 12,
        min_matching_frames: int = 3
    ) -> List[Tuple[Path, int]]:
        """
        Find videos that have multiple matching frames with the query fingerprint.

        This is useful for finding duplicate or similar videos.

        Args:
            fingerprint: VideoFingerprint to search for
            hamming_threshold: Maximum Hamming distance for frame matches
            min_matching_frames: Minimum number of matching frames to report

        Returns:
            List of (video_path, match_count) tuples sorted by match count descending
        """
        from collections import defaultdict

        # Track unique frame matches per video
        # video_path -> set of (query_frame_idx, match_frame_idx)
        video_matches: Dict[Path, Set[Tuple[int, int]]] = defaultdict(set)

        for frame in fingerprint.frames:
            matches = self.query(
                phash=frame.phash,
                hamming_threshold=hamming_threshold,
                exclude_video=fingerprint.path  # Don't match against self
            )

            for match in matches:
                # Use (query_frame_idx, match_frame_idx) to deduplicate
                # This ensures we only count each unique frame pair once
                video_matches[match.video_path].add((frame.index, match.frame_index))

        # Convert to counts and filter
        results = [
            (video_path, len(matches))
            for video_path, matches in video_matches.items()
            if len(matches) >= min_matching_frames
        ]

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _extract_segments(self, phash: int) -> List[int]:
        """
        Extract segment keys from a 64-bit pHash.

        Splits the pHash into num_segments pieces and returns each as a separate key.

        Args:
            phash: 64-bit pHash integer

        Returns:
            List of segment keys (integers)
        """
        segments = []
        mask = (1 << self.bits_per_segment) - 1  # e.g., 0xFFFF for 16 bits

        for i in range(self.num_segments):
            shift = i * self.bits_per_segment
            segment = (phash >> shift) & mask
            # Include segment index in key to avoid collisions between segments
            segment_key = (i << 32) | segment
            segments.append(segment_key)

        return segments

    @staticmethod
    def _hamming_distance(hash1: int, hash2: int) -> int:
        """
        Compute Hamming distance between two pHashes.

        Args:
            hash1: First pHash
            hash2: Second pHash

        Returns:
            Number of differing bits (0-64)
        """
        xor = hash1 ^ hash2
        # Python 3.10+ has int.bit_count()
        if hasattr(int, 'bit_count'):
            return xor.bit_count()
        else:
            return bin(xor).count('1')

    def get_stats(self) -> Dict[str, int]:
        """
        Get index statistics.

        Returns:
            Dictionary with statistics about the index
        """
        return {
            'total_frames': self.total_frames,
            'total_videos': self.total_videos,
            'num_buckets': len(self.buckets),
            'avg_bucket_size': sum(len(b) for b in self.buckets.values()) / max(1, len(self.buckets)),
        }

    def clear(self) -> None:
        """Clear all data from the index."""
        self.buckets.clear()
        self._video_paths.clear()
        self.total_frames = 0
        self.total_videos = 0
