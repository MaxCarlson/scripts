#!/usr/bin/env python
"""
Sequence-based matching for detecting partial video overlaps.

This module implements diagonal streak matching to find contiguous temporal
overlaps between videos. Unlike simple frame-by-frame comparison, this approach
identifies sequences where frames from video A align temporally with frames from
video B (diagonal streaks in the match matrix).

Strategy:
1. Find all matching frame pairs between two videos (using pHash index)
2. Look for diagonal streaks (sequences where both frame indices increase together)
3. Measure streak length in seconds (temporal overlap)
4. Report overlap if duration ≥ threshold (e.g., ≥10% of longer video)

This detects:
- Full duplicates (entire video overlaps)
- Clips (short video is subset of long video)
- Partial overlaps (≥10% contiguous segment match)
"""

from __future__ import annotations
from typing import List, Tuple, Optional, NamedTuple
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class OverlapMatch:
    """
    Detected temporal overlap between two videos.

    Attributes:
        video_a_path: Path to first video
        video_b_path: Path to second video
        overlap_duration: Duration of overlap in seconds
        overlap_ratio: Ratio relative to longer video (0.0-1.0)
        start_a: Start timestamp in video A (seconds)
        start_b: Start timestamp in video B (seconds)
        end_a: End timestamp in video A (seconds)
        end_b: End timestamp in video B (seconds)
        matching_frames: Number of matching frames in the streak
    """
    video_a_path: Path
    video_b_path: Path
    overlap_duration: float
    overlap_ratio: float
    start_a: float
    end_a: float
    start_b: float
    end_b: float
    matching_frames: int

    def is_full_duplicate(self, tolerance: float = 0.95) -> bool:
        """Check if this is a full duplicate (≥95% overlap)."""
        return self.overlap_ratio >= tolerance

    def is_subset(self, min_ratio: float = 0.10) -> bool:
        """Check if this is a partial overlap/subset (≥10% overlap)."""
        return self.overlap_ratio >= min_ratio


class DiagonalStreak(NamedTuple):
    """
    A diagonal streak in the frame match matrix.

    Represents a sequence of matching frames where both indices increase together,
    indicating temporal alignment.
    """
    start_a: int  # Starting frame index in video A
    start_b: int  # Starting frame index in video B
    length: int   # Number of consecutive matching frames


class SequenceMatcher:
    """
    Detects partial overlaps between videos using diagonal streak matching.

    This class analyzes frame-level matches between two videos to find contiguous
    temporal overlaps (diagonal streaks in the match matrix).

    Example:
        >>> from vdedup.phash_index import PHashIndex
        >>> from vdedup.phash import compute_video_fingerprint
        >>>
        >>> # Build index
        >>> index = PHashIndex()
        >>> fp1 = compute_video_fingerprint(Path("video1.mp4"))
        >>> fp2 = compute_video_fingerprint(Path("video2.mp4"))
        >>> index.add_fingerprint(fp1)
        >>> index.add_fingerprint(fp2)
        >>>
        >>> # Find overlaps
        >>> matcher = SequenceMatcher(hamming_threshold=12, min_streak_length=5)
        >>> overlap = matcher.find_overlap(fp1, fp2, index)
        >>> if overlap and overlap.is_subset(min_ratio=0.10):
        ...     print(f"Found {overlap.overlap_ratio*100:.1f}% overlap")
    """

    def __init__(
        self,
        hamming_threshold: int = 12,
        min_streak_length: int = 5,
        gap_tolerance: int = 2
    ):
        """
        Initialize sequence matcher.

        Args:
            hamming_threshold: Maximum Hamming distance for frame matches
            min_streak_length: Minimum number of consecutive frames for a valid streak
            gap_tolerance: Allow small gaps in diagonal streaks (frames can be skipped)
        """
        self.hamming_threshold = hamming_threshold
        self.min_streak_length = min_streak_length
        self.gap_tolerance = gap_tolerance

    def find_overlap(
        self,
        fingerprint_a,
        fingerprint_b,
        index
    ) -> Optional[OverlapMatch]:
        """
        Find the best temporal overlap between two videos.

        Args:
            fingerprint_a: VideoFingerprint for first video
            fingerprint_b: VideoFingerprint for second video
            index: PHashIndex containing both videos' frames

        Returns:
            OverlapMatch if significant overlap found, None otherwise
        """
        # Find all matching frame pairs
        matches = self._find_matching_pairs(fingerprint_a, fingerprint_b, index)

        if not matches:
            return None

        # Find diagonal streaks
        streaks = self._find_diagonal_streaks(matches)

        if not streaks:
            return None

        # Convert best streak to OverlapMatch
        best_streak = max(streaks, key=lambda s: s.length)

        if best_streak.length < self.min_streak_length:
            return None

        return self._streak_to_overlap(best_streak, fingerprint_a, fingerprint_b)

    def _find_matching_pairs(
        self,
        fingerprint_a,
        fingerprint_b,
        index
    ) -> List[Tuple[int, int]]:
        """
        Find all (frame_a_idx, frame_b_idx) pairs that match.

        Args:
            fingerprint_a: VideoFingerprint for first video
            fingerprint_b: VideoFingerprint for second video
            index: PHashIndex for efficient lookup

        Returns:
            List of (frame_a_index, frame_b_index) tuples
        """
        matches = []

        for frame_a in fingerprint_a.frames:
            # Query index for similar frames
            similar_frames = index.query(
                phash=frame_a.phash,
                hamming_threshold=self.hamming_threshold,
                exclude_video=fingerprint_a.path
            )

            # Filter to only frames from video B
            for match in similar_frames:
                if match.video_path == fingerprint_b.path:
                    matches.append((frame_a.index, match.frame_index))

        return matches

    def _find_diagonal_streaks(
        self,
        matches: List[Tuple[int, int]]
    ) -> List[DiagonalStreak]:
        """
        Find diagonal streaks in the match pairs.

        A diagonal streak is a sequence where both indices increase together,
        indicating temporal alignment.

        Args:
            matches: List of (frame_a_idx, frame_b_idx) pairs

        Returns:
            List of DiagonalStreak objects
        """
        if not matches:
            return []

        # Sort by first index, then second
        sorted_matches = sorted(matches)

        streaks = []
        current_streak_start_a = sorted_matches[0][0]
        current_streak_start_b = sorted_matches[0][1]
        current_streak_length = 1
        last_a = sorted_matches[0][0]
        last_b = sorted_matches[0][1]

        for idx_a, idx_b in sorted_matches[1:]:
            # Check if this continues the diagonal streak
            # Allow for small gaps (gap_tolerance)
            gap_a = idx_a - last_a
            gap_b = idx_b - last_b

            if (gap_a > 0 and gap_b > 0 and
                gap_a <= self.gap_tolerance + 1 and
                gap_b <= self.gap_tolerance + 1 and
                abs(gap_a - gap_b) <= 1):  # Diagonal (similar progress in both)
                # Continue streak
                current_streak_length += 1
            else:
                # End current streak, start new one
                if current_streak_length >= self.min_streak_length:
                    streaks.append(DiagonalStreak(
                        start_a=current_streak_start_a,
                        start_b=current_streak_start_b,
                        length=current_streak_length
                    ))

                current_streak_start_a = idx_a
                current_streak_start_b = idx_b
                current_streak_length = 1

            last_a = idx_a
            last_b = idx_b

        # Don't forget the last streak
        if current_streak_length >= self.min_streak_length:
            streaks.append(DiagonalStreak(
                start_a=current_streak_start_a,
                start_b=current_streak_start_b,
                length=current_streak_length
            ))

        return streaks

    def _streak_to_overlap(
        self,
        streak: DiagonalStreak,
        fingerprint_a,
        fingerprint_b
    ) -> OverlapMatch:
        """
        Convert a DiagonalStreak to an OverlapMatch with temporal information.

        Args:
            streak: DiagonalStreak found in match matrix
            fingerprint_a: VideoFingerprint for first video
            fingerprint_b: VideoFingerprint for second video

        Returns:
            OverlapMatch with temporal boundaries and statistics
        """
        # Get temporal boundaries from frames
        end_idx_a = min(streak.start_a + streak.length - 1, len(fingerprint_a.frames) - 1)
        end_idx_b = min(streak.start_b + streak.length - 1, len(fingerprint_b.frames) - 1)

        start_time_a = fingerprint_a.frames[streak.start_a].timestamp
        end_time_a = fingerprint_a.frames[end_idx_a].timestamp
        start_time_b = fingerprint_b.frames[streak.start_b].timestamp
        end_time_b = fingerprint_b.frames[end_idx_b].timestamp

        overlap_duration_a = end_time_a - start_time_a
        overlap_duration_b = end_time_b - start_time_b

        # Use the average overlap duration
        overlap_duration = (overlap_duration_a + overlap_duration_b) / 2.0

        # Calculate overlap ratio relative to longer video
        longer_duration = max(fingerprint_a.duration, fingerprint_b.duration)
        overlap_ratio = overlap_duration / longer_duration if longer_duration > 0 else 0.0

        return OverlapMatch(
            video_a_path=fingerprint_a.path,
            video_b_path=fingerprint_b.path,
            overlap_duration=overlap_duration,
            overlap_ratio=overlap_ratio,
            start_a=start_time_a,
            end_a=end_time_a,
            start_b=start_time_b,
            end_b=end_time_b,
            matching_frames=streak.length
        )


def find_all_overlaps(
    fingerprints: List,
    index,
    min_overlap_ratio: float = 0.10,
    hamming_threshold: int = 12,
    min_streak_length: int = 5
) -> List[OverlapMatch]:
    """
    Find all partial overlaps among a collection of videos.

    Args:
        fingerprints: List of VideoFingerprint objects
        index: PHashIndex containing all fingerprints
        min_overlap_ratio: Minimum overlap ratio to report (default: 0.10 = 10%)
        hamming_threshold: Maximum Hamming distance for frame matches
        min_streak_length: Minimum consecutive frames for valid overlap

    Returns:
        List of OverlapMatch objects for all detected overlaps
    """
    matcher = SequenceMatcher(
        hamming_threshold=hamming_threshold,
        min_streak_length=min_streak_length
    )

    overlaps = []

    # Compare all pairs
    for i, fp_a in enumerate(fingerprints):
        for fp_b in fingerprints[i+1:]:
            overlap = matcher.find_overlap(fp_a, fp_b, index)

            if overlap and overlap.overlap_ratio >= min_overlap_ratio:
                overlaps.append(overlap)

    return overlaps
